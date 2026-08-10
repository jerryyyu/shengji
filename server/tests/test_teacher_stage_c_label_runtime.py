from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).parents[1] / "scripts" /
          "teacher_stage_c_label_runtime.py")
SPEC = importlib.util.spec_from_file_location("stage_c_label_runtime", SCRIPT)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
SPEC.loader.exec_module(runtime)


class FakeRound:
    def __init__(self, attacker: bool = True):
        self.attacker = attacker

    def is_attacker(self, _seat: int) -> bool:
        return self.attacker


def _state(*, stratum: str = "ordinary_anchor", candidates: int = 2) -> dict:
    return {
        "state_id": "DESIGN:170000000:4:0",
        "split": "DESIGN",
        "surface_type": "play",
        "stratum": stratum,
        "seat": 0,
        "candidates": [
            {"cards": [f"C{index + 2}"], "sources": [f"source-{index}"]}
            for index in range(candidates)
        ],
    }


def _fold_runner(selection_values: list[float],
                 report_values: list[float]):
    def run(_rnd, state, indices, count, purpose, ledger):
        values = selection_values if purpose.endswith("selection") \
            else report_values
        sampler = {
            "schema": runtime.SAMPLER_SCHEMA,
            "fold": purpose,
            "seed": runtime.seed_for(state, purpose),
            "requested": count,
            "accepted": count,
            "attempts": count,
            "attempt_cap": count * runtime.SAMPLE_ATTEMPT_FACTOR,
            "counters": {
                "sample_attempts": count, "accepted_worlds": count,
                "failed_worlds": 0, "rejected_worlds": 0,
                "impossible_worlds": 0,
            },
            "world_keys_sha256": ("1" if purpose.endswith("selection")
                                    else "2") * 64,
            "complete": True,
        }
        ledger.record_sampler(purpose, sampler)
        actions = []
        for logical_index, candidate_index in enumerate(indices):
            for _ in range(count):
                ledger.begin_candidate_world(purpose)
                ledger.finish_candidate_world(purpose)
            value = float(values[candidate_index])
            actions.append({
                "logical_index": logical_index,
                "candidate_index": candidate_index,
                "cards": state["candidates"][candidate_index]["cards"],
                "sources": state["candidates"][candidate_index]["sources"],
                "raw_attacker_points": [80.0] * count,
                "signed_level_utility": [value] * count,
                "mean_signed_level_utility": value,
            })
        return {
            "seed": sampler["seed"], "sampler": sampler,
            "schema": runtime.FOLD_SCHEMA, "fold": purpose,
            "worlds": count, "candidate_indices": list(indices),
            "tensor_orientation": "logical_action_by_common_world",
            "actions": actions, "candidate_worlds": len(indices) * count,
            "complete": True,
        }
    return run


def test_fold_seeds_are_deterministic_and_domain_separated() -> None:
    state = _state()
    first = {fold: runtime.seed_for(state, fold) for fold in runtime.FOLDS}
    second = {fold: runtime.seed_for(state, fold) for fold in runtime.FOLDS}
    assert first == second
    assert len(set(first.values())) == len(runtime.FOLDS)
    changed = dict(state, state_id="DESIGN:170000001:4:0")
    assert runtime.seed_for(changed, "selection") != first["selection"]


