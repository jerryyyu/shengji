"""Bounded executable checks for the teacher-v1 Stage-A/B contract."""
from __future__ import annotations

import copy
import json
import math
import random
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_v1_gate as gate  # noqa: E402
import teacher_v1_label as label  # noqa: E402
import teacher_v1_states as states  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.teacher_v1 import (CAPTURE_MAX_DEALS, CAPTURE_PACKET_ID,  # noqa: E402
                                CAPTURE_SHARDS, EXPERIMENT, GOLD_FOLDS,
                                PRODUCER_RECEIPT_SCHEMA,
                                SEED_START, STATE_SCHEMA, TARGET_SCHEMA,
                                canonical_state_partition,
                                capture_coverage, capture_packet,
                                capture_shard_seeds, derive_stream,
                                replay_state, split_for_deal, stable_digest,
                                stage_b_regret, targets, tensor_problems)


def packet_lineage():
    parent_map = {
        str(index): stable_digest({"capture": index})
        for index in range(CAPTURE_SHARDS)
    }
    diagnostic_map = {
        str(index): stable_digest({"diagnostic-records": index})
        for index in range(CAPTURE_SHARDS)
    }
    coverage = {
        **capture_coverage(),
        "capture_parent_sha256": parent_map,
        "diagnostic_records_sha256": diagnostic_map,
    }
    inputs = [
        {
            "path": f"diagnostic-{index}.json",
            "sha256": stable_digest({"diagnostic-artifact": index}),
            "capture_shard_index": index,
            "capture_parent_sha256": parent_map[str(index)],
            "diagnostic_records_sha256": diagnostic_map[str(index)],
        }
        for index in range(CAPTURE_SHARDS)
    ]
    return coverage, inputs


def valid_capture_manifest(shard: int) -> dict:
    seeds = capture_shard_seeds(shard)
    records = []
    return {
        "schema": states.CAPTURE_SCHEMA, "experiment_id": EXPERIMENT,
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "seed_start": SEED_START, "seed0": SEED_START,
        "max_deals": CAPTURE_MAX_DEALS, "shard_count": CAPTURE_SHARDS,
        "shard_index": shard, "complete": True,
        "scanned_deals": len(seeds), "scanned_seeds": seeds,
        "scanned_seeds_sha256": stable_digest(seeds),
        "unreachable_targets": len(seeds), "unreachable_seeds": seeds,
        "n_records": 0, "records": records,
        "records_digest": stable_digest(records),
        "tree_dirty": False, "promotable": True,
        "fast_engine": True, "require_voids": True,
        "exam_exclusion": {
            "verified": True, "overlap": 0,
            "sources": [{"path": path} for path in states.DEFAULT_EXAM_SPLITS],
        },
        "actor": {"policy": "mc-strong", "identity": "actor"},
    }


def valid_diagnostic_manifest(shard: int) -> dict:
    seeds = capture_shard_seeds(shard)
    records = []
    parent = stable_digest({"capture-parent": shard})
    return {
        "schema": states.DIAGNOSTIC_SCHEMA, "experiment_id": EXPERIMENT,
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_shard_index": shard,
        "capture_scanned_seeds": seeds,
        "capture_scanned_seeds_sha256": stable_digest(seeds),
        "capture_unreachable_seeds": seeds,
        "capture_input_sha256": parent, "input_sha256": parent,
        "complete": True, "n_records": 0, "records": records,
        "records_digest": stable_digest(records),
        "diagnosed_state_ids": [],
        "diagnosed_state_ids_sha256": stable_digest([]),
        "tree_dirty": False, "promotable": True,
        "fast_engine": True, "require_voids": True,
        "exam_exclusion": {
            "verified": True, "overlap": 0,
            "sources": [{"path": path} for path in states.DEFAULT_EXAM_SPLITS],
        },
        "actor": {"policy": "mc-strong", "identity": "actor"},
        "selector_worlds": states.SELECTOR_WORLDS,
        "selector_policy": "selector", "v11_checkpoint_sha256": "v11",
        "git": "git", "python": "3.14", "fast_binary_sha256": "fast",
        "fast_router_sha256": "router", "state_script_sha256": "states",
    }


