"""Build the installer for the computer this runs on, and the kit it goes in.

    python packaging/make_installer.py

On a Mac that is a disk image; on Windows it is a setup program. Neither can be
made on the other, because what is bundled is the Python of the machine that
builds it. Both go into the same kit, with the source they were built from and
what the Raspberry Pi needs, so that the whole thing can be kept on a USB stick
and installed with no internet.

Nothing here uses GitHub, and nothing in the source folder is changed: the build
happens in a temporary copy, with its own Python environment.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "PiTrac Easy-Connect"
HELPER = "PiTrac Updater"
WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"

#: The window on Windows is drawn through pythonnet, which is pinned to a release
#: that does not know about Python 3.14.
OLDEST, NEWEST = (3, 10), (3, 13)

#: Never part of the source, whatever is lying about in the folder.
SKIP = {".git", ".check", ".build", "dist", "dist-helper", "build", "__pycache__", ".venv",
        "venv", ".pytest_cache", ".claude", ".DS_Store"}

#: A shell script with Windows line endings does not run on the Pi, and a batch
#: file without them does strange things on Windows.
UNIX_LINES = (".sh", ".service")
DOS_LINES = (".cmd",)


class BuildError(Exception):
    """Something a person can act on."""


def say(text):
    print("  " + text, flush=True)


def step(text):
    print("\n" + text, flush=True)


def run(command, **options):
    """Run something, and show what it said only if it failed."""

    done = subprocess.run([str(part) for part in command], capture_output=True, text=True,
                          errors="replace", **options)
    if done.returncode != 0:
        tail = "\n".join((done.stdout + "\n" + done.stderr).strip().splitlines()[-25:])
        raise BuildError("{} failed:\n{}".format(Path(str(command[0])).name, tail))
    return done.stdout


# --- What is being built -------------------------------------------------------


def version_of(root=ROOT):
    text = (root / "src" / "pitrac_easy_connect" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def check_python(info=None):
    info = info or sys.version_info
    if not OLDEST <= (info[0], info[1]) <= NEWEST:
        raise BuildError(
            "This needs Python {}.{} to {}.{}, and is running on {}.{}.".format(
                *OLDEST, *NEWEST, info[0], info[1])
        )


def machine_name():
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)


def installer_name(version, system=None, machine=None):
    system = system or platform.system()
    machine = machine or machine_name()
    if system == "Darwin":
        kind = "Mac Apple silicon" if machine == "arm64" else "Mac Intel"
        return "{} {} ({}).dmg".format(APP, version, kind)
    return "{} {} (Windows).exe".format(APP, version)


def source_files(root=ROOT):
    """Every file that belongs to the project, as paths relative to it."""

    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8").split("\0")
        inside = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                                capture_output=True, check=True, text=True).stdout.strip()
        if Path(inside).resolve() == Path(root).resolve():
            return sorted(name for name in listed if name and (root / name).is_file())
    except (OSError, subprocess.CalledProcessError):
        pass
    # Not a checkout: the kit's own source, unpacked on the Windows computer.
    found = []
    for folder, folders, names in os.walk(root):
        folders[:] = [name for name in folders if name not in SKIP and not name.endswith(".egg-info")]
        for name in names:
            if name not in SKIP and not name.startswith("._") and not name.endswith(".pyc"):
                found.append((Path(folder) / name).relative_to(root).as_posix())
    return sorted(found)


def with_line_endings(name, data):
    if name.endswith(UNIX_LINES):
        return data.replace(b"\r\n", b"\n")
    if name.endswith(DOS_LINES):
        return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def write_source(target, root=ROOT, folder="PiTrac-Easy-Connect"):
    """The source as one file, the same bytes whichever machine wrote it."""

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in source_files(root):
            entry = zipfile.ZipInfo("{}/{}".format(folder, name), (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            mode = 0o755 if name.endswith(".sh") else 0o644
            entry.external_attr = (0o100000 | mode) << 16
            archive.writestr(entry, with_line_endings(name, (root / name).read_bytes()))
    return target


def copy_source(target, root=ROOT):
    for name in source_files(root):
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(with_line_endings(name, (root / name).read_bytes()))
        if name.endswith(".sh"):
            destination.chmod(0o755)


# --- Building the app ------------------------------------------------------------


def build_environment(work):
    step("Preparing the pinned build tools")
    home = work / "python"
    run([sys.executable, "-m", "venv", home])
    python = home / ("Scripts/python.exe" if WINDOWS else "bin/python")
    run([python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "-r", work / "source" / "packaging" / "build-requirements.txt"])
    say("Ready")
    return python


def build_app(work, python, version):
    source = work / "source"
    step("Building {} {}".format(APP, version))
    environment = dict(os.environ, PITRAC_VERSION=version, PYTHONDONTWRITEBYTECODE="1",
                       # Windows otherwise reads and writes text in its own encoding.
                       PYTHONUTF8="1")
    # A source folder on the path would be found before the copy being built.
    environment.pop("PYTHONPATH", None)
    options = {"cwd": source, "env": environment}
    run([python, "packaging/collect-licences.py"], **options)
    run([python, "packaging/icon/make-icons.py", "packaging/icon"], **options)
    if MAC:
        run(["iconutil", "-c", "icns", "packaging/icon/PiTrac.iconset",
             "-o", "packaging/icon/PiTrac.icns"], **options)
    for spec, out in (("PiTrac-Easy-Connect.spec", "dist"), ("PiTrac-Updater.spec", "dist-helper")):
        say("PyInstaller, {}".format(spec))
        run([python, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", out,
             "--workpath", "build/" + Path(spec).stem, "packaging/" + spec], **options)
    toc = next((source / "build" / "PiTrac-Easy-Connect").rglob("Analysis-00.toc"))
    run([python, "packaging/bundled-licences.py", "--check", "--toc", toc], **options)
    say("Everything bundled is credited in NOTICE.md")
    return assemble(source, python, version, options)


def assemble(source, python, version, options):
    """Put the app, its updater, and its manifest into one installable unit."""

    if MAC:
        app = source / "dist" / (APP + ".app")
        helpers = app / "Contents" / "Helpers"
        helpers.mkdir(exist_ok=True)
        shutil.copy2(source / "dist-helper" / HELPER, helpers / HELPER)
        (helpers / HELPER).chmod(0o755)
        manifest = app / "Contents" / "Resources" / "pitrac-install.json"
        system = "Darwin"
    else:
        app = source / "dist" / "payload" / APP
        app.mkdir(parents=True)
        shutil.copy2(source / "dist" / (APP + ".exe"), app)
        shutil.copy2(source / "dist-helper" / (HELPER + ".exe"), app)
        for name in ("LICENSE", "NOTICE.md", "THIRD-PARTY-LICENCES.txt",
                     "packaging/WINDOWS-INSTALLATION.txt"):
            shutil.copy2(source / name, app)
        manifest = app / "pitrac-install.json"
        system = "Windows"
    run([python, "packaging/write-install-manifest.py", manifest, "--version", version,
         "--system", system, "--arch", machine_name()], **options)
    if MAC:
        say("Runs on macOS {} or later".format(set_minimum_macos(app)))
        sign_mac(app, source)
    run([python, "-c",
         "import sys; sys.path.insert(0, 'src')\n"
         "from pathlib import Path\n"
         "from pitrac_easy_connect.companion import self_update\n"
         "self_update.validate_install_root(Path(sys.argv[1]), expected_version=sys.argv[2])",
         app, version], **options)
    say("The installed layout is complete")
    return app


# --- macOS -----------------------------------------------------------------------


def newest_minimum(listings):
    """The newest system any of these ``otool -l`` listings asks for."""

    found = [
        tuple(int(part) for part in value.split("."))
        for text in listings
        for value in re.findall(r"^\s+(?:minos|version) (\d+(?:\.\d+)+)$", text, re.M)
        # LC_SOURCE_VERSION and friends print a "version" too, in other shapes.
        if 10 <= int(value.split(".")[0]) < 100
    ]
    return max(found) if found else (11, 0)


def set_minimum_macos(app):
    """Say truthfully which macOS this needs.

    It depends on the Python it was built with: one from python.org runs on old
    systems, and one from Homebrew only on the system it was built for. Claiming
    the older one would give somebody an app that installs and will not open.
    """

    listings = []
    for path in app.rglob("*"):
        if path.is_file() and not path.is_symlink() and (
            path.suffix in (".so", ".dylib") or os.access(path, os.X_OK)
        ):
            done = subprocess.run(["otool", "-l", str(path)], capture_output=True, text=True,
                                  errors="replace")
            if "minos" in done.stdout or "LC_VERSION_MIN_MACOSX" in done.stdout:
                # Only the part that names a system, not every library's version.
                listings += re.findall(
                    r"cmd LC_(?:BUILD_VERSION|VERSION_MIN_MACOSX).*?(?=Load command|\Z)",
                    done.stdout, re.S)
    needed = max(newest_minimum(listings), (11, 0))
    text = ".".join(str(part) for part in needed[:2])
    run(["plutil", "-replace", "LSMinimumSystemVersion", "-string", text,
         app / "Contents" / "Info.plist"])
    return text


def sign_mac(app, source):
    """Inside out: the helper first, then the bundle that contains it."""

    identity = os.environ.get("PITRAC_MAC_IDENTITY", "-")
    options = []
    if identity != "-":
        options = ["--options", "runtime", "--timestamp",
                   "--entitlements", source / "packaging" / "entitlements.plist"]
    run(["xattr", "-cr", app])
    for part in (app / "Contents" / "Helpers" / HELPER, app):
        run(["codesign", "--force", "--deep", *options, "--sign", identity, part])
    run(["codesign", "--verify", "--deep", "--strict", app])
    say("Signed{}".format(" as " + identity if identity != "-" else " for this kind of Mac only"))


def make_dmg(app, target, work):
    step("Making the disk image")
    contents = work / "dmg"
    contents.mkdir()
    run(["ditto", "--norsrc", "--noextattr", app, contents / app.name])
    (contents / "Applications").symlink_to("/Applications")
    (contents / "If it will not open.txt").write_text(MAC_NOTE, encoding="utf-8")
    run(["hdiutil", "create", "-volname", APP, "-srcfolder", contents, "-ov",
         "-format", "UDZO", target])
    run(["hdiutil", "verify", target])
    return target


class InstalledMac:
    """The app as somebody would have it: out of the disk image, into a folder."""

    def __init__(self, installer, work):
        self.folder = work / "installed"
        self.folder.mkdir()
        mount = work / "mounted"
        run(["hdiutil", "attach", installer, "-nobrowse", "-readonly", "-mountpoint", mount])
        try:
            run(["ditto", mount / (APP + ".app"), self.folder / (APP + ".app")])
        finally:
            subprocess.run(["hdiutil", "detach", str(mount), "-force"], capture_output=True)
        self.executable = self.folder / (APP + ".app") / "Contents" / "MacOS" / APP
        run(["codesign", "--verify", "--deep", "--strict", self.folder / (APP + ".app")])

    def remove(self):
        shutil.rmtree(self.folder, ignore_errors=True)


# --- Windows ---------------------------------------------------------------------


def find_inno(environment=None):
    """Inno Setup's compiler, wherever it was installed."""

    environment = os.environ if environment is None else environment
    for variable, below in (("ProgramFiles(x86)", ""), ("ProgramFiles", ""),
                            ("LOCALAPPDATA", "Programs")):
        base = environment.get(variable)
        if not base:
            continue
        for folder in sorted(Path(base, below).glob("Inno Setup *"), reverse=True):
            if (folder / "ISCC.exe").is_file():
                return folder / "ISCC.exe"
    return None


