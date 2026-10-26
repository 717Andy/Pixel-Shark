"""Turn one screenshot into a schema-valid game state."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from pixelshark_perception.backends import VlmBackend, VlmRequest, backend_from_env
from pixelshark_perception.consistency import ConsistencyIssue, check_consistency
from pixelshark_perception.errors import PerceptionError
from pixelshark_perception.prompt import build_prompt, build_retry_prompt
from pixelshark_perception.repair import extract_json_object, repair_document
from pixelshark_schema import GameState


class TableReader(Protocol):
    def read(self, image: bytes) -> GameState:
        """Turn one frame into a game-state document."""


@dataclass(frozen=True)
class PerceptionResult:
    """A read, plus the bookkeeping the eval harness and the read log want."""

    state: GameState
    issues: tuple[ConsistencyIssue, ...]
    attempts: int
    raw: str
    latency_s: float
    backend: str
    image: bytes = b""


class GroundTruthReader:
    """Return a state supplied by the caller. ``image`` is ignored.

    The orchestrator uses this when it is talking to our own table and does
    not want a model in the loop.
    """

    def __init__(self, state: GameState) -> None:
        self.state = state

    def read(self, image: bytes) -> GameState:
        del image
        return self.state


class VlmReader:
    """Ask a vision-language backend for JSON, then validate, repair, and cross-check.

    ``backend`` defaults to whatever ``PIXELSHARK_VLM`` selects. Tests pass a
    :class:`~pixelshark_perception.backends.MockBackend` so nothing here needs
    a GPU or an API key. A schema failure is sent back to the model up to
    ``attempts`` times. A document that parses but disagrees with itself is
    still returned; the disagreeing fields get a lower confidence.
    """

    def __init__(
        self,
        backend: VlmBackend | None = None,
        *,
        attempts: int = 3,
        default_confidence: float = 0.8,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.backend = backend if backend is not None else backend_from_env()
        self.attempts = attempts
        self.default_confidence = default_confidence
        self._prompt = build_prompt()

    def read(self, image: bytes) -> GameState:
        return self.read_detail(image).state

    def read_detail(self, image: bytes) -> PerceptionResult:
        started = time.perf_counter()
        prompt = self._prompt
        raw = ""
        last_error = "the model returned nothing"
        for attempt in range(1, self.attempts + 1):
            raw = self.backend.complete(VlmRequest(image=image, prompt=prompt))
            try:
                document = repair_document(
                    extract_json_object(raw),
                    default_confidence=self.default_confidence,
                )
                state = GameState.model_validate(document)
            except (PerceptionError, ValidationError, ValueError) as exc:
                last_error = str(exc)
                prompt = build_retry_prompt(self._prompt, raw, last_error)
                continue
            state, issues = check_consistency(state)
            return PerceptionResult(
                state=state,
                issues=tuple(issues),
                attempts=attempt,
                raw=raw,
                latency_s=time.perf_counter() - started,
                backend=self.backend.name,
                image=image,
            )
        raise PerceptionError(
            f"no schema-valid state after {self.attempts} attempt(s): {last_error}"
        )
