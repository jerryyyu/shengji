from __future__ import annotations

import copy
import random
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


class _BuryEnsemble(_Ensemble):
    surface = "bury"


class _Round(SimpleNamespace):
    def play(self, _seat, _cards):
        return None

    def bury(self, _seat, _cards):
        return None

    def is_attacker(self, _seat):
        return True


def _round():
    return _Round(phase="play", turn=2, banker=0)


def _bury_round():
    return _Round(phase="bury", turn=None, banker=0)


def _eligible_scope(candidate_count: int) -> dict:
    return {
        "schema": "teacher-stage-c-live-uncertainty-selection-v1",
        "evaluation_complete": True,
        "eligible": True,
        "reason": "eligible",
        "candidate_worlds": 30 * candidate_count,
    }


def _patch_live_parent(monkeypatch, live, *, incumbent_index: int = 1):
    from shengji.ai.registry import REGISTRY

    base = REGISTRY["mc-s0-report-lcb"]
    monkeypatch.setattr(
        base, "_candidates",
        lambda _self, _rnd, _seat: copy.deepcopy(live))

    def decide(self, _rnd, _seat):
        self.last_decision_record = {
            "schema": "mc-decision-v2",
            "candidates": copy.deepcopy(live),
            "reason": "report_lcb_override",
            "played_index": incumbent_index,
        }
        return list(live[incumbent_index])

    monkeypatch.setattr(base, "decide_play", decide)
    monkeypatch.setattr(COMPOSE, "Memory", lambda *_args, **_kw: object())
    monkeypatch.setattr(
        base, "_report_fold_gap",
        lambda *_args, **_kw: {
            "gap": 2.0, "se": 0.1, "worlds": 300,
            "attempts": 300, "rejected": 0, "complete": True,
            "seed": _kw["seed"],
        })
    return base


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


def test_protected_incumbent_need_not_be_capture_candidate_zero(
        monkeypatch) -> None:
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    candidates = [["H2"], ["HA"], ["S3"], ["D4"]]
    result = COMPOSE.focused_pairs(
        _Ensemble(2), _round(), 2, candidates, state_key="protected",
        protected_incumbent=["HA"])
    assert result["incumbent_index"] == 1
    assert result["treatment_indices"] == [1, 2]
    assert result["null_indices"][0] == 1
    assert result["null_indices"][1] != 1


def test_uncertainty_scope_replays_capture_arithmetic_without_rng_drift(
        monkeypatch) -> None:
    monkeypatch.setattr(COMPOSE, "Memory", lambda *_args, **_kw: object())
    class Bot:
        MARGIN = 5.0
        BANKER_KITTY = True

        def __init__(self):
            self.rng = random.Random(17)
            self.search_calls = self.rollouts = self.short_search_decisions = 0
            self.search_secs = 0.0
            self.sample_attempts = self.accepted_worlds = 0
            self.failed_worlds = self.rejected_worlds = 0
            self.impossible_worlds = 0

        def _sampler_snapshot(self):
            return {name: getattr(self, name) for name in (
                "sample_attempts", "accepted_worlds", "failed_worlds",
                "rejected_worlds", "impossible_worlds")}

        def _sampler_delta(self, before):
            return {name: getattr(self, name) - value
                    for name, value in before.items()}

        def _sample_hands(self, _rnd, _seat, _mem):
            self.sample_attempts += 1
            self.accepted_worlds += 1
            return {}, []

        @staticmethod
        def _rollout(_rnd, _seat, _hands, _buried, candidate):
            return 5.0 if candidate == ["HA"] else 0.0

        @staticmethod
        def _score(value):
            return value

        @staticmethod
        def _pick_index(_candidates, means, indices):
            return max(indices, key=lambda index: means[index])

    bot = Bot()
    rnd = _round()
    before_rng = bot.rng.getstate()
    result = COMPOSE.champion_uncertainty_diagnostic(
        bot, rnd, 2, [["H2"], ["HA"]], state_key="public")
    assert result["eligible"] is True
    assert result["raw_best_index"] == 1
    assert result["paired_gap_vs_candidate0"] == 5.0
    assert result["paired_se_vs_candidate0"] == 0.0
    assert result["worlds"] == 30
    assert result["candidate_worlds"] == 60
    assert bot.search_calls == 1 and bot.rollouts == 60
    assert bot.rng.getstate() == before_rng


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
    live = [["H2"], ["HA"], ["S3"]]
    _patch_live_parent(monkeypatch, live, incumbent_index=1)
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(
        COMPOSE, "champion_uncertainty_diagnostic",
        lambda _bot, _rnd, _seat, candidates, **_kw:
            _eligible_scope(len(candidates)))

    def source(_bot, _rnd, _seat, observed):
        assert observed == live
        return observed + [["D4"]], {"source": "test"}

    bot = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(3), source, arm="treatment", seed=7)
    assert bot._candidates(_round(), 2) == live
    assert bot.decide_play(_round(), 2) == ["D4"]
    assert bot.stage_c_focus_calls == 1
    assert bot.stage_c_focus_triggers == 1
    assert bot.stage_c_focus_fallbacks == 0
    assert bot.last_stage_c_focus_record["candidate_source"] == {
        "source": "test"}

    def broken(*_args):
        raise RuntimeError("source failed")

    fallback = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(1), broken, arm="matched-null", seed=8)
    assert fallback.decide_play(_round(), 2) == ["HA"]
    assert fallback.stage_c_focus_fallbacks == 1
    assert fallback.last_stage_c_focus_record[
        "fallback_to_live_ballot"] is True


