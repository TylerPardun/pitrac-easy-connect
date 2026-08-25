"""Safe, journaled replacement of a packaged Easy-Connect installation."""

import hashlib
import json
import os
import platform
import plistlib
import posixpath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

try:
    import psutil
except ImportError:  # pragma: no cover - packaged builds include psutil
    psutil = None

APP_NAME = "PiTrac Easy-Connect"
APPLICATION_ID = "com.pitrac.easyconnect"
INSTALL_MANIFEST = "pitrac-install.json"
PACKAGE_LAYOUT_VERSION = 1
HELPER_NAME = "PiTrac Updater"
#: What --ping prints, so the reply cannot be confused with any other
#: output the process might produce.
HELPER_PING_REPLY = "pitrac-updater-ready"
VERSION_PROBE_TIMEOUT = 15.0
HELPER_PING_TIMEOUT = 20.0
HELPER_EXIT_TIMEOUT = 45.0
#: How long to wait for a restarted application to confirm itself. The
#: confirmation only fires once its window is on screen, which on a slow
#: machine means starting Python, a local server and a WebKit window from a
#: bundle written seconds earlier. Forty-five seconds was not enough on an
#: Intel Mac -- measured at about forty-eight. Waiting longer costs nothing
#: but a helper process that lives a little longer, and running out no
#: longer undoes the update anyway.
ACK_TIMEOUT = 300.0
DISK_MARGIN_BYTES = 64 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
PHASES = {
    "prepared", "waiting-for-old-app", "previous-moved", "current-promoted",
    "awaiting-restart-verification", "complete", "rolling-back", "rolled-back", "failed",
}


class SelfUpdateError(Exception):
    """The update contract or transaction is unsafe or invalid."""


@dataclass(frozen=True)
class InstalledApp:
    install_root: Path
    executable: Path
    manifest: Dict[str, Any]


def _default_state_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "pitrac-easy-connect"


def staging_dir(base: Optional[Path] = None) -> Path:
    if base is not None:
        return Path(base)
    override = os.environ.get("PITRAC_UPDATE_STATE_DIR")
    return Path(override) if override else _default_state_dir() / "updates"


def new_transaction_dir(base: Optional[Path] = None) -> Path:
    root = staging_dir(base)
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("transaction-" + uuid.uuid4().hex)
    path.mkdir(mode=0o700)
    return path


def _platform_name(system: Optional[str] = None) -> str:
    value = system or platform.system()
    try:
        return {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}[value]
    except KeyError:
        raise SelfUpdateError("unsupported update platform: {}".format(value))


def _architecture(machine: Optional[str] = None) -> str:
    value = str(machine or platform.machine()).lower()
    value = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(value, value)
    if value not in ("x86_64", "arm64"):
        raise SelfUpdateError("unsupported update architecture: {}".format(value))
    return value


def manifest_path(root: Path, *, system: Optional[str] = None) -> Path:
    if (system or platform.system()) == "Darwin":
        return Path(root) / "Contents" / "Resources" / INSTALL_MANIFEST
    return Path(root) / INSTALL_MANIFEST


def executable_path(root: Path, *, system: Optional[str] = None) -> Path:
    system = system or platform.system()
    if system == "Darwin":
        return Path(root) / "Contents" / "MacOS" / APP_NAME
    return Path(root) / (APP_NAME + (".exe" if system == "Windows" else ""))


def helper_path(root: Path, *, system: Optional[str] = None) -> Path:
    system = system or platform.system()
    name = HELPER_NAME + (".exe" if system == "Windows" else "")
    if system == "Darwin":
        return Path(root) / "Contents" / "Helpers" / name
    return Path(root) / name


def package_manifest(version: str, *, system: Optional[str] = None,
                     machine: Optional[str] = None) -> Dict[str, Any]:
    system = system or platform.system()
    root = Path(APP_NAME + ".app") if system == "Darwin" else Path(APP_NAME)
    return {
        "applicationId": APPLICATION_ID,
        "version": str(version).lstrip("v"),
        "platform": _platform_name(system),
        "architecture": _architecture(machine),
        "executable": executable_path(root, system=system).relative_to(root).as_posix(),
        "helper": helper_path(root, system=system).relative_to(root).as_posix(),
        "packageLayoutVersion": PACKAGE_LAYOUT_VERSION,
    }


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SelfUpdateError("could not read {}: {}".format(Path(path).name, exc))
    if not isinstance(value, dict):
        raise SelfUpdateError("{} is not a JSON object".format(Path(path).name))
    return value


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new-" + uuid.uuid4().hex)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short atomic write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(str(temporary), str(path))
    _fsync_dir(path.parent)


def write_package_manifest(root: Path, version: str, *, system: Optional[str] = None,
                           machine: Optional[str] = None) -> Path:
    path = manifest_path(root, system=system)
    _atomic_json(path, package_manifest(version, system=system, machine=machine))
    return path


