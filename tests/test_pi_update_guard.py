"""The enclosure's update guard: what happens after the restart.

Restarting the Easy-Connect service kills the process performing the update,
so the updater's own health check and rollback are code that can never run on
a Pi. Everything here is about the component that runs instead: a separate
process, registered with systemd before the symlink moves, which decides
whether the release that came back actually works and puts the previous one
back if it does not.

The staged import probe these tests do not repeat is necessary but not
sufficient. Every failure below imports perfectly.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import on_posix
from pitrac_easy_connect.pi import update_guard as guard


pytestmark = on_posix


class Clock:
    """A clock the guard's own waiting drives, so tests take no real time."""

    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


@pytest.fixture
def live_process():
    """A real process, so liveness is observed rather than mocked."""

    started = []

    def start():
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"]
        )
        started.append(process)
        return process

    yield start
    for process in started:
        process.kill()
        process.wait()


@pytest.fixture
def enclosure(tmp_path):
    """The layout an installed enclosure has: releases behind one symlink."""

    releases = tmp_path / "releases-root" / "releases"
    releases.mkdir(parents=True)
    previous = releases / "0.6.0-100-aaa"
    candidate = releases / "0.7.0-200-bbb"
    for path, version in ((previous, "0.6.0"), (candidate, "0.7.0")):
        (path / "pitrac_easy_connect").mkdir(parents=True)
        (path / "pitrac_easy_connect" / "__init__.py").write_text(
            '__version__ = "{}"\n'.format(version), encoding="utf-8"
        )
    link = tmp_path / "pitrac-easy-connect"
    link.symlink_to(previous)
    state = tmp_path / "state"
    state.mkdir()
    return {"releases": releases, "previous": previous, "candidate": candidate,
            "link": link, "state": state}


def arm(enclosure, **overrides):
    registered = []
    journal_path = guard.arm(
        state_dir=enclosure["state"],
        link_path=enclosure["link"],
        releases_dir=enclosure["releases"],
        previous=enclosure["previous"],
        candidate=enclosure["candidate"],
        installed_version="0.6.0",
        expected_version="0.7.0",
        expected_tag="v0.7.0",
        asset_sha256="a" * 64,
        register=lambda path, journal: registered.append(path),
        **overrides,
    )
    assert registered == [journal_path], "the guard was not registered before the swap"
    return journal_path


def move_link(enclosure, journal_path=None):
    """What the updater does after arming: one atomic symlink replacement."""

    guard._point_link_at(enclosure["link"], enclosure["candidate"])
    if journal_path is not None:
        journal = guard.load_journal(journal_path)
        guard.write_journal(journal_path, journal, "symlink-moved")


def acknowledge(enclosure, *, version="0.7.0", release=None, pid, proofs=None):
    """What pi/app.py does once the restarted service is genuinely up."""

    values = {name: True for name in guard.REQUIRED_PROOFS}
    values.update(proofs or {})
    return guard.acknowledge_health(
        state_dir=enclosure["state"],
        version=version,
        release_path=release or enclosure["candidate"],
        proofs=values,
        pid=pid,
    )


def run(journal_path, clock=None, **kwargs):
    clock = clock or Clock()
    unregistered = []
    code = guard.run_guard(
        journal_path, now=clock.now, sleep=clock.sleep,
        restart=kwargs.pop("restart", lambda name: None),
        unregister=kwargs.pop("unregister", lambda journal: unregistered.append(journal)),
        **kwargs,
    )
    return code, unregistered


def phase_of(journal_path):
    return guard.load_journal(journal_path)["phase"]


def link_target(enclosure):
    return Path(os.path.realpath(str(enclosure["link"])))


# --- The update works ----------------------------------------------------


def test_a_proved_release_is_kept_and_the_guard_stands_down(enclosure, live_process):
    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    service = live_process()
    assert acknowledge(enclosure, pid=service.pid) is True

    code, unregistered = run(journal_path)

    assert code == 0
    assert phase_of(journal_path) == "healthy"
    assert link_target(enclosure) == enclosure["candidate"]
    assert unregistered, "the guard stayed registered after a verified success"


def test_an_ordinary_boot_has_nothing_to_acknowledge(enclosure):
    """Almost every boot. It must cost nothing and claim nothing."""

    assert guard.pending_transaction(enclosure["state"]) is None
    assert acknowledge(enclosure, pid=os.getpid()) is False


