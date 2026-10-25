"""One cash-style no-limit hold'em table.

Chip push and pull are done by hand, after the pot list is recorded. PokerKit's
automatic payout clears that list inside the same call, which would hide side
pots from the snapshot. Blinds, burns, showdown, and bet collection stay
automatic.

The deck is reshuffled with a :class:`random.Random` seeded per hand. PokerKit
shuffles with the global ``random`` module; replacing ``deck_cards`` keeps a
table seed from depending on other libraries.
"""

from __future__ import annotations

import random
from collections import deque
from typing import Literal

from pokerkit import Automation, Deck, Mode, NoLimitTexasHoldem
from pokerkit.state import State

from pixelshark_schema import (
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
)
from pixelshark_sim.bots import Policy, make_policy
from pixelshark_sim.cards import card_code
from pixelshark_sim.clock import Clock, WallClock
from pixelshark_sim.errors import HumanToAct, IllegalAction, TableConfigError
from pixelshark_sim.positions import pokerkit_order, position_for, ring_from_button

# Payout is manual so snapshots can still see pots. See the module docstring.
_AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.CARD_BURNING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
)

_SIZES: tuple[tuple[str, float | None], ...] = (
    ("min", None),
    ("1/3 pot", 1 / 3),
    ("1/2 pot", 1 / 2),
    ("2/3 pot", 2 / 3),
    ("pot", 1.0),
    ("all-in", None),
)

Reveal = Literal["all", "hero", "showdown"]


