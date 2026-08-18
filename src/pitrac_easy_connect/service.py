import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .models import Simulator, TEST_SHOT
from .protocols import SimulatorResult, check_socket, send_test_shot


def default_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "pitrac-easy-connect" / "config.json"


class CompanionService:
    def __init__(
        self,
        config_path: Optional[Path] = None,
        simulator_ports: Optional[Dict[Simulator, int]] = None,
    ):
        self.config_path = config_path or default_config_path()
        self.simulator_ports = simulator_ports or {
            Simulator.GSPRO: Simulator.GSPRO.default_port,
            Simulator.E6: Simulator.E6.default_port,
        }
        self._lock = threading.Lock()
        self._simulator = Simulator.GSPRO
        self._last_result: Optional[SimulatorResult] = None
        self._test_shot_accepted = False
        self._load()

    @property
    def simulator(self) -> Simulator:
        with self._lock:
            return self._simulator

    def select(self, simulator_name: str) -> Dict[str, Any]:
        try:
            simulator = Simulator(simulator_name)
        except ValueError as exc:
            raise ValueError("Only GSPro and E6 Connect are supported") from exc
        with self._lock:
            self._simulator = simulator
            self._last_result = None
            self._test_shot_accepted = False
            self._save_locked()
        return self.status()

    def check(self) -> Dict[str, Any]:
        simulator = self.simulator
        result = check_socket("127.0.0.1", self.simulator_ports[simulator])
        with self._lock:
            self._last_result = result
            self._test_shot_accepted = False
        return self.status()

    def test_shot(self) -> Dict[str, Any]:
        simulator = self.simulator
        result = send_test_shot(
            simulator,
            ("127.0.0.1", self.simulator_ports[simulator]),
            TEST_SHOT,
        )
        with self._lock:
            self._last_result = result
            self._test_shot_accepted = result.accepted
        return self.status()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            simulator = self._simulator
            result = self._last_result
            test_shot_accepted = self._test_shot_accepted
        return {
            "version": "0.1.0",
            "simulator": simulator.value,
            "simulatorLabel": simulator.label,
            "endpoint": "127.0.0.1:{}".format(self.simulator_ports[simulator]),
            "connected": bool(result and result.accepted),
            "message": result.message if result else "Not checked yet",
            "testShotAccepted": test_shot_accepted,
            "ready": test_shot_accepted,
            "response": result.response if result else None,
            "pi": {
                "connected": False,
                "message": "Pi pairing will be added after the desktop workflow is validated",
            },
        }

    def _load(self) -> None:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._simulator = Simulator(data.get("simulator", Simulator.GSPRO.value))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            self._simulator = Simulator.GSPRO

    def _save_locked(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"simulator": self._simulator.value}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.config_path)