def test_play_wrapper_phase_gate_precedes_source_scope_and_model(
        monkeypatch) -> None:
    live = [["H2"], ["HA"]]
    _patch_live_parent(monkeypatch, live, incumbent_index=1)

    class MustNotRun(_Ensemble):
        def select(self, _obs, _actions):
            raise AssertionError("Stage C ran in an early state")

    calls = []

    def source(*_args):
        calls.append("source")
        raise AssertionError("candidate source ran in an early state")

    monkeypatch.setattr(
        COMPOSE, "champion_uncertainty_diagnostic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("scope ran in an early state")))
    bot = COMPOSE.make_play_report_lcb_bot(
        MustNotRun(1), source, arm="treatment", seed=7,
        min_completed_tricks=5)
    rnd = _round()
    rnd.history = [object()] * 4
    assert bot.decide_play(rnd, 2) == ["HA"]
    assert calls == []
    assert bot.stage_c_focus_calls == 0
    assert bot.stage_c_scope_checks == 0
    assert bot.stage_c_focus_triggers == 0
    assert bot.last_stage_c_focus_record is None
    assert bot.last_decision_record["played_index"] == 1


def test_play_wrapper_phase_gate_opens_at_exact_threshold(monkeypatch) -> None:
    live = [["H2"], ["HA"]]
    _patch_live_parent(monkeypatch, live, incumbent_index=0)
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(
        COMPOSE, "champion_uncertainty_diagnostic",
        lambda _bot, _rnd, _seat, candidates, **_kw:
            _eligible_scope(len(candidates)))
    calls = []

    def source(_bot, _rnd, _seat, observed):
        calls.append("source")
        return observed, {"source": "threshold-test"}

    bot = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(1), source, arm="treatment", seed=7,
        min_completed_tricks=5)
    rnd = _round()
    rnd.history = [object()] * 5
    assert bot.decide_play(rnd, 2) == ["HA"]
    assert calls == ["source"]
    assert bot.stage_c_focus_calls == 1
    assert bot.stage_c_scope_checks == 1
    assert bot.stage_c_focus_triggers == 1


@pytest.mark.parametrize("threshold", (True, -1, 1.5, "5"))
def test_play_wrapper_rejects_invalid_phase_threshold(
        monkeypatch, threshold) -> None:
    _patch_live_parent(monkeypatch, [["H2"]], incumbent_index=0)
    with pytest.raises(COMPOSE.StageCCompositionError, match="threshold"):
        COMPOSE.make_play_report_lcb_bot(
            _Ensemble(0), lambda *_args: ([["H2"]], {}),
            arm="treatment", min_completed_tricks=threshold)


