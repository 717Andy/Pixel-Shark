"""Cross-check a read against itself and lower confidence when it disagrees.

The numbers are left as the model wrote them. A later step can decide what to
trust. Confidence is multiplied by 0.5 for each failed check that touches a
field, and it is not lowered below 0.05.
"""

from __future__ import annotations

from dataclasses import dataclass

from pixelshark_schema import GameState
from pixelshark_sim.positions import position_for, ring_from_button

_PENALTY = 0.5
_FLOOR = 0.05
_BOARD = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}


@dataclass(frozen=True)
class ConsistencyIssue:
    """One way the document disagrees with itself."""

    code: str
    message: str
    fields: tuple[str, ...] = ()


class _Penalties:
    def __init__(self) -> None:
        self._factors: dict[int, float] = {}
        self._objects: dict[int, object] = {}

    def add(self, obs: object) -> None:
        if obs is None or not hasattr(obs, "confidence"):
            return
        key = id(obs)
        self._factors[key] = self._factors.get(key, 1.0) * _PENALTY
        self._objects[key] = obs

    def apply(self) -> None:
        for key, factor in self._factors.items():
            obs = self._objects[key]
            current = float(obs.confidence)  # type: ignore[attr-defined]
            lowered = current * factor
            if current > 0:
                lowered = max(_FLOOR, lowered)
            obs.confidence = round(min(current, lowered), 4)  # type: ignore[attr-defined]


def check_consistency(state: GameState) -> tuple[GameState, list[ConsistencyIssue]]:
    """Return a copy with confidences lowered wherever the checks failed."""

    state = state.model_copy(deep=True)
    issues: list[ConsistencyIssue] = []
    penalties = _Penalties()
    _cards(state, issues, penalties)
    _board_street(state, issues, penalties)
    _chips(state, issues, penalties)
    _pot(state, issues, penalties)
    _button(state, issues, penalties)
    _positions(state, issues, penalties)
    _actor(state, issues, penalties)
    _legal(state, issues, penalties)
    _blinds(state, issues, penalties)
    penalties.apply()
    return state, issues


