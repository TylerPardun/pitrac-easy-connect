"""Desktop discovery reports the network truth, including partial failures."""

import json
import socket
import types

from pitrac_easy_connect.common import discovery


class FakeSocket:
    def __init__(self, failed=(), replies=(), receive_error=None):
        self.failed = set(failed)
        self.replies = list(replies)
        self.receive_error = receive_error
        self.sent = []

    def setsockopt(self, *_args):
        pass

    def settimeout(self, *_args):
        pass

    def bind(self, *_args):
        pass

    def sendto(self, payload, target):
        self.sent.append(target[0])
        if target[0] in self.failed:
            raise PermissionError(13, "permission denied")

    def recvfrom(self, _size):
        if self.replies:
            return self.replies.pop(0)
        if self.receive_error:
            error, self.receive_error = self.receive_error, None
            raise error
        raise socket.timeout()

    def close(self):
        pass


def run_with(monkeypatch, fake, targets):
    monkeypatch.setattr(discovery.socket, "socket", lambda *_args: fake)
    return discovery.discover(timeout=0.001, port=1, broadcast_to=targets)


def reply(device="AAAA1111"):
    payload = json.dumps({
        "deviceId": device,
        "displayName": "Garage",
        "linkPort": 39877,
        "hostname": "pitrac-" + device.lower(),
    }).encode()
    return payload, ("10.0.0.42", 39876)


def test_all_network_sends_failing_is_not_hidden_by_loopback(monkeypatch):
    fake = FakeSocket(failed={"255.255.255.255", "10.0.0.255"})
    result = run_with(
        monkeypatch, fake, ["255.255.255.255", "10.0.0.255", "127.0.0.1"]
    )
    assert result.problem is not None
    assert result.problem.kind == "permission"


def test_partial_send_failures_still_allow_a_normal_search(monkeypatch):
    fake = FakeSocket(failed={"255.255.255.255"})
    result = run_with(monkeypatch, fake, ["255.255.255.255", "10.0.0.255"])
    assert result.problem is None


def test_receive_failure_is_reported(monkeypatch):
    fake = FakeSocket(receive_error=OSError(5, "receive failed"))
    result = run_with(monkeypatch, fake, ["10.0.0.255"])
    assert result.problem is not None
    assert result.problem.kind == "receive"


def test_no_replies_after_successful_send_is_not_a_network_failure(monkeypatch):
    result = run_with(monkeypatch, FakeSocket(), ["10.0.0.255"])
    assert result.enclosures == []
    assert result.problem is None


def test_successful_replies_are_deduplicated(monkeypatch):
    fake = FakeSocket(replies=[reply(), reply()])
    result = run_with(monkeypatch, fake, ["10.0.0.255"])
    assert [item.device_id for item in result.enclosures] == ["AAAA1111"]
    assert result.problem is None


def test_every_active_ipv4_directed_broadcast_is_used(monkeypatch):
    address = lambda ip, mask, broadcast: types.SimpleNamespace(
        family=socket.AF_INET, address=ip, netmask=mask, broadcast=broadcast
    )
    fake_psutil = types.SimpleNamespace(
        net_if_addrs=lambda: {
            "wifi": [address("10.0.0.4", "255.255.255.0", "10.0.0.255")],
            "utm": [address("192.168.64.2", "255.255.255.0", None)],
            "vpn": [address("100.64.0.2", "255.255.255.255", None)],
            "down": [address("172.16.0.2", "255.255.0.0", "172.16.255.255")],
            "loopback": [address("127.0.0.1", "255.0.0.0", None)],
        },
        net_if_stats=lambda: {
            "wifi": types.SimpleNamespace(isup=True),
            "utm": types.SimpleNamespace(isup=True),
            "vpn": types.SimpleNamespace(isup=True),
            "down": types.SimpleNamespace(isup=False),
            "loopback": types.SimpleNamespace(isup=True),
        },
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)
    assert discovery._network_broadcasts() == [
        "255.255.255.255", "10.0.0.255", "192.168.64.255"
    ]
