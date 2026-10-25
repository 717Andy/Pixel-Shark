"""Save model reads next to the frames, for a later per-skin detector.

The directory is the training set the next phase will consume. This phase only
writes it and can list it back. Nothing here trains a model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pixelshark_perception.reader import PerceptionResult
from pixelshark_schema import GameState


@dataclass(frozen=True)
class LoggedRead:
    """One row of ``manifest.jsonl``."""

    sample_id: str
    image_path: Path
    state_path: Path
    skin: str


class ReadLog:
    """Append-only log of frames and the JSON the reader returned."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.frames = directory / "frames"
        self.reads = directory / "reads"
        self.truth = directory / "truth"
        self.frames.mkdir(parents=True, exist_ok=True)
        self.reads.mkdir(parents=True, exist_ok=True)
        self.truth.mkdir(parents=True, exist_ok=True)
        self._manifest = directory / "manifest.jsonl"
        self._index = _next_index(self._manifest)

    def write(
        self,
        *,
        image: bytes,
        state: GameState,
        raw: str,
        issues: list[dict[str, object]],
        backend: str,
        attempts: int,
        latency_s: float,
        sample_id: str | None = None,
        skin: str | None = None,
        truth: GameState | None = None,
    ) -> Path:
        """Store one successful read. Returns the path of the JSON record."""

        label = sample_id if sample_id is not None else f"{self._index:04d}"
        self._index += 1
        suffix = ".jpg" if image.startswith(b"\xff\xd8") else ".png"
        frame_path = self.frames / f"{label}{suffix}"
        read_path = self.reads / f"{label}.json"
        frame_path.write_bytes(image)
        record = {
            "sample_id": label,
            "skin": skin,
            "backend": backend,
            "attempts": attempts,
            "latency_s": round(latency_s, 6),
            "issues": issues,
            "raw": raw,
            "state": state.model_dump(mode="json"),
            "frame": str(frame_path.relative_to(self.directory)),
        }
        if truth is not None:
            truth_path = self.truth / f"{label}.json"
            truth_path.write_text(json.dumps(truth.model_dump(mode="json"), indent=2) + "\n")
            record["truth"] = str(truth_path.relative_to(self.directory))
        read_path.write_text(json.dumps(record, indent=2) + "\n")
        row = {
            "sample_id": label,
            "skin": skin or "unknown",
            "frame": record["frame"],
            "state": str(read_path.relative_to(self.directory)),
        }
        with self._manifest.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        return read_path


def write_result(
    log: ReadLog,
    result: PerceptionResult,
    *,
    sample_id: str | None = None,
    skin: str | None = None,
    truth: GameState | None = None,
) -> Path:
    """Store one read next to the frame that produced it."""

    issues = [
        {"code": issue.code, "message": issue.message, "fields": list(issue.fields)}
        for issue in result.issues
    ]
    return log.write(
        image=result.image,
        state=result.state,
        raw=result.raw,
        issues=issues,
        backend=result.backend,
        attempts=result.attempts,
        latency_s=result.latency_s,
        sample_id=sample_id,
        skin=skin,
        truth=truth,
    )


def load_log(directory: Path) -> list[LoggedRead]:
    """List the frames in a read log. Missing files are skipped."""

    manifest = directory / "manifest.jsonl"
    if not manifest.exists():
        return []
    rows: list[LoggedRead] = []
    for line in manifest.read_text().splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        image_path = directory / item["frame"]
        state_path = directory / item["state"]
        if not image_path.exists() or not state_path.exists():
            continue
        rows.append(
            LoggedRead(
                sample_id=str(item["sample_id"]),
                image_path=image_path,
                state_path=state_path,
                skin=str(item.get("skin") or "unknown"),
            )
        )
    return rows


def _next_index(manifest: Path) -> int:
    if not manifest.exists():
        return 0
    count = 0
    for line in manifest.read_text().splitlines():
        if line.strip():
            count += 1
    return count
