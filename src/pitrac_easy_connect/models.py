from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict


class Simulator(str, Enum):
    GSPRO = "gspro"
    E6 = "e6"

    @property
    def label(self) -> str:
        return "GSPro" if self is Simulator.GSPRO else "E6 Connect"

    @property
    def default_port(self) -> int:
        return 921 if self is Simulator.GSPRO else 2483


@dataclass(frozen=True)
class ShotData:
    speed_mph: float = 102.5
    vertical_launch_deg: float = 14.2
    horizontal_launch_deg: float = 1.3
    back_spin_rpm: int = 2850
    side_spin_rpm: int = -180

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not 0 < self.speed_mph < 250:
            raise ValueError("Ball speed must be between 0 and 250 mph")
        if not -20 <= self.vertical_launch_deg <= 90:
            raise ValueError("Vertical launch angle is outside the supported range")
        if not -90 <= self.horizontal_launch_deg <= 90:
            raise ValueError("Horizontal launch angle is outside the supported range")
        if not -20000 <= self.back_spin_rpm <= 20000:
            raise ValueError("Back spin is outside the supported range")
        if not -10000 <= self.side_spin_rpm <= 10000:
            raise ValueError("Side spin is outside the supported range")


TEST_SHOT = ShotData()