def raw_state(seed=120_000_123, *, follow=False):
    rnd = Game(random.Random(seed)).start_round()
    bots = [make_bot("smart", seed=seed + seat) for seat in range(4)]
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"stage": "deal", "deal_pos": rnd._deal_pos,
                                 "seat": seat, "cards": list(cards)})
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"stage": "final", "deal_pos": rnd._deal_pos,
                                 "seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    assert rnd.banker is not None
    buried = bots[rnd.banker].decide_bury(rnd, rnd.banker)
    final = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"], "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    setup = {
        "deck": list(rnd.deck), "initial_banker": None,
        "trump_rank": rnd.trump_rank, "banker": rnd.banker,
        "trump_suit": rnd.trump_suit, "trump_is_nt": rnd.trump_is_nt,
        "declarations": declarations, "final_declaration": final,
        "buried": list(buried),
    }
    rnd.bury(rnd.banker, buried)
    plays = []
    if follow:
        seat = rnd.turn
        play = bots[seat].decide_play(rnd, seat)
        rnd.play(seat, play)
        plays.append({"seat": seat, "cards": list(play)})
    seat = rnd.turn
    row = {
        "schema": STATE_SCHEMA, "experiment_id": EXPERIMENT,
        "seed": seed, "seat": seat, "ply": len(plays), "trick": 0,
        "phase": "early", "decision": "follow" if follow else "lead",
        "role": "attacker" if rnd.is_attacker(seat) else "defender",
        "split": split_for_deal(EXPERIMENT, seed),
        "selector_pool": "representative", "kind": "representative",
        "selection_probability": 0.5, "setup": setup, "plays": plays,
    }
    row["state_id"] = f"{seed}:{len(plays)}:{seat}"
    return row


def test_named_streams_are_replayable_and_domain_separated():
    identity = dict(experiment_id=EXPERIMENT, deal_seed=120_000_001,
                    state_id="s", purpose="belief", fold="selection")
    assert derive_stream(**identity) == derive_stream(**identity)
    assert derive_stream(**identity)["seed"] != derive_stream(
        **{**identity, "fold": "report"})["seed"]
    with pytest.raises(ValueError, match="common across candidates"):
        derive_stream(**identity, candidate=2)


def test_split_is_deal_disjoint_and_approximately_70_15_15():
    got = [split_for_deal(EXPERIMENT, 120_000_000 + i) for i in range(2000)]
    assert 1300 < got.count("train") < 1500
    assert 240 < got.count("tune") < 360
    assert 240 < got.count("holdout") < 360


def test_registered_capture_refuses_wrong_packet_range():
    payload = valid_capture_manifest(0)
    assert states.registered_capture_problems(payload) == []
    payload["capture_packet"] = {
        **payload["capture_packet"], "seed_end_inclusive": SEED_START + 7,
    }
    assert "capture packet identity/range" in \
        states.registered_capture_problems(payload)
    payload = valid_capture_manifest(0)
    payload["max_deals"] = 128
    assert "capture top-level packet identity/range" in \
        states.registered_capture_problems(payload)


def test_diagnostic_population_is_exact_complete_and_nonoverlapping():
    manifests = [valid_diagnostic_manifest(index)
                 for index in range(CAPTURE_SHARDS)]
    problems, coverage = states.diagnostic_population_problems(manifests)
    assert problems == []
    assert coverage["seed_count"] == CAPTURE_MAX_DEALS
    assert set(coverage["capture_parent_sha256"]) == {
        str(index) for index in range(CAPTURE_SHARDS)
    }


def test_diagnostic_population_refuses_missing_or_repeated_shard():
    manifests = [valid_diagnostic_manifest(index)
                 for index in range(CAPTURE_SHARDS)]
    problems, _ = states.diagnostic_population_problems(manifests[:-1])
    assert any("shard count 7" in problem for problem in problems)
    assert any("not exact/nonoverlapping" in problem for problem in problems)

    repeated = manifests[:-1] + [copy.deepcopy(manifests[0])]
    problems, _ = states.diagnostic_population_problems(repeated)
    assert any("shard identities" in problem for problem in problems)
    assert "repeated capture parent artifact" in problems
    assert any("not exact/nonoverlapping" in problem for problem in problems)


def test_diagnostic_population_refuses_conflicting_packet_or_source_identity():
    manifests = [valid_diagnostic_manifest(index)
                 for index in range(CAPTURE_SHARDS)]
    manifests[3]["packet_id"] = "different-packet"
    manifests[4]["state_script_sha256"] = "different-source"
    problems, _ = states.diagnostic_population_problems(manifests)
    assert any("diagnostic packet id" in problem for problem in problems)
    assert "diagnostic 3: conflicting packet_id" in problems
    assert "diagnostic 4: conflicting state_script_sha256" in problems


def test_schema_only_metadata_cannot_advance_capture_chain():
    capture_only = {"schema": states.CAPTURE_SCHEMA, "complete": True}
    diagnostic_only = {"schema": states.DIAGNOSTIC_SCHEMA, "complete": True}
    state_set_only = {
        "schema": states.STATE_SET_SCHEMA, "complete": True,
        "states": [], "states_digest": stable_digest([]),
    }
    label_only = {
        "schema": gate.CHEAP_SHARD_SCHEMA, "complete": True,
        "records": [], "records_digest": gate.records_digest([]),
    }
    assert states.registered_capture_problems(capture_only)
    assert states.registered_diagnostic_problems(diagnostic_only)
    assert states.state_set_packet_problems(state_set_only)
    assert gate.label_packet_problems(label_only)