def _canonical_digest(value: Dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("integritySha256", None)
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_journal(path: Path, journal: Dict[str, Any], phase: Optional[str] = None) -> None:
    value = dict(journal)
    if phase is not None:
        if phase not in PHASES:
            raise SelfUpdateError("invalid transaction phase")
        value["phase"] = phase
    value["updatedAt"] = time.time()
    value["integritySha256"] = _canonical_digest(value)
    _atomic_json(path, value)
    journal.clear()
    journal.update(value)


def _resolved(path: Path) -> Path:
    return Path(os.path.realpath(str(path)))


def _inside(path: Path, parent: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(parent))
        return True
    except ValueError:
        return False


def _reject_broad_root(root: Path, *, system: str) -> None:
    text = str(root)
    pure = PureWindowsPath(text) if system == "Windows" else PurePosixPath(text)
    if str(pure) in (str(pure.anchor), ".", "") or pure.parent == pure:
        raise SelfUpdateError("the filesystem or drive root cannot be replaced")
    if pure.name.lower() in ("desktop", "downloads", "documents"):
        raise SelfUpdateError("{} is a user folder, not an application install".format(pure.name))
    if system != "Windows":
        home = Path.home()
        protected = (home, home / "Desktop", home / "Downloads", home / "Documents", staging_dir())
        if any(_resolved(root) == _resolved(item) for item in protected):
            raise SelfUpdateError("that broad user or update-state directory cannot be replaced")


def current_install_root(*, system: Optional[str] = None,
                         executable: Optional[Path] = None) -> Path:
    system = system or platform.system()
    raw = str(executable) if executable is not None else sys.executable
    if system == "Windows":
        return Path(str(PureWindowsPath(raw).parent))
    exe = PurePosixPath(raw)
    if system == "Darwin" and len(exe.parents) >= 3:
        candidate = exe.parent.parent.parent
        if candidate.suffix == ".app":
            return Path(str(candidate))
    return Path(str(exe.parent))


def packaged_architecture(*, system: Optional[str] = None,
                          executable: Optional[Path] = None,
                          expected_version: Optional[str] = None) -> str:
    """Return the architecture declared by the package running this process.

    ``platform.machine()`` describes the native operating system on Windows
    ARM, even while the supported x86-64 package is running through Windows'
    compatibility layer. Asset selection must follow the installed package,
    because that is the executable the replacement has to match. This is a
    read-only identity check; strict install-root and helper checks still run
    immediately before any installation mutation.
    """

    system = system or platform.system()
    running = Path(executable) if executable is not None else Path(sys.executable)
    root = current_install_root(system=system, executable=running)
    manifest = _read_json(manifest_path(root, system=system))
    architecture = _architecture(str(manifest.get("architecture") or ""))
    expected = package_manifest(
        expected_version or str(manifest.get("version") or ""),
        system=system,
        machine=architecture,
    )
    for key in (
        "applicationId",
        "version",
        "platform",
        "architecture",
        "executable",
        "packageLayoutVersion",
    ):
        if str(manifest.get(key) or "") != str(expected.get(key) or ""):
            raise SelfUpdateError(
                "the running package manifest has the wrong {}".format(key)
            )
    expected_executable = executable_path(root, system=system)
    if _resolved(running) != _resolved(expected_executable):
        raise SelfUpdateError("the running executable does not match its package manifest")
    return architecture


def validate_install_root(root: Path, *, system: Optional[str] = None,
                          machine: Optional[str] = None,
                          expected_version: Optional[str] = None,
                          running_executable: Optional[Path] = None,
                          require_helper: bool = True,
                          allow_transaction_name: bool = False) -> InstalledApp:
    """Prove that ``root`` is the one replaceable application unit."""

    system = system or platform.system()
    root = Path(root)
    _reject_broad_root(root, system=system)
    expected_name = APP_NAME + (".app" if system == "Darwin" else "")
    if root.name != expected_name and not (
        allow_transaction_name and root.name.startswith(".pitrac-prepared-")
    ):
        raise SelfUpdateError("automatic replacement requires the dedicated {} install root".format(expected_name))
    if not root.is_dir():
        raise SelfUpdateError("the application install root does not exist")
    manifest = _read_json(manifest_path(root, system=system))
    expected = package_manifest(expected_version or manifest.get("version", ""),
                                system=system, machine=machine)
    for key in ("applicationId", "platform", "architecture", "executable", "helper",
                "packageLayoutVersion"):
        if manifest.get(key) != expected.get(key):
            raise SelfUpdateError("the install manifest has the wrong {}".format(key))
    version = str(manifest.get("version") or "")
    if not version or (expected_version and version.lstrip("v") != str(expected_version).lstrip("v")):
        raise SelfUpdateError("the install manifest has the wrong version")
    executable = executable_path(root, system=system)
    if not executable.is_file() or not _inside(executable, root):
        raise SelfUpdateError("the expected application executable is missing or outside its root")
    if system != "Windows" and not os.access(str(executable), os.X_OK):
        raise SelfUpdateError("the application executable is not executable")
    if running_executable is not None and _resolved(running_executable) != _resolved(executable):
        raise SelfUpdateError("the running executable is not the dedicated install executable")
    helper = helper_path(root, system=system)
    if require_helper and (not helper.is_file() or not _inside(helper, root)):
        raise SelfUpdateError("the dedicated updater helper is missing")
    if require_helper and system != "Windows" and not os.access(str(helper), os.X_OK):
        raise SelfUpdateError("the updater helper is not executable")
    if system == "Darwin":
        try:
            with open(root / "Contents" / "Info.plist", "rb") as handle:
                plist = plistlib.load(handle)
        except (OSError, ValueError, plistlib.InvalidFileException) as exc:
            raise SelfUpdateError("the application bundle has no valid Info.plist: {}".format(exc))
        if plist.get("CFBundleIdentifier") != APPLICATION_ID:
            raise SelfUpdateError("the application bundle identifier is wrong")
        if str(plist.get("CFBundleShortVersionString") or "") != version:
            raise SelfUpdateError("the application bundle version does not match its manifest")
    return InstalledApp(root, executable, manifest)


def _zip_member_name(raw: str) -> PurePosixPath:
    if not raw or "\\" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise SelfUpdateError("the package contains an unsafe path: {}".format(raw))
    path = PurePosixPath(raw.rstrip("/"))
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise SelfUpdateError("the package contains an unsafe path: {}".format(raw))
    return path


def _validated_members(archive: zipfile.ZipFile, *, system: str) -> Iterable[Tuple[zipfile.ZipInfo, PurePosixPath, int, Optional[str]]]:
    seen, symlinks, values = set(), set(), []
    for info in archive.infolist():
        member = _zip_member_name(info.filename)
        key = str(member)
        if key in seen:
            raise SelfUpdateError("the package contains a duplicate path: {}".format(key))
        seen.add(key)
        mode = (info.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(mode) if mode else (stat.S_IFDIR if info.is_dir() else stat.S_IFREG)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK):
            raise SelfUpdateError("the package contains a device, hard link, or special file")
        link_target = None
        if kind == stat.S_IFLNK:
            if system != "Darwin":
                raise SelfUpdateError("links are permitted only inside the macOS application bundle")
            try:
                link_target = archive.read(info).decode("utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                raise SelfUpdateError("the package contains an unreadable link: {}".format(exc))
            if not link_target or link_target.startswith("/") or re.match(r"^[A-Za-z]:", link_target):
                raise SelfUpdateError("the package contains an absolute link")
            # ZIP paths are POSIX paths on every host. os.path.normpath uses
            # backslashes on Windows and would misclassify a valid macOS
            # in-bundle link when CI inspects that archive there.
            target = PurePosixPath(posixpath.normpath(str(member.parent / link_target)))
            app = APP_NAME + ".app"
            try:
                app_index = member.parts.index(app)
            except ValueError:
                raise SelfUpdateError("the package link is outside the application bundle")
            bundle_prefix = member.parts[:app_index + 1]
            if (target.parts[:app_index + 1] != bundle_prefix or
                    len(target.parts) <= app_index or ".." in target.parts):
                raise SelfUpdateError("the package link escapes the application bundle")
            symlinks.add(key)
        values.append((info, member, mode, link_target))
    for _info, member, _mode, _target in values:
        if any(str(parent) in symlinks for parent in list(member.parents)[:-1]):
            raise SelfUpdateError("the package writes through a symbolic link")
    return values


def _remove_tree(path: Path, *, allowed_parent: Path) -> None:
    candidate = Path(path)
    if not candidate.exists() and not candidate.is_symlink():
        return
    if _resolved(candidate.parent) != _resolved(allowed_parent) or candidate == allowed_parent:
        raise SelfUpdateError("refused unsafe cleanup path: {}".format(candidate))
    if candidate.is_symlink() or candidate.is_file():
        candidate.unlink()
    else:
        shutil.rmtree(candidate)


def extract_safely(archive_path: Path, dest_dir: Path, *,
                   system: Optional[str] = None) -> Path:
    """Validate all ZIP members before extracting into a fresh directory."""

    system = system or platform.system()
    destination = Path(dest_dir)
    if destination.exists() and any(destination.iterdir()):
        raise SelfUpdateError("the extraction directory is not empty")
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad = archive.testzip()
            if bad:
                raise SelfUpdateError("the package is damaged at {}".format(bad))
            members = list(_validated_members(archive, system=system))
            for info, member, mode, link_target in members:
                target = destination.joinpath(*member.parts)
                if not _inside(target.parent, destination):
                    raise SelfUpdateError("the package tried to write outside staging")
                if info.is_dir() or stat.S_ISDIR(mode):
                    target.mkdir(parents=True, exist_ok=True)
                elif link_target is None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, open(target, "xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    if mode:
                        os.chmod(target, stat.S_IMODE(mode) or 0o644)
            for _info, member, _mode, link_target in members:
                if link_target is not None:
                    target = destination.joinpath(*member.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(link_target, target)
    except Exception:
        _remove_tree(destination, allowed_parent=destination.parent)
        raise
    return destination


def validate_archive_layout(extracted: Path, *, system: Optional[str] = None) -> Path:
    system = system or platform.system()
    roots = {entry.name for entry in Path(extracted).iterdir()}
    legal = {"LICENSE", "NOTICE.md", "THIRD-PARTY-LICENCES.txt"}
    if system == "Darwin":
        app_name = APP_NAME + ".app"
        if roots != legal | {app_name}:
            raise SelfUpdateError("the macOS package must contain one application bundle and three legal files")
        return Path(extracted) / app_name
    if roots != {APP_NAME}:
        raise SelfUpdateError("the Windows/Linux package must contain one dedicated top-level directory")
    root = Path(extracted) / APP_NAME
    if not legal.issubset({entry.name for entry in root.iterdir()}):
        raise SelfUpdateError("the package is missing required legal files")
    return root


def _probe_version(executable: Path, timeout: float = VERSION_PROBE_TIMEOUT) -> str:
    # A Windows PyInstaller windowed executable has no stdout, so `--version`
    # is not a portable process-level probe. Use a unique, tightly constrained
    # result file in update state instead.
    probe_state = Path(tempfile.mkdtemp(prefix="pitrac-version-probe-"))
    probe_root = probe_state / "probes"
    probe_root.mkdir(parents=True, exist_ok=True)
    output = probe_root / ("version-probe-" + uuid.uuid4().hex + ".json")
    try:
        environment = os.environ.copy()
        environment["PITRAC_UPDATE_STATE_DIR"] = str(probe_state)
        result = subprocess.run(
            [str(executable), "--version-probe-output", str(output)],
            capture_output=True, text=True, timeout=timeout, check=False,
            env=environment,
        )
        if result.returncode:
            raise SelfUpdateError("the staged application exited {}".format(result.returncode))
        value = _read_json(output)
        if value.get("applicationId") != APPLICATION_ID:
            raise SelfUpdateError("the staged application returned the wrong identity")
        return str(value.get("version") or "")
    finally:
        shutil.rmtree(probe_state, ignore_errors=True)


def write_version_probe(output: Path, version: str) -> None:
    """Write a frozen-app version result only inside the dedicated probe dir."""

    path = Path(output)
    probe_root = staging_dir() / "probes"
    if (_resolved(path.parent) != _resolved(probe_root) or
            not re.fullmatch(r"version-probe-[0-9a-f]{32}\.json", path.name)):
        raise SelfUpdateError("the version probe output path is unsafe")
    probe_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, {"applicationId": APPLICATION_ID,
                        "version": str(version).lstrip("v"), "at": time.time()})


def validate_structure(extracted_dir: Path, expected_version: Optional[str], *,
                       system: Optional[str] = None, machine: Optional[str] = None,
                       probe: Optional[Callable[[Path], str]] = None) -> InstalledApp:
    system = system or platform.system()
    root = validate_archive_layout(extracted_dir, system=system)
    app = validate_install_root(root, system=system, machine=machine,
                                expected_version=expected_version)
    if expected_version is not None:
        try:
            reported = (probe or _probe_version)(app.executable)
        except Exception as exc:
            raise SelfUpdateError("that version would not run on this computer: {}".format(exc))
        if str(reported).lstrip("v") != str(expected_version).lstrip("v"):
            raise SelfUpdateError("the package reports version {} but expected {}".format(
                reported or "nothing", expected_version))
    return app


def stage_update(archive_path: Path, transaction_root: Path, expected_version: str, *,
                 system: Optional[str] = None, machine: Optional[str] = None,
                 probe: Optional[Callable[[Path], str]] = None) -> InstalledApp:
    extracted = extract_safely(archive_path, Path(transaction_root) / "extracted", system=system)
    return validate_structure(extracted, expected_version, system=system, machine=machine,
                              probe=probe)


def _tree_size(path: Path) -> int:
    total = 0
    for parent, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            candidate = Path(parent) / name
            try:
                if not candidate.is_symlink():
                    total += candidate.stat().st_size
            except OSError:
                pass
    return total


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(value: str) -> str:
    if not SHA256_RE.fullmatch(str(value or "")):
        raise SelfUpdateError("the release SHA-256 is missing or malformed")
    return str(value).lower()


def _preflight_parent(parent: Path, transaction_id: str) -> None:
    first = parent / (".pitrac-write-test-" + transaction_id)
    second = parent / (first.name + "-renamed")
    try:
        with open(first, "xb") as handle:
            handle.write(b"safe")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(first, second)
        second.unlink()
    except OSError as exc:
        for item in (first, second):
            try:
                item.unlink()
            except OSError:
                pass
        raise SelfUpdateError("the application folder is not safely writable: {}".format(exc))


def _fsync_tree(root: Path) -> None:
    for parent, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(parent) / name
            if path.is_symlink():
                continue
            try:
                descriptor = os.open(str(path), os.O_RDONLY)
                os.fsync(descriptor)
                os.close(descriptor)
            except OSError:
                pass
        _fsync_dir(Path(parent))


def prepare_transaction(*, archive_path: Path, staged: InstalledApp, install_root: Path,
                        installed_version: str, target_version: str, expected_tag: str,
                        asset_name: str, asset_sha256: str, transaction_root: Path,
                        system: Optional[str] = None, machine: Optional[str] = None,
                        running_executable: Optional[Path] = None,
                        relaunch_arguments: Optional[list] = None) -> Path:
    """Preflight and materialise the complete same-filesystem transaction."""

    system = system or platform.system()
    architecture = _architecture(machine)
    target = str(target_version).lstrip("v")
    if str(expected_tag) != "v" + target:
        raise SelfUpdateError("the release tag and target version do not match")
    digest = validate_sha256(asset_sha256)
    archive = Path(archive_path)
    if _hash_file(archive) != digest:
        raise SelfUpdateError("the archive no longer matches its release SHA-256")
    current = validate_install_root(install_root, system=system, machine=architecture,
                                    expected_version=installed_version,
                                    running_executable=running_executable)
    validate_install_root(staged.install_root, system=system, machine=architecture,
                          expected_version=target)
    tx_root = _resolved(transaction_root)
    state_root = _resolved(staging_dir())
    if not _inside(tx_root, state_root):
        raise SelfUpdateError("the transaction is outside the update-state directory")
    transaction_id = tx_root.name.removeprefix("transaction-")
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise SelfUpdateError("the transaction directory name is invalid")
    parent = current.install_root.parent
    _preflight_parent(parent, transaction_id)
    prepared = parent / (".pitrac-prepared-" + transaction_id)
    previous = parent / (".pitrac-previous-" + transaction_id)
    broken = parent / (".pitrac-broken-" + transaction_id)
    if any(item.exists() for item in (prepared, previous, broken)):
        raise SelfUpdateError("a transaction sibling is already occupied")
    required = archive.stat().st_size + _tree_size(staged.install_root) + _tree_size(current.install_root) + DISK_MARGIN_BYTES
    free = shutil.disk_usage(parent).free
    if free < required:
        raise SelfUpdateError("not enough disk space ({} bytes required, {} available)".format(required, free))
    try:
        shutil.copytree(staged.install_root, prepared, symlinks=True, copy_function=shutil.copy2)
        validate_install_root(prepared, system=system, machine=architecture,
                              expected_version=target, allow_transaction_name=True)
        _fsync_tree(prepared)
    except Exception:
        _remove_tree(prepared, allowed_parent=parent)
        raise
    helper_source = helper_path(current.install_root, system=system)
    helper_dir = state_root / "helpers" / transaction_id
    helper_dir.mkdir(parents=True, exist_ok=False)
    independent = helper_dir / helper_source.name
    try:
        shutil.copy2(helper_source, independent)
        if system != "Windows":
            independent.chmod(independent.stat().st_mode | stat.S_IXUSR)
        if not independent.is_file() or (system != "Windows" and not os.access(str(independent), os.X_OK)):
            raise SelfUpdateError("the independent updater helper is missing or not executable")
        # Only for a packaged build. The risk this covers -- a binary copied
        # out of an unsigned bundle that satisfies is_file() and the executable
        # bit and still refuses to start -- belongs to the frozen application.
        # Running from source the helper is a script, which is not started this
        # way in production and is not a .exe Windows can execute at all.
        if getattr(sys, "frozen", False):
            _prove_helper_runs(independent)
    except Exception:
        _remove_tree(helper_dir, allowed_parent=helper_dir.parent)
        _remove_tree(prepared, allowed_parent=parent)
        raise
    if any(_inside(independent, item) for item in (current.install_root, staged.install_root, prepared)):
        raise SelfUpdateError("the updater helper is not independent")
    journal_path = tx_root / "journal.json"
    journal = {
        "transactionId": transaction_id, "applicationId": APPLICATION_ID,
        "installedVersion": str(installed_version).lstrip("v"), "targetVersion": target,
        "expectedReleaseTag": str(expected_tag), "platform": _platform_name(system),
        "architecture": architecture, "assetName": str(asset_name), "assetSha256": digest,
        "downloadedArchivePath": str(_resolved(archive)),
        "stagingPath": str(_resolved(staged.install_root)),
        "preparedSiblingPath": str(_resolved(prepared)), "installRoot": str(_resolved(current.install_root)),
        "previousInstallPath": str(_resolved(previous)), "brokenInstallPath": str(_resolved(broken)),
        "resultFilePath": str(_resolved(tx_root / "result.json")),
        "restartAcknowledgementPath": str(_resolved(tx_root / "restart-ack.json")),
        "helperPath": str(_resolved(independent)), "restartToken": secrets.token_urlsafe(32),
        "relaunchArguments": [str(value) for value in (relaunch_arguments or [])],
        "phase": "prepared", "createdAt": time.time(), "updatedAt": time.time(),
    }
    _write_journal(journal_path, journal)
    return journal_path


def _prove_helper_runs(helper: Path, timeout: float = HELPER_PING_TIMEOUT) -> None:
    """Start the copied helper and require it to answer.

    The application shuts itself down so this helper can replace it. If the
    copy cannot start, nothing performs the update and nothing writes a
    result -- the user is left on the old version with no explanation, which
    is the least debuggable outcome available.
    """

    try:
        done = subprocess.run([str(helper), "--ping"], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SelfUpdateError(
            "the independent updater helper would not start: {}".format(exc)
        ) from exc
    if done.returncode != 0 or HELPER_PING_REPLY not in (done.stdout or ""):
        raise SelfUpdateError(
            "the independent updater helper did not answer when started"
        )


def load_journal(path: Path) -> Dict[str, Any]:
    journal_path = _resolved(path)
    state_root = _resolved(staging_dir())
    if not _inside(journal_path, state_root) or journal_path.name != "journal.json":
        raise SelfUpdateError("the journal path is outside update state")
    journal = _read_json(journal_path)
    if not secrets.compare_digest(str(journal.get("integritySha256") or ""),
                                  _canonical_digest(journal)):
        raise SelfUpdateError("the transaction journal integrity check failed")
    required = {"transactionId", "applicationId", "installedVersion", "targetVersion",
                "expectedReleaseTag", "platform", "architecture", "assetName", "assetSha256",
                "downloadedArchivePath", "stagingPath", "preparedSiblingPath", "installRoot",
                "previousInstallPath", "brokenInstallPath", "resultFilePath",
                "restartAcknowledgementPath", "helperPath",
                "restartToken", "relaunchArguments", "phase"}
    if required.difference(journal):
        raise SelfUpdateError("the transaction journal is incomplete")
    if journal["applicationId"] != APPLICATION_ID or journal["phase"] not in PHASES:
        raise SelfUpdateError("the transaction journal identifies the wrong application or phase")
    validate_sha256(journal["assetSha256"])
    if journal["expectedReleaseTag"] != "v" + str(journal["targetVersion"]):
        raise SelfUpdateError("the journal tag and target do not match")
    relaunch = journal["relaunchArguments"]
    valued_flags = {"--port", "--gspro-port", "--e6-port", "--simulator-host",
                    "--discovery-port", "--config", "--computer-name"}
    boolean_flags = {"--headless"}
    valid_relaunch = isinstance(relaunch, list) and len(relaunch) <= 15
    index = 0
    while valid_relaunch and index < len(relaunch):
        flag = relaunch[index]
        if not isinstance(flag, str) or "\x00" in flag:
            valid_relaunch = False
            break
        if flag in boolean_flags:
            index += 1
            continue
        if flag not in valued_flags or index + 1 >= len(relaunch):
            valid_relaunch = False
            break
        value = relaunch[index + 1]
        if not isinstance(value, str) or "\x00" in value or value.startswith("--"):
            valid_relaunch = False
            break
        index += 2
    if not valid_relaunch:
        raise SelfUpdateError("the journal relaunch arguments are invalid")
    transaction_root = journal_path.parent
    for key in ("downloadedArchivePath", "stagingPath", "resultFilePath",
                "restartAcknowledgementPath"):
        if not _inside(Path(journal[key]), transaction_root):
            raise SelfUpdateError("the journal contains an unsafe {}".format(key))
    system = {"macos": "Darwin", "windows": "Windows", "linux": "Linux"}.get(journal["platform"])
    if not system:
        raise SelfUpdateError("the journal platform is invalid")
    install = Path(journal["installRoot"])
    _reject_broad_root(install, system=system)
    if install.name != APP_NAME + (".app" if system == "Darwin" else ""):
        raise SelfUpdateError("the journal install root is not dedicated")
    parent, txid = _resolved(install.parent), journal["transactionId"]
    for key, name in (("preparedSiblingPath", ".pitrac-prepared-" + txid),
                      ("previousInstallPath", ".pitrac-previous-" + txid),
                      ("brokenInstallPath", ".pitrac-broken-" + txid)):
        candidate = Path(journal[key])
        if _resolved(candidate.parent) != parent or candidate.name != name:
            raise SelfUpdateError("the journal contains an unsafe {}".format(key))
    if journal_path.parent.name != "transaction-" + txid:
        raise SelfUpdateError("the journal transaction ID and directory differ")
    if _resolved(journal["resultFilePath"]) != _resolved(transaction_root / "result.json"):
        raise SelfUpdateError("the journal result path is not exact")
    if _resolved(journal["restartAcknowledgementPath"]) != _resolved(transaction_root / "restart-ack.json"):
        raise SelfUpdateError("the journal acknowledgement path is not exact")
    expected_helper_dir = state_root / "helpers" / txid
    if _resolved(Path(journal["helperPath"]).parent) != _resolved(expected_helper_dir):
        raise SelfUpdateError("the journal helper path is not independent and exact")
    expected_assets = {
        ("macos", "arm64"): "PiTrac-Easy-Connect-macos-apple-silicon.zip",
        ("macos", "x86_64"): "PiTrac-Easy-Connect-macos-intel.zip",
        ("windows", "x86_64"): "PiTrac-Easy-Connect-windows.zip",
        ("linux", "x86_64"): "PiTrac-Easy-Connect-linux-x86_64.zip",
    }
    if journal["assetName"] != expected_assets.get((journal["platform"], journal["architecture"])):
        raise SelfUpdateError("the journal asset does not match its platform and architecture")
    return journal


def _launched_still_running(launched: Any, pid: int) -> bool:
    """Whether the application this helper started is still going.

    The helper created the process, so its own handle is the authority:
    ``poll()`` distinguishes "still running" from "exited" exactly, without
    needing psutil. The tree check below cannot, because when psutil is absent
    it falls back to ``os.kill(pid, 0)``, and that succeeds for a process which
    has exited but not yet been reaped -- the helper never reaps, so every
    dead child looks alive to it.

    That mattered: keeping an update depends on the application still running,
    and a zombie reported as alive would keep an update whose application had
    actually died. It passed on a machine with psutil installed and failed on
    CI, which has none.
    """

    poll = getattr(launched, "poll", None)
    if callable(poll):
        try:
            return poll() is None
        except Exception:            # pragma: no cover - defensive
            pass
    return bool(pid) and _process_tree_alive(pid, set())


def _process_tree_alive(root_pid: int, known: set, ignored: Optional[set] = None) -> bool:
    ignored = ignored or set()
    if psutil is not None:
        try:
            root = psutil.Process(root_pid)
            if root_pid not in ignored:
                known.add(root_pid)
            known.update(
                child.pid for child in root.children(recursive=True)
                if child.pid not in ignored
            )
        except Exception:
            pass
        alive = False
        for pid in tuple(known):
            if pid in ignored:
                known.discard(pid)
                continue
            try:
                process = psutil.Process(pid)
                if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                    alive = True
                else:
                    known.discard(pid)
            except Exception:
                known.discard(pid)
        return alive
    try:
        os.kill(root_pid, 0)
        return True
    except OSError:
        return False


def _independent_helper_processes(helper_path_value: Path) -> set:
    """The helper's own PyInstaller chain, which is not part of the old app.

    Windows keeps the new helper parented under the process that launched it
    even when it has a separate process group. A one-file helper may also have
    an outer bootloader and inner Python process. Both execute from the exact
    independent helper path and must be excluded from the old-app tree wait,
    or the helper waits for itself forever.
    """

    ignored = {os.getpid()}
    if psutil is None:
        return ignored
    expected = _resolved(helper_path_value)
    try:
        process = psutil.Process(os.getpid())
        while True:
            parent = process.parent()
            if parent is None or _resolved(parent.exe()) != expected:
                break
            ignored.add(parent.pid)
            process = parent
    except Exception:
        pass
    return ignored


def _terminate_process_tree(pid: int) -> None:
    if psutil is None:
        return
    try:
        root = psutil.Process(pid)
        processes = root.children(recursive=True) + [root]
    except Exception:
        return
    for process in reversed(processes):
        try:
            process.terminate()
        except Exception:
            pass
    _gone, alive = psutil.wait_procs(processes, timeout=5)
    for process in alive:
        try:
            process.kill()
        except Exception:
            pass
    if alive:
        # A killed Windows PyInstaller/WebView2 process can retain image or
        # directory handles briefly. Do not begin rollback until the kernel
        # has actually reaped the processes we had to kill.
        try:
            psutil.wait_procs(alive, timeout=5)
        except Exception:
            pass


def _replace_transaction_path(source: Path, destination: Path, *, timeout: float = 10) -> None:
    """Atomically rename an exact transaction path, tolerating brief Windows locks."""

    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(str(source), str(destination))
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def _write_result(journal: Dict[str, Any], success: bool, detail: str,
                  *, rolled_back: bool = False) -> None:
    value = {"transactionId": journal["transactionId"], "success": bool(success),
             "rolledBack": bool(rolled_back), "installedVersion": journal["installedVersion"],
             "targetVersion": journal["targetVersion"], "detail": str(detail), "at": time.time()}
    _atomic_json(Path(journal["resultFilePath"]), value)
    _atomic_json(staging_dir() / "last-install-result.json", value)


def _system_from_journal(journal: Dict[str, Any]) -> str:
    return {"macos": "Darwin", "windows": "Windows", "linux": "Linux"}[journal["platform"]]


def _spawn_detached(arguments: list) -> subprocess.Popen:
    kwargs: Dict[str, Any] = {"close_fds": True}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:  # pragma: no cover - Windows CI
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(arguments, **kwargs)


def _launch_args(journal_path: Path, journal: Dict[str, Any], executable: Path) -> list:
    return [str(executable), "--post-update-journal", str(journal_path),
            "--post-update-token", str(journal["restartToken"]),
            "--post-update-helper-pid", str(os.getpid()),
            "--post-update-helper-path", str(journal["helperPath"]),
            *journal.get("relaunchArguments", [])]


def run_helper(journal_path: Path, wait_pid: int, *, timeout: float = HELPER_EXIT_TIMEOUT,
               ack_timeout: float = ACK_TIMEOUT,
               process_tree_alive: Optional[Callable[[int, set], bool]] = None,
               launcher: Optional[Callable[[list], Any]] = None) -> int:
    """Perform promotion and keep the previous version until exact acknowledgement."""

    journal_path = _resolved(journal_path)
    try:
        journal = load_journal(journal_path)
    except Exception:
        return 2
    system = _system_from_journal(journal)
    install = Path(journal["installRoot"])
    prepared = Path(journal["preparedSiblingPath"])
    previous = Path(journal["previousInstallPath"])
    broken = Path(journal.get("brokenInstallPath") or install.parent / (".pitrac-broken-" + journal["transactionId"]))
    if process_tree_alive is not None:
        alive = process_tree_alive
    else:
        ignored_helper_processes = _independent_helper_processes(Path(journal["helperPath"]))
        alive = lambda pid, known: _process_tree_alive(pid, known, ignored_helper_processes)
    try:
        if getattr(sys, "frozen", False) and _resolved(sys.executable) != _resolved(journal["helperPath"]):
            raise SelfUpdateError("the updater is not running from its independent helper path")
        _write_journal(journal_path, journal, "waiting-for-old-app")
        known, deadline = set(), time.monotonic() + timeout
        while alive(wait_pid, known) and time.monotonic() < deadline:
            time.sleep(0.2)
        if alive(wait_pid, known):
            raise SelfUpdateError("the previous application process tree did not close")
        journal = load_journal(journal_path)
        if _hash_file(Path(journal["downloadedArchivePath"])) != journal["assetSha256"]:
            raise SelfUpdateError("the archive changed after verification")
        validate_install_root(install, system=system, machine=journal["architecture"],
                              expected_version=journal["installedVersion"])
        validate_install_root(prepared, system=system, machine=journal["architecture"],
                              expected_version=journal["targetVersion"], allow_transaction_name=True)
        if previous.exists():
            raise SelfUpdateError("the recovery path is already occupied")
        _replace_transaction_path(install, previous)
        _fsync_dir(install.parent)
        _write_journal(journal_path, journal, "previous-moved")
        _replace_transaction_path(prepared, install)
        _fsync_dir(install.parent)
        _write_journal(journal_path, journal, "current-promoted")
        new_app = validate_install_root(install, system=system, machine=journal["architecture"],
                                        expected_version=journal["targetVersion"])
        launched = (launcher or _spawn_detached)(_launch_args(journal_path, journal, new_app.executable))
        journal["launchedPid"] = int(getattr(launched, "pid", 0) or 0)
        _write_journal(journal_path, journal, "awaiting-restart-verification")
        ack_path, deadline, acknowledged = Path(journal["restartAcknowledgementPath"]), time.monotonic() + ack_timeout, False
        launched_pid, still_running = int(journal.get("launchedPid") or 0), True
        while time.monotonic() < deadline:
            if ack_path.exists():
                try:
                    ack = _read_json(ack_path)
                    acknowledged = (secrets.compare_digest(str(ack.get("token") or ""), str(journal["restartToken"]))
                                    and str(ack.get("version") or "") == journal["targetVersion"]
                                    and _resolved(ack.get("executable", "")) == _resolved(new_app.executable))
                except Exception:
                    acknowledged = False
                if acknowledged:
                    break
            if not _launched_still_running(launched, launched_pid):
                still_running = False
                break
            time.sleep(0.2)
        if not acknowledged:
            # Two very different things used to end up here. An application
            # that started and then died is a failed update and must be undone.
            # An application that is still running and simply has not confirmed
            # itself yet is a *successful* update on a slow machine, and undoing
            # it is the worse outcome by far: the user watches the new version
            # start, then finds the old one back with nothing said about why.
            #
            # That is what happened in the field. The confirmation only fires
            # once the window is on screen, and on an Intel Mac the first launch
            # of a freshly written bundle took about forty-eight seconds against
            # a forty-five second deadline. The rollback then restored a version
            # which missed the same deadline by two and a half seconds.
            if not still_running:
                raise SelfUpdateError("the new application did not acknowledge its exact path and version")
            _write_journal(journal_path, journal, "complete")
            _write_result(
                journal, True,
                "Updated to {}. It started but had not confirmed itself after {:.0f} seconds, "
                "so the previous version was kept at {} rather than the update being undone."
                .format(journal["targetVersion"], ack_timeout, previous),
            )
            return 0
        _remove_tree(previous, allowed_parent=install.parent)
        _write_journal(journal_path, journal, "complete")
        _write_result(journal, True, "Updated to {} and verified after restart.".format(journal["targetVersion"]))
        return 0
    except Exception as exc:
        try:
            journal = load_journal(journal_path)
        except Exception:
            return 2
        if journal.get("phase") in ("previous-moved", "current-promoted", "awaiting-restart-verification") or previous.exists():
            try:
                _write_journal(journal_path, journal, "rolling-back")
                if journal.get("launchedPid"):
                    _terminate_process_tree(int(journal["launchedPid"]))
                if install.exists():
                    if broken.exists():
                        _remove_tree(broken, allowed_parent=install.parent)
                    _replace_transaction_path(install, broken)
                if previous.exists():
                    _replace_transaction_path(previous, install)
                _fsync_dir(install.parent)
                old = validate_install_root(install, system=system, machine=journal["architecture"],
                                            expected_version=journal["installedVersion"])
                ack_path = Path(journal["restartAcknowledgementPath"])
                try:
                    ack_path.unlink()
                except OSError:
                    pass
                old_process = _spawn_detached(_launch_args(journal_path, journal, old.executable))
                journal["rollbackPid"] = int(old_process.pid)
                _write_journal(journal_path, journal, "rolling-back")
                rollback_deadline = time.monotonic() + ack_timeout
                rollback_acknowledged = False
                while time.monotonic() < rollback_deadline:
                    if ack_path.exists():
                        try:
                            ack = _read_json(ack_path)
                            rollback_acknowledged = (
                                secrets.compare_digest(str(ack.get("token") or ""), str(journal["restartToken"]))
                                and str(ack.get("version") or "") == journal["installedVersion"]
                                and _resolved(ack.get("executable", "")) == _resolved(old.executable)
                            )
                        except Exception:
                            rollback_acknowledged = False
                        if rollback_acknowledged:
                            break
                    if not _process_tree_alive(int(old_process.pid), set()):
                        break
                    time.sleep(0.2)
                if rollback_acknowledged and broken.exists():
                    _remove_tree(broken, allowed_parent=install.parent)
                _write_journal(journal_path, journal, "rolled-back")
                detail = "The update failed and the previous working version was restored: {}".format(exc)
                if not rollback_acknowledged:
                    detail += " The restored application did not acknowledge its relaunch automatically."
                _write_result(journal, False, detail, rolled_back=True)
                return 1
            except Exception as rollback_exc:
                _write_result(journal, False, "The update failed and rollback also failed: {}; {}".format(exc, rollback_exc))
                return 2
        _write_journal(journal_path, journal, "failed")
        _write_result(journal, False, "Nothing was changed: {}".format(exc))
        return 1


def spawn_helper(journal_path: Path, *, wait_pid: Optional[int] = None) -> subprocess.Popen:
    journal = load_journal(journal_path)
    helper = Path(journal["helperPath"])
    if not helper.is_file():
        raise SelfUpdateError("the independent updater helper is missing")
    return _spawn_detached([str(helper), "--journal", str(journal_path),
                            "--wait-pid", str(wait_pid or os.getpid())])


def validate_restart(journal_path: Path, token: str, *, version: str,
                     executable: Optional[Path] = None) -> Tuple[Dict[str, Any], Path]:
    """Validate the restart proof without claiming the app is usable yet."""

    journal = load_journal(journal_path)
    if journal["phase"] not in ("current-promoted", "awaiting-restart-verification",
                                "rolling-back", "rolled-back"):
        raise SelfUpdateError("the transaction is not awaiting acknowledgement")
    if not secrets.compare_digest(str(token), str(journal["restartToken"])):
        raise SelfUpdateError("the restart acknowledgement token is invalid")
    expected_version = (journal["targetVersion"] if journal["phase"] in
                        ("current-promoted", "awaiting-restart-verification") else journal["installedVersion"])
    if str(version).lstrip("v") != expected_version:
        raise SelfUpdateError("the restarted application reports the wrong version")
    expected_executable = executable_path(Path(journal["installRoot"]),
                                          system=_system_from_journal(journal))
    actual = Path(executable or sys.executable)
    if _resolved(actual) != _resolved(expected_executable):
        raise SelfUpdateError("the restarted executable is not at the final install path")
    return journal, actual


def acknowledge_restart(journal_path: Path, token: str, *, version: str,
                        executable: Optional[Path] = None) -> None:
    journal, actual = validate_restart(
        journal_path, token, version=version, executable=executable
    )
    _atomic_json(Path(journal["restartAcknowledgementPath"]),
                 {"transactionId": journal["transactionId"], "token": str(token),
                  "version": str(version).lstrip("v"), "executable": str(_resolved(actual)),
                  "at": time.time()})


def cleanup_independent_helper(helper_pid: int, helper_file: Path) -> None:
    """Delete the independent helper after it exits (needed on Windows)."""
    helper = _resolved(helper_file)
    helpers_root = _resolved(staging_dir() / "helpers")
    if not _inside(helper, helpers_root) or helper.parent.parent != helpers_root:
        return
    def work() -> None:
        deadline = time.monotonic() + 120
        while _process_tree_alive(int(helper_pid), set()) and time.monotonic() < deadline:
            time.sleep(0.25)
        # Windows's one-file outer bootloader can retain the helper executable
        # briefly after its inner process exits. Retry the narrowly validated
        # helper directory instead of swallowing that first sharing violation
        # and leaking the helper forever.
        cleanup_deadline = time.monotonic() + 120
        while time.monotonic() < cleanup_deadline:
            try:
                _remove_tree(helper.parent, allowed_parent=helpers_root)
                return
            except Exception:
                time.sleep(0.25)
    threading.Thread(target=work, daemon=True).start()


def recover_pending_restart(*, version: str, executable: Optional[Path] = None) -> bool:
    """Acknowledge a promoted or restored install after an interrupted launch.

    Journals are the authority; this never derives a destination or performs a
    rename. It only completes the same narrow path/version proof the helper's
    explicit restart arguments normally request.
    """
    actual = Path(executable or sys.executable)
    root = staging_dir()
    if not root.is_dir():
        return False
    for path in sorted(root.glob("transaction-*/journal.json"), reverse=True):
        try:
            journal = load_journal(path)
            if journal["phase"] not in (
                "current-promoted", "awaiting-restart-verification",
                "rolling-back", "rolled-back",
            ):
                continue
            expected = executable_path(Path(journal["installRoot"]),
                                       system=_system_from_journal(journal))
            if _resolved(actual) != _resolved(expected):
                continue
            acknowledge_restart(path, journal["restartToken"], version=version,
                                executable=actual)
            return True
        except Exception:
            continue
    return False


def read_and_clear_last_result(base: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = staging_dir(base) / "last-install-result.json"
    if not path.exists():
        return None
    try:
        value = _read_json(path)
    except SelfUpdateError:
        value = None
    try:
        path.unlink()
    except OSError:
        pass
    return value


def prune_transactions(base: Optional[Path] = None, keep: int = 3) -> None:
    root = staging_dir(base)
    if not root.is_dir():
        return
    completed = []
    for path in root.glob("transaction-*"):
        try:
            if load_journal(path / "journal.json")["phase"] in ("complete", "failed", "rolled-back"):
                completed.append(path)
        except Exception:
            continue
    completed.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    for path in completed[keep:]:
        _remove_tree(path, allowed_parent=root)


def clean_transaction(path: Path) -> None:
    """Remove one incomplete transaction, and never any broader directory."""
    candidate = Path(path)
    root = staging_dir()
    if candidate.parent != root or not candidate.name.startswith("transaction-"):
        raise SelfUpdateError("refused unsafe transaction cleanup path")
    _remove_tree(candidate, allowed_parent=root)


def run_helper_cli(argv) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="PiTrac Updater")
    # Proving the copied helper can start, rather than assuming it from a
    # file mode. The check before this existed looked at is_file() and the
    # executable bit and then reported "could not execute" on failure, which
    # claimed more than it had tested: a binary copied out of an unsigned
    # bundle can satisfy both and still refuse to launch. The application
    # closes itself in favour of this helper, so being wrong about it means
    # nothing performs the update and nothing reports why.
    parser.add_argument("--ping", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--journal", type=Path, required=False)
    parser.add_argument("--wait-pid", type=int, required=False)
    parser.add_argument("--timeout", type=float, default=HELPER_EXIT_TIMEOUT)
    parser.add_argument("--ack-timeout", type=float, default=ACK_TIMEOUT)
    args = parser.parse_args(argv)
    if args.ping:
        print(HELPER_PING_REPLY)
        return 0
    if args.journal is None or args.wait_pid is None:
        parser.error("--journal and --wait-pid are required")
    return run_helper(args.journal, args.wait_pid, timeout=args.timeout,
                      ack_timeout=args.ack_timeout)
