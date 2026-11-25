"""Talking to the PiTrac that is actually running.

PiTrac keeps its simulators, settings, and calibration in a SQLite database that
its web server owns. Files under ``~/.pitrac/config`` are only a one-time import
source: writing to them does not change a running PiTrac, and reading them does
not say what it is doing. So everything here goes through the web server.

It is a loopback connection to a program somebody else maintains and updates.
Each answer is checked for the shape this code relies on, and a PiTrac that
answers differently is reported as unsupported rather than guessed at.
"""

import http.client
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ..common import jsontext

DEFAULT_URL = "http://127.0.0.1:8080"

#: The PiTrac revision this release was built and tested against. Not enforced:
#: what matters is whether the calls below are answered as expected, which is
#: checked at run time. PiTrac publishes no releases, so a commit is the only
#: way to name a version of it.
TESTED_COMMIT = "78f1de60fd21398f34d348f19f55e73029bc95f9"

#: Loopback, so a healthy answer takes milliseconds. Short because the setup
#: page waits behind this.
TIMEOUT_SECONDS = 3.0

#: A restore writes to the memory card, which can stall for a few seconds.
SAVE_TIMEOUT_SECONDS = 15.0

#: Far more than any of these answers needs; a cap so a fault cannot eat memory.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class PitracApiError(Exception):
    """Something went wrong talking to PiTrac."""


class PitracUnreachable(PitracApiError):
    """The web server is not answering. It may simply still be starting."""


class PitracUnsupported(PitracApiError):
    """It answered, but not the way this release knows how to use."""


class PitracRefused(PitracApiError):
    """It understood the request and turned it down."""


class PitracApi:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = TIMEOUT_SECONDS):
        self.url = url.rstrip("/")
        self.timeout = timeout
        # Never through a proxy: this is this machine talking to itself.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # --- Simulators -------------------------------------------------------

    def sims(self) -> List[Dict[str, Any]]:
        found = self._call("GET", "/api/sims")
        if not isinstance(found, list) or not all(_is_sim(sim) for sim in found):
            raise PitracUnsupported("PiTrac described its simulators in a form this release cannot read")
        return found

    def create_sim(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._sim(self._call("POST", "/api/sims", body))

    def update_sim(self, sim_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self._sim(self._call("PUT", "/api/sims/" + quote(str(sim_id), safe=""), body))

    @staticmethod
    def _sim(answer: Any) -> Dict[str, Any]:
        if not _is_sim(answer):
            raise PitracUnsupported("PiTrac did not confirm the simulator it was asked to save")
        return answer

    # --- Readiness --------------------------------------------------------

    def setup_status(self) -> Dict[str, Any]:
        """Which calibrations PiTrac itself says are done."""

        answer = self._call("GET", "/api/setup/status")
        cameras = answer.get("cameras") if isinstance(answer, dict) else None
        strobe = answer.get("strobe") if isinstance(answer, dict) else None
        readable = (
            isinstance(cameras, dict)
            and isinstance(strobe, dict)
            and isinstance(strobe.get("safe"), bool)
            and all(
                isinstance(cameras.get(name), dict)
                and isinstance(cameras[name].get("lens_calibrated"), bool)
                and isinstance(cameras[name].get("position_calibrated"), bool)
                for name in ("camera1", "camera2")
            )
        )
        if not readable:
            raise PitracUnsupported("PiTrac reported its calibration in a form this release cannot read")
        return answer

    # --- Settings and calibration ----------------------------------------

    def export_config(self) -> Dict[str, Any]:
        answer = self._call("GET", "/api/config/export")
        if not isinstance(answer, dict) or not all(
            isinstance(answer.get(key), dict) for key in ("user_settings", "calibration_data")
        ):
            raise PitracUnsupported("PiTrac exported its settings in a form this release cannot read")
        return answer

    def import_config(self, document: Dict[str, Any]) -> Dict[str, str]:
        """Replace the sections named in ``document``. Returns what it would not take.

        PiTrac replaces each section whole and leaves out any value it considers
        invalid, so the answer is which keys were dropped and why.
        """

        answer = self._call("POST", "/api/config/import", document, timeout=SAVE_TIMEOUT_SECONDS)
        if not isinstance(answer, dict) or answer.get("success") is not True:
            raise PitracUnsupported("PiTrac did not confirm the settings it was asked to save")
        skipped = answer.get("skipped")
        return dict(skipped) if isinstance(skipped, dict) else {}

    # --- The request itself -----------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            with exc:
                detail = _reason(exc)
            # 404 on a whole route, or 405 on a method, is an older or newer
            # PiTrac. A 404 for one simulator carries an explanation instead.
            if exc.code in (404, 405) and not detail:
                raise PitracUnsupported("PiTrac does not offer {}".format(path)) from exc
            raise PitracRefused(detail or "PiTrac answered {}".format(exc.code)) from exc
        except (OSError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise PitracUnreachable("PiTrac's web server is not answering: {}".format(reason)) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PitracUnsupported("PiTrac's answer was far larger than expected")
        try:
            return jsontext.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise PitracUnsupported("PiTrac answered with something that is not JSON") from exc


def _is_sim(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and isinstance(value.get("type"), str)
        and isinstance(value.get("on"), bool)
        and isinstance(value.get("settings"), dict)
    )


def _reason(error: urllib.error.HTTPError) -> str:
    """What PiTrac said was wrong, if it said anything of its own."""

    try:
        answer = jsontext.loads(error.read(64 * 1024).decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return ""
    if not isinstance(answer, dict):
        return ""
    for key in ("error", "message"):
        if answer.get(key):
            return str(answer[key])
    # FastAPI's own {"detail": "Not Found"} means the route does not exist.
    return ""
