"""Score a reader against a datagen directory and write a report.

A datagen sample is a folder with ``frame.png``, ``state.json``, and usually
``meta.json``. The harness asks the reader to read each frame, then compares
that read to the ground truth. Confidence is ignored on purpose: this measures
whether the values are right, not whether the model sounded sure.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pixelshark_perception.backends import OracleBackend, VlmBackend
from pixelshark_perception.consistency import ConsistencyIssue
from pixelshark_perception.errors import PerceptionError
from pixelshark_perception.reader import VlmReader
from pixelshark_perception.readlog import ReadLog
from pixelshark_schema import GameState, LegalAction

_KIND_ORDER = ("fold", "check", "call", "bet", "raise")
_SIZE_ORDER = ("min", "1/3 pot", "1/2 pot", "2/3 pot", "pot", "all-in")

DEFINITIONS = {
    "cards": (
        "Board cards, plus hole cards whose faces were drawn "
        "(ground-truth hole_cards_shown is true)."
    ),
    "cards_including_hidden": ("Every hole-card code in the ground truth, including card backs."),
    "numbers": (
        "Blinds, ante, total pot, each pot amount, stacks, bets, button seat, and actor seat."
    ),
    "positions": "The position name at each seat.",
    "legal_actions": (
        "Each legal action, including kind, call amount, min and max, the sizing buttons, "
        "and whether it is all-in."
    ),
    "full_state_exact_match": (
        "Street, board, pot, seats, positions, stacks, bets, status, names, and legal actions "
        "all match. Hole-card codes that were not drawn are ignored, but the shown flag is not."
    ),
}


@dataclass
class Score:
    correct: int = 0
    total: int = 0

    def add(self, ok: bool) -> None:
        self.total += 1
        if ok:
            self.correct += 1

    def merge(self, other: Score) -> None:
        self.correct += other.correct
        self.total += other.total

    def as_dict(self) -> dict[str, Any]:
        accuracy = None if self.total == 0 else round(self.correct / self.total, 4)
        return {"correct": self.correct, "total": self.total, "accuracy": accuracy}


@dataclass
class Bucket:
    cards: Score = field(default_factory=Score)
    cards_including_hidden: Score = field(default_factory=Score)
    numbers: Score = field(default_factory=Score)
    positions: Score = field(default_factory=Score)
    legal_actions: Score = field(default_factory=Score)
    exact: Score = field(default_factory=Score)
    latencies: list[float] = field(default_factory=list)
    frames: int = 0
    failures: int = 0

    def merge(self, other: Bucket) -> None:
        self.cards.merge(other.cards)
        self.cards_including_hidden.merge(other.cards_including_hidden)
        self.numbers.merge(other.numbers)
        self.positions.merge(other.positions)
        self.legal_actions.merge(other.legal_actions)
        self.exact.merge(other.exact)
        self.latencies.extend(other.latencies)
        self.frames += other.frames
        self.failures += other.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "failures": self.failures,
            "cards": self.cards.as_dict(),
            "cards_including_hidden": self.cards_including_hidden.as_dict(),
            "numbers": self.numbers.as_dict(),
            "positions": self.positions.as_dict(),
            "legal_actions": self.legal_actions.as_dict(),
            "full_state_exact_match": self.exact.as_dict(),
            "latency_s": _latency(self.latencies),
        }


@dataclass(frozen=True)
class Sample:
    sample_id: str
    skin: str
    image: bytes
    truth: GameState


def load_dataset(path: Path) -> list[Sample]:
    """Read a datagen directory. A manifest is used when one is present."""

    manifest_path = path / "manifest.json"
    skins: dict[str, str] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        ids = [str(item["id"]) for item in manifest["samples"]]
        skins = {
            str(item["id"]): str(item.get("skin") or "unknown") for item in manifest["samples"]
        }
    else:
        ids = sorted(
            child.name
            for child in path.iterdir()
            if child.is_dir() and (child / "state.json").exists() and (child / "frame.png").exists()
        )
    if not ids:
        raise FileNotFoundError(f"no labeled frames in {path}")
    samples: list[Sample] = []
    for sample_id in ids:
        folder = path / sample_id
        meta_path = folder / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        skin = str(meta.get("skin") or skins.get(sample_id) or "unknown")
        samples.append(
            Sample(
                sample_id=sample_id,
                skin=skin,
                image=(folder / "frame.png").read_bytes(),
                truth=GameState.model_validate_json((folder / "state.json").read_text()),
            )
        )
    return samples


def evaluate_dataset(
    dataset: Path,
    backend: VlmBackend,
    *,
    holdout_skin: str = "linen",
    out: Path | None = None,
    log_dir: Path | None = None,
    limit: int | None = None,
    attempts: int = 3,
) -> dict[str, Any]:
    """Run ``backend`` over ``dataset`` and return the report dict.

    When ``out`` is set, ``report.json`` and ``report.md`` are written there.
    When ``log_dir`` is set, each successful read is stored with its frame.
    """

    samples = load_dataset(dataset)
    if limit is not None:
        samples = samples[:limit]
    reader = VlmReader(backend, attempts=attempts)
    read_log = ReadLog(log_dir) if log_dir is not None else None
    oracle = backend if isinstance(backend, OracleBackend) else None
    overall = Bucket()
    by_skin: dict[str, Bucket] = {}
    frames: list[dict[str, Any]] = []
    for sample in samples:
        if oracle is not None:
            oracle.response = sample.truth.model_dump_json()
        bucket = by_skin.setdefault(sample.skin, Bucket())
        frame, partial = _score_frame(reader, sample, read_log)
        frames.append(frame)
        for target in (overall, bucket):
            target.frames += 1
            target.latencies.append(frame["latency_s"])
            target.failures += int(frame["failure"] is not None)
            target.cards.merge(partial.cards)
            target.cards_including_hidden.merge(partial.cards_including_hidden)
            target.numbers.merge(partial.numbers)
            target.positions.merge(partial.positions)
            target.legal_actions.merge(partial.legal_actions)
            target.exact.merge(partial.exact)
    seen = Bucket()
    holdout = Bucket()
    for skin, bucket in by_skin.items():
        if skin == holdout_skin:
            holdout.merge(bucket)
        else:
            seen.merge(bucket)
    report = {
        "schema_version": "1.0.0",
        "dataset": str(dataset),
        "backend": backend.name,
        "holdout_skin": holdout_skin,
        "frames": len(samples),
        "definitions": DEFINITIONS,
        "overall": overall.as_dict(),
        "seen_skins": seen.as_dict(),
        "holdout": holdout.as_dict(),
        "by_skin": {skin: bucket.as_dict() for skin, bucket in sorted(by_skin.items())},
        "samples": frames,
    }
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        (out / "report.md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """A short report a person can read without opening the JSON."""

    lines = [
        "# Perception eval",
        "",
        f"Backend: `{report['backend']}`",
        f"Dataset: `{report['dataset']}`",
        f"Frames: {report['frames']}",
        f"Held-out skin: `{report['holdout_skin']}`",
        "",
        "The held-out skin is a look the default screenshot set does not use. "
        "Compare it with the other skins to see whether a reader generalizes.",
        "",
        "## Overall",
        "",
        _table(report["overall"]),
        "",
        "## Skins the default set uses",
        "",
        _table(report["seen_skins"]),
        "",
        f"## Held-out skin ({report['holdout_skin']})",
        "",
    ]
    if report["holdout"]["frames"] == 0:
        lines.append(
            "No frames used this skin. Generate some with "
            "`pixelshark-datagen generate --include-holdout`, then run the eval again."
        )
    else:
        lines.append(_table(report["holdout"]))
    lines.extend(["", "## Per skin", ""])
    if not report["by_skin"]:
        lines.append("No frames.")
    for skin, bucket in report["by_skin"].items():
        lines.extend([f"### {skin}", "", _table(bucket), ""])
    lines.extend(
        [
            "## Frames",
            "",
            "| id | skin | exact | latency | issues |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for frame in report["samples"]:
        exact = "fail" if frame["failure"] else ("yes" if frame["exact"] else "no")
        issues = ", ".join(frame["issues"]) or ""
        lines.append(
            f"| {frame['id']} | {frame['skin']} | {exact} | {frame['latency_s']:.3f}s | {issues} |"
        )
    lines.extend(["", "## What the columns count", ""])
    for name, text in report["definitions"].items():
        lines.append(f"- **{name}**: {text}")
    lines.append("")
    return "\n".join(lines)


def _score_frame(
    reader: VlmReader,
    sample: Sample,
    read_log: ReadLog | None,
) -> tuple[dict[str, Any], Bucket]:
    started = time.perf_counter()
    try:
        result = reader.read_detail(sample.image)
    except PerceptionError as exc:
        bucket = _score_values(sample.truth, None)
        bucket.exact.add(False)
        return (
            {
                "id": sample.sample_id,
                "skin": sample.skin,
                "exact": False,
                "latency_s": round(time.perf_counter() - started, 6),
                "attempts": reader.attempts,
                "issues": [],
                "failure": str(exc),
            },
            bucket,
        )
    bucket = _score_values(sample.truth, result.state)
    exact = _exact(sample.truth, result.state)
    bucket.exact.add(exact)
    if read_log is not None:
        read_log.write(
            image=sample.image,
            state=result.state,
            raw=result.raw,
            issues=_issue_dicts(result.issues),
            backend=result.backend,
            attempts=result.attempts,
            latency_s=result.latency_s,
            sample_id=sample.sample_id,
            skin=sample.skin,
            truth=sample.truth,
        )
    return (
        {
            "id": sample.sample_id,
            "skin": sample.skin,
            "exact": exact,
            "latency_s": round(result.latency_s, 6),
            "attempts": result.attempts,
            "issues": [issue.code for issue in result.issues],
            "failure": None,
        },
        bucket,
    )


def _score_values(truth: GameState, pred: GameState | None) -> Bucket:
    bucket = Bucket()
    _score_cards(bucket.cards, truth, pred, visible_only=True)
    _score_cards(bucket.cards_including_hidden, truth, pred, visible_only=False)
    _score_numbers(bucket.numbers, truth, pred)
    _score_positions(bucket.positions, truth, pred)
    _score_legal(bucket.legal_actions, truth, pred)
    return bucket


def _score_cards(
    score: Score, truth: GameState, pred: GameState | None, *, visible_only: bool
) -> None:
    pred_board = [card.value for card in pred.board] if pred is not None else []
    truth_board = [card.value for card in truth.board]
    width = max(len(truth_board), len(pred_board))
    for index in range(width):
        left = truth_board[index] if index < len(truth_board) else None
        right = pred_board[index] if index < len(pred_board) else None
        score.add(left == right)
    pred_seats = {seat.seat: seat for seat in pred.seats} if pred is not None else {}
    for seat in truth.seats:
        if visible_only and not seat.hole_cards_shown.value:
            continue
        other = pred_seats.get(seat.seat)
        truth_cards = [card.value for card in seat.hole_cards]
        pred_cards = [card.value for card in other.hole_cards] if other is not None else []
        for index in range(max(len(truth_cards), len(pred_cards))):
            left = truth_cards[index] if index < len(truth_cards) else None
            right = pred_cards[index] if index < len(pred_cards) else None
            score.add(left == right)


def _score_numbers(score: Score, truth: GameState, pred: GameState | None) -> None:
    def value(state: GameState | None, name: str) -> object:
        if state is None:
            return _missing
        return getattr(state, name).value

    for name in ("small_blind", "big_blind", "ante", "total_pot", "button_seat", "actor_seat"):
        score.add(value(truth, name) == value(pred, name))
    truth_pots = [pot.amount.value for pot in truth.pots]
    pred_pots = [pot.amount.value for pot in pred.pots] if pred is not None else []
    for index in range(max(len(truth_pots), len(pred_pots))):
        left = truth_pots[index] if index < len(truth_pots) else None
        right = pred_pots[index] if index < len(pred_pots) else None
        score.add(left == right)
    pred_seats = {seat.seat: seat for seat in pred.seats} if pred is not None else {}
    seen: set[int] = set()
    for seat in truth.seats:
        seen.add(seat.seat)
        other = pred_seats.get(seat.seat)
        score.add(other is not None and other.stack.value == seat.stack.value)
        score.add(other is not None and other.bet.value == seat.bet.value)
    if pred is not None:
        for seat in pred.seats:
            if seat.seat not in seen:
                score.add(False)
                score.add(False)


def _score_positions(score: Score, truth: GameState, pred: GameState | None) -> None:
    pred_seats = {seat.seat: seat for seat in pred.seats} if pred is not None else {}
    seen = {seat.seat for seat in truth.seats}
    for seat in truth.seats:
        other = pred_seats.get(seat.seat)
        score.add(other is not None and other.position.value == seat.position.value)
    if pred is not None:
        for seat in pred.seats:
            if seat.seat not in seen:
                score.add(False)


def _score_legal(score: Score, truth: GameState, pred: GameState | None) -> None:
    if pred is None:
        if not truth.legal_actions:
            score.add(False)
            return
        for _action in truth.legal_actions:
            score.add(False)
        return
    truth_counts = Counter(_signature(action) for action in truth.legal_actions)
    pred_counts = Counter(_signature(action) for action in pred.legal_actions)
    if not truth_counts and not pred_counts:
        score.add(True)
        return
    for key in set(truth_counts) | set(pred_counts):
        matched = min(truth_counts[key], pred_counts[key])
        total = max(truth_counts[key], pred_counts[key])
        for _ in range(matched):
            score.add(True)
        for _ in range(total - matched):
            score.add(False)


def _signature(action: LegalAction) -> tuple[Any, ...]:
    amount = None if action.amount is None else action.amount.value
    min_to = None if action.min_to is None else action.min_to.value
    max_to = None if action.max_to is None else action.max_to.value
    sizing = tuple(sorted((option.label, option.to_amount.value) for option in action.sizing))
    return (action.kind, amount, min_to, max_to, sizing, action.is_all_in)


def _exact(truth: GameState, pred: GameState) -> bool:
    shown = {seat.seat: seat.hole_cards_shown.value for seat in truth.seats}
    return _project(truth, shown) == _project(pred, shown)


def _project(state: GameState, shown: dict[int, bool]) -> dict[str, Any]:
    seats = []
    for seat in sorted(state.seats, key=lambda item: item.seat):
        cards = [card.value for card in seat.hole_cards]
        if shown.get(seat.seat) is False:
            cards = ["hidden"] * len(cards)
        seats.append(
            {
                "seat": seat.seat,
                "name": seat.name.value,
                "position": seat.position.value,
                "stack": seat.stack.value,
                "bet": seat.bet.value,
                "hole_cards": cards,
                "status": seat.status.value,
                "is_button": seat.is_button.value,
                "is_actor": seat.is_actor.value,
                "hole_cards_shown": seat.hole_cards_shown.value,
            }
        )
    return {
        "street": state.street.value,
        "hand_phase": state.hand_phase.value,
        "board": [card.value for card in state.board],
        "button_seat": state.button_seat.value,
        "actor_seat": state.actor_seat.value,
        "small_blind": state.small_blind.value,
        "big_blind": state.big_blind.value,
        "ante": state.ante.value,
        "total_pot": state.total_pot.value,
        "pots": [
            {"amount": pot.amount.value, "eligible_seats": sorted(pot.eligible_seats)}
            for pot in state.pots
        ],
        "seats": seats,
        "legal_actions": [
            {
                "kind": action.kind,
                "amount": None if action.amount is None else action.amount.value,
                "min_to": None if action.min_to is None else action.min_to.value,
                "max_to": None if action.max_to is None else action.max_to.value,
                "is_all_in": action.is_all_in,
                "sizing": [
                    {"label": option.label, "to_amount": option.to_amount.value}
                    for option in sorted(
                        action.sizing,
                        key=lambda option: (
                            _SIZE_ORDER.index(option.label),
                            option.to_amount.value,
                        ),
                    )
                ],
            }
            for action in sorted(
                state.legal_actions, key=lambda action: _KIND_ORDER.index(action.kind)
            )
        ],
    }


def _issue_dicts(issues: tuple[ConsistencyIssue, ...]) -> list[dict[str, object]]:
    return [
        {"code": issue.code, "message": issue.message, "fields": list(issue.fields)}
        for issue in issues
    ]


def _latency(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None}
    return {
        "mean": round(sum(values) / len(values), 6),
        "p50": round(_percentile(values, 0.50), 6),
        "p95": round(_percentile(values, 0.95), 6),
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * fraction
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _table(bucket: dict[str, Any]) -> str:
    lines = [
        "| field | correct | total | accuracy |",
        "| --- | --- | --- | --- |",
    ]
    for name in (
        "cards",
        "cards_including_hidden",
        "numbers",
        "positions",
        "legal_actions",
        "full_state_exact_match",
    ):
        item = bucket[name]
        accuracy = "n/a" if item["accuracy"] is None else f"{item['accuracy'] * 100:.1f}%"
        lines.append(f"| {name} | {item['correct']} | {item['total']} | {accuracy} |")
    latency = bucket["latency_s"]
    if latency["mean"] is None:
        lines.append("")
        lines.append("Latency: n/a")
    else:
        lines.append("")
        lines.append(
            f"Frames: {bucket['frames']}. Failed reads: {bucket['failures']}. "
            f"Latency mean {latency['mean']:.3f}s, "
            f"p50 {latency['p50']:.3f}s, p95 {latency['p95']:.3f}s."
        )
    return "\n".join(lines)


class _Missing:
    pass


_missing = _Missing()
