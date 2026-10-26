"""The training interface for fast per-skin detectors. Training itself is later.

A vision-language model is the reader this phase. The next phase can distill
those reads into a small detector for each skin. :func:`load_log` already
turns a read log into labeled frames. :meth:`PerSkinDetectorTrainer.fit` is
the hook that will consume them, and it refuses to pretend it trained anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pixelshark_perception.readlog import LoggedRead, load_log
from pixelshark_schema import GameState


class PerSkinDetector(Protocol):
    """A small model that reads one skin. Not implemented in this phase."""

    def read(self, image: bytes, *, skin: str | None = None) -> GameState:
        """Turn one frame into a game state, the same job as the VLM reader."""


class PerSkinDetectorTrainer:
    """Group logged reads by skin and, later, fit one detector each.

    ``fit`` always raises :class:`NotImplementedError`. Call it only to confirm
    the log loads. The exception text says how many frames were waiting.
    """

    def fit(self, log_dir: str | Path) -> PerSkinDetector:
        examples: list[LoggedRead] = load_log(Path(log_dir))
        counts: dict[str, int] = {}
        for example in examples:
            counts[example.skin] = counts.get(example.skin, 0) + 1
        summary = ", ".join(f"{skin}={count}" for skin, count in sorted(counts.items())) or "none"
        raise NotImplementedError(
            "Per-skin detector training is the next phase. Nothing was trained. "
            f"The log has {len(examples)} frame(s) across skins: {summary}."
        )
