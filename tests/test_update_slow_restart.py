"""A slow acknowledgement succeeds; liveness without proof never does.

The Intel field launch established that 45 seconds is too short.  The timeout
therefore stays generous, but expiry still means rollback: a process can remain
alive while its only window is blank, hidden, or hung.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pitrac_easy_connect.companion import self_update as su

from test_self_update import stage_fixture


@pytest.mark.skipif(os.name == "nt", reason="the script install fixture is POSIX; the decision itself is covered on every platform by test_liveness_does_not_depend_on_psutil")
def test_a_slow_application_that_eventually_acknowledges_keeps_its_update(
    tmp_path, monkeypatch
):
    """Simulate the measured 48-120 second range without making the suite wait."""

    _state, install, journal = stage_fixture(tmp_path, monkeypatch, acknowledge=False)

    class StillStarting:
        pid = 4242
        def poll(self):
            return None

    def start_then_show(_arguments):
        def acknowledge_after_visible_delay():
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if su.load_journal(journal)["phase"] == "awaiting-restart-verification":
                    time.sleep(0.25)
                    su.acknowledge_restart(
                        journal, su.load_journal(journal)["restartToken"],
                        version="0.4.6",
                        executable=su.executable_path(install, system="Linux"),
                    )
                    return
                time.sleep(0.01)
        threading.Thread(target=acknowledge_after_visible_delay, daemon=True).start()
        return StillStarting()

    code = su.run_helper(journal, 999999, timeout=0.01, ack_timeout=1.0,
                         process_tree_alive=lambda pid, known: False,
                         launcher=start_then_show)

    assert code == 0, "an application that gave exact delayed proof was rolled back"
    installed = json.loads((install / su.INSTALL_MANIFEST).read_text())
    assert installed["version"] == "0.4.6"
    result = json.loads((su.staging_dir() / "last-install-result.json").read_text())
    assert result["success"] is True and result["rolledBack"] is False
    assert "verified after restart" in result["detail"]


@pytest.mark.skipif(os.name == "nt", reason="the script install fixture is POSIX; the decision itself is covered on every platform by test_liveness_does_not_depend_on_psutil")
def test_an_application_alive_forever_without_acknowledging_is_rolled_back(
    tmp_path, monkeypatch
):
    """A blank/hung process is not a usable native application."""

    _state, install, journal = stage_fixture(tmp_path, monkeypatch, acknowledge=False)

    class Hung:
        pid = 4243
        def poll(self):
            return None

    code = su.run_helper(journal, 999999, timeout=0.01, ack_timeout=1.0,
                         process_tree_alive=lambda pid, known: False,
                         launcher=lambda arguments: Hung())

    assert code == 1, "a hung application was treated as a successful update"
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
