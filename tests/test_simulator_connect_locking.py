"""Connecting to a simulator never stalls the window.

The connect used to happen while holding the lock every status read takes, so
a refused connection -- about two seconds on Windows -- froze the window for
as long. It now happens outside that lock, and a session closed while a
connect was under way stays closed.
"""

import socket
import threading
import time

import pytest

from pitrac_easy_connect.companion import simulator_session as module
from pitrac_easy_connect.companion.simulator_session import SimulatorSession
from pitrac_easy_connect.models import Simulator


def test_status_is_read_at_once_while_a_connect_is_slow(monkeypatch):
    started = threading.Event()

    def slow_refusal(address, timeout=None):
        started.set()
        time.sleep(1.5)
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(module.socket, "create_connection", slow_refusal)
    session = SimulatorSession(Simulator.GSPRO, port=9)
    worker = threading.Thread(target=session.ensure_connected, daemon=True)
    worker.start()
    assert started.wait(2)
    began = time.monotonic()
    assert session.connected is False
    assert time.monotonic() - began < 0.2, "a status read waited on the connect"
    worker.join(3)
    assert session.last_error


def test_a_session_closed_during_a_connect_stays_closed(monkeypatch):
    started, release = threading.Event(), threading.Event()
    ours, theirs = socket.socketpair()

    def held_connect(address, timeout=None):
        started.set()
        release.wait(3)
        return ours

    monkeypatch.setattr(module.socket, "create_connection", held_connect)
    session = SimulatorSession(Simulator.GSPRO, port=9)
    outcome = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault("connected", session.ensure_connected()), daemon=True)
    worker.start()
    assert started.wait(2)
    session.close()
    release.set()
    worker.join(3)
    assert outcome["connected"] is False
    assert session.connected is False
    theirs.close()
