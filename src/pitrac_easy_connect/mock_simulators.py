import argparse
import json
import os
import socketserver
import threading
from typing import Any, Dict, List, Optional, Tuple

from .models import Simulator


class MockTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: Tuple[str, int], simulator: Simulator):
        self.simulator = simulator
        self.received: List[Dict[str, Any]] = []
        self.received_lock = threading.Lock()
        super().__init__(address, MockHandler)

    def record(self, message: Dict[str, Any]) -> None:
        with self.received_lock:
            self.received.append(message)


class MockHandler(socketserver.BaseRequestHandler):
    server: MockTCPServer

    def handle(self) -> None:
        buffer = ""
        decoder = json.JSONDecoder()
        e6_types = set()
        while True:
            chunk = self.request.recv(8192)
            if not chunk:
                return
            try:
                buffer += chunk.decode("utf-8")
            except UnicodeDecodeError:
                return

            while True:
                stripped = buffer.lstrip()
                if not stripped:
                    buffer = ""
                    break
                try:
                    message, consumed = decoder.raw_decode(stripped)
                except json.JSONDecodeError:
                    buffer = stripped
                    break
                buffer = stripped[consumed:]
                if not isinstance(message, dict):
                    return
                self.server.record(message)
                print("{} mock received: {}".format(self.server.simulator.label, message))

                if self.server.simulator is Simulator.GSPRO:
                    self._send({"Code": 200, "Message": "Shot received successfully"})
                    continue

                message_type = message.get("Type")
                e6_types.add(message_type)
                if message_type == "Handshake":
                    self._send({"Type": "HandshakeAck"})
                elif message_type == "SendShot":
                    required = {"SetBallData", "SetClubData", "SendShot"}
                    if required.issubset(e6_types):
                        self._send({"Type": "ShotAccepted"})
                    else:
                        self._send({"Type": "Error", "Message": "Shot sequence incomplete"})

    def _send(self, message: Dict[str, Any]) -> None:
        self.request.sendall(json.dumps(message, separators=(",", ":")).encode("utf-8"))


class RunningMock:
    def __init__(self, simulator: Simulator, host: str = "127.0.0.1", port: int = 0):
        self.server = MockTCPServer((host, port), simulator)
        self.thread: Optional[threading.Thread] = None

    @property
    def address(self) -> Tuple[str, int]:
        host, port = self.server.server_address
        return str(host), int(port)

    @property
    def received(self) -> List[Dict[str, Any]]:
        with self.server.received_lock:
            return list(self.server.received)

    def start(self) -> "RunningMock":
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)

    def __enter__(self) -> "RunningMock":
        return self.start()

    def __exit__(self, *_args: Any) -> None:
        self.stop()


def run_mock(simulator: Simulator, port: Optional[int] = None) -> None:
    if port is None:
        # Unix reserves ports below 1024 for privileged processes. Real GSPro
        # runs on Windows at 921; local development uses an unprivileged port.
        if simulator is Simulator.GSPRO and os.name != "nt":
            selected_port = 19210
        else:
            selected_port = simulator.default_port
    else:
        selected_port = port
    server = MockTCPServer(("127.0.0.1", selected_port), simulator)
    print("Fake {} is listening on 127.0.0.1:{}".format(simulator.label, server.server_address[1]))
    print("Press Control-C to stop it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local fake GSPro or E6 server")
    parser.add_argument("simulator", choices=[item.value for item in Simulator])
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    run_mock(Simulator(args.simulator), args.port)


def gspro_main() -> None:
    run_mock(Simulator.GSPRO)


def e6_main() -> None:
    run_mock(Simulator.E6)


if __name__ == "__main__":
    main()
