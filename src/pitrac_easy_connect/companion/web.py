"""The Companion's local web server.

Bound to loopback only. Nothing on the residence network can reach it, which is
why it does not need its own authentication: reaching it already requires being
logged in to this computer.
"""

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict
from urllib.parse import urlparse

from ..common.errors import EasyConnectError
from .page import PAGE
from .service import CompanionService

MAX_BODY_BYTES = 64 * 1024


class CompanionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service: CompanionService):
        self.service = service
        super().__init__(address, CompanionHandler)


class CompanionHandler(BaseHTTPRequestHandler):
    server: CompanionHTTPServer
    server_version = "PiTracEasyConnect"
    sys_version = ""

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._html(PAGE)
            return
        if path == "/api/status":
            self._guarded(self.server.service.status)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": {"failed": "That page does not exist"}})

    def do_POST(self) -> None:
        service = self.server.service
        path = urlparse(self.path).path
        routes: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "/api/search": lambda body: {"enclosures": service.search()},
            "/api/pair": lambda body: service.pair(
                str(body.get("deviceId", "")), str(body.get("code", ""))
            ),
            "/api/connect": lambda body: service.connect(str(body.get("deviceId", ""))),
            "/api/forget": lambda body: service.forget(str(body.get("deviceId", ""))),
            "/api/simulator": lambda body: service.select_simulator(str(body.get("simulator", ""))),
            "/api/check": lambda body: service.check_simulator(),
            "/api/test-shot": lambda body: service.send_test_shot(),
            "/api/enclosure": lambda body: service.command(
                str(body.get("command", "")), body.get("arguments") or {}
            ),
        }
        handler = routes.get(path)
        if handler is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": {"failed": "That action does not exist"}})
            return
        try:
            body = self._read_json()
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": {"failed": str(exc)}})
            return
        self._guarded(lambda: handler(body))

    # --- Wire -------------------------------------------------------------

    def _guarded(self, work: Callable[[], Any]) -> None:
        try:
            result = work()
        except EasyConnectError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": exc.as_dict()})
        except (ValueError, TimeoutError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": {"failed": str(exc)}})
        except Exception as exc:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "failed": "Easy Connect could not complete that: {}".format(exc),
                        "stillSafe": "Nothing was changed on PiTrac.",
                        "nextStep": "Try again. If it keeps failing, restart Easy Connect.",
                    }
                },
            )
        else:
            self._json(HTTPStatus.OK, result if isinstance(result, dict) else {"result": result})

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("The request length was not valid") from exc
        if length > MAX_BODY_BYTES:
            raise ValueError("The request was too large")
        if length <= 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("The request was not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("The request must be a JSON object")
        return value

    def _headers(self, content_type: str, length: int, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def _html(self, markup: str) -> None:
        body = markup.encode("utf-8")
        self._headers("text/html; charset=utf-8", len(body), HTTPStatus.OK)
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, value: Dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")
        self._headers("application/json; charset=utf-8", len(body), status)
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return
