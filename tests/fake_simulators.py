"""Simulators that behave the way the real ones do where it matters."""

import json
import socket
import threading
import time


class _Server:
    def __init__(self):
        self.received = []
        self.read_delay = 0.0
        self.clients = []
        self._server = socket.socket()
        self._server.bind(("127.0.0.1", 0))
        self._server.listen()
        self.port = self._server.getsockname()[1]
        self._open = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self._open:
            try:
                client, _address = self._server.accept()
            except OSError:
                return
            self.clients.append(client)
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client):
        while True:
            # A busy program gets round to reading when it can, and by then
            # more may have arrived.
            time.sleep(self.read_delay)
            try:
                data = client.recv(65536)
            except OSError:
                return
            if not data:
                return
            self.heard(client, data)

    def say(self, message, client=None):
        for each in [client] if client else list(self.clients):
            try:
                each.sendall((json.dumps(message) + "\n").encode())
            except OSError:
                pass

    def close(self):
        self._open = False
        for each in [*self.clients, self._server]:
            try:
                each.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            each.close()


class FakeOpenGolfSim(_Server):
    """One read is one message: two that arrive together are both lost. Every
    message is answered, and a shot is played only with somewhere to hit from."""

    def __init__(self):
        super().__init__()
        self.on_a_hole = True
        self.refuse = False
        self.silent = False
        self.lost = 0
        self.flight = 0.2

    @property
    def shots(self):
        return [m["shot"] for m in self.received if m.get("type") == "shot"]

    @property
    def statuses(self):
        return [m["status"] for m in self.received if m.get("type") == "device"]

    def heard(self, client, data):
        try:
            message = json.loads(data.decode())
        except ValueError as exc:
            self.lost += 1
            self.say({"status": 400, "error": str(exc)}, client)
            return
        self.received.append(message)
        if self.silent:
            return
        if message.get("type") == "shot" and self.refuse:
            self.say({"status": 400, "error": "shot out of range"}, client)
            return
        self.say({"status": 200}, client)
        if message.get("type") == "shot" and self.on_a_hole:
            threading.Timer(self.flight, self.finish, args=(message["shot"],)).start()

    def finish(self, shot, carry=150.0):
        self.say({"type": "result", "data": {
            "result": {"carry": carry, "height": 25.0, "roll": 4.0, "total": carry + 4, "lateral": -2.0},
            "club": {"name": "7I", "id": "7I", "distance": 140}, "shot": shot, "sessionId": 1}})

    def choose(self, club):
        self.say({"type": "player", "data": {
            "playerId": "p", "currentPosition": {"x": 0, "y": 0, "z": 0},
            "club": {"name": club, "id": club, "distance": 140}}})


class FakeGSPro(_Server):
    """Answers shots, and talks about the player whenever it feels like it."""

    def __init__(self, answer=None):
        super().__init__()
        self.answer = answer if answer is not None else {"Code": 200, "Message": "Shot received"}
        self.chatter = False
        self._buffer = ""

    def heard(self, client, data):
        decoder = json.JSONDecoder()
        self._buffer += data.decode()
        while self._buffer.strip():
            try:
                message, end = decoder.raw_decode(self._buffer.lstrip())
            except ValueError:
                return
            self._buffer = self._buffer.lstrip()[end:]
            self.received.append(message)
            if message["ShotDataOptions"]["IsHeartBeat"]:
                continue
            if self.chatter:
                self.say({"Code": 201, "Message": "Player", "Player": {"Handed": "RH", "Club": "I7"}}, client)
                time.sleep(0.05)
            if self.answer:
                self.say(self.answer, client)
