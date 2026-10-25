"""The checked-in sample set is part of the phase-0 deliverable."""

import json
import struct
from pathlib import Path

from pixelshark_schema import GameState

_ROOT = Path(__file__).resolve().parents[3] / "examples" / "sample"


def _png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_example_dataset_matches_the_schema():
    manifest = json.loads((_ROOT / "manifest.json").read_text())
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["count"] >= 3
    skins = set()
    viewports = set()
    for sample in manifest["samples"]:
        folder = _ROOT / sample["id"]
        state = GameState.model_validate_json((folder / "state.json").read_text())
        assert state.source == "ground_truth"
        assert state.variant == "NLHE"
        assert state.street.value == sample["street"]
        boxes = json.loads((folder / "boxes.json").read_text())
        labels = {box["label"] for box in boxes["boxes"]}
        assert {"card", "chips", "button"} <= labels
        width, height = _png_size((folder / "frame.png").read_bytes())
        assert [width, height] == sample["viewport"]
        assert boxes["width"] == width and boxes["height"] == height
        skins.add(sample["skin"])
        viewports.add(tuple(sample["viewport"]))
    assert {"felt", "midnight", "broadcast"} <= skins
    assert len(viewports) >= 3
