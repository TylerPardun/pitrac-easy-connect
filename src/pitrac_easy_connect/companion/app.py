"""Entry point for the native PiTrac Easy-Connect desktop application."""

import argparse
import sys
import threading
from pathlib import Path

from .. import __version__
from ..common import discovery
from ..models import Simulator
from .service import CompanionService
from .web import CompanionHTTPServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pitrac-easy-connect", description="PiTrac Easy-Connect desktop application"
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
    parser.add_argument(
        "--headless", action="store_true",
        help="run the local API without a window (CI, automated tests, or service use only)",
    )
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="exercise guarded page requests in the real native window (release validation)",
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
    try:
        server = CompanionHTTPServer(("127.0.0.1", args.port), service)
    except OSError as exc:
        return _handle_busy_port(args, service, exc)
    return _run(args, service, server)


def _run(args, service, server) -> int:
    url = "http://127.0.0.1:{}".format(server.server_port)
    print("PiTrac Easy-Connect {} is running at {}".format(__version__, url))
    if service.store.get("activeDeviceId"):
        threading.Thread(target=_reconnect, args=(service,), daemon=True).start()

    try:
        if args.headless:
            service.set_window_state("headless")
            print("Headless mode is active. Press Control-C to stop it.")
            server.serve_forever()
            return 0

        if args.smoke_test:
            url += "?pitracSmoke=1"
        return _show_native(service, url, serve=server.serve_forever)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()
        service.close()


def _show_native(service: CompanionService, url: str, serve=None) -> int:
    from .window import NativeWindowError, run_native

    service.set_window_state("starting")
    try:
        run_native(
            url,
            on_created=lambda: service.set_window_state("native"),
            on_activation_ready=service.register_window_activator,
            on_close_ready=service.register_window_closer,
            on_started=serve,
        )
    except NativeWindowError as exc:
        reason = str(exc)
        service.set_window_state("failed", reason)
        _say_it_failed(
            "PiTrac Easy-Connect could not open its application window.\n\n{}".format(reason)
        )
        return 1
    return 0


def _handle_busy_port(args, service, failure: OSError) -> int:
    """Handle a bind failure without leaving a windowless desktop process."""

    import errno

    if failure.errno not in (errno.EADDRINUSE, errno.EACCES):
        service.set_window_state("failed", str(failure))
        service.close()
        _say_it_failed("PiTrac Easy-Connect could not start.\n\n{}".format(failure))
        return 1

    instance_token = _running_instance(args.port)
    if instance_token:
        if args.headless:
            service.close()
            return 0
        activated = _activate_running(args.port, instance_token)
        service.close()
        if activated:
            return 0
        _say_it_failed(
            "PiTrac Easy-Connect is already running, but its window could not be brought "
            "to the front. Close it from the application switcher and try again."
        )
        return 1

    try:
        server = CompanionHTTPServer(("127.0.0.1", 0), service)
    except OSError as exc:
        service.set_window_state("failed", str(exc))
        service.close()
        _say_it_failed("PiTrac Easy-Connect could not start.\n\n{}".format(exc))
        return 1
    print("Port {} is in use; using {} instead.".format(args.port, server.server_port))
    return _run(args, service, server)


def _already_running(port: int) -> bool:
    """Compatibility predicate used by startup tests and diagnostics."""

    return bool(_running_instance(port))


def _running_instance(port: int) -> str:
    import json
    import urllib.error
    import urllib.request

    try:
        request = urllib.request.Request(
            "http://127.0.0.1:{}/api/instance".format(port),
            headers={"X-PiTrac-App": "1"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return ""
    if body.get("application") != "PiTrac Easy-Connect":
        return ""
    token = str(body.get("instanceToken", ""))
    return token if len(token) >= 32 else ""


def _activate_running(port: int, instance_token: str) -> bool:
    import json
    import urllib.error
    import urllib.request

    payload = json.dumps({"instanceToken": instance_token}).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:{}/api/activate".format(port),
        data=payload,
        headers={"X-PiTrac-App": "1", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return bool(body.get("activated") or body.get("queued"))


def _say_it_failed(message: str) -> None:
    """Show the actual startup reason in an operating-system dialog."""

    print(message, file=sys.stderr)
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "PiTrac Easy-Connect", 0x10)
            return
        if sys.platform == "darwin":
            import subprocess

            subprocess.run(
                ["osascript", "-e", 'display alert "PiTrac Easy-Connect" message {}'.format(
                    _applescript_string(message)
                )],
                check=False, timeout=30,
            )
            return
        _linux_error_dialog(message)
    except Exception as dialog_error:
        print("The error dialog also failed: {}".format(dialog_error), file=sys.stderr)


def _linux_error_dialog(message: str) -> None:
    import shutil
    import subprocess

    commands = (
        ("zenity", ["zenity", "--error", "--title=PiTrac Easy-Connect", "--text", message]),
        ("kdialog", ["kdialog", "--error", message, "--title", "PiTrac Easy-Connect"]),
        ("xmessage", ["xmessage", "-center", message]),
    )
    for executable, command in commands:
        if shutil.which(executable):
            subprocess.run(command, check=False, timeout=30)
            return
    raise RuntimeError("no desktop error-dialog provider is installed")


def _applescript_string(text: str) -> str:
    return '"{}"'.format(text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " "))


def _reconnect(service: CompanionService) -> None:
    try:
        service.search()
        service.connect()
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
