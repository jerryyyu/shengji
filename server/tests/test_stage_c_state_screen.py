from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from shengji.rl import stage_c_state_screen as SCREEN


def _counters(accepted: int) -> dict:
    return {
        "sample_attempts": accepted,
        "accepted_worlds": accepted,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }


def _state(*, phase: str = "mid", role: str = "attacker",
           position: str = "lead", seed: int = 10,
           state_id: str = "fresh:10:20:0") -> dict:
    return {
        "schema": "teacher-stage-c-replay-state-v1",
        "state_id": state_id,
        "seed": seed,
        "seat": 0,
        "surface_type": "play",
        "trick": 5 if phase == "mid" else 12,
        "phase": phase,
        "role": role,
        "surface": position,
    }


class _Round(SimpleNamespace):
    def is_attacker(self, _seat: int) -> bool:
        return self.role == "attacker"


def _replay(state):
    return _Round(
        phase="play", turn=state["seat"], role=state["role"],
        history=[object()] * state["trick"],
        trick=SimpleNamespace(
            plays=[] if state["surface"] == "lead" else [object()]))


def _live_decision(live: list[str], *, policy: str) -> dict:
    return {
        "schema": "mc-decision-v2",
        "policy": policy,
        "policy_class": policy,
        "candidates": [list(live), ["C4"], ["D5"]],
        "played_index": 0,
        "played": list(live),
        "reason": "report_lcb_below_min_gain",
        "search_secs": 0.01 if policy == "treatment" else 9.99,
    }


def _focused(arm: str, *, played: list[str], live: list[str],
             elapsed: float = 0.1) -> dict:
    challenger_index = 1 if arm == "treatment" else 2
    return {
        "schema": "teacher-stage-c-focused-proposal-v1",
        "surface": "play",
        "arm": arm,
        "candidate_count": 3,
        "candidate_source": {"schema": "source", "identity": "same"},
        "candidate_keys": [["H2"], ["HA"], ["S3"]],
        "head": "ranking",
        "epoch": 32,
        "state_key": "shared-state-key",
        "matched_random_index": 2,
        "treatment_candidates": [["H2"], ["HA"]],
        "null_candidates": [["H2"], ["S3"]],
        "selection": {
            "surface": "play", "head": "ranking", "epoch": 32,
            "candidate_count": 3, "selected_index": 1,
        },
        "scope_diagnostic": {
            "eligible": True,
            "evaluation_complete": True,
            "worlds": 30,
            "attempts": 30,
            "candidate_worlds": 90,
            "sampler_counters": _counters(30),
            "elapsed_seconds": elapsed,
        },
        "fallback_to_live_ballot": False,
        "model_triggered": True,
        "fresh_paired_report_lcb_required": True,
        "model_direct_override_authorized": False,
        "model_selected_index": 1,
        "incumbent_index": 0,
        "treatment_indices": [0, 1],
        "null_indices": [0, 2],
        "searched_arms_treatment": 2,
        "searched_arms_null": 2,
        "challenger_candidate_union_index": challenger_index,
        "live_incumbent": list(live),
        "played": list(played),
        "reason": ("stage_c_report_lcb_below_min_gain"
                   if sorted(played) == sorted(live)
                   else "stage_c_report_lcb_override"),
        "work": {
            "report_budget": 600,
            "report_rollouts": 600,
            "complete": True,
        },
        "report_fold": {
            "worlds": 300, "attempts": 300, "rejected": 0,
            "complete": True,
        },
        "report_seed": 12345,
        "sampler_counters": {"delta": _counters(300)},
        "live_policy_decision": _live_decision(live, policy=arm),
    }


class _Policy:
    stage_c_min_completed_tricks = 5

    def __init__(self, played: list[str], record: dict | None = None,
                 *, policy: str = "champion"):
        self.played = played
        self.last_stage_c_focus_record = record
        self.last_decision_record = _live_decision(played, policy=policy)

    def decide_play(self, _rnd, _seat):
        return list(self.played)


def _factories(*, treatment=("HA",), matched_null=("S3",), live=("H2",)):
    seen = []

    def treatment_factory(seed):
        seen.append(("treatment", seed))
        played = list(treatment)
        bot = _Policy(played, _focused(
            "treatment", played=played, live=list(live), elapsed=0.1),
            policy="treatment")
        bot.last_decision_record = copy.deepcopy(
            bot.last_stage_c_focus_record["live_policy_decision"])
        return bot

    def null_factory(seed):
        seen.append(("matched_null", seed))
        played = list(matched_null)
        bot = _Policy(played, _focused(
            "matched-null", played=played, live=list(live), elapsed=9.9),
            policy="matched-null")
        bot.last_decision_record = copy.deepcopy(
            bot.last_stage_c_focus_record["live_policy_decision"])
        return bot

    def champion_factory(seed):
        seen.append(("champion", seed))
        return _Policy(list(live), policy="champion")

    return treatment_factory, null_factory, champion_factory, seen


