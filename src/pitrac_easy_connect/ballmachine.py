"""A stand-in for the launch monitor, so the whole system can be tested early.

``pitrac_lm`` connects out to the relay and sends shots. Nothing about that
requires it to be PiTrac: anything that speaks the same protocol to the same
port exercises the identical path. So this connects to the relay on the Pi and
feeds it realistic shots.

That matters because it is **not a mock of our software**. The relay, the paired
link, the encryption, the companion, the simulator session, the shot log and the
range are all the real ones, running in the real order. The only thing replaced
is the camera and the ball, which are the parts that are still in transit.

    # one shot, to see it work
    python3 -m pitrac_easy_connect.ballmachine --host pitrac.local

    # a bucket of balls, realistically spaced
    python3 -m pitrac_easy_connect.ballmachine --host pitrac.local --shots 40

    # hammer it, to see what falls over
    python3 -m pitrac_easy_connect.ballmachine --host pitrac.local \\
        --shots 500 --interval 0.05

Run it on the Pi itself, or from anywhere that can reach the relay port.
"""

import argparse
import json
import random
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import Simulator
from .pi.relay import DEFAULT_RELAY_PORTS

#: Ball speed mph, launch degrees, backspin rpm, and how much each varies.
#: Loosely a decent amateur rather than a Tour player, because that is who
#: will be hitting into it.
CLUBS: List[Tuple[str, float, float, float, float, float]] = [
    # club,            speed, launch, spin,  speed sd, dispersion sd (deg)
    ("Driver",         148.0, 12.5,  2900,   6.0, 2.4),
    ("3 wood",         141.0, 11.8,  3600,   5.0, 2.2),
    ("5 iron",         120.0, 15.0,  5200,   4.5, 2.0),
    ("7 iron",         108.0, 18.5,  6900,   4.0, 1.8),
    ("9 iron",          98.0, 22.5,  8500,   3.5, 1.6),
    ("Pitching wedge",  88.0, 26.0,  9200,   3.0, 1.5),
    ("Sand wedge",      72.0, 31.0, 10200,   3.0, 1.8),
]


def one_shot(club: Optional[str] = None, shank: float = 0.0) -> Dict[str, Any]:
    """A plausible shot, with plausible mishits."""

    if club:
        chosen = next((c for c in CLUBS if c[0].lower() == club.lower()), CLUBS[3])
    else:
        chosen = random.choice(CLUBS)

    name, speed, launch, spin, speed_sd, spread = chosen
    bad = random.random() < shank

    ball_speed = max(20.0, random.gauss(speed, speed_sd * (2.5 if bad else 1.0)))
    vla = max(1.0, random.gauss(launch, 2.0 * (2.5 if bad else 1.0)))
    hla = random.gauss(0.0, spread * (3.0 if bad else 1.0))
    back = max(200.0, random.gauss(spin, spin * 0.12))
    side = random.gauss(0.0, 420.0 * (3.0 if bad else 1.0))

    return {
        "club": name,
        "mishit": bad,
        "payload": {
            "DeviceID": "PiTrac Ball Machine",
            "Units": "Yards",
            "ShotNumber": 0,
            "APIversion": "1",
            "BallData": {
                "Speed": round(ball_speed, 2),
                "SpinAxis": round(_spin_axis(back, side), 2),
                "TotalSpin": round((back**2 + side**2) ** 0.5, 1),
                "BackSpin": int(back),
                "SideSpin": int(side),
                "HLA": round(hla, 2),
                "VLA": round(vla, 2),
            },
            "ClubData": {},
            "ShotDataOptions": {
                "ContainsBallData": True,
                "ContainsClubData": False,
                "LaunchMonitorIsReady": True,
                "LaunchMonitorBallDetected": True,
                "IsHeartBeat": False,
            },
        },
    }


def _spin_axis(back: float, side: float) -> float:
    import math

    return math.degrees(math.atan2(side, max(back, 1.0)))


