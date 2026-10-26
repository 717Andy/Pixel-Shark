import pytest

from pixelshark_perception import GroundTruthReader, PerceptionError, VlmReader
from pixelshark_perception.backends import MockBackend
from pixelshark_sim import Table


def _state():
    return Table(seats=2, seed=1, autoplay=False).snapshot()


def test_ground_truth_reader_ignores_the_image():
    state = _state()
    assert GroundTruthReader(state).read(b"anything") is state


def test_unconfigured_mock_does_not_call_a_model(monkeypatch):
    monkeypatch.delenv("PIXELSHARK_VLM", raising=False)
    monkeypatch.delenv("PIXELSHARK_VLM_MOCK_JSON", raising=False)
    with pytest.raises(PerceptionError, match="mock"):
        VlmReader().read(b"frame")


def test_reader_repairs_a_fenced_answer_and_normalizes_ten():
    state = _state()
    payload = state.model_dump(mode="json")
    payload["source"] = "ground_truth"
    payload["street"] = "preflop"
    payload["board"] = ["10h", "AS", "2♣"]
    import json

    raw = "```json\n" + json.dumps(payload) + "\n```"
    result = VlmReader(MockBackend([raw])).read_detail(b"frame")
    assert result.attempts == 1
    assert result.state.source == "perception"
    assert result.state.schema_version == "1.0.0"
    assert [card.value for card in result.state.board] == ["Th", "As", "2c"]
    assert result.backend == "mock"


def test_reader_retries_until_the_json_validates():
    state = _state()
    backend = MockBackend(["this is not json", state.model_dump_json()])
    result = VlmReader(backend, attempts=3).read_detail(b"png")
    assert result.attempts == 2
    assert result.state.hand_id == state.hand_id
    assert "was not valid JSON" in backend.calls[1].prompt
    assert backend.calls[0].image == b"png"
    assert "schema_version" in backend.calls[0].prompt


def test_reader_gives_up_after_the_attempt_budget():
    backend = MockBackend(["nope", "still nope"])
    with pytest.raises(PerceptionError, match="2 attempt"):
        VlmReader(backend, attempts=2).read(b"frame")
    assert len(backend.calls) == 2


def test_duplicate_cards_lower_confidence_without_changing_the_code():
    state = _state()
    payload = state.model_dump(mode="json")
    payload["board"] = [
        {"value": "As", "confidence": 1},
        {"value": "Kd", "confidence": 1},
        {"value": "2c", "confidence": 1},
    ]
    payload["street"] = {"value": "flop", "confidence": 1}
    payload["seats"][0]["hole_cards"][0] = {"value": "As", "confidence": 1}
    import json

    result = VlmReader(MockBackend([json.dumps(payload)])).read_detail(b"frame")
    assert result.state.board[0].value == "As"
    assert result.state.board[0].confidence < 1
    assert result.state.seats[0].hole_cards[0].confidence < 1
    assert any(issue.code == "duplicate_cards" for issue in result.issues)
