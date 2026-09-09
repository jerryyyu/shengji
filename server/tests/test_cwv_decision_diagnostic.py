import copy

import numpy as np
import pytest

from shengji.luna.game import _state_snapshot
from shengji.train.cwv_decision_diagnostic import diagnose, reference_metrics
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import play_state, round_signature


class Values:
    def score(self, states, seat, **kw):
        return np.asarray([r.attacker_points for r in states], dtype=float)

    def identity(self):
        return {"checkpoint_sha256": "a" * 64, "backend": "test"}


def test_crossfit_does_not_use_evaluation_worlds_to_select_or_clamp_losses():
    values = np.asarray([[0., 2.], [0., -2.], [0., 2.], [0., -2.]])
    out = reference_metrics(values, [0., 0.], [0, 1], 0, 0)
    assert out["descriptive_selection_regret"] == 0
    assert out["crossfit"] == {"coverage_gap": 0., "selection_gap": -1., "total_gap": -1.}
    assert out["crossfit_folds"][0]["retained_selected"] == 1
    assert out["crossfit_folds"][1]["retained_selected"] == 0


def test_decomposition_and_action_gap_control_are_not_absolute_value_error():
    values = np.asarray([[20., 21., 23.]] * 4)
    out = reference_metrics(values, [-100., -99., -97.], [0, 1], 1, 0)
    assert out["descriptive_coverage_regret"] == 2
    assert out["descriptive_selection_regret"] == 0
    assert out["crossfit"] == {"coverage_gap": 2., "selection_gap": 0., "total_gap": 2.}
    assert out["model_action_gap_mae"] == 0
    assert out["zero_action_gap_mae"] == 2


def test_single_action_cannot_publish_nan_gap():
    with pytest.raises(ValueError, match="world/action matrix"):
        reference_metrics([[1.]] * 4, [1.], [0], 0, 0)


def test_real_observed_consumer_preserves_w32_choice_and_scores(monkeypatch):
    rnd = play_state()
    before = round_signature(rnd)
    monkeypatch.setattr(CWVShortlistBot, "_rollout",
                        lambda self, rnd, seat, sampled, buried, action, **kw: float(len(action)))
    baseline = CWVShortlistBot(Values(), seed=13, reuse_successors=True,
        config=CWVShortlistConfig(worlds=1, selection_worlds=2))
    baseline.REPORT_FOLD_WORLDS = 30
    chosen = baseline.decide_play(copy.deepcopy(rnd), rnd.turn)
    root = {"id": "0" * 64, "deal_key": "fixture", "provenance": {"split": "fit"},
            "snapshot": _state_snapshot(rnd)}
    result = diagnose(root, Values(), seed=13, reference_worlds=4,
                      ranking_worlds=1, selection_worlds=2, report_worlds=30)
    assert result["played"] == chosen
    assert result["selection"]["means"] == baseline.last_decision_record["means"]
    assert result["selection"]["report_fold"] == baseline.last_decision_record["report_fold"]
    assert result["reference"]["seed"] != result["selection"]["report_fold"]["seed"]
    assert [result["model_scores"][i] for i in result["retained_indices"]] == baseline.last_shortlist["shortlist_means"]
    assert len(result["reference"]["points"]) == 4
    assert len(result["reference"]["points"][0]) == len(result["menu_indices"])
    assert before == round_signature(rnd)


def test_holdout_refused_before_reconstruction():
    with pytest.raises(ValueError, match="explicitly fit-only root"):
        diagnose({"provenance": {"split": "val"}}, Values())


@pytest.mark.parametrize("worlds", [0, 1, 3, True])
def test_bad_world_population_refuses(worlds):
    with pytest.raises(ValueError):
        diagnose({"provenance": {"split": "fit"}}, Values(), reference_worlds=worlds)