@pytest.mark.parametrize("follow", [False, True])
def test_teacher_state_round_trips_lead_and_follow(follow):
    row = raw_state(follow=follow)
    rnd = replay_state(row)
    assert rnd.turn == row["seat"]
    assert bool(rnd.trick.plays) is follow


def test_targets_keep_attacker_raw_and_flip_acting_team():
    assert targets(80, True) == {
        "attacker_points": 80, "signed_points": 80,
        "bracket": 0, "signed_level_utility": 0.5,
    }
    assert targets(0, False) == {
        "attacker_points": 0, "signed_points": 0,
        "bracket": -3, "signed_level_utility": 3.5,
    }
    assert targets(120, False)["signed_level_utility"] == -1.5
    # House rules are uncapped.  A +3 training clip, if added later, must be a
    # separately named target rather than silently changing this teacher.
    assert targets(240, True)["bracket"] == 4
    assert targets(240, True)["signed_level_utility"] == 4.5


def test_tensor_validator_requires_full_world_by_candidate_shape():
    fold = {
        "requested_worlds": 2, "draw_ids": ["a", "b"],
        "world_digests": ["x", "y"],
        "tensor": {name: [[0, 1], [2, 3]] for name in (
            "attacker_points", "signed_points", "bracket",
            "signed_level_utility")},
    }
    assert tensor_problems(fold, 2, 2) == []
    fold["tensor"]["bracket"][1].pop()
    assert any("bracket tensor shape" in p for p in tensor_problems(fold, 2, 2))


def gold_record(regret: float, seed: int) -> dict:
    rows = [[0.0, regret] for _ in range(GOLD_FOLDS["gold_report"])]
    tensor = {name: [list(row) for row in rows] for name in (
        "attacker_points", "signed_points", "bracket",
        "signed_level_utility")}
    fold = {
        "requested_worlds": GOLD_FOLDS["gold_report"],
        "draw_ids": [f"d{i}" for i in range(GOLD_FOLDS["gold_report"])],
        "world_digests": [f"w{i}" for i in range(GOLD_FOLDS["gold_report"])],
        "tensor": tensor,
    }
    return {
        "state_id": str(seed), "deal_seed": seed,
        "candidates": [["A"], ["B"]],
        "cheap_selected_index": 0, "gold_reference_index": 1,
        "gold_report_regret": regret,
        "folds": {"gold_report": fold},
    }


def test_stage_b_gate_uses_one_state_mean_and_one_sided_upper_bound():
    records = [gold_record(0.05, 120_001_000 + i) for i in range(128)]
    result = stage_b_regret(records)
    assert result["passed"] is True
    assert result["n_states"] == 128
    assert result["upper_95"] == pytest.approx(0.05)
    records[-1] = gold_record(8.0, 120_002_000)
    result = stage_b_regret(records)
    assert result["passed"] is False
    assert result["upper_95"] > 0.10


def test_stage_b_short_artifact_is_inconclusive_not_pass():
    result = stage_b_regret([gold_record(0.0, 120_003_000 + i)
                             for i in range(127)])
    assert result["passed"] is False
    assert result["inconclusive"] is True


def test_records_rerun_digest_excludes_only_wall_time():
    a = [{"state_id": "s", "value": [1, 2], "elapsed_seconds": 1.0}]
    b = [{"state_id": "s", "value": [1, 2], "elapsed_seconds": 9.0}]
    assert label.deterministic_records_digest(a) == \
        label.deterministic_records_digest(b)
    assert gate.deterministic_rerun_problems(a, b) == []
    b[0]["value"][0] = 9
    assert gate.deterministic_rerun_problems(a, b)


def synthetic_diag(seed: int, phase: str, role: str, decision: str,
                   pool: str, gap: float, se: float, disagreement: bool):
    sid = f"{seed}:0:0"
    return {
        "state_id": sid,
        "state": {"state_id": sid, "seed": seed, "phase": phase,
                  "role": role, "decision": decision,
                  "selector_pool": pool},
        "gap": gap, "gap_se": se, "disagreement": disagreement,
    }