def _cards(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    seen: dict[str, list[tuple[str, object]]] = {}
    for index, card in enumerate(state.board):
        if card.value:
            seen.setdefault(card.value, []).append((f"board[{index}]", card))
    for seat in state.seats:
        if seat.status.value != "sitting_out" and len(seat.hole_cards) != 2:
            issues.append(
                ConsistencyIssue(
                    "hole_card_count",
                    f"seat {seat.seat} should have 2 hole cards, found {len(seat.hole_cards)}",
                    tuple(f"seats[{seat.seat}].hole_cards" for _ in seat.hole_cards)
                    or (f"seats[{seat.seat}].hole_cards",),
                )
            )
            for card in seat.hole_cards:
                penalties.add(card)
        for index, card in enumerate(seat.hole_cards):
            if card.value:
                seen.setdefault(card.value, []).append(
                    (f"seats[{seat.seat}].hole_cards[{index}]", card)
                )
    duplicates = {code: hits for code, hits in seen.items() if len(hits) > 1}
    for code, hits in sorted(duplicates.items()):
        for _field, obs in hits:
            penalties.add(obs)
        issues.append(
            ConsistencyIssue(
                "duplicate_cards",
                f"{code} appears {len(hits)} times",
                tuple(field for field, _obs in hits),
            )
        )


def _board_street(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    expected = _BOARD[state.street.value]
    actual = sum(1 for card in state.board if card.value)
    if len(state.board) == expected and actual == expected:
        return
    issues.append(
        ConsistencyIssue(
            "board_street",
            f"{state.street.value} should show {expected} board cards, found {actual}",
            ("street", "board"),
        )
    )
    penalties.add(state.street)
    for card in state.board:
        penalties.add(card)


def _chips(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    bad: list[str] = []
    if state.total_pot.value < 0:
        bad.append("total_pot")
        penalties.add(state.total_pot)
    for index, pot in enumerate(state.pots):
        if pot.amount.value < 0:
            bad.append(f"pots[{index}]")
            penalties.add(pot.amount)
    for seat in state.seats:
        if seat.stack.value < 0:
            bad.append(f"seats[{seat.seat}].stack")
            penalties.add(seat.stack)
        if seat.bet.value < 0:
            bad.append(f"seats[{seat.seat}].bet")
            penalties.add(seat.bet)
    if bad:
        issues.append(ConsistencyIssue("negative_chips", "a chip count is negative", tuple(bad)))


def _pot(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    """The middle number has to account for the bets.

    On this table the pot total already includes live bets, and the pot rows
    sum to that total. A reader that instead reports the collected pot plus
    the bets as the total is also accepted. Anything else is a disagreement.
    """

    pot_sum = sum(pot.amount.value for pot in state.pots)
    bet_sum = sum(seat.bet.value for seat in state.seats)
    total = state.total_pot.value
    if bet_sum <= total and (pot_sum == total or pot_sum + bet_sum == total):
        return
    issues.append(
        ConsistencyIssue(
            "pot_mismatch",
            f"total pot {total} does not match pot rows {pot_sum} and bets {bet_sum}",
            ("total_pot", "pots", "bets"),
        )
    )
    penalties.add(state.total_pot)
    for pot in state.pots:
        penalties.add(pot.amount)
    for seat in state.seats:
        penalties.add(seat.bet)


def _button(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    marked = [seat for seat in state.seats if seat.is_button.value]
    owners = [seat for seat in state.seats if seat.seat == state.button_seat.value]
    if len(marked) == 1 and owners and marked[0].seat == state.button_seat.value:
        return
    issues.append(
        ConsistencyIssue(
            "button_mismatch",
            "the button seat and the dealer flags do not name the same seat",
            ("button_seat", "is_button"),
        )
    )
    penalties.add(state.button_seat)
    for seat in state.seats:
        penalties.add(seat.is_button)


def _positions(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    indexes = [seat.seat for seat in state.seats]
    if sorted(indexes) != list(range(len(state.seats))):
        issues.append(
            ConsistencyIssue(
                "position_mismatch",
                "seat numbers are not a full table from 0, so positions were not checked",
                tuple(f"seats[{seat.seat}].position" for seat in state.seats),
            )
        )
        for seat in state.seats:
            penalties.add(seat.position)
        return
    active = {seat.seat for seat in state.seats if seat.status.value != "sitting_out"}
    if len(active) < 2:
        return
    try:
        ring = ring_from_button(len(state.seats), state.button_seat.value, active)
    except ValueError:
        issues.append(
            ConsistencyIssue(
                "position_mismatch",
                "the button is not on a seated player, so positions were not checked",
                ("button_seat",),
            )
        )
        return
    bad: list[str] = []
    for seat in state.seats:
        expected = None if seat.seat not in active else position_for(ring, seat.seat)
        if seat.position.value != expected:
            bad.append(f"seats[{seat.seat}].position")
            penalties.add(seat.position)
    if bad:
        issues.append(
            ConsistencyIssue(
                "position_mismatch",
                "one or more position names do not match the button",
                tuple(bad),
            )
        )


def _actor(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    marked = [seat for seat in state.seats if seat.is_actor.value]
    actor = state.actor_seat.value
    if state.hand_phase.value != "betting":
        if actor is not None or marked:
            issues.append(
                ConsistencyIssue(
                    "actor_mismatch",
                    "nobody should be to act when the hand is not in a betting phase",
                    ("actor_seat", "hand_phase"),
                )
            )
            penalties.add(state.actor_seat)
            penalties.add(state.hand_phase)
            for seat in marked:
                penalties.add(seat.is_actor)
        return
    if actor is None or len(marked) != 1 or marked[0].seat != actor:
        issues.append(
            ConsistencyIssue(
                "actor_mismatch",
                "the actor seat and the highlighted-seat flags do not agree",
                ("actor_seat", "is_actor"),
            )
        )
        penalties.add(state.actor_seat)
        for seat in state.seats:
            penalties.add(seat.is_actor)


def _legal(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    actions = state.legal_actions
    if state.hand_phase.value != "betting" or state.actor_seat.value is None:
        if actions:
            issues.append(
                ConsistencyIssue(
                    "legal_idle",
                    "legal actions are listed when nobody is betting",
                    ("legal_actions",),
                )
            )
            for action in actions:
                penalties.add(action)
        return
    kinds = [action.kind for action in actions]
    kindset = set(kinds)
    problems: list[str] = []
    if len(kinds) != len(kindset):
        problems.append("the same action kind is listed twice")
    if "check" in kindset and "call" in kindset:
        problems.append("check and call are both listed")
    if "bet" in kindset and "raise" in kindset:
        problems.append("bet and raise are both listed")
    actor = next((seat for seat in state.seats if seat.seat == state.actor_seat.value), None)
    if actor is None:
        problems.append("the actor is not one of the seats")
    else:
        to_call = max(0, max(seat.bet.value for seat in state.seats) - actor.bet.value)
        if to_call == 0:
            if "call" in kindset or "fold" in kindset or "raise" in kindset:
                problems.append("a free check is mixed with call, fold, or raise")
            if "check" not in kindset:
                problems.append("the actor can check but check is missing")
        else:
            if "check" in kindset or "bet" in kindset:
                problems.append("the actor faces a bet but check or bet is listed")
            if "fold" not in kindset or "call" not in kindset:
                problems.append("facing a bet requires fold and call")
            call = next((action for action in actions if action.kind == "call"), None)
            amount = None if call is None or call.amount is None else call.amount.value
            if amount != to_call:
                problems.append(f"call amount {amount} does not match the bets ({to_call})")
                if call is not None and call.amount is not None:
                    penalties.add(call.amount)
                for seat in state.seats:
                    penalties.add(seat.bet)
    for action in actions:
        if (
            action.min_to is not None
            and action.max_to is not None
            and action.min_to.value > action.max_to.value
        ):
            problems.append(f"{action.kind} min is above max")
            penalties.add(action.min_to)
            penalties.add(action.max_to)
        for option in action.sizing:
            amount = option.to_amount.value
            if action.min_to is not None and amount < action.min_to.value:
                problems.append(f"{option.label} is below the minimum")
                penalties.add(option.to_amount)
            if action.max_to is not None and amount > action.max_to.value:
                problems.append(f"{option.label} is above the maximum")
                penalties.add(option.to_amount)
    if not problems:
        return
    issues.append(ConsistencyIssue("legal_actions", "; ".join(problems), ("legal_actions",)))
    for action in actions:
        penalties.add(action)


def _blinds(state: GameState, issues: list[ConsistencyIssue], penalties: _Penalties) -> None:
    if (
        state.small_blind.value > 0
        and state.big_blind.value >= state.small_blind.value
        and state.ante.value >= 0
    ):
        return
    issues.append(
        ConsistencyIssue(
            "blind_order",
            "blinds must be positive and the big blind must be at least the small blind",
            ("small_blind", "big_blind", "ante"),
        )
    )
    penalties.add(state.small_blind)
    penalties.add(state.big_blind)
    penalties.add(state.ante)
