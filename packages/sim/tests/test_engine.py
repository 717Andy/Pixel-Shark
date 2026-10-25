import random

import pytest

from pixelshark_schema import Decision, GameState
from pixelshark_sim import HumanToAct, IllegalAction, Table, TableConfigError
from pixelshark_sim.clock import WallClock


class FakeClock:
    def __init__(self) -> None:
        self.mono = 0.0
        self.unix = 1_700_000_000_000

    def monotonic(self) -> float:
        return self.mono

    def unix_ms(self) -> int:
        return self.unix

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.unix += int(seconds * 1000)


def _table(**kwargs) -> Table:
    defaults = dict(
        seats=6,
        stacks=10_000,
        small_blind=50,
        big_blind=100,
        seed=3,
        hero_seat=0,
        rebuy=False,
        shot_clock_ms=15_000,
        clock=FakeClock(),
    )
    defaults.update(kwargs)
    return Table(**defaults)


def test_config_rejects_bad_tables():
    with pytest.raises(TableConfigError):
        _table(seats=1)
    with pytest.raises(TableConfigError):
        _table(seats=10)
    with pytest.raises(TableConfigError):
        _table(small_blind=100, big_blind=50)


def test_six_max_positions_and_first_actor():
    table = _table(button_seat=0)
    state = table.snapshot()
    assert isinstance(state, GameState)
    assert state.schema_version == "1.0.0"
    assert state.source == "ground_truth"
    by_seat = {seat.seat: seat for seat in state.seats}
    assert by_seat[0].position.value == "BTN"
    assert by_seat[1].position.value == "SB"
    assert by_seat[1].bet.value == 50
    assert by_seat[2].position.value == "BB"
    assert by_seat[2].bet.value == 100
    assert by_seat[3].position.value == "UTG"
    assert state.actor_seat.value == 3
    assert state.street.value == "preflop"
    assert state.hand_phase.value == "betting"
    assert state.total_pot.value == 150
    assert all(len(seat.hole_cards) == 2 for seat in state.seats)
    assert all(card.confidence == 1.0 for seat in state.seats for card in seat.hole_cards)
    # Hero sees their cards. Everyone else is face down until showdown.
    assert by_seat[0].hole_cards_shown.value is True
    assert by_seat[3].hole_cards_shown.value is False
    kinds = {action.kind for action in state.legal_actions}
    assert {"fold", "call", "raise"} <= kinds
    raise_action = next(action for action in state.legal_actions if action.kind == "raise")
    assert raise_action.min_to is not None and raise_action.min_to.value == 200
    assert any(option.label == "all-in" for option in raise_action.sizing)


def test_heads_up_button_acts_first_and_posts_small_blind():
    table = _table(seats=2, button_seat=0, hero_seat=0)
    state = table.snapshot()
    by_seat = {seat.seat: seat for seat in state.seats}
    assert by_seat[0].position.value == "BTN"
    assert by_seat[0].bet.value == 50
    assert by_seat[1].position.value == "BB"
    assert by_seat[1].bet.value == 100
    assert state.actor_seat.value == 0


def test_fold_ends_hand_and_conserves_chips():
    table = _table(seats=2, button_seat=0, hero_seat=None, bot_seats=[])
    start = sum(seat.stack.value + seat.bet.value for seat in table.snapshot().seats)
    done = table.apply(0, Decision(kind="fold"))
    assert done.hand_phase.value == "complete"
    assert done.street.value == "preflop"
    assert sum(seat.stack.value for seat in done.seats) == start
    assert sum(seat.payoff.value or 0 for seat in done.seats) == 0
    winner = next(seat for seat in done.seats if (seat.payoff.value or 0) > 0)
    assert winner.seat == 1
    assert winner.hole_cards_shown.value is True
    # Folded cards stay in the ground truth even though the faces are hidden.
    folder = next(seat for seat in done.seats if seat.seat == 0)
    assert folder.status.value == "folded"
    assert len(folder.hole_cards) == 2
    assert folder.hole_cards_shown.value is False


def test_illegal_actions():
    table = _table(seats=2, button_seat=0, hero_seat=0)
    with pytest.raises(IllegalAction):
        table.apply(1, Decision(kind="fold"))
    with pytest.raises(IllegalAction):
        table.apply(0, Decision(kind="raise", to_amount=51))
    with pytest.raises(IllegalAction):
        table.apply(0, Decision(kind="check"))