def test_stage_a_freezer_has_four_per_cell_and_disjoint_challenge_rows():
    diagnostics = []
    seed = 120_100_000
    for phase, role, decision in states.REPRESENTATIVE_CELLS:
        for _ in range(6):
            diagnostics.append(synthetic_diag(
                seed, phase, role, decision, "representative", 0, 0, False))
            seed += 1
    for i in range(24):
        diagnostics.append(synthetic_diag(
            seed, "early", "attacker", "lead", "challenge",
            5 + (i - 12) / 10, 2 - i / 100, i % 2 == 0))
        seed += 1
    picked, problems = states.select_gate_states(diagnostics, "a", set())
    assert problems == []
    assert len(picked) == 64
    kinds = {kind: sum(row["kind"] == kind for row in picked)
             for kind in ("representative", "boundary", "uncertainty")}
    assert kinds == {"representative": 48, "boundary": 8, "uncertainty": 8}
    assert len({row["seed"] for row in picked}) == 64
    assert all(0 < row["selection_probability"] <= 1 for row in picked)
    assert all(row["selection_metadata"]["deployment_weightable"] is True
               for row in picked if row["kind"] == "representative")
    assert all(row["selection_probability"] == 1.0 and
               row["selection_metadata"]["deployment_weightable"] is False
               for row in picked if row["kind"] != "representative")


def test_stage_b_contract_requires_exact_stratified_composition():
    records = []
    seed = 120_500_000
    for phase, role, decision in states.REPRESENTATIVE_CELLS:
        for _ in range(8):
            records.append({
                "deal_seed": seed, "kind": "representative",
                "stratum": {"phase": phase, "role": role,
                            "decision": decision},
            })
            seed += 1
    for kind in ("boundary", "uncertainty"):
        for _ in range(16):
            records.append({"deal_seed": seed, "kind": kind, "stratum": {}})
            seed += 1
    assert gate.stage_contract_problems(records, "b") == []
    records[-1]["kind"] = "boundary"
    problems = gate.stage_contract_problems(records, "b")
    assert "boundary states 17, required 16" in problems
    assert "uncertainty states 15, required 16" in problems


def test_stage_b_exclusion_refuses_schema_only_or_digest_drift():
    diagnostic = {
        "git": "g", "actor": {"policy": "mc-strong"},
        "exam_exclusion": {"verified": True}, "python": "3",
        "fast_binary_sha256": "b", "fast_router_sha256": "r",
        "state_script_sha256": "s",
    }
    schema_only = {
        "schema": states.STATE_SET_SCHEMA, "experiment_id": EXPERIMENT,
        "stage": "a", "complete": True, "states": [],
        "states_digest": stable_digest([]),
    }
    problems = states.stage_a_exclusion_problems(
        schema_only, diagnostic, {"diagnostic"})
    assert "excluded Stage-A count 0, required 64" in problems
    assert "excluded Stage-A diagnostic population drift" in problems
    schema_only["states_digest"] = "corrupt"
    assert "excluded Stage-A states digest" in \
        states.stage_a_exclusion_problems(
            schema_only, diagnostic, {"diagnostic"})


def test_stage_b_refuses_plausible_handwritten_gate_and_state_set_drift():
    coverage, _ = packet_lineage()
    state_set_sha = stable_digest({"stage-a": "state-set"})
    gate_payload = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "complete": True,
        "stage": "A", "verdict": "PASS", "stage_b_authorized": True,
        "problems": [], "state_input_sha256": state_set_sha,
        "n_states": 64,
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_coverage": coverage,
        "inputs": [
            {"shard_index": index,
             "sha256": stable_digest({"primary": index})}
            for index in range(CAPTURE_SHARDS)
        ],
        "reruns": [
            {"shard_index": index,
             "sha256": stable_digest({"rerun": index})}
            for index in range(CAPTURE_SHARDS)
        ],
    }
    problems = states.stage_a_gate_problems(gate_payload, state_set_sha)
    assert "Stage-A gate exact state-set artifact binding" in problems
    assert "Stage-A gate producer run identities" in problems
    assert "Stage-A gate executable source provenance" in problems
    assert "Stage-A gate runtime is not clean/compiled/strict" in problems
    assert "Stage-A gate is not bound to the excluded state set" in \
        states.stage_a_gate_problems(gate_payload, stable_digest("different"))
    gate_payload["verdict"] = "FAIL"
    assert "Stage-A mechanics gate did not pass" in \
        states.stage_a_gate_problems(gate_payload, state_set_sha)