def test_play_wrapper_treatment_and_null_share_triggered_arm_count(
        monkeypatch) -> None:
    live = [["H2"], ["HA"], ["S3"], ["D4"]]
    _patch_live_parent(monkeypatch, live, incumbent_index=1)
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(
        COMPOSE, "champion_uncertainty_diagnostic",
        lambda _bot, _rnd, _seat, candidates, **_kw:
            _eligible_scope(len(candidates)))
    source = lambda _bot, _rnd, _seat, observed: (observed, {})
    treatment = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(2), source, arm="treatment", seed=1)
    null = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(2), source, arm="matched-null", seed=1)
    treatment.decide_play(_round(), 2)
    null.decide_play(_round(), 2)
    assert treatment.last_stage_c_focus_record["model_selected_index"] \
        == null.last_stage_c_focus_record["model_selected_index"] == 2
    assert treatment.last_stage_c_focus_record["incumbent_index"] == 1
    assert null.last_stage_c_focus_record["incumbent_index"] == 1
    assert treatment.last_stage_c_focus_record["searched_arms_treatment"] \
        == null.last_stage_c_focus_record["searched_arms_null"] == 2


def test_outside_scope_never_invokes_stage_c_and_keeps_live_action(
        monkeypatch) -> None:
    live = [["H2"], ["HA"]]
    _patch_live_parent(monkeypatch, live, incumbent_index=1)
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(
        COMPOSE, "champion_uncertainty_diagnostic",
        lambda _bot, _rnd, _seat, candidates, **_kw: {
            **_eligible_scope(len(candidates)),
            "eligible": False,
            "reason": "outside_uncertainty_window",
        })

    class MustNotRun(_Ensemble):
        def select(self, _obs, _actions):
            raise AssertionError("Stage C ran before its public scope gate")

    source = lambda *_args: (copy.deepcopy(live), {})
    bot = COMPOSE.make_play_report_lcb_bot(
        MustNotRun(0), source, arm="treatment", seed=4)
    assert bot.decide_play(_round(), 2) == ["HA"]
    telemetry = COMPOSE.stage_c_policy_telemetry([bot])
    assert telemetry["scope_ineligible"] == 1
    assert telemetry["scope_eligible"] == 0
    assert telemetry["model_triggers"] == 0


def test_stage_c_policy_telemetry_reconciles_zero_fallback_run() -> None:
    bot = SimpleNamespace(
        stage_c_focus_calls=7,
        stage_c_scope_checks=7,
        stage_c_scope_eligible=7,
        stage_c_scope_ineligible=0,
        stage_c_scope_candidate_rollouts=2_100,
        stage_c_model_keeps=3,
        stage_c_focus_triggers=4,
        stage_c_focus_fallbacks=0,
        stage_c_report_overrides=1,
        stage_c_report_rejections=2,
        stage_c_report_underfills=1,
    )
    result = COMPOSE.stage_c_policy_telemetry([bot])
    assert result["focus_calls"] == 7
    assert result["model_triggers"] == 4
    assert result["exact_reconciliation"] is True
    bot.stage_c_report_underfills = 0
    with pytest.raises(COMPOSE.StageCCompositionError, match="reconcile"):
        COMPOSE.stage_c_policy_telemetry([bot])


def test_play_wrapper_records_closed_activation_telemetry(monkeypatch) -> None:
    live = [["H2"], ["HA"]]
    _patch_live_parent(monkeypatch, live, incumbent_index=0)
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(
        COMPOSE, "champion_uncertainty_diagnostic",
        lambda _bot, _rnd, _seat, candidates, **_kw:
            _eligible_scope(len(candidates)))
    source = lambda *_args: (copy.deepcopy(live), {})
    bot = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(1), source, arm="treatment", seed=3)
    assert bot.decide_play(_round(), 2) == ["HA"]
    telemetry = COMPOSE.stage_c_policy_telemetry([bot])
    assert telemetry["focus_calls"] == telemetry["model_triggers"] == 1
    assert telemetry["report_overrides"] == 1
    assert telemetry["fallbacks"] == 0
    assert telemetry["exact_reconciliation"] is True


