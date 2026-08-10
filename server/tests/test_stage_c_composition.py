from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from shengji.rl import stage_c_composition as COMPOSE


class _Ensemble:
    surface = "play"
    head = "ranking"
    epoch = 8

    def __init__(self, selected: int):
        self.selected = selected

    def select(self, _obs, actions):
        return {
            "surface": self.surface,
            "head": self.head,
            "epoch": self.epoch,
            "candidate_count": len(actions),
            "selected_index": self.selected,
        }


def _round():
    return SimpleNamespace(phase="play", turn=2, banker=0)


def test_model_trigger_focuses_treatment_and_matches_null_work(monkeypatch) -> None:
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action",
                        lambda action, _rnd: [float(len(action))])
    candidates = [["H2"], ["HA"], ["S3", "S3"]]
    result = COMPOSE.focused_pairs(
        _Ensemble(2), _round(), 2, candidates, state_key="room:ply")
    assert result["model_triggered"] is True
    assert result["treatment_indices"] == [0, 2]
    assert result["null_indices"][0] == 0
    assert result["null_indices"][1] in {1, 2}
    assert result["searched_arms_treatment"] \
        == result["searched_arms_null"] == 2
    assert result["model_direct_override_authorized"] is False
    assert result["fresh_paired_report_lcb_required"] is True


def test_model_keep_has_identical_one_arm_treatment_and_null(monkeypatch) -> None:
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    candidates = [["H2"], ["HA"]]
    result = COMPOSE.focused_pairs(
        _Ensemble(0), _round(), 2, candidates, state_key="room:keep")
    assert result["treatment_candidates"] == [["H2"]]
    assert result["null_candidates"] == [["H2"]]
    assert result["fresh_paired_report_lcb_required"] is False


def test_matched_random_is_replayable_and_candidate_identity_bound(
        monkeypatch) -> None:
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    candidates = [["H2"], ["HA"], ["S3"], ["D4"]]
    first = COMPOSE.focused_pairs(
        _Ensemble(1), _round(), 2, candidates, state_key="same")
    second = COMPOSE.focused_pairs(
        _Ensemble(1), _round(), 2, copy.deepcopy(candidates), state_key="same")
    assert first["matched_random_index"] == second["matched_random_index"]
    changed = COMPOSE.focused_pairs(
        _Ensemble(1), _round(), 2, list(reversed(candidates)),
        state_key="same")
    assert first["candidate_keys"] != changed["candidate_keys"]


@pytest.mark.parametrize("candidates,match", [
    ([[]], "action"),
    ([["H2"], ["H2"]], "candidate union"),
    ([["H2"]] * 21, "candidate union"),
])
def test_candidate_union_refuses_empty_duplicate_or_over_cap(
        monkeypatch, candidates, match) -> None:
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    with pytest.raises(COMPOSE.StageCCompositionError, match=match):
        COMPOSE.focused_pairs(
            _Ensemble(0), _round(), 2, candidates, state_key="bad")


def test_wrong_turn_or_model_index_refuses(monkeypatch) -> None:
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    with pytest.raises(COMPOSE.StageCCompositionError, match="surface"):
        COMPOSE.focused_pairs(
            _Ensemble(0), _round(), 1, [["H2"]], state_key="bad-turn")
    with pytest.raises(COMPOSE.StageCCompositionError, match="selection"):
        COMPOSE.focused_pairs(
            _Ensemble(2), _round(), 2, [["H2"]], state_key="bad-index")


def test_play_wrapper_focuses_one_challenger_and_falls_back_to_full_live(
        monkeypatch) -> None:
    from shengji.ai.registry import REGISTRY

    base = REGISTRY["mc-s0-report-lcb"]
    live = [["H2"], ["HA"], ["S3"]]
    monkeypatch.setattr(base, "_candidates",
                        lambda _self, _rnd, _seat: copy.deepcopy(live))
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])

    def source(_bot, _rnd, _seat, observed):
        assert observed == live
        return observed + [["D4"]], {"source": "test"}

    bot = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(3), source, arm="treatment", seed=7)
    focused = bot._candidates(_round(), 2)
    assert focused == [["H2"], ["D4"]]
    assert bot.stage_c_focus_calls == 1
    assert bot.stage_c_focus_triggers == 1
    assert bot.stage_c_focus_fallbacks == 0
    assert bot.last_stage_c_focus_record["candidate_source"] == {
        "source": "test"}

    def broken(*_args):
        raise RuntimeError("source failed")

    fallback = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(1), broken, arm="matched-null", seed=8)
    assert fallback._candidates(_round(), 2) == live
    assert fallback.stage_c_focus_fallbacks == 1
    assert fallback.last_stage_c_focus_record[
        "fallback_to_live_ballot"] is True


def test_play_wrapper_treatment_and_null_share_triggered_arm_count(
        monkeypatch) -> None:
    from shengji.ai.registry import REGISTRY

    base = REGISTRY["mc-s0-report-lcb"]
    live = [["H2"], ["HA"], ["S3"], ["D4"]]
    monkeypatch.setattr(base, "_candidates",
                        lambda _self, _rnd, _seat: copy.deepcopy(live))
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    source = lambda _bot, _rnd, _seat, observed: (observed, {})
    treatment = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(2), source, arm="treatment", seed=1)
    null = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(2), source, arm="matched-null", seed=1)
    assert len(treatment._candidates(_round(), 2)) == 2
    assert len(null._candidates(_round(), 2)) == 2
    assert treatment.last_stage_c_focus_record["model_selected_index"] \
        == null.last_stage_c_focus_record["model_selected_index"] == 2
