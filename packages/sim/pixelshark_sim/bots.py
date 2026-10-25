"""Policies that can play a seat without a model.

``ScriptedPolicy`` is intentionally simple: it continues more often when a call
is cheap and bets the pot a minority of the time. It exists so a table can run
unattended. It is not a poker strategy. The later CFR / OpenSpiel work replaces
it behind the same :class:`pixelshark_schema.Decision` shape.
"""

from __future__ import annotations

import random
from typing import Protocol

from pixelshark_schema import Decision, GameState, LegalAction

_EARLY = {"UTG", "UTG+1", "MP"}


class Policy(Protocol):
    def choose(self, state: GameState, rng: random.Random) -> Decision:
        """Pick one legal action. Implementations must not mutate ``state``."""


def make_policy(name: str) -> Policy:
    if name == "scripted":
        return ScriptedPolicy()
    if name == "random":
        return RandomPolicy()
    raise ValueError(f"unknown bot policy {name!r}; use 'scripted' or 'random'")


class RandomPolicy:
    """Uniform over fold / check / call and each listed bet size."""

    def choose(self, state: GameState, rng: random.Random) -> Decision:
        options = _choices(state)
        if not options:
            raise RuntimeError("no legal action to randomize")
        return rng.choice(options)


class ScriptedPolicy:
    """A passive baseline. Checks a lot, calls small bets, raises sometimes."""

    def choose(self, state: GameState, rng: random.Random) -> Decision:
        by_kind = {action.kind: action for action in state.legal_actions}
        actor = state.actor_seat.value
        position = None
        if actor is not None:
            for seat in state.seats:
                if seat.seat == actor:
                    position = seat.position.value
                    break
        tight = position in _EARLY and state.street.value == "preflop"

        if "check" in by_kind and "bet" in by_kind:
            if rng.random() < (0.78 if tight else 0.62):
                return Decision(kind="check")
            return Decision(kind="bet", to_amount=_size(by_kind["bet"], "1/2 pot"))

        if "check" in by_kind:
            return Decision(kind="check")

        if "call" in by_kind:
            call = by_kind["call"].amount.value if by_kind["call"].amount else 0
            price = call / max(state.total_pot.value, 1)
            fold_p = min(0.85, 0.12 + 0.55 * price + (0.12 if tight else 0.0))
            roll = rng.random()
            if roll < fold_p and "fold" in by_kind:
                return Decision(kind="fold")
            if roll > 0.88 and "raise" in by_kind:
                return Decision(kind="raise", to_amount=_size(by_kind["raise"], "2/3 pot"))
            return Decision(kind="call")

        if "fold" in by_kind:
            return Decision(kind="fold")
        if "bet" in by_kind:
            return Decision(kind="bet", to_amount=_size(by_kind["bet"], "min"))
        if "raise" in by_kind:
            return Decision(kind="raise", to_amount=_size(by_kind["raise"], "min"))
        raise RuntimeError("scripted policy found no legal action")


def _choices(state: GameState) -> list[Decision]:
    found: list[Decision] = []
    for action in state.legal_actions:
        if action.kind in ("fold", "check", "call"):
            found.append(Decision(kind=action.kind))
            continue
        if action.sizing:
            for option in action.sizing:
                found.append(Decision(kind=action.kind, to_amount=option.to_amount.value))
        elif action.min_to is not None:
            found.append(Decision(kind=action.kind, to_amount=action.min_to.value))
    return found


def _size(action: LegalAction, prefer: str) -> int:
    for option in action.sizing:
        if option.label == prefer:
            return option.to_amount.value
    if action.sizing:
        return action.sizing[0].to_amount.value
    if action.min_to is not None:
        return action.min_to.value
    raise RuntimeError(f"{action.kind} has no amount")
