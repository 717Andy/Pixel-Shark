import pytest

from pixelshark_perception.errors import PerceptionError
from pixelshark_perception.repair import extract_json_object, normalize_card, repair_document
from pixelshark_schema import GameState
from pixelshark_sim import Table


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("As", "As"),
        ("as", "As"),
        ("10h", "Th"),
        ("10H", "Th"),
        ("A♠", "As"),
        ("A♥", "Ah"),
        ("ace of spades", "As"),
        ("ten of hearts", "Th"),
        ("??", None),
        (None, None),
        ("back", None),
    ],
)
def test_card_normalization(raw, code):
    assert normalize_card(raw) == code


def test_extracts_json_from_prose():
    payload = extract_json_object('Sure.\n{"street": "flop", "board": []}\nThanks.')
    assert payload["street"] == "flop"


def test_unwraps_a_nested_state():
    payload = extract_json_object('{"game_state": {"street": "turn", "seats": []}}')
    assert payload["street"] == "turn"


def test_repair_round_trip_keeps_the_values():
    state = Table(seats=6, seed=4, autoplay=False).snapshot()
    repaired = GameState.model_validate(repair_document(state.model_dump(mode="json")))
    assert repaired.source == "perception"
    assert repaired.street.value == state.street.value
    assert [card.value for card in repaired.board] == [card.value for card in state.board]
    assert repaired.total_pot.value == state.total_pot.value
    assert [(seat.seat, seat.stack.value, seat.bet.value) for seat in repaired.seats] == [
        (seat.seat, seat.stack.value, seat.bet.value) for seat in state.seats
    ]
    assert [action.kind for action in repaired.legal_actions] == [
        action.kind for action in state.legal_actions
    ]


def test_bare_values_are_wrapped():
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    payload = state.model_dump(mode="json")
    payload["total_pot"] = "1,500"
    payload["street"] = "Flop"
    payload["hand_phase"] = "betting"
    repaired = repair_document(payload)
    assert repaired["total_pot"] == {"value": 1500, "confidence": 0.8}
    assert repaired["street"]["value"] == "flop"


def test_missing_json_object_is_an_error():
    with pytest.raises(PerceptionError):
        extract_json_object("no braces here")