def _evaluation_fold(values=(1.5, -1.5, -1.5), seen=None):
    inverse = {-3.5: 0, -2.5: 1, -1.5: 40, 0.5: 80,
               1.5: 120, 2.5: 160, 3.5: 200}

    def run(rnd, _seat, actions, seed):
        if seen is not None:
            seen.append((copy.deepcopy(actions), seed))
        hashes = [f"{index:064x}" for index in range(300)]
        sampler = {
            "schema": SCREEN.LABEL_SAMPLER_SCHEMA,
            "fold": "report",
            "seed": seed,
            "requested": SCREEN.EVALUATION_WORLDS,
            "accepted": SCREEN.EVALUATION_WORLDS,
            "accepted_draws": SCREEN.EVALUATION_WORLDS,
            "attempts": SCREEN.EVALUATION_WORLDS,
            "attempt_cap": (SCREEN.EVALUATION_WORLDS
                            * SCREEN.SAMPLE_ATTEMPT_FACTOR),
            "counters": _counters(SCREEN.EVALUATION_WORLDS),
            "world_key_sha256s": hashes,
            "world_keys_sha256": __import__("hashlib").sha256(
                SCREEN._canonical_json(hashes)).hexdigest(),
            "unique_worlds": SCREEN.EVALUATION_WORLDS,
            "duplicate_draws_retained": 0,
            "prior_fold_overlap_draws_retained": 0,
            "sampling_with_replacement": True,
            "domain_separated_stream": True,
            "complete": True,
        }
        fold_work = {
            "selection": 0,
            "report": 3 * SCREEN.EVALUATION_WORLDS,
            "audit_selection": 0,
            "audit_report": 0,
        }
        signed = list(values)
        raw = [inverse[value if rnd.role == "attacker" else -value]
               for value in signed]
        return {
            "schema": SCREEN.EVALUATION_FOLD_SCHEMA,
            "seed": seed,
            "worlds": SCREEN.EVALUATION_WORLDS,
            "candidate_worlds": 3 * SCREEN.EVALUATION_WORLDS,
            "complete": True,
            "sampler": sampler,
            "work": {
                "schema": SCREEN.LABEL_WORK_SCHEMA,
                "candidate_worlds_attempted": fold_work,
                "candidate_worlds_completed": fold_work,
                "total_candidate_worlds_attempted":
                    3 * SCREEN.EVALUATION_WORLDS,
                "total_candidate_worlds_completed":
                    3 * SCREEN.EVALUATION_WORLDS,
                "samplers": {"report": sampler},
                "sampler_sequence": ["report"],
                "accounting_complete": True,
            },
            "actions": [{
                "logical_index": index,
                "candidate_index": index,
                "cards": list(action),
                "sources": [["treatment_final"],
                            ["matched_null_final"],
                            ["literal_live_final"]][index],
                "raw_attacker_points": [float(raw[index])]
                * SCREEN.EVALUATION_WORLDS,
                "signed_level_utility": [signed[index]]
                * SCREEN.EVALUATION_WORLDS,
                "mean_signed_level_utility": signed[index],
            } for index, action in enumerate(actions)],
        }
    return run


def _run(*, state=None, values=(1.5, -1.5, -1.5), **kwargs):
    treatment, null, champion, seen = _factories(**kwargs)
    evaluation_seen = []
    result = SCREEN.run_state(
        _state() if state is None else state, replay=_replay,
        treatment_factory=treatment,
        matched_null_factory=null,
        champion_factory=champion,
        evaluation_fold=_evaluation_fold(values=values, seen=evaluation_seen),
    )
    return result, seen, evaluation_seen


def test_run_state_uses_shared_decision_seed_and_independent_evaluation() -> None:
    result, seen, evaluation_seen = _run()
    policy_seeds = {seed for _name, seed in seen}
    assert len(policy_seeds) == 1
    assert result["selection"]["policy_seed"] == next(iter(policy_seeds))
    assert result["evaluation_seed"] != result["selection"]["policy_seed"]
    assert evaluation_seen == [(
        [["HA"], ["S3"], ["H2"]], result["evaluation_seed"])]
    assert result["deltas"] == {
        "treatment_minus_live": 3.0,
        "treatment_minus_matched_null": 3.0,
        "matched_null_minus_live": 0.0,
    }
    assert result["whole_game_launch_authorized"] is False


