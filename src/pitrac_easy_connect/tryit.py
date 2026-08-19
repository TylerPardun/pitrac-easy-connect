"""A hands-on test you run yourself, to see the whole thing work.

Starts a stand-in golf simulator on this computer and the real Companion, finds
your PiTrac on the network, and then gets out of the way so you can do the rest
through the two web pages exactly as a new owner would.

What this proves: a computer finds the enclosure by itself, pairs with a code
read off the enclosure's own page, and carries a shot from PiTrac into the
simulator. None of it involves logging into the Pi.

What it cannot prove on a Mac: GSPro and E6 are Windows programs, so a stand-in
takes their place here. The messages on the wire are the real ones.
"""

import argparse
import json
import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__
from .common import discovery
from .companion.service import CompanionService
from .companion.web import CompanionHTTPServer
from .mock_simulators import RunningMock
from .models import Simulator

GREEN = "\033[32m"
BOLD = "\033[1m"
DIM = "\033[2m"
OFF = "\033[0m"


def say(text=""):
    print(text, flush=True)


def heading(text):
    say("\n{}{}{}".format(BOLD, text, OFF))


def find_enclosure(companion, timeout=25.0):
    """Search through the Companion, so the enclosure it finds is the one it pairs with."""

    say("Looking for your PiTrac on this network...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = companion.search(timeout=2.5)
        if found:
            return found
        say("  nothing yet, still looking...")
    return []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Try PiTrac Easy Connect against your own enclosure"
    )
    parser.add_argument("simulator", nargs="?", default="gspro",
                        choices=[item.value for item in Simulator])
    parser.add_argument("--companion-port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    simulator = Simulator(args.simulator)

    say("{}PiTrac Easy Connect {} - hands-on test{}".format(BOLD, __version__, OFF))
    say("{}This starts a stand-in {} on this computer. Nothing on the Pi is changed.{}".format(
        DIM, simulator.label, OFF))

    companion = CompanionService(
        config_path=Path.home() / ".pitrac-easy-connect-test.json",
        simulator_ports={simulator: 0},
        computer_name=socket.gethostname() or "This computer",
    )
    enclosures = find_enclosure(companion)
    if not enclosures:
        companion.close()
        say("\n{}No PiTrac found on this network.{}".format(BOLD, OFF))
        say("  - Is the enclosure powered on?")
        say("  - Is this computer on the same Wi-Fi as the enclosure?")
        say("  - If PiTrac cannot reach your Wi-Fi it makes its own signal instead:")
        say("    look for a network named PiTrac-XXXXXXXX and join that.")
        return 1

    enclosure = enclosures[0]
    say("\n{}Found {} ({}) at {}{}".format(
        GREEN, enclosure["displayName"], enclosure["deviceId"], enclosure["address"], OFF))
    say("  It says its state is: {}".format(enclosure["state"]))
    setup_page = "http://{}".format(enclosure["address"])

    with RunningMock(simulator, quiet=True) as mock:
        say("\nStand-in {} listening on this computer, port {}.".format(
            simulator.label, mock.address[1]))

        companion.simulator_ports[simulator] = mock.address[1]
        companion.store.set("simulator", simulator.value)
        server = CompanionHTTPServer(("127.0.0.1", args.companion_port), companion)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        companion_url = "http://127.0.0.1:{}".format(server.server_port)

        heading("Do this, in your browser:")
        say("  1. Easy Connect is open at   {}{}{}".format(BOLD, companion_url, OFF))
        say("  2. The PiTrac setup page is  {}{}{}".format(BOLD, setup_page, OFF))
        say("")
        say("  3. On the PiTrac setup page, find the six-digit code under 'Pair your PC'.")
        say("  4. In Easy Connect, press Search, click your enclosure, and type that code.")
        say("  5. Press 'Send a test shot'. Watch this window - the shot appears below.")
        say("")
        say("{}Everything you just did was through two web pages. No terminal on the Pi.{}"
            .format(DIM, OFF))

        if not args.no_browser:
            threading.Timer(0.6, lambda: webbrowser.open(companion_url)).start()
            threading.Timer(1.4, lambda: webbrowser.open(setup_page)).start()

        heading("Live - shots arriving at the stand-in simulator:")
        say("{}(press Control-C when you have seen enough){}".format(DIM, OFF))

        # Handle the stop signals explicitly rather than relying on
        # KeyboardInterrupt, so the summary is printed however this is stopped.
        stopping = threading.Event()
        for received_signal in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(received_signal, lambda *_a: stopping.set())
            except ValueError:
                pass

        seen = 0
        try:
            while not stopping.is_set():
                stopping.wait(0.4)
                received = mock.received
                while seen < len(received):
                    _describe_shot(received[seen], simulator, seen + 1)
                    seen += 1
        except KeyboardInterrupt:
            pass

        heading("How it went")
        status = companion.status()
        for hop in status["chain"]:
            say("  [{}] {}".format("x" if hop["ok"] else " ", hop["title"]))
        say("\n  State: {}{}{}".format(BOLD, status["state"], OFF))
        say("  Messages the simulator received: {}".format(len(mock.received)))
        if status["ready"]:
            say("\n{}That is the whole path working: PiTrac -> your network -> this computer"
                " -> the simulator.{}".format(GREEN, OFF))
        else:
            blocking = status.get("nextStep")
            if blocking:
                say("\n  Did not finish. The next thing to fix was: {}".format(blocking))

        companion.close()
        server.server_close()
    return 0


def _describe_shot(message, simulator, number):
    ball = message.get("BallData") or {}
    if simulator is Simulator.GSPRO and ball:
        say("  {}shot {}{}  {:.1f} mph  launch {:.1f} deg  backspin {} rpm".format(
            GREEN, number, OFF,
            float(ball.get("Speed", 0)), float(ball.get("VLA", 0)), ball.get("BackSpin", 0)))
    elif message.get("Type"):
        say("  {}message {}{}  {}".format(DIM, number, OFF, message.get("Type")))
    else:
        say("  {}message {}{}  {}".format(DIM, number, OFF, json.dumps(message)[:70]))


if __name__ == "__main__":
    raise SystemExit(main())
