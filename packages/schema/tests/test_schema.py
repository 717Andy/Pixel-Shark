import json
from pathlib import Path

import pytest

from pixelshark_schema import SCHEMA_VERSION, CardObs, Decision, GameState, json_schema

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "pixelshark_schema" / "game_state.schema.json"


def test_card_codes():
    assert CardObs(value="Td").value == "Td"
    assert CardObs(value=None).value is None
    with pytest.raises(ValueError):
        CardObs(value="10h")
    with pytest.raises(ValueError):
        CardObs(value="Asx")


def test_decision_raise_to_is_optional_on_a_fold():
    assert Decision(kind="fold").to_amount is None
    assert Decision(kind="raise", to_amount=300).to_amount == 300


def test_checked_in_schema_matches_the_model():
    document = json.loads(_SCHEMA_PATH.read_text())
    live = json_schema()
    assert document == live
    assert document["$id"] == "urn:pixelshark:game-state:1.0.0"
    assert document["$schema"].startswith("https://json-schema.org/draft/2020-12/")
    seat_ref = document["$defs"]["SeatState"]
    props = document["properties"]
    for name in (
        "schema_version",
        "board",
        "pots",
        "total_pot",
        "seats",
        "button_seat",
        "street",
        "legal_actions",
        "timers",
        "actor_seat",
    ):
        assert name in props
    seat_props = seat_ref["properties"]
    for name in ("hole_cards", "stack", "bet", "position", "status"):
        assert name in seat_props
    assert props["schema_version"]["const"] == SCHEMA_VERSION


def test_confidence_bounds():
    with pytest.raises(ValueError):
        CardObs(value="As", confidence=1.5)


def test_game_state_rejects_one_seat():
    with pytest.raises(ValueError):
        GameState.model_validate(
            {
                "table_id": "t",
                "hand_id": "t-h1",
                "hand_number": {"value": 1},
                "small_blind": {"value": 50},
                "big_blind": {"value": 100},
                "ante": {"value": 0},
                "button_seat": {"value": 0},
                "street": {"value": "preflop"},
                "hand_phase": {"value": "betting"},
                "total_pot": {"value": 0},
                "actor_seat": {"value": None},
                "timers": {
                    "shot_clock_ms": {"value": 1000},
                    "remaining_ms": {"value": None},
                    "deadline_unix_ms": {"value": None},
                },
                "seats": [],
            }
        )
