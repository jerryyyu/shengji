from __future__ import annotations

import copy
import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
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
        world_hashes = [runtime.sha256_bytes(
            f"{state['state_id']}:{purpose}:{index}".encode())
            for index in range(count)]
        sampler = {
            "schema": runtime.SAMPLER_SCHEMA,
            "fold": purpose,
            "seed": runtime.seed_for(state, purpose),
            "requested": count,
            "accepted": count,
            "accepted_draws": count,
            "attempts": count,
            "attempt_cap": count * runtime.SAMPLE_ATTEMPT_FACTOR,
            "counters": {
                "sample_attempts": count, "accepted_worlds": count,
                "failed_worlds": 0, "rejected_worlds": 0,
                "impossible_worlds": 0,
            },
            "world_key_sha256s": world_hashes,
            "world_keys_sha256": runtime.sha256_bytes(
                runtime.canonical_json(world_hashes)),
            "overlap_discarded": 0,
            "duplicate_discarded": 0,
            "exactly_disjoint_from_prior_folds": True,
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
            return ({1: [f"C{self.sample_attempts}"],
                     2: ["D2"], 3: ["H2"]}, ["S2"])

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
    assert sampler["accepted_draws"] == 2
    assert sampler["overlap_discarded"] == 0
    assert sampler["duplicate_discarded"] == 0
    assert len(sampler["world_key_sha256s"]) == 2
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


def test_later_fold_rejects_an_exact_prior_world_hash(
        monkeypatch: pytest.MonkeyPatch) -> None:
    worlds = [
        ({1: ["C2"], 2: ["D2"], 3: ["H2"]}, ["S2"]),
        ({1: ["C3"], 2: ["D2"], 3: ["H2"]}, ["S2"]),
    ]

    class SequenceBot:
        SAMPLE_ATTEMPT_FACTOR = runtime.SAMPLE_ATTEMPT_FACTOR
        BANKER_KITTY = True

        def __init__(self):
            self.sample_attempts = 0
            self.accepted_worlds = 0
            self.failed_worlds = 0
            self.rejected_worlds = 0
            self.impossible_worlds = 0

        def _sample_hands(self, _rnd, _seat, _mem):
            value = worlds[min(self.sample_attempts, len(worlds) - 1)]
            self.sample_attempts += 1
            self.accepted_worlds += 1
            return value

    monkeypatch.setattr(runtime, "Memory", lambda *_args, **_kwargs: object())
    ledger = runtime.WorkLedger()
    first_hash = runtime._world_hash(*worlds[0])
    prior = {
        "schema": runtime.SAMPLER_SCHEMA,
        "fold": "selection", "seed": 1, "requested": 1,
        "accepted": 1, "accepted_draws": 1,
        "attempts": 1, "attempt_cap": runtime.SAMPLE_ATTEMPT_FACTOR,
        "counters": {"sample_attempts": 1, "accepted_worlds": 1,
                     "failed_worlds": 0, "rejected_worlds": 0,
                     "impossible_worlds": 0},
        "world_key_sha256s": [first_hash],
        "world_keys_sha256": runtime.sha256_bytes(
            runtime.canonical_json([first_hash])),
        "overlap_discarded": 0, "duplicate_discarded": 0,
        "exactly_disjoint_from_prior_folds": True, "complete": True,
    }
    ledger.record_sampler("selection", prior)
    _bot, sampled, report = runtime.draw_common_worlds(
        FakeRound(), 0, 1, 2, fold="report", ledger=ledger,
        bot_factory=lambda _seed: SequenceBot())
    assert sampled == [worlds[1]]
    assert report["attempts"] == 2
    assert report["accepted_draws"] == 2
    assert report["overlap_discarded"] == 1
    assert report["duplicate_discarded"] == 0
    assert not set(report["world_key_sha256s"]).intersection(
        prior["world_key_sha256s"])


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
    assert summary["one_sided_95_ucb"] > summary["mean"]
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


def test_audit_report_plan_uses_three_slots_without_increasing_work() -> None:
    distinct = runtime.audit_report_plan(2, 1)
    assert distinct["candidate_indices"] == [0, 2, 1]
    assert distinct["worlds"] == 400
    assert distinct["candidate_worlds"] == 1_200
    assert distinct["slot_roles"] == [
        "candidate0", "audit_selection_winner", "frozen_label_choice"]

    # Duplicate identities still consume three logical slots, just as the
    # hard-tail report preserves two slots when candidate zero wins.
    duplicate = runtime.audit_report_plan(0, 0)
    assert duplicate["candidate_indices"] == [0, 0, 0]
    assert duplicate["candidate_worlds"] == 2 * 600


def test_audit_report_certifies_winner_and_measures_label_regret() -> None:
    state = _state(candidates=3)
    plan = runtime.audit_report_plan(2, 1)
    report = _fold_runner(
        [0.0, 0.0, 0.0], [0.0, 0.5, 2.0])(
            None, state, plan["candidate_indices"], plan["worlds"],
            "audit_report", runtime.WorkLedger())
    summary = runtime.audit_report_summary(
        report, audit_selection_winner=2, frozen_label_choice=1)
    assert summary["audit_reference_index"] == 2
    assert summary["audit_reference_reason"] == "audit_report_lcb_override"
    assert summary["winner_vs_candidate0"]["one_sided_95_lcb"] == 2.0
    assert summary["audit_reference_minus_label_choice"]["mean"] == 1.5
    assert summary["candidate_worlds"] == 1_200

    fallback_report = _fold_runner(
        [0.0, 0.0, 0.0], [1.0, 2.0, 0.0])(
            None, state, plan["candidate_indices"], plan["worlds"],
            "audit_report", runtime.WorkLedger())
    fallback = runtime.audit_report_summary(
        fallback_report, audit_selection_winner=2, frozen_label_choice=1)
    assert fallback["audit_reference_index"] == 0
    assert fallback["audit_reference_reason"] == \
        "audit_report_lcb_fallback_to_candidate0"
    assert fallback["audit_reference_minus_label_choice"]["mean"] == -1.0


def test_label_row_can_include_frozen_report_audit_without_work_drift() -> None:
    state = _state(stratum="proposal_disagreement", candidates=3)
    row = runtime.label_replayed_state(
        state,
        FakeRound(),
        include_audit=True,
        fold_runner=_fold_runner([0.0, 1.0, 2.0], [0.0, 1.0, 2.0]),
    )
    assert row["decision"]["final_index"] == 2
    assert row["audit"]["selection"]["candidate_indices"] == [0, 1, 2]
    assert row["audit"]["report"]["candidate_indices"] == [0, 2, 2]
    assert row["audit"]["decision"]["audit_reference_index"] == 2
    expected = 3 * runtime.HARD_SELECTION_WORLDS + 600
    expected += 3 * runtime.AUDIT_SELECTION_WORLDS + 1_200
    assert row["work"]["total_candidate_worlds_completed"] == expected
    samplers = row["work"]["samplers"]
    assert set(samplers) == set(runtime.FOLDS)
    assert len({sampler["seed"] for sampler in samplers.values()}) == 4
    assert len({sampler["world_keys_sha256"]
                for sampler in samplers.values()}) == 4


def test_semantic_validator_recomputes_decisions_utilities_and_work() -> None:
    state = _state(stratum="proposal_disagreement", candidates=3)
    value = runtime.acting_utility(80, attacker=True)
    row = runtime.label_replayed_state(
        state, FakeRound(), include_audit=True,
        fold_runner=_fold_runner([value] * 3, [value] * 3))
    runtime.validate_label_row(
        state, FakeRound(), row, audit_expected=True)

    forged = dict(row)
    forged["decision"] = dict(row["decision"], final_index=2)
    forged["row_sha256"] = runtime.sha256_bytes(runtime.canonical_json({
        key: item for key, item in forged.items() if key != "row_sha256"
    }))
    with pytest.raises(runtime.LabelRefused, match="decision drift"):
        runtime.validate_label_row(
            state, FakeRound(), forged, audit_expected=True)

    overlap = copy.deepcopy(row)
    sampler = overlap["audit"]["selection"]["sampler"]
    sampler["world_key_sha256s"][0] = overlap["selection"]["sampler"][
        "world_key_sha256s"][0]
    sampler["world_keys_sha256"] = runtime.sha256_bytes(
        runtime.canonical_json(sampler["world_key_sha256s"]))
    overlap["work"]["samplers"]["audit_selection"] = copy.deepcopy(sampler)
    overlap["row_sha256"] = runtime.sha256_bytes(runtime.canonical_json({
        key: item for key, item in overlap.items() if key != "row_sha256"
    }))
    with pytest.raises(runtime.LabelRefused, match="fold separation drift"):
        runtime.validate_label_row(
            state, FakeRound(), overlap, audit_expected=True)


def test_refusal_record_never_exposes_partial_outcomes() -> None:
    state = _state()
    record = runtime.refusal_record(state, runtime.LabelRefused("x"))
    assert record["status"] == "REFUSED_NO_LABEL"
    assert record["utility_published"] is False
    assert record["label_published"] is False
    assert "reason" not in record
    assert record["row_sha256"] == runtime.sha256_bytes(
        runtime.canonical_json({
            key: value for key, value in record.items()
            if key != "row_sha256"
        }))


def _audit_gate_fixture(*, target_random: bool = False):
    rows = []
    states = {}
    for index in range(256):
        state_id = f"REPORT:{index}"
        if index < 64:
            stratum = "ordinary_anchor"
        elif index < 112:
            stratum = "proposal_disagreement"
        else:
            stratum = "champion_uncertainty"
        candidates = [
            {"cards": ["C2"], "sources": ["live_production_ballot"]},
            {"cards": ["C3"], "sources": ["v11pair_top_proposal"]},
            {"cards": ["C4"], "sources": ["same_budget_random_diversifier"]},
        ]
        states[state_id] = {
            "state_id": state_id, "stratum": stratum,
            "surface_type": "play", "phase": "mid", "role": "attacker",
            "surface": "lead", "candidates": candidates,
        }
        target = 2 if target_random and stratum == "proposal_disagreement" else 1
        rows.append({
            "state_id": state_id,
            "audit": {"decision": {
                "audit_reference_index": target,
                "audit_reference_minus_label_choice": {"mean": 0.0},
            }},
        })
    return rows, states


def test_terminal_audit_gate_clusters_states_and_matches_v11_control() -> None:
    rows, states = _audit_gate_fixture()
    gate = runtime._audit_gate(rows, states)
    assert gate["ordinary_anchor_regret"]["n"] == 64
    assert gate["hard_tail_regret"]["n"] == 192
    assert gate["v11_recall_treatment_minus_matched_random"]["n"] == 48
    assert gate["fidelity_pass"] is True
    assert gate["v11_recall_pass"] is True
    assert gate["decision"] == "AUTHORIZE_MODEL_PACKET_REVIEW"

    rows, states = _audit_gate_fixture(target_random=True)
    failed = runtime._audit_gate(rows, states)
    assert failed["v11_recall_pass"] is False
    assert failed["decision"] == "DIAGNOSE_FROZEN_STAGE_C_ONLY"


def test_cli_rejects_invalid_admit_instead_of_succeeding_silently() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "admit", "--definitely-invalid"],
        cwd=SCRIPT.parents[2], capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "required" in result.stderr or "unrecognized" in result.stderr


