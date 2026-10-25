from pixelshark_schema import Decision
from pixelshark_sim import Table
from pixelshark_style import HumanPace, IdentityStyle


def test_styles_do_not_change_the_action():
    state = Table(seats=2, seed=1).snapshot()
    decision = Decision(kind="fold")
    plain = IdentityStyle().apply(state, decision)
    paced = HumanPace(250).apply(state, decision)
    assert plain.delay_ms == 0
    assert plain.decision == decision
    assert paced.delay_ms == 250
    assert paced.decision.kind == "fold"