# --- Everything the import probe cannot see -------------------------------


@pytest.mark.parametrize("failure,proofs", [
    # The service object could not be built at all, so nothing was written.
    ("service constructor raised", None),
    # It started, but this enclosure's own settings would not parse.
    ("corrupt state loading", {"stateFilesLoaded": False}),
    # The port is held by something else, so no computer could ever connect.
    ("link port bind failure", {"linkListening": False}),
    ("portal port bind failure", {"portalListening": False}),
    ("discovery bind failure", {"discoveryListening": False}),
    # It bound everything and then never completed a refresh.
    ("refresh never completed", {"refreshCompleted": False}),
])
def test_a_release_that_imports_but_will_not_run_is_rolled_back(
    enclosure, live_process, failure, proofs
):
    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    if proofs is not None:
        acknowledge(enclosure, pid=live_process().pid, proofs=proofs)

    restarted = []
    code, unregistered = run(journal_path, restart=restarted.append)

    assert code == 2, failure
    assert link_target(enclosure) == enclosure["previous"], (
        "{}: the enclosure was left running the broken release".format(failure)
    )
    assert restarted == ["pitrac-easy-connect.service"]
    assert phase_of(journal_path) == "unresolved"
    assert not unregistered, "the guard stood down before anything proved itself"


def test_a_rollback_the_previous_release_confirms_is_complete(enclosure, live_process):
    """The whole point: back on the old version, and known to be back."""

    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)

    def restart(_name):
        # The restored service comes up and proves itself, exactly as the
        # candidate was supposed to.
        acknowledge(enclosure, version="0.6.0", release=enclosure["previous"],
                    pid=live_process().pid)

    code, unregistered = run(journal_path, restart=restart)

    assert code == 1
    assert phase_of(journal_path) == "rolled-back"
    assert link_target(enclosure) == enclosure["previous"]
    assert unregistered, "the guard stayed registered after a verified rollback"


def test_an_acknowledgement_from_the_old_release_cannot_pass_for_the_new_one(
    enclosure, live_process
):
    """A crash loop back to the previous release must not read as success."""

    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    acknowledge(enclosure, version="0.6.0", release=enclosure["previous"],
                pid=live_process().pid)

    code, _unregistered = run(journal_path, restart=lambda name: None)
    assert code == 2
    assert link_target(enclosure) == enclosure["previous"]


def test_a_timeout_with_no_acknowledgement_at_all_rolls_back(enclosure):
    journal_path = arm(enclosure, health_timeout=30.0)
    move_link(enclosure, journal_path)
    clock = Clock()

    code, _unregistered = run(journal_path, clock=clock, restart=lambda name: None)

    assert code == 2
    assert clock.value >= 30.0, "it gave up before the bounded interval expired"
    assert link_target(enclosure) == enclosure["previous"]


def test_a_process_that_dies_during_the_settle_window_is_a_crash_loop(
    enclosure, live_process
):
    """An acknowledgement proves it started, not that it stayed started."""

    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    service = live_process()
    acknowledge(enclosure, pid=service.pid)
    service.kill()
    service.wait()

    code, _unregistered = run(journal_path, restart=lambda name: None)

    assert code == 2
    assert link_target(enclosure) == enclosure["previous"]


def test_a_service_that_keeps_restarting_is_a_crash_loop(enclosure, live_process):
    """Each restart writes a fresh acknowledgement; none of them is health."""

    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    acknowledge(enclosure, pid=live_process().pid)
    clock = Clock()
    original = clock.sleep

    def restart_again(seconds):
        original(seconds)
        # A new process each time round, exactly as systemd Restart=always
        # would produce while the release crashes on startup.
        acknowledge(enclosure, pid=live_process().pid)

    clock.sleep = restart_again
    code, _unregistered = run(journal_path, clock=clock, restart=lambda name: None)

    assert code == 2
    assert link_target(enclosure) == enclosure["previous"]