def test_stage_a_gate_refuses_schema_only_and_reused_rerun_artifacts():
    schema_only = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "stage": "A", "verdict": "PASS", "stage_b_authorized": True,
        "problems": [],
    }
    assert states.stage_a_gate_problems(
        schema_only, stable_digest("state-set"))

    coverage, _ = packet_lineage()
    state_set_sha = stable_digest("state-set")
    artifacts = [
        {"shard_index": index, "sha256": stable_digest({"shard": index})}
        for index in range(CAPTURE_SHARDS)
    ]
    plausible = {
        **schema_only, "complete": True, "n_states": 64,
        "state_input_sha256": state_set_sha,
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_coverage": coverage,
        "inputs": artifacts, "reruns": copy.deepcopy(artifacts),
    }
    assert "Stage-A gate primary/rerun artifact identity overlap" in \
        states.stage_a_gate_problems(plausible, state_set_sha)

    plausible.update({
        "state_set": {"path": "states.json", "sha256": state_set_sha},
        "primary_producer_run_id": "primary-run-001",
        "rerun_producer_run_id": "primary-run-001",
    })
    assert "Stage-A gate primary/rerun producer identity reused" in \
        states.stage_a_gate_problems(plausible, state_set_sha)


def test_stage_b_rehashes_every_stage_a_artifact_before_authorizing(tmp_path):
    coverage, _ = packet_lineage()
    state_set_sha = stable_digest("stage-a-state-set")
    inputs, reruns = [], []
    for field, rows in (("primary", inputs), ("rerun", reruns)):
        for index in range(CAPTURE_SHARDS):
            path = tmp_path / f"{field}-{index}.json"
            path.write_text("{}\n")
            rows.append({
                "path": str(path), "shard_index": index,
                # Deliberately plausible syntax but not the exact file bytes.
                "sha256": stable_digest({field: index}),
            })
    payload = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "complete": True, "stage": "A", "verdict": "PASS",
        "stage_b_authorized": True, "problems": [], "n_states": 64,
        "state_input_sha256": state_set_sha,
        "state_set": {"path": "stage-a.json", "sha256": state_set_sha},
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_coverage": coverage, "inputs": inputs, "reruns": reruns,
        "primary_producer_run_id": "primary-run-001",
        "rerun_producer_run_id": "rerun-run-0001",
        "git": "abc", "python": "3.14", "tree_dirty": False,
        "promotable": True, "fast_engine": True, "require_voids": True,
        "gate_source_digests": {
            name: stable_digest(name) for name in (
                "compiled_engine", "fast_router", "gate_script",
                "label_script", "state_script", "teacher_contract")
        },
    }
    problems = states.stage_a_gate_problems(
        payload, state_set_sha,
        {"states": [], "capture_coverage": coverage},
        verify_artifacts=True)
    assert any("artifact byte-hash drift" in problem for problem in problems)


def test_target_assignment_is_fixed_before_play_and_covers_cells():
    targets_ = [states.target_for_deal(EXPERIMENT, SEED)
                for SEED in range(120_000_000, 120_001_000)]
    assert all(t == states.target_for_deal(EXPERIMENT, 120_000_000 + i)
               for i, t in enumerate(targets_))
    assert {t["phase"] for t in targets_} == {"early", "mid", "late"}
    assert {t["decision"] for t in targets_} == {"lead", "follow"}
    assert {t["selector_pool"] for t in targets_} == {
        "representative", "challenge"}


def test_gate_refuses_gold_continuation_that_is_not_mc_strong():
    row = raw_state()
    candidates = [[next(iter(Game(random.Random(row["seed"])).start_round().deck))]]
    # Test the policy identity boundary directly with a minimal malformed fold;
    # shape errors are expected too, but the gold-vs-heuristic defect must be
    # named independently.
    cheap = {"state_id": row["state_id"], "deal_seed": row["seed"],
             "split": row["split"], "state": row,
             "replay_digest": stable_digest(row), "ballot_spec": {},
             "candidates": candidates, "candidate_count": 1,
             "cheap_selected_index": 0}
    gold = dict(cheap)
    gold["folds"] = {name: {
        "continuation_policy": "heuristic", "continuation_n": 0,
        "requested_worlds": count, "draw_ids": [], "world_digests": [],
        "tensor": {}, "sampler_counters": {}, "inner_sampler_counters": {},
    } for name, count in GOLD_FOLDS.items()}
    problems = gate.gold_record_problems(gold, cheap, GOLD_FOLDS)
    assert any("not production N=30 gold" in p for p in problems)


