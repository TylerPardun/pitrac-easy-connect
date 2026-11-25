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
    NET_NOT_CONFIRMED,
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
from .nmcli_backend import PROVISIONAL_SUFFIX

#: How long the enclosure waits for something to confirm it is reachable on a
#: newly joined network before it gives up and restores what worked before.
CONFIRMATION_SECONDS = 150.0

#: NetworkManager's own rollback timer. Deliberately longer than the
#: confirmation window so our orderly rollback runs first and the checkpoint is
#: only a backstop for a crash.
CHECKPOINT_SECONDS = 240

#: How often the running loop looks at whether the enclosure is where it should
#: be. Each look costs a few processes, so not on every tick.
WATCH_SECONDS = 10.0

#: How long a saved network may be missing before the setup hotspot goes up. A
#: router restarting takes two or three minutes and comes back on its own.
LOST_NETWORK_SECONDS = 180.0

#: How long to sit on the setup hotspot between looking for a saved network, and
#: how long that grows to. After a power cut the enclosure is up long before the
#: router is, and without this it stayed on its own hotspot until restarted.
RETRY_SECONDS = (120.0, 300.0, 600.0)


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
        sleep: Callable[[float], None] = time.sleep,
        boot_grace: Optional[float] = None,
        confirmation_seconds: float = CONFIRMATION_SECONDS,
    ):
        self.backend = backend
        self.setup_ssid = setup_ssid
        self.setup_password = setup_password
        self.clock = clock
        #: Injectable so tests do not actually wait for a radio.
        self.sleep = sleep
        #: How long boot waits for the radio. Injectable for the same
        #: reason: a test suite must not spend real minutes on it.
        # Both waits are real time on a real radio and pure delay against a
        # simulated one, so a test can shorten them without changing what is
        # being tested.
        self.leaving_direct_grace = (
            self.LEAVING_DIRECT_MODE_GRACE_SECONDS if boot_grace is None
            else float(boot_grace)
        )
        self.boot_grace = (
            self.ASSOCIATION_GRACE_SECONDS if boot_grace is None else float(boot_grace)
        )
        self.confirmation_seconds = confirmation_seconds
        self._lock = threading.RLock()
        self._journal = ConfigStore(
            journal_path,
            defaults={"pending": None, "lastGood": None, "directMode": False, "adopting": None},
            schema_version=1,
        )
        self._pending_deadline: Optional[float] = None
        self._checkpoint: Optional[str] = None
        self._last_error: Optional[EasyConnectError] = None
        self.mode = NetworkMode.UNKNOWN
        #: Whether somebody is using the setup hotspot right now, as far as the
        #: service can tell. Taking it down to look for a router would cut them
        #: off in the middle of typing a password.
        self.hotspot_in_use: Callable[[], bool] = lambda: False
        #: What was in range the last time this radio could look.
        self._seen: List[WifiNetwork] = []
        self._started = False
        self._next_watch: Optional[float] = None
        self._lost_since: Optional[float] = None
        self._retry_at: Optional[float] = None
        self._retries = 0

    # --- Startup ----------------------------------------------------------

    def recover_after_boot(self) -> ProvisioningResult:
        """Undo a network change that a power cut interrupted, then get online.

        Called once at startup. A journal entry that is still present means the
        enclosure lost power between beginning a change and confirming it, so
        the change is abandoned and the previously working profile is restored.
        """

        with self._lock:
            self._finish_adopting()
            interrupted = self._journal.get("pending")
            if interrupted:
                self._last_error = EasyConnectError(
                    NET_INTERRUPTED,
                    "a change to {} was interrupted".format(interrupted.get("ssid", "a network")),
                )
                previous_profile = interrupted.get("previousProfile")
                self._undo_pending(interrupted.get("ssid", ""))
                if self.direct_mode:
                    return self._fall_back_to_hotspot(None)
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

            # At boot the radio has usually not associated yet, so wait
            # before deciding. This is the difference between a slow start
            # and an enclosure that strands itself on its own hotspot.
            return self.ensure_online(grace=self.boot_grace)

    #: How long to let NetworkManager finish associating before deciding the
    #: saved network has failed. Starting after ``network.target`` only means
    #: the stack is up, not that a radio has associated, and associating takes
    #: several seconds from cold. Judging too early is how an enclosure that
    #: was perfectly fine ends up on its own hotspot after a power cut.
    ASSOCIATION_GRACE_SECONDS = 45.0
    ASSOCIATION_POLL_SECONDS = 1.5
    #: Shorter, because a person is watching this one happen.
    LEAVING_DIRECT_MODE_GRACE_SECONDS = 15.0

    def _wait_for_association(self, seconds: float) -> Optional[ActiveConnection]:
        """Poll until the radio associates, the time runs out, or we give up.

        Bounded by a count as well as by the clock. A loop at boot whose only
        exit is a deadline is a loop that never ends if the clock does not move
        the way it is expected to -- a stepped clock, or an injected one that
        the sleep does not advance -- and hanging here means the enclosure
        never finishes starting.
        """

        deadline = self.clock() + seconds
        polls = max(1, int(seconds / self.ASSOCIATION_POLL_SECONDS) + 2)
        for _attempt in range(polls):
            current = self.backend.active_connection()
            if current and not current.is_hotspot:
                return current
            if self.clock() >= deadline:
                return None
            self.sleep(self.ASSOCIATION_POLL_SECONDS)
        return None

    def ensure_online(self, grace: float = 0.0) -> ProvisioningResult:
        """Get onto a saved network, or put the setup hotspot up instead.

        ``grace`` is how long to let the radio associate before concluding the
        network is gone. It defaults to none: only boot has a reason to wait,
        and everywhere else there is a person watching a spinner.
        """

        with self._lock:
            if self.direct_mode:
                # Chosen, so it is what boot restores. Without this the radio
                # rejoined whichever house it last knew, while everything on
                # screen went on saying Direct Mode.
                return self._fall_back_to_hotspot(None)
            current = self.backend.active_connection()
            if grace > 0 and (current is None or current.is_hotspot):
                # Give the radio time before concluding anything. This is the
                # difference between a slow boot and a lost network.
                waited = self._wait_for_association(grace)
                if waited is not None:
                    current = waited
            if current and not current.is_hotspot:
                self._settled()
                self._journal.update({"lastGood": current.profile})
                return ProvisioningResult(
                    True, self.mode, "PiTrac is on {}.".format(current.ssid), ssid=current.ssid
                )

            found = self._try_saved(self._profiles_worth_trying())
            return found or self._fall_back_to_hotspot(None)

    def _try_saved(self, profiles: List[str]) -> Optional[ProvisioningResult]:
        for profile in profiles:
            try:
                connection = self.backend.activate_profile(profile)
            except BackendError:
                continue
            self._settled()
            self._journal.update({"lastGood": profile})
            return ProvisioningResult(
                True,
                self.mode,
                "PiTrac reconnected to {}.".format(connection.ssid),
                ssid=connection.ssid,
            )
        return None

    def _settled(self) -> None:
        self._started = True
        self.mode = NetworkMode.RESIDENCE
        self._lost_since = None
        self._retry_at = None
        self._retries = 0

    def _profiles_worth_trying(self) -> List[str]:
        """Every Wi-Fi profile this Pi has, not only the ones we created.

        ``saved_profiles`` deliberately stops at Easy-Connect's own, because
        those are the only ones it may modify or delete. Deciding what to
        *join* is a different question, and answering it with the narrow list
        meant a Pi whose network was set up by netplan -- which is every Pi
        that had Wi-Fi before Easy-Connect was installed -- had nothing to try
        and went straight to its own hotspot on every boot.

        Activating a profile does not change it, so reaching past our own here
        is safe in a way that deleting one would not be.
        """

        try:
            profiles = list(self.backend.all_wifi_profiles())
        except Exception:
            profiles = list(self.backend.saved_profiles())
        # One that was never confirmed is not a network to go back to.
        profiles = [name for name in profiles if not name.endswith(PROVISIONAL_SUFFIX)]

        last_good = self._journal.get("lastGood")
        if last_good in profiles:
            # The one that worked most recently is the most likely to work now.
            profiles.remove(last_good)
            profiles.insert(0, last_good)
        return profiles

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
            if len(password) < 8:
                raise EasyConnectError(
                    NET_INVALID_DETAILS, "a Wi-Fi password is at least eight characters"
                )
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
            for network in self._networks()
            if network.ssid != self.setup_ssid
        ]

    def _networks(self, rescan: bool = True) -> List[WifiNetwork]:
        """What is in range, or was when the radio could last look.

        While the enclosure is being its own hotspot its one radio cannot scan,
        and that is exactly when somebody is standing there wanting to choose a
        network. So the list is taken just before the hotspot goes up and kept.
        """

        found = self.backend.scan() if rescan else self.backend.scan(rescan=False)
        others = [network for network in found if network.ssid != self.setup_ssid]
        if others:
            self._seen = others
        if others or not self.on_setup_hotspot:
            return others
        return [replace(network, in_use=False) for network in self._seen]

    def _look_around(self) -> None:
        """Note what is in range, before the radio stops being able to tell."""

        try:
            if self.backend.wifi_country():
                found = [n for n in self.backend.scan() if n.ssid != self.setup_ssid]
                if found:
                    self._seen = found
        except BackendError:
            pass

    # --- Making a change --------------------------------------------------

    def join(
        self, ssid: str, password: Optional[str] = None, hidden: bool = False
    ) -> ProvisioningResult:
        with self._lock:
            if not self.backend.wifi_country():
                raise EasyConnectError(NET_COUNTRY_REQUIRED, "no wireless country is set")
            ssid = str(ssid)
            if not ssid.strip():
                raise EasyConnectError(NET_NOT_FOUND, "no network name was given")
            password = password or None
            self._validate_details(ssid, password)
            # Every reason to refuse is checked before anything is abandoned.
            # Cancelling first meant a request that was then rejected -- an
            # unsupported business network, say -- left the previous
            # unconfirmed network active with its deadline and its rollback
            # record erased, so nothing would ever undo it.
            self._reject_unsupported_security(ssid, hidden)

            # Only now, with the new request known to be workable: undo the
            # provisional network rather than merely forgetting it was
            # pending, so the enclosure is on something known-good before the
            # next attempt starts.
            self._abandon_provisional_network()

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
                connection = self._reach(ssid, password, hidden)
            except BackendError as exc:
                info = _classify_connect_failure(exc)
                error = EasyConnectError(info, str(exc))
                self._last_error = error
                self._undo_pending(ssid)
                recovery = self._restore_previous(previous_profile) or None
                if recovery is None:
                    self._fall_back_to_hotspot(error)
                else:
                    self._settled()
                return ProvisioningResult(
                    False, self.mode, info.failed, error=error.as_dict(), ssid=ssid
                )

            self._pending_deadline = self.clock() + self.confirmation_seconds
            self._settled()
            return ProvisioningResult(
                True,
                self.mode,
                "PiTrac joined {}. Reconnect this computer to {} and open Easy-Connect to "
                "finish.".format(ssid, ssid),
                awaiting_confirmation=True,
                ssid=connection.ssid or ssid,
            )

    def _reach(self, ssid: str, password: Optional[str], hidden: bool) -> ActiveConnection:
        """Join a network, with the password it was saved with if none is given."""

        if password is None:
            failure: Optional[BackendError] = None
            for profile in self._profiles_worth_trying():
                if self.backend.ssid_of(profile) != ssid:
                    continue
                try:
                    return self.backend.activate_profile(profile)
                except BackendError as exc:
                    failure = exc
            if failure is not None:
                raise failure
        seen = next((network for network in self._seen if network.ssid == ssid), None)
        return self.backend.connect(
            ssid, password, hidden=hidden, wpa3_only=bool(seen and seen.wpa3_only)
        )

    def _reject_unsupported_security(self, ssid: str, hidden: bool) -> None:
        if hidden:
            return  # a hidden network cannot be inspected before joining it
        try:
            visible = self._networks(rescan=False)
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

    # These do not take the lock. A change of network holds it for as long as a
    # radio takes to associate, and the setup page has to go on answering then
    # more than at any other time.

    @property
    def awaiting_confirmation(self) -> bool:
        return self._pending_deadline is not None

    def seconds_left_to_confirm(self) -> float:
        deadline = self._pending_deadline
        return 0.0 if deadline is None else max(0.0, deadline - self.clock())

    def confirm(self, via: str = "") -> ProvisioningResult:
        """Something reached the enclosure on the new network. Make it permanent.

        ``via`` is the enclosure's own address that it was reached at, when the
        caller knows. A computer arriving over an Ethernet cable says nothing
        about whether the Wi-Fi works.
        """

        with self._lock:
            if self._pending_deadline is None:
                current = self.backend.active_connection()
                return ProvisioningResult(
                    True,
                    self.mode,
                    "PiTrac is on {}.".format(current.ssid if current else "its saved network"),
                    ssid=current.ssid if current else "",
                )

            # Confirmation means "a computer reached me over the new network".
            # Any paired computer can call this, and it might have reached the
            # enclosure over ethernet, or over the old network that has not
            # dropped yet. Making the change permanent on that basis is how a
            # machine ends up committed to a network nothing can actually
            # reach it on. So check what it is actually associated with.
            current = self.backend.active_connection()
            pending = self._journal.get("pending") or {}
            expected = str(pending.get("ssid") or "")
            if expected:
                if current is None or current.is_hotspot or current.ssid != expected:
                    on = "nothing" if current is None else (
                        "its own setup network" if current.is_hotspot else current.ssid)
                    raise EasyConnectError(
                        NET_NOT_CONFIRMED,
                        "the change was not confirmed over {}; PiTrac is on {}".format(
                            expected, on),
                    )

            if via and current is not None and not self.backend.simulated:
                if via != current.ipv4.split("/")[0]:
                    raise EasyConnectError(
                        NET_NOT_CONFIRMED,
                        "the computer reached PiTrac at {}, which is not its Wi-Fi".format(via),
                    )

            self._pending_deadline = None
            if self._checkpoint:
                self.backend.destroy_checkpoint(self._checkpoint)
                self._checkpoint = None

            # Proved. Recorded before the profiles are rearranged, so a power
            # cut in the middle finishes the rearranging rather than undoing
            # the network that was just proved.
            previous = str(pending.get("previousProfile") or "")
            self._journal.update({
                "pending": None,
                # Joining a network and proving it is leaving Direct Mode.
                "directMode": False,
                "lastGood": current.profile if current else None,
                "adopting": {
                    "ssid": expected,
                    "replacing": previous if expected and self._joins(previous, expected) else "",
                    "keep": str(self._journal.get("lastGood") or ""),
                } if expected else None,
            })
            adopted = self._finish_adopting()
            if adopted and current is not None:
                current = replace(current, profile=adopted)
                self._journal.update({"lastGood": adopted})
            self._last_error = None
            self._settled()
            return ProvisioningResult(
                True,
                self.mode,
                "PiTrac is connected to {} and will rejoin it automatically.".format(
                    current.ssid if current else "your network"
                ),
                ssid=current.ssid if current else "",
            )

    def _joins(self, profile: str, ssid: str) -> bool:
        if not profile:
            return False
        try:
            return self.backend.ssid_of(profile) == ssid
        except BackendError:
            return False

    def _finish_adopting(self) -> str:
        """Make a proved profile permanent, including after an interruption."""

        adopting = self._journal.get("adopting")
        if not adopting:
            return ""
        try:
            name = self.backend.adopt(
                str(adopting.get("ssid") or ""),
                replacing=str(adopting.get("replacing") or ""),
                keep=str(adopting.get("keep") or ""),
            )
        except BackendError:
            # It works; it is only not yet tidy. Tried again at the next boot.
            return ""
        self._journal.update({"adopting": None})
        return name

    def poll(self) -> Optional[ProvisioningResult]:
        """Keep the enclosure where it should be. Safe to call often.

        Undoes a change nothing confirmed, holds Direct Mode, and moves between
        a saved network and the setup hotspot as networks come and go.
        """

        with self._lock:
            if self._pending_deadline is None:
                return self._watch()
            if self.clock() < self._pending_deadline:
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
            self._undo_pending(pending.get("ssid", ""))
            restored = self._restore_previous(previous_profile)
            if restored:
                self._settled()
                return ProvisioningResult(
                    False, self.mode, info.failed, error=error.as_dict(), ssid=restored.ssid
                )
            return self._fall_back_to_hotspot(error)

    def _watch(self) -> Optional[ProvisioningResult]:
        now = self.clock()
        if not self._started:
            return None
        if self._next_watch is not None and now < self._next_watch:
            return None
        self._next_watch = now + WATCH_SECONDS

        current = self.backend.active_connection()
        on_hotspot = bool(current and current.is_hotspot)
        if self.direct_mode:
            return None if on_hotspot else self._fall_back_to_hotspot(None)

        if current is not None and not on_hotspot:
            if self.mode is not NetworkMode.RESIDENCE:
                self._settled()
            self._lost_since = None
            return None

        if current is None:
            # NetworkManager retries a network that is in range by itself. The
            # hotspot is for when that has clearly not worked.
            if self._lost_since is None:
                self._lost_since = now
            if now - self._lost_since < LOST_NETWORK_SECONDS:
                return None
            self._lost_since = None
            return self.ensure_online()

        return self._look_for_home(now)

    def _look_for_home(self, now: float) -> Optional[ProvisioningResult]:
        """On the setup hotspot: is a saved network back?"""

        if self._retry_at is None:
            self._retry_at = now + RETRY_SECONDS[0]
            return None
        if now < self._retry_at:
            return None
        profiles = self._profiles_worth_trying()
        if not profiles or self._hotspot_busy():
            self._retry_at = now + RETRY_SECONDS[0]
            return None

        self._retries += 1
        self._retry_at = now + RETRY_SECONDS[min(self._retries, len(RETRY_SECONDS) - 1)]
        retries, retry_at = self._retries, self._retry_at
        # The radio has to stop being an access point to look at all.
        self.backend.stop_hotspot()
        self._look_around()
        in_range = {network.ssid for network in self._seen}
        worth = [p for p in profiles if self.backend.ssid_of(p) in in_range]
        found = self._try_saved(worth)
        if found is not None:
            return found
        result = self._fall_back_to_hotspot(self._last_error)
        self._retries, self._retry_at = retries, retry_at
        return None if result.ok else result

    def _hotspot_busy(self) -> bool:
        try:
            if self.hotspot_in_use():
                return True
            return bool(self.backend.hotspot_clients())
        except Exception:
            # Not knowing is not a reason to cut somebody off.
            return True

    def _undo_pending(self, ssid: str = "") -> None:
        """Undo an unconfirmed change, then forget that it was pending.

        The order matters and used to be the other way round. Clearing the
        journal first means a power cut *during* the rollback leaves a machine
        that has neither the new network nor a record that it was mid-change,
        so the next boot has nothing to undo and the enclosure is stranded.
        The marker is the only evidence recovery is owed; it goes last.
        """

        if self._checkpoint:
            self.backend.rollback_checkpoint(self._checkpoint)
            self._checkpoint = None
        if ssid:
            try:
                self.backend.discard(ssid)
            except (BackendError, NotImplementedError):
                pass
        self._journal.update({"pending": None})

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

    # --- The way back in --------------------------------------------------

    def start_setup_hotspot(self) -> ProvisioningResult:
        with self._lock:
            return self._fall_back_to_hotspot(None)

    def _fall_back_to_hotspot(self, cause: Optional[EasyConnectError]) -> ProvisioningResult:
        self._started = True
        if not self.on_setup_hotspot:
            self._look_around()
        try:
            connection = self.backend.start_hotspot(self.setup_ssid, self.setup_password)
        except BackendError as exc:
            error = EasyConnectError(NET_HOTSPOT_FAILED, str(exc))
            self._last_error = error
            self.mode = NetworkMode.UNKNOWN
            return ProvisioningResult(
                False, self.mode, NET_HOTSPOT_FAILED.failed, error=error.as_dict()
            )

        self._lost_since = None
        self._retry_at = None
        self._retries = 0
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

    def _abandon_provisional_network(self) -> None:
        """Undo an unconfirmed change before starting another.

        Different from cancelling: the caller is about to move the enclosure
        somewhere else, so the provisional network is rolled back rather than
        silently kept.
        """

        pending = self._journal.get("pending") or {}
        if not pending:
            self._cancel_pending_change()
            return
        previous_profile = pending.get("previousProfile")
        self._undo_pending(pending.get("ssid", ""))
        self._restore_previous(previous_profile)
        self._pending_deadline = None

    def _cancel_pending_change(self) -> None:
        """Abandon an unconfirmed network change, without undoing it.

        Anything that deliberately changes where the enclosure lives has to
        call this first. A confirmation deadline and its NetworkManager
        checkpoint outlive whatever set them, so entering Direct Mode with one
        still running meant the old timer expired minutes later and quietly
        put the enclosure back on the residence network -- undoing a choice
        the owner had just made, with nothing on screen to explain it.

        The caller has already decided where the machine should be, so the
        checkpoint is destroyed rather than rolled back.
        """

        if self._checkpoint:
            try:
                self.backend.destroy_checkpoint(self._checkpoint)
            except BackendError:
                pass
            self._checkpoint = None
        self._pending_deadline = None
        pending = self._journal.get("pending") or {}
        if pending.get("ssid"):
            # Not confirmed and not going to be, so not worth keeping either.
            try:
                self.backend.discard(str(pending["ssid"]))
            except (BackendError, NotImplementedError):
                pass
        self._journal.update({"pending": None})

    def set_direct_mode(self, enabled: bool) -> ProvisioningResult:
        """Play without a router: the PC joins the enclosure's own signal."""

        with self._lock:
            if enabled:
                # Cancelling merely forgot that a change was pending. The
                # provisional network's profile stayed saved with autoconnect
                # on, so leaving Direct Mode later could silently rejoin a
                # network nobody ever confirmed. Undo it properly instead.
                self._abandon_provisional_network()
            else:
                self._cancel_pending_change()
            self._journal.update({"directMode": bool(enabled)})
            if enabled:
                return self._fall_back_to_hotspot(None)
            self.backend.stop_hotspot()
            # Someone is waiting on this one, so wait for the radio but not
            # for as long as a boot does.
            return self.ensure_online(grace=self.leaving_direct_grace)

    @property
    def on_setup_hotspot(self) -> bool:
        """Whether the enclosure is currently serving its own setup network.

        Being connected to it means being within Wi-Fi range of the enclosure,
        which is a meaningfully different thing from being somewhere on the
        residence network.
        """

        connection = self.backend.active_connection()
        return bool(connection and connection.is_hotspot)

    @property
    def direct_mode(self) -> bool:
        return bool(self._journal.get("directMode"))

    def forget_all_networks(self) -> None:
        """Reset networking only. Calibration and pairings are not touched."""

        with self._lock:
            # A pending change would otherwise expire later and try to restore
            # a profile this has just deleted.
            self._cancel_pending_change()
            for profile in self.backend.saved_profiles():
                try:
                    self.backend.forget_profile(profile)
                except BackendError:
                    continue
            # Direct Mode goes too. It is a choice about networks, and the next
            # owner should find an enclosure asking to be set up.
            self._journal.update({
                "pending": None, "lastGood": None, "adopting": None, "directMode": False,
            })

    # --- Reporting --------------------------------------------------------

    @property
    def journal(self) -> ConfigStore:
        """The store recording the in-progress change, for the self-test to inspect."""

        return self._journal

    def status(self) -> Dict[str, Any]:
        current = self.backend.active_connection()
        error = self._last_error
        return {
            "mode": self.mode.value,
            "directMode": self.direct_mode,
            "country": self.backend.wifi_country(),
            "connection": current.as_dict() if current else None,
            "savedNetworkCount": len(self.backend.saved_profiles()),
            "awaitingConfirmation": self.awaiting_confirmation,
            "secondsLeftToConfirm": round(self.seconds_left_to_confirm()),
            "setupSsid": self.setup_ssid,
            "lastError": error.as_dict() if error else None,
        }