def test_an_acknowledgement_that_arrives_late_still_counts(enclosure, live_process):
    """Slow is not broken; the interval is bounded but generous."""

    journal_path = arm(enclosure, health_timeout=120.0)
    move_link(enclosure, journal_path)
    clock = Clock()
    original = clock.sleep

    def acknowledge_at_90_seconds(seconds):
        original(seconds)
        if clock.value >= 90.0 and guard.pending_transaction(enclosure["state"]):
            if not (Path(journal_path).parent / "health.json").exists():
                acknowledge(enclosure, pid=live_process().pid)

    clock.sleep = acknowledge_at_90_seconds
    code, unregistered = run(journal_path, clock=clock)

    assert code == 0
    assert phase_of(journal_path) == "healthy"
    assert unregistered


# --- Power loss ----------------------------------------------------------


def test_power_loss_before_the_symlink_moved_leaves_the_previous_release_live(
    enclosure
):
    """The candidate exists, the link never moved. Nothing to undo."""

    journal_path = arm(enclosure)
    # No move_link: the machine died between arming and the swap.
    code, unregistered = run(journal_path)

    assert code == 1
    assert phase_of(journal_path) == "failed"
    assert link_target(enclosure) == enclosure["previous"]
    assert enclosure["previous"].is_dir()
    assert unregistered


def test_power_loss_after_the_symlink_moved_is_rolled_back_at_the_next_boot(
    enclosure, live_process
):
    """The phase never recorded the swap; the filesystem did."""

    journal_path = arm(enclosure)
    guard._point_link_at(enclosure["link"], enclosure["candidate"])
    assert phase_of(journal_path) == "guard-armed", "the phase records no swap"

    def restart(_name):
        acknowledge(enclosure, version="0.6.0", release=enclosure["previous"],
                    pid=live_process().pid)

    code, _unregistered = run(journal_path, restart=restart)

    assert code == 1
    assert link_target(enclosure) == enclosure["previous"]


def test_a_link_pointing_at_neither_release_is_never_guessed_at(enclosure):
    """Something outside this transaction moved it. Fail closed, stay armed."""

    journal_path = arm(enclosure)
    stranger = enclosure["releases"] / "0.5.0-50-ccc"
    (stranger / "pitrac_easy_connect").mkdir(parents=True)
    guard._point_link_at(enclosure["link"], stranger)

    code, unregistered = run(journal_path)

    assert code == 2
    assert phase_of(journal_path) == "unresolved"
    assert link_target(enclosure) == stranger
    assert not unregistered


def test_a_missing_previous_release_is_unresolved_rather_than_destructive(
    enclosure
):
    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    import shutil

    shutil.rmtree(enclosure["previous"])

    code, unregistered = run(journal_path, restart=lambda name: None)

    assert code == 2
    assert phase_of(journal_path) == "unresolved"
    assert link_target(enclosure) == enclosure["candidate"], (
        "it left the enclosure with no software rather than a suspect release"
    )
    assert not unregistered


def test_running_the_guard_again_is_idempotent(enclosure, live_process):
    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    acknowledge(enclosure, pid=live_process().pid)

    first, _ = run(journal_path)
    second, _ = run(journal_path)
    third, _ = run(journal_path)

    assert (first, second, third) == (0, 0, 0)
    assert link_target(enclosure) == enclosure["candidate"]


# --- The journal is the only authority -----------------------------------


def test_a_tampered_journal_is_never_acted_on(enclosure):
    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    value = json.loads(Path(journal_path).read_text())
    value["previousReleasePath"] = str(enclosure["releases"].parent.parent / "elsewhere")
    Path(journal_path).write_text(json.dumps(value))

    code, unregistered = run(journal_path)

    assert code == 2
    assert link_target(enclosure) == enclosure["candidate"]
    assert not unregistered, "a tampered journal deregistered the guard"


@pytest.mark.parametrize("field,value", [
    ("expectedVersion", "9.9.9"),
    ("installedVersion", "9.9.9"),
    ("assetSha256", "b" * 64),
    ("healthTimeout", 0.0),
    ("settleSeconds", 0.0),
    ("serviceName", "something-else.service"),
    ("phase", "healthy"),
])
def test_editing_any_field_without_the_digest_is_refused(enclosure, field, value):
    """The path rules cannot see these, so only the digest can.

    Shortening the health timeout to nothing, or writing in a phase that means
    "already fine", would each defeat the guard without moving a single path
    outside the releases directory.
    """

    journal_path = arm(enclosure)
    edited = json.loads(Path(journal_path).read_text())
    edited[field] = value
    Path(journal_path).write_text(json.dumps(edited))

    with pytest.raises(guard.GuardError, match="has been altered"):
        guard.load_journal(journal_path)