def require_inno(ask=input):
    found = find_inno()
    if found:
        return found
    say("The setup program is made with Inno Setup, which is not installed.")
    if sys.stdin is None or not sys.stdin.isatty():
        raise BuildError("Install it with:  winget install --id JRSoftware.InnoSetup -e")
    if ask("  Install it now with winget? [y/N] ").strip().lower() in ("y", "yes"):
        subprocess.run(["winget", "install", "--id", "JRSoftware.InnoSetup", "-e"])
        found = find_inno()
    if not found:
        raise BuildError("Install Inno Setup from jrsoftware.org, then run this again.")
    return found


def make_setup(app, target, work, version, inno, *options):
    run([inno, "/DAppVersion=" + version, "/DSourceDir=" + str(app), *options,
         "/O" + str(target.parent), "/F" + target.stem,
         work / "source" / "packaging" / "windows-installer.iss"])
    if not target.is_file():
        raise BuildError("Inno Setup finished without making {}".format(target.name))
    return target


class InstalledWindows:
    """Installed for real, into a folder of its own, and removed again.

    From a setup program that differs only in who it says it is, so that a
    computer with the real one installed keeps it untouched.
    """

    def __init__(self, installer, work):
        self.folder = work / "installed" / APP
        log = work / "install.log"
        # Each value carries its own quotes, because the folder has a space in it.
        done = subprocess.run(
            '"{}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="{}" /LOG="{}"'.format(
                installer, self.folder, log))
        if done.returncode != 0:
            tail = log.read_text(errors="replace").splitlines()[-20:] if log.exists() else []
            raise BuildError("The setup program failed:\n" + "\n".join(tail))
        self.executable = self.folder / (APP + ".exe")
        missing = [name for name in (APP + ".exe", HELPER + ".exe", "pitrac-install.json")
                   if not (self.folder / name).is_file()]
        if missing:
            raise BuildError("The setup program did not install " + ", ".join(missing))

    def remove(self):
        uninstall = self.folder / "unins000.exe"
        if uninstall.is_file():
            subprocess.run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])


