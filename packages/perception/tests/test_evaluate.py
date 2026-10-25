import json
from pathlib import Path

from pixelshark_perception.backends import MockBackend, OracleBackend
from pixelshark_perception.evaluate import evaluate_dataset, load_dataset
from pixelshark_perception.reader import VlmReader
from pixelshark_schema import GameState
from pixelshark_sim import Table

_SAMPLE = Path(__file__).resolve().parents[3] / "examples" / "sample"


def _write_sample(folder: Path, state: GameState, skin: str, image: bytes) -> None:
    folder.mkdir(parents=True)
    (folder / "frame.png").write_bytes(image)
    (folder / "state.json").write_text(state.model_dump_json(indent=2) + "\n")
    (folder / "meta.json").write_text(json.dumps({"id": folder.name, "skin": skin}) + "\n")


def test_oracle_scores_the_checked_in_sample_as_perfect(tmp_path):
    report = evaluate_dataset(
        _SAMPLE,
        OracleBackend(),
        holdout_skin="linen",
        out=tmp_path / "report",
    )
    assert report["backend"] == "oracle"
    assert report["frames"] == 4
    assert report["overall"]["full_state_exact_match"]["accuracy"] == 1
    assert report["overall"]["cards"]["accuracy"] == 1
    assert report["overall"]["numbers"]["accuracy"] == 1
    assert report["overall"]["positions"]["accuracy"] == 1
    assert report["overall"]["legal_actions"]["accuracy"] == 1
    assert report["holdout"]["frames"] == 0
    assert report["seen_skins"]["frames"] == 4
    assert set(report["by_skin"]) == {"felt", "midnight", "broadcast"}
    assert all(frame["issues"] == [] and frame["failure"] is None for frame in report["samples"])
    assert (tmp_path / "report" / "report.json").exists()
    markdown = (tmp_path / "report" / "report.md").read_text()
    assert "Held-out skin" in markdown
    assert "linen" in markdown
    assert "100.0%" in markdown
    latency = report["overall"]["latency_s"]
    assert latency["mean"] >= 0
    assert latency["p50"] is not None and latency["p95"] is not None


def test_holdout_skin_is_scored_apart_from_the_others(tmp_path):
    felt = Table(seats=2, seed=1, autoplay=False, hero_seat=0, reveal="showdown").snapshot()
    linen = Table(seats=2, seed=5, autoplay=False, hero_seat=0, reveal="all").snapshot()
    root = tmp_path / "data"
    _write_sample(root / "0000", felt, "felt", b"felt-bytes")
    _write_sample(root / "0001", linen, "linen", b"linen-bytes")
    wrong = linen.model_dump(mode="json")
    wrong["street"] = {
        "value": "river" if linen.street.value != "river" else "flop",
        "confidence": 0.9,
    }
    wrong["board"] = [{"value": "As", "confidence": 0.9}]

    def respond(request):
        if request.image == b"felt-bytes":
            return felt.model_dump_json()
        return json.dumps(wrong)

    log_dir = tmp_path / "log"
    report = evaluate_dataset(
        root,
        MockBackend(respond),
        holdout_skin="linen",
        out=tmp_path / "out",
        log_dir=log_dir,
    )
    assert report["by_skin"]["felt"]["full_state_exact_match"]["accuracy"] == 1
    assert report["by_skin"]["linen"]["full_state_exact_match"]["accuracy"] == 0
    assert report["seen_skins"]["full_state_exact_match"]["accuracy"] == 1
    assert report["holdout"]["full_state_exact_match"]["accuracy"] == 0
    assert report["by_skin"]["linen"]["cards"]["accuracy"] < 1
    assert (log_dir / "manifest.jsonl").exists()
    assert (log_dir / "frames" / "0000.png").read_bytes() == b"felt-bytes"
    assert (log_dir / "reads" / "0001.json").exists()
    assert (log_dir / "truth" / "0001.json").exists()


def test_hidden_hole_cards_do_not_decide_the_visible_card_score(tmp_path):
    state = Table(seats=2, seed=1, autoplay=False, hero_seat=0, reveal="showdown").snapshot()
    hidden = next(seat for seat in state.seats if not seat.hole_cards_shown.value)
    root = tmp_path / "data"
    _write_sample(root / "0000", state, "felt", b"frame")
    payload = state.model_dump(mode="json")
    for seat in payload["seats"]:
        if seat["seat"] == hidden.seat:
            seat["hole_cards"] = [
                {"value": "2c", "confidence": 0.4},
                {"value": "3d", "confidence": 0.4},
            ]
    report = evaluate_dataset(root, MockBackend([json.dumps(payload)]), holdout_skin="linen")
    assert report["overall"]["full_state_exact_match"]["accuracy"] == 1
    assert report["overall"]["cards"]["accuracy"] == 1
    assert report["overall"]["cards_including_hidden"]["accuracy"] < 1


def test_a_failed_read_counts_as_a_miss(tmp_path):
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    root = tmp_path / "data"
    _write_sample(root / "0000", state, "felt", b"frame")
    report = evaluate_dataset(root, MockBackend(["nope"]), holdout_skin="linen", attempts=1)
    assert report["samples"][0]["failure"]
    assert report["overall"]["full_state_exact_match"]["accuracy"] == 0
    assert report["overall"]["numbers"]["accuracy"] == 0


def test_load_dataset_without_a_manifest(tmp_path):
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    _write_sample(tmp_path / "0002", state, "broadcast", b"x")
    samples = load_dataset(tmp_path)
    assert [sample.sample_id for sample in samples] == ["0002"]
    assert samples[0].skin == "broadcast"
    assert samples[0].truth.hand_id == state.hand_id


def test_reader_protocol_is_what_the_harness_calls():
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    assert (
        VlmReader(MockBackend([state.model_dump_json()])).read(b"x").street.value
        == state.street.value
    )