def test_button_moves_and_deals_are_seeded():
    first = _table(seats=2, button_seat=0, seed=11)
    second = _table(seats=2, button_seat=0, seed=11)
    assert _codes(first) == _codes(second)
    other = _table(seats=2, button_seat=0, seed=12)
    assert _codes(first) != _codes(other)
    first.apply(0, Decision(kind="fold"))
    nxt = first.start_hand()
    assert nxt.button_seat.value == 1
    assert nxt.hand_number.value == 2


def test_side_pots_and_conservation():
    table = _table(
        seats=3,
        stacks=[300, 1000, 1000],
        button_seat=0,
        hero_seat=None,
        bot_seats=[],
        seed=4,
    )
    start = 300 + 1000 + 1000
    # Button shoves, small blind reshoves, big blind calls. The board runs out.
    for _ in range(2):
        state = table.snapshot()
        seat = state.actor_seat.value
        aggressive = next(
            action for action in state.legal_actions if action.kind in ("bet", "raise")
        )
        assert aggressive.max_to is not None
        table.apply(seat, Decision(kind=aggressive.kind, to_amount=aggressive.max_to.value))
    state = table.snapshot()
    assert state.actor_seat.value is not None
    table.apply(state.actor_seat.value, Decision(kind="call"))
    done = table.snapshot()
    assert done.hand_phase.value == "complete"
    assert len(done.board) == 5
    assert done.street.value == "river"
    assert done.total_pot.value == start
    assert sorted(pot.amount.value for pot in done.pots) == [900, 1400]
    side = next(pot for pot in done.pots if pot.amount.value == 1400)
    assert 0 not in side.eligible_seats
    assert sum(seat.stack.value for seat in done.seats) == start
    assert sum(seat.payoff.value or 0 for seat in done.seats) == 0


@pytest.mark.parametrize("seats", [2, 6, 9])
def test_scripted_bots_conserve_chips(seats: int):
    table = _table(seats=seats, hero_seat=None, bot_seats=set(range(seats)), seed=seats + 20)
    start = seats * 10_000
    for _ in range(8):
        guard = 0
        while table.betting and guard < 80:
            guard += 1
            table.step_bot()
        assert sum(table.stacks) == start
        if not table.betting:
            table.start_hand()
    # start_hand posts the blinds, so chips in the current pot are not in stacks.
    state = table.snapshot()
    live = sum(seat.stack.value + seat.bet.value for seat in state.seats)
    assert live == start


def test_step_bot_refuses_a_human_seat():
    table = _table(seats=2, button_seat=0, hero_seat=0, bot_seats={1})
    with pytest.raises(HumanToAct):
        table.step_bot()


def test_reveal_all_shows_every_hand():
    table = _table(reveal="all", hero_seat=None)
    state = table.snapshot()
    assert all(seat.hole_cards_shown.value for seat in state.seats)


def test_sitting_out_when_broke():
    table = _table(seats=3, stacks=[0, 1000, 1000], button_seat=0, hero_seat=None, rebuy=False)
    state = table.snapshot()
    by_seat = {seat.seat: seat for seat in state.seats}
    assert by_seat[0].status.value == "sitting_out"
    assert by_seat[0].position.value is None
    assert {by_seat[1].position.value, by_seat[2].position.value} == {"BTN", "BB"}


def test_shot_clock_is_reported():
    clock = FakeClock()
    table = _table(seats=2, clock=clock, shot_clock_ms=10_000)
    state = table.snapshot()
    assert state.timers.shot_clock_ms.value == 10_000
    assert state.timers.remaining_ms.value == 10_000
    clock.advance(4)
    state = table.snapshot()
    assert state.timers.remaining_ms.value == 6_000


def test_random_policy_finishes_a_hand():
    table = _table(seats=4, hero_seat=None, bot_policy="random", seed=99)
    guard = 0
    while table.betting and guard < 100:
        guard += 1
        table.step_bot()
    assert table.snapshot().hand_phase.value == "complete"
    assert sum(table.stacks) == 40_000


def test_wall_clock_moves():
    clock = WallClock()
    assert clock.unix_ms() > 0
    assert clock.monotonic() > 0


def _codes(table: Table) -> list[str | None]:
    return [card.value for seat in table.snapshot().seats for card in seat.hole_cards]


def test_policy_rng_is_independent_of_python_random():
    # Importing the engine must not require the global random seed to reproduce a deal.
    random.seed(1)
    left = _codes(_table(seats=2, seed=5))
    random.seed(2)
    right = _codes(_table(seats=2, seed=5))
    assert left == right
