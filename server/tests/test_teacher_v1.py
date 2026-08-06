"""Bounded executable checks for the teacher-v1 Stage-A/B contract."""
from __future__ import annotations

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
from shengji.teacher_v1 import (EXPERIMENT, GOLD_FOLDS, STATE_SCHEMA,  # noqa: E402
                                TARGET_SCHEMA,
                                derive_stream, replay_state,
                                split_for_deal, stable_digest,
                                stage_b_regret, targets, tensor_problems)


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


def test_stage_b_requires_pass_gate_bound_to_exact_stage_a_set():
    gate_payload = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "stage": "A", "verdict": "PASS", "stage_b_authorized": True,
        "problems": [], "state_input_sha256": "stage-a-sha",
    }
    assert states.stage_a_gate_problems(
        gate_payload, "stage-a-sha") == []
    assert "Stage-A gate is not bound to the excluded state set" in \
        states.stage_a_gate_problems(gate_payload, "different")
    gate_payload["verdict"] = "FAIL"
    assert "Stage-A mechanics gate did not pass" in \
        states.stage_a_gate_problems(gate_payload, "stage-a-sha")


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
    common = {
        "schema": states.DIAGNOSTIC_SCHEMA,  # replaced below; avoids magic str
        "experiment_id": EXPERIMENT, "stage": "b", "mode": "gold",
        "git": "abc", "tree_dirty": False, "promotable": True,
        "target_schema": TARGET_SCHEMA, "fast_engine": True,
        "require_voids": True, "source_digests": {"code": "x"},
        "shard_count": 2, "continuation": "mc-strong@N=30",
        "counts": dict(GOLD_FOLDS), "state_input_sha256": "frozen-states",
        "state_contract": {
            "one_state_per_deal": True,
            "exam_exclusion": {"verified": True, "overlap": 0,
                               "sources": [{"path": "exam"}]},
            "actor": {"policy": "mc-strong", "identity": "actor"},
        },
        "complete": True,
    }
    paths = []
    for index in range(2):
        records = [{"state_id": f"s{index}"}]
        payload = {
            **common, "schema": gate.GOLD_SHARD_SCHEMA,
            "shard_index": index, "input_sha256": f"cheap-shard-{index}",
            "n_records": 1, "records": records,
            "records_digest": gate.records_digest(records),
        }
        path = tmp_path / f"gold-{index}.json"
        path.write_text(json.dumps(payload))
        paths.append(str(path))
    _, records, problems = gate.load_shards(
        paths, schema=gate.GOLD_SHARD_SCHEMA, stage="b", mode="gold"
    )
    assert problems == []
    assert len(records) == 2


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

    cheap_payload = {
        "records": [], "records_digest": label.deterministic_records_digest([]),
        "n_records": 0, "git": runtime["git"], "source_digests": digests,
        "target_schema": TARGET_SCHEMA, "fast_engine": True,
        "require_voids": True, "counts": dict(label.CHEAP_FOLDS),
        "candidate_world_work": 0,
    }
    assert label.cheap_parent_problems(
        cheap_payload, runtime, digests, smoke=False) == []
    cheap_payload["source_digests"] = {**digests, "mcbot_sampler": "stale"}
    assert "cheap-parent executable source drift" in label.cheap_parent_problems(
        cheap_payload, runtime, digests, smoke=False)