def test_gold_shards_may_have_distinct_cheap_parent_hashes(tmp_path):
    coverage, diagnostic_inputs = packet_lineage()
    state_set_sha = stable_digest({"state-set": "b"})
    common = {
        "schema": states.DIAGNOSTIC_SCHEMA,  # replaced below; avoids magic str
        "experiment_id": EXPERIMENT, "stage": "b", "mode": "gold",
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_coverage": coverage,
        "git": "abc", "tree_dirty": False, "promotable": True,
        "target_schema": TARGET_SCHEMA, "fast_engine": True,
        "require_voids": True, "source_digests": {"code": "x"},
        "shard_count": CAPTURE_SHARDS, "continuation": "mc-strong@N=30",
        "counts": dict(GOLD_FOLDS), "state_input_sha256": state_set_sha,
        "producer_run_id": "gold-run-0001",
        "producer_receipt": {
            "path": "gold-receipt.json",
            "sha256": stable_digest("gold-receipt"),
            "run_id": "gold-run-0001", "role": "stage-b-gold",
            "nonce": stable_digest("gold-nonce"),
        },
        "state_contract": {
            "one_state_per_deal": True,
            "exam_exclusion": {"verified": True, "overlap": 0,
                               "sources": [{"path": "exam"}]},
            "actor": {"policy": "mc-strong", "identity": "actor"},
            "packet_id": CAPTURE_PACKET_ID,
            "capture_packet": capture_packet(),
            "capture_coverage": coverage,
            "diagnostic_inputs": diagnostic_inputs,
            "state_set_sha256": state_set_sha,
        },
        "complete": True,
    }
    paths = []
    all_records = [{"state_id": f"state-{record_index:03d}"}
                   for record_index in range(128)]
    for index in range(CAPTURE_SHARDS):
        records = canonical_state_partition(
            all_records, index, CAPTURE_SHARDS)
        state_ids = [record["state_id"] for record in records]
        payload = {
            **common, "schema": gate.GOLD_SHARD_SCHEMA,
            "shard_index": index,
            "input_sha256": stable_digest({"cheap-shard": index}),
            "state_partition": {
                "schema": "teacher-v1-state-partition-v1",
                "assignment": "sorted_state_id_then_interleaved_position",
                "shard_index": index, "shard_count": CAPTURE_SHARDS,
                "state_ids": state_ids,
                "state_ids_sha256": stable_digest(state_ids),
            },
            "n_records": len(records), "records": records,
            "records_digest": gate.records_digest(records),
        }
        path = tmp_path / f"gold-{index}.json"
        path.write_text(json.dumps(payload))
        paths.append(str(path))
    _, records, problems = gate.load_shards(
        paths, schema=gate.GOLD_SHARD_SCHEMA, stage="b", mode="gold"
    )
    assert problems == []
    assert len(records) == 128

    mixed = json.loads(Path(paths[3]).read_text())
    original = copy.deepcopy(mixed)
    mixed["producer_receipt"]["nonce"] = stable_digest("mixed-population")
    Path(paths[3]).write_text(json.dumps(mixed))
    _, _, problems = gate.load_shards(
        paths, schema=gate.GOLD_SHARD_SCHEMA, stage="b", mode="gold"
    )
    assert any("producer_receipt drift" in problem for problem in problems)
    Path(paths[3]).write_text(json.dumps(original))

    # Editing both claimed indices and their local partition metadata is still
    # caught against the independently reconstructed global state partition.
    first = json.loads(Path(paths[0]).read_text())
    second = json.loads(Path(paths[1]).read_text())
    first["shard_index"] = first["state_partition"]["shard_index"] = 1
    second["shard_index"] = second["state_partition"]["shard_index"] = 0
    Path(paths[0]).write_text(json.dumps(first))
    Path(paths[1]).write_text(json.dumps(second))
    _, _, problems = gate.load_shards(
        paths, schema=gate.GOLD_SHARD_SCHEMA, stage="b", mode="gold"
    )
    assert any("registered state partition" in problem for problem in problems)


def test_real_state_set_requires_exam_exclusion_and_actor_identity():
    payload = {"schema": states.STATE_SET_SCHEMA, "experiment_id": EXPERIMENT,
               "seed_start": 120_000_000, "states": []}
    problems = label.state_set_problems(payload, "a", smoke=False)
    assert any("exclusion" in p for p in problems)
    assert any("actor identity" in p for p in problems)


def test_state_set_binds_stage_completion_and_internal_digest():
    payload = {
        "schema": states.STATE_SET_SCHEMA, "experiment_id": EXPERIMENT,
        "stage": "a", "complete": True, "states": [],
        "states_digest": stable_digest([]),
    }
    assert label.state_set_problems(payload, "a", smoke=True) == []
    payload["states_digest"] = "changed"
    assert "state-set record digest" in label.state_set_problems(
        payload, "a", smoke=True)
    payload["states_digest"] = stable_digest([])
    payload["stage"] = "b"
    assert "state-set stage" in label.state_set_problems(
        payload, "a", smoke=True)