def test_selection_can_be_frozen_before_evaluation_is_opened() -> None:
    treatment, null, champion, _seen = _factories()
    selection = SCREEN.select_state(
        _state(), replay=_replay,
        treatment_factory=treatment,
        matched_null_factory=null,
        champion_factory=champion)
    assert selection["schema"] == SCREEN.SELECTION_SCHEMA
    assert selection["evaluation_opened"] is False
    assert "evaluation_fold" not in selection
    assert selection["selection_sha256"] == SCREEN._self_hash(
        selection, "selection_sha256")
    result = SCREEN.evaluate_selected(
        _state(), selection, replay=_replay,
        evaluation_fold=_evaluation_fold())
    assert result["selection"] == selection
    assert result["evaluation_fold"]["worlds"] == 300


def test_selection_classifies_safe_model_keep_as_ineligible() -> None:
    treatment, null, champion, _seen = _factories()

    def keep_factory(seed):
        bot = treatment(seed)
        bot.last_stage_c_focus_record["model_triggered"] = False
        bot.last_stage_c_focus_record["reason"] = "model_kept_live_incumbent"
        bot.last_stage_c_focus_record["report_fold"] = None
        return bot

    with pytest.raises(SCREEN.StageCStateIneligible,
                       match="model_kept_live_incumbent"):
        SCREEN.select_state(
            _state(), replay=_replay,
            treatment_factory=keep_factory,
            matched_null_factory=null,
            champion_factory=champion)


def test_run_state_preserves_logical_duplicate_actions_and_exact_work() -> None:
    result, _seen, evaluation_seen = _run(
        treatment=("H2",), matched_null=("H2",), live=("H2",))
    assert evaluation_seen[0][0] == [["H2"], ["H2"], ["H2"]]
    assert result["evaluation_fold"]["candidate_worlds"] == 900


def test_run_state_refuses_early_or_wrong_surface() -> None:
    treatment, null, champion, _seen = _factories()
    for changed in (
        {**_state(), "phase": "early", "trick": 4},
        {**_state(), "surface_type": "bury"},
    ):
        with pytest.raises(SCREEN.StageCStateScreenError, match="identity"):
            SCREEN.run_state(
                changed, replay=_replay,
                treatment_factory=treatment,
                matched_null_factory=null,
                champion_factory=champion,
                evaluation_fold=_evaluation_fold())


def test_run_state_refuses_live_or_arm_identity_drift() -> None:
    treatment, null, _champion, _seen = _factories()
    with pytest.raises(SCREEN.StageCStateScreenError, match="identity drift"):
        SCREEN.run_state(
            _state(), replay=_replay,
            treatment_factory=treatment,
            matched_null_factory=null,
            champion_factory=lambda _seed: _Policy(["D4"]),
            evaluation_fold=_evaluation_fold())


def test_select_state_refuses_underlying_live_decision_drift() -> None:
    treatment, null, champion, _seen = _factories()

    def drifted_null(seed):
        bot = null(seed)
        bot.last_stage_c_focus_record["live_policy_decision"][
            "reason"] = "different_live_path"
        return bot

    with pytest.raises(SCREEN.StageCStateScreenError,
                       match="decision identity drift"):
        SCREEN.select_state(
            _state(), replay=_replay, treatment_factory=treatment,
            matched_null_factory=drifted_null,
            champion_factory=champion)


def test_run_state_refuses_evaluation_work_mutation() -> None:
    treatment, null, champion, _seen = _factories()

    def underfilled(rnd, seat, actions, seed):
        value = _evaluation_fold()(rnd, seat, actions, seed)
        value["candidate_worlds"] = 899
        return value

    with pytest.raises(SCREEN.StageCStateScreenError,
                       match="evaluation-fold drift"):
        SCREEN.run_state(
            _state(), replay=_replay,
            treatment_factory=treatment,
            matched_null_factory=null,
            champion_factory=champion,
            evaluation_fold=underfilled)


@pytest.mark.parametrize("mutation", ("work", "world-hash", "utility"))
def test_record_validator_reopens_full_evaluation_evidence(
        mutation: str) -> None:
    result, _seen, _evaluation_seen = _run()
    forged = copy.deepcopy(result)
    if mutation == "work":
        forged["evaluation_fold"]["work"][
            "total_candidate_worlds_completed"] = 899
    elif mutation == "world-hash":
        forged["evaluation_fold"]["sampler"][
            "world_key_sha256s"][0] = "f" * 64
    else:
        forged["evaluation_fold"]["actions"][0][
            "signed_level_utility"][0] = -3.5
    forged["record_sha256"] = SCREEN._self_hash(
        forged, "record_sha256")
    with pytest.raises(SCREEN.StageCStateScreenError,
                       match="evaluation|utility"):
        SCREEN._validate_record(forged)


