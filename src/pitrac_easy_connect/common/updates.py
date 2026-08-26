"""Telling you when there is a newer version, and installing it when asked.

The point is that every enclosure and every PC ends up on the same release
rather than each carrying whatever was current the day it was set up.

Two kinds of installation exist and they update differently:

**A source checkout** — the repository cloned with git. Updating is ``git pull``,
which is how this is normally run during development and by anyone who installed
from source.

**A packaged desktop build** — the macOS app, Windows executable, or native
Linux executable someone downloaded. There is no repository to pull, so the
newest published release is looked up and the user is pointed at the download.

The enclosure has a separate verified ``.pyz`` archive updater below. That
archive is an installation payload for the Pi service, not a desktop release.

Three rules shape all of it:

- **Never block startup.** Checking happens off the startup path with a short
  timeout, and any failure is silent. A GitHub outage must not stop someone
  playing golf.
- **Never install without being asked.** Checking and applying are separate.
- **Never offer an update to a working tree with local changes.** That is a
  development install, and pulling over it would discard work.
"""

import hashlib
import json

from . import jsontext
from . import release_manifest
import os
import platform
import re
import shutil
import tempfile
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .errors import UPD_UNSUPPORTED_PLATFORM, EasyConnectError
from .versions import compare, is_newer, parse

#: Where releases are published. Overridable so the update path can be
#: exercised against a stand-in rather than against GitHub.
REPOSITORY = os.environ.get("PITRAC_UPDATE_REPOSITORY", "TylerPardun/pitrac-easy-connect")

#: The base of the release API. Overridable for the same reason.
API_BASE = os.environ.get("PITRAC_UPDATE_API", "https://api.github.com")
RELEASES_API = API_BASE + "/repos/{}/releases/latest"
RELEASES_PAGE = "https://github.com/{}/releases/latest"

CHECK_TIMEOUT = 6.0
GIT_TIMEOUT = 20.0
#: Do not ask GitHub again for this long. Being polite to a public API, and
#: making repeated launches cheap.
RECHECK_SECONDS = 6 * 60 * 60

SOURCE = "source"
PACKAGED = "packaged"
DEVELOPMENT = "development"
UNKNOWN = "unknown"


@dataclass
class UpdateStatus:
    """What is installed, what is available, and whether anything can be done."""

    installed: str
    kind: str = UNKNOWN
    latest: str = ""
    available: bool = False
    can_apply: bool = False
    detail: str = ""
    download_url: str = ""
    checked_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "installed": self.installed,
            "kind": self.kind,
            "latest": self.latest,
            "available": self.available,
            "canApply": self.can_apply,
            "detail": self.detail,
            "downloadUrl": self.download_url,
            "checkedAt": self.checked_at,
        }


@dataclass
class UpdateCoordination:
    """The one safe next step for bringing desktop and enclosure together."""

    phase: str
    desktop_version: str
    enclosure_version: str
    latest_version: str
    target_version: str = ""
    synchronized: bool = False
    can_update_pi: bool = False
    #: The saved plan was for a version this desktop has already passed, so it
    #: has been ignored and should be forgotten. Kept separate from
    #: ``synchronized`` because nothing was reached -- the plan simply expired.
    discard_pending: bool = False
    detail: str = ""
    download_url: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "desktopVersion": self.desktop_version,
            "enclosureVersion": self.enclosure_version,
            "latestVersion": self.latest_version,
            "targetVersion": self.target_version,
            "synchronized": self.synchronized,
            "canUpdatePi": self.can_update_pi,
            "discardPending": self.discard_pending,
            "detail": self.detail,
            "downloadUrl": self.download_url,
        }


def coordinate_update(
    desktop: UpdateStatus,
    enclosure_version: str,
    pending_target: str = "",
) -> UpdateCoordination:
    """Choose one update direction, forgetting a plan that has been overtaken.

    A saved plan for a version this desktop has already passed is finished,
    not broken. It used to be reported as a blocking fault, which stopped the
    enclosure being offered the update it was actually due, and the only way
    out was starting another check by hand. Installing a newer desktop
    manually is the ordinary way to arrive here, because that is what someone
    does after automatic installation has been refused.

    The opposite case is the one that matters and is unchanged: an older
    desktop must never send the enclosure ahead of itself.
    """

    installed = str(desktop.installed or "")
    pending = str(pending_target or "").lstrip("v")
    overtaken = False
    if pending:
        passed = compare(installed, pending)
        if passed is not None and passed > 0:
            pending, overtaken = "", True

    plan = _decide_update(desktop, enclosure_version, pending)
    if overtaken:
        plan.discard_pending = True
    return plan


