"""Deciding which computers are allowed to talk to this enclosure.

There used to be a six-digit code here. It was removed, because it could not do
the job it claimed to do. The enclosure has no screen and no button, so the only
place a code can appear is its setup page — and that page is reachable by
anything on the same Wi-Fi. Anyone who could be stopped by the code could also
read it. Meanwhile the app grew to show that page itself, so the code became
something the app displayed and then asked you to type back to it.

What is left is the honest version of the same boundary. The first computer to
ask may pair, because an enclosure with nothing paired to it is one nobody has
set up yet. After that, pairing is closed until the owner opens a short window
from the setup page. So a computer can never pair without someone deciding, at
that moment, to let it — and the trust boundary is your home network, which is
what it always really was.

Each paired computer gets its own random secret. There is no fleet-wide
password, so revoking one PC cannot affect another, and a secret taken from one
enclosure is useless against the next one.

The secret is never sent over the network after pairing. Both sides prove they
hold it by answering a random challenge with an HMAC, which also means a
listener on the LAN learns nothing reusable and cannot replay an old exchange.
"""

import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List

from ..common import pairing_exchange as exchange
from ..common.configstore import ConfigStore
from ..common.errors import (
    PAIR_EXCHANGE_LOST,
    PAIR_NOT_ACCEPTING,
    PAIR_NOT_PAIRED,
    PAIR_RATE_LIMITED,
    PAIR_REVOKED,
    EasyConnectError,
)

#: How long the owner's "let another computer pair" window stays open.
PAIRING_WINDOW_SECONDS = 300.0
EXCHANGE_LIFETIME_SECONDS = 120.0

#: How many pairing exchanges may be in flight at once. Starting an exchange
#: needs no authentication, so without a cap anyone who can reach the setup page
#: could make the enclosure allocate memory indefinitely. A real user needs one;
#: a few spare covers a refreshed page or a second computer being set up.
MAX_OPEN_EXCHANGES = 8
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 600.0
#: A refused attempt is not a wrong guess any more, so this is only here to stop
#: something hammering the enclosure.
SECRET_BYTES = 32


@dataclass(frozen=True)
class NewPairing:
    """Handed to the Companion once, at the moment of pairing."""

    pairing_id: str
    secret: str
    device_id: str

    def as_dict(self) -> Dict[str, str]:
        return {"pairingId": self.pairing_id, "secret": self.secret, "deviceId": self.device_id}


