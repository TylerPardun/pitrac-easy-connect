"""The kit: one folder that installs everything, with no internet.

The Windows half can only be built on Windows, so what can be checked here is
checked here: that the source survives the trip, that the batch file is one
Windows can read, and that trying an installer out cannot hurt a real one.
"""

import importlib.util
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "make_installer", ROOT / "packaging" / "make_installer.py")
make = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make)

INNO = (ROOT / "packaging" / "windows-installer.iss").read_text(encoding="utf-8")
BATCH = ROOT / "Build Windows Installer.cmd"


@pytest.fixture(scope="module")
def unpacked(tmp_path_factory):
    folder = tmp_path_factory.mktemp("kit")
    make.write_source(folder / "source.zip")
    with zipfile.ZipFile(folder / "source.zip") as archive:
        archive.extractall(folder)
    return folder / "PiTrac-Easy-Connect"


# --- The source -------------------------------------------------------------


@pytest.mark.parametrize("needed", [
    "packaging/pi/install.sh", "packaging/pi/pitrac-easy-connect.service",
    "packaging/make_installer.py", "packaging/windows-installer.iss", "packaging/check.sh",
    "packaging/build-requirements.txt", "Build Windows Installer.cmd", "LICENSE", "NOTICE.md",
    "README.md", "src/pitrac_easy_connect/pi/app.py", "src/pitrac_easy_connect/companion/app.py",
])
def test_the_kit_has_everything_both_other_machines_need(unpacked, needed):
    assert (unpacked / needed).is_file()


def test_nothing_private_or_built_goes_in_the_kit(unpacked):
    names = [p.relative_to(unpacked).as_posix() for p in unpacked.rglob("*") if p.is_file()]
    for name in names:
        assert not re.search(r"(^|/)(\.git|\.check|dist|build|__pycache__)/|\.pyc$|\.pem$|\.p12$", name), name


def test_the_pi_gets_scripts_it_can_run(unpacked):
    for script in unpacked.rglob("*.sh"):
        assert b"\r" not in script.read_bytes(), script.name
    with zipfile.ZipFile(unpacked.parent / "source.zip") as archive:
        info = archive.getinfo("PiTrac-Easy-Connect/packaging/pi/install.sh")
        assert (info.external_attr >> 16) & 0o111, "not executable"


def test_line_endings_are_put_right_whichever_machine_made_the_kit():
    assert make.with_line_endings("a.sh", b"one\r\ntwo\r\n") == b"one\ntwo\n"
    assert make.with_line_endings("a.cmd", b"one\ntwo\n") == b"one\r\ntwo\r\n"
    assert make.with_line_endings("a.cmd", b"one\r\ntwo\r\n") == b"one\r\ntwo\r\n"
    assert make.with_line_endings("a.png", b"\r\n\n") == b"\r\n\n"


def test_the_same_source_makes_the_same_file(tmp_path):
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    make.write_source(first)
    make.write_source(second)
    assert first.read_bytes() == second.read_bytes()


def test_the_unpacked_source_can_make_the_kit_again(unpacked, tmp_path):
    """On Windows there is no checkout, only what came out of the zip."""

    (unpacked / "dist").mkdir(exist_ok=True)
    (unpacked / "dist" / "old.exe").write_bytes(b"x")
    (unpacked / "src" / "__pycache__").mkdir(exist_ok=True)
    (unpacked / "src" / "__pycache__" / "a.pyc").write_bytes(b"x")
    again = set(make.source_files(unpacked))
    assert again == set(make.source_files(ROOT))
    assert make.version_of(unpacked) == make.version_of(ROOT)


# --- What it says -----------------------------------------------------------


@pytest.fixture
def kit(tmp_path):
    folder = tmp_path / "kit"
    folder.mkdir()
    return folder