def fire(
    host: str,
    port: int,
    shots: int,
    interval: float,
    club: Optional[str],
    shank: float,
    timeout: float,
) -> int:
    """Send shots the way the launch monitor does, and report what came back."""

    print("Connecting to the relay at {}:{}".format(host, port))
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        print("Could not reach the relay: {}".format(exc))
        print("Is Easy-Connect running on the Pi, and is this the right host?")
        return 1

    sock.settimeout(timeout)
    sent = replied = lost = 0
    started = time.time()
    slowest = 0.0

    try:
        for number in range(1, shots + 1):
            shot = one_shot(club, shank)
            shot["payload"]["ShotNumber"] = number
            body = (json.dumps(shot["payload"]) + "\n").encode("utf-8")

            at = time.time()
            sock.sendall(body)
            sent += 1

            answer = _read_reply(sock, timeout)
            took = time.time() - at
            slowest = max(slowest, took)
            if answer is None:
                lost += 1
                mark = "no reply"
            else:
                replied += 1
                mark = "{} in {:.0f} ms".format(answer.get("Code", "?"), took * 1000)

            print("  {:>4}  {:<15} {:>6.1f} mph  {:>5.1f}deg  {:>5.0f} rpm  {}{}".format(
                number, shot["club"], shot["payload"]["BallData"]["Speed"],
                shot["payload"]["BallData"]["VLA"],
                shot["payload"]["BallData"]["BackSpin"], mark,
                "  MISHIT" if shot["mishit"] else ""))

            if interval and number < shots:
                time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    except OSError as exc:
        print("\nThe relay closed the connection: {}".format(exc))
    finally:
        sock.close()

    elapsed = time.time() - started
    print("\n{} sent, {} acknowledged, {} without a reply, in {:.1f} s".format(
        sent, replied, lost, elapsed))
    print("slowest round trip {:.0f} ms".format(slowest * 1000))
    if lost:
        print("\nShots without a reply are not necessarily lost: the relay only "
              "answers when a computer is connected and its simulator is up.")
    return 0 if sent else 1


def _read_reply(sock: socket.socket, timeout: float) -> Optional[Dict[str, Any]]:
    """Read one JSON reply.

    The simulators do not delimit their replies with a newline -- a reply is
    simply a complete JSON object -- so this reads until what has arrived
    parses, rather than waiting for a terminator that never comes.
    """

    deadline = time.time() + timeout
    buffered = b""
    while time.time() < deadline:
        try:
            sock.settimeout(max(0.05, deadline - time.time()))
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            return None
        buffered += chunk
        text = buffered.decode("utf-8", "replace").strip()
        # A reply may arrive alongside the next one; take the first object.
        decoder = json.JSONDecoder()
        try:
            value, _end = decoder.raw_decode(text)
            return value if isinstance(value, dict) else None
        except ValueError:
            continue
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m pitrac_easy_connect.ballmachine",
        description="Feed the relay realistic shots, so everything downstream "
                    "can be tested before the cameras arrive.",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="where Easy-Connect is running (default: this machine)")
    parser.add_argument("--simulator", choices=[s.value for s in Simulator],
                        default=Simulator.GSPRO.value)
    parser.add_argument("--port", type=int, help="override the relay port")
    parser.add_argument("--shots", type=int, default=1)
    parser.add_argument("--interval", type=float, default=3.0,
                        help="seconds between shots (default: 3, about a real pace)")
    parser.add_argument("--club", help="hit only this club")
    parser.add_argument("--shank", type=float, default=0.08,
                        help="fraction of shots that are mishits (default: 0.08)")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    simulator = Simulator(args.simulator)
    port = args.port or DEFAULT_RELAY_PORTS[simulator]
    return fire(args.host, port, max(1, args.shots), max(0.0, args.interval),
                args.club, min(max(args.shank, 0.0), 1.0), args.timeout)


if __name__ == "__main__":
    sys.exit(main())
