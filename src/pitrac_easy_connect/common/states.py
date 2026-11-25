"""The user-visible operating states defined by the product requirements.

Both the Pi service and the Companion report progress with these names so a
user reads the same word on the enclosure setup page and on the PC. Every state
carries the plain-language sentence shown to the user, because a bare state name
is not an explanation.
"""

from enum import Enum


class State(str, Enum):
    STARTING = "STARTING"
    SETUP_REQUIRED = "SETUP REQUIRED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SIMULATOR_ACTION_REQUIRED = "SIMULATOR ACTION REQUIRED"
    READY_TO_PLAY = "READY TO PLAY"
    UPDATING = "UPDATING"
    RECOVERY_REQUIRED = "RECOVERY REQUIRED"
    SHUTTING_DOWN = "SHUTTING DOWN"
    # Companion-side link states. These exist because a failed link to the
    # enclosure is not one thing — "never paired," "paired but kicked out,"
    # "this isn't the Pi we paired with anymore," "someone else is using it
    # right now," and "PiTrac itself could not join Wi-Fi" each need a
    # different next step, and collapsing them all into SETUP_REQUIRED (whose
    # own detail text is specifically about Wi-Fi provisioning) told the user
    # the wrong thing to go fix.
    PAIRING_REQUIRED = "PAIRING REQUIRED"
    PAIRING_REVOKED = "PAIRING REVOKED"
    SAVED_PI_RESET = "SAVED PI RESET"
    ANOTHER_COMPUTER_CONNECTED = "ANOTHER COMPUTER CONNECTED"
    RATE_LIMITED = "RATE LIMITED"

    @property
    def headline(self) -> str:
        return _HEADLINES[self]

    @property
    def detail(self) -> str:
        return _DETAILS[self]

    @property
    def is_playable(self) -> bool:
        return self is State.READY_TO_PLAY


_HEADLINES = {
    State.STARTING: "Starting up",
    State.SETUP_REQUIRED: "Setup required",
    State.CONNECTING: "Connecting",
    State.CONNECTED: "Connected",
    State.SIMULATOR_ACTION_REQUIRED: "Your simulator needs attention",
    State.READY_TO_PLAY: "Ready to play",
    State.UPDATING: "Installing an update",
    State.RECOVERY_REQUIRED: "Recovery required",
    State.SHUTTING_DOWN: "Shutting down",
    State.PAIRING_REQUIRED: "This computer is not paired",
    State.PAIRING_REVOKED: "This computer's access was removed",
    State.SAVED_PI_RESET: "PiTrac appears to have been reset or replaced",
    State.ANOTHER_COMPUTER_CONNECTED: "Another computer is connected",
    State.RATE_LIMITED: "Too many attempts — waiting",
}

_DETAILS = {
    State.STARTING: "PiTrac is checking its hardware and services. This takes about a minute.",
    State.SETUP_REQUIRED: "PiTrac could not join a saved network. Connect to the PiTrac setup signal to choose one.",
    State.CONNECTING: "PiTrac is trying a network, pairing, or simulator connection. It will report a result shortly.",
    State.CONNECTED: "PiTrac and this computer can talk to each other. A test shot has not been tried yet.",
    State.SIMULATOR_ACTION_REQUIRED: "PiTrac is healthy, but your golf simulator needs a specific change before play.",
    State.READY_TO_PLAY: "Everything a shot passes through has been checked. Go hit a ball.",
    State.UPDATING: "An update is being installed. Leave the power connected until this finishes.",
    State.RECOVERY_REQUIRED: "PiTrac could not fix a problem on its own and needs you to choose a recovery action.",
    State.SHUTTING_DOWN: "Settings have been saved. Wait for the safe-to-unplug message before removing power.",
    State.PAIRING_REQUIRED: "PiTrac does not recognise this computer. Search and pair with it again.",
    State.PAIRING_REVOKED: "The owner removed this computer's access. Ask them to open Pair another computer.",
    State.SAVED_PI_RESET: "A different PiTrac now answers at this computer's saved address. Remove the old "
    "pairing, then pair with the PiTrac that's here now.",
    State.ANOTHER_COMPUTER_CONNECTED: "Only one computer can be connected at a time. Close Easy-Connect on "
    "the other computer, or remove it from the trusted list.",
    State.RATE_LIMITED: "Too many connection attempts were refused. Wait, then try again.",
}
