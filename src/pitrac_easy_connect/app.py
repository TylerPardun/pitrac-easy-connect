import argparse
import threading
import webbrowser

from .models import Simulator
from .service import CompanionService
from .web import CompanionHTTPServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PiTrac Easy Connect desktop prototype")
    parser.add_argument("--port", type=int, default=8787, help="local web interface port")
    parser.add_argument(
        "--gspro-port", type=int, default=921, help="GSPro destination port"
    )
    parser.add_argument(
        "--e6-port", type=int, default=2483, help="E6 destination port"
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    ports = {Simulator.GSPRO: args.gspro_port, Simulator.E6: args.e6_port}
    server = CompanionHTTPServer(
        ("127.0.0.1", args.port), CompanionService(simulator_ports=ports)
    )
    url = "http://127.0.0.1:{}".format(server.server_port)
    print("PiTrac Easy Connect is running at {}".format(url))
    print("Press Control-C to stop it.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
