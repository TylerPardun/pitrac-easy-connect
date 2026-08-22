"""Entry point for the Easy Connect Companion on the simulator PC."""

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from .. import __version__
from ..common import discovery
from ..models import Simulator
from .service import CompanionService
from .web import CompanionHTTPServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pitrac-companion", description="PiTrac Easy-Connect for your simulator PC"
    )
    parser.add_argument("--port", type=int, default=8787, help="local interface port")
    parser.add_argument(
        "--gspro-port", type=int, default=Simulator.GSPRO.default_port, help="GSPro port"
    )
    parser.add_argument("--e6-port", type=int, default=Simulator.E6.default_port, help="E6 port")
    parser.add_argument("--simulator-host", default="127.0.0.1", help="where the simulator runs")
    parser.add_argument("--discovery-port", type=int, default=discovery.DISCOVERY_PORT)
    parser.add_argument("--config", type=Path, default=None, help="settings file location")
    parser.add_argument("--computer-name", default=None, help="name shown on the enclosure")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--hidden", action="store_true",
        help="start without opening a window; use the shortcut before a golf session",
    )
    parser.add_argument(
        "--window", action="store_true",
        help="open as an application window rather than a browser tab",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    service = CompanionService(
        config_path=args.config,
        simulator_ports={Simulator.GSPRO: args.gspro_port, Simulator.E6: args.e6_port},
        simulator_host=args.simulator_host,
        discovery_port=args.discovery_port,
        computer_name=args.computer_name,
    )

    # Loopback only. The Companion holds pairing secrets and must not be
    # reachable from the residence network.
    try:
        server = CompanionHTTPServer(("127.0.0.1", args.port), service)
    except OSError as exc:
        return _handle_busy_port(args, service, exc)
    return _run(args, service, server)


def _run(args, service, server) -> int:
    url = "http://127.0.0.1:{}".format(server.server_port)
    print("PiTrac Easy-Connect {} is running at {}".format(__version__, url))

    if service.store.get("activeDeviceId"):
        # Reconnect to the enclosure this PC used last, without being asked.
        threading.Thread(target=_reconnect, args=(service,), daemon=True).start()

    wants_window = args.window and not args.no_browser and not args.hidden
    try:
        if wants_window:
            from .window import native_available, open_in_browser, run_native

            # A native window has to own the main thread on both macOS and
            # Windows, so the web server moves to a background thread.
            threading.Thread(target=server.serve_forever, daemon=True).start()

            if native_available() and run_native(url):
                return 0  # the user closed the window

            # No native backend on this machine: fall back to an
            # browser and wait as before.
            print("No native window on this machine; opening it in your browser.")
            open_in_browser(url)
            _wait_for_stop(server)
            return 0

        print("Press Control-C to stop it.")
        if not args.no_browser and not args.hidden:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        if args.hidden:
            print("Running in the background. Open {} to see it.".format(url))
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()
        service.close()
    return 0


def _handle_busy_port(args, service, failure: OSError) -> int:
    """Decide what to do when the usual port will not open.

    The packaged Windows app has no console, so an exception here is invisible:
    double-clicking the icon appears to do nothing at all. Every path out of
    this either shows the running copy, starts anyway somewhere else, or says
    what went wrong somewhere the user can actually see it.
    """

    import errno

    if failure.errno not in (errno.EADDRINUSE, errno.EACCES):
        service.close()
        _say_it_failed(
            "PiTrac Easy-Connect could not start.\n\n{}".format(failure)
        )
        return 1

    running = _already_running(args.port)
    if running:
        # A second double-click on the icon. Show the copy that is already
        # there rather than starting a rival that cannot hold the port.
        service.close()
        url = "http://127.0.0.1:{}".format(args.port)
        print("PiTrac Easy-Connect is already running; opening {}".format(url))
        _show(args, url)
        return 0

    # Something that is not Easy-Connect holds the port. Take any free one:
    # nothing else on this machine needs to find us at a fixed number.
    try:
        server = CompanionHTTPServer(("127.0.0.1", 0), service)
    except OSError as exc:
        service.close()
        _say_it_failed("PiTrac Easy-Connect could not start.\n\n{}".format(exc))
        return 1
    print(
        "Port {} is in use by something else; using {} instead.".format(
            args.port, server.server_port
        )
    )
    return _run(args, service, server)


def _already_running(port: int) -> bool:
    """Whether the thing holding the port is another copy of this program."""

    import json as _json
    import urllib.error
    import urllib.request

    try:
        request = urllib.request.Request(
            "http://127.0.0.1:{}/api/status".format(port),
            headers={"X-PiTrac-App": "1"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = _json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    # computerName is ours; a different program answering 200 on this port
    # will not have it.
    return "computerName" in body and "state" in body


def _show(args, url: str) -> None:
    """Put the interface in front of the user, however this build does that."""

    if args.no_browser or args.hidden:
        return
    if args.window:
        try:
            from .window import native_available, open_in_browser, run_native

            if native_available() and run_native(url):
                return
            open_in_browser(url)
            return
        except Exception:
            pass
    webbrowser.open(url)


def _say_it_failed(message: str) -> None:
    """Report a startup failure where a user without a console will see it."""

    print(message)
    try:
        if sys.platform == "win32":
            import ctypes

            # 0x10 is MB_ICONERROR.
            ctypes.windll.user32.MessageBoxW(None, message, "PiTrac Easy-Connect", 0x10)
        elif sys.platform == "darwin":
            import subprocess

            subprocess.run(
                ["osascript", "-e",
                 'display alert "PiTrac Easy-Connect" message {}'.format(
                     _applescript_string(message))],
                check=False, timeout=30,
            )
    except Exception:
        # A dialog that will not open must not become the failure the user
        # sees instead of the one that actually happened.
        pass


def _applescript_string(text: str) -> str:
    return '"{}"'.format(text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " "))


def _wait_for_stop(server) -> None:
    """Keep running until the page asks the program to stop, or Control-C."""

    try:
        while not server.stopped.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass


def _reconnect(service: CompanionService) -> None:
    try:
        service.search()
        service.connect()
    except Exception:
        # Failing to reconnect is reported through the interface, not a crash.
        pass


if __name__ == "__main__":
    raise SystemExit(main())
