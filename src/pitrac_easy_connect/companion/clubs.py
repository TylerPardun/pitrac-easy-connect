"""Which club to reach for, from how far away the target is.

PiTrac measures the ball and cannot see the club, so nothing here detects one.
What it can do is what a caddie does: look at the distance and at how far this
player actually hits things, and suggest. The player's word always wins.
"""

from typing import Dict, Iterable, List, Optional

#: Every club that can be chosen, longest first, with a carry in yards to assume
#: until this player has hit it enough to know better. Ordinary amateur
#: distances: starting too long is what makes a suggestion useless.
CARRIES = {
    "Driver": 225, "3 wood": 208, "5 wood": 194, "3 hybrid": 188, "4 hybrid": 178,
    "3 iron": 182, "4 iron": 172, "5 iron": 162, "6 iron": 152, "7 iron": 142,
    "8 iron": 131, "9 iron": 120, "Pitching wedge": 108, "Gap wedge": 95,
    "Sand wedge": 80, "Lob wedge": 65, "Putter": 0,
}
CLUBS = list(CARRIES)

#: Fourteen, as the rules allow, until the player says what they carry.
DEFAULT_BAG = [
    "Driver", "3 wood", "5 wood", "4 hybrid", "5 iron", "6 iron", "7 iron", "8 iron",
    "9 iron", "Pitching wedge", "Gap wedge", "Sand wedge", "Lob wedge", "Putter",
]

#: A club's own distance is believed after this many shots, from this many most
#: recent ones. The median, so that one topped ball does not change the caddie.
ENOUGH_SHOTS = 3
RECENT_SHOTS = 20


def clean_bag(names: Optional[Iterable[str]]) -> List[str]:
    """Known clubs only, in order, and never empty."""

    wanted = set(names or [])
    bag = [club for club in CLUBS if club in wanted]
    return bag or list(DEFAULT_BAG)


def known_carries(shots: List[Dict[str, object]]) -> Dict[str, float]:
    """How far this player carries each club, for the clubs they have hit enough."""

    by_club: Dict[str, List[float]] = {}
    for shot in shots:
        carry = shot.get("carry")
        club = shot.get("club")
        if club in CARRIES and isinstance(carry, (int, float)) and carry > 0:
            by_club.setdefault(str(club), []).append(float(carry))
    return {
        club: _median(carries[-RECENT_SHOTS:])
        for club, carries in by_club.items()
        if len(carries) >= ENOUGH_SHOTS
    }


def carries(known: Dict[str, float]) -> Dict[str, float]:
    """A distance for every club: theirs where known, scaled guesses elsewhere.

    Somebody who hits a 7 iron 165 does not hit a 6 iron 152. The clubs they
    have hit say how long a hitter they are, and the rest follow from that.
    """

    ratios = [known[club] / CARRIES[club] for club in known if CARRIES.get(club)]
    scale = _median(ratios) if ratios else 1.0
    return {
        club: round(known.get(club, default * scale), 1) for club, default in CARRIES.items()
    }


def suggest(distance: float, bag: Iterable[str], distances: Dict[str, float]) -> str:
    """The club in the bag whose carry comes closest. Never the putter.

    A tie goes to the longer club: short of the green is the commoner miss.
    The putter changes how PiTrac measures, so only the player chooses it.
    """

    choices = [club for club in clean_bag(bag) if club != "Putter"]
    if not choices:
        return ""
    return min(choices, key=lambda club: (abs(distances[club] - distance), -distances[club]))


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0
