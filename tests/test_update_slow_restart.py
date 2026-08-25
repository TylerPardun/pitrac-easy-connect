"""A slow start is not a failed update.

What happened on a real Intel Mac, reconstructed from the transaction journal
it left behind:

    phase        = rolled-back
    installRoot  = /Applications/PiTrac Easy-Connect.app
    result       = "the new application did not acknowledge its exact path and
                    version. The restored application did not acknowledge its
                    relaunch automatically."
    restart-ack  = version 0.4.6, written 2.5 seconds AFTER the helper gave up

The update worked. The helper replaced the application, launched it, and the
owner watched the new version start. The confirmation only fires once the
window is on screen, and that took about forty-eight seconds against a
forty-five second deadline -- so the helper undid a good installation. The old
version it restored then missed the same deadline by two and a half seconds,
which is how we know the deadline was the problem rather than the new build.

The rule now: undo an update when the new application *dies*, never merely
because it is slow. A user watching the new version start and then finding the
old one back, with nothing said about why, is the worst outcome available.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pitrac_easy_connect.companion import self_update as su

from test_self_update import stage_fixture


@pytest.mark.skipif(os.name == "nt", reason="the script install fixture is POSIX; the decision itself is covered on every platform by test_liveness_does_not_depend_on_psutil")
def test_a_live_but_slow_application_keeps_its_update(tmp_path, monkeypatch):
    """The exact shape of the field failure: running, but not yet confirmed."""

    state, install, journal = stage_fixture(tmp_path, monkeypatch, acknowledge=False)

    class StillStarting:
        pid = 4242

    # Alive throughout, and it never writes an acknowledgement.
    monkeypatch.setattr(su, "_process_tree_alive", lambda pid, known, *a, **k: True)

    code = su.run_helper(journal, 999999, timeout=0.01, ack_timeout=0.4,
                         process_tree_alive=lambda pid, known: False,
                         launcher=lambda arguments: StillStarting())

    assert code == 0, "a running application had its update undone"
    installed = json.loads((install / su.INSTALL_MANIFEST).read_text())
    assert installed["version"] == "0.4.6", (
        "the update was rolled back even though the application was still running"
    )
    result = json.loads((su.staging_dir() / "last-install-result.json").read_text())
    assert result["success"] is True and result["rolledBack"] is False
    assert "had not confirmed itself" in result["detail"], result["detail"]


@pytest.mark.skipif(os.name == "nt", reason="the script install fixture is POSIX; the decision itself is covered on every platform by test_liveness_does_not_depend_on_psutil")
def test_an_application_that_dies_without_confirming_is_still_rolled_back(tmp_path, monkeypatch):
    """The safety this must not lose."""

    state, install, journal = stage_fixture(tmp_path, monkeypatch, acknowledge=False)

    class Died:
        pid = 4243

    monkeypatch.setattr(su, "_process_tree_alive", lambda pid, known, *a, **k: False)

    code = su.run_helper(journal, 999999, timeout=0.01, ack_timeout=0.4,
                         process_tree_alive=lambda pid, known: False,
                         launcher=lambda arguments: Died())

    assert code == 1, "an application that died without confirming was not rolled back"
    installed = json.loads((install / su.INSTALL_MANIFEST).read_text())
    assert installed["version"] == "0.4.5", "the previous version was not restored"


def test_the_deadline_is_generous_enough_for_a_slow_first_launch():
    """Forty-five seconds was measured as too short on real hardware."""

    assert su.ACK_TIMEOUT >= 120, (
        "the confirmation deadline is {}s; a first launch of a freshly written "
        "bundle was measured at about 48s on an Intel Mac, and that was with "
        "45s allowed".format(su.ACK_TIMEOUT)
    )


# --- The helper the application shuts itself down for ----------------------


@pytest.mark.skipif(os.name == "nt", reason="the script fixture is POSIX; Windows needs a real .exe")
def test_a_helper_that_cannot_run_is_caught_before_the_application_exits(tmp_path, monkeypatch):
    """The application closes itself so the helper can replace it.

    Before this, the check was is_file() plus the executable bit, and the
    failure message said "could not execute" -- a stronger claim than the
    check supported. A binary copied out of an unsigned bundle can satisfy
    both and still refuse to launch, and when that happens nothing performs
    the update and nothing writes a result: the owner is left on the old
    version with no record of why.
    """

    broken = tmp_path / "PiTrac Updater"
    broken.write_text("this is not a program\n")
    broken.chmod(0o755)

    with pytest.raises(su.SelfUpdateError) as raised:
        su._prove_helper_runs(broken)
    assert "would not start" in str(raised.value) or "did not answer" in str(raised.value)


@pytest.mark.skipif(os.name == "nt", reason="the script fixture is POSIX; Windows needs a real .exe")
def test_a_working_helper_answers_when_started(tmp_path):
    working = tmp_path / "PiTrac Updater"
    working.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pitrac_easy_connect.companion.self_update import run_helper_cli\n"
        "raise SystemExit(run_helper_cli(sys.argv[1:]))\n"
    )
    working.chmod(0o755)
    su._prove_helper_runs(working)      # must not raise


def test_the_probe_does_not_perform_an_update():
    """--ping must be inert; it runs against the installed helper."""

    import inspect

    source = inspect.getsource(su.run_helper_cli)
    assert "if args.ping:" in source
    assert source.index("if args.ping:") < source.index("run_helper("), (
        "the probe falls through into a real update"
    )


def test_liveness_does_not_depend_on_psutil(monkeypatch):
    """The keep-or-roll-back decision itself, on every platform.

    The two tests above drive a whole transaction and need a runnable install,
    which the suite builds as a POSIX script -- so they are skipped on Windows,
    the same way test_restart_without_ack_rolls_back_to_previous_working_version
    already is. This one has no fixture and runs everywhere, so the decision is
    not left unexercised on the platform those skip.

    CI has no psutil; the machine this was written on did.

    Without psutil the process-tree check falls back to os.kill(pid, 0),
    which succeeds for a process that has exited but not been reaped. The
    helper never reaps, so every dead child looked alive to it -- and since
    keeping an update now depends on the application still running, that
    would have kept an update whose application had died. It passed locally
    and failed on all four CI runners.
    """

    monkeypatch.setattr(su, "psutil", None)

    class Exited:
        def poll(self):
            return 0

    class Running:
        def poll(self):
            return None

    assert su._launched_still_running(Exited(), 999999) is False
    assert su._launched_still_running(Running(), 999999) is True


def test_the_probe_only_runs_for_a_packaged_build():
    """Running from source the helper is a script, not the copied binary.

    The failure it guards against belongs to the frozen application, and
    attempting it from source made every Windows test that prepares a
    transaction fail with "not a valid Win32 application" -- and then leave
    file handles that blocked the cleanup.
    """

    import inspect

    source = inspect.getsource(su.prepare_transaction)
    assert 'if getattr(sys, "frozen", False):' in source
    assert source.index('if getattr(sys, "frozen", False):') < source.index("_prove_helper_runs(independent)")
