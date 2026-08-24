"""Filesystem and subprocess coverage for the safe desktop update contract.

The old tests treated arbitrary temporary directories as replaceable installs
and invoked the application itself as the helper. Those assertions described
the unsafe v0.4.5 prototype. These tests require the sentinel, stable root,
independent helper, explicit journal, restart acknowledgement, and rollback.
"""

import hashlib
import json
import os
import plistlib
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from pitrac_easy_connect.companion import self_update as su


ROOT = Path(__file__).resolve().parent.parent


def _script(version, acknowledge=True):
    acknowledgement = """
if '--post-update-journal' in sys.argv:
    from pitrac_easy_connect.companion.self_update import acknowledge_restart
    def value(flag): return sys.argv[sys.argv.index(flag) + 1]
    acknowledge_restart(Path(value('--post-update-journal')), value('--post-update-token'),
                        version=VERSION, executable=Path(sys.argv[0]))
""" if acknowledge else ""
    return """#!/usr/bin/env python3
import sys
import json
from pathlib import Path
VERSION = {version!r}
if '--version' in sys.argv:
    print(VERSION)
    raise SystemExit(0)
if '--version-probe-output' in sys.argv:
    output = Path(sys.argv[sys.argv.index('--version-probe-output') + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({{'applicationId': 'com.pitrac.easyconnect',
                                  'version': VERSION}}))
    raise SystemExit(0)
{ack}
""".format(version=version, ack=acknowledgement)


def _helper_script():
    return """#!/usr/bin/env python3
import sys
from pitrac_easy_connect.companion.self_update import run_helper_cli
raise SystemExit(run_helper_cli(sys.argv[1:]))
"""


def make_install(parent, version, *, system="Linux", machine="x86_64",
                 acknowledge=True, root_name=None):
    root = parent / (root_name or (su.APP_NAME + (".app" if system == "Darwin" else "")))
    executable = su.executable_path(root, system=system)
    helper = su.helper_path(root, system=system)
    executable.parent.mkdir(parents=True, exist_ok=True)
    helper.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(_script(version, acknowledge=acknowledge))
    helper.write_text(_helper_script())
    executable.chmod(0o755)
    helper.chmod(0o755)
    for legal in ("LICENSE", "NOTICE.md", "THIRD-PARTY-LICENCES.txt"):
        (root / legal).write_text(legal)
    if system == "Darwin":
        with open(root / "Contents" / "Info.plist", "wb") as handle:
            plistlib.dump({"CFBundleIdentifier": su.APPLICATION_ID,
                           "CFBundleShortVersionString": version}, handle)
    su.write_package_manifest(root, version, system=system, machine=machine)
    return root


def make_archive(path, source_root, *, system="Linux", unsafe_link=None):
    with zipfile.ZipFile(path, "w") as archive:
        roots = [source_root]
        if system == "Darwin":
            for legal in ("LICENSE", "NOTICE.md", "THIRD-PARTY-LICENCES.txt"):
                legal_path = source_root.parent / legal
                legal_path.write_text(legal)
                roots.append(legal_path)
        for root in roots:
            if root.is_file():
                archive.write(root, root.name)
                continue
            for candidate in [root, *root.rglob("*")]:
                name = candidate.relative_to(root.parent).as_posix()
                info = zipfile.ZipInfo(name + ("/" if candidate.is_dir() else ""))
                if candidate.is_symlink():
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, os.readlink(candidate))
                elif candidate.is_dir():
                    info.external_attr = (stat.S_IFDIR | 0o755) << 16
                    archive.writestr(info, b"")
                else:
                    info.external_attr = (stat.S_IFREG | stat.S_IMODE(candidate.stat().st_mode)) << 16
                    archive.writestr(info, candidate.read_bytes())
        if unsafe_link:
            info = zipfile.ZipInfo(unsafe_link[0])
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, unsafe_link[1])