def _aggregate_records(*, treatment=1.5, null=-1.5) -> list[dict]:
    records = []
    index = 0
    for phase in SCREEN.PHASES:
        for role in SCREEN.ROLES:
            for _ in range(SCREEN.TARGET_PER_CELL):
                state = _state(
                    phase=phase, role=role, seed=1_000_000 + index,
                    state_id=f"fresh:{index}")
                records.append(_run(
                    state=state, values=(treatment, null, -1.5))[0])
                index += 1
    return records


def test_aggregate_pass_authorizes_design_only() -> None:
    result = SCREEN.aggregate(
        _aggregate_records(), forbidden_deal_seeds=[1, 2, 3])
    assert result["decision"] == "AUTHORIZE_WHOLE_GAME_SCREEN_DESIGN"
    assert all(result["gates"].values())
    assert result["whole_game_screen_design_authorized"] is True
    assert result["whole_game_launch_authorized"] is False
    assert result["strength_claim"] is False


def test_aggregate_selects_none_when_model_does_not_beat_null() -> None:
    result = SCREEN.aggregate(
        _aggregate_records(treatment=-1.5, null=-1.5),
        forbidden_deal_seeds=[])
    assert result["decision"] == "SELECT_NONE"
    assert result["gates"]["treatment_minus_live_lcb_gt_zero"] is False


def test_aggregate_requires_unique_fresh_deals_and_exact_cells() -> None:
    duplicate = _aggregate_records()
    duplicate[1]["selection"]["deal_seed"] = \
        duplicate[0]["selection"]["deal_seed"]
    duplicate[1]["selection"]["policy_seed"] = SCREEN._seed(
        {"state_id": duplicate[1]["selection"]["state_id"],
         "seed": duplicate[1]["selection"]["deal_seed"]}, "decision")
    duplicate[1]["evaluation_seed"] = SCREEN._seed(
        {"state_id": duplicate[1]["selection"]["state_id"],
         "seed": duplicate[1]["selection"]["deal_seed"]},
        "independent-evaluation")
    duplicate[1]["evaluation_fold"]["seed"] = duplicate[1]["evaluation_seed"]
    duplicate[1]["evaluation_fold"]["sampler"]["seed"] = \
        duplicate[1]["evaluation_seed"]
    duplicate[1]["selection"]["selection_sha256"] = SCREEN._self_hash(
        duplicate[1]["selection"], "selection_sha256")
    duplicate[1]["record_sha256"] = SCREEN._self_hash(
        duplicate[1], "record_sha256")
    with pytest.raises(SCREEN.StageCStateScreenError, match="quota drift"):
        SCREEN.aggregate(duplicate, forbidden_deal_seeds=[])

    forbidden = _aggregate_records()
    with pytest.raises(SCREEN.StageCStateScreenError, match="quota drift"):
        SCREEN.aggregate(
            forbidden, forbidden_deal_seeds=[
                forbidden[0]["selection"]["deal_seed"]])

    cells = _aggregate_records()
    cells[0]["selection"]["role"] = "defender"
    cells[0]["selection"]["cell"] = "mid:defender"
    for row in cells[0]["evaluation_fold"]["actions"]:
        row["signed_level_utility"] = [
            -value for value in row["signed_level_utility"]]
        row["mean_signed_level_utility"] *= -1
    utilities = [row["signed_level_utility"][0]
                 for row in cells[0]["evaluation_fold"]["actions"]]
    cells[0]["deltas"] = {
        "treatment_minus_live": utilities[0] - utilities[2],
        "treatment_minus_matched_null": utilities[0] - utilities[1],
        "matched_null_minus_live": utilities[1] - utilities[2],
    }
    cells[0]["selection"]["selection_sha256"] = SCREEN._self_hash(
        cells[0]["selection"], "selection_sha256")
    cells[0]["record_sha256"] = SCREEN._self_hash(
        cells[0], "record_sha256")
    with pytest.raises(SCREEN.StageCStateScreenError, match="quota drift"):
        SCREEN.aggregate(cells, forbidden_deal_seeds=[])


def test_aggregate_reports_null_live_without_turning_it_into_third_gate() -> None:
    result = SCREEN.aggregate(
        _aggregate_records(treatment=2.5, null=1.5),
        forbidden_deal_seeds=[])
    assert result["decision"] == "AUTHORIZE_WHOLE_GAME_SCREEN_DESIGN"
    assert result["diagnostics"][
        "matched_null_minus_live_interval_contains_zero"] is False


def test_aggregate_recomputes_deltas_instead_of_trusting_shard_summary() -> None:
    records = _aggregate_records()
    records[0]["deltas"]["treatment_minus_live"] = 99.0
    records[0]["record_sha256"] = SCREEN._self_hash(
        records[0], "record_sha256")
    with pytest.raises(SCREEN.StageCStateScreenError,
                       match="delta recomputation"):
        SCREEN.aggregate(records, forbidden_deal_seeds=[])
