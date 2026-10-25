"""Perception readers. The VLM itself is intentionally absent."""

from __future__ import annotations

from typing import Protocol

from pixelshark_schema import GameState


class TableReader(Protocol):
    def read(self, image: bytes) -> GameState:
        """Turn one frame into a game-state document."""


class GroundTruthReader:
    """Return a state supplied by the caller. ``image`` is ignored.

    This is the phase-0 stand-in. It lets the orchestrator run against the
    table's ground truth before a model exists.
    """

    def __init__(self, state: GameState) -> None:
        self.state = state

    def read(self, image: bytes) -> GameState:
        del image
        return self.state


class VlmReader:
    """Future vision-language reader. Not implemented in phase 0."""

    def read(self, image: bytes) -> GameState:
        del image
        raise NotImplementedError(
            "VLM perception is a later phase. Use GroundTruthReader until a model is wired."
        )
