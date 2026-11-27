"""An update guard for the enclosure that outlives the update.

Replacing the enclosure's software has one property the desktop's does not:
restarting the service kills the process performing the update. Everything
after ``systemctl restart`` in the updater -- the health check, the rollback,
the cleanup -- is code that can never run. Until now the only protection was a
probe of the *staged* copy before the swap, which catches a truncated download
or an import that no longer resolves, and cannot catch anything that only
happens once the real service runs: state files it cannot parse, a port it
cannot bind, a constructor that raises, a crash loop.

So the component that decides whether the update worked has to be a different
process, started before the symlink moves, with its own systemd registration
so a power cut brings it back at the next boot. That is this module.

It is deliberately standard-library only and imports nothing from the rest of
the package, because the installer copies this one file to a directory outside
the releases tree. A rollback component that lives only inside the release
being replaced is a rollback component that can be replaced by the thing it is
meant to protect against.

The journal is the authority for every path. Nothing here derives a
destination, accepts one from a caller at rollback time, or removes a tree it
has not validated against the journal first. A journal that does not verify
fails closed: the guard stays registered and touches nothing.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

#: Where the copy of this file that must survive the update lives. Outside
#: both the symlink and the releases directory, so replacing either cannot
#: replace the guard.
GUARD_DIR = Path("/usr/lib/pitrac-easy-connect-guard")
GUARD_SCRIPT = "pitrac-update-guard.py"
GUARD_UNIT = "pitrac-easy-connect-update-guard.service"
SERVICE_UNIT = "pitrac-easy-connect.service"

#: Where transactions are recorded. In the state directory, not in /usr:
#: /usr is read-only to the service except for the two update paths, and the
#: journal has to be writable by the guard after the swap either way.
UPDATES_DIRNAME = "updates"

#: How long the new service has to prove itself, and how long it then has to
#: stay up. The Pi 5 cold-starts the service in a few seconds; a minute is
#: generous enough to absorb a slow card and short enough that nobody is left
#: staring at an enclosure that is never coming back.
HEALTH_TIMEOUT = 180.0
SETTLE_SECONDS = 20.0
SWAP_TIMEOUT = 300.0

PHASES = (
    "prepared", "guard-armed", "symlink-moved", "awaiting-health",
    "healthy", "rolling-back", "rolled-back", "failed", "unresolved",
)
TERMINAL_PHASES = ("healthy", "rolled-back", "failed")

#: Every proof the restarted service must supply. A missing key is a failure,
#: so adding one here makes every older acknowledgement insufficient rather
#: than silently accepted.
REQUIRED_PROOFS = (
    "stateFilesLoaded",
    "portalListening",
    "linkListening",
    "discoveryListening",
    "refreshCompleted",
)

_TRANSACTION_RE = re.compile(r"^transaction-[0-9a-f]{32}$")


class GuardError(Exception):
    """The transaction record or the layout it describes is not trustworthy."""


# --- Durability ----------------------------------------------------------

def fsync_dir(path: Path) -> None:
    """Make a rename or creation in this directory survive power loss."""

    try:
        descriptor = os.open(str(path), getattr(os, "O_DIRECTORY", os.O_RDONLY))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def fsync_tree(path: Path) -> None:
    """Push a freshly written release to the card before anything points at it.

    Without this the symlink swap is atomic with respect to a tree that may
    still be entirely in page cache, so a power cut immediately after the swap
    can leave the link pointing at files that were never written.
    """

    for parent, directories, files in os.walk(str(path)):
        for name in files:
            candidate = Path(parent) / name
            if candidate.is_symlink():
                continue
            try:
                descriptor = os.open(str(candidate), os.O_RDONLY)
            except OSError:
                continue
            try:
                os.fsync(descriptor)
            except OSError:
                pass
            finally:
                os.close(descriptor)
        for name in directories:
            fsync_dir(Path(parent) / name)
    fsync_dir(path)


def _atomic_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new-" + uuid.uuid4().hex)
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    fsync_dir(path.parent)


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- The journal ---------------------------------------------------------

def _canonical_digest(journal) -> str:
    value = {key: journal[key] for key in sorted(journal) if key != "integritySha256"}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


REQUIRED_KEYS = (
    "transactionId", "linkPath", "releasesDir", "previousReleasePath",
    "candidateReleasePath", "expectedVersion", "expectedTag", "assetSha256",
    "installedVersion", "serviceName", "phase", "createdAt", "updatedAt",
    "healthTimeout", "settleSeconds",
)


def write_journal(path: Path, journal, phase=None) -> None:
    value = dict(journal)
    if phase is not None:
        if phase not in PHASES:
            raise GuardError("invalid transaction phase")
        value["phase"] = phase
    value["updatedAt"] = time.time()
    value["integritySha256"] = _canonical_digest(value)
    _atomic_json(path, value)
    journal.clear()
    journal.update(value)


def _reject_broad_path(path: Path) -> None:
    """Refuse anything a rollback must never be able to name."""

    resolved = Path(os.path.normpath(str(path)))
    if str(resolved) in ("/", "", ".") or resolved.parent == resolved:
        raise GuardError("a filesystem root cannot be a release path")
    if resolved.name.lower() in ("desktop", "downloads", "documents", "usr", "lib", "var"):
        raise GuardError("{} is not a release directory".format(resolved))
    try:
        home = Path.home()
    except (OSError, RuntimeError):
        home = None
    if home is not None and resolved == home:
        raise GuardError("a home directory cannot be a release path")


def load_journal(path: Path):
    """Read one transaction, or refuse to act on it at all.

    Every field the guard would act on is checked here, before any caller can
    reach a rename: a tampered journal is the one way an attacker who can
    write to the state directory could aim a privileged rollback at a path of
    their choosing.
    """

    try:
        journal = _read_json(path)
    except (OSError, ValueError) as exc:
        raise GuardError("the transaction journal could not be read: {}".format(exc))
    if not isinstance(journal, dict):
        raise GuardError("the transaction journal is not a record")
    missing = [key for key in REQUIRED_KEYS if key not in journal]
    if missing:
        raise GuardError("the transaction journal is missing {}".format(", ".join(missing)))
    if journal.get("integritySha256") != _canonical_digest(journal):
        raise GuardError("the transaction journal has been altered")
    if journal["phase"] not in PHASES:
        raise GuardError("the transaction journal names an unknown phase")
    if not _TRANSACTION_RE.match("transaction-" + str(journal["transactionId"])):
        raise GuardError("the transaction identifier is malformed")

    releases = Path(journal["releasesDir"])
    link = Path(journal["linkPath"])
    _reject_broad_path(releases)
    _reject_broad_path(link)
    for key in ("previousReleasePath", "candidateReleasePath"):
        candidate = Path(journal[key])
        _reject_broad_path(candidate)
        # The only destinations a rollback may name are release directories
        # directly inside the releases directory this transaction recorded.
        if candidate.parent != releases:
            raise GuardError("{} is not inside {}".format(candidate, releases))
    if Path(journal["previousReleasePath"]) == Path(journal["candidateReleasePath"]):
        raise GuardError("the transaction has no distinct previous release")
    if link.parent == releases:
        raise GuardError("the live link cannot live among the releases it selects")
    return journal


def transaction_dir(state_dir: Path, transaction_id: str) -> Path:
    return Path(state_dir) / UPDATES_DIRNAME / ("transaction-" + transaction_id)


def pending_transaction(state_dir: Path):
    """The newest transaction that has not reached a terminal phase."""

    root = Path(state_dir) / UPDATES_DIRNAME
    if not root.is_dir():
        return None
    found = []
    for path in root.glob("transaction-*"):
        if not _TRANSACTION_RE.match(path.name):
            continue
        journal_path = path / "journal.json"
        try:
            journal = load_journal(journal_path)
        except GuardError:
            continue
        if journal["phase"] not in TERMINAL_PHASES:
            found.append((journal["updatedAt"], journal_path))
    if not found:
        return None
    return max(found)[1]


# --- The health acknowledgement ------------------------------------------

def acknowledge_health(state_dir: Path, *, version: str, release_path: Path,
                       proofs, pid=None, started_at=None) -> bool:
    """Record that this running service has actually proved itself.

    Called by the restarted enclosure service once its listeners are up and
    its state has loaded. It returns whether an acknowledgement was written,
    which is False whenever there is no transaction to acknowledge -- an
    ordinary boot, which is almost every boot.
    """

    journal_path = pending_transaction(state_dir)
    if journal_path is None:
        return False
    journal = load_journal(journal_path)
    _atomic_json(journal_path.parent / "health.json", {
        "transactionId": journal["transactionId"],
        "version": str(version).lstrip("v"),
        "releasePath": str(Path(os.path.realpath(str(release_path)))),
        "proofs": {key: bool(value) for key, value in dict(proofs).items()},
        "pid": int(pid if pid is not None else os.getpid()),
        "startedAt": float(started_at if started_at is not None else time.time()),
        "writtenAt": time.time(),
    })
    return True


def _health_for(journal, path: Path, version: str, release: Path):
    """One acknowledgement, or None -- never a partial or hopeful match."""

    try:
        health = _read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(health, dict):
        return None
    if health.get("transactionId") != journal["transactionId"]:
        return None
    if str(health.get("version") or "") != str(version).lstrip("v"):
        return None
    if Path(str(health.get("releasePath") or "")) != Path(os.path.realpath(str(release))):
        return None
    proofs = health.get("proofs")
    if not isinstance(proofs, dict):
        return None
    if not all(proofs.get(name) is True for name in REQUIRED_PROOFS):
        return None
    return health


def running_release_path(module_file=None) -> Path:
    """The real release directory the running service was imported from.

    Resolved rather than reported, because the whole point is that the symlink
    may now point somewhere else than it did when this process started.
    """

    here = Path(module_file or __file__).resolve()
    # .../<release>/pitrac_easy_connect/pi/update_guard.py
    return here.parent.parent.parent


# --- The guard itself ----------------------------------------------------

def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _point_link_at(link: Path, destination: Path) -> None:
    """Move the live symlink in one atomic replacement."""

    temporary = link.with_name(link.name + ".guard-" + uuid.uuid4().hex)
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    temporary.symlink_to(destination)
    os.replace(temporary, link)
    fsync_dir(link.parent)


def _restart_service(name: str) -> None:  # pragma: no cover - exercised on a Pi
    subprocess.run(["systemctl", "restart", name], timeout=120, check=False,
                   capture_output=True)


def _systemctl(*arguments) -> int:  # pragma: no cover - exercised on a Pi
    try:
        done = subprocess.run(["systemctl", *arguments], timeout=60, check=False,
                              capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return 1
    return done.returncode


def arm(*, state_dir: Path, link_path: Path, releases_dir: Path, previous: Path,
        candidate: Path, installed_version: str, expected_version: str,
        expected_tag: str, asset_sha256: str, service_name: str = SERVICE_UNIT,
        health_timeout: float = HEALTH_TIMEOUT, settle_seconds: float = SETTLE_SECONDS,
        register=None) -> Path:
    """Record the transaction and register the guard, before the symlink moves.

    Order matters and is the whole point: the candidate tree is pushed to the
    card, then the journal that names it is written and pushed, then the guard
    is registered to run at the next boot, and only then may the caller move
    the link. Every earlier interruption leaves the previous release live.
    """

    transaction_id = uuid.uuid4().hex
    directory = transaction_dir(state_dir, transaction_id)
    directory.mkdir(parents=True, exist_ok=True)
    journal_path = directory / "journal.json"
    journal = {
        "transactionId": transaction_id,
        "linkPath": str(link_path),
        "releasesDir": str(releases_dir),
        "previousReleasePath": str(previous),
        "candidateReleasePath": str(candidate),
        "installedVersion": str(installed_version).lstrip("v"),
        "expectedVersion": str(expected_version).lstrip("v"),
        "expectedTag": str(expected_tag),
        "assetSha256": str(asset_sha256),
        "serviceName": str(service_name),
        "healthTimeout": float(health_timeout),
        "settleSeconds": float(settle_seconds),
        "phase": "prepared",
        "createdAt": time.time(),
        "updatedAt": time.time(),
    }
    write_journal(journal_path, journal)
    load_journal(journal_path)

    fsync_tree(candidate)
    fsync_dir(Path(releases_dir))
    (register or register_guard)(journal_path, journal)
    write_journal(journal_path, journal, "guard-armed")
    return journal_path


def register_guard(journal_path: Path, journal) -> None:  # pragma: no cover - Pi only
    """Install and enable the out-of-tree guard so a power cut cannot skip it."""

    source = Path(journal["candidateReleasePath"]) / "pitrac_easy_connect" / "pi" / "update_guard.py"
    if not source.is_file():
        source = Path(__file__).resolve()
    GUARD_DIR.mkdir(parents=True, exist_ok=True)
    installed = GUARD_DIR / GUARD_SCRIPT
    shutil.copy2(source, installed)
    os.chmod(installed, 0o755)
    fsync_dir(GUARD_DIR)

    unit = Path("/etc/systemd/system") / GUARD_UNIT
    unit.write_text(GUARD_UNIT_TEMPLATE.format(
        script=installed, journal=journal_path, service=journal["serviceName"],
    ), encoding="utf-8")
    fsync_dir(unit.parent)
    _systemctl("daemon-reload")
    # Enabled, so a power cut before or during the swap still runs it at the
    # next boot; started, so the ordinary case is watched right now.
    if _systemctl("enable", GUARD_UNIT) != 0:
        raise GuardError("the update guard could not be registered to run at boot")
    _systemctl("start", "--no-block", GUARD_UNIT)


def unregister_guard(journal) -> None:  # pragma: no cover - Pi only
    """Stop the guard running at boot. Called by the guard itself, as it ends.

    No daemon-reload: this runs inside the guard's own unit, and reloading with
    its file gone leaves systemd holding a unit with default settings -- a
    90-second start limit -- for a guard that may have been running for
    minutes. On a real enclosure that killed the guard at the end of a
    rollback. Removing the file is enough; the next reload forgets the unit.
    """

    _systemctl("disable", GUARD_UNIT)
    try:
        (Path("/etc/systemd/system") / GUARD_UNIT).unlink()
    except OSError:
        pass


GUARD_UNIT_TEMPLATE = """\
[Unit]
Description=PiTrac Easy-Connect update guard
DefaultDependencies=no
After=local-fs.target
Before=shutdown.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {script} --journal {journal}
RemainAfterExit=no
TimeoutStartSec=900
# The one thing this exists to do is move the live symlink back. It lives
# beside the releases, which is the only place in /usr it may write.
ReadWritePaths=/usr/lib/pitrac-easy-connect-releases
ReadWritePaths=/var/lib/pitrac-easy-connect