class Table:
    """A 2-9 seat no-limit hold'em table with stable seat numbers."""

    def __init__(
        self,
        *,
        table_id: str = "table",
        seats: int = 6,
        stacks: int | list[int] = 10_000,
        small_blind: int = 50,
        big_blind: int = 100,
        ante: int = 0,
        button_seat: int = 0,
        hero_seat: int | None = None,
        bot_seats: set[int] | list[int] | None = None,
        bot_policy: str = "scripted",
        seed: int = 0,
        reveal: Reveal = "showdown",
        autoplay: bool = False,
        shot_clock_ms: int = 20_000,
        rebuy: bool = True,
        clock: Clock | None = None,
    ) -> None:
        if not 2 <= seats <= 9:
            raise TableConfigError("a table has 2 to 9 seats")
        if small_blind <= 0 or big_blind < small_blind:
            raise TableConfigError("blinds must be positive and the big blind >= the small blind")
        if ante < 0:
            raise TableConfigError("ante cannot be negative")
        if not 0 <= button_seat < seats:
            raise TableConfigError("button seat is off the table")
        if hero_seat is not None and not 0 <= hero_seat < seats:
            raise TableConfigError("hero seat is off the table")
        if reveal not in ("all", "hero", "showdown"):
            raise TableConfigError("reveal must be all, hero, or showdown")

        self.table_id = table_id
        self.seat_count = seats
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.ante = ante
        self.button = button_seat
        self.hero_seat = hero_seat
        self.reveal: Reveal = reveal
        self.autoplay = autoplay
        self.shot_clock_ms = shot_clock_ms
        self.rebuy = rebuy
        self.seed = seed
        self.clock = clock or WallClock()
        self.policy: Policy = make_policy(bot_policy)
        self.policy_rng = random.Random(seed)

        if isinstance(stacks, int):
            if stacks <= 0:
                raise TableConfigError("starting stack must be positive")
            self.starting_stacks = [stacks] * seats
        else:
            if len(stacks) != seats:
                raise TableConfigError("stacks must provide one value per seat")
            if any(stack < 0 for stack in stacks):
                raise TableConfigError("stacks cannot be negative")
            self.starting_stacks = list(stacks)
        self.stacks = list(self.starting_stacks)

        if bot_seats is None:
            self.bot_seats = {seat for seat in range(seats) if seat != hero_seat}
        else:
            self.bot_seats = set(bot_seats)
        if any(seat < 0 or seat >= seats for seat in self.bot_seats):
            raise TableConfigError("a bot seat is off the table")
        if hero_seat is not None and hero_seat in self.bot_seats:
            raise TableConfigError("the hero seat cannot also be a bot")

        self.hand_number = 0
        self.hand_button = button_seat
        self.state: State | None = None
        self.pk_to_seat: list[int] = []
        self.seat_to_pk: dict[int, int] = {}
        self.ring: list[int] = []
        self.folded: set[int] = set()
        self.known_holes: dict[int, list[str]] = {}
        self.last_action = "Table open."
        self._last_street = "preflop"
        self._last_total = 0
        self._last_pots: list[tuple[int, list[int]]] = []
        self._timed_actor: int | None = None
        self._deadline_unix_ms: int | None = None
        self.start_hand()

    @property
    def betting(self) -> bool:
        return self.state is not None and bool(self.state.status)

    def start_hand(self) -> GameState:
        """Deal the next hand. The button moves after the first hand."""

        if self.betting:
            raise IllegalAction("the current hand is still in progress")
        if self.hand_number > 0:
            self.button = (self.button + 1) % self.seat_count
        if self.rebuy:
            for seat, target in enumerate(self.starting_stacks):
                if self.stacks[seat] <= 0 and target > 0:
                    self.stacks[seat] = target

        active = {seat for seat, stack in enumerate(self.stacks) if stack > 0}
        if len(active) < 2:
            raise TableConfigError("need at least two seats with chips to deal")

        self.hand_number += 1
        self.ring = ring_from_button(self.seat_count, self.button, active)
        self.hand_button = self.ring[0]
        self.pk_to_seat = pokerkit_order(self.ring)
        self.seat_to_pk = {seat: index for index, seat in enumerate(self.pk_to_seat)}
        self.folded = set()
        self.known_holes = {}
        self._timed_actor = None
        self._deadline_unix_ms = None
        self._last_total = 0
        self._last_pots = []

        self.state = NoLimitTexasHoldem.create_state(
            _AUTOMATIONS,
            True,
            self.ante,
            (self.small_blind, self.big_blind),
            self.big_blind,
            [self.stacks[seat] for seat in self.pk_to_seat],
            len(self.pk_to_seat),
            mode=Mode.TOURNAMENT,
        )
        self._install_deck()
        self._normalize()
        self.last_action = (
            f"Hand {self.hand_number} started. Blinds {self.small_blind}/{self.big_blind}."
        )
        return self.snapshot()

    def apply(self, seat: int, decision: Decision) -> GameState:
        """Apply one action for ``seat``. Raises :class:`IllegalAction` otherwise."""

        before = self.snapshot()
        self._require_legal(before, seat, decision)
        text = _describe(before, decision)
        assert self.state is not None
        try:
            if decision.kind == "fold":
                self.folded.add(seat)
                self.state.fold()
            elif decision.kind in ("check", "call"):
                self.state.check_or_call()
            else:
                assert decision.to_amount is not None
                self.state.complete_bet_or_raise_to(int(decision.to_amount))
        except ValueError as exc:
            raise IllegalAction(str(exc)) from exc
        self._normalize()
        if not self.betting:
            text = f"{text}. {_result_text(self)}"
        self.last_action = text
        return self.snapshot()

    def step_bot(self) -> GameState:
        """Let the scripted or random policy act once for the current bot seat."""

        seat = self.actor_seat()
        if not self.betting or seat is None:
            raise IllegalAction("no seat is waiting to act")
        if seat not in self.bot_seats:
            raise HumanToAct(f"seat {seat} is a human")
        decision = self.policy.choose(self.snapshot(), self.policy_rng)
        return self.apply(seat, decision)

    def timeout_decision(self) -> Decision:
        """What a human seat does when the shot clock expires: check if free, else fold."""

        kinds = {action.kind for action in self.snapshot().legal_actions}
        if "check" in kinds:
            return Decision(kind="check")
        if "fold" in kinds:
            return Decision(kind="fold")
        if "call" in kinds:
            return Decision(kind="call")
        raise IllegalAction("the shot clock expired and no action is legal")

    def set_hero(self, seat: int | None) -> None:
        if seat is not None and not 0 <= seat < self.seat_count:
            raise TableConfigError(f"seat {seat} is not at this table")
        if self.hero_seat is not None:
            self.bot_seats.add(self.hero_seat)
        self.hero_seat = seat
        if seat is not None:
            self.bot_seats.discard(seat)

    def set_reveal(self, reveal: Reveal) -> None:
        if reveal not in ("all", "hero", "showdown"):
            raise TableConfigError("reveal must be all, hero, or showdown")
        self.reveal = reveal

    def actor_seat(self) -> int | None:
        if self.state is None or not self.state.status or self.state.actor_index is None:
            return None
        return self.pk_to_seat[self.state.actor_index]

    def snapshot(self) -> GameState:
        """Ground-truth state. May finish a hand that is waiting to pay the pot."""

        self._normalize()
        assert self.state is not None
        phase = "betting" if self.state.status else "complete"
        actor = self.actor_seat()
        total, pots = self._pot_view()
        remaining, deadline = self._timer()
        return GameState(
            schema_version=SCHEMA_VERSION,
            source="ground_truth",
            table_id=self.table_id,
            hand_id=f"{self.table_id}-h{self.hand_number}",
            hand_number=IntObs(value=self.hand_number),
            small_blind=IntObs(value=self.small_blind),
            big_blind=IntObs(value=self.big_blind),
            ante=IntObs(value=self.ante),
            button_seat=IntObs(value=self.hand_button),
            street=StreetObs(value=self._current_street()),
            hand_phase=PhaseObs(value=phase),
            board=[CardObs(value=code) for code in self._board()],
            pots=[
                PotState(amount=IntObs(value=amount), eligible_seats=list(seats))
                for amount, seats in pots
            ],
            total_pot=IntObs(value=total),
            seats=[self._seat_state(seat, actor, phase) for seat in range(self.seat_count)],
            actor_seat=ActorObs(value=actor),
            legal_actions=self._legal_actions() if actor is not None else [],
            timers=TimerState(
                shot_clock_ms=IntObs(value=self.shot_clock_ms),
                remaining_ms=OptIntObs(value=remaining),
                deadline_unix_ms=OptIntObs(value=deadline),
            ),
            hero_seat=self.hero_seat,
            reveal=self.reveal,
            autoplay=self.autoplay,
            last_action=self.last_action,
        )

    def _install_deck(self) -> None:
        assert self.state is not None
        deck = list(Deck.STANDARD)
        random.Random(f"{self.seed}:deck:{self.hand_number}").shuffle(deck)
        self.state.deck_cards = deque(deck)

    def _normalize(self) -> None:
        """Deal anything waiting, then pay the pot once the hand is over."""

        if self.state is None:
            return
        for _ in range(16):
            if self.state.can_deal_hole() or self.state.can_deal_board():
                self._deal_pending()
                continue
            if self.state.can_push_chips() or self.state.can_pull_chips():
                self._settle_chips()
                continue
            break
        self._capture_holes()
        self._current_street()
        self._sync_stacks()
        self._touch_turn()

    def _deal_pending(self) -> None:
        assert self.state is not None
        while self.state.status and (self.state.can_deal_hole() or self.state.can_deal_board()):
            if self.state.can_deal_hole():
                self.state.deal_hole()
            else:
                self.state.deal_board()
            self._capture_holes()
            self._remember_open_pots()

    def _settle_chips(self) -> None:
        assert self.state is not None
        self._remember_open_pots()
        for _ in range(24):
            if not self.state.status:
                return
            if self.state.can_push_chips():
                self.state.push_chips()
            elif self.state.can_pull_chips():
                self.state.pull_chips()
            else:
                return

    def _capture_holes(self) -> None:
        assert self.state is not None
        for index, cards in enumerate(self.state.hole_cards):
            coded: list[str] = []
            for card in cards:
                code = card_code(card)
                if code == "??":
                    continue
                coded.append(code)
            if len(coded) == 2:
                self.known_holes[self.pk_to_seat[index]] = coded

    def _sync_stacks(self) -> None:
        assert self.state is not None
        for index, seat in enumerate(self.pk_to_seat):
            self.stacks[seat] = int(self.state.stacks[index])

    def _remember_open_pots(self) -> None:
        assert self.state is not None
        total = int(self.state.total_pot_amount)
        if total <= 0:
            return
        detailed: list[tuple[int, list[int]]] = []
        for pot in self.state.pots:
            amount = int(pot.amount)
            if amount <= 0:
                continue
            seats = sorted(self.pk_to_seat[index] for index in pot.player_indices)
            detailed.append((amount, seats))
        if detailed and sum(amount for amount, _seats in detailed) == total:
            pots = detailed
        else:
            active = sorted(
                self.pk_to_seat[index]
                for index, playing in enumerate(self.state.statuses)
                if playing and index < len(self.pk_to_seat)
            )
            pots = [(total, active or sorted(self.pk_to_seat))]
        self._last_total = total
        self._last_pots = pots

    def _pot_view(self) -> tuple[int, list[tuple[int, list[int]]]]:
        if self.state is not None and self.state.status:
            self._remember_open_pots()
        return self._last_total, self._last_pots

    def _board(self) -> list[str]:
        assert self.state is not None
        return [card_code(card) for card in self.state.get_board_cards(0)]

    def _current_street(self) -> str:
        """Name the street from the cards on the board.

        PokerKit's ``street_index`` moves on when the previous street finishes,
        which is before the next cards are visible. The board itself matches
        what a screenshot shows.
        """

        count = len(self._board()) if self.state is not None else 0
        if count >= 5:
            name = "river"
        elif count == 4:
            name = "turn"
        elif count == 3:
            name = "flop"
        else:
            name = "preflop"
        self._last_street = name
        return name

    def _timer(self) -> tuple[int | None, int | None]:
        if self.actor_seat() is None or self._deadline_unix_ms is None:
            return None, None
        remaining = max(0, self._deadline_unix_ms - self.clock.unix_ms())
        return remaining, self._deadline_unix_ms

    def _touch_turn(self) -> None:
        actor = self.actor_seat()
        if actor is None:
            self._timed_actor = None
            self._deadline_unix_ms = None
            return
        if actor == self._timed_actor:
            return
        self._timed_actor = actor
        self._deadline_unix_ms = self.clock.unix_ms() + self.shot_clock_ms

    def _seat_state(self, seat: int, actor: int | None, phase: str) -> SeatState:
        in_hand = seat in self.seat_to_pk
        status = self._status(seat)
        holes = self.known_holes.get(seat, [])
        shown = self._faces_up(seat, status, phase)
        payoff: int | None = None
        if in_hand and phase == "complete" and self.state is not None:
            payoff = int(self.state.payoffs[self.seat_to_pk[seat]])
        bet = 0
        if in_hand and self.state is not None and self.state.status:
            bet = int(self.state.bets[self.seat_to_pk[seat]])
        position = position_for(self.ring, seat) if in_hand else None
        return SeatState(
            seat=seat,
            name=StrObs(value=self._name(seat)),
            position=PositionObs(value=position),  # type: ignore[arg-type]
            stack=IntObs(value=int(self.stacks[seat])),
            bet=IntObs(value=bet),
            hole_cards=[CardObs(value=code) for code in holes],
            status=StatusObs(value=status),
            is_button=BoolObs(value=seat == self.hand_button),
            is_actor=BoolObs(value=seat == actor),
            hole_cards_shown=BoolObs(value=shown),
            payoff=OptIntObs(value=payoff),
        )

    def _status(self, seat: int) -> str:
        if seat not in self.seat_to_pk:
            return "sitting_out"
        if seat in self.folded:
            return "folded"
        if self.stacks[seat] <= 0:
            return "all_in"
        return "active"

    def _faces_up(self, seat: int, status: str, phase: str) -> bool:
        if not self.known_holes.get(seat):
            return False
        if self.reveal == "all":
            return True
        if seat == self.hero_seat:
            return True
        if self.reveal == "hero":
            return False
        return phase == "complete" and status != "folded"

    def _name(self, seat: int) -> str:
        number = seat + 1
        if seat == self.hero_seat:
            return "You"
        if seat in self.bot_seats:
            return f"Bot {number}"
        return f"Seat {number}"

    def _legal_actions(self) -> list[LegalAction]:
        assert self.state is not None and self.state.actor_index is not None
        state = self.state
        index = state.actor_index
        actions: list[LegalAction] = []
        call_amount = int(state.checking_or_calling_amount or 0)
        if state.can_fold() and call_amount > 0:
            actions.append(LegalAction(kind="fold"))
        if state.can_check_or_call():
            if call_amount == 0:
                actions.append(LegalAction(kind="check"))
            else:
                stack = int(state.stacks[index])
                actions.append(
                    LegalAction(
                        kind="call",
                        amount=IntObs(value=call_amount),
                        is_all_in=stack <= call_amount,
                    )
                )
        if state.can_complete_bet_or_raise_to():
            actions.append(self._bet_action(index, call_amount))
        return actions

    def _bet_action(self, index: int, call_amount: int) -> LegalAction:
        assert self.state is not None
        state = self.state
        min_to = int(state.min_completion_betting_or_raising_to_amount)
        max_to = int(state.max_completion_betting_or_raising_to_amount)
        bet_now = int(state.bets[index])
        pot = int(state.total_pot_amount)
        stack = int(state.stacks[index])
        kind = "bet" if call_amount == 0 else "raise"

        def to_amount(fraction: float) -> int:
            # A pot-sized raise calls, then raises the size of the pot after that call.
            extra = int(round(fraction * (pot + call_amount)))
            return bet_now + call_amount + extra

        raw: list[tuple[str, int]] = []
        for label, fraction in _SIZES:
            if label == "min":
                amount = min_to
            elif label == "all-in":
                amount = max_to
            else:
                assert fraction is not None
                amount = to_amount(fraction)
            raw.append((label, amount))

        sizing: list[SizingOption] = []
        seen: set[int] = set()
        for label, amount in raw:
            if amount < min_to or amount > max_to:
                continue
            if not state.can_complete_bet_or_raise_to(amount):
                continue
            if amount in seen:
                continue
            if amount == max_to:
                label = "all-in"
            seen.add(amount)
            sizing.append(SizingOption(label=label, to_amount=IntObs(value=amount)))  # type: ignore[arg-type]

        return LegalAction(
            kind=kind,  # type: ignore[arg-type]
            min_to=IntObs(value=min_to),
            max_to=IntObs(value=max_to),
            sizing=sizing,
            is_all_in=min_to >= bet_now + stack,
        )

    def _require_legal(self, before: GameState, seat: int, decision: Decision) -> None:
        if before.hand_phase.value != "betting":
            raise IllegalAction("the hand is not waiting for an action")
        if before.actor_seat.value != seat:
            actor = before.actor_seat.value
            raise IllegalAction(f"seat {seat} cannot act; seat {actor} is next")
        matches = [action for action in before.legal_actions if action.kind == decision.kind]
        if not matches:
            raise IllegalAction(f"{decision.kind} is not legal")
        if decision.kind in ("bet", "raise"):
            if decision.to_amount is None:
                raise IllegalAction(f"{decision.kind} needs to_amount")
            assert self.state is not None
            if not self.state.can_complete_bet_or_raise_to(int(decision.to_amount)):
                raise IllegalAction(f"cannot {decision.kind} to {decision.to_amount}")


