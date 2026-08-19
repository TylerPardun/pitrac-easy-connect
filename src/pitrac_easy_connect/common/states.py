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
}

_DETAILS = {
    State.STARTING: "PiTrac is checking its hardware and services. This takes about a minute.",
    State.SETUP_REQUIRED: "PiTrac could not join a saved network. Connect to the PiTrac setup signal to choose one.",
    State.CONNECTING: "PiTrac is trying a network, pairing, or simulator connection. It will report a result shortly.",
    State.CONNECTED: "PiTrac and this computer can talk to each other. The simulator path has not been checked yet.",
    State.SIMULATOR_ACTION_REQUIRED: "PiTrac is healthy, but your golf simulator needs a specific change before play.",
    State.READY_TO_PLAY: "Everything from the cameras to your simulator has been checked. Go hit a ball.",
    State.UPDATING: "An update is being installed. Leave the power connected until this finishes.",
    State.RECOVERY_REQUIRED: "PiTrac could not fix a problem on its own and needs you to choose a recovery action.",
    State.SHUTTING_DOWN: "Settings have been saved. Wait for the safe-to-unplug message before removing power.",
}
