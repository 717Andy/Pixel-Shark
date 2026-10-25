"""State tracker. Phase 0 does not smooth anything."""

from __future__ import annotations

from typing import Protocol

from pixelshark_schema import GameState


class Tracker(Protocol):
    def update(self, observation: GameState) -> GameState:
        """Fold one observation into the running belief and return that belief."""


class PassthroughTracker:
    """Return the observation unchanged."""

    def update(self, observation: GameState) -> GameState:
        return observation