# --- Trying it ---------------------------------------------------------------------


class RunningApp:
    def __init__(self, executable, config, *arguments):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.arguments = [str(executable), "--port", str(self.port), "--config", str(config)]
        self.process = subprocess.Popen([*self.arguments, *arguments])

    def ask(self, path, body=None):
        request = urllib.request.Request(
            "http://127.0.0.1:{}{}".format(self.port, path),
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"X-PiTrac-App": "1", "Content-Type": "application/json"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as answer:
            return json.loads(answer.read())

    def wait_for(self, condition, seconds, why):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise BuildError("The app closed by itself while {}".format(why))
            try:
                if condition():
                    return
            except OSError:
                pass
            time.sleep(0.5)
        raise BuildError("Gave up waiting for the app while {}".format(why))

    def quit(self):
        try:
            self.ask("/api/quit", {})
            self.process.wait(20)
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False
        finally:
            if self.process.poll() is None:
                if WINDOWS:
                    # The program somebody sees is a child of the one started.
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                                   capture_output=True)
                self.process.kill()
                self.process.wait(10)


def try_it(executable, version, work):
    """Open the installed app and use it, the way its first owner would."""

    step("Trying the installed app")
    config = work / "try" / "companion.json"
    # Long waits: a first launch unpacks and is scanned by whatever looks at
    # programs nobody has seen before.
    app = RunningApp(executable, config, "--smoke-test")
    try:
        app.wait_for(lambda: app.ask("/api/status")["version"] == version, 120, "starting")
        app.wait_for(lambda: app.ask("/api/status")["window"]["state"] == "native", 60,
                     "opening its window")
        app.wait_for(lambda: app.ask("/api/page-check")["requests"].get("POST /api/finish-setup"),
                     120, "drawing its page")
        status = app.ask("/api/status")
        if status["simulator"] != "local":
            raise BuildError("A new installation should start on the Local Range")
        if status["update"]["desktop"]["state"] != "idle":
            raise BuildError("It went looking for an update that cannot exist")
        app.ask("/api/range-demo", {})
        app.ask("/api/range-target", {"yards": 100})
        if app.ask("/api/range")["count"] != 1:
            raise BuildError("The range did not take a shot")
        say("Opens in its own window, and the range works")

        second = subprocess.Popen(app.arguments)
        try:
            if second.wait(60) != 0:
                raise BuildError("Opening it twice did not go well")
        except subprocess.TimeoutExpired:
            second.kill()
            raise BuildError("Opening it twice left two copies running")
        app.wait_for(lambda: app.ask("/api/page-check")["requests"].get("POST /api/activate"), 20,
                     "being opened a second time")
        say("Opening it again shows the one already open")
    finally:
        closed = app.quit()
    if not closed:
        raise BuildError("The app did not close when asked")

    # What was chosen is still there, which is what upgrading relies on.
    again = RunningApp(executable, config)
    try:
        again.wait_for(lambda: again.ask("/api/range")["target"] == 100, 120, "remembering")
        say("Closed and reopened with its settings intact")
    finally:
        again.quit()


