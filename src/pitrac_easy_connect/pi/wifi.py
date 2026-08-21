"""Changing the enclosure's network without ever stranding its owner.

The hard part of Wi-Fi provisioning is not joining a network. It is what happens
when joining goes wrong. A nontechnical user standing in a new house with an
enclosure that has no screen must never be able to reach a state where the only
way back is an SSH session.

So every change is provisional until it is proved:

1. Refuse to touch anything until the wireless country is known.
2. Write a journal entry naming the profile that currently works. If the power
   is cut anywhere after this point, the next boot finds the entry and undoes
   the change.
3. Ask NetworkManager for a checkpoint with its own rollback timer, so even a
   crash of this process restores the network.
4. Join the new network.
5. Stay provisional until something confirms it can actually reach the enclosure
   on that network.
6. If nothing confirms in time, restore the previous profile, and if that fails
   too, put the setup hotspot back.

Step 5 matters because the PC is usually attached to the setup hotspot while the
change is made, and that hotspot disappears the moment the enclosure joins the
house network. Confirmation therefore arrives over the *new* network, from the
Companion or from the setup page reloaded there, not over the link that
requested the change.
"""

import threading
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..common.configstore import ConfigStore
from ..common.errors import (
    NET_CONFIRM_TIMEOUT,
    NET_COUNTRY_INVALID,
    NET_COUNTRY_REQUIRED,
    NET_ENTERPRISE,
    NET_HOTSPOT_FAILED,
    NET_INTERRUPTED,
    NET_INVALID_DETAILS,
    NET_ISOLATED,
    NET_NO_ADDRESS,
    NET_NOT_FOUND,
    NET_WRONG_PASSWORD,
    EasyConnectError,
    ErrorInfo,
)
from .backend import (
    SECURITY_ENTERPRISE,
    SECURITY_WEP,
    ActiveConnection,
    BackendError,
    PiBackend,
    WifiNetwork,
)

#: How long the enclosure waits for something to confirm it is reachable on a
#: newly joined network before it gives up and restores what worked before.
CONFIRMATION_SECONDS = 150.0

#: NetworkManager's own rollback timer. Deliberately longer than the
#: confirmation window so our orderly rollback runs first and the checkpoint is
#: only a backstop for a crash.
CHECKPOINT_SECONDS = 240


class NetworkMode(str, Enum):
    UNKNOWN = "unknown"
    SETUP_HOTSPOT = "setup"
    RESIDENCE = "residence"
    DIRECT = "direct"


@dataclass(frozen=True)
class ProvisioningResult:
    ok: bool
    mode: NetworkMode
    message: str
    error: Optional[Dict[str, str]] = None
    awaiting_confirmation: bool = False
    ssid: str = ""

    def as_dict(self) -> Dict[str, Any]:
        value = {
            "ok": self.ok,
            "mode": self.mode.value,
            "message": self.message,
            "awaitingConfirmation": self.awaiting_confirmation,
            "ssid": self.ssid,
        }
        if self.error:
            value["error"] = self.error
        return value


def _classify_connect_failure(error: BackendError) -> ErrorInfo:
    text = str(error).lower()
    if "secret" in text or "password" in text or "psk" in text or "authentic" in text:
        return NET_WRONG_PASSWORD
    if "not found" in text or "no network" in text or "ssid" in text:
        return NET_NOT_FOUND
    if "address" in text or "dhcp" in text or "ip-config" in text:
        return NET_NO_ADDRESS
    if "802.1x" in text or "eap" in text:
        return NET_ENTERPRISE
    return NET_NO_ADDRESS


