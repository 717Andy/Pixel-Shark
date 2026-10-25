"""Versioned game-state contract shared by the table, datagen, and later models.

Schema 1.0.0 is the phase-0 ground truth. Every observed field is a small
object ``{"value": ..., "confidence": 0.0-1.0}``. The table writes confidence
1.0 because it knows the cards. A future perception model fills the same
document with lower confidence, and uses null when a card was not read.
"""

from pixelshark_schema.game_state import (
    SCHEMA_VERSION,
    ActorObs,
    BoolObs,
    CardObs,
    Decision,
    GameState,
    IntObs,
    LegalAction,
    OptIntObs,
    PhaseObs,
    PositionObs,
    PotState,
    SeatState,
    SizingOption,
    StatusObs,
    StreetObs,
    StrObs,
    TimerState,
    json_schema,
)

__all__ = [
    "SCHEMA_VERSION",
    "ActorObs",
    "BoolObs",
    "CardObs",
    "Decision",
    "GameState",
    "IntObs",
    "LegalAction",
    "OptIntObs",
    "PhaseObs",
    "PositionObs",
    "PotState",
    "SeatState",
    "SizingOption",
    "StatusObs",
    "StrObs",
    "StreetObs",
    "TimerState",
    "json_schema",
]