def test_strict_sampler_retries_and_reconciles(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBot:
        SAMPLE_ATTEMPT_FACTOR = runtime.SAMPLE_ATTEMPT_FACTOR
        BANKER_KITTY = True

        def __init__(self):
            self.sample_attempts = 0
            self.accepted_worlds = 0
            self.failed_worlds = 0
            self.rejected_worlds = 0
            self.impossible_worlds = 0

        def _sample_hands(self, _rnd, _seat, _mem):
            self.sample_attempts += 1
            if self.sample_attempts <= 2:
                self.failed_worlds += 1
                return None
            self.accepted_worlds += 1
            return ({1: ["C2"], 2: ["D2"], 3: ["H2"]}, ["S2"])

    monkeypatch.setattr(runtime, "Memory", lambda *_args, **_kwargs: object())
    ledger = runtime.WorkLedger()
    _bot, worlds, sampler = runtime.draw_common_worlds(
        FakeRound(), 0, 2, 7, fold="selection", ledger=ledger,
        bot_factory=lambda _seed: FakeBot())
    assert len(worlds) == 2
    assert sampler["attempts"] == 4
    assert sampler["counters"] == {
        "sample_attempts": 4, "accepted_worlds": 2, "failed_worlds": 2,
        "rejected_worlds": 0, "impossible_worlds": 0,
    }
    assert ledger.snapshot()["samplers"]["selection"] == sampler


def test_strict_sampler_underfill_is_finite_and_keeps_attempts(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingBot:
        SAMPLE_ATTEMPT_FACTOR = runtime.SAMPLE_ATTEMPT_FACTOR
        BANKER_KITTY = True

        def __init__(self):
            self.sample_attempts = 0
            self.accepted_worlds = 0
            self.failed_worlds = 0
            self.rejected_worlds = 0
            self.impossible_worlds = 0

        def _sample_hands(self, _rnd, _seat, _mem):
            self.sample_attempts += 1
            self.failed_worlds += 1
            return None

    monkeypatch.setattr(runtime, "Memory", lambda *_args, **_kwargs: object())
    ledger = runtime.WorkLedger()
    with pytest.raises(runtime.LabelRefused, match="underfilled"):
        runtime.draw_common_worlds(
            FakeRound(), 0, 1, 8, fold="report", ledger=ledger,
            bot_factory=lambda _seed: FailingBot())
    sampler = ledger.snapshot()["samplers"]["report"]
    assert sampler["attempts"] == runtime.SAMPLE_ATTEMPT_FACTOR
    assert sampler["accepted"] == 0
    assert sampler["complete"] is False


def test_score_actions_preserves_raw_tensor_and_role_sign() -> None:
    class RolloutBot:
        @staticmethod
        def _rollout(_rnd, _seat, _hands, _buried, cards):
            return 80.0 if cards == ["C2"] else 120.0

    state = _state()
    worlds = [({1: [], 2: [], 3: []}, []) for _ in range(3)]
    attacker_ledger = runtime.WorkLedger()
    attacker = runtime.score_actions(
        RolloutBot(), FakeRound(attacker=True), state, worlds, [0, 1],
        fold="selection", ledger=attacker_ledger)
    assert attacker["actions"][0]["raw_attacker_points"] == [80.0] * 3
    assert attacker["actions"][0]["signed_level_utility"] == [0.5] * 3
    assert attacker["actions"][1]["signed_level_utility"] == [1.5] * 3
    assert attacker_ledger.snapshot()["total_candidate_worlds_completed"] == 6

    defender_ledger = runtime.WorkLedger()
    defender = runtime.score_actions(
        RolloutBot(), FakeRound(attacker=False), state, worlds, [0],
        fold="selection", ledger=defender_ledger)
    assert defender["actions"][0]["signed_level_utility"] == [-0.5] * 3


def test_selection_tie_uses_lowest_candidate_index() -> None:
    fold = _fold_runner([2.0, 2.0, 1.0], [0.0, 0.0, 0.0])(
        None, _state(candidates=3), [0, 1, 2], 4, "selection",
        runtime.WorkLedger())
    assert runtime.selection_winner(fold, 3) == 0


def test_paired_lcb_is_fixed_pair_student_t() -> None:
    summary = runtime.paired_summary(
        [2.0, 4.0, 6.0, 8.0], [1.0, 1.0, 1.0, 1.0], critical=1.5)
    assert summary["n"] == 4
    assert summary["mean"] == pytest.approx(4.0)
    assert summary["se"] > 0
    assert summary["one_sided_95_lcb"] < summary["mean"]
    assert "fixed-pair" in summary["family"]


def test_ordinary_label_uses_selection_only_and_exact_all_candidate_work() -> None:
    state = _state(stratum="ordinary_anchor", candidates=3)
    row = runtime.label_replayed_state(
        state, FakeRound(), fold_runner=_fold_runner(
            [0.0, 2.0, 1.0], [50.0, -50.0, 100.0]))
    assert row["decision"]["selection_winner_index"] == 1
    assert row["decision"]["final_index"] == 1
    assert row["decision"]["report_never_selected"] is True
    assert row["work"]["total_candidate_worlds_completed"] == 3 * 512
    assert row["selection"]["candidate_indices"] == [0, 1, 2]
    assert row["report"]["candidate_indices"] == [0, 1, 2]


def test_hard_tail_report_lcb_overrides_or_falls_back_without_reselection() -> None:
    state = _state(stratum="proposal_disagreement", candidates=2)
    passed = runtime.label_replayed_state(
        state, FakeRound(), fold_runner=_fold_runner([0.0, 1.0], [0.0, 2.0]))
    assert passed["decision"]["selection_winner_index"] == 1
    assert passed["decision"]["final_index"] == 1
    assert passed["report"]["candidate_indices"] == [0, 1]
    assert passed["work"]["total_candidate_worlds_completed"] == 2 * 64 + 600

    failed = runtime.label_replayed_state(
        state, FakeRound(), fold_runner=_fold_runner([0.0, 1.0], [0.0, -1.0]))
    assert failed["decision"]["selection_winner_index"] == 1
    assert failed["decision"]["final_index"] == 0
    assert failed["decision"]["reason"] == "hard_tail_report_lcb_fallback"


def test_hard_tail_candidate_zero_winner_still_consumes_two_report_slots() -> None:
    state = _state(stratum="champion_uncertainty", candidates=2)
    row = runtime.label_replayed_state(
        state, FakeRound(), fold_runner=_fold_runner([2.0, 1.0], [2.0, 1.0]))
    assert row["report"]["candidate_indices"] == [0, 0]
    assert row["report"]["candidate_worlds"] == 600
    assert row["decision"]["final_index"] == 0


def test_audit_report_plan_refuses_three_distinct_required_actions() -> None:
    assert runtime.audit_report_plan(2, 0)["candidate_indices"] == [0, 2]
    assert runtime.audit_report_plan(0, 1)["candidate_indices"] == [0, 1]
    with pytest.raises(runtime.AuditContractConflict, match="three distinct"):
        runtime.audit_report_plan(2, 1)


def test_refusal_record_never_exposes_partial_outcomes() -> None:
    state = _state()
    record = runtime.refusal_record(state, runtime.LabelRefused("x"))
    assert record["status"] == "REFUSED_NO_LABEL"
    assert record["utility_published"] is False
    assert record["label_published"] is False
    assert "reason" not in record
