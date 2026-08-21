"""The two trained models PiTrac needs, and why they are handled separately.

PiTrac itself is GPL-2.0. The models are not: `LICENSE.MODEL.md` in the PiTrac
repository puts them under a separate proprietary agreement that forbids
redistributing them, transferring them to anyone else, or using them in a
commercial product without written permission from PiTracLM.

Two consequences shape this module.

**They must come off before an enclosure changes hands.** The licence is
non-transferable, so handing on a machine with the models on it is a breach even
between two hobbyists. Whoever receives it has to obtain their own copy, under
their own acceptance of the terms.

**Removing the installed copy is not enough.** A Pi that has had PiTrac built on
it carries the models three times over: installed under ``/etc/pitrac/models``,
in the working tree of the source clone, and inside that clone's git history.
Deleting the first two leaves the third recoverable with one command, which is
why this removes the clone outright rather than tidying files inside it.

This module never downloads anything. Fetching the models at first boot would
cure the redistribution problem, but not the separate clause forbidding
commercial use without written permission, so it is not a way around that.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Where PiTrac's installer puts the models for the launch monitor to load.
INSTALLED_DIR = Path(os.environ.get("PITRAC_MODELS_DIR", "/etc/pitrac/models"))

#: The model directories PiTrac expects to find, by name.
MODEL_NAMES = ("yolo26-ball-detector", "spin-predictor")

#: Where the models sit inside a clone of the PiTrac repository.
REPO_MODELS_SUBPATH = Path("Software/LMSourceCode/ml_models")

#: Places a PiTrac clone is normally found. Searched in order.
REPO_CANDIDATES = ("~/PiTrac", "~/pitrac", "/opt/PiTrac", "/usr/src/PiTrac")


def find_repo(candidates=REPO_CANDIDATES, home: Optional[str] = None) -> Optional[Path]:
    """The PiTrac source clone, if this Pi has one."""

    for candidate in candidates:
        path = Path(candidate)
        if home and candidate.startswith("~"):
            path = Path(home) / candidate[2:]
        else:
            path = path.expanduser()
        if (path / REPO_MODELS_SUBPATH).exists() or (path / ".git").exists():
            return path
    return None


def _files_under(directory: Path) -> List[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*") if path.is_file())


def status(
    installed_dir: Path = INSTALLED_DIR,
    repo: Optional[Path] = None,
    home: Optional[str] = None,
) -> Dict[str, Any]:
    """Where copies of the models exist on this machine.

    Reported so the owner can see what a transfer would have to remove, and so
    the self-test can say plainly when PiTrac cannot measure a ball because the
    models are absent.
    """

    repo = repo if repo is not None else find_repo(home=home)
    installed = {
        name: len(_files_under(installed_dir / name)) for name in MODEL_NAMES
    }
    repo_models = repo / REPO_MODELS_SUBPATH if repo else None
    return {
        "installed": all(count > 0 for count in installed.values()),
        "installedDir": str(installed_dir),
        "installedFiles": installed,
        "repo": str(repo) if repo else "",
        "repoCopy": bool(repo_models and _files_under(repo_models)),
        "repoHistory": bool(repo and (repo / ".git").is_dir()),
    }


def remove(
    installed_dir: Path = INSTALLED_DIR,
    repo: Optional[Path] = None,
    home: Optional[str] = None,
    drop_repo: bool = True,
) -> Dict[str, Any]:
    """Take every copy of the models off this machine.

    ``drop_repo`` removes the whole source clone rather than the model files
    inside it. That is deliberate: the models are in the clone's history, so
    deleting only the working copy leaves them one ``git checkout`` away. The
    clone is not needed to run PiTrac — the built software lives elsewhere —
    and the next owner can clone it again and accept the model licence
    themselves.
    """

    repo = repo if repo is not None else find_repo(home=home)
    removed: List[str] = []

    for name in MODEL_NAMES:
        target = installed_dir / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(str(target))

    if repo and drop_repo and repo.exists():
        shutil.rmtree(repo, ignore_errors=True)
        removed.append(str(repo))
    elif repo:
        models = repo / REPO_MODELS_SUBPATH
        if models.exists():
            shutil.rmtree(models, ignore_errors=True)
            removed.append(str(models))

    after = status(installed_dir=installed_dir, repo=None, home=home)
    return {
        "removed": removed,
        "clear": not after["installed"] and not after["repoCopy"] and not after["repoHistory"],
        "remaining": after,
    }
