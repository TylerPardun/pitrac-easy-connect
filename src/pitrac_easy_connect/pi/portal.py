"""The web server behind the enclosure's setup page.

This is the one part of Easy Connect that listens on the network before any
pairing exists, so it is also the part with the least to offer an attacker. It
can set the country, list and join networks, show a pairing code, and perform
the maintenance actions a stranded owner needs. It cannot read a Wi-Fi password
back out, cannot run a command, and cannot forward a shot.

Three protections apply to every state-changing request:

**A custom header is required.** A browser will not attach ``X-PiTrac-Portal``
to a cross-origin request without a preflight, and the preflight is refused, so
a malicious page the user happens to have open cannot post to the enclosure.

**The Origin must match.** Any request that carries an ``Origin`` from somewhere
else is rejected outright.

**The Host must be one we recognise.** This blocks DNS rebinding, where a name
under an attacker's control is made to resolve to the enclosure's address.
"""

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict
from urllib.parse import urlparse

from ..common.errors import EasyConnectError
from .downloads import CompanionDownloads
from .portal_page import PAGE, downloads_page

PORTAL_PORT = 80
MAX_BODY_BYTES = 64 * 1024
#: A restore carries a whole backup file in its body, so it gets its own limit.
MAX_RESTORE_BYTES = 9 * 1024 * 1024
GUARD_HEADER = "X-PiTrac-Portal"

#: Host values the portal answers to. Anything else is refused so a name an
#: attacker controls cannot be pointed at the enclosure and then scripted.
_ALLOWED_HOST = re.compile(
    r"^(?:"
    r"\d{1,3}(?:\.\d{1,3}){3}"          # any bare IPv4 literal, including 10.42.0.1
    r"|\[?[0-9a-fA-F:]+\]?"             # IPv6 literal
    r"|localhost"
    r"|[a-z0-9-]+\.local"               # pitrac-<id>.local
    r"|pitrac(?:\.setup)?"
    r")(?::\d+)?$"
)


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True
    # Not allow_reuse_address: on Windows that lets a second copy take the port
    # from the one already serving. See common.link.claim_port.
    allow_reuse_address = False

    def server_bind(self):
        from ..common.link import claim_port

        claim_port(self.socket)
        super().server_bind()

    def __init__(self, address, service, extra_hosts=(), downloads_dir=None):
        self.service = service
        self.extra_hosts = {host.lower() for host in extra_hosts}
        self.downloads = CompanionDownloads(
            downloads_dir if downloads_dir is not None else service.paths.downloads
        )
        super().__init__(address, PortalHandler)


