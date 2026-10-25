"""Instruction-layer stubs with one real delay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pixelshark_schema import Decision, GameState


@dataclass(frozen=True)
class StyledAction:
    """A decision plus the pacing the executor should wait for."""

    decision: Decision
    delay_ms: int
    note: str


class Style(Protocol):
    def apply(self, state: GameState, decision: Decision) -> StyledAction:
        """Annotate ``decision`` with pacing. Do not change the poker action."""


class IdentityStyle:
    """Leave the action alone and do not wait."""

    def apply(self, state: GameState, decision: Decision) -> StyledAction:
        del state
        return StyledAction(decision=decision, delay_ms=0, note="no styling")


class HumanPace:
    """A fixed pause so an action is not instant. No randomness in phase 0."""

    def __init__(self, delay_ms: int = 400) -> None:
        if delay_ms < 0:
            raise ValueError("delay_ms cannot be negative")
        self.delay_ms = delay_ms

    def apply(self, state: GameState, decision: Decision) -> StyledAction:
        del state
        return StyledAction(
            decision=decision,
            delay_ms=self.delay_ms,
            note="steady pace",
        )