def test_wrapper_refuses_parent_contract_drift(monkeypatch) -> None:
    from shengji.ai.registry import REGISTRY

    base = REGISTRY["mc-s0-report-lcb"]
    monkeypatch.setattr(base, "REPORT_FOLD_WORLDS", 299)
    with pytest.raises(COMPOSE.StageCCompositionError, match="exact live"):
        COMPOSE.make_play_report_lcb_bot(
            _Ensemble(1), lambda *_args: ([['H2']], {}),
            arm="treatment", seed=1)


def test_play_wrapper_falls_back_when_source_candidate_is_illegal(
        monkeypatch) -> None:
    live = [["H2"], ["HA"]]
    _patch_live_parent(monkeypatch, live, incumbent_index=1)
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])

    class Round(SimpleNamespace):
        def __deepcopy__(self, _memo):
            return self

        def play(self, _seat, cards):
            if cards == ["BAD"]:
                raise ValueError("not held")

    rnd = Round(phase="play", turn=2, banker=0)
    source = lambda *_args: (live + [["BAD"]], {})
    bot = COMPOSE.make_play_report_lcb_bot(
        _Ensemble(2), source, arm="treatment", seed=2)
    assert bot.decide_play(rnd, 2) == ["HA"]
    assert bot.stage_c_focus_fallbacks == 1
    assert "replay-illegal" in bot.last_stage_c_focus_record["failure"]


def test_bury_report_fold_uses_fresh_paired_banker_values() -> None:
    class Bot:
        SAMPLE_ATTEMPT_FACTOR = 3

        def __init__(self):
            self.rng = random.Random(11)

        @staticmethod
        def _sample_hands(_rnd, _seat, _mem):
            return {1: [], 2: [], 3: []}, []

        @staticmethod
        def _score(value):
            return float(value)

        @staticmethod
        def _rollout_from_bury(_rnd, _seat, _hands, cards):
            return 10.0 if cards == ["LOW"] else 20.0

        @staticmethod
        def _paired_se(_d_sum, _d_sq, _n):
            return 0.0

    bot = Bot()
    original_state = bot.rng.getstate()
    report = COMPOSE._bury_report_fold_gap(
        bot, object(), 0, object(), ["LOW"], ["HIGH"], 3, seed=99)
    assert report == {
        "gap": 10.0, "se": 0.0, "worlds": 3, "attempts": 3,
        "rejected": 0, "complete": True, "seed": 99,
    }
    assert bot.rng.getstate() == original_state


def test_bury_wrapper_requires_fresh_lcb_before_model_override(
        monkeypatch) -> None:
    from shengji.ai.registry import REGISTRY

    base = REGISTRY["mc-s0-report-lcb"]
    incumbent = ["H2"] * 8
    challenger = ["HA"] * 8
    third = ["S3"] * 8
    monkeypatch.setattr(base, "decide_bury",
                        lambda _self, _rnd, _seat: list(incumbent))
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(COMPOSE, "Memory", lambda *_args, **_kw: object())

    def source(_bot, _rnd, _seat, observed):
        assert observed == [incumbent]
        return [incumbent, challenger, third], {"source": "test"}

    monkeypatch.setattr(COMPOSE, "_bury_report_fold_gap",
                        lambda *_args, **_kw: {
                            "gap": 2.0, "se": 0.25, "worlds": 300,
                            "attempts": 300, "rejected": 0,
                            "complete": True, "seed": _kw["seed"],
                        })
    bot = COMPOSE.make_bury_report_lcb_bot(
        _BuryEnsemble(2), source, arm="treatment", seed=7)
    assert bot.decide_bury(_bury_round(), 0) == third
    record = bot.last_stage_c_focus_record
    assert record["reason"] == "report_lcb_override"
    assert record["played_candidate_union_index"] == 2
    assert record["work"] == {
        "report_budget": 600, "report_rollouts": 600, "complete": True}
    assert bot.stage_c_focus_triggers == 1
    assert bot.stage_c_focus_fallbacks == 0


