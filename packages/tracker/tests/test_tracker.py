from pixelshark_sim import Table
from pixelshark_tracker import PassthroughTracker


def test_passthrough_returns_the_same_state():
    state = Table(seats=2, seed=1).snapshot()
    assert PassthroughTracker().update(state) is state
