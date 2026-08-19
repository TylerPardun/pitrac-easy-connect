"""Deciding which computers are allowed to talk to this enclosure.

Pairing has to satisfy two things that pull against each other: a person who
cannot use a terminal must be able to do it in a few seconds, and a neighbour on
the same Wi-Fi must not be able to do it at all.

The compromise is a six-digit code that is only visible to someone with physical
access — it appears on the setup page, which is reachable over the enclosure's
own hotspot, and on the maintenance screen, which needs an existing pairing.
Codes expire, work once, and are rate limited.

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
from typing import Any, Callable, Dict, List, Optional

from ..common import pairing_exchange as exchange
from ..common.configstore import ConfigStore
from ..common.errors import (
    PAIR_CODE_EXPIRED,
    PAIR_CODE_INVALID,
    PAIR_NOT_PAIRED,
    PAIR_RATE_LIMITED,
    EasyConnectError,
)

CODE_LIFETIME_SECONDS = 300.0
EXCHANGE_LIFETIME_SECONDS = 120.0

#: How many pairing exchanges may be in flight at once. Starting an exchange
#: needs no authentication, so without a cap anyone who can reach the setup page
#: could make the enclosure allocate memory indefinitely. A real user needs one;
#: a few spare covers a refreshed page or a second computer being set up.
MAX_OPEN_EXCHANGES = 8
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 600.0
SECRET_BYTES = 32


@dataclass(frozen=True)
class PairingCode:
    code: str
    expires_at: float

    def seconds_left(self, now: float) -> float:
        return max(0.0, self.expires_at - now)

    def as_dict(self, now: float) -> Dict[str, Any]:
        return {"code": self.code, "secondsLeft": round(self.seconds_left(now))}


@dataclass(frozen=True)
class NewPairing:
    """Handed to the Companion once, at the moment of pairing."""

    pairing_id: str
    secret: str
    device_id: str

    def as_dict(self) -> Dict[str, str]:
        return {"pairingId": self.pairing_id, "secret": self.secret, "deviceId": self.device_id}


def _now_code() -> str:
    # secrets.randbelow avoids the modulo bias a naive randint-on-digits has.
    return "{:06d}".format(secrets.randbelow(1_000_000))


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
            defaults={"pairings": {}},
            schema_version=1,
            secret=True,
        )
        self._code: Optional[PairingCode] = None
        self._failures: List[float] = []
        self._exchanges: Dict[str, Dict[str, Any]] = {}

    # --- Offering a code --------------------------------------------------

    def issue_code(self) -> PairingCode:
        """Make a fresh code, replacing any code that is still outstanding."""

        with self._lock:
            self._code = PairingCode(_now_code(), self.clock() + CODE_LIFETIME_SECONDS)
            return self._code

    def current_code(self) -> Optional[PairingCode]:
        with self._lock:
            if self._code and self._code.seconds_left(self.clock()) > 0:
                return self._code
            self._code = None
            return None

    def code_for_display(self) -> PairingCode:
        return self.current_code() or self.issue_code()

    # --- Redeeming one ----------------------------------------------------

    def _check_rate_limit(self) -> None:
        now = self.clock()
        self._failures = [at for at in self._failures if now - at < FAILURE_WINDOW_SECONDS]
        if len(self._failures) >= MAX_FAILURES:
            raise EasyConnectError(
                PAIR_RATE_LIMITED,
                "{} incorrect codes within {:.0f} minutes".format(
                    len(self._failures), FAILURE_WINDOW_SECONDS / 60
                ),
            )

    def redeem(self, code: str, computer_name: str = "") -> NewPairing:
        with self._lock:
            self._check_rate_limit()
            now = self.clock()
            offered = str(code or "").strip()

            outstanding = self._code
            if outstanding is None or outstanding.seconds_left(now) <= 0:
                self._code = None
                self._failures.append(now)
                raise EasyConnectError(PAIR_CODE_EXPIRED, "no code is currently valid")

            # Constant-time so the response time does not leak how much of the
            # code was right.
            if not hmac.compare_digest(offered, outstanding.code):
                self._failures.append(now)
                raise EasyConnectError(PAIR_CODE_INVALID, "the code did not match")

            # Single use: burn it whether or not anything later fails.
            self._code = None
            self._failures = []

            pairing_id = secrets.token_hex(8)
            secret = secrets.token_hex(SECRET_BYTES)
            name = " ".join(str(computer_name or "").split())[:40] or "Windows PC"

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
        code: str,
        client_proof: str,
        computer_name: str = "",
    ) -> Dict[str, str]:
        """Finish the exchange and hand back the pairing secret, masked.

        The rate limit is applied to the whole exchange, not just the code, so a
        caller cannot get unlimited attempts by starting a new exchange each
        time.
        """

        with self._lock:
            self._check_rate_limit()
            now = self.clock()
            session = getattr(self, "_exchanges", {}).get(session_id)
            if session is None or session["expiresAt"] <= now:
                self._failures.append(now)
                raise EasyConnectError(PAIR_CODE_EXPIRED, "the pairing exchange expired")

            try:
                key = exchange.shared_key(client_public, session["private"])
            except ValueError as exc:
                self._exchanges.pop(session_id, None)
                self._failures.append(now)
                raise EasyConnectError(PAIR_CODE_INVALID, str(exc)) from exc

            outstanding = self._code
            if outstanding is None or outstanding.seconds_left(now) <= 0:
                self._exchanges.pop(session_id, None)
                self._code = None
                self._failures.append(now)
                raise EasyConnectError(PAIR_CODE_EXPIRED, "no code is currently valid")

            expected = exchange.proof(
                key, outstanding.code, session["public"], client_public, "client"
            )
            if not exchange.verify_proof(expected, client_proof):
                # One attempt per exchange. Reusing it would turn the rate limit
                # into a formality.
                self._exchanges.pop(session_id, None)
                self._failures.append(now)
                raise EasyConnectError(PAIR_CODE_INVALID, "the code did not match")

            self._exchanges.pop(session_id, None)

        pairing = self.redeem(outstanding.code, computer_name)
        return {
            "pairingId": pairing.pairing_id,
            "deviceId": self.device_id,
            "maskedSecret": exchange.mask_secret(key, pairing.secret),
            "serverProof": exchange.proof(
                key, outstanding.code, session["public"], client_public, "server"
            ),
        }

    # --- Proving identity on every connection ----------------------------

    def new_challenge(self) -> str:
        return secrets.token_hex(24)

    def _secret_for(self, pairing_id: str) -> str:
        pairings = self._store.get("pairings") or {}
        record = pairings.get(pairing_id)
        if not record:
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
            self._store.set("pairings", pairings)

    def revoke_all(self) -> None:
        """Used by 'prepare for new owner'. Networking and calibration are untouched."""

        with self._lock:
            self._store.set("pairings", {})
            self._code = None

    @property
    def count(self) -> int:
        return len(self._store.get("pairings") or {})
