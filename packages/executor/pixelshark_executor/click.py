"""Map a decision onto a button box."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from pixelshark_schema import Decision


@dataclass(frozen=True)
class Click:
    x: float
    y: float
    action: str


class Executor(Protocol):
    def locate(self, decision: Decision, boxes: Sequence[Mapping[str, object]]) -> Click | None:
        """Return a click point, or None when no matching button is in the frame."""


def locate(decision: Decision, boxes: Sequence[Mapping[str, object]]) -> Click | None:
    """Center of the action button that matches ``decision``.

    Boxes use the datagen shape: ``label`` is ``button`` and ``attrs`` carries
    ``kind=action``, ``action`` (fold/check/call/bet/raise), and ``to`` for a
    sizing button. The dealer button (``kind=dealer``) is ignored.
    """

    matches: list[Mapping[str, object]] = []
    for box in boxes:
        if box.get("label") != "button":
            continue
        attrs = box.get("attrs")
        if not isinstance(attrs, Mapping):
            continue
        if attrs.get("kind") not in (None, "action"):
            continue
        if attrs.get("action") != decision.kind:
            continue
        matches.append(box)
    if decision.to_amount is not None:
        exact = [box for box in matches if _to_amount(box) == decision.to_amount]
        if exact:
            matches = exact
    if not matches:
        return None
    box = matches[0]
    x = float(box["x"])
    y = float(box["y"])
    width = float(box["width"])
    height = float(box["height"])
    return Click(x=x + width / 2, y=y + height / 2, action=decision.kind)


class ButtonExecutor:
    """:func:`locate` behind the executor protocol."""

    def locate(self, decision: Decision, boxes: Sequence[Mapping[str, object]]) -> Click | None:
        return locate(decision, boxes)


def _to_amount(box: Mapping[str, object]) -> int | None:
    attrs = box.get("attrs")
    if not isinstance(attrs, Mapping) or "to" not in attrs:
        return None
    raw = attrs["to"]
    try:
        return int(str(raw))
    except ValueError:
        return None
