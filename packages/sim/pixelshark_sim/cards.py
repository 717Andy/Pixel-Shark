"""Card codes shared with the schema (``As``, ``Td``, ``9h``, ``2c``)."""

from __future__ import annotations

import re

_CODE = re.compile(r"^[2-9TJQKA][cdhs]$")
_IN_PARENS = re.compile(r"\(([2-9TJQKA][cdhs])\)")


def card_code(card: object) -> str:
    """Return the two-character code PokerKit uses in ``repr(card)``."""

    text = repr(card).strip("'\"")
    if _CODE.fullmatch(text):
        return text
    match = _IN_PARENS.search(str(card))
    if match is not None:
        return match.group(1)
    raise ValueError(f"unrecognized card {card!r}")
