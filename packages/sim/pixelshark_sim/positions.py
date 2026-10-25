"""Seat geometry for 2 to 9 handed no-limit hold'em.

Seats are numbered clockwise. The ring for a hand starts at the button and
walks clockwise through seats that still have chips. Heads-up is special:
the button posts the small blind and PokerKit's player 0 is the big blind.
With three or more players, PokerKit's player 0 is the small blind and the
last player is the button.
"""

from __future__ import annotations

# Index is the clockwise offset from the button.
POSITIONS: dict[int, tuple[str, ...]] = {
    2: ("BTN", "BB"),
    3: ("BTN", "SB", "BB"),
    4: ("BTN", "SB", "BB", "UTG"),
    5: ("BTN", "SB", "BB", "UTG", "CO"),
    6: ("BTN", "SB", "BB", "UTG", "HJ", "CO"),
    7: ("BTN", "SB", "BB", "UTG", "LJ", "HJ", "CO"),
    8: ("BTN", "SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO"),
    9: ("BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"),
}


def effective_button(seat_count: int, button: int, active: set[int]) -> int:
    """Button seat for this hand. If that seat is sitting out, walk clockwise."""

    if button in active:
        return button
    for step in range(1, seat_count + 1):
        seat = (button + step) % seat_count
        if seat in active:
            return seat
    raise ValueError("no seated player has chips")


def ring_from_button(seat_count: int, button: int, active: set[int]) -> list[int]:
    """Clockwise seats in the hand, starting with the button."""

    start = effective_button(seat_count, button, active)
    ring = [start]
    seat = start
    while len(ring) < len(active):
        for step in range(1, seat_count + 1):
            nxt = (seat + step) % seat_count
            if nxt in active:
                seat = nxt
                break
        else:  # pragma: no cover - active seats are a subset of the table
            raise ValueError("active seats are not on the table")
        ring.append(seat)
    return ring


def pokerkit_order(ring: list[int]) -> list[int]:
    """Translate a button-first ring into PokerKit's player-index order."""

    if len(ring) < 2:
        raise ValueError("a hand needs two players")
    if len(ring) == 2:
        # Player 0 posts the big blind. The button posts the small blind.
        return [ring[1], ring[0]]
    # Player 0 is the small blind, player 1 the big blind, and the last is the button.
    return ring[1:] + ring[:1]


def position_for(ring: list[int], seat: int) -> str:
    return POSITIONS[len(ring)][ring.index(seat)]