class WifiProvisioner:
    def __init__(
        self,
        backend: PiBackend,
        journal_path: Path,
        setup_ssid: str,
        setup_password: str,
        clock: Callable[[], float] = time.monotonic,
        confirmation_seconds: float = CONFIRMATION_SECONDS,
    ):
        self.backend = backend
        self.setup_ssid = setup_ssid
        self.setup_password = setup_password
        self.clock = clock
        self.confirmation_seconds = confirmation_seconds
        self._lock = threading.RLock()
        self._journal = ConfigStore(
            journal_path,
            defaults={"pending": None, "lastGood": None, "directMode": False},
            schema_version=1,
        )
        self._pending_deadline: Optional[float] = None
        self._checkpoint: Optional[str] = None
        self._last_error: Optional[EasyConnectError] = None
        self.mode = NetworkMode.UNKNOWN

    # --- Startup ----------------------------------------------------------

    def recover_after_boot(self) -> ProvisioningResult:
        """Undo a network change that a power cut interrupted, then get online.

        Called once at startup. A journal entry that is still present means the
        enclosure lost power between beginning a change and confirming it, so
        the change is abandoned and the previously working profile is restored.
        """

        with self._lock:
            interrupted = self._journal.get("pending")
            if interrupted:
                self._last_error = EasyConnectError(
                    NET_INTERRUPTED,
                    "a change to {} was interrupted".format(interrupted.get("ssid", "a network")),
                )
                previous_profile = interrupted.get("previousProfile")
                self._undo_pending(interrupted.get("ssid", ""), keep=previous_profile)
                restored = self._restore_previous(previous_profile)
                if restored:
                    return ProvisioningResult(
                        True,
                        self.mode,
                        "An interrupted network change was undone. PiTrac is back on {}.".format(
                            restored.ssid
                        ),
                        error=self._last_error.as_dict(),
                        ssid=restored.ssid,
                    )
                return self._fall_back_to_hotspot(self._last_error)

            return self.ensure_online()

    def ensure_online(self) -> ProvisioningResult:
        """Get onto a saved network, or put the setup hotspot up instead."""

        with self._lock:
            current = self.backend.active_connection()
            if current and not current.is_hotspot:
                self.mode = NetworkMode.RESIDENCE
                self._journal.update({"lastGood": current.profile})
                return ProvisioningResult(
                    True, self.mode, "PiTrac is on {}.".format(current.ssid), ssid=current.ssid
                )

            for profile in self._profiles_worth_trying():
                try:
                    connection = self.backend.activate_profile(profile)
                except BackendError:
                    continue
                self.mode = NetworkMode.RESIDENCE
                self._journal.update({"lastGood": profile})
                return ProvisioningResult(
                    True,
                    self.mode,
                    "PiTrac reconnected to {}.".format(connection.ssid),
                    ssid=connection.ssid,
                )

            return self._fall_back_to_hotspot(None)

    def _profiles_worth_trying(self) -> List[str]:
        saved = self.backend.saved_profiles()
        last_good = self._journal.get("lastGood")
        if last_good in saved:
            # The one that worked most recently is the most likely to work now.
            saved.remove(last_good)
            saved.insert(0, last_good)
        return saved

    # --- Reading the airwaves --------------------------------------------

    def country(self) -> str:
        return self.backend.wifi_country()

    def set_country(self, country: str) -> None:
        # Validated here rather than in the backend so a mistyped country is a
        # message the user can act on, not an internal error.
        code = str(country or "").strip().upper()
        if len(code) != 2 or not all("A" <= character <= "Z" for character in code):
            raise EasyConnectError(NET_COUNTRY_INVALID, "{!r} is not two letters".format(country))
        try:
            self.backend.set_wifi_country(code)
        except BackendError as exc:
            raise EasyConnectError(NET_COUNTRY_INVALID, str(exc)) from exc

    @staticmethod
    def _validate_details(ssid: str, password: Optional[str]) -> None:
        """Reject names and passwords no wireless network could accept.

        802.11 caps an SSID at 32 bytes and a WPA passphrase at 63 characters.
        Checking here turns a confusing failure deep inside NetworkManager into a
        sentence about line breaks, which is the usual real cause.
        """

        if len(ssid.encode("utf-8")) > 32:
            raise EasyConnectError(NET_INVALID_DETAILS, "the network name is too long")
        if any(ord(character) < 32 or ord(character) == 127 for character in ssid):
            raise EasyConnectError(
                NET_INVALID_DETAILS,
                "the network name contains a line break or control character",
            )
        if password is not None:
            if len(password) > 63:
                raise EasyConnectError(NET_INVALID_DETAILS, "the password is too long")
            if any(ord(character) < 32 or ord(character) == 127 for character in password):
                raise EasyConnectError(
                    NET_INVALID_DETAILS,
                    "the password contains a line break or control character",
                )

    def scan(self) -> List[WifiNetwork]:
        """What is in range, with the ones this enclosure already knows marked.

        Someone changing network needs to tell "the one I am on" and "the one I
        used at the old house" apart from a list of strangers' networks, and
        signal strength alone does not do that.
        """

        if not self.backend.wifi_country():
            raise EasyConnectError(NET_COUNTRY_REQUIRED, "no wireless country is set")
        try:
            known = set(self.backend.known_ssids())
        except Exception:
            # Never let this cost the user the list itself.
            known = set()
        return [
            replace(network, known=network.ssid in known)
            for network in self.backend.scan()
            if network.ssid != self.setup_ssid
        ]

    # --- Making a change --------------------------------------------------

    def join(
        self, ssid: str, password: Optional[str] = None, hidden: bool = False
    ) -> ProvisioningResult:
        with self._lock:
            if not self.backend.wifi_country():
                raise EasyConnectError(NET_COUNTRY_REQUIRED, "no wireless country is set")
            if not str(ssid).strip():
                raise EasyConnectError(NET_NOT_FOUND, "no network name was given")
            self._validate_details(str(ssid), password)

            self._reject_unsupported_security(ssid, hidden)

            previous = self.backend.active_connection()
            previous_profile = (
                previous.profile if previous and not previous.is_hotspot else None
            )

            # Written before anything is touched, so an interrupted change is
            # always detectable on the next boot.
            self._journal.update(
                {
                    "pending": {
                        "ssid": ssid,
                        "previousProfile": previous_profile,
                        "startedAt": time.time(),
                    }
                }
            )
            self._checkpoint = self.backend.create_checkpoint(CHECKPOINT_SECONDS)

            try:
                connection = self.backend.connect(ssid, password, hidden=hidden)
            except BackendError as exc:
                info = _classify_connect_failure(exc)
                error = EasyConnectError(info, str(exc))
                self._last_error = error
                self._undo_pending(ssid, keep=previous_profile)
                recovery = self._restore_previous(previous_profile) or None
                if recovery is None:
                    self._fall_back_to_hotspot(error)
                else:
                    self.mode = NetworkMode.RESIDENCE
                return ProvisioningResult(
                    False, self.mode, info.failed, error=error.as_dict(), ssid=ssid
                )

            self._pending_deadline = self.clock() + self.confirmation_seconds
            self.mode = NetworkMode.RESIDENCE
            return ProvisioningResult(
                True,
                self.mode,
                "PiTrac joined {}. Reconnect this computer to {} and open Easy-Connect to "
                "finish.".format(ssid, ssid),
                awaiting_confirmation=True,
                ssid=connection.ssid or ssid,
            )

    def _reject_unsupported_security(self, ssid: str, hidden: bool) -> None:
        if hidden:
            return  # a hidden network cannot be inspected before joining it
        try:
            visible = self.backend.scan(rescan=False)
        except BackendError:
            return
        for network in visible:
            if network.ssid != ssid:
                continue
            if network.security == SECURITY_ENTERPRISE:
                raise EasyConnectError(NET_ENTERPRISE, "{} uses 802.1X".format(ssid))
            if network.security == SECURITY_WEP:
                raise EasyConnectError(
                    NET_ENTERPRISE, "{} uses WEP, which is not secure".format(ssid)
                )
            return

    # --- Confirming or undoing -------------------------------------------

    @property
    def awaiting_confirmation(self) -> bool:
        with self._lock:
            return self._pending_deadline is not None

    def seconds_left_to_confirm(self) -> float:
        with self._lock:
            if self._pending_deadline is None:
                return 0.0
            return max(0.0, self._pending_deadline - self.clock())

    def confirm(self) -> ProvisioningResult:
        """Something reached the enclosure on the new network. Make it permanent."""

        with self._lock:
            if self._pending_deadline is None:
                current = self.backend.active_connection()
                return ProvisioningResult(
                    True,
                    self.mode,
                    "PiTrac is on {}.".format(current.ssid if current else "its saved network"),
                    ssid=current.ssid if current else "",
                )

            self._pending_deadline = None
            if self._checkpoint:
                self.backend.destroy_checkpoint(self._checkpoint)
                self._checkpoint = None

            current = self.backend.active_connection()
            self._journal.update(
                {"pending": None, "lastGood": current.profile if current else None}
            )
            self._last_error = None
            self.mode = NetworkMode.RESIDENCE
            return ProvisioningResult(
                True,
                self.mode,
                "PiTrac is connected to {} and will rejoin it automatically.".format(
                    current.ssid if current else "your network"
                ),
                ssid=current.ssid if current else "",
            )

    def poll(self) -> Optional[ProvisioningResult]:
        """Roll back if the confirmation window has run out. Safe to call often."""

        with self._lock:
            if self._pending_deadline is None or self.clock() < self._pending_deadline:
                return None
            pending = self._journal.get("pending") or {}
            ssid = pending.get("ssid", "the new network")

            # Two different problems look identical from here, and they need
            # different advice. If the router answers, the network is working
            # and is keeping devices from reaching each other — a guest network.
            # If it does not, the connection itself never came good.
            try:
                router_answers = self.backend.can_reach_gateway()
            except Exception:
                router_answers = None
            info = NET_ISOLATED if router_answers else NET_CONFIRM_TIMEOUT
            error = EasyConnectError(
                info,
                "nothing reached PiTrac on {} within {:.0f} seconds{}".format(
                    ssid, self.confirmation_seconds,
                    "; the router answered, so the network is blocking devices"
                    if router_answers else "",
                ),
            )
            self._last_error = error
            self._pending_deadline = None
            previous_profile = pending.get("previousProfile")
            self._undo_pending(pending.get("ssid", ""), keep=previous_profile)
            restored = self._restore_previous(previous_profile)
            if restored:
                self.mode = NetworkMode.RESIDENCE
                return ProvisioningResult(
                    False, self.mode, info.failed, error=error.as_dict(), ssid=restored.ssid
                )
            return self._fall_back_to_hotspot(error)

    def _undo_pending(self, ssid: str = "", keep: Optional[str] = None) -> None:
        self._journal.update({"pending": None})
        if self._checkpoint:
            self.backend.rollback_checkpoint(self._checkpoint)
            self._checkpoint = None
        self._forget_abandoned(ssid, keep)

    def _restore_previous(self, profile: Optional[str]) -> Optional[ActiveConnection]:
        """Put the named profile back, or report that there is nothing to go back to.

        The profile has to be named explicitly. Accepting whatever happens to be
        active would let an unconfirmed network pass itself off as the one that
        already worked, which is exactly what the confirmation step exists to
        prevent.
        """

        if not profile:
            return None
        current = self.backend.active_connection()
        if current and not current.is_hotspot and current.profile == profile:
            return current
        try:
            return self.backend.activate_profile(profile)
        except BackendError:
            return None

    def _forget_abandoned(self, ssid: str, keep: Optional[str]) -> None:
        """Delete the profile for a network that never proved itself.

        Easy Connect creates profiles with autoconnect enabled, so leaving a
        rejected network saved would let it win the next boot and undo the
        rollback we just performed. The profile that was already working, and
        the last one known good, are never removed.
        """

        if not ssid:
            return
        try:
            profile = self.backend.profile_name_for(ssid)
        except (BackendError, NotImplementedError):
            return
        if profile in {keep, self._journal.get("lastGood")}:
            return
        if profile not in self.backend.saved_profiles():
            return
        try:
            self.backend.forget_profile(profile)
        except BackendError:
            pass

    # --- The way back in --------------------------------------------------

    def start_setup_hotspot(self) -> ProvisioningResult:
        with self._lock:
            return self._fall_back_to_hotspot(None)

    def _fall_back_to_hotspot(self, cause: Optional[EasyConnectError]) -> ProvisioningResult:
        try:
            connection = self.backend.start_hotspot(self.setup_ssid, self.setup_password)
        except BackendError as exc:
            error = EasyConnectError(NET_HOTSPOT_FAILED, str(exc))
            self._last_error = error
            self.mode = NetworkMode.UNKNOWN
            return ProvisioningResult(
                False, self.mode, NET_HOTSPOT_FAILED.failed, error=error.as_dict()
            )

        self.mode = (
            NetworkMode.DIRECT if self._journal.get("directMode") else NetworkMode.SETUP_HOTSPOT
        )
        message = (
            "PiTrac is running in Direct Mode. Join {} from this computer.".format(self.setup_ssid)
            if self.mode is NetworkMode.DIRECT
            else "PiTrac could not join a saved network, so its setup signal {} is on.".format(
                self.setup_ssid
            )
        )
        return ProvisioningResult(
            True,
            self.mode,
            message,
            error=cause.as_dict() if cause else None,
            ssid=connection.ssid,
        )

    def set_direct_mode(self, enabled: bool) -> ProvisioningResult:
        """Play without a router: the PC joins the enclosure's own signal."""

        with self._lock:
            self._journal.update({"directMode": bool(enabled)})
            if enabled:
                return self._fall_back_to_hotspot(None)
            self.backend.stop_hotspot()
            return self.ensure_online()

    @property
    def direct_mode(self) -> bool:
        return bool(self._journal.get("directMode"))

    def forget_all_networks(self) -> None:
        """Reset networking only. Calibration and pairings are not touched."""

        with self._lock:
            for profile in self.backend.saved_profiles():
                try:
                    self.backend.forget_profile(profile)
                except BackendError:
                    continue
            self._journal.update({"pending": None, "lastGood": None})

    # --- Reporting --------------------------------------------------------

    @property
    def journal(self) -> ConfigStore:
        """The store recording the in-progress change, for the self-test to inspect."""

        return self._journal

    def status(self) -> Dict[str, Any]:
        with self._lock:
            current = self.backend.active_connection()
            return {
                "mode": self.mode.value,
                "directMode": self.direct_mode,
                "country": self.backend.wifi_country(),
                "connection": current.as_dict() if current else None,
                "savedNetworkCount": len(self.backend.saved_profiles()),
                "awaitingConfirmation": self._pending_deadline is not None,
                "secondsLeftToConfirm": round(self.seconds_left_to_confirm()),
                "setupSsid": self.setup_ssid,
                "lastError": self._last_error.as_dict() if self._last_error else None,
            }