def test_the_instructions_describe_what_is_actually_there(kit):
    make.finish_kit(kit, "1.2.3")
    text = (kit / "READ ME FIRST.txt").read_text(encoding="utf-8")
    assert text.count("Not in this kit yet") == 2

    (kit / make.installer_name("1.2.3", "Darwin", "arm64")).write_bytes(b"mac")
    (kit / make.installer_name("1.2.3", "Windows", "x86_64")).write_bytes(b"win")
    make.finish_kit(kit, "1.2.3")
    text = (kit / "READ ME FIRST.txt").read_text(encoding="utf-8")
    assert "Not in this kit yet" not in text
    for installer in kit.iterdir():
        if installer.suffix in (".dmg", ".exe", ".zip"):
            assert '"{}"'.format(installer.name) in text
    assert make.tested_pitrac() in text
    assert "Run anyway" in text


def test_every_file_worth_checking_is_listed(kit):
    (kit / make.installer_name("1.2.3", "Windows", "x86_64")).write_bytes(b"win")
    make.finish_kit(kit, "1.2.3")
    sums = (kit / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert len(sums.splitlines()) == 2
    assert "(Windows).exe" in sums and "source.zip" in sums


def test_the_mac_note_says_what_macos_now_does():
    assert "Open Anyway" in make.MAC_NOTE
    assert "ight-click" not in make.MAC_NOTE
    assert "ight-click" not in (ROOT / "README.md").read_text(encoding="utf-8")


# --- Refusing early ---------------------------------------------------------


@pytest.mark.parametrize("version, works", [
    ((3, 9, 1), False), ((3, 10, 0), True), ((3, 13, 5), True), ((3, 14, 0), False),
])
def test_a_python_that_cannot_build_it_is_refused_first(version, works):
    if works:
        make.check_python(version)
    else:
        with pytest.raises(make.BuildError, match="Python 3.10 to 3.13"):
            make.check_python(version)


def test_a_failed_build_leaves_no_installer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(make, "MAC", True)
    monkeypatch.setattr(make, "WINDOWS", False)
    monkeypatch.setattr(make, "check_python", lambda: None)
    monkeypatch.setattr(make, "build_environment",
                        lambda work: (_ for _ in ()).throw(make.BuildError("no internet")))
    assert make.main(["--output", str(tmp_path)]) == 1
    assert "no internet" in capsys.readouterr().err
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


@pytest.mark.parametrize("listing, expected", [
    (["cmd LC_BUILD_VERSION\n platform 1\n    minos 11.0\n      sdk 14.0\n"], (11, 0)),
    (["cmd LC_BUILD_VERSION\n    minos 11.0\n", "cmd LC_BUILD_VERSION\n    minos 27.0\n"], (27, 0)),
    (["cmd LC_VERSION_MIN_MACOSX\n  cmdsize 16\n  version 10.13\n"], (10, 13)),
    ([], (11, 0)),
])
def test_the_macos_it_needs_is_read_from_what_was_bundled(listing, expected):
    assert make.newest_minimum(listing) == expected


# --- Windows ----------------------------------------------------------------


def test_the_batch_file_is_one_windows_can_read():
    data = BATCH.read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n")
    data.decode("ascii")
    labels = set(re.findall(rb"^:(\w+)", data, re.M))
    assert set(re.findall(rb"goto (\w+)", data)) <= labels


def test_the_batch_file_asks_before_installing_anything():
    text = BATCH.read_text()
    assert text.index("choice") < text.index("winget install")
    assert "--accept" not in text


def test_inno_setup_is_found_wherever_it_was_put(tmp_path):
    assert make.find_inno({}) is None
    mine = tmp_path / "local" / "Programs" / "Inno Setup 6"
    mine.mkdir(parents=True)
    (mine / "ISCC.exe").write_bytes(b"")
    assert make.find_inno({"LOCALAPPDATA": str(tmp_path / "local")}) == mine / "ISCC.exe"
    shared = tmp_path / "x86" / "Inno Setup 6"
    shared.mkdir(parents=True)
    (shared / "ISCC.exe").write_bytes(b"")
    assert make.find_inno({"ProgramFiles(x86)": str(tmp_path / "x86"),
                           "LOCALAPPDATA": str(tmp_path / "local")}) == shared / "ISCC.exe"


def test_trying_the_installer_cannot_touch_a_real_installation():
    """Same identity, and it would take over the real one's shortcuts and then
    remove them."""

    ids = re.findall(r"^AppId=(.+)$", INNO, re.M)
    assert len(ids) == len(set(ids)) == 2
    assert INNO.index("#ifdef TryOut") < INNO.index(ids[0]) < INNO.index("#else") < INNO.index(ids[1])
    assert ids[1] == "{{7C4F6A62-9C1B-4E2E-9E3B-8F5A2D6C1E44}", "upgrades depend on this one"
    icons = INNO[INNO.index("#ifndef TryOut"):]
    assert icons.index("[Icons]") < icons.index("#endif")
    assert INNO.count("#if") == INNO.count("#endif")


def test_the_setup_program_is_told_where_everything_is(monkeypatch, tmp_path):
    seen = []

    def fake(command, **_options):
        seen.append([str(part) for part in command])
        (tmp_path / "PiTrac Easy-Connect 1.2.3 (Windows).exe").write_bytes(b"x")
        return ""

    monkeypatch.setattr(make, "run", fake)
    make.make_setup(Path("app folder"), tmp_path / make.installer_name("1.2.3", "Windows"),
                    tmp_path, "1.2.3", Path("ISCC.exe"), "/DTryOut")
    assert "/DAppVersion=1.2.3" in seen[0] and "/DSourceDir=app folder" in seen[0]
    assert "/FPiTrac Easy-Connect 1.2.3 (Windows)" in seen[0] and "/DTryOut" in seen[0]


# --- A private build --------------------------------------------------------


def test_updates_are_on_unless_turned_off():
    """The repository is public and its releases signed, so the app updates
    itself; PITRAC_UPDATES=off is the one way to stop it."""

    from pitrac_easy_connect.common import updates

    assert updates.published({}) is True
    for off in ("off", "0", "no", "false", " OFF "):
        assert updates.published({"PITRAC_UPDATES": off}) is False
    # The test suite runs with it off, so nothing here reaches the network.
    assert updates.PUBLISHED is False


def test_a_build_with_updates_off_never_goes_looking_for_them(tmp_path, monkeypatch):
    """Off means off: no check, and nothing in front of the person about it."""

    from pitrac_easy_connect.companion.service import CompanionService

    def asked(*_args, **_kwargs):
        raise AssertionError("looked for an update")

    monkeypatch.setattr(CompanionService, "_schedule_update_check", asked)
    app = CompanionService(tmp_path / "c.json", discovery_port=0, updates_published=False)
    try:
        app.trigger_update_check()
        assert app.check_for_updates()["checkStarted"] is False
        status = app.status()["update"]
        assert status["desktop"]["state"] == "idle"
        assert "installer" in status["detail"]
    finally:
        app.close()


def test_a_private_build_says_when_the_two_halves_differ(tmp_path):
    from pitrac_easy_connect.companion.service import CompanionService

    app = CompanionService(tmp_path / "c.json", discovery_port=0, updates_published=False)
    try:
        assert app._private_update_plan(app.version).phase == "private"
        plan = app._private_update_plan("0.9.1")
        assert plan.phase == "blocked" and not plan.can_update_pi
        assert "0.9.1" in plan.detail and app.version in plan.detail
    finally:
        app.close()


if sys.platform == "win32":
    def test_the_batch_file_runs_to_its_first_question():
        import subprocess

        done = subprocess.run(["cmd", "/c", str(BATCH), "--help"], input="\n",
                              capture_output=True, text=True, timeout=60)
        assert "usage" in done.stdout or "Python 3.13" in done.stdout


def test_rebuilding_never_erases_a_filled_in_owner_card(kit):
    """It may be the only copy of the way back in."""

    make.finish_kit(kit, "1.2.3")
    card = kit / "Owner card.txt"
    assert "Setup password" in card.read_text(encoding="utf-8")
    card.write_text("Setup password: ABCD", encoding="utf-8")
    make.finish_kit(kit, "1.2.3")
    assert card.read_text(encoding="utf-8") == "Setup password: ABCD"
