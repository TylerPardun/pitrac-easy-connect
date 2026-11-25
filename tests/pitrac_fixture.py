"""A PiTrac to test against, without a Raspberry Pi or PiTrac itself.

``test_pitrac_contract.py`` is what keeps the stand-in honest: it runs the same
code against PiTrac's real web server.
"""

from pitrac_easy_connect.pi.pitrac import PitracInstallation
from pitrac_easy_connect.pi.simulated import SimulatedPitracApi


def make_pitrac(tmp_path, calibrated=False, images_dir=None, relay_ports=None):
    """An installation that forgets what it saw at once, so tests never wait."""

    pitrac = PitracInstallation(
        SimulatedPitracApi(calibrated=calibrated),
        config_dir=tmp_path / ".pitrac" / "config",
        images_dir=images_dir or tmp_path / "Images",
    )
    fresh = pitrac.snapshot
    pitrac.snapshot = lambda max_age=0.0: fresh(max_age)
    if relay_ports:
        pitrac.ensure_relay_target(relay_ports)
    return pitrac