class PairingManager:
    def __init__(
        self,
        path: Path,
        device_id: str,
        clock: Callable[[], float] = time.time,
    ):
        self.device_id = device_id
        self.clock = clock
        self._lock = threading.RLock()
        self._store = ConfigStore(
            path,
            defaults={"pairings": {}, "revoked": []},
            schema_version=1,
            secret=True,
        )
        self._open_until: float = 0.0
        self._failures: List[float] = []
        self._exchanges: Dict[str, Dict[str, Any]] = {}

    # --- Deciding whether anyone may pair right now -----------------------

    def open_window(self) -> float:
        """Let one more computer pair, for a few minutes. The owner asks for this."""

        with self._lock:
            self._open_until = self.clock() + PAIRING_WINDOW_SECONDS
            return PAIRING_WINDOW_SECONDS

    def close_window(self) -> None:
        with self._lock:
            self._open_until = 0.0

    def window_seconds_left(self) -> float:
        with self._lock:
            return max(0.0, self._open_until - self.clock())

    def accepting(self) -> bool:
        """Whether a computer asking to pair right now would be allowed.

        Open in exactly two situations: nothing has ever been paired, so this is
        an enclosure nobody has set up; or the owner opened a window just now.
        Note the first case is also the way back in if every computer is
        unpaired — otherwise an enclosure could be left with no way to reach it.
        """

        with self._lock:
            return self.count == 0 or self.window_seconds_left() > 0

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "accepting": self.accepting(),
                "windowSecondsLeft": round(self.window_seconds_left()),
                "firstSetup": self.count == 0,
            }

    def _check_rate_limit(self) -> None:
        now = self.clock()
        self._failures = [at for at in self._failures if now - at < FAILURE_WINDOW_SECONDS]
        if len(self._failures) >= MAX_FAILURES:
            raise EasyConnectError(
                PAIR_RATE_LIMITED,
                "{} refused attempts within {:.0f} minutes".format(
                    len(self._failures), FAILURE_WINDOW_SECONDS / 60
                ),
            )

    def create_pairing(self, computer_name: str = "") -> NewPairing:
        """Record a pairing. Whether to allow it is the caller's decision.

        Callers deciding on the basis of ``accepting`` must hold the lock
        across both, or two of them can decide yes on the same window.
        """

        with self._lock:
            now = self.clock()
            # A window is for one computer. Close it so a second cannot follow
            # through the same opening.
            self._open_until = 0.0
            self._failures = []

            pairing_id = secrets.token_hex(8)
            secret = secrets.token_hex(SECRET_BYTES)
            name = " ".join(str(computer_name or "").split())[:40] or "This computer"

            pairings = dict(self._store.get("pairings") or {})
            pairings[pairing_id] = {
                "name": name,
                "secret": secret,
                "createdAt": now,
                "lastSeen": now,
            }
            self._store.set("pairings", pairings)
            return NewPairing(pairing_id, secret, self.device_id)

    # --- The key exchange that delivers the secret -----------------------

    def begin_exchange(self) -> Dict[str, str]:
        """Start a pairing exchange and return this enclosure's public value."""

        with self._lock:
            now = self.clock()
            self._exchanges = {
                key: value
                for key, value in getattr(self, "_exchanges", {}).items()
                if value["expiresAt"] > now
            }
            # Evict the oldest rather than refusing, so a genuine user whose
            # page reloaded a few times is never locked out of pairing.
            while len(self._exchanges) >= MAX_OPEN_EXCHANGES:
                oldest = min(self._exchanges, key=lambda key: self._exchanges[key]["expiresAt"])
                del self._exchanges[oldest]

            session_id = secrets.token_hex(8)
            private = exchange.generate_private()
            public = exchange.public_for(private)
            self._exchanges[session_id] = {
                "private": private,
                "public": public,
                "expiresAt": now + EXCHANGE_LIFETIME_SECONDS,
            }
            return {"sessionId": session_id, "serverPublic": public}

    def complete_exchange(
        self,
        session_id: str,
        client_public: str,
        computer_name: str = "",
    ) -> Dict[str, str]:
        """Finish the exchange and hand back the pairing secret, masked.

        The exchange keeps the secret off the wire: it is masked with a key only
        this enclosure and that computer can derive, so anything listening on
        the network learns nothing it could reuse. What the exchange does not do
        is decide *whether* to pair — ``accepting`` does that, above.
        """

        with self._lock:
            self._check_rate_limit()
            now = self.clock()
            session = getattr(self, "_exchanges", {}).get(session_id)
            if session is None or session["expiresAt"] <= now:
                self._failures.append(now)
                raise EasyConnectError(PAIR_EXCHANGE_LOST, "the pairing exchange expired")

            try:
                key = exchange.shared_key(client_public, session["private"])
            except ValueError as exc:
                self._exchanges.pop(session_id, None)
                self._failures.append(now)
                raise EasyConnectError(PAIR_EXCHANGE_LOST, str(exc)) from exc

            if not self.accepting():
                # Checked here rather than at the start, so an enclosure that is
                # not accepting still costs an attempt against the rate limit.
                self._exchanges.pop(session_id, None)
                self._failures.append(now)
                raise EasyConnectError(
                    PAIR_NOT_ACCEPTING, "this enclosure is not accepting new computers"
                )

            self._exchanges.pop(session_id, None)
            # Created inside the same lock that decided it was allowed. With
            # the creation outside, two requests arriving together could both
            # pass `accepting` before either had consumed the window, and both
            # would be admitted -- which is exactly what the window exists to
            # prevent.
            pairing = self.create_pairing(computer_name)


        return {
            "pairingId": pairing.pairing_id,
            "deviceId": self.device_id,
            "maskedSecret": exchange.mask_secret(key, pairing.secret),
            "serverProof": exchange.proof(key, session["public"], client_public, "server"),
        }

    # --- Proving identity on every connection ----------------------------

    def new_challenge(self) -> str:
        return secrets.token_hex(24)

    def _secret_for(self, pairing_id: str) -> str:
        pairings = self._store.get("pairings") or {}
        record = pairings.get(pairing_id)
        if not record:
            # "Your access was removed" and "I have never heard of you" are
            # different situations for the person reading the message.
            if pairing_id in (self._store.get("revoked") or []):
                raise EasyConnectError(PAIR_REVOKED, "this pairing was revoked")
            raise EasyConnectError(PAIR_NOT_PAIRED, "unknown pairing")
        return record["secret"]

    @staticmethod
    def _tag(secret: str, challenge: str, role: str) -> str:
        return hmac.new(
            secret.encode("utf-8"), "{}|{}".format(challenge, role).encode("utf-8"), sha256
        ).hexdigest()

    def expected_client_proof(self, pairing_id: str, challenge: str) -> str:
        return self._tag(self._secret_for(pairing_id), challenge, "client")

    def server_proof(self, pairing_id: str, challenge: str) -> str:
        """What the enclosure sends back so the PC knows it is the right one."""

        return self._tag(self._secret_for(pairing_id), challenge, "server")

    def verify(self, pairing_id: str, challenge: str, proof: str) -> None:
        with self._lock:
            self._check_rate_limit()
            try:
                expected = self.expected_client_proof(pairing_id, challenge)
            except EasyConnectError:
                self._failures.append(self.clock())
                raise
            if not hmac.compare_digest(expected, str(proof or "")):
                self._failures.append(self.clock())
                raise EasyConnectError(PAIR_NOT_PAIRED, "the computer could not prove its pairing")
            self._failures = []
            self.touch(pairing_id)

    @staticmethod
    def client_proof(secret: str, challenge: str) -> str:
        """Used by the Companion, which holds the secret rather than the store."""

        return PairingManager._tag(secret, challenge, "client")

    @staticmethod
    def expected_server_proof(secret: str, challenge: str) -> str:
        return PairingManager._tag(secret, challenge, "server")

    # --- Managing trusted computers --------------------------------------

    def is_paired(self, pairing_id: str) -> bool:
        return pairing_id in (self._store.get("pairings") or {})

    def touch(self, pairing_id: str) -> None:
        with self._lock:
            pairings = dict(self._store.get("pairings") or {})
            if pairing_id in pairings:
                pairings[pairing_id] = {**pairings[pairing_id], "lastSeen": self.clock()}
                self._store.set("pairings", pairings)

    def trusted_computers(self) -> List[Dict[str, Any]]:
        pairings = self._store.get("pairings") or {}
        listed = [
            {
                "pairingId": pairing_id,
                "name": record.get("name", "Windows PC"),
                "pairedAt": record.get("createdAt"),
                "lastSeen": record.get("lastSeen"),
            }
            for pairing_id, record in pairings.items()
        ]
        return sorted(listed, key=lambda item: item.get("lastSeen") or 0, reverse=True)

    def rename(self, pairing_id: str, name: str) -> None:
        cleaned = " ".join(str(name or "").split())[:40]
        if not cleaned:
            raise ValueError("A computer needs a name")
        with self._lock:
            pairings = dict(self._store.get("pairings") or {})
            if pairing_id not in pairings:
                raise EasyConnectError(PAIR_NOT_PAIRED, "unknown pairing")
            pairings[pairing_id] = {**pairings[pairing_id], "name": cleaned}
            self._store.set("pairings", pairings)

    def revoke(self, pairing_id: str) -> None:
        with self._lock:
            pairings = dict(self._store.get("pairings") or {})
            if pairings.pop(pairing_id, None) is None:
                raise EasyConnectError(PAIR_NOT_PAIRED, "unknown pairing")
            # Remembering the id, and nothing else about it, is what lets the
            # revoked computer be told why rather than left guessing. The list
            # is capped so it cannot grow without bound.
            revoked = [item for item in (self._store.get("revoked") or []) if item != pairing_id]
            revoked.append(pairing_id)
            self._store.update({"pairings": pairings, "revoked": revoked[-50:]})

    def revoke_all(self) -> None:
        """Used by 'prepare for new owner'. Networking and calibration are untouched."""

        with self._lock:
            revoked = list(self._store.get("revoked") or [])
            revoked.extend(self._store.get("pairings") or {})
            self._store.update({"pairings": {}, "revoked": revoked[-50:]})
            self._open_until = 0.0

    def export(self) -> Dict[str, Any]:
        """The full pairing records, secrets included, for a backup.

        Only ever called when the owner has explicitly asked to include paired
        computers, because the result is as sensitive as the pairings themselves.
        """

        with self._lock:
            return {"pairings": dict(self._store.get("pairings") or {})}

    def restore(self, section: Dict[str, Any]) -> None:
        pairings = section.get("pairings")
        if not isinstance(pairings, dict):
            return
        cleaned = {
            str(pairing_id): record
            for pairing_id, record in pairings.items()
            if isinstance(record, dict) and record.get("secret")
        }
        with self._lock:
            self._store.set("pairings", cleaned)
            self._open_until = 0.0

    @property
    def count(self) -> int:
        return len(self._store.get("pairings") or {})
