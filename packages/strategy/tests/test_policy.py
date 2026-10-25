from pixelshark_schema import Decision
from pixelshark_sim import Table
from pixelshark_strategy import ScriptedStrategy


def test_scripted_strategy_picks_a_legal_action():
    table = Table(seats=6, seed=2, hero_seat=None)
    decision = ScriptedStrategy(seed=2).choose(table.snapshot())
    assert isinstance(decision, Decision)
    kinds = {action.kind for action in table.snapshot().legal_actions}
    assert decision.kind in kinds