def test_state_and_cheap_parent_refuse_executable_generation_drift():
    digests = label.source_digests()
    runtime = {"git": label.git_output("rev-parse", "HEAD")}
    actor = states.actor_identity()
    state_payload = {
        "git": runtime["git"], "actor": actor,
        "state_script_sha256": digests["state_freezer"],
        "fast_router_sha256": digests["fast_router"],
        "fast_binary_sha256": digests["compiled_engine"],
    }
    assert label.state_source_problems(state_payload, runtime, digests) == []
    state_payload["fast_binary_sha256"] = "stale"
    assert "state-set compiled engine drift" in label.state_source_problems(
        state_payload, runtime, digests)

    coverage, diagnostic_inputs = packet_lineage()
    state_set_sha = stable_digest({"state-set": "b"})
    cheap_payload = {
        "records": [], "records_digest": label.deterministic_records_digest([]),
        "n_records": 0, "git": runtime["git"], "source_digests": digests,
        "target_schema": TARGET_SCHEMA, "fast_engine": True,
        "require_voids": True, "counts": dict(label.CHEAP_FOLDS),
        "candidate_world_work": 0,
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_coverage": coverage, "state_input_sha256": state_set_sha,
        "producer_run_id": "cheap-run-0001",
        "producer_receipt": {
            "path": "cheap-receipt.json",
            "sha256": stable_digest("cheap-receipt"),
            "run_id": "cheap-run-0001", "role": "stage-b-cheap",
            "nonce": stable_digest("cheap-nonce"),
        },
        "shard_index": 0, "shard_count": CAPTURE_SHARDS,
        "state_partition": {
            "schema": "teacher-v1-state-partition-v1",
            "assignment": "sorted_state_id_then_interleaved_position",
            "shard_index": 0, "shard_count": CAPTURE_SHARDS,
            "state_ids": [], "state_ids_sha256": stable_digest([]),
        },
        "state_contract": {
            "packet_id": CAPTURE_PACKET_ID,
            "capture_packet": capture_packet(),
            "capture_coverage": coverage,
            "diagnostic_inputs": diagnostic_inputs,
            "state_set_sha256": state_set_sha,
        },
    }
    assert label.cheap_parent_problems(
        cheap_payload, runtime, digests, smoke=False) == []
    cheap_payload["source_digests"] = {**digests, "mcbot_sampler": "stale"}
    assert "cheap-parent executable source drift" in label.cheap_parent_problems(
        cheap_payload, runtime, digests, smoke=False)


def test_gate_runtime_must_match_label_executable_identity():
    gate_sources = {
        "compiled_engine": stable_digest("compiled"),
        "fast_router": stable_digest("router"),
        "label_script": stable_digest("label"),
        "state_script": stable_digest("state"),
        "teacher_contract": stable_digest("teacher"),
        "producer_receipt_script": stable_digest("receipt"),
        "gate_script": stable_digest("gate"),
    }
    runtime = {
        "git": "abc", "python": "3.14", "fast_engine": True,
        "require_voids": True, "gate_source_digests": gate_sources,
    }
    manifest = {
        "git": "abc", "python": "3.14", "fast_engine": True,
        "require_voids": True,
        "source_digests": {
            "compiled_engine": gate_sources["compiled_engine"],
            "fast_router": gate_sources["fast_router"],
            "label_script": gate_sources["label_script"],
            "state_freezer": gate_sources["state_script"],
            "teacher_contract": gate_sources["teacher_contract"],
            "producer_receipt_script": gate_sources[
                "producer_receipt_script"],
        },
    }
    assert gate.gate_input_runtime_problems(manifest, runtime) == []
    manifest["source_digests"]["label_script"] = stable_digest("stale")
    assert "gate/label label_script source drift" in \
        gate.gate_input_runtime_problems(manifest, runtime)


