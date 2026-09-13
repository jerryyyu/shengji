import json
from types import SimpleNamespace

import pytest

from shengji.train import cwv_shortlist_screen as S


def _cfg(**overrides):
    value = {
        "schema": "cwv-shortlist-config-v1", "arm": "learned",
        "checkpoint": "m.pt", "checkpoint_sha256": "a" * 64,
        "shortlist": {"worlds": 1, "selection_worlds": 30,
                       "alternatives": 4, "batch_size": 128, "uniform": False},
        "report_worlds": 300, "production_multiplier": 1,
        "target_wall_multiplier": 1, "seed0": 17, "clusters": 1,
        "baseline": "flat-shortlist",
        "corrected_rollout": {"mode": "corrected", "correction_worlds": 64,
                              "residual_worlds": 16},
    }
    value.update(overrides)
    return value


def test_corrected_factory_binds_mode_and_world_recipe(monkeypatch):
    class Fake:
        def __init__(self, evaluator, **kwargs):
            self.kwargs = kwargs
            self.REPORT_FOLD_WORLDS = None

    monkeypatch.setattr(S, "CWVCorrectedRolloutBot", Fake)
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: SimpleNamespace(
        checkpoint_sha256="a" * 64))
    bot = S.make_side(_cfg(), "arm", 17)
    assert bot.kwargs["correction_mode"] == "corrected"
    assert bot.kwargs["correction_worlds"] == 64
    assert bot.kwargs["residual_worlds"] == 16
    assert S._recipe(_cfg())["corrected_rollout"]["mode"] == "corrected"


def test_real_factory_keeps_flat_baseline_uncorrected_and_bury_mro(monkeypatch):
    evaluator = SimpleNamespace(checkpoint_sha256="a" * 64)
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: evaluator)
    arm = S.make_side(_cfg(hybrid_bury=True), "arm", 17)
    baseline = S.make_side(_cfg(hybrid_bury=True), "baseline", 17)
    assert type(arm) is S.CWVCorrectedRolloutBuryBot
    assert type(baseline) is S.CWVBuryBot
    assert arm.correction_worlds == 64 and arm.residual_worlds == 16
    assert not hasattr(baseline, "corrected_rollout_counts")


def test_levels_shortlist_baseline_uses_same_selector_without_model_evaluation(monkeypatch):
    import random
    import numpy as np
    from tests.test_world_shortlist import play_state
    from shengji.ai.memory import Memory
    calls = []
    def score(leaves, seat):
        calls.append(len(leaves))
        return np.zeros(len(leaves))
    evaluator = SimpleNamespace(checkpoint_sha256="a" * 64, score=score)
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: evaluator)
    config = _cfg(baseline="levels-shortlist", corrected_rollout={
        "mode": "corrected", "correction_worlds": 2, "residual_worlds": 1})
    arm = S.make_side(config, "arm", 17)
    control = S.make_side(config, "baseline", 17)
    assert type(arm) is type(control) is S.CWVCorrectedRolloutBot
    assert arm.correction_mode == "corrected"
    assert control.correction_mode == "levels"
    assert (arm.correction_worlds, arm.residual_worlds) == (2, 1)
    rnd = play_state()
    action = [[rnd.hands[rnd.turn][0]]]
    for bot in (control, arm):
        bot._selection_override(rnd, rnd.turn, action, Memory(rnd, rnd.turn),
             rnd.is_attacker(rnd.turn), allocation_rng=random.Random(3))
        assert sum(calls) == (0 if bot is control else 2)


def test_levels_control_is_same_recipe_except_mode():
    corrected = _cfg()
    levels = _cfg(corrected_rollout={"mode": "levels", "correction_worlds": 64,
                                     "residual_worlds": 16})
    assert S._recipe(corrected)["corrected_rollout"] != S._recipe(levels)["corrected_rollout"]
    assert S._recipe(corrected)["shortlist"] == S._recipe(levels)["shortlist"]


def test_work_counters_charge_model_worlds_without_calling_them_full_rollouts(monkeypatch):
    monkeypatch.setattr(S.duel, "work_counters", lambda bots: {
        "accepted_worlds": 30, "rollouts": 12})
    bot = SimpleNamespace(corrected_rollout_counts={
        "sampled_worlds": 64, "residual_worlds": 16,
        "model_evaluations": 256, "rollouts": 16})
    result = S.work_counters([bot])
    assert result["correction_sampled_worlds"] == 64
    assert result["correction_model_evaluations"] == 256
    assert result["cheap_evaluations"] == 256
    assert result["full_rollout_accepted_worlds"] == 30 - 48
    assert result["total_rollouts"] == 12


@pytest.mark.parametrize("extra", [
    ["--arm", "uniform", "--baseline", "production"],
    ["--baseline", "production"],
    ["--inner-mode", "learned"],
    ["--value-head", "outcome"],
    ["--report-tie-keeps-incumbent"],
])
def test_corrected_cli_rejects_nonisolated_combinations(tmp_path, monkeypatch, extra, capsys):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(SystemExit):
        S.main(["--arm", "learned", "--checkpoint", str(tmp_path / "m.pt"),
                "--corrected-rollout", "corrected", "--baseline", "flat-shortlist",
                "--clusters", "1",
                "--workers", "1", "--seed0", "17", "--out", str(tmp_path / "o"),
                *extra])
    assert "corrected-rollout" in capsys.readouterr().err


def test_corrected_cli_rejects_residual_overflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(SystemExit):
        S.main(["--arm", "learned", "--checkpoint", str(tmp_path / "m.pt"),
                "--baseline", "flat-shortlist", "--corrected-rollout", "corrected",
                "--correction-worlds", "4", "--residual-worlds", "5",
                "--clusters", "1", "--workers", "1", "--seed0", "17",
                "--out", str(tmp_path / "o")])
    assert "residual worlds must be <= correction worlds" in capsys.readouterr().err


def test_corrected_cli_persists_opt_in_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    ckpt = tmp_path / "m.pt"
    ckpt.write_bytes(b"x")
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: SimpleNamespace(
        checkpoint_sha256="a" * 64, identity=lambda: {"backend": "fake"}))
    monkeypatch.setattr(S, "execution_source_identity", lambda *_: {"source": "test"})
    monkeypatch.setattr(S, "_run_pending", lambda *a, **k: None)
    out = tmp_path / "o"
    S.main(["--arm", "learned", "--checkpoint", str(ckpt), "--baseline", "flat-shortlist",
            "--corrected-rollout", "levels",
            "--clusters", "1", "--workers", "1", "--seed0", "17", "--out", str(out)])
    config = json.loads((out / "config.json").read_text())
    assert config["corrected_rollout"] == {"mode": "levels", "correction_worlds": 64,
                                             "residual_worlds": 16}
    assert config["baseline"] == "flat-shortlist"