class PortalHandler(BaseHTTPRequestHandler):
    server: PortalServer
    server_version = "PiTracEasyConnect"
    sys_version = ""

    # --- Routing ----------------------------------------------------------

    def do_GET(self) -> None:
        if not self._host_allowed():
            return
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/setup"):
            self._send_html(PAGE)
            return
        if path in ("/companion", "/companion/"):
            self._send_html(downloads_page(
                [item.as_dict() for item in self.server.downloads.available()],
                self.server.service.identity.display_name,
                self.server.service.version,
            ))
            return
        if path.startswith("/companion/"):
            self._send_download(path[len("/companion/"):])
            return
        if path == "/api/status":
            self._json(HTTPStatus.OK, self.server.service.status())
            return
        if path == "/api/downloads":
            self._json(
                HTTPStatus.OK,
                {"downloads": [item.as_dict() for item in self.server.downloads.available()]},
            )
            return
        if path == "/api/networks":
            self._guarded(lambda: {"networks": [n.as_dict() for n in self._service().provisioner.scan()]})
            return
        if path == "/api/pair-hello":
            self._guarded(self._pair_hello)
            return
        if path == "/api/backup":
            self._download_backup()
            return
        if path == "/api/owner-card":
            self._guarded(lambda: {"text": self._service().identity.owner_card()})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": {"failed": "That page does not exist"}})

    def do_POST(self) -> None:
        if not self._host_allowed() or not self._request_allowed():
            return
        path = urlparse(self.path).path
        routes: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "/api/country": lambda body: self._service().command(
                "setCountry", {"country": body.get("country", "")}
            ),
            "/api/join": lambda body: self._service().command(
                "joinNetwork",
                {
                    "ssid": body.get("ssid", ""),
                    "password": body.get("password") or None,
                    "hidden": bool(body.get("hidden")),
                },
            ),
            "/api/direct-mode": lambda body: self._service().command(
                "setDirectMode", {"enabled": bool(body.get("enabled"))}
            ),
            "/api/pair-remove": lambda body: self._remove_computer(str(body.get("pairingId", ""))),
            "/api/model-licence": lambda body: self._service().command("modelLicence", {}),
            "/api/install-models": lambda body: self._service().command(
                "installModels", {"accepted": bool(body.get("accepted"))}
            ),
            "/api/pair-open": lambda body: self._open_pairing(),
            "/api/pair-close": lambda body: self._close_pairing(),
            "/api/pair": lambda body: self._service().pairings.complete_exchange(
                str(body.get("sessionId", "")),
                str(body.get("clientPublic", "")),
                str(body.get("computerName", "")),
            ),
            "/api/backup/inspect": lambda body: self._service().command(
                "inspectBackup", {"file": body.get("file", "")}
            ),
            "/api/backup/restore": lambda body: self._service().command("restoreBackup", body),
            "/api/restart-pitrac": lambda body: self._service().command("restartPitrac"),
            "/api/new-owner": lambda body: self._service().command("prepareForNewOwner", {}),
            "/api/reset-network": lambda body: self._service().command("resetNetwork"),
            "/api/shutdown": lambda body: self._service().command("shutdown"),
            "/api/reboot": lambda body: self._service().command("reboot"),
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

    def do_OPTIONS(self) -> None:
        # Refusing the preflight is what stops a cross-origin page from being
        # able to send the guarded header at all.
        self.send_response(HTTPStatus.FORBIDDEN)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- Guards -----------------------------------------------------------

    def _service(self):
        return self.server.service

    def _host_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        if not host or _ALLOWED_HOST.match(host) or host in self.server.extra_hosts:
            return True
        self._json(
            HTTPStatus.MISDIRECTED_REQUEST,
            {"error": {"failed": "PiTrac does not answer to that address"}},
        )
        return False

    def _request_allowed(self) -> bool:
        if self.headers.get(GUARD_HEADER) is None:
            self._json(
                HTTPStatus.FORBIDDEN,
                {"error": {"failed": "This request did not come from the PiTrac setup page"}},
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
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": {"failed": str(exc)}})
        except Exception as exc:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "error": {
                        "failed": "PiTrac could not complete that: {}".format(exc),
                        "stillSafe": "Nothing was changed.",
                        "nextStep": "Try again. If it keeps failing, restart PiTrac.",
                    }
                },
            )
        else:
            self._json(HTTPStatus.OK, result if isinstance(result, dict) else {"result": result})

    def _send_download(self, name: str) -> None:
        """Serve one Companion build. The name is validated before it is used."""

        from urllib.parse import unquote

        resolved = self.server.downloads.resolve(unquote(name))
        if resolved is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": {"failed": "That download does not exist"}})
            return
        try:
            payload = resolved.read_bytes()
        except OSError:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": {"failed": "That download could not be read"}},
            )
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Content-Disposition", 'attachment; filename="{}"'.format(resolved.name)
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _download_backup(self) -> None:
        """Hand the browser a backup file to save."""

        from urllib.parse import parse_qs

        query = parse_qs(urlparse(self.path).query)
        try:
            made = self._service().command(
                "createBackup",
                {
                    "includeIdentity": query.get("identity", ["0"])[0] == "1",
                    "includePairings": query.get("pairings", ["0"])[0] == "1",
                },
            )
        except EasyConnectError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": exc.as_dict()})
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

    def _pair_hello(self) -> Dict[str, Any]:
        service = self._service()
        started = service.pairings.begin_exchange()
        started.update(
            {
                "deviceId": service.identity.device_id,
                "displayName": service.identity.display_name,
                "linkPort": service.link_server.port,
                "version": service.version,
            }
        )
        return started

    def _remove_computer(self, pairing_id: str) -> Dict[str, Any]:
        """Take away one computer's access, from the enclosure's own page.

        A computer that was unpaired while the enclosure was off, or one that
        no longer exists, leaves an entry only this can clear.
        """

        service = self._service()
        service.command("revokeComputer", {"pairingId": pairing_id})
        return {"computers": service.pairings.trusted_computers()}

    def _open_pairing(self) -> Dict[str, Any]:
        """Let one more computer connect, for a few minutes."""

        pairings = self._service().pairings
        pairings.open_window()
        return pairings.status()

    def _close_pairing(self) -> Dict[str, Any]:
        pairings = self._service().pairings
        pairings.close_window()
        return pairings.status()

    # --- Wire -------------------------------------------------------------


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
        self.send_header("Referrer-Policy", "no-referrer")
        # The app shows this page inside its own window, so framing has to be
        # allowed from loopback — and only from loopback. A website cannot be
        # served from 127.0.0.1 on the visitor's machine, so this still stops
        # the clickjacking that X-Frame-Options: DENY was there to stop.
        # X-Frame-Options is deliberately absent: browsers ignore it when
        # frame-ancestors is present, and leaving both in place invited the
        # bug where the app's Setup tab silently showed nothing.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "connect-src 'self'; form-action 'none'; "
            "frame-ancestors 'self' http://127.0.0.1:* http://localhost:*",
        )
        self.end_headers()

    def _send_html(self, markup: str) -> None:
        body = markup.encode("utf-8")
        self._headers("text/html; charset=utf-8", len(body), HTTPStatus.OK)
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, value: Dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")
        self._headers("application/json; charset=utf-8", len(body), status)
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Request lines can contain a network name. Nothing here goes to a log.
        return