def test_producer_receipt_is_bound_before_work_and_reopened_by_gate(tmp_path):
    state_sha = stable_digest("stage-a-state-set")
    source_digests = {
        name: stable_digest(name) for name in (
            "compiled_engine", "fast_router", "label_script",
            "producer_receipt_script", "state_freezer", "teacher_contract",
        )
    }
    runtime = {
        "git": "abc", "python": "3.14", "tree_dirty": False,
        "promotable": True, "fast_engine": True, "require_voids": True,
    }
    receipt = {
        "schema": PRODUCER_RECEIPT_SCHEMA,
        "experiment_id": EXPERIMENT,
        "packet_id": CAPTURE_PACKET_ID,
        "capture_packet": capture_packet(),
        "complete": True,
        "run_id": "stage-a-primary-0001",
        "role": "stage-a-primary",
        "stage": "a", "mode": "cheap",
        "state_set": {"path": "stage-a.json", "sha256": state_sha},
        "nonce": stable_digest("primary-nonce"),
        "created_time_ns": 1,
        "creator_pid": 123,
        **runtime,
        "source_digests": source_digests,
    }
    assert label.producer_receipt_problems(
        receipt, runtime=runtime, digests=source_digests,
        stage="a", mode="cheap", state_set_sha256=state_sha,
    ) == []
    contradictory = {**receipt, "stage": "b", "mode": "gold"}
    assert "producer receipt role/stage/mode" in \
        label.producer_receipt_problems(
            contradictory, runtime=runtime, digests=source_digests,
            stage="a", mode="cheap", state_set_sha256=state_sha,
        )
    wrong_state = {
        **receipt,
        "state_set": {**receipt["state_set"], "sha256": stable_digest("wrong")},
    }
    assert "producer receipt exact state-set binding" in \
        label.producer_receipt_problems(
            wrong_state, runtime=runtime, digests=source_digests,
            stage="a", mode="cheap", state_set_sha256=state_sha,
        )
    stale_sources = {**receipt, "source_digests": {"stale": "source"}}
    assert "producer receipt executable source drift" in \
        label.producer_receipt_problems(
            stale_sources, runtime=runtime, digests=source_digests,
            stage="a", mode="cheap", state_set_sha256=state_sha,
        )

    receipt_path = tmp_path / "primary-receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    receipt_sha = gate.sha256_file(str(receipt_path))
    manifest = {
        "stage": "a", "mode": "cheap",
        "producer_run_id": receipt["run_id"],
        "producer_receipt": {
            "path": str(receipt_path), "sha256": receipt_sha,
            "run_id": receipt["run_id"], "role": receipt["role"],
            "nonce": receipt["nonce"],
        },
        "state_input_sha256": state_sha,
        **runtime,
        "source_digests": source_digests,
    }
    assert gate.producer_receipt_problems(manifest) == []
    with pytest.raises(label.TeacherProtocolError, match="input digest mismatch"):
        label.load_producer_receipt(
            path=str(receipt_path), expected=stable_digest("wrong-hash"),
            smoke=False, runtime=runtime, digests=source_digests,
            stage="a", mode="cheap", state_set_sha256=state_sha,
        )

    contradictory_path = tmp_path / "contradictory-receipt.json"
    contradictory_path.write_text(json.dumps(contradictory) + "\n")
    contradictory_binding = copy.deepcopy(manifest)
    contradictory_binding["producer_receipt"] = {
        **contradictory_binding["producer_receipt"],
        "path": str(contradictory_path),
        "sha256": gate.sha256_file(str(contradictory_path)),
    }
    assert "producer receipt role/stage/mode" in \
        gate.producer_receipt_problems(contradictory_binding)

    # A copied label cannot manufacture a distinct run by editing its manifest.
    copied = copy.deepcopy(manifest)
    copied["producer_run_id"] = "stage-a-rerun-0002"
    assert "label producer receipt binding" in gate.label_packet_problems(copied)

    # The real gate reopens the pre-existing receipt, so byte mutation after
    # labelling is detected even when the label manifest itself is unchanged.
    receipt_path.write_text(json.dumps({**receipt, "creator_pid": 456}) + "\n")
    assert "producer receipt exact byte hash" in \
        gate.producer_receipt_problems(manifest)


def test_stage_a_receipts_must_have_independent_nonces():
    state_sha = stable_digest("state-set")
    shared_nonce = stable_digest("shared-nonce")
    base = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "complete": True, "stage": "A", "verdict": "PASS",
        "stage_b_authorized": True, "problems": [], "n_states": 64,
        "state_input_sha256": state_sha,
        "state_set": {"path": "states.json", "sha256": state_sha},
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_coverage": packet_lineage()[0],
        "inputs": [
            {"path": f"primary-{index}.json", "shard_index": index,
             "sha256": stable_digest({"primary": index})}
            for index in range(CAPTURE_SHARDS)
        ],
        "reruns": [
            {"path": f"rerun-{index}.json", "shard_index": index,
             "sha256": stable_digest({"rerun": index})}
            for index in range(CAPTURE_SHARDS)
        ],
        "primary_producer_run_id": "stage-a-primary-0001",
        "rerun_producer_run_id": "stage-a-rerun-0002",
        "primary_producer_receipt": {
            "sha256": stable_digest("primary-receipt"),
            "run_id": "stage-a-primary-0001", "role": "stage-a-primary",
            "nonce": shared_nonce,
        },
        "rerun_producer_receipt": {
            "sha256": stable_digest("rerun-receipt"),
            "run_id": "stage-a-rerun-0002", "role": "stage-a-rerun",
            "nonce": shared_nonce,
        },
    }
    assert "Stage-A gate primary/rerun producer receipt reused" in \
        states.stage_a_gate_problems(base, state_sha)
    assert "primary/rerun producer receipt reused" in \
        gate.stage_a_receipt_independence_problems(
            {
                "producer_run_id": base["primary_producer_run_id"],
                "producer_receipt": base["primary_producer_receipt"],
            },
            {
                "producer_run_id": base["rerun_producer_run_id"],
                "producer_receipt": base["rerun_producer_receipt"],
            },
        )