def stage_fixture(tmp_path, monkeypatch, *, old="0.4.5", new="0.4.6",
                  acknowledge=True):
    state = tmp_path / "state"
    monkeypatch.setenv("PITRAC_UPDATE_STATE_DIR", str(state))
    install_parent = tmp_path / "applications"
    source_parent = tmp_path / "source"
    install_parent.mkdir()
    source_parent.mkdir()
    current = make_install(install_parent, old)
    candidate = make_install(source_parent, new, acknowledge=acknowledge)
    archive = state / "seed" / "candidate.zip"
    archive.parent.mkdir(parents=True)
    make_archive(archive, candidate)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    transaction = su.new_transaction_dir()
    downloaded = transaction / "candidate.zip"
    downloaded.write_bytes(archive.read_bytes())
    staged = su.stage_update(downloaded, transaction, new, system="Linux",
                             machine="x86_64", probe=lambda _executable: new)
    journal = su.prepare_transaction(
        archive_path=downloaded, staged=staged, install_root=current,
        installed_version=old, target_version=new, expected_tag="v" + new,
        asset_name="PiTrac-Easy-Connect-linux-x86_64.zip", asset_sha256=digest,
        transaction_root=transaction, system="Linux", machine="x86_64",
        running_executable=su.executable_path(current, system="Linux"),
    )
    return state, current, journal