def _decide_update(
    desktop: UpdateStatus,
    enclosure_version: str,
    pending_target: str = "",
) -> UpdateCoordination:
    """Choose one update direction after comparing all three versions.

    A Pi update is permitted only when this desktop already runs the exact
    latest release. That makes it impossible for an older desktop to send the
    enclosure ahead of itself. A pending target survives the expected link
    drop while the Pi restarts, and success is reported only after the Pi has
    reconnected and identified itself as that target.
    """

    installed = str(desktop.installed or "")
    enclosure = str(enclosure_version or "")
    latest = str(desktop.latest or "")
    pending = str(pending_target or "")

    if pending:
        desktop_to_pending = compare(installed, pending)
        if desktop_to_pending is None:
            return UpdateCoordination(
                "blocked", installed, enclosure, latest, pending,
                detail="The version this update was aiming for is not readable.",
            )
        if desktop_to_pending < 0:
            return UpdateCoordination(
                "desktop-update-required", installed, enclosure, latest, pending,
                detail=(
                    "Update this desktop app to {}, close the old copy, and restart the new "
                    "copy. PiTrac will not be updated first."
                ).format(pending),
                download_url=desktop.download_url,
            )
        if not enclosure:
            return UpdateCoordination(
                "verifying-pi", installed, enclosure, latest, pending,
                detail=(
                    "Waiting for PiTrac to connect and report its version before continuing "
                    "the {} update."
                ).format(pending),
            )
        enclosure_to_pending = compare(enclosure, pending)
        if enclosure_to_pending == 0:
            return UpdateCoordination(
                "synchronized", installed, enclosure, latest, pending,
                synchronized=True,
                detail="This app and PiTrac are both running {}.".format(pending),
            )
        if enclosure_to_pending == -1:
            return UpdateCoordination(
                "pi-update-required", installed, enclosure, latest, pending,
                can_update_pi=True,
                detail="The desktop is current. PiTrac can now be updated to exactly {}.".format(
                    pending
                ),
                download_url=desktop.download_url,
            )
        return UpdateCoordination(
            "blocked", installed, enclosure, latest, pending,
            detail=(
                "PiTrac is on {} and this update was aiming for {}, so PiTrac was "
                "left alone rather than moved backwards."
            ).format(enclosure, pending),
            download_url=desktop.download_url,
        )

    if not latest or parse(latest) is None:
        return UpdateCoordination(
            "unavailable", installed, enclosure, latest,
            detail=desktop.detail or "The latest release could not be determined.",
            download_url=desktop.download_url,
        )

    target = latest.lstrip("v")
    desktop_order = compare(installed, target)
    if desktop_order is None:
        return UpdateCoordination(
            "blocked", installed, enclosure, latest, target,
            detail="The desktop version could not be compared with the latest release.",
            download_url=desktop.download_url,
        )
    if desktop_order < 0:
        return UpdateCoordination(
            "desktop-update-required", installed, enclosure, latest, target,
            detail=(
                "Update this desktop app to {}, close the old copy, and restart the new copy. "
                "PiTrac will not be updated first."
            ).format(target),
            download_url=desktop.download_url,
        )
    if desktop_order > 0:
        return UpdateCoordination(
            "blocked", installed, enclosure, latest, target,
            detail=(
                "This desktop ({}) is newer than the latest published release ({}), so "
                "PiTrac will not be changed automatically."
            ).format(installed, target),
            download_url=desktop.download_url,
        )

    if not enclosure:
        return UpdateCoordination(
            "reconnect-required", installed, enclosure, latest, target,
            detail="Connect to PiTrac before continuing so its installed version can be verified.",
            download_url=desktop.download_url,
        )

    enclosure_order = compare(enclosure, target)
    if enclosure_order is None:
        return UpdateCoordination(
            "blocked", installed, enclosure, latest, target,
            detail="PiTrac reported an unreadable version, so it was not updated.",
            download_url=desktop.download_url,
        )
    if enclosure_order < 0:
        return UpdateCoordination(
            "pi-update-required", installed, enclosure, latest, target,
            can_update_pi=True,
            detail="The desktop is current. PiTrac can now be updated to exactly {}.".format(
                target
            ),
            download_url=desktop.download_url,
        )
    if enclosure_order > 0:
        return UpdateCoordination(
            "blocked", installed, enclosure, latest, target,
            detail=(
                "PiTrac ({}) is newer than the latest published release ({}), so it was "
                "not downgraded."
            ).format(enclosure, target),
            download_url=desktop.download_url,
        )
    return UpdateCoordination(
        "synchronized", installed, enclosure, latest, target,
        synchronized=True,
        detail="This app and PiTrac are both running {}.".format(target),
        download_url=desktop.download_url,
    )


def _run_git(arguments, cwd: Path, timeout: float = GIT_TIMEOUT):
    return subprocess.run(
        ["git", *arguments], cwd=str(cwd), capture_output=True, text=True, timeout=timeout
    )