def test_bury_wrapper_keeps_incumbent_on_negative_or_underfilled_report(
        monkeypatch) -> None:
    from shengji.ai.registry import REGISTRY

    base = REGISTRY["mc-s0-report-lcb"]
    incumbent = ["H2"] * 8
    challenger = ["HA"] * 8
    monkeypatch.setattr(base, "decide_bury",
                        lambda _self, _rnd, _seat: list(incumbent))
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(COMPOSE, "Memory", lambda *_args, **_kw: object())
    source = lambda *_args: ([incumbent, challenger], {})

    outcomes = iter([
        {"gap": -1.0, "se": 0.1, "worlds": 300, "attempts": 300,
         "rejected": 0, "complete": True, "seed": 1},
        {"gap": 1.0, "se": float("inf"), "worlds": 0, "attempts": 1200,
         "rejected": 1200, "complete": False, "seed": 2},
    ])
    monkeypatch.setattr(COMPOSE, "_bury_report_fold_gap",
                        lambda *_args, **_kw: next(outcomes))
    bot = COMPOSE.make_bury_report_lcb_bot(
        _BuryEnsemble(1), source, arm="treatment", seed=8)
    assert bot.decide_bury(_bury_round(), 0) == incumbent
    assert bot.last_stage_c_focus_record["reason"] \
        == "report_lcb_below_min_gain"
    assert bot.decide_bury(_bury_round(), 0) == incumbent
    assert bot.last_stage_c_focus_record["reason"] == "report_underfilled"
    assert bot.stage_c_report_underfills == 1


def test_bury_treatment_and_null_share_trigger_and_report_stream(
        monkeypatch) -> None:
    from shengji.ai.registry import REGISTRY

    base = REGISTRY["mc-s0-report-lcb"]
    candidates = [[card] * 8 for card in ("H2", "HA", "S3", "D4")]
    monkeypatch.setattr(base, "decide_bury",
                        lambda _self, _rnd, _seat: list(candidates[0]))
    monkeypatch.setattr(COMPOSE, "encode_obs", lambda _rnd, _seat: [0.0])
    monkeypatch.setattr(COMPOSE, "encode_action", lambda _action, _rnd: [0.0])
    monkeypatch.setattr(COMPOSE, "Memory", lambda *_args, **_kw: object())
    source = lambda *_args: (copy.deepcopy(candidates), {})
    calls = []

    def report(_bot, _rnd, _seat, _mem, challenger, incumbent, _n, **kw):
        calls.append((list(challenger), list(incumbent), kw["seed"]))
        return {
            "gap": 2.0, "se": 0.25, "worlds": 300, "attempts": 300,
            "rejected": 0, "complete": True, "seed": kw["seed"],
        }

    monkeypatch.setattr(COMPOSE, "_bury_report_fold_gap", report)
    treatment = COMPOSE.make_bury_report_lcb_bot(
        _BuryEnsemble(3), source, arm="treatment", seed=77)
    null = COMPOSE.make_bury_report_lcb_bot(
        _BuryEnsemble(3), source, arm="matched-null", seed=77)
    treatment.decide_bury(_bury_round(), 0)
    null.decide_bury(_bury_round(), 0)
    assert len(calls) == 2
    assert calls[0][2] == calls[1][2]
    assert calls[0][0] == candidates[3]
    assert calls[0][1] == calls[1][1] == candidates[0]
    assert len(treatment.last_stage_c_focus_record["treatment_indices"]) == 2
    assert len(null.last_stage_c_focus_record["null_indices"]) == 2
    assert treatment.last_stage_c_focus_record["work"] \
        == null.last_stage_c_focus_record["work"]
