import argparse
import threading
import webbrowser

from .mock_simulators import RunningMock
from .models import Simulator
from .service import CompanionService
from .web import CompanionHTTPServer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete Easy Connect desktop demo")
    parser.add_argument("simulator", choices=[item.value for item in Simulator], nargs="?", default="gspro")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    simulator = Simulator(args.simulator)
    mock_port = 19210 if simulator is Simulator.GSPRO else Simulator.E6.default_port
    ports = {
        Simulator.GSPRO: 19210,
        Simulator.E6: Simulator.E6.default_port,
    }

    with RunningMock(simulator, port=mock_port):
        service = CompanionService(simulator_ports=ports)
        service.select(simulator.value)
        server = CompanionHTTPServer(("127.0.0.1", 8787), service)
        url = "http://127.0.0.1:{}".format(server.server_port)
        print("Fake {} and Easy Connect are running.".format(simulator.label))
        print("Open {} and press Control-C when finished.".format(url))
        if not args.no_browser:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()

