import json

from pixelshark_perception.cli import main
from pixelshark_sim import Table


def test_read_command_uses_the_mock_file(tmp_path, monkeypatch, capsys):
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    script = tmp_path / "script.json"
    script.write_text(state.model_dump_json())
    image = tmp_path / "frame.png"
    image.write_bytes(b"png")
    monkeypatch.setenv("PIXELSHARK_VLM", "mock")
    monkeypatch.setenv("PIXELSHARK_VLM_MOCK_JSON", str(script))
    assert main(["read", str(image)]) == 0
    out = capsys.readouterr().out
    assert "perceived" in out
    assert "no action taken" in out
    assert f'"hand_id": "{state.hand_id}"' in out


def test_eval_command_writes_a_report(tmp_path, capsys):
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    folder = tmp_path / "data" / "0000"
    folder.mkdir(parents=True)
    (folder / "frame.png").write_bytes(b"png")
    (folder / "state.json").write_text(state.model_dump_json())
    (folder / "meta.json").write_text(json.dumps({"skin": "felt"}))
    out = tmp_path / "out"
    code = main(
        ["eval", "--data", str(tmp_path / "data"), "--out", str(out), "--backend", "oracle"]
    )
    assert code == 0
    report = json.loads((out / "report.json").read_text())
    assert report["overall"]["full_state_exact_match"]["accuracy"] == 1
    assert "exact match" in capsys.readouterr().out


def test_read_command_can_log_the_frame(tmp_path, monkeypatch, capsys):
    state = Table(seats=2, seed=1, autoplay=False).snapshot()
    script = tmp_path / "script.json"
    script.write_text(state.model_dump_json())
    image = tmp_path / "frame.png"
    image.write_bytes(b"png-bytes")
    monkeypatch.setenv("PIXELSHARK_VLM", "mock")
    monkeypatch.setenv("PIXELSHARK_VLM_MOCK_JSON", str(script))
    log_dir = tmp_path / "log"
    assert main(["read", str(image), "--log", str(log_dir)]) == 0
    assert (log_dir / "frames" / "0000.png").read_bytes() == b"png-bytes"
    assert "perceived" in capsys.readouterr().out
