"""Run the entire product on one machine, with nothing real attached.

Starts a fake golf simulator, a simulated Raspberry Pi running the real Easy
Connect service, and the real Companion, then pairs them automatically. Two
browser tabs open: the enclosure's setup page and the Companion.

Every component except the fake Pi hardware and the fake simulator is the code
that ships. This is how the beginner flow is exercised without an enclosure, a
Windows PC, or a copy of GSPro.
"""

import argparse
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

from .companion.service import CompanionService
from .companion.web import CompanionHTTPServer
from .mock_simulators import RunningMock
from .models import Simulator
from .pi.portal import PortalServer
from .pi.service import PiService, ServicePaths
from .pi.simulated import home_network_pi
from .pi.pitrac import PitracInstallation


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the complete Easy-Connect demo locally")
    parser.add_argument(
        "simulator", choices=[item.value for item in Simulator], nargs="?", default="gspro"
    )
    parser.add_argument("--portal-port", type=int, default=8088)
    parser.add_argument("--companion-port", type=int, default=8787)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--no-pair", action="store_true", help="stop before pairing, to try it by hand"
    )
    parser.add_argument(
        "--no-network", action="store_true", help="leave the enclosure on its setup hotspot"
    )
    parser.add_argument(
        "--no-country", action="store_true",
        help="start with no wireless country set, as a brand new enclosure would",
    )
    args = parser.parse_args(argv)

    simulator = Simulator(args.simulator)
    state_dir = Path(args.state_dir or tempfile.mkdtemp(prefix="pitrac-demo-"))
    pitrac_dir = state_dir / "pitrac-config"
    pitrac_dir.mkdir(parents=True, exist_ok=True)
    # Pretend the cameras have been calibrated, so the demo can reach READY.
    (pitrac_dir / "calibration_data.json").write_text(
        '{"gs_config": {"cameras": {"kCamera1CalibrationMatrix": [[1]],'
        ' "kCamera2CalibrationMatrix": [[1]]}}}',
        encoding="utf-8",
    )

    print("PiTrac Easy-Connect demo")
    print("  Fake {} and a simulated Raspberry Pi.".format(simulator.label))
    print("  State: {}".format(state_dir))

    with RunningMock(simulator) as mock:
        service = PiService(
            home_network_pi(country="" if args.no_country else "US"),
            paths=ServicePaths(state_dir / "pi"),
            pitrac=PitracInstallation(
                pitrac_dir / "user_settings.json", pitrac_dir / "calibration_data.json"
            ),
            relay_ports={Simulator.GSPRO: 0, Simulator.E6: 0},
            link_port=0,
            discovery_port=0,
            portal_port=args.portal_port,
            manage_hostname=False,
        )
        service.start()

        portal = PortalServer(("127.0.0.1", args.portal_port), service)
        threading.Thread(target=portal.serve_forever, daemon=True).start()

        companion = CompanionService(
            config_path=state_dir / "companion.json",
            simulator_ports={simulator: mock.address[1]},
            discovery_port=service.discovery.port,
            computer_name="Demo PC",
        )
        companion.select_simulator(simulator.value)
        web = CompanionHTTPServer(("127.0.0.1", args.companion_port), companion)
        threading.Thread(target=web.serve_forever, daemon=True).start()

        if not args.no_network:
            service.command("joinNetwork", {"ssid": "Ferndale", "password": "GoodPassword1"})
            service.command("confirmNetwork")
            print("  Enclosure joined the fake home network 'Ferndale'.")

        if not args.no_pair:
            _auto_pair(service, companion, args.portal_port)

        identity = service.identity
        portal_url = "http://127.0.0.1:{}".format(portal.server_port)
        companion_url = "http://127.0.0.1:{}".format(web.server_port)
        print()
        print("  Enclosure:  {} ({})".format(identity.display_name, identity.device_id))
        print("  Setup page: {}".format(portal_url))
        print("  Companion:  {}".format(companion_url))
        print("  Setup Wi-Fi password (normally on the owner card): {}".format(
            identity.setup_password))
        print()
        print("  Press Control-C to stop.")

        if not args.no_browser:
            threading.Timer(0.5, lambda: webbrowser.open(companion_url)).start()
            threading.Timer(1.2, lambda: webbrowser.open(portal_url)).start()

        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopping.")
        finally:
            web.server_close()
            portal.server_close()
            companion.close()
            service.stop()
    return 0


def _auto_pair(service: PiService, companion: CompanionService, portal_port: int) -> None:
    """Do what the user would do: pick the enclosure out of the list."""

    for _attempt in range(20):
        found = companion.search(timeout=1.0)
        if any(item["deviceId"] == service.identity.device_id for item in found):
            break
        time.sleep(0.2)
    else:
        print("  Could not find the enclosure to pair with.")
        return

    try:
        companion.pair(service.identity.device_id, portal_port=portal_port)
    except Exception as exc:
        print("  Pairing failed: {}".format(exc))
        return

    for _attempt in range(50):
        if companion.status()["link"]["connected"]:
            print("  Paired and connected.")
            return
        time.sleep(0.1)
    print("  Paired, but the link has not come up yet.")


if __name__ == "__main__":
    raise SystemExit(main())
