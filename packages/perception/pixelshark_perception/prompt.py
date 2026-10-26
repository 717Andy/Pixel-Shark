"""The text we send with a screenshot so the model returns game-state JSON."""

from __future__ import annotations

import json

from pixelshark_schema import json_schema

_INSTRUCTIONS = """\
You read one screenshot of a no-limit hold'em table and report the game state.

The picture is the Pixel Shark research table, or another table that shows the
same facts. Skins only change colors and fonts. The layout stays: community
cards in the middle, the pot under them, seats around the felt, and action
buttons along the bottom.

Card codes are two characters, rank then suit: As, Td, 9h, 2c. Ten is the
letter T, not 10. Suits are c (clubs), d (diamonds), h (hearts), and s
(spades). If a card is face down, hidden, or not on the board yet, its value
is null. Do not invent hidden cards.

Seat numbers start at 0. The bottom seat is seat 0, then seats continue
clockwise. A name "Bot 1" is seat 0, "Bot 2" is seat 1, and so on. "You" is
the human. The D marker is the dealer button. The highlighted seat is the
player to act. The plate shows the position (BTN, SB, BB, UTG, UTG+1, MP, LJ,
HJ, CO) and the stack. Chips in front of a seat are that seat's bet for this
street. The number in the middle is the total pot, and on this table it
already includes live bets.

Buttons at the bottom are the legal actions, even when they are greyed out.
Kinds are fold, check, call, bet, and raise. A call amount is the extra chips
printed on Call. Bet and raise sizes are the street total ("raise to"), not
the extra chips on top of a call. min_to is the smallest legal total and
max_to is the largest. Sizing labels are only: min, 1/3 pot, 1/2 pot,
2/3 pot, pot, all-in.

Reply with one JSON object and no other text. No markdown fence.
schema_version must be "1.0.0" and source must be "perception". Every fact
you read is an object {"value": ..., "confidence": number from 0 to 1}. Use a
lower confidence when the glyph is unclear. If the picture does not show an
id, table_id "perceived" and hand_id "perceived-h1" are acceptable. If you
cannot see a shot clock, set shot_clock_ms to 20000 and leave remaining_ms
and deadline_unix_ms null. Include every seat you can see (2 to 9).
"""


def build_prompt() -> str:
    """Instructions plus the JSON Schema the answer has to satisfy."""

    schema = json.dumps(json_schema(), separators=(",", ":"))
    return f"{_INSTRUCTIONS}\nJSON Schema:\n{schema}\n"


def build_retry_prompt(base: str, previous: str, error: str) -> str:
    """Ask again, showing the last answer and why it was rejected."""

    clipped = previous.strip()
    if len(clipped) > 4000:
        clipped = clipped[:4000] + "\n…"
    reason = error.strip()
    if len(reason) > 1500:
        reason = reason[:1500] + "…"
    return (
        f"{base}\n"
        "The previous answer was not valid JSON for that schema. "
        "Fix it. Reply with one JSON object only.\n"
        f"Error:\n{reason}\n"
        f"Previous answer:\n{clipped}\n"
    )
