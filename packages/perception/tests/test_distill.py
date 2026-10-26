import pytest

from pixelshark_perception.backends import MockBackend
from pixelshark_perception.detector import PerSkinDetectorTrainer
from pixelshark_perception.evaluate import evaluate_dataset
from pixelshark_perception.readlog import load_log
from pixelshark_sim import Table


def test_trainer_loads_the_log_and_does_not_train(tmp_path):
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    data = tmp_path / "data" / "0000"
    data.mkdir(parents=True)
    (data / "frame.png").write_bytes(b"png")
    (data / "state.json").write_text(state.model_dump_json())
    (data / "meta.json").write_text('{"skin": "felt"}')
    log_dir = tmp_path / "reads"
    evaluate_dataset(tmp_path / "data", MockBackend([state.model_dump_json()]), log_dir=log_dir)
    rows = load_log(log_dir)
    assert len(rows) == 1
    assert rows[0].skin == "felt"
    assert rows[0].image_path.read_bytes() == b"png"
    with pytest.raises(NotImplementedError, match="next phase"):
        PerSkinDetectorTrainer().fit(log_dir)


def test_empty_log_is_still_a_stub(tmp_path):
    with pytest.raises(NotImplementedError, match="0 frame"):
        PerSkinDetectorTrainer().fit(tmp_path)
