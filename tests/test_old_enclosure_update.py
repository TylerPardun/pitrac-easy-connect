"""An enclosure too old to talk to can still be told to update itself.

Enclosures before 0.9 speak link protocol 1, which this app will not play
through. Their only way to a newer release is the update command over that
link, so the app keeps exactly that one conversation: prove the pairing, ask
for this app's own version, and say nothing else.

The whole path was also run against the real 0.4.6 enclosure code from history,
updating itself from a stand-in release service and coming back as the new
version with its pairings; this keeps the app's half of it from regressing.
"""

import socket
import threading

from pitrac_easy_connect.common import link
from pitrac_easy_connect.companion.link_client import (
    LEGACY_PROTOCOL,
    CompanionLinkClient,
    LegacyUpdateLink,
)
from pitrac_easy_connect.pi.pairing import PairingManager

SECRET = "s3cret-for-the-test"
PAIRING = "pairing-1"
DEVICE = {"deviceId": "OLDPI123", "displayName": "PiTrac OLD1"}


class OldEnclosure:
    """Speaks protocol 1 the way 0.4.x did, and records what it is asked."""

    def __init__(self, restart_on_apply=True, available=True):
        self.restart_on_apply = restart_on_apply
        self.available = available
        self.commands = []
        self.auth = None
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(4)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while True:
            try:
                sock, _ = self._server.accept()
            except OSError:
                return
            stream = link.FrameStream(sock)
            try:
                self._one(stream)
            except (link.LinkClosed, link.LinkError, OSError, TimeoutError):
                pass
            finally:
                stream.close()

    def _one(self, stream):
        challenge = "challenge-1"
        stream.send({"type": "hello", "protocol": 1, "version": "0.4.6",
                     "challenge": challenge, "device": DEVICE})
        self.auth = stream.receive(timeout=5)
        if self.auth.get("protocol") != 1:
            stream.send(link.error("PT-LINK-003", "mismatch", "update"))
            return
        if self.auth.get("proof") != PairingManager.client_proof(SECRET, challenge):
            stream.send(link.error("PT-PAIR-004", "unknown", "pair"))
            return
        stream.send(link.auth_ok(PairingManager.expected_server_proof(SECRET, challenge)))
        # An old enclosure volunteers its status; the update link ignores it.
        stream.send({"type": "enclosureStatus", "status": {"version": "0.4.6"}})
        while True:
            frame = stream.receive(timeout=5)
            if frame.get("type") != "command":
                continue
            self.commands.append((frame["command"], frame.get("arguments")))
            if frame["command"] == "checkForUpdates":
                stream.send(link.command_result(frame["id"], True, {
                    "available": self.available, "canApply": self.available,
                    "latest": frame["arguments"]["targetTag"],
                    "detail": "ready" if self.available else "no matching archive",
                }))
            elif frame["command"] == "applyUpdate":
                if self.restart_on_apply:
                    return  # restarting ends the connection before any answer
                stream.send(link.command_result(frame["id"], True, {"applied": True}))

    def close(self):
        self._server.close()


def updater(enclosure):
    return LegacyUpdateLink("127.0.0.1", enclosure.port, PAIRING, SECRET, "0.10.3",
                            "Den PC", expected_device_id=DEVICE["deviceId"])


def test_it_asks_an_old_enclosure_for_exactly_this_version_and_nothing_else():
    enclosure = OldEnclosure()
    try:
        result = updater(enclosure).update_to("v0.10.3", timeout=5)
    finally:
        enclosure.close()
    assert result["started"] is True
    assert enclosure.auth["protocol"] == LEGACY_PROTOCOL
    assert enclosure.commands == [
        ("checkForUpdates", {"targetTag": "v0.10.3"}),
        ("applyUpdate", {"targetTag": "v0.10.3"}),
    ]


def test_nothing_is_installed_when_the_enclosure_cannot_find_that_release():
    enclosure = OldEnclosure(available=False)
    try:
        result = updater(enclosure).update_to("v0.10.3", timeout=5)
    finally:
        enclosure.close()
    assert result["started"] is False
    assert "no matching archive" in result["detail"]
    assert [name for name, _ in enclosure.commands] == ["checkForUpdates"]


def test_the_ordinary_link_names_the_old_version_instead_of_only_refusing():
    enclosure = OldEnclosure()
    client = CompanionLinkClient(
        "127.0.0.1", enclosure.port, PAIRING, SECRET, "0.10.3", "Den PC",
        on_shot=lambda *a: {}, reconnect_seconds=0.1,
    )
    try:
        client.start()
        import time
        deadline = time.monotonic() + 5
        while client.outdated_enclosure is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert client.outdated_enclosure["version"] == "0.4.6"
        assert client.status()["lastError"]["code"] == "PT-LINK-003"
        # It never authenticated as protocol 2 and never played through it.
        assert client.connected is False
    finally:
        client.stop()
        enclosure.close()
