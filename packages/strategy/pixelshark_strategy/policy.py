"""Strategy adapters."""

from __future__ import annotations

import random
from typing import Protocol

from pixelshark_schema import Decision, GameState
from pixelshark_sim import ScriptedPolicy


class Strategy(Protocol):
    def choose(self, state: GameState) -> Decision:
        """Pick one action. It should be legal for ``state``, but callers still check."""


class ScriptedStrategy:
    """The unattended-play baseline. Not a solver."""

    def __init__(self, seed: int = 0) -> None:
        self._policy = ScriptedPolicy()
        self._rng = random.Random(seed)

    def choose(self, state: GameState) -> Decision:
        return self._policy.choose(state, self._rng)
