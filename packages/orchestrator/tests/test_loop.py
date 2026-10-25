from pixelshark_executor import ButtonExecutor
from pixelshark_orchestrator import AgentLoop
from pixelshark_perception import GroundTruthReader
from pixelshark_schema import Decision
from pixelshark_sim import Table
from pixelshark_style import HumanPace
from pixelshark_tracker import PassthroughTracker


class _Fold:
    def choose(self, state: object) -> Decision:
        del state
        return Decision(kind="fold")


def test_loop_returns_a_click_when_the_button_is_boxed():
    state = Table(seats=2, seed=1).snapshot()
    loop = AgentLoop(
        reader=GroundTruthReader(state),
        tracker=PassthroughTracker(),
        strategy=_Fold(),
        style=HumanPace(100),
        executor=ButtonExecutor(),
    )
    boxes = [
        {
            "label": "button",
            "x": 8,
            "y": 12,
            "width": 20,
            "height": 10,
            "attrs": {"kind": "action", "action": "fold"},
        }
    ]
    result = loop.step(b"frame", boxes)
    assert result.decision.kind == "fold"
    assert result.delay_ms == 100
    assert result.click_x == 18
    assert result.click_y == 17
    assert result.state.hand_id == state.hand_id
