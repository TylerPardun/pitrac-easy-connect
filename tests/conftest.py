"""Shared helpers for the test suite, and how it is spread across workers."""

import os
import pathlib
import threading

import pytest

#: Parts of this project only ever run on the enclosure, which is Linux. File
#: ownership, the accounts a privilege drop needs, permission bits and the
#: NetworkManager backend have no meaning on Windows, and a test for them there
#: fails for reasons that say nothing about the code.
on_posix = pytest.mark.skipif(
    os.name != "posix",
    reason="this behaviour belongs to the enclosure, which is Linux",
)

#: What makes a module socket-heavy: it stands up a real service, a real
#: simulator, or a real HTTP server on a real port.
#:
#: Derived rather than listed. A hand-written list was wrong twice -- it missed
#: test_shot_history_accuracy, which borrows another module's fixture and so
#: mentions none of the obvious names, and that module then ran alongside the
#: pool it should have been inside and paired against an enclosure another
#: worker was tearing down.
SOCKET_SIGNS = (
    "PiService(",
    "CompanionService(",
    "RunningMock",
    "start_serving",
    "serve_forever",
    "from test_companion import",
    # Modules that reach for sockets or the relay directly rather than through
    # a service: test_robustness names none of the above and binds plenty.
    "import socket",
    "ShotRelay(",
    "LinkServer(",
)

#: Two pools, balanced by measured runtime so neither worker waits on the
#: other: the endurance run is 80 seconds on its own, and these three come to
#: about the same as everything else here put together. Anything newly
#: detected joins the second pool, which is the safe default -- a module in
#: the wrong pool is slow, a module in no pool is flaky.
FIRST_POOL = {"test_endurance", "test_range", "test_live_data"}


def _socket_modules(directory):
    """Which test modules put something on a real port."""

    found = set()
    for path in sorted(directory.glob("test_*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:                       # pragma: no cover
            continue
        if any(sign in source for sign in SOCKET_SIGNS):
            found.add(path.stem)
    return found


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Group every test, so --dist loadgroup can place them deliberately.

    tryfirst matters: xdist stamps the group onto the node id from its own
    collection hook, and a marker added after that is simply not seen. The
    tests then spread across every worker and the grouping silently does
    nothing -- which is exactly what happened, and only showed up as the
    socket-heavy module running four times faster than it can run serially.
    """

    socket_modules = _socket_modules(pathlib.Path(__file__).parent)
    for item in items:
        module = pathlib.Path(str(item.nodeid).split("::")[0]).stem
        if module in FIRST_POOL:
            group = "network-a"
        elif module in socket_modules:
            group = "network-b"
        else:
            # Everything else keeps its own file on one worker, which is what
            # --dist loadfile used to do.
            group = module
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