[Install]
WantedBy=multi-user.target
"""


def run_guard(journal_path: Path, *, now=time.monotonic, sleep=time.sleep,
              restart=None, unregister=None, prune=True) -> int:
    """Decide whether the restarted enclosure kept the update, and act.

    Returns 0 when the candidate proved itself, 1 when the previous release
    was restored and proved itself, and 2 when neither could be established --
    in which case the registration is deliberately left in place so the next
    boot tries again.
    """

    restart = restart or _restart_service
    unregister = unregister or unregister_guard
    try:
        journal = load_journal(journal_path)
    except GuardError:
        # Fail closed. A journal that does not verify is never acted on, and
        # never deleted either: it is the evidence.
        return 2

    if journal["phase"] in TERMINAL_PHASES:
        unregister(journal)
        return 0 if journal["phase"] == "healthy" else 1

    link = Path(journal["linkPath"])
    previous = Path(journal["previousReleasePath"])
    candidate = Path(journal["candidateReleasePath"])
    health_path = Path(journal_path).parent / "health.json"

    def current():
        try:
            return Path(os.path.realpath(str(link)))
        except OSError:
            return None

    # Reconcile against the filesystem, not against the phase alone: a power
    # cut can happen after a rename and before the phase that records it.
    deadline = now() + SWAP_TIMEOUT
    while current() == previous and journal["phase"] in ("prepared", "guard-armed"):
        if now() >= deadline:
            break
        sleep(0.25)
        try:
            journal = load_journal(journal_path)
        except GuardError:
            return 2

    where = current()
    if where == previous:
        # The swap never happened. There is nothing to undo, and the running
        # release is the one that was always there.
        write_journal(journal_path, journal, "failed")
        unregister(journal)
        return 1
    if where != candidate:
        # Neither release. Something outside this transaction moved the link;
        # guessing would be how an enclosure loses its software.
        write_journal(journal_path, journal, "unresolved")
        return 2

    write_journal(journal_path, journal, "awaiting-health")
    healthy = _await_health(
        journal, health_path, journal["expectedVersion"], candidate,
        journal["healthTimeout"], journal["settleSeconds"], now=now, sleep=sleep,
    )
    if healthy:
        write_journal(journal_path, journal, "healthy")
        if prune:
            _prune_releases(journal)
        unregister(journal)
        return 0

    # --- Rollback -------------------------------------------------------
    if not previous.is_dir():
        write_journal(journal_path, journal, "unresolved")
        return 2
    write_journal(journal_path, journal, "rolling-back")
    try:
        health_path.unlink()
    except OSError:
        pass
    try:
        _point_link_at(link, previous)
    except OSError:
        write_journal(journal_path, journal, "unresolved")
        return 2
    restart(journal["serviceName"])
    restored = _await_health(
        journal, health_path, journal["installedVersion"], previous,
        journal["healthTimeout"], journal["settleSeconds"], now=now, sleep=sleep,
    )
    if not restored:
        # The files are back but nothing has proved it. Stay registered.
        write_journal(journal_path, journal, "unresolved")
        return 2
    write_journal(journal_path, journal, "rolled-back")
    unregister(journal)
    return 1


def _await_health(journal, health_path: Path, version: str, release: Path,
                  timeout: float, settle: float, *, now, sleep) -> bool:
    """Wait for one exact acknowledgement, then for it to still be true.

    The settle window is what distinguishes a service that started from a
    service that keeps starting. A crash loop writes an acknowledgement every
    time round, so the acknowledgement alone proves nothing; the same process
    still being alive a while later does.
    """

    deadline = now() + max(0.0, float(timeout))
    health = None
    while now() < deadline:
        health = _health_for(journal, health_path, version, release)
        if health is not None:
            break
        sleep(0.25)
    if health is None:
        return False

    settle_until = now() + max(0.0, float(settle))
    while now() < settle_until:
        sleep(0.25)
        current = _health_for(journal, health_path, version, release)
        if current is None or current.get("pid") != health.get("pid"):
            return False
        if not _alive(int(current.get("pid") or 0)):
            return False
    return _alive(int(health.get("pid") or 0))


def _prune_releases(journal, keep: int = 2) -> None:
    """Keep the live release and the one to go back to; drop older ones.

    This runs here because on the enclosure it can run nowhere else: the
    updater's own pruning is after a restart that ends its process.
    """

    releases = Path(journal["releasesDir"])
    live = Path(os.path.realpath(str(journal["linkPath"])))
    try:
        found = [path for path in releases.iterdir() if path.is_dir() and not path.is_symlink()]
    except OSError:
        return
    found.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    keeping = [path for path in found if path != live][: max(keep - 1, 0)]
    for path in found:
        if path == live or path in keeping:
            continue
        if path.parent != releases:            # pragma: no cover - defensive
            continue
        shutil.rmtree(path, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="pitrac-update-guard",
        description="Restore the enclosure's previous release if an update will not run",
    )
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    arguments = parser.parse_args(argv)
    journal_path = arguments.journal
    if journal_path is None:
        if arguments.state_dir is None:
            parser.error("--journal or --state-dir is required")
        journal_path = pending_transaction(arguments.state_dir)
        if journal_path is None:
            return 0
    return run_guard(journal_path)


if __name__ == "__main__":                     # pragma: no cover - Pi entry point
    raise SystemExit(main())
