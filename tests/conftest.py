"""Shared helpers for the test suite, and how it is spread across workers."""

import pathlib
import threading

import pytest

#: Modules that drive real sockets against real servers. Four of these running
#: at once on a four-vCPU Windows runner starved the serving threads until the
#: clients timed out and Windows aborted the connections underneath them
#: (WinError 10053) -- the same commit passed on one run and failed on the
#: next. They are pinned to two groups so at most two run together.
#:
#: Two groups rather than one: the pair is balanced -- the endurance run on
#: its own is about as long as everything else together -- so the isolation
#: costs no wall-clock time, while halving how many of these run at once.
NETWORK_GROUPS = {
    "test_endurance": "network-a",
    "test_api_robustness": "network-b",
    "test_companion": "network-b",
    "test_end_to_end_relay": "network-b",
    "test_robustness": "network-b",
    "test_pi_service": "network-b",
    "test_downloads": "network-b",
    "test_pi_updates": "network-b",
    "test_model_install": "network-b",
    "test_app_startup": "network-b",
}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Group every test, so --dist loadgroup can place them deliberately.

    Anything not named above is grouped by its own module, which is what
    --dist loadfile used to do: a file stays whole on one worker, so tests
    that share a fixture are not split across processes.
    """

    for item in items:
        module = pathlib.Path(str(item.nodeid).split("::")[0]).stem
        group = NETWORK_GROUPS.get(module, module)
        item.add_marker(pytest.mark.xdist_group(group))


def start_serving(server):
    """Run ``server`` on a background thread, and return how to stop it.

    Closing a socket while another thread is still selecting on it is
    undefined. POSIX shrugs; Windows raises WinError 10038 from inside the
    serving thread, which prints a traceback that looks exactly like a real
    failure and is not one. Stopping in order -- leave the loop, join the
    thread, then close -- keeps the run readable on every platform.
    """

    # serve_forever polls for the shutdown flag every half second by default,
    # so shutdown() blocks for up to that long. Once per process that is
    # nothing; once per test it was most of this suite's runtime.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01},
                              daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    return stop


#: Every socket loop in the project wakes on a timeout to notice it has been
#: asked to stop. A fifth of a second is right on the enclosure, where shutdown
#: happens once. It is wrong here: three of these close behind every server
#: fixture, so each test paid about a second of teardown, and the socket-heavy
#: module spent more time closing sockets than exercising routes.
SHUTDOWN_POLLS = (
    ("pitrac_easy_connect.common.discovery", "RESPONDER_POLL_SECONDS"),
    ("pitrac_easy_connect.pi.link_server", "ACCEPT_POLL_SECONDS"),
    ("pitrac_easy_connect.pi.relay", "ACCEPT_POLL_SECONDS"),
)


@pytest.fixture(autouse=True)
def _prompt_shutdown(monkeypatch):
    """Let the loops notice a stop quickly, without changing what ships.

    A test that genuinely cares about the interval can set it back.
    """

    import importlib

    for module_name, attribute in SHUTDOWN_POLLS:
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, attribute, 0.01, raising=True)
