"""Integration witnesses for corrected selection through the total-play cap."""
import numpy as np
import pytest

from shengji.train import cwv_shortlist_screen as screen
from shengji.train.cwv_corrected_rollout import CWVCorrectedRolloutBot
from shengji.train.screen_deadline import DeadlineSession, RECIPE
from tests.test_world_shortlist import play_state
from tests.test_cwv_shortlist_screen import cfg


class FakeEvaluator:
    checkpoint_sha256 = "a" * 64

    def identity(self):
        return {"backend": "deterministic-fake"}

    def score(self, leaves, seat):
        return np.zeros(len(leaves), dtype=np.float64)


def _small_candidates(self, rnd, seat):
    return [[rnd.hands[seat][0]], [rnd.hands[seat][1]]]


def capped_factory(config, side, seed):
    # This is the actual screen factory in the spawned worker. The substitutions
    # are local to that worker and keep the witness deterministic and tiny.
    screen.shared_evaluator = lambda *args, **kwargs: FakeEvaluator()
    CWVCorrectedRolloutBot._candidates = _small_candidates
    return screen._deadline_side(config, side, seed)


@pytest.mark.parametrize("side, expected_mode, expected_model_evaluations", [
    ("arm", "corrected", 4), ("baseline", "levels", 0)])
def test_real_deadline_consumer_preserves_corrected_metadata_and_counts(
        side, expected_mode, expected_model_evaluations):
    config = cfg("learned", checkpoint="unused", checkpoint_sha256="a" * 64,
                 baseline="levels-shortlist",
                 hybrid_bury=True, decision_deadline=dict(RECIPE),
                 shortlist={"worlds": 1, "selection_worlds": 2, "alternatives": 1,
                            "batch_size": 2, "uniform": False},
                 report_worlds=30,
                 corrected_rollout={"mode": "corrected", "correction_worlds": 2,
                                    "residual_worlds": 1})
    session = DeadlineSession(capped_factory, 30)
    try:
        policy = session.register(config, side, 17)
        rnd = play_state()
        played = policy.decide_play(rnd, rnd.turn)
        record = policy.last_decision_record
        assert played in record["candidates"]
        assert record["alloc"]["mode"] == "model-corrected-rollout-v1"
        assert record["alloc"]["correction_mode"] == expected_mode
        assert record["alloc"]["model_evaluations"] == expected_model_evaluations
        assert policy.corrected_rollout_counts["model_evaluations"] == expected_model_evaluations
        assert record["work"]["selection_rollouts"] == 2
        assert record["work"]["report_rollouts"] == 60
        assert not policy.decisions[-1]["deadline"]["timed_out"]
        counters = screen.work_counters([policy])
        assert counters["correction_model_evaluations"] == expected_model_evaluations
        assert counters["correction_sampled_worlds"] == 2
        assert counters["correction_residual_worlds"] == 1
    finally:
        session.close()


@pytest.mark.parametrize("field", ["throw_components", "wide_tail"])
def test_make_side_rejects_nonisolated_corrected_config(field, monkeypatch):
    config = cfg("learned", checkpoint="m.pt", checkpoint_sha256="a" * 64,
                 baseline="flat-shortlist",
                 corrected_rollout={"mode": "corrected", "correction_worlds": 2,
                                    "residual_worlds": 1},
                 **{field: True})
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *args, **kwargs: FakeEvaluator())
    for side in ("arm", "baseline"):
        with pytest.raises(ValueError, match="cannot be combined"):
            screen.make_side(config, side, 17)


def test_cli_rejects_corrected_throw_combination(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(SystemExit):
        screen.main([
            "--arm", "learned", "--checkpoint", str(tmp_path / "m.pt"),
            "--baseline", "flat-shortlist", "--corrected-rollout", "corrected",
            "--throw-components", "--clusters", "1", "--workers", "1",
            "--seed0", "17", "--out", str(tmp_path / "out"),
        ])
    assert "corrected-rollout" in capsys.readouterr().err


def test_capped_hybrid_control_cli_reaches_bound_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(screen, "shared_evaluator", lambda *a, **kw: FakeEvaluator())
    seen = []

    def pending(config, *args, **kwargs):
        assert config["decision_deadline"] == RECIPE
        assert config["hybrid_bury"] is True
        assert screen._recipe(config)["decision_deadline"] == RECIPE
        for side, mode in (("arm", "corrected"), ("baseline", "levels")):
            bot = screen.make_side(config, side, 17)
            assert isinstance(bot, screen.CWVCorrectedRolloutBuryBot)
            assert bot.correction_mode == mode
        seen.append(config)

    monkeypatch.setattr(screen, "_run_pending", pending)
    assert screen.main([
        "--arm", "learned", "--checkpoint", str(tmp_path / "fake.pt"),
        "--baseline", "levels-shortlist", "--corrected-rollout", "corrected",
        "--correction-worlds", "64", "--residual-worlds", "30",
        "--hybrid-bury", "--decision-deadline", "300",
        "--clusters", "1", "--workers", "1", "--seed0", "17",
        "--out", str(tmp_path / "out"),
    ]) == 0
    assert len(seen) == 1