# --- The kit --------------------------------------------------------------------------


MAC_NOTE = """If macOS says it cannot check this app
=======================================

This app is not from the App Store, so macOS asks before opening it the first
time on a Mac it was not built on.

1. Drag PiTrac Easy-Connect into Applications.
2. Open it. macOS says it could not be opened. Close that message.
3. Open System Settings, then Privacy & Security, and scroll down.
4. Beside PiTrac Easy-Connect, press Open Anyway.

If it then cannot find PiTrac, turn it on under Privacy & Security, Local Network.
"""

OWNER_CARD = """PiTrac owner card
=================

The Raspberry Pi prints this when Easy-Connect is installed on it. Copy it here
and keep it with the enclosure. Without it there is no way back in if PiTrac
cannot reach a network.

Device ID:        ______________________

Setup Wi-Fi:      PiTrac-________________

Setup password:   ______________________
"""


def read_me(version, names, commit):
    have = lambda kind: next((name for name in names if kind in name), None)
    mac = have("(Mac")
    windows = have("(Windows)")
    return """PiTrac Easy-Connect {version}
{line}

Everything needed to set up one enclosure and its computers, with no internet
except where it says so.


1. The Raspberry Pi
   ----------------
   PiTrac itself goes on first, and that does need internet. This version was
   tested with one revision of it:

       git clone https://github.com/PiTracLM/PiTrac
       cd PiTrac
       git checkout {commit}

   then follow PiTrac's own instructions. Once its dashboard opens and it
   measures a ball, copy "{source}" to the Pi and:

       unzip "{source}"
       cd PiTrac-Easy-Connect
       sudo bash packaging/pi/install.sh

   It prints the owner card. Copy it into "Owner card.txt" and keep it.


2. A Mac
   -----
   {mac}


3. A Windows computer
   ------------------
   {windows}


4. Play
   ----
   Open PiTrac Easy-Connect. It finds the enclosure, asks which Wi-Fi to use if
   it needs to, and opens the range.


Updates
   When a newer version is out, the app says so at the top of its first page.
   Press Update now: it installs on this computer, restarts, and then brings
   the Pi to the same version by itself. Pairing, Wi-Fi, calibration,
   settings, and shot history are all kept. If the app ever says the Pi needs
   a one-time reinstall, run the install command from step 1 again with this
   kit.

Checking these files
   SHA256SUMS.txt lists what each one should be.
""".format(
        version=version,
        line="=" * (len("PiTrac Easy-Connect ") + len(version)),
        commit=commit,
        source=have("source"),
        mac='Open "{}" and drag the app into Applications.\n   '
            'If macOS will not open it, the note beside it says what to do.'.format(mac)
            if mac else "Not in this kit yet. On a Mac, unpack the source and run:\n\n"
            "       python3 packaging/make_installer.py",
        windows='Run "{}".\n   If Windows says it does not recognise it, choose More info, '
            'then Run anyway.'.format(windows)
            if windows else 'Not in this kit yet. On the Windows computer, unpack the source and\n'
            '   double-click "Build Windows Installer". It asks before installing anything,\n'
            "   needs internet the first time, and takes about ten minutes.",
    )