def test_admit_run_shard_and_aggregate_execution_seam(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCtrl:
        RUN_ID = "test-stage-c-labels"
        RECEIPT_SCHEMA = "test-receipt"
        ADMISSION_SCHEMA = "test-admission"
        SHARD_ADMISSION_SCHEMA = "test-shard-admission"
        SHARD_SCHEMA = "test-shard"
        AGGREGATE_SCHEMA = "test-aggregate"
        LABEL_SHARDS = 1
        EXPECTED_STATES = 1

        @staticmethod
        def admission_slot_logical_path():
            return FakeCtrl.slot_logical

        @staticmethod
        def shard_admission_logical_path(index):
            assert index == 0
            return FakeCtrl.shard_slot_logical

        sha256_file = staticmethod(
            lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())
        sha256_bytes = staticmethod(runtime.sha256_bytes)
        canonical_json = staticmethod(runtime.canonical_json)

    log_root = runtime.REPO / "server/runs/logs"
    with tempfile.TemporaryDirectory(dir=log_root) as raw:
        root = Path(raw)
        FakeCtrl.slot_logical = str((root / "admission.json").relative_to(
            runtime.REPO))
        FakeCtrl.shard_slot_logical = str((
            root / "shard-admission.json").relative_to(runtime.REPO))
        packet_path = root / "controller.json"
        packet_path.write_text("{}\n")
        review = root / "review.txt"
        review.write_text("review\n")
        receipt_path = root / "label-receipt.json"
        shard_path = root / "design/shard-00.json"
        aggregate_path = root / "label-aggregate.json"
        state = {
            "state_id": "DESIGN:1", "split": "DESIGN",
            "surface_type": "play", "stratum": "ordinary_anchor",
            "candidates": [{"cards": ["C2"], "sources": []}],
        }
        state_set = {"states": [state]}
        schedule_shard = {
            "index": 0, "split": "DESIGN", "local_shard": 0,
            "state_count": 1, "state_ids": [state["state_id"]],
            "state_ids_sha256": runtime.sha256_bytes(
                runtime.canonical_json([state["state_id"]])),
            "audit_state_ids": [], "candidate_worlds": 0,
        }
        packet = {
            "producer": {"git": "f" * 40},
            "packet_sha256": "a" * 64,
            "external_sha256": "b" * 64,
            "parents": {"state_set": {"external_sha256": "c" * 64}},
            "schedule": {"schedule_sha256": "d" * 64,
                         "shards": [schedule_shard]},
            "result_contract": {
                "receipt": str(receipt_path.relative_to(runtime.REPO)),
                "shards": [str(shard_path.relative_to(runtime.REPO))],
                "aggregate": str(aggregate_path.relative_to(runtime.REPO)),
                "max_candidate_worlds": 0,
                "max_sampler_attempts": 0,
                "shard_admission_slots": [FakeCtrl.shard_slot_logical],
            },
        }
        monkeypatch.setattr(runtime, "_ctrl", lambda: FakeCtrl)
        monkeypatch.setattr(runtime, "_controller_packet",
                            lambda *_args, **_kwargs: packet)
        monkeypatch.setattr(runtime, "_validated_parents",
                            lambda *_args, **_kwargs: (state_set, {}))
        monkeypatch.setattr(runtime, "_controller_review_claim",
                            lambda *_args, **_kwargs: {"verdict": "PASS"})
        monkeypatch.setattr(runtime, "_load_v11", lambda: object())
        monkeypatch.setattr(runtime.CAPTURE, "replay_state",
                            lambda _state: FakeRound())
        monkeypatch.setattr(runtime.CAPTURE, "_validate_candidates",
                            lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime, "validate_label_row",
                            lambda *_args, **_kwargs: None)
        monkeypatch.setattr(runtime, "_audit_gate", lambda *_args: {
            "decision": "AUTHORIZE_MODEL_PACKET_REVIEW"})

        def fake_label(state_value, **_kwargs):
            row = {
                "schema": runtime.SCHEMA, "status": "COMPLETE",
                "state_id": state_value["state_id"], "split": "DESIGN",
                "surface_type": "play", "stratum": "ordinary_anchor",
                "audit": None,
                "work": {"schema": runtime.WORK_SCHEMA,
                         "candidate_worlds_attempted": {
                             name: 0 for name in runtime.FOLDS},
                         "candidate_worlds_completed": {
                             name: 0 for name in runtime.FOLDS},
                         "total_candidate_worlds_attempted": 0,
                         "total_candidate_worlds_completed": 0,
                         "samplers": {}, "accounting_complete": True},
            }
            row["row_sha256"] = runtime.sha256_bytes(
                runtime.canonical_json(row))
            return row

        monkeypatch.setattr(runtime, "label_state", fake_label)
        admitted = runtime.admit(
            packet_path=packet_path, expected_packet_sha256="b" * 64,
            controller_review_record=review,
            state_set_review_record=review, out=receipt_path)
        receipt_sha = FakeCtrl.sha256_file(receipt_path)
        runtime._receipt(
            receipt_path, receipt_sha, packet, "b" * 64, review, review)
        shard = runtime.run_shard(
            packet_path=packet_path, expected_packet_sha256="b" * 64,
            receipt_path=receipt_path, expected_receipt_sha256=receipt_sha,
            controller_review_record=review, state_set_review_record=review,
            shard_index=0,
            progress_every=1, out=shard_path)
        assert shard["status"] == "COMPLETE"
        with pytest.raises(runtime.LabelRefused, match="already consumed"):
            runtime._consume_shard_slot(
                packet, index=0, packet_sha256="b" * 64,
                receipt_sha256=receipt_sha)
        aggregate = runtime.aggregate(
            packet_path=packet_path, expected_packet_sha256="b" * 64,
            receipt_path=receipt_path, expected_receipt_sha256=receipt_sha,
            controller_review_record=review, state_set_review_record=review,
            shard_paths=[shard_path],
            out=aggregate_path)
        assert aggregate["status"] == "COMPLETE"
        assert aggregate["model_packet_review_authorized"] is True
        assert aggregate["training_authorized"] is False
        assert aggregate["report_open_authorized"] is False
