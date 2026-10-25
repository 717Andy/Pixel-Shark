import pytest

from pixelshark_perception import GroundTruthReader, VlmReader
from pixelshark_sim import Table


def test_ground_truth_reader_ignores_the_image():
    state = Table(seats=2, seed=1).snapshot()
    assert GroundTruthReader(state).read(b"anything") is state


def test_vlm_reader_is_not_implemented():
    with pytest.raises(NotImplementedError):
        VlmReader().read(b"frame")
