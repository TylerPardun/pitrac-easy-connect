"""The trained models are not ours to pass on.

PiTracLM's `LICENSE.MODEL.md` grants a licence that is explicitly
non-transferable, so an enclosure that changes hands must not carry them. These
tests pin the parts of that which are code rather than paperwork.
"""

from pathlib import Path

from pitrac_easy_connect.pi import ml_models


def build_pi(tmp_path, with_history=True):
    """A machine that has had PiTrac built on it, models and all."""

    installed = tmp_path / "etc" / "pitrac" / "models"
    for name in ml_models.MODEL_NAMES:
        directory = installed / name
        directory.mkdir(parents=True)
        (directory / "best.ncnn.bin").write_bytes(b"weights" * 100)
        (directory / "best.ncnn.param").write_text("graph")

    home = tmp_path / "home" / "pitracuser"
    repo = home / "PiTrac"
    repo_models = repo / ml_models.REPO_MODELS_SUBPATH
    for name in ml_models.MODEL_NAMES:
        directory = repo_models / name
        directory.mkdir(parents=True)
        (directory / "best.ncnn.bin").write_bytes(b"weights" * 100)
    if with_history:
        (repo / ".git" / "objects").mkdir(parents=True)
        (repo / ".git" / "objects" / "pack").write_bytes(b"the models are in here too")
    return installed, home, repo


def test_every_copy_is_found(tmp_path):
    installed, home, _repo = build_pi(tmp_path)
    found = ml_models.status(installed_dir=installed, home=str(home))
    assert found["installed"]
    assert found["repoCopy"]
    assert found["repoHistory"]


def test_handing_the_enclosure_on_removes_all_of_them(tmp_path):
    installed, home, repo = build_pi(tmp_path)

    result = ml_models.remove(installed_dir=installed, home=str(home))

    assert result["clear"], result["remaining"]
    for name in ml_models.MODEL_NAMES:
        assert not (installed / name).exists()
    assert not repo.exists()


def test_the_git_history_goes_too(tmp_path):
    """Deleting the working copy leaves the models one checkout away.

    The clone carries them in its history, so a wipe that only cleared
    ``ml_models/`` would hand the next owner a recoverable copy.
    """

    installed, home, repo = build_pi(tmp_path)
    ml_models.remove(installed_dir=installed, home=str(home))
    assert not (repo / ".git").exists()


def test_a_machine_with_no_source_clone_is_still_cleaned(tmp_path):
    installed, home, repo = build_pi(tmp_path)
    import shutil

    shutil.rmtree(repo)

    result = ml_models.remove(installed_dir=installed, home=str(home))
    assert result["clear"]


def test_removal_is_safe_to_repeat(tmp_path):
    installed, home, _repo = build_pi(tmp_path)
    ml_models.remove(installed_dir=installed, home=str(home))
    again = ml_models.remove(installed_dir=installed, home=str(home))
    assert again["clear"] and again["removed"] == []


def test_the_licence_situation_is_written_down():
    """A future reader has to be able to find out why this code exists.

    It lives in the module rather than in a document, so it travels with the
    code it explains and cannot be left behind when the docs change.
    """

    source = (
        Path(__file__).resolve().parent.parent
        / "src" / "pitrac_easy_connect" / "pi" / "ml_models.py"
    ).read_text().lower()
    explanation = source.split('"""')[1]
    for point in ("non-transferable", "commercial", "written permission"):
        assert point in explanation
    # The git-history point is the non-obvious one; losing it would make the
    # removal look like overreach and invite someone to "fix" it.
    assert "history" in explanation


def test_the_owner_can_reach_the_transfer_from_the_setup_page():
    """It existed only as an API call, so nobody selling a unit could run it."""

    source = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    portal_page = (source / "pi" / "portal_page.py").read_text()
    portal = (source / "pi" / "portal.py").read_text()

    assert 'id="newOwner"' in portal_page
    assert '"/api/new-owner"' in portal
    # It is destructive and cannot be undone, so it must ask first and must say
    # the models are going.
    press = portal_page.split('$("newOwner").addEventListener')[1].split("}));")[0]
    assert "confirm(" in press
    assert "models" in press and "cannot be undone" in press
