"""The phase-0 agent cycle. Collaborators are passed in; this module only sequences them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pixelshark_schema import Decision, GameState


@dataclass(frozen=True)
class StepResult:
    state: GameState
    decision: Decision
    delay_ms: int
    note: str
    click_x: float | None
    click_y: float | None


class AgentLoop:
    """Run one cycle. ``boxes`` is optional; without it the loop still chooses an action."""

    def __init__(
        self,
        reader: object,
        tracker: object,
        strategy: object,
        style: object,
        executor: object,
    ) -> None:
        self.reader = reader
        self.tracker = tracker
        self.strategy = strategy
        self.style = style
        self.executor = executor

    def step(
        self,
        image: bytes,
        boxes: Sequence[Mapping[str, object]] | None = None,
    ) -> StepResult:
        observation = self.reader.read(image)  # type: ignore[attr-defined]
        tracked = self.tracker.update(observation)  # type: ignore[attr-defined]
        decision = self.strategy.choose(tracked)  # type: ignore[attr-defined]
        styled = self.style.apply(tracked, decision)  # type: ignore[attr-defined]
        click = None
        if boxes is not None:
            click = self.executor.locate(styled.decision, boxes)  # type: ignore[attr-defined]
        return StepResult(
            state=tracked,
            decision=styled.decision,
            delay_ms=int(styled.delay_ms),
            note=str(styled.note),
            click_x=None if click is None else float(click.x),
            click_y=None if click is None else float(click.y),
        )