def test_packaged_architecture_follows_the_manifest_not_the_host(tmp_path, monkeypatch):
    root = make_install(tmp_path, "0.4.6", system="Linux", machine="x86_64")
    executable = su.executable_path(root, system="Linux")
    monkeypatch.setattr(su.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(su, "current_install_root", lambda **_arguments: root)

    assert su.packaged_architecture(
        system="Linux", executable=executable, expected_version="0.4.6"
    ) == "x86_64"


def test_packaged_architecture_rejects_a_manifest_not_bound_to_the_running_executable(
    tmp_path, monkeypatch
):
    root = make_install(tmp_path, "0.4.6", system="Linux", machine="x86_64")
    other = root / "renamed-copy"
    other.write_text("copied executable")
    monkeypatch.setattr(su, "current_install_root", lambda **_arguments: root)

    with pytest.raises(su.SelfUpdateError, match="running executable"):
        su.packaged_architecture(
            system="Linux", executable=other, expected_version="0.4.6"
        )


def test_linux_archive_contract_has_one_dedicated_root(tmp_path):
    source = make_install(tmp_path / "source", "0.4.6")
    archive = tmp_path / "package.zip"
    make_archive(archive, source)
    extracted = su.extract_safely(archive, tmp_path / "out", system="Linux")
    app = su.validate_structure(extracted, "0.4.6", system="Linux",
                                machine="x86_64", probe=lambda _executable: "0.4.6")
    assert app.install_root.name == su.APP_NAME
    assert app.manifest["applicationId"] == su.APPLICATION_ID


def test_macos_archive_preserves_safe_internal_symlinks(tmp_path):
    source = make_install(tmp_path / "source", "0.4.6", system="Darwin")
    frameworks = source / "Contents" / "Frameworks"
    frameworks.mkdir()
    (frameworks / "Versions").mkdir()
    (frameworks / "Versions" / "Current").symlink_to("A")
    archive = tmp_path / "mac.zip"
    make_archive(archive, source, system="Darwin")
    extracted = su.extract_safely(archive, tmp_path / "out", system="Darwin")
    app = su.validate_structure(
        extracted, "0.4.6", system="Darwin", machine="x86_64",
        probe=lambda _executable: "0.4.6",
    )
    assert (app.install_root / "Contents/Frameworks/Versions/Current").is_symlink()


@pytest.mark.parametrize("target", ["/etc/passwd", "../../../../escape"])
def test_macos_archive_rejects_absolute_and_escaping_symlinks(tmp_path, target):
    source = make_install(tmp_path / "source", "0.4.6", system="Darwin")
    archive = tmp_path / "bad.zip"
    make_archive(archive, source, system="Darwin",
                 unsafe_link=(su.APP_NAME + ".app/Contents/Frameworks/bad", target))
    with pytest.raises(su.SelfUpdateError):
        su.extract_safely(archive, tmp_path / "out", system="Darwin")


@pytest.mark.parametrize("bad_name", ["/etc/passwd", "../../escape", "C:/Windows/file"])
def test_archive_traversal_is_rejected_before_extraction(tmp_path, bad_name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(bad_name, b"bad")
    with pytest.raises(su.SelfUpdateError):
        su.extract_safely(archive, tmp_path / "out", system="Linux")
    assert not (tmp_path / "escape").exists()


def test_extraction_refuses_stale_files(tmp_path):
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("safe", b"safe")
    output = tmp_path / "out"
    output.mkdir()
    (output / "stale").write_text("old")
    with pytest.raises(su.SelfUpdateError, match="not empty"):
        su.extract_safely(archive, output)


@pytest.mark.parametrize("name", ["Downloads", "Desktop", "Documents", "random-folder"])
def test_broad_or_arbitrary_linux_directories_are_refused(tmp_path, name):
    root = tmp_path / name
    root.mkdir()
    (root / su.APP_NAME).write_text("unrelated")
    with pytest.raises(su.SelfUpdateError):
        su.validate_install_root(root, system="Linux", machine="x86_64")
    assert (root / su.APP_NAME).exists()


def test_home_and_filesystem_root_are_refused():
    for root in (Path.home(), Path("/")):
        with pytest.raises(su.SelfUpdateError):
            su.validate_install_root(root, system="Linux", machine="x86_64")


def test_wrong_or_missing_manifest_is_refused(tmp_path):
    root = make_install(tmp_path, "0.4.5")
    su.manifest_path(root, system="Linux").unlink()
    with pytest.raises(su.SelfUpdateError):
        su.validate_install_root(root, system="Linux", machine="x86_64")


def test_preflight_keeps_current_install_and_places_helper_outside_all_roots(tmp_path, monkeypatch):
    state, current, journal_path = stage_fixture(tmp_path, monkeypatch)
    journal = su.load_journal(journal_path)
    assert su.executable_path(current, system="Linux").read_text().find("0.4.5") >= 0
    assert Path(journal["preparedSiblingPath"]).parent == current.parent
    helper = Path(journal["helperPath"])
    assert helper.is_file()
    assert str(helper).startswith(str(state / "helpers"))
    assert not str(helper).startswith(str(current))


def test_malformed_digest_is_rejected_before_any_copy(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("PITRAC_UPDATE_STATE_DIR", str(state))
    with pytest.raises(su.SelfUpdateError, match="malformed"):
        su.validate_sha256("1234")


def test_version_probe_refuses_output_outside_dedicated_probe_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("PITRAC_UPDATE_STATE_DIR", str(tmp_path / "state"))
    outside = tmp_path / "outside.json"
    with pytest.raises(su.SelfUpdateError, match="unsafe"):
        su.write_version_probe(outside, "0.4.6")
    assert not outside.exists()


def _run_real_helper(journal, monkeypatch, timeout=15):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run([str(su.load_journal(journal)["helperPath"]),
                             "--journal", str(journal), "--wait-pid", "999999",
                             "--timeout", "1", "--ack-timeout", "5"],
                            env=env, capture_output=True, text=True, timeout=timeout)
    return result


@pytest.mark.skipif(os.name == "nt", reason="the portable script fixture is POSIX; Windows CI uses the packaged helper")
def test_real_independent_helper_subprocess_swaps_acks_and_cleans_previous(tmp_path, monkeypatch):
    _state, current, journal = stage_fixture(tmp_path, monkeypatch)
    result = _run_real_helper(journal, monkeypatch)
    assert result.returncode == 0, result.stderr
    assert subprocess.check_output([str(su.executable_path(current, system="Linux")), "--version"],
                                   text=True).strip() == "0.4.6"
    data = su.load_journal(journal)
    assert data["phase"] == "complete"
    assert not Path(data["previousInstallPath"]).exists()


@pytest.mark.skipif(os.name == "nt", reason="the portable script fixture is POSIX; Windows CI uses the packaged helper")
def test_restart_without_ack_rolls_back_to_previous_working_version(tmp_path, monkeypatch):
    _state, current, journal = stage_fixture(tmp_path, monkeypatch, acknowledge=False)
    result = _run_real_helper(journal, monkeypatch)
    assert result.returncode == 1, result.stderr
    assert subprocess.check_output([str(su.executable_path(current, system="Linux")), "--version"],
                                   text=True).strip() == "0.4.5"
    data = su.load_journal(journal)
    assert data["phase"] == "rolled-back"
    outcome = json.loads(Path(data["resultFilePath"]).read_text())
    assert outcome["rolledBack"] is True


def test_helper_timeout_leaves_installed_files_untouched(tmp_path, monkeypatch):
    _state, current, journal = stage_fixture(tmp_path, monkeypatch)
    before = su.executable_path(current, system="Linux").read_bytes()
    result = su.run_helper(journal, 123, timeout=0.01,
                           process_tree_alive=lambda _pid, _known: True)
    assert result == 1
    assert su.executable_path(current, system="Linux").read_bytes() == before


def test_old_process_tree_wait_excludes_only_the_independent_helper(monkeypatch, tmp_path):
    helper = tmp_path / "PiTrac Updater"
    old_executable = tmp_path / "PiTrac Easy-Connect"
    current_pid = os.getpid()

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def parent(self):
            return {current_pid: Process(7001), 7001: Process(7000)}.get(self.pid)

        def exe(self):
            return str(helper if self.pid in (current_pid, 7001) else old_executable)

        def children(self, recursive=True):
            return [Process(7001), Process(7002)] if self.pid == 7000 else []

        def is_running(self):
            return True

        def status(self):
            return "running"

    fake_psutil = type("Psutil", (), {"STATUS_ZOMBIE": "zombie", "Process": Process})
    monkeypatch.setattr(su, "psutil", fake_psutil)
    ignored = su._independent_helper_processes(helper)
    assert ignored == {current_pid, 7001}
    known = set()
    assert su._process_tree_alive(7000, known, ignored) is True
    assert known == {7000, 7002}


def test_windows_helper_cleanup_retries_a_transient_file_lock(monkeypatch, tmp_path):
    state = tmp_path / "state"
    monkeypatch.setenv("PITRAC_UPDATE_STATE_DIR", str(state))
    helper_dir = state / "helpers" / "transaction-helper"
    helper_dir.mkdir(parents=True)
    helper = helper_dir / "PiTrac Updater.exe"
    helper.write_bytes(b"locked")
    monkeypatch.setattr(su, "_process_tree_alive", lambda _pid, _known: False)
    real_remove = su._remove_tree
    attempts = []

    def sharing_violation_then_remove(path, *, allowed_parent):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("the bootloader still holds the executable")
        return real_remove(path, allowed_parent=allowed_parent)

    monkeypatch.setattr(su, "_remove_tree", sharing_violation_then_remove)
    su.cleanup_independent_helper(999999, helper)
    deadline = time.monotonic() + 2
    while helper_dir.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(attempts) >= 3
    assert not helper_dir.exists()


def test_second_promotion_rename_failure_restores_the_previous_install(monkeypatch, tmp_path):
    _state, current, journal = stage_fixture(tmp_path, monkeypatch)
    real_replace = su._replace_transaction_path
    promoted_attempts = []

    class RelaunchedPreviousApp:
        pid = 999999

    def fail_prepared_promotion(source, destination, *, timeout=10):
        if Path(source).name.startswith(".pitrac-prepared-"):
            promoted_attempts.append(1)
            raise PermissionError("candidate promotion stayed locked")
        return real_replace(source, destination, timeout=timeout)

    monkeypatch.setattr(su, "_replace_transaction_path", fail_prepared_promotion)
    # This test covers filesystem restoration, not platform executable format.
    # Windows CI cannot execute the intentionally POSIX fixture after rollback.
    monkeypatch.setattr(su, "_spawn_detached", lambda _arguments: RelaunchedPreviousApp())
    result = su.run_helper(journal, 999999)
    data = su.load_journal(journal)
    assert result == 1
    assert promoted_attempts == [1]
    assert data["phase"] == "rolled-back"
    assert su.executable_path(current, system="Linux").read_text().find("0.4.5") >= 0
    assert not Path(data["previousInstallPath"]).exists()
    assert not Path(data["brokenInstallPath"]).exists()


def test_tampered_journal_is_rejected_before_mutation(tmp_path, monkeypatch):
    _state, current, journal = stage_fixture(tmp_path, monkeypatch)
    value = json.loads(journal.read_text())
    value["installRoot"] = str(tmp_path / "Downloads")
    journal.write_text(json.dumps(value))
    before = su.executable_path(current, system="Linux").read_bytes()
    assert su.run_helper(journal, 999999) == 2
    assert su.executable_path(current, system="Linux").read_bytes() == before
