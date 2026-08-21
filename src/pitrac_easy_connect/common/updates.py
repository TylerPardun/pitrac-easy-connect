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

import json
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

#: Where releases are published. Set once the repository exists.
REPOSITORY = "PiTracLM-EasyConnect/pitrac-easy-connect"
RELEASES_API = "https://api.github.com/repos/{}/releases/latest"
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