def tested_pitrac(root=ROOT):
    text = (root / "src" / "pitrac_easy_connect" / "pi" / "pitrac_api.py").read_text(encoding="utf-8")
    return re.search(r'TESTED_COMMIT = "([0-9a-f]{40})"', text).group(1)


def finish_kit(kit, version, root=ROOT):
    """Write the parts of the kit that depend on what is in it."""

    source = kit / "{} {} source.zip".format(APP, version)
    write_source(source, root)
    card = kit / "Owner card.txt"
    if not card.exists():
        # Somebody may have filled it in, and it may be the only copy.
        card.write_text(OWNER_CARD, encoding="utf-8")
    names = sorted(path.name for path in kit.iterdir() if path.suffix in (".dmg", ".exe", ".zip"))
    (kit / "READ ME FIRST.txt").write_text(
        read_me(version, names, tested_pitrac(root)), encoding="utf-8")
    sums = []
    for name in names:
        digest = hashlib.sha256((kit / name).read_bytes()).hexdigest()
        sums.append("{}  {}\n".format(digest, name))
    (kit / "SHA256SUMS.txt").write_text("".join(sums), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=ROOT / "dist",
                        help="where the kit goes (default: dist)")
    parser.add_argument("--no-try", action="store_true",
                        help="do not install and open what was built")
    args = parser.parse_args(argv)
    work = None
    try:
        if not (MAC or WINDOWS):
            raise BuildError("Installers are built on a Mac or on Windows.")
        check_python()
        inno = require_inno() if WINDOWS else None
        version = version_of()
        kit = args.output.resolve() / "{} {}".format(APP, version)
        kit.mkdir(parents=True, exist_ok=True)
        # Outside the project: a synced Desktop folder adds attributes to files
        # as they are written, and macOS will not sign a bundle that has them.
        work = Path(tempfile.mkdtemp(prefix="pitrac-build-"))
        copy_source(work / "source")
        python = build_environment(work)
        app = build_app(work, python, version)
        built = work / installer_name(version)
        if MAC:
            installer = trial = make_dmg(app, built, work)
        else:
            step("Making the setup program")
            installer = make_setup(app, built, work, version, inno)
            trial = make_setup(app, work / "trial.exe", work, version, inno, "/DTryOut")
        if not args.no_try:
            installed = (InstalledMac if MAC else InstalledWindows)(trial, work)
            try:
                try_it(installed.executable, version, work)
            finally:
                installed.remove()
        # Only now, so the kit never holds one that was not seen to work.
        shutil.copy2(installer, kit / installer.name)
        finish_kit(kit, version)
        step("Done")
        say(str(kit))
        for path in sorted(kit.iterdir()):
            say("  {:<58}{:>8.1f} MB".format(path.name, path.stat().st_size / 1e6))
        return 0
    except BuildError as exc:
        print("\nNot built. {}".format(exc), file=sys.stderr)
        return 1
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
