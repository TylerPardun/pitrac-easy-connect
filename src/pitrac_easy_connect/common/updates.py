"""Telling you when there is a newer version, and installing it when asked.

The point is that every enclosure and every PC ends up on the same release
rather than each carrying whatever was current the day it was set up.

Two kinds of installation exist and they update differently:

**A source checkout** — the repository cloned with git. Updating is ``git pull``,
which is how this is normally run during development and by anyone who installed
from source.

**A packaged build** — the ``.exe`` or ``.pyz`` someone downloaded. There is no
repository to pull, so the newest published release is looked up and the user is
pointed at the download.

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
import os
import shutil
import tempfile
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .versions import is_newer

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
            return json.loads(response.read().decode("utf-8"))

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
        #: Asked about the *staged* copy before anything is swapped. This is
        #: the check that actually protects an enclosure: restarting kills the
        #: updater, so a decision made after it can never be acted on.
        self._verify = verify
        self._fetch = fetch or _download
        self._api = (api_base or API_BASE).rstrip("/")
        self._lock = threading.RLock()

    def check(self) -> UpdateStatus:
        try:
            release = self._release()
        except Exception:
            return UpdateStatus(self.installed, PACKAGED, detail="Could not check for updates.")

        tag = str(release.get("tag_name") or "")
        if not tag or not is_newer(tag, self.installed):
            return UpdateStatus(self.installed, PACKAGED, latest=tag or self.installed,
                                detail="Up to date.")
        if not self._archive_url(release):
            return UpdateStatus(
                self.installed, PACKAGED, latest=tag, available=True, can_apply=False,
                detail="Version {} is available, but it has no archive to install.".format(tag),
                download_url=str(release.get("html_url") or ""),
            )
        return UpdateStatus(
            self.installed, PACKAGED, latest=tag, available=True, can_apply=True,
            detail="Version {} is ready to install.".format(tag),
            download_url=str(release.get("html_url") or ""),
        )

    def apply(self) -> Dict[str, Any]:
        with self._lock:
            try:
                release = self._release()
            except Exception as exc:
                return {"applied": False, "detail": "Could not reach the update service: {}".format(exc)}

            tag = str(release.get("tag_name") or "")
            if not tag or not is_newer(tag, self.installed):
                return {"applied": False, "detail": "Already up to date."}

            url = self._archive_url(release)
            if not url:
                return {"applied": False, "detail": "That release has nothing to install."}

            try:
                blob = self._fetch(url)
            except Exception as exc:
                return {"applied": False, "detail": "The download did not finish: {}".format(exc)}

            if not MIN_ARCHIVE_BYTES <= len(blob) <= MAX_ARCHIVE_BYTES:
                return {"applied": False,
                        "detail": "The downloaded file is not the right size to be an update."}

            expected = self._archive_digest(release)
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
                previous = (self._swap_release(staged, inside) if releases
                            else self._swap(staged))
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

    def _release(self) -> Dict[str, Any]:
        request = urllib.request.Request(
            "{}/repos/{}/releases/latest".format(self._api, self.repository),
            headers={"Accept": "application/vnd.github+json", "User-Agent": "PiTrac"},
        )
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _archive_url(release: Dict[str, Any]) -> str:
        for asset in release.get("assets") or []:
            name = str(asset.get("name") or "")
            if name.endswith(ARCHIVE_SUFFIX):
                return str(asset.get("browser_download_url") or "")
        return ""

    @staticmethod
    def _archive_digest(release: Dict[str, Any]) -> str:
        """The sha256 the release API states for the archive, if it states one.

        The listing and the download come from different hosts: the API is
        api.github.com, the bytes come from a content host. Checking the bytes
        against the digest the API gave means the download has to match what
        the release actually says it contains, not merely arrive over TLS.
        """

        for asset in release.get("assets") or []:
            name = str(asset.get("name") or "")
            if name.endswith(ARCHIVE_SUFFIX):
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

    def _swap_release(self, staged: Path, version: str) -> Path:
        """Install as a new release and move the symlink onto it.

        The running release is never touched, so there is no moment where the
        application directory is missing and nothing to undo if the new one
        will not start -- the old release is still there and the symlink can
        simply be pointed back at it.
        """

        previous = self.link_path.resolve()
        destination = self._new_release_dir(version)
        shutil.move(str(staged), str(destination / "pitrac_easy_connect"))

        temporary = self.link_path.with_name(self.link_path.name + ".new")
        if temporary.is_symlink() or temporary.exists():
            temporary.unlink()
        temporary.symlink_to(destination)
        os.replace(temporary, self.link_path)
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
