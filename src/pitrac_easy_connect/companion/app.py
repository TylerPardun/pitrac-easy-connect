"""Entry point for the Easy Connect Companion on the simulator PC."""

import argparse
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
        prog="pitrac-companion", description="PiTrac Easy Connect for your simulator PC"
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
    server = CompanionHTTPServer(("127.0.0.1", args.port), service)
    url = "http://127.0.0.1:{}".format(server.server_port)
    print("PiTrac Easy Connect {} is running at {}".format(__version__, url))
    print("Press Control-C to stop it.")

    if service.store.get("activeDeviceId"):
        # Reconnect to the enclosure this PC used last, without being asked.
        threading.Thread(target=_reconnect, args=(service,), daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
    return 0


def _reconnect(service: CompanionService) -> None:
    try:
        service.search()
        service.connect()
    except Exception:
        # Failing to reconnect is reported through the interface, not a crash.
        pass


if __name__ == "__main__":
    raise SystemExit(main())