def _describe(before: GameState, decision: Decision) -> str:
    name = "Seat"
    bet = 0
    stack = 0
    for seat in before.seats:
        if seat.seat == before.actor_seat.value:
            name = seat.name.value
            bet = seat.bet.value
            stack = seat.stack.value
            break
    if decision.kind == "fold":
        return f"{name} folds"
    if decision.kind == "check":
        return f"{name} checks"
    if decision.kind == "call":
        amount = 0
        for action in before.legal_actions:
            if action.kind == "call" and action.amount is not None:
                amount = action.amount.value
        suffix = " all-in" if amount >= stack else ""
        return f"{name} calls {amount}{suffix}"
    assert decision.to_amount is not None
    chips = decision.to_amount - bet
    suffix = " all-in" if chips >= stack else ""
    verb = "bets" if decision.kind == "bet" else "raises to"
    shown = decision.to_amount if decision.kind == "raise" else chips
    return f"{name} {verb} {shown}{suffix}"


def _result_text(table: Table) -> str:
    assert table.state is not None
    parts: list[str] = []
    for seat in range(table.seat_count):
        if seat not in table.seat_to_pk:
            continue
        payoff = int(table.state.payoffs[table.seat_to_pk[seat]])
        parts.append(f"{table._name(seat)} {payoff:+d}")
    return "Result: " + ", ".join(parts)
