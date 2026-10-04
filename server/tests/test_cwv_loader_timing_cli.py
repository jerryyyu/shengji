import pytest

from shengji.train import train_cwv


def test_loader_stage_timing_is_an_opt_in_train_flag():
    parser = train_cwv.build_parser()
    default = parser.parse_args(["train", "--data", "d", "--out", "o"])
    enabled = parser.parse_args([
        "train", "--data", "d", "--out", "o", "--loader-stage-timing",
    ])
    assert default.loader_stage_timing is False
    assert enabled.loader_stage_timing is True


def test_loader_stage_timing_reaches_train_but_not_evaluate(monkeypatch):
    calls = []
    monkeypatch.setattr(train_cwv, "train", lambda **kw: calls.append(("train", kw)) or {})
    monkeypatch.setattr(train_cwv, "evaluate", lambda **kw: calls.append(("evaluate", kw)) or {})

    assert train_cwv.main([
        "train", "--data", "d", "--out", "o", "--loader-stage-timing",
    ]) == 0
    assert calls[-1][0] == "train"
    assert calls[-1][1]["loader_stage_timing"] is True

    assert train_cwv.main([
        "evaluate", "--checkpoint", "c", "--out", "o", "--data", "d",
    ]) == 0
    assert calls[-1][0] == "evaluate"
    assert "loader_stage_timing" not in calls[-1][1]


def test_loader_stage_timing_rejects_pack_before_pipeline_setup(tmp_path):
    with pytest.raises(train_cwv.TrainError, match="not supported with --pack-dir"):
        train_cwv.train(data=["missing"], out=tmp_path / "out", pack_dir="pack",
                        loader_stage_timing=True)
