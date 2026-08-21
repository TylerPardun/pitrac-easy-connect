"""The Companion's local web server.

Bound to loopback only. Nothing on the residence network can reach it, which is
why it does not need its own authentication: reaching it already requires being
logged in to this computer.
"""

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict
from urllib.parse import urlparse

from ..common.errors import EasyConnectError
from .page import PAGE
from .service import CompanionService

GUARD_HEADER = "X-PiTrac-App"
#: Loopback only, by name or address. Anything else is somebody pointing
#: their own hostname at this machine.
_ALLOWED_HOST = re.compile(r"^(localhost|127(\.\d+){3}|\[::1\])(:\d+)?$")
MAX_BODY_BYTES = 64 * 1024
MAX_RESTORE_BYTES = 9 * 1024 * 1024


class CompanionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Not allow_reuse_address: on Windows that lets a second copy of the app
    # take the port from the copy already running, so opening it twice would
    # break the first one silently. See common.link.claim_port.
    allow_reuse_address = False

    def server_bind(self):
        from ..common.link import claim_port

        claim_port(self.socket)
        super().server_bind()

    def __init__(self, address, service: CompanionService):
        self.service = service
        #: Set when the user asks the program to stop from the page.
        self.stopped = __import__("threading").Event()
        super().__init__(address, CompanionHandler)

    def request_stop(self) -> None:
        self.stopped.set()
        self.shutdown()


class CompanionHandler(BaseHTTPRequestHandler):
    server: CompanionHTTPServer
    server_version = "PiTracEasyConnect"
    sys_version = ""

    def do_GET(self) -> None:
        if not self._host_allowed():
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._html(PAGE)
            return
        if path == "/api/status":
            self._guarded(self.server.service.status)
            return
        if path == "/api/raw-shots":
            self._guarded(self.server.service.raw_shots)
            return
        if path == "/api/range":
            self._guarded(self.server.service.range_status)
            return
        if path == "/api/backup":
            self._download_backup()
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": {"failed": "That page does not exist"}})

    def do_POST(self) -> None:
        if not self._host_allowed() or not self._request_allowed():
            return
        service = self.server.service
        path = urlparse(self.path).path
        routes: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "/api/search": lambda body: {"enclosures": service.search()},
            "/api/pair": lambda body: service.pair(str(body.get("deviceId", ""))),
            "/api/range-clear": lambda body: service.clear_range(),
            "/api/range-conditions": lambda body: service.set_range_conditions(body),
            "/api/range-demo": lambda body: service.range_demo_shot(),
            "/api/finish-setup": lambda body: service.finish_setup(
                bool(body.get("done", True))
            ),
            "/api/connect": lambda body: service.connect(str(body.get("deviceId", ""))),
            "/api/forget": lambda body: service.forget(str(body.get("deviceId", ""))),
            "/api/simulator": lambda body: service.select_simulator(str(body.get("simulator", ""))),
            "/api/check": lambda body: service.check_simulator(),
            "/api/test-shot": lambda body: service.send_test_shot(),
            "/api/backup/inspect": lambda body: service.command(
                "inspectBackup", {"file": body.get("file", "")}
            ),
            "/api/backup/restore": lambda body: service.command("restoreBackup", body),
            "/api/club": lambda body: service.set_club(str(body.get("club", ""))),
            "/api/shots/clear": lambda body: service.clear_shots(),
            "/api/cameras": lambda body: service.cameras(),
            "/api/update/check": lambda body: service.check_for_updates(),
            "/api/update/apply": lambda body: service.apply_update(),
            "/api/quit": lambda body: self._quit(),
            "/api/enclosure": lambda body: service.command(
                str(body.get("command", "")), body.get("arguments") or {}
            ),
        }
        handler = routes.get(path)
        if handler is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": {"failed": "That action does not exist"}})
            return
        try:
            body = self._read_json(
                MAX_RESTORE_BYTES if path.startswith("/api/backup/") else MAX_BODY_BYTES
            )
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": {"failed": str(exc)}})
            return
        self._guarded(lambda: handler(body))

    def _quit(self) -> Dict[str, Any]:
        """Stop Easy Connect, so nothing is left running after a session."""

        import threading

        threading.Timer(0.4, self.server.request_stop).start()
        return {"stopping": True}

    def _download_backup(self) -> None:
        """Ask the enclosure for a backup and hand it to the browser to save.

        Saving it on the PC is the point: a backup that lives only on the
        enclosure's memory card cannot help when the memory card is the problem.
        """

        from urllib.parse import parse_qs

        query = parse_qs(urlparse(self.path).query)
        try:
            made = self.server.service.command(
                "createBackup",
                {
                    "includeIdentity": query.get("identity", ["0"])[0] == "1",
                    "includePairings": query.get("pairings", ["0"])[0] == "1",
                },
            )
        except Exception as exc:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": getattr(exc, "as_dict", lambda: {"failed": str(exc)})()},
            )
            return

        body = (json.dumps(made["backup"], indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Disposition", 'attachment; filename="{}"'.format(made["filename"])
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    # --- Wire -------------------------------------------------------------

    def _host_allowed(self) -> bool:
        """Only answer to loopback names.

        A page on the wider internet can make the browser resolve a name it
        controls to 127.0.0.1 and then talk to whatever is listening. Checking
        the Host header is what stops that being this.
        """

        host = (self.headers.get("Host") or "").strip().lower()
        if not host or _ALLOWED_HOST.match(host):
            return True
        self._json(
            HTTPStatus.MISDIRECTED_REQUEST,
            {"error": {"failed": "Easy-Connect does not answer to that address"}},
        )
        return False

    def _request_allowed(self) -> bool:
        """Only act on requests that came from our own page.

        The app listens on loopback, which keeps the network out but not the
        browser: any website open at the same time can post to 127.0.0.1. A
        custom header cannot be set on a cross-origin request without a
        preflight the browser will refuse, so requiring one is what makes a
        state-changing route unreachable from somebody else's page.
        """

        if self.headers.get(GUARD_HEADER) is None:
            self._json(
                HTTPStatus.FORBIDDEN,
                {"error": {"failed": "This request did not come from Easy-Connect"}},
            )
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = (self.headers.get("Host") or "").strip().lower()
            if urlparse(origin).netloc.lower() != host:
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {"error": {"failed": "This request came from another website"}},
                )
                return False
        return True

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
                        "failed": "Easy-Connect could not complete that: {}".format(exc),
                        "stillSafe": "Nothing was changed on PiTrac.",
                        "nextStep": "Try again. If it keeps failing, restart Easy-Connect.",
                    }
                },
            )
        else:
            self._json(HTTPStatus.OK, result if isinstance(result, dict) else {"result": result})


    #: How much of an oversized body to read and throw away so the caller can
    #: receive the refusal. Past this, closing on them is the right answer.
    DRAIN_LIMIT = 4 * 1024 * 1024

    def _drain(self, length: int, limit: int) -> None:
        remaining = min(length, self.DRAIN_LIMIT)
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                return
            remaining -= len(chunk)

    def _read_json(self, limit: int = MAX_BODY_BYTES) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("The request length was not valid") from exc
        if length > limit:
            # Refusing without reading leaves the caller still writing when the
            # socket closes, so it sees a dropped connection instead of the
            # reason. Drain a bounded amount first -- bounded, because draining
            # whatever arrives is how a refusal becomes a way to tie the server
            # up. Beyond that the connection does close, which is correct.
            self._drain(length, limit)
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