class Updater:
    def __init__(
        self,
        installed: str,
        root: Optional[Path] = None,
        repository: str = REPOSITORY,
        fetch: Optional[Callable[[str], Dict[str, Any]]] = None,
    ):
        self.installed = installed
        self.repository = repository
        self.root = Path(root) if root else Path(__file__).resolve().parent.parent.parent.parent
        self._fetch = fetch or self._fetch_latest_release
        self._lock = threading.Lock()
        self._last: Optional[UpdateStatus] = None

    # --- Which kind of installation is this ------------------------------

    def kind(self) -> str:
        if getattr(sys, "frozen", False):
            return PACKAGED
        # A zipapp runs out of a single archive file, not a directory.
        if ".pyz" in str(Path(sys.argv[0]).name).lower():
            return PACKAGED
        if not (self.root / ".git").exists():
            return PACKAGED
        try:
            dirty = _run_git(["status", "--porcelain"], self.root, timeout=8).stdout.strip()
            ahead = _run_git(
                ["rev-list", "@{u}..HEAD", "--count"], self.root, timeout=8
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return UNKNOWN
        if dirty or (ahead.isdigit() and int(ahead) > 0):
            # Uncommitted work or unpushed commits: this is someone's working
            # copy, and pulling over it would throw their work away.
            return DEVELOPMENT
        return SOURCE

    # --- Checking ---------------------------------------------------------

    def check(self, force: bool = False) -> UpdateStatus:
        with self._lock:
            cached = self._last
        if cached and not force and time.time() - cached.checked_at < RECHECK_SECONDS:
            return cached

        status = self._check_now()
        with self._lock:
            self._last = status
        return status

    def check_in_background(self, done: Optional[Callable[[UpdateStatus], None]] = None) -> None:
        """Check without holding anything up. Failure is silent by design."""

        def work():
            try:
                status = self.check()
            except Exception:
                return
            if done is not None:
                try:
                    done(status)
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _check_now(self) -> UpdateStatus:
        kind = self.kind()

        if kind == DEVELOPMENT:
            return UpdateStatus(
                self.installed, kind,
                detail="This is a development copy with local changes, so it is left alone.",
            )

        if kind == SOURCE:
            return self._check_source()

        return self._check_release(kind)

    def _check_source(self) -> UpdateStatus:
        try:
            fetched = _run_git(["fetch", "--quiet"], self.root)
            if fetched.returncode != 0:
                return UpdateStatus(
                    self.installed, SOURCE, detail="Could not reach the repository to check."
                )
            behind = _run_git(["rev-list", "HEAD..@{u}", "--count"], self.root).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return UpdateStatus(self.installed, SOURCE, detail="Could not check for updates.")

        if not behind.isdigit():
            return UpdateStatus(self.installed, SOURCE, detail="Could not check for updates.")

        count = int(behind)
        if count == 0:
            return UpdateStatus(self.installed, SOURCE, detail="Up to date.")
        return UpdateStatus(
            self.installed, SOURCE, available=True, can_apply=True,
            detail="{} update{} available.".format(count, "" if count == 1 else "s"),
        )

    def _check_release(self, kind: str) -> UpdateStatus:
        try:
            release = self._fetch(RELEASES_API.format(self.repository))
        except Exception:
            return UpdateStatus(self.installed, kind, detail="Could not check for updates.")

        tag = str(release.get("tag_name") or "")
        if not tag:
            return UpdateStatus(self.installed, kind, detail="Up to date.")
        if not is_newer(tag, self.installed):
            return UpdateStatus(self.installed, kind, latest=tag, detail="Up to date.")

        return UpdateStatus(
            self.installed, kind, latest=tag, available=True,
            # A packaged build cannot replace itself safely, so the user is sent
            # to the download rather than being promised an install.
            can_apply=False,
            detail="Version {} is available.".format(tag),
            download_url=str(release.get("html_url") or RELEASES_PAGE.format(self.repository)),
        )

    @staticmethod
    def _fetch_latest_release(url: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json", "User-Agent": "PiTrac"}
        )
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
            return jsontext.loads(response.read().decode("utf-8"))

    # --- Applying ---------------------------------------------------------

    def apply(self) -> Dict[str, Any]:
        """Install a waiting update. Only ever called because someone asked."""

        kind = self.kind()
        if kind != SOURCE:
            return {
                "applied": False,
                "detail": "This copy cannot update itself. Download the new version.",
                "downloadUrl": RELEASES_PAGE.format(self.repository),
            }
        try:
            result = _run_git(["pull", "--ff-only"], self.root, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"applied": False, "detail": "The update did not finish: {}".format(exc)}

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            return {
                "applied": False,
                "detail": detail[-1] if detail else "The update did not finish.",
            }

        with self._lock:
            self._last = None
        return {
            "applied": True,
            "detail": "Updated. Restart PiTrac Easy-Connect to use the new version.",
            "needsRestart": True,
        }


# --- The desktop's own packaged release -------------------------------
#
# A packaged desktop build has no repository to pull, but unlike the git
# checkout it *can* replace itself -- there is a real, platform-specific
# package published for it. Checking, downloading, and verifying that
# package lives here, next to the other release-facing code, so there is one
# place that knows how a release is shaped. Actually replacing the running
# application is a companion-only concern (process handling, install-path
# discovery, restart handoff) and lives in companion.self_update instead.


class DesktopUpdateState(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    UP_TO_DATE = "up-to-date"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    CANCELLED = "cancelled"
    VERIFYING = "verifying"
    STAGING = "staging"
    READY_TO_RESTART = "ready-to-restart"
    PREFLIGHT_FAILED = "preflight-failed"
    INSTALLING = "installing"
    AWAITING_RESTART_VERIFICATION = "awaiting-restart-verification"
    ROLLBACK = "rollback"
    ROLLED_BACK = "rolled-back"
    SYNCHRONIZED = "synchronized"
    RESTART_REQUIRED = "restart-required"
    CHECK_FAILED = "check-failed"
    DOWNLOAD_FAILED = "download-failed"
    VERIFY_FAILED = "verify-failed"
    INSTALL_FAILED = "install-failed"


#: Every filename here is produced deterministically by build.yml's build
#: matrix (see the EXPECTED array in its release job) -- reused verbatim,
#: never reconstructed from a version number, so a naming change in the
#: workflow is a naming change here too rather than a silent mismatch.
#:
#: Desktop, not enclosure: no Linux entry, because no Linux desktop build is
#: published. A Linux desktop entry once claimed one existed, so a Linux
#: desktop launch resolved a real-looking filename that no release has ever
#: contained, discovering "unsupported" only as a download failure instead
#: of immediately. select_desktop_asset() below now refuses cleanly instead.
PLATFORM_ASSET_NAMES: Dict[Tuple[str, str], str] = {
    ("Darwin", "arm64"): "PiTrac-Easy-Connect-macos-apple-silicon.zip",
    ("Darwin", "x86_64"): "PiTrac-Easy-Connect-macos-intel.zip",
    ("Windows", "x86_64"): "PiTrac-Easy-Connect-windows.zip",
}

_ARCH_ALIASES = {
    "arm64": "arm64",
    "aarch64": "arm64",
    "x86_64": "x86_64",
    "amd64": "x86_64",
}


def normalize_arch(machine: str) -> str:
    """The same processor reported under whatever name this platform uses."""

    return _ARCH_ALIASES.get(str(machine or "").strip().lower(), str(machine or ""))


def select_desktop_asset(system: Optional[str] = None, machine: Optional[str] = None) -> str:
    """The one release asset built for this computer, or a refusal.

    Never a fallback to a different platform's package: running an Apple
    Silicon binary under Rosetta, or an x86 binary on ARM, is exactly the
    kind of "it downloaded something, but not really for this computer"
    failure this exists to prevent.
    """

    resolved_system = system if system is not None else platform.system()
    resolved_machine = normalize_arch(machine if machine is not None else platform.machine())
    name = PLATFORM_ASSET_NAMES.get((resolved_system, resolved_machine))
    if name is None:
        raise EasyConnectError(
            UPD_UNSUPPORTED_PLATFORM,
            "{} {} has no published PiTrac Easy-Connect build".format(
                resolved_system, resolved_machine or "unknown"
            ),
        )
    return name


def _find_asset(release: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for asset in release.get("assets") or []:
        if str(asset.get("name") or "") == name:
            return asset
    return None


def _find_asset_url(release: Dict[str, Any], name: str) -> str:
    asset = _find_asset(release, name)
    return str(asset.get("browser_download_url") or "") if asset else ""


#: Successful answers ("up to date," "available") are trusted longer than a
#: failure, which is retried sooner on the assumption it was a transient
#: network problem rather than a considered answer.
RECHECK_SECONDS_OK = 20 * 60
RECHECK_SECONDS_FAILED = 5 * 60

#: A real desktop package is tens of megabytes; anything wildly outside this
#: range did not actually arrive.
MIN_PACKAGE_BYTES = 200 * 1024
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30.0


class DesktopReleaseUpdater:
    """Checks for, downloads, and verifies the desktop's own packaged build.

    This never touches the running application -- it only ever produces a
    checked, verified file on disk. Installing it is companion.self_update's
    job, kept separate because it needs to know about running processes and
    install paths, neither of which belongs in this network/crypto layer.
    """

    def __init__(
        self,
        installed: str,
        repository: str = REPOSITORY,
        api_base: Optional[str] = None,
        system: Optional[str] = None,
        machine: Optional[str] = None,
        allow_prerelease: bool = False,
        fetch_json: Optional[Callable[[str], Dict[str, Any]]] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.installed = installed
        self.repository = repository
        self._api = (api_base or API_BASE).rstrip("/")
        self._system = system
        self._machine = machine
        self.allow_prerelease = allow_prerelease
        self._fetch_json = fetch_json or self._fetch_release_json
        self._clock = clock
        self._lock = threading.Lock()
        self._check_condition = threading.Condition(self._lock)
        self._checking = False
        self._last: Optional[UpdateStatus] = None
        self._last_failed = False
        self._selected_releases: Dict[str, Dict[str, Any]] = {}
        #: One verified manifest per tag, so a release is authenticated once
        #: rather than on every status poll.
        self._manifests: Dict[str, tuple] = {}

    def asset_name(self) -> str:
        return select_desktop_asset(self._system, self._machine)

    @property
    def system(self) -> str:
        """The platform this checker selects and verifies packages for --
        the real host by default, injectable so a test (or, one day, a
        cross-compile tool) can exercise another platform's logic without
        needing to run on it."""

        return self._system if self._system is not None else platform.system()

    @property
    def machine(self) -> str:
        return normalize_arch(self._machine if self._machine is not None else platform.machine())

    @property
    def last_check_failed(self) -> bool:
        """Whether the most recent check could not reach the release
        service at all, as opposed to reaching it and getting a real
        answer (up to date, available, unsupported platform, and so on)."""

        with self._lock:
            return self._last_failed

    def cached_status(self) -> UpdateStatus:
        """Return immediately without touching the network."""

        with self._lock:
            if self._last is not None:
                return self._last
        return UpdateStatus(self.installed, PACKAGED, detail="Update check has not finished yet.")

    # --- Checking -----------------------------------------------------

    def check(self, force: bool = False) -> UpdateStatus:
        """Return one checked result without holding the cache lock on I/O.

        An explicit in-progress condition makes concurrent callers reuse the
        owner call. This avoids both duplicate network requests and timestamp
        heuristics that fail on clocks with coarse resolution.
        """

        with self._check_condition:
            if self._checking:
                while self._checking:
                    self._check_condition.wait()
                if self._last is not None:
                    return self._last
            if self._last is not None:
                window = RECHECK_SECONDS_FAILED if self._last_failed else RECHECK_SECONDS_OK
                cache_is_fresh = not force and self._clock() - self._last.checked_at < window
                if cache_is_fresh:
                    return self._last
            self._checking = True

        try:
            status, failed = self._check_now()
        except Exception:
            with self._check_condition:
                self._checking = False
                self._check_condition.notify_all()
            raise

        with self._check_condition:
            if failed and self._last is not None and self._last.latest:
                # A transient outage does not erase the last verified release
                # selection. The detail and last_check_failed flag still make
                # the failed latest attempt explicit.
                status.latest = self._last.latest
                status.available = self._last.available
                status.can_apply = self._last.can_apply
                status.download_url = self._last.download_url
            # Stamped after the network call finishes, not when it started --
            # a check that took a while must not look, to a concurrent
            # caller, as if it had already gone stale before it even
            # returned.
            status.checked_at = self._clock()
            self._last = status
            self._last_failed = failed
            self._checking = False
            self._check_condition.notify_all()
            return status

    def check_in_background(self, done: Optional[Callable[[UpdateStatus], None]] = None) -> None:
        def work():
            try:
                status = self.check()
            except Exception:
                return
            if done is not None:
                try:
                    done(status)
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _check_now(self) -> Tuple[UpdateStatus, bool]:
        now = self._clock()
        try:
            asset = self.asset_name()
        except EasyConnectError as exc:
            return UpdateStatus(self.installed, PACKAGED, detail=str(exc), checked_at=now), True

        try:
            release = self._fetch_json(self._releases_url())
        except Exception:
            return (
                UpdateStatus(self.installed, PACKAGED, detail="Could not check for updates.", checked_at=now),
                True,
            )

        tag = str(release.get("tag_name") or "")
        if tag:
            # Bind the selected metadata to this exact tag. Download work
            # reuses this immutable snapshot instead of asking "latest" a
            # second time and potentially changing transactions mid-flight.
            with self._lock:
                self._selected_releases[tag] = json.loads(json.dumps(release))

        if not self.allow_prerelease and (release.get("draft") or release.get("prerelease")):
            return UpdateStatus(self.installed, PACKAGED, detail="Up to date.", checked_at=now), False

        if not tag or not is_newer(tag, self.installed):
            return (
                UpdateStatus(
                    self.installed, PACKAGED, latest=tag or self.installed, detail="Up to date.",
                    checked_at=now,
                ),
                False,
            )

        if not _find_asset_url(release, asset):
            return (
                UpdateStatus(
                    self.installed, PACKAGED, latest=tag, available=True, can_apply=False,
                    detail="Version {} is available, but no {} package was published for "
                    "this computer.".format(tag, asset),
                    download_url=str(release.get("html_url") or ""),
                    checked_at=now,
                ),
                False,
            )

        return (
            UpdateStatus(
                self.installed, PACKAGED, latest=tag, available=True, can_apply=True,
                detail="Version {} is ready to download.".format(tag),
                download_url=str(release.get("html_url") or ""),
                checked_at=now,
            ),
            False,
        )

    def _releases_url(self, tag: Optional[str] = None) -> str:
        if tag:
            return "{}/repos/{}/releases/tags/{}".format(
                self._api, self.repository, urllib.parse.quote(tag, safe="")
            )
        return "{}/repos/{}/releases/latest".format(self._api, self.repository)

    @staticmethod
    def _fetch_release_json(url: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json", "User-Agent": "PiTrac"}
        )
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
            return jsontext.loads(response.read().decode("utf-8"))

    # --- Downloading and verifying --------------------------------------

    def latest_release(self) -> Dict[str, Any]:
        """The raw release listing, for asset/checksum lookups after ``check``."""

        return self._fetch_json(self._releases_url())

    def release_for_tag(self, tag: str) -> Dict[str, Any]:
        """Return the exact release selected by checking, never a new latest."""

        exact = str(tag or "")
        with self._lock:
            cached = self._selected_releases.get(exact)
            if cached is not None:
                return json.loads(json.dumps(cached))
        release = self._fetch_json(self._releases_url(exact))
        if str(release.get("tag_name") or "") != exact:
            raise ValueError("the release service returned a different tag")
        with self._lock:
            self._selected_releases[exact] = json.loads(json.dumps(release))
        return release

    def asset_download_url(self, release: Dict[str, Any], asset_name: str) -> str:
        return _find_asset_url(release, asset_name)

    def signed_manifest(self, release: Dict[str, Any], tag: str):
        """This release's own signed description of itself, or None.

        None means the release predates signed manifests. Anything wrong --
        missing where it is required, a bad signature, a manifest describing a
        different release, or no way to check on this computer -- raises,
        because a caller must not be able to mistake any of those for "fine".
        """

        cached = self._manifests.get(str(tag))
        if cached is not None:
            return cached[0]
        manifest = release_manifest.fetch_manifest(
            release, self._fetch_bytes, tag=str(tag)
        )
        self._manifests[str(tag)] = (manifest,)
        return manifest

    def expected_sha256(self, release: Dict[str, Any], asset_name: str,
                        manifest=None) -> Optional[str]:
        """The checksum to hold the download to.

        A signed manifest is preferred over everything else, because it is the
        only digest here that is authenticated rather than merely co-located:
        GitHub's own ``digest`` field arrives from the same listing as the
        download URL, so whoever can answer as that listing can supply a
        matching pair. The unsigned sources remain for releases published
        before manifests existed. Neither present is a hard refusal, never a
        silent skip.
        """

        if manifest is not None:
            return release_manifest.expected_digest(manifest, asset_name)
        asset = _find_asset(release, asset_name)
        if asset:
            digest = str(asset.get("digest") or "")
            if digest.startswith("sha256:"):
                value = digest[7:]
                return value.lower() if re.fullmatch(r"[0-9a-fA-F]{64}", value) else None
        sums_url = _find_asset_url(release, "SHA256SUMS.txt")
        if not sums_url:
            return None
        try:
            text = self._fetch_text(sums_url)
        except Exception:
            return None
        for line in text.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].strip() == asset_name:
                value = parts[0].strip()
                return value.lower() if re.fullmatch(r"[0-9a-fA-F]{64}", value) else None
        return None

    @staticmethod
    def _fetch_text(url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "PiTrac"})
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
            return response.read(1024 * 1024).decode("utf-8", errors="replace")

    @staticmethod
    def _fetch_bytes(url: str) -> bytes:
        """Read one small unauthenticated document, with a hard ceiling.

        The signature is checked after this returns, so everything it reads is
        hostile until then -- including its length.
        """

        if not url:
            raise release_manifest.ManifestError("the release names no manifest to download")
        request = urllib.request.Request(url, headers={"User-Agent": "PiTrac"})
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
            return response.read(release_manifest.MAX_MANIFEST_BYTES + 1)

    def download(
        self,
        url: str,
        dest_dir: Path,
        *,
        max_bytes: int = MAX_PACKAGE_BYTES,
        timeout: float = DOWNLOAD_TIMEOUT,
        cancel_event: Optional[threading.Event] = None,
        progress: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> Path:
        """Stream a package into ``dest_dir``, never into the running app.

        ``dest_dir`` is always a staging location outside any application
        bundle or install directory -- the caller (companion.self_update)
        decides where that is; this only ever writes inside it.
        """

        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        destination = dest_dir / "download.part"
        request = urllib.request.Request(url, headers={"User-Agent": "PiTrac"})
        written = 0
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                length = response.headers.get("Content-Length")
                expected_length = int(length) if length is not None else None
                if expected_length is not None and expected_length > max_bytes:
                    raise ValueError("the published package is larger than expected")
                with open(destination, "wb") as handle:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise InterruptedError("the download was cancelled")
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError("the download is larger than expected")
                        handle.write(chunk)
                        if progress is not None:
                            progress(written, expected_length)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if written < MIN_PACKAGE_BYTES:
            destination.unlink(missing_ok=True)
            raise ValueError("the downloaded file is too small to be a real package")
        return destination

    @staticmethod
    def verify(path: Path, expected_sha256: str) -> bool:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(expected_sha256 or "")):
            return False
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha256


# --- Updating an installation that came from an archive --------------------
#
# The enclosure is installed by copying a directory into /usr/lib, so it has no
# git checkout to pull and cannot replace itself the way a source tree can.
# What it can do is fetch the release archive, unpack it somewhere else,
# satisfy itself that what arrived is real, and swap it into place.
#
# The swap is the part that has to be right. A half-written application
# directory on a machine with no keyboard and no screen is not a bug report,
# it is a brick, so the new copy is assembled completely before anything is
# moved, the old one is kept until the new one is in place, and a failure at
# any point leaves the running version untouched.

#: The file in a release that holds the application, as build-app.sh names it.
ARCHIVE_SUFFIX = ".pyz"

#: A release archive far outside this range is not one of ours.
#: Refuse an archive the release publishes no checksum for. GitHub states a
#: sha256 for every asset, so a release without one is not a release this
#: enclosure should be installing. The failure direction is deliberate: an
#: enclosure that declines to update is recoverable, one that installed
#: something unverified is not.
REQUIRE_DIGEST = True

MIN_ARCHIVE_BYTES = 50 * 1024
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024


def _requested_tag(value: str) -> str:
    """A validated release tag in the form GitHub publishes."""

    text = str(value or "").strip()
    if parse(text) is None:
        raise ValueError("The requested release tag is not a valid version.")
    return text if text.startswith("v") else "v" + text


def _archive_name(tag: str) -> str:
    return "PiTrac-Easy-Connect-{}{}".format(str(tag).lstrip("v"), ARCHIVE_SUFFIX)


def _let_others_read(root: Path) -> None:
    """Open the staged tree just far enough for an unprivileged check.

    mkdtemp makes its directory 0700, which is right for a secret and wrong
    here: the enclosure runs as root and deliberately drops to ``nobody`` to
    run the downloaded code before trusting it. ``nobody`` could not traverse
    into 0700, so the check failed on every real enclosure and every valid
    update was rejected -- while passing in tests, where the check runs as the
    same user that unpacked the files.

    Readable and traversable, never writable: the account running the probe
    must not be able to edit the code that is about to be installed as root.
    """

    try:
        os.chmod(root, 0o755)
        for parent, directories, files in os.walk(root):
            for name in directories:
                os.chmod(os.path.join(parent, name), 0o755)
            for name in files:
                os.chmod(os.path.join(parent, name), 0o644)
    except OSError:
        # Losing the relaxation is survivable on a system where the check
        # never drops privileges in the first place.
        pass


def _fsync_directory(path: Path) -> None:
    """Make a rename in this directory survive power loss."""

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


class ArchiveUpdater:
    """Replaces an installed copy from a published release archive."""

    def __init__(
        self,
        installed: str,
        app_dir: Path,
        repository: str = REPOSITORY,
        link_path: Optional[Path] = None,
        releases_dir: Optional[Path] = None,
        restart: Optional[Callable[[], None]] = None,
        healthy: Optional[Callable[[], bool]] = None,
        verify: Optional[Callable[[Path], bool]] = None,
        fetch: Optional[Callable[[str], bytes]] = None,
        api_base: str = None,
        arm_guard: Optional[Callable[..., Optional[Callable[[], None]]]] = None,
    ):
        self.installed = installed
        self.app_dir = Path(app_dir)
        #: When the installation uses versioned releases behind a symlink,
        #: these say where. Set, an update becomes a new sibling release and a
        #: symlink move rather than an edit of the directory being run from.
        self.link_path = Path(link_path) if link_path else None
        self.releases_dir = Path(releases_dir) if releases_dir else None
        self.repository = repository
        self._restart = restart
        #: Asked after the restart. Returning False rolls the update back.
        #: On the enclosure this cannot be used, because the restart ends this
        #: process -- see ``verify``.
        self._healthy = healthy
        #: Asked about the *staged* copy before anything is swapped. Necessary
        #: but not sufficient: it catches a truncated download or an import
        #: that no longer resolves, and cannot catch anything that only happens
        #: once the real service runs. ``arm_guard`` is what covers the rest.
        self._verify = verify
        #: Called just before the symlink moves, with everything an independent
        #: component needs to put the previous release back. It returns a
        #: callback to run once the link actually points at the candidate, or
        #: None. Kept as a plain callable so this module, which the desktop
        #: also imports, needs to know nothing about the enclosure's guard.
        self._arm_guard = arm_guard
        self._fetch = fetch or _download
        self._api = (api_base or API_BASE).rstrip("/")
        self._lock = threading.RLock()

    def check(self, target_tag: Optional[str] = None) -> UpdateStatus:
        try:
            requested = _requested_tag(target_tag) if target_tag else ""
        except ValueError as exc:
            return UpdateStatus(self.installed, PACKAGED, detail=str(exc))
        try:
            release = self._release(requested or None)
        except Exception:
            return UpdateStatus(self.installed, PACKAGED, detail="Could not check for updates.")

        tag = str(release.get("tag_name") or "")
        if requested and compare(tag, requested) != 0:
            return UpdateStatus(
                self.installed, PACKAGED, latest=requested,
                detail="The update service did not return the requested release {}.".format(
                    requested
                ),
            )
        if not tag or not is_newer(tag, self.installed):
            return UpdateStatus(self.installed, PACKAGED, latest=tag or self.installed,
                                detail="Up to date.")
        if not self._archive_url(release, tag):
            return UpdateStatus(
                self.installed, PACKAGED, latest=tag, available=True, can_apply=False,
                detail=(
                    "Version {} is available, but it has no matching Pi-service archive "
                    "to install."
                ).format(tag),
                download_url=str(release.get("html_url") or ""),
            )
        return UpdateStatus(
            self.installed, PACKAGED, latest=tag, available=True, can_apply=True,
            detail="Version {} is ready to install.".format(tag),
            download_url=str(release.get("html_url") or ""),
        )

    def apply(self, target_tag: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                requested = _requested_tag(target_tag) if target_tag else ""
            except ValueError as exc:
                return {"applied": False, "detail": str(exc)}
            try:
                release = self._release(requested or None)
            except Exception as exc:
                return {"applied": False, "detail": "Could not reach the update service: {}".format(exc)}

            tag = str(release.get("tag_name") or "")
            if requested and compare(tag, requested) != 0:
                return {
                    "applied": False,
                    "detail": "The update service did not return the requested release {}.".format(
                        requested
                    ),
                }
            if not tag or not is_newer(tag, self.installed):
                return {"applied": False, "detail": "Already up to date."}

            url = self._archive_url(release, tag)
            if not url:
                return {
                    "applied": False,
                    "detail": "That release has no matching Pi-service archive to install.",
                }

            try:
                blob = self._fetch(url)
            except Exception as exc:
                return {"applied": False, "detail": "The download did not finish: {}".format(exc)}

            if not MIN_ARCHIVE_BYTES <= len(blob) <= MAX_ARCHIVE_BYTES:
                return {"applied": False,
                        "detail": "The downloaded file is not the right size to be an update."}

            try:
                manifest = release_manifest.fetch_manifest(release, self._fetch, tag=tag)
            except release_manifest.ManifestError as exc:
                return {"applied": False, "detail": str(exc)}
            if manifest is not None:
                refusal = release_manifest.check_pi_supported(
                    manifest, version=self.installed,
                    python_version="{}.{}".format(*sys.version_info[:2]),
                )
                if refusal:
                    return {"applied": False, "detail": refusal}

            expected = self._archive_digest(release, tag, manifest=manifest)
            if expected:
                actual = hashlib.sha256(blob).hexdigest()
                if actual != expected:
                    return {
                        "applied": False,
                        "detail": "The download did not match the checksum this "
                                  "release publishes, so it was not installed.",
                    }
            elif REQUIRE_DIGEST:
                return {
                    "applied": False,
                    "detail": "That release publishes no checksum for its archive, "
                              "so it was not installed.",
                }

            try:
                staged = self._unpack(blob)
            except Exception as exc:
                return {"applied": False, "detail": "The update could not be unpacked: {}".format(exc)}

            inside = self._version_inside(staged)
            if inside != tag.lstrip("v"):
                shutil.rmtree(staged.parent.parent, ignore_errors=True)
                return {
                    "applied": False,
                    "detail": "That release is labelled {} but contains {}, so it "
                              "was not installed.".format(tag, inside or "no version"),
                }

            if self._verify is not None and not self._verify(staged):
                shutil.rmtree(staged.parent.parent, ignore_errors=True)
                return {
                    "applied": False,
                    "detail": "That version would not start on this machine, so "
                              "nothing was changed.",
                }

            releases = self._uses_releases()
            try:
                previous = (self._swap_release(staged, inside, tag=tag,
                                               digest=self._archive_digest(release, tag) or "")
                            if releases else self._swap(staged))
            except Exception as exc:
                shutil.rmtree(staged.parent, ignore_errors=True)
                return {"applied": False,
                        "detail": "The update could not be installed: {}".format(exc)}

            # The new copy is in place but has not run yet. Restart, then ask
            # it whether it came back. If it did not, put the old one back:
            # an enclosure that will not start is not a failed update, it is a
            # machine with no keyboard that nobody can reach.
            if self._restart:
                try:
                    self._restart()
                except Exception as exc:
                    (self._roll_back_release if releases else self._roll_back)(previous)
                    return {"applied": False,
                            "detail": "The update was undone: it could not be started ({})".format(exc)}

            if self._healthy is not None and not self._healthy():
                (self._roll_back_release if releases else self._roll_back)(previous)
                if self._restart:
                    try:
                        self._restart()
                    except Exception:
                        pass
                return {"applied": False, "rolledBack": True,
                        "detail": "Version {} would not start, so the previous "
                                  "version was put back.".format(tag)}

            # The previous release is deliberately kept when there is one:
            # it is the thing to go back to if the new version misbehaves
            # later, and disk is cheaper than an unreachable enclosure.
            if not releases:
                shutil.rmtree(previous, ignore_errors=True)
            else:
                # The previous release is deliberately kept -- it is the thing
                # to go back to -- but only the previous one.
                self._prune_releases()
            return {"applied": True, "version": tag,
                    "detail": "Updated to {}. PiTrac is restarting.".format(tag)}

    # --- The pieces ------------------------------------------------------

    def _release(self, target_tag: Optional[str] = None) -> Dict[str, Any]:
        endpoint = (
            "releases/tags/{}".format(urllib.parse.quote(target_tag, safe=""))
            if target_tag
            else "releases/latest"
        )
        request = urllib.request.Request(
            "{}/repos/{}/{}".format(self._api, self.repository, endpoint),
            headers={"Accept": "application/vnd.github+json", "User-Agent": "PiTrac"},
        )
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
            return jsontext.loads(response.read().decode("utf-8"))

    @staticmethod
    def _archive_url(release: Dict[str, Any], tag: str = "") -> str:
        expected = _archive_name(tag) if tag else ""
        for asset in release.get("assets") or []:
            name = str(asset.get("name") or "")
            if name == expected or (not expected and name.endswith(ARCHIVE_SUFFIX)):
                return str(asset.get("browser_download_url") or "")
        return ""

    @staticmethod
    def _archive_digest(release: Dict[str, Any], tag: str = "", manifest=None) -> str:
        """The sha256 to hold the archive to.

        A signed manifest wins when the release publishes one: it is the only
        digest that is authenticated rather than merely co-located. Without
        one, the release API's own digest still means the download has to
        match what the release says it contains rather than merely arriving
        over TLS -- which is better than nothing and less than a signature.
        """

        expected = _archive_name(tag) if tag else ""
        if manifest is not None:
            name = expected or str(manifest.get("pi", {}).get("asset") or "")
            return release_manifest.expected_digest(manifest, name)
        for asset in release.get("assets") or []:
            name = str(asset.get("name") or "")
            if name == expected or (not expected and name.endswith(ARCHIVE_SUFFIX)):
                digest = str(asset.get("digest") or "")
                return digest[7:] if digest.startswith("sha256:") else ""
        return ""

    def _unpack(self, blob: bytes) -> Path:
        """Unpack into a staging directory, and check it looks like the app.

        A zipapp is a zip file, so this is also where a truncated download or
        something that is not an update at all gets caught, before anything on
        the machine has been touched.
        """

        import zipfile

        staging = Path(tempfile.mkdtemp(prefix="pitrac-update-"))
        archive = staging / "download.pyz"
        archive.write_bytes(blob)

        unpacked = staging / "new"
        with zipfile.ZipFile(archive) as zipped:
            bad = zipped.testzip()
            if bad:
                raise ValueError("the archive is damaged at {}".format(bad))
            root = unpacked.resolve()
            for member in zipped.namelist():
                target = (unpacked / member).resolve()
                # relative_to, not a string prefix: "/tmp/new-evil" starts with
                # "/tmp/new" and would have passed a prefix comparison.
                try:
                    target.relative_to(root)
                except ValueError:
                    raise ValueError("the archive tried to write outside itself")
            zipped.extractall(unpacked)

        package = unpacked / "pitrac_easy_connect"
        if not (package / "__init__.py").exists():
            raise ValueError("the archive does not contain the application")
        if not (package / "pi" / "service.py").exists():
            raise ValueError("the archive is missing the enclosure service")
        _let_others_read(staging)
        return package

    @staticmethod
    def _version_inside(package: Path) -> str:
        """The version the archive actually contains.

        The release tag is a label somebody typed. Trusting it meant an
        archive tagged 9.9.9 that held 1.1.0 was reported as 9.9.9 installed
        while 1.1.0 was what actually landed, and the enclosure then believed
        it was up to date.
        """

        import re as _re

        try:
            source = (package / "__init__.py").read_text()
        except OSError:
            return ""
        found = _re.search(r'__version__ = "([^"]+)"', source)
        return found.group(1) if found else ""

    def _uses_releases(self) -> bool:
        return bool(
            self.link_path and self.releases_dir
            and self.link_path.is_symlink() and self.releases_dir.is_dir()
        )

    def _swap_release(self, staged: Path, version: str, *, tag: str = "",
                      digest: str = "") -> Path:
        """Install as a new release and move the symlink onto it.

        The running release is never touched, so there is no moment where the
        application directory is missing and nothing to undo if the new one
        will not start -- the old release is still there and the symlink can
        simply be pointed back at it.

        Pointing it back is the part this process cannot do. Restarting the
        enclosure's service ends this process, so the guard is armed first:
        the candidate tree and a journal naming both releases are on the card,
        and an independent component is registered to run at the next boot,
        before the link is allowed to move.
        """

        previous = self.link_path.resolve()
        destination = self._new_release_dir(version)
        shutil.move(str(staged), str(destination / "pitrac_easy_connect"))

        swapped = None
        if self._arm_guard is not None:
            swapped = self._arm_guard(
                previous=previous, candidate=destination,
                installed_version=self.installed, expected_version=version,
                expected_tag=tag or ("v" + version), asset_sha256=digest,
            )

        temporary = self.link_path.with_name(self.link_path.name + ".new")
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()
        temporary.symlink_to(destination)
        os.replace(temporary, self.link_path)
        _fsync_directory(self.link_path.parent)
        if swapped is not None:
            swapped()
        shutil.rmtree(staged.parent.parent, ignore_errors=True)
        return previous

    def _new_release_dir(self, version: str) -> Path:
        """A release directory of its own, whatever else is already there.

        The name used to be the version and the time in whole seconds, and a
        directory of that name was deleted before being recreated. Two updates
        inside one second therefore had the second one delete the first --
        which, when the first is the release the symlink points at, is the
        running copy. Rare, but the consequence is an enclosure with no
        software and nobody at the keyboard.
        """

        self.releases_dir.mkdir(parents=True, exist_ok=True)
        prefix = "{}-{}-".format(version, int(time.time()))
        destination = Path(tempfile.mkdtemp(prefix=prefix, dir=str(self.releases_dir)))
        # mkdtemp is 0700; releases are read by the service and are not secret.
        os.chmod(destination, 0o755)
        return destination

    def _prune_releases(self, keep: int = 2) -> None:
        """Keep the running release and the one to go back to; drop the rest.

        Installing by hand has always kept two. Updating over the air kept
        every release ever installed, so an enclosure that updated regularly
        filled its card with copies of software it would never run again.
        """

        try:
            current = self.link_path.resolve()
        except OSError:
            return
        try:
            releases = [path for path in self.releases_dir.iterdir() if path.is_dir()]
        except OSError:
            return
        # Newest first, and never the one being run, whatever its age.
        releases.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        keeping = [path for path in releases if path != current][: max(keep - 1, 0)]
        for path in releases:
            if path == current or path in keeping:
                continue
            shutil.rmtree(path, ignore_errors=True)

    def _roll_back_release(self, previous: Path) -> None:
        if not previous or not previous.exists():
            return
        temporary = self.link_path.with_name(self.link_path.name + ".new")
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()
        temporary.symlink_to(previous)
        os.replace(temporary, self.link_path)

    def _swap(self, staged: Path) -> Path:
        """Put the new copy in place, keeping the old one until it has proved
        itself. Returns where the old one is, so it can be rolled back to."""

        target = self.app_dir / "pitrac_easy_connect"
        previous = self.app_dir / "pitrac_easy_connect.previous"

        shutil.rmtree(previous, ignore_errors=True)
        if target.exists():
            os.replace(target, previous)
        try:
            shutil.move(str(staged), str(target))
        except Exception:
            # Put back what was working before giving up.
            if previous.exists() and not target.exists():
                os.replace(previous, target)
            raise
        shutil.rmtree(staged.parent.parent, ignore_errors=True)
        return previous

    def _roll_back(self, previous: Path) -> None:
        """Undo a swap whose result would not start."""

        target = self.app_dir / "pitrac_easy_connect"
        if not previous.exists():
            return
        shutil.rmtree(target, ignore_errors=True)
        os.replace(previous, target)


def _download(url: str, timeout: float = 120.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "PiTrac"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_ARCHIVE_BYTES + 1)
