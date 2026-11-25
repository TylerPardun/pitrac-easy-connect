"""Entry point for the native PiTrac Easy-Connect desktop application."""

import argparse
import os
import sys
import threading
from pathlib import Path

from .. import __version__
from ..common import jsontext
from ..common import discovery, updates
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
    parser.add_argument(
        "--ogs-port", type=int, default=Simulator.OGS.default_port, help="OpenGolfSim port"
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
    parser.add_argument(
        "--packaged-smoke-installed-version", default="", help=argparse.SUPPRESS,
    )
    # Internal restart proof. The helper supplies all four arguments; a normal
    # launch supplies none. They are deliberately not useful independently.
    parser.add_argument("--post-update-journal", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--post-update-token", default="", help=argparse.SUPPRESS)
    parser.add_argument("--post-update-helper-pid", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--post-update-helper-path", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--version-probe-output", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def _runtime_version(args) -> str:
    """Allow only packaged CI to make the candidate exercise its updater.

    The binary's real ``--version`` and restart acknowledgement always remain
    the compiled version. This changes only the version supplied to the
    updater service in the explicit native smoke process, so it can download
    and verify the same candidate archive before preflight is deliberately
    refused.
    """

    requested = str(args.packaged_smoke_installed_version or "").strip()
    if not requested:
        return __version__
    if not (
        args.smoke_test
        and os.environ.get("PITRAC_PACKAGED_UPDATE_SMOKE") == "1"
    ):
        raise ValueError(
            "the packaged-smoke version override is restricted to native release validation"
        )
    return requested


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        runtime_version = _runtime_version(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if (
        args.post_update_journal
        and os.environ.get("PITRAC_PACKAGED_UPDATE_SMOKE") == "1"
    ):
        # Release CI starts the actual preceding artifact, which cannot know a
        # future --smoke-test relaunch flag. The inherited, test-only
        # environment makes only that post-update candidate exercise its page.
        args.smoke_test = True
    if args.version_probe_output is not None:
        from . import self_update
        try:
            self_update.write_version_probe(args.version_probe_output, __version__)
        except self_update.SelfUpdateError:
            return 1
        return 0
    from . import self_update
    restart_context = None
    if not args.post_update_journal:
        # If power/process interruption happened after promotion but before
        # helper-provided restart arguments arrived, locate the transaction.
        # This does not write an acknowledgement; only the native shown
        # callback (or the explicitly gated headless health probe) may do that.
        restart_context = self_update.recover_pending_restart(
            version=__version__, executable=Path(sys.executable)
        )
    relaunch_arguments = [
        "--port", str(args.port),
        "--gspro-port", str(args.gspro_port),
        "--ogs-port", str(args.ogs_port),
        "--e6-port", str(args.e6_port),
        "--simulator-host", str(args.simulator_host),
        "--discovery-port", str(args.discovery_port),
    ]
    if args.config is not None:
        relaunch_arguments.extend(["--config", str(args.config)])
    if args.computer_name:
        relaunch_arguments.extend(["--computer-name", str(args.computer_name)])
    if args.headless:
        # Packaged update/rollback tests deliberately run without a desktop.
        # A normal user launch never carries this flag, so production restarts
        # still reopen the native window.
        relaunch_arguments.append("--headless")
    if args.smoke_test:
        relaunch_arguments.append("--smoke-test")
    service = CompanionService(
        config_path=args.config,
        simulator_ports={
            Simulator.GSPRO: args.gspro_port,
            Simulator.OGS: args.ogs_port,
            Simulator.E6: args.e6_port,
        },
        simulator_host=args.simulator_host,
        discovery_port=args.discovery_port,
        computer_name=args.computer_name,
        desktop_relaunch_arguments=relaunch_arguments,
        version=runtime_version,
        updates_published=updates.PUBLISHED,
    )
    try:
        server = CompanionHTTPServer(("127.0.0.1", args.port), service)
    except OSError as exc:
        return _handle_busy_port(args, service, exc)
    restart_ready = None
    if args.post_update_journal:
        try:
            if os.environ.get("PITRAC_FAILURE_INJECT_NO_ACK") == "1":
                journal = self_update.load_journal(args.post_update_journal)
                if journal["phase"] in (
                    "current-promoted", "awaiting-restart-verification"
                ):
                    raise self_update.SelfUpdateError(
                        "restart acknowledgement failure injected by packaged CI"
                    )
            # Validate immediately, but a GUI restart must not acknowledge
            # until pywebview has actually shown the native window. Otherwise
            # the helper could delete the rollback copy after a bound port but
            # before discovering that the desktop backend cannot start.
            _journal, actual = self_update.validate_restart(
                args.post_update_journal,
                args.post_update_token,
                version=__version__,
                executable=Path(sys.executable),
            )
            restart_context = self_update.PendingRestart(
                journal_path=args.post_update_journal,
                token=str(args.post_update_token),
                version=__version__,
                executable=actual,
            )
        except self_update.SelfUpdateError as exc:
            service.close()
            server.server_close()
            message = "The updated application could not verify its restart.\n\n{}".format(exc)
            if args.headless:
                print(message, file=sys.stderr)
            else:
                _say_it_failed(message)
            return 1
    if restart_context is not None:
        def restart_ready():
            self_update.acknowledge_pending_restart(restart_context)
            service.watch_install_result(restart_context.journal_path)
            if args.post_update_helper_pid and args.post_update_helper_path:
                self_update.cleanup_independent_helper(
                    args.post_update_helper_pid, args.post_update_helper_path
                )
    return _run(args, service, server, on_ready=restart_ready)


def _run(args, service, server, on_ready=None) -> int:
    url = "http://127.0.0.1:{}".format(server.server_port)
    print("PiTrac Easy-Connect {} is running at {}".format(__version__, url))
    if service.store.get("activeDeviceId"):
        threading.Thread(target=_reconnect, args=(service,), daemon=True).start()

    try:
        if args.headless:
            service.set_window_state("headless")
            health = {"passed": on_ready is None, "detail": ""}
            if on_ready is not None:
                if os.environ.get("PITRAC_ALLOW_HEADLESS_UPDATE_ACK") != "1":
                    print(
                        "A post-update headless restart cannot acknowledge outside "
                        "the guarded packaged-test health path.",
                        file=sys.stderr,
                    )
                    return 1

                def prove_guarded_health():
                    import urllib.request

                    deadline = __import__("time").monotonic() + 20
                    while __import__("time").monotonic() < deadline:
                        try:
                            request = urllib.request.Request(
                                url + "/api/status", headers={"X-PiTrac-App": "1"}
                            )
                            with urllib.request.urlopen(request, timeout=2) as response:
                                status = jsontext.loads(response.read().decode("utf-8"))
                            if (
                                status.get("version") == __version__
                                and status.get("window", {}).get("state") == "headless"
                            ):
                                on_ready()
                                health["passed"] = True
                                return
                        except Exception as exc:
                            health["detail"] = str(exc)
                        __import__("time").sleep(0.1)
                    health["detail"] = health["detail"] or "guarded health request timed out"
                    server.shutdown()

                threading.Thread(target=prove_guarded_health, daemon=True).start()
            print("Headless mode is active. Press Control-C to stop it.")
            server.serve_forever()
            if not health["passed"]:
                print(
                    "The guarded post-update health check failed: {}".format(health["detail"]),
                    file=sys.stderr,
                )
                return 1
            return 0

        if args.smoke_test:
            url += "?pitracSmoke=1"
        return _show_native(service, url, serve=server.serve_forever, on_ready=on_ready)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()
        service.close()


def _show_native(service: CompanionService, url: str, serve=None, on_ready=None) -> int:
    from .window import NativeWindowError, run_native

    service.set_window_state("starting")
    try:
        run_native(
            url,
            on_created=lambda: _on_window_created(service, on_ready=on_ready),
            on_activation_ready=service.register_window_activator,
            on_close_ready=service.register_window_closer,
            on_fullscreen_ready=service.register_fullscreen,
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


def _on_window_created(service: CompanionService, on_ready=None) -> None:
    """The window is actually usable now, not merely under construction.

    A fresh update check fired here, on top of the one already started when
    the service was built, is what guarantees "shortly after the window
    becomes usable" regardless of exactly when the earlier one happened to
    land relative to window startup -- it is a cache hit and a no-op if the
    earlier one already finished, and the first real check if it had not.
    """

    service.set_window_state("native")
    if on_ready is not None:
        on_ready()
    try:
        service.trigger_update_check()
    except Exception:
        pass


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
            body = jsontext.loads(response.read().decode("utf-8"))
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
            body = jsontext.loads(response.read().decode("utf-8"))
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
