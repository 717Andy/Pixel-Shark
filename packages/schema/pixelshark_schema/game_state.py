"""Pydantic model for one moment at a no-limit hold'em table.

Card codes are two characters: rank then suit. Rank is ``2-9``, ``T``, ``J``,
``Q``, ``K``, or ``A``. Suit is ``c``, ``d``, ``h``, or ``s``. Ten is ``T``,
not ``10`` — the browser displays it as 10.

``to_amount`` on a bet or raise is the seat's total commitment on this street
("raise to 300"), not the extra chips being added.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

CARD_RE = re.compile(r"^[2-9TJQKA][cdhs]$")

PositionName = Literal["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "LJ", "HJ", "CO"]
SeatStatusName = Literal["active", "folded", "all_in", "sitting_out"]
StreetName = Literal["preflop", "flop", "turn", "river"]
PhaseName = Literal["betting", "complete"]
ActionKind = Literal["fold", "check", "call", "bet", "raise"]
SizingLabel = Literal["min", "1/3 pot", "1/2 pot", "2/3 pot", "pot", "all-in"]
RevealMode = Literal["all", "hero", "showdown"]
StateSource = Literal["ground_truth", "perception", "tracker"]


def _confidence() -> Any:
    return Field(default=1.0, ge=0.0, le=1.0)


class IntObs(BaseModel):
    """An integer the observer claims to have read."""

    value: int
    confidence: float = _confidence()


class OptIntObs(BaseModel):
    """An integer that may be unknown. ``value: null`` means "not applicable"."""

    value: int | None = None
    confidence: float = _confidence()


class StrObs(BaseModel):
    value: str
    confidence: float = _confidence()


class BoolObs(BaseModel):
    value: bool
    confidence: float = _confidence()


class CardObs(BaseModel):
    """One card. ``value`` is null when the observer did not read it."""

    value: str | None = Field(
        default=None,
        description="Card code such as As, Td, 9h, 2c. Null if unknown.",
    )
    confidence: float = _confidence()

    @field_validator("value")
    @classmethod
    def _check_code(cls, value: str | None) -> str | None:
        if value is not None and CARD_RE.fullmatch(value) is None:
            raise ValueError(f"card must look like As or Td, got {value!r}")
        return value


class ActorObs(BaseModel):
    """Seat index of the player to act, or null when nobody is acting."""

    value: int | None = None
    confidence: float = _confidence()

    @field_validator("value")
    @classmethod
    def _seat(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 8:
            raise ValueError("actor seat must be from 0 to 8")
        return value


class StreetObs(BaseModel):
    value: StreetName
    confidence: float = _confidence()


class PhaseObs(BaseModel):
    value: PhaseName
    confidence: float = _confidence()


class StatusObs(BaseModel):
    value: SeatStatusName
    confidence: float = _confidence()


class PositionObs(BaseModel):
    """Position name, or null when the seat is sitting out."""

    value: PositionName | None = None
    confidence: float = _confidence()


class SizingOption(BaseModel):
    """One suggested bet size. ``to_amount`` is the street total, not the increment."""

    label: SizingLabel
    to_amount: IntObs


class LegalAction(BaseModel):
    """An action the current actor is allowed to take.

    For ``call``, ``amount`` is the extra chips required (0 is not used; a free
    response is ``check``). For ``bet`` and ``raise``, ``min_to`` and ``max_to``
    bound the street total and ``sizing`` lists concrete buttons inside that range.
    """

    kind: ActionKind
    amount: IntObs | None = None
    min_to: IntObs | None = None
    max_to: IntObs | None = None
    sizing: list[SizingOption] = Field(default_factory=list)
    is_all_in: bool = False
    confidence: float = _confidence()


class PotState(BaseModel):
    """One collected pot. Side pots are separate entries."""

    amount: IntObs
    eligible_seats: list[int] = Field(
        description="Seats entitled to win this pot, in ascending seat order.",
    )


class SeatState(BaseModel):
    seat: int = Field(ge=0, le=8)
    name: StrObs
    position: PositionObs
    stack: IntObs = Field(description="Chips behind, not counting the current bet.")
    bet: IntObs = Field(description="Chips committed in front of the seat this street.")
    hole_cards: list[CardObs] = Field(
        description=(
            "Private cards. Ground truth always includes the real codes. "
            "hole_cards_shown says whether the table is drawing the faces."
        ),
    )
    status: StatusObs
    is_button: BoolObs
    is_actor: BoolObs
    hole_cards_shown: BoolObs
    payoff: OptIntObs = Field(
        description="Net chips for this hand. Null until the hand is complete.",
    )


class TimerState(BaseModel):
    """Shot clock for the current actor. Remaining is null when nobody is acting."""

    shot_clock_ms: IntObs
    remaining_ms: OptIntObs
    deadline_unix_ms: OptIntObs


class Decision(BaseModel):
    """A chosen action, separate from the list of legal ones.

    ``to_amount`` is required for ``bet`` and ``raise``. It is the total chips
    this seat will have in front of them on this street.
    """

    kind: ActionKind
    to_amount: int | None = None


class GameState(BaseModel):
    """One labeled moment. This is the document the table emits and models will emit.

    Configuration fields (``hero_seat``, ``reveal``, ``autoplay``, ``last_action``)
    describe the research table. They are not things a vision model is expected
    to read off the felt. Observation fields carry their own confidence.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    source: StateSource = "ground_truth"
    table_id: str
    hand_id: str
    hand_number: IntObs
    variant: Literal["NLHE"] = "NLHE"
    small_blind: IntObs
    big_blind: IntObs
    ante: IntObs
    button_seat: IntObs
    street: StreetObs
    hand_phase: PhaseObs
    board: list[CardObs]
    pots: list[PotState]
    total_pot: IntObs = Field(
        description="All chips in the middle plus outstanding bets, before the hand is awarded.",
    )
    seats: list[SeatState]
    actor_seat: ActorObs
    legal_actions: list[LegalAction]
    timers: TimerState
    hero_seat: int | None = Field(
        default=None,
        description="Seat a human is playing. Null when every seat is a bot.",
    )
    reveal: RevealMode = "showdown"
    autoplay: bool = False
    last_action: str | None = None

    @field_validator("hero_seat")
    @classmethod
    def _hero(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 8:
            raise ValueError("hero seat must be from 0 to 8")
        return value

    @field_validator("seats")
    @classmethod
    def _seat_count(cls, seats: list[SeatState]) -> list[SeatState]:
        indexes = [seat.seat for seat in seats]
        if len(indexes) != len(set(indexes)):
            raise ValueError("duplicate seat indexes")
        if not 2 <= len(seats) <= 9:
            raise ValueError("a table has 2 to 9 seats")
        return seats


def json_schema() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) for :class:`GameState`."""

    schema = GameState.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:pixelshark:game-state:1.0.0"
    return schema