def test_a_journal_with_a_repaired_digest_still_cannot_name_a_broad_path(
    enclosure, tmp_path
):
    """Recomputing the digest is easy; the path rules are the real check."""

    journal_path = arm(enclosure)
    value = json.loads(Path(journal_path).read_text())
    value["previousReleasePath"] = str(tmp_path)
    value.pop("integritySha256")
    value["integritySha256"] = guard._canonical_digest(value)
    Path(journal_path).write_text(json.dumps(value))

    with pytest.raises(guard.GuardError, match="not inside"):
        guard.load_journal(journal_path)


@pytest.mark.parametrize("broad", ["/", "~", "/usr", "/var"])
def test_no_transaction_may_name_a_broad_system_path(enclosure, broad):
    target = Path(os.path.expanduser(broad))
    with pytest.raises(guard.GuardError):
        guard._reject_broad_path(target)


def test_a_missing_proof_key_is_a_failure_not_an_absence(enclosure, live_process):
    """Adding a required proof must invalidate older acknowledgements."""

    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    journal = guard.load_journal(journal_path)
    guard._atomic_json(Path(journal_path).parent / "health.json", {
        "transactionId": journal["transactionId"],
        "version": "0.7.0",
        "releasePath": str(enclosure["candidate"]),
        "proofs": {"stateFilesLoaded": True},        # the rest are absent
        "pid": live_process().pid,
        "startedAt": time.time(),
    })
    assert guard._health_for(
        journal, Path(journal_path).parent / "health.json", "0.7.0",
        enclosure["candidate"],
    ) is None


def test_an_acknowledgement_for_another_transaction_is_ignored(
    enclosure, live_process
):
    journal_path = arm(enclosure)
    move_link(enclosure, journal_path)
    journal = guard.load_journal(journal_path)
    guard._atomic_json(Path(journal_path).parent / "health.json", {
        "transactionId": "f" * 32,
        "version": "0.7.0",
        "releasePath": str(enclosure["candidate"]),
        "proofs": {name: True for name in guard.REQUIRED_PROOFS},
        "pid": live_process().pid,
        "startedAt": time.time(),
    })
    code, _unregistered = run(journal_path, restart=lambda name: None)
    assert code == 2
    assert link_target(enclosure) == enclosure["previous"]


# --- Durability ----------------------------------------------------------


def test_the_candidate_and_journal_are_on_the_card_before_the_link_moves(
    enclosure, monkeypatch
):
    """A symlink swap is only atomic with respect to files that exist."""

    order = []
    monkeypatch.setattr(guard, "fsync_tree", lambda path: order.append(("tree", path)))
    monkeypatch.setattr(guard, "fsync_dir", lambda path: order.append(("dir", path)))
    journal_path = arm(enclosure)

    assert ("tree", enclosure["candidate"]) in order
    assert ("dir", enclosure["releases"]) in order
    assert order.index(("tree", enclosure["candidate"])) < order.index(
        ("dir", enclosure["releases"])
    )


def test_the_journal_records_everything_a_rollback_needs(enclosure):
    journal = guard.load_journal(arm(enclosure))
    assert journal["transactionId"]
    assert journal["previousReleasePath"] == str(enclosure["previous"])
    assert journal["candidateReleasePath"] == str(enclosure["candidate"])
    assert journal["expectedVersion"] == "0.7.0"
    assert journal["expectedTag"] == "v0.7.0"
    assert journal["assetSha256"] == "a" * 64
    assert journal["installedVersion"] == "0.6.0"
    assert journal["phase"] == "guard-armed"
    assert journal["createdAt"] <= journal["updatedAt"]


def test_the_guard_is_importable_without_the_rest_of_the_package(tmp_path):
    """It is copied to a directory outside the release it protects.

    A rollback component that can only be imported from inside the release
    being replaced is a rollback component the update can break.
    """

    copied = tmp_path / "pitrac-update-guard.py"
    copied.write_bytes(Path(guard.__file__).read_bytes())
    done = subprocess.run(
        [sys.executable, str(copied), "--state-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=60,
        cwd=str(tmp_path), env={"PATH": os.environ.get("PATH", ""),
                                "PYTHONPATH": ""},
    )
    assert done.returncode == 0, done.stderr
