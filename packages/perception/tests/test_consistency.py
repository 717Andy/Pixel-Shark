from pixelshark_perception.consistency import check_consistency
from pixelshark_schema import Decision, LegalAction
from pixelshark_sim import Table


def _play_to_flop(seed: int = 1) -> Table:
    table = Table(seats=6, seed=seed, autoplay=False)
    for _ in range(12):
        state = table.snapshot()
        if state.street.value == "flop":
            return table
        kinds = {action.kind: action for action in state.legal_actions}
        actor = state.actor_seat.value
        assert actor is not None
        if "check" in kinds:
            table.apply(actor, Decision(kind="check"))
        elif "call" in kinds:
            table.apply(actor, Decision(kind="call"))
        else:
            table.apply(actor, Decision(kind="fold"))
    raise AssertionError("never reached the flop")


def test_engine_snapshots_agree_with_themselves():
    samples = [
        Table(seats=6, seed=1, autoplay=False).snapshot(),
        Table(seats=2, seed=3, autoplay=False).snapshot(),
        _play_to_flop().snapshot(),
    ]
    table = _play_to_flop(seed=2)
    state = table.snapshot()
    bet = next(action for action in state.legal_actions if action.kind == "bet")
    actor = state.actor_seat.value
    assert actor is not None
    samples.append(table.apply(actor, Decision(kind="bet", to_amount=bet.min_to.value)))
    finished = Table(seats=2, seed=2, autoplay=False)
    for _ in range(30):
        state = finished.snapshot()
        if state.hand_phase.value == "complete":
            samples.append(state)
            break
        kinds = {action.kind: action for action in state.legal_actions}
        actor = state.actor_seat.value
        assert actor is not None
        if "check" in kinds:
            finished.apply(actor, Decision(kind="check"))
        elif "call" in kinds:
            finished.apply(actor, Decision(kind="call"))
        else:
            finished.apply(actor, Decision(kind="fold"))
    assert samples[-1].hand_phase.value == "complete"
    for state in samples:
        checked, issues = check_consistency(state)
        assert issues == []
        assert checked.total_pot.value == state.total_pot.value
        assert checked.total_pot.confidence == 1


def test_pot_mismatch_lowers_confidence_and_keeps_the_number():
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    state.total_pot.value = 1
    checked, issues = check_consistency(state)
    assert checked.total_pot.value == 1
    assert checked.total_pot.confidence < 1
    assert any(issue.code == "pot_mismatch" for issue in issues)


def test_check_and_call_together_are_not_trusted():
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    state.legal_actions.append(LegalAction(kind="check"))
    checked, issues = check_consistency(state)
    assert any(issue.code == "legal_actions" for issue in issues)
    assert all(action.confidence < 1 for action in checked.legal_actions)
    assert [action.kind for action in checked.legal_actions] == [
        action.kind for action in state.legal_actions
    ]


def test_board_that_does_not_match_the_street():
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    assert state.street.value == "preflop"
    state.street.value = "flop"
    checked, issues = check_consistency(state)
    assert any(issue.code == "board_street" for issue in issues)
    assert checked.street.value == "flop"
    assert checked.street.confidence < 1


def test_blind_order():
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    state.small_blind.value = 500
    state.big_blind.value = 100
    _checked, issues = check_consistency(state)
    assert any(issue.code == "blind_order" for issue in issues)
