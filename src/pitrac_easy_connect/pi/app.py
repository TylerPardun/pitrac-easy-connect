"""Entry point for the Easy Connect service on the Raspberry Pi.

``--simulate`` runs the whole service against a fake Raspberry Pi, which is how
the setup page and the state machine are developed and demonstrated on a Mac.
It changes nothing about the code under test except the backend.
"""

import argparse
import signal
import sys
import threading
from pathlib import Path

from .. import __version__
from ..common import discovery, link
from ..models import Simulator
from .backend import PiBackend
from .nmcli_backend import NmcliBackend
from .portal import PORTAL_PORT, PortalServer
from .relay import DEFAULT_RELAY_PORTS
from .service import DEFAULT_STATE_DIR, PiService, ServicePaths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pitrac-easy-connect",
        description="The PiTrac Easy-Connect service that runs on the enclosure",
    )
    parser.add_argument(
        "--state-dir", type=Path, default=DEFAULT_STATE_DIR,
        help="where device identity, settings, and pairings are kept",
    )
    parser.add_argument("--portal-port", type=int, default=PORTAL_PORT, help="setup page port")
    parser.add_argument("--link-port", type=int, default=link.LINK_PORT, help="Companion port")
    parser.add_argument(
        "--discovery-port", type=int, default=discovery.DISCOVERY_PORT, help="discovery beacon port"
    )
    parser.add_argument("--gspro-relay-port", type=int, default=DEFAULT_RELAY_PORTS[Simulator.GSPRO])
    parser.add_argument("--e6-relay-port", type=int, default=DEFAULT_RELAY_PORTS[Simulator.E6])
    parser.add_argument("--wifi-device", default="wlan0", help="wireless interface name")
    parser.add_argument(
        "--pitrac-config-dir", type=Path, default=None,
        help="PiTrac's config directory (default ~/.pitrac/config)",
    )
    parser.add_argument(
        "--pitrac-images-dir", type=Path, default=None,
        help="where PiTrac writes shot images (default <pitrac home>/LM_Shares/Images)",
    )
    parser.add_argument(
        "--sudo", action="store_true",
        help="run privileged commands through sudo instead of directly as root",
    )
    parser.add_argument(
        "--no-hostname", action="store_true",
        help="do not set the system hostname from the device ID",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="run against a fake Raspberry Pi, for development on a Mac",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def build_pitrac(args) -> "PitracInstallation":
    """Choose which PiTrac installation to read and configure.

    In simulated mode this defaults to a directory inside the state directory,
    so running the service on a development machine never writes into a real
    ``~/.pitrac`` that belongs to something else.
    """

    from .pitrac import CALIBRATION_DATA, IMAGES_DIR, USER_SETTINGS, PitracInstallation

    directory = args.pitrac_config_dir
    if directory is None and args.simulate:
        directory = Path(args.state_dir) / "pitrac-config"
    if directory is None:
        return PitracInstallation(
            USER_SETTINGS, CALIBRATION_DATA, args.pitrac_images_dir or IMAGES_DIR
        )

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    # The service runs as root, so "~" is root's home, not the home of whoever
    # runs PiTrac. Everything PiTrac owns is found relative to its config
    # directory instead, which the installer passes in explicitly.
    images = args.pitrac_images_dir
    if images is None:
        pitrac_home = directory.parent.parent
        images = pitrac_home / "LM_Shares" / "Images"
    return PitracInstallation(
        directory / "user_settings.json", directory / "calibration_data.json", Path(images)
    )


def build_backend(args) -> PiBackend:
    if args.simulate:
        from .simulated import home_network_pi

        return home_network_pi(country="US")
    return NmcliBackend(device=args.wifi_device, sudo=args.sudo)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    backend = build_backend(args)

    service = PiService(
        backend,
        paths=ServicePaths(Path(args.state_dir)),
        pitrac=build_pitrac(args),
        relay_ports={
            Simulator.GSPRO: args.gspro_relay_port,
            Simulator.E6: args.e6_relay_port,
        },
        link_port=args.link_port,
        discovery_port=args.discovery_port,
        portal_port=args.portal_port,
        manage_hostname=not args.no_hostname and not args.simulate,
    )
    service.start()

    try:
        portal = PortalServer(("0.0.0.0", args.portal_port), service)
    except OSError as exc:
        service.stop()
        print(
            "Could not open the setup page on port {}: {}".format(args.portal_port, exc),
            file=sys.stderr,
        )
        if args.portal_port < 1024:
            print("Ports below 1024 need root. Try --portal-port 8088.", file=sys.stderr)
        return 1

    identity = service.identity
    print("PiTrac Easy-Connect {} is running.".format(__version__))
    print("  Enclosure:   {} ({})".format(identity.display_name, identity.device_id))
    print("  Setup page:  http://localhost:{}".format(portal.server_port))
    print("  Recovery:    {}".format(identity.recovery_address))
    print("  Setup Wi-Fi: {}".format(identity.setup_ssid))
    print("  State:       {}".format(service.state.value))
    print("Press Control-C to stop.")

    stopping = threading.Event()

    def handle_signal(_signum, _frame):
        stopping.set()
        threading.Thread(target=portal.shutdown, daemon=True).start()

    for received in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(received, handle_signal)
        except ValueError:
            pass

    try:
        portal.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        portal.server_close()
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
