"""Bounded executable checks for the teacher-v1 Stage-A/B contract."""
from __future__ import annotations

import copy
import json
import math
import os
import random
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_v1_gate as gate  # noqa: E402
import teacher_v1_label as label  # noqa: E402
import teacher_v1_receipt as receipt  # noqa: E402
import teacher_v1_states as states  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.teacher_v1 import (CAPTURE_MAX_DEALS, CAPTURE_PACKET_ID,  # noqa: E402
                                CAPTURE_SHARDS, EXPERIMENT, GOLD_FOLDS,
                                PRODUCER_RECEIPT_SCHEMA,
                                SEED_START, STATE_SCHEMA, STATE_SET_SCHEMA,
                                TARGET_SCHEMA,
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


def raw_state(seed=SEED_START + 123, *, follow=False):
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
    identity = dict(experiment_id=EXPERIMENT, deal_seed=SEED_START + 1,
                    state_id="s", purpose="belief", fold="selection")
    assert derive_stream(**identity) == derive_stream(**identity)
    assert derive_stream(**identity)["seed"] != derive_stream(
        **{**identity, "fold": "report"})["seed"]
    with pytest.raises(ValueError, match="common across candidates"):
        derive_stream(**identity, candidate=2)


def test_split_is_deal_disjoint_and_approximately_70_15_15():
    got = [split_for_deal(EXPERIMENT, SEED_START + i) for i in range(2000)]
    assert 1300 < got.count("train") < 1500
    assert 240 < got.count("tune") < 360
    assert 240 < got.count("holdout") < 360


@pytest.mark.parametrize("flag", states.EXPERIMENTAL_SAMPLER_BALLOT_FLAGS)
@pytest.mark.parametrize("value", ["1", ""])
def test_real_state_runtime_refuses_experimental_sampler_and_ballot_flags(
    monkeypatch, flag, value,
):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    # Presence is refused even when the shell value is empty: artifacts claim
    # the keys were unset, and import-time flag semantics must not be inferred
    # from a later or differently parsed representation.
    monkeypatch.setenv(flag, value)
    with pytest.raises(states.TeacherProtocolError, match="must be unset"):
        states.runtime(False)


@pytest.mark.parametrize("runtime_name", ["label", "gate"])
@pytest.mark.parametrize("flag", states.EXPERIMENTAL_SAMPLER_BALLOT_FLAGS)
@pytest.mark.parametrize("value", ["1", ""])
def test_late_teacher_runtime_refuses_present_experimental_flags(
        monkeypatch, runtime_name, flag, value):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv(flag, value)
    runtime = label.runtime_contract if runtime_name == "label" else \
        gate.gate_runtime
    args = (False,) if runtime_name == "label" else ()
    with pytest.raises(states.TeacherProtocolError, match="must be unset"):
        runtime(*args)


@pytest.mark.parametrize("runtime_name", ["label", "gate"])
def test_late_teacher_runtime_pins_exact_python(monkeypatch, runtime_name):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    module = label if runtime_name == "label" else gate
    monkeypatch.setattr(module.sys, "version", "3.14.5 test-runtime")
    runtime = label.runtime_contract if runtime_name == "label" else \
        gate.gate_runtime
    args = (False,) if runtime_name == "label" else ()
    with pytest.raises(states.TeacherProtocolError, match="requires Python 3.14.6"):
        runtime(*args)


def test_state_artifact_publication_is_exclusive_and_removes_partial(tmp_path):
    output = tmp_path / "artifact.json"
    states.write_exclusive(str(output), {"winner": "producer"})
    assert json.loads(output.read_text()) == {"winner": "producer"}
    assert not Path(str(output) + ".partial").exists()


def test_state_artifact_concurrent_winner_cannot_be_overwritten(
    tmp_path, monkeypatch,
):
    output = tmp_path / "artifact.json"
    partial = Path(str(output) + ".partial")
    real_link = states.os.link

    def competing_publish(source, destination):
        Path(destination).write_text('{"winner":"competitor"}\n')
        return real_link(source, destination)

    monkeypatch.setattr(states.os, "link", competing_publish)
    with pytest.raises(states.TeacherProtocolError, match="partial remains"):
        states.write_exclusive(str(output), {"winner": "candidate"})
    assert json.loads(output.read_text()) == {"winner": "competitor"}
    assert json.loads(partial.read_text()) == {"winner": "candidate"}


def test_state_artifact_dangling_final_symlink_refuses_and_keeps_partial(
    tmp_path,
):
    output = tmp_path / "artifact.json"
    output.symlink_to(tmp_path / "missing-target.json")
    partial = Path(str(output) + ".partial")
    with pytest.raises(states.TeacherProtocolError, match="partial remains"):
        states.write_exclusive(str(output), {"winner": "candidate"})
    assert output.is_symlink()
    assert os.readlink(output).endswith("missing-target.json")
    assert json.loads(partial.read_text()) == {"winner": "candidate"}


def test_state_artifact_existing_partial_is_never_reused(tmp_path):
    output = tmp_path / "artifact.json"
    partial = Path(str(output) + ".partial")
    partial.write_text('{"winner":"old-attempt"}\n')
    with pytest.raises(states.TeacherProtocolError, match="existing partial"):
        states.write_exclusive(str(output), {"winner": "candidate"})
    assert json.loads(partial.read_text()) == {"winner": "old-attempt"}
    assert not output.exists()


def _late_artifact_writer(name):
    if name == "receipt":
        return receipt.write_exclusive, receipt
    if name == "gate":
        return gate.write_gate, gate
    return label.write_complete, label


@pytest.mark.parametrize("writer_name", ["receipt", "label", "gate"])
def test_receipt_and_label_publication_is_exclusive(tmp_path, writer_name):
    writer, _ = _late_artifact_writer(writer_name)
    output = tmp_path / f"{writer_name}.json"
    writer(str(output), {"winner": "producer"})
    assert json.loads(output.read_text()) == {"winner": "producer"}
    assert not Path(str(output) + ".partial").exists()


@pytest.mark.parametrize("writer_name", ["receipt", "label", "gate"])
def test_receipt_and_label_collision_cannot_overwrite_winner(
        tmp_path, monkeypatch, writer_name):
    writer, module = _late_artifact_writer(writer_name)
    output = tmp_path / f"{writer_name}.json"
    partial = Path(str(output) + ".partial")
    real_link = module.os.link

    def competing_publish(source, destination):
        Path(destination).write_text('{"winner":"competitor"}\n')
        return real_link(source, destination)

    monkeypatch.setattr(module.os, "link", competing_publish)
    with pytest.raises(module.TeacherProtocolError, match="partial remains"):
        writer(str(output), {"winner": "candidate"})
    assert json.loads(output.read_text()) == {"winner": "competitor"}
    assert json.loads(partial.read_text()) == {"winner": "candidate"}


@pytest.mark.parametrize("writer_name", ["receipt", "label", "gate"])
def test_receipt_and_label_verification_failure_keeps_partial_marker(
        tmp_path, writer_name):
    writer, module = _late_artifact_writer(writer_name)
    output = tmp_path / f"{writer_name}.json"
    partial = Path(str(output) + ".partial")

    def refuse():
        raise module.TeacherProtocolError("injected verification refusal")

    with pytest.raises(module.TeacherProtocolError,
                       match="injected verification refusal"):
        writer(str(output), {"winner": "candidate"}, verify=refuse)
    assert json.loads(output.read_text()) == {"winner": "candidate"}
    assert json.loads(partial.read_text()) == {"winner": "candidate"}
    with pytest.raises(gate.TeacherProtocolError, match="partial artifact remains"):
        gate.load_json_artifact(str(output))


@pytest.mark.parametrize("writer_name", ["receipt", "label", "gate"])
def test_receipt_and_label_dangling_final_refuses_and_keeps_partial(
        tmp_path, writer_name):
    writer, module = _late_artifact_writer(writer_name)
    output = tmp_path / f"{writer_name}.json"
    output.symlink_to(tmp_path / "missing-final-target.json")
    partial = Path(str(output) + ".partial")
    with pytest.raises(module.TeacherProtocolError, match="partial remains"):
        writer(str(output), {"winner": "candidate"})
    assert output.is_symlink()
    assert json.loads(partial.read_text()) == {"winner": "candidate"}


@pytest.mark.parametrize("writer_name", ["receipt", "label", "gate"])
def test_receipt_and_label_dangling_partial_is_never_followed(
        tmp_path, writer_name):
    writer, module = _late_artifact_writer(writer_name)
    output = tmp_path / f"{writer_name}.json"
    target = tmp_path / "missing-partial-target.json"
    partial = Path(str(output) + ".partial")
    partial.symlink_to(target)
    with pytest.raises(module.TeacherProtocolError, match="existing partial"):
        writer(str(output), {"winner": "candidate"})
    assert partial.is_symlink()
    assert not target.exists()
    assert not output.exists()


def test_receipt_label_and_gate_verification_refuse_dangling_partial(tmp_path):
    artifact = tmp_path / "artifact.json"
    payload = {"complete": True}
    artifact.write_text(json.dumps(payload) + "\n")
    digest = label.sha256_file(artifact)
    partial = Path(str(artifact) + ".partial")
    partial.symlink_to(tmp_path / "missing-partial-target.json")

    with pytest.raises(label.TeacherProtocolError, match="partial artifact remains"):
        label.load_pinned(str(artifact), digest)
    with pytest.raises(gate.TeacherProtocolError, match="partial artifact remains"):
        gate.load_json_artifact(str(artifact))
    with pytest.raises(receipt.TeacherProtocolError,
                       match="partial artifact remains"):
        receipt.verify_published_receipt(
            str(artifact), payload, runtime={}, sources={}, stage="a",
            mode="cheap", state_set_sha256=stable_digest("state-set"),
        )
    _, _, problems = gate.load_shards(
        [str(artifact)], schema="schema", stage="a", mode="cheap")
    assert any("partial artifact remains" in problem for problem in problems)


def test_gate_final_drift_refuses_and_keeps_forensic_partial(tmp_path):
    output = tmp_path / "stage-a-gate.json"
    state_set = {"stage": "a"}
    payload = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "complete": True, "stage": "A", "verdict": "FAIL",
        "stage_b_authorized": False, "stage_c_authorized": False,
        "problems": ["expected mechanics failure"],
    }

    def mutate_then_verify():
        output.write_text(json.dumps({**payload, "verdict": "PASS"}) + "\n")
        gate.verify_published_gate(
            str(output), payload, state_set=state_set,
            state_set_path=str(tmp_path / "states.json"),
            expected_state_set_sha256=stable_digest("state-set"),
            runtime={}, allow_partial=True,
        )

    with pytest.raises(gate.TeacherProtocolError,
                       match="published gate differs"):
        gate.write_gate(str(output), payload, verify=mutate_then_verify)
    partial = Path(str(output) + ".partial")
    assert output.exists() and partial.exists()
    assert json.loads(output.read_text())["verdict"] == "PASS"
    assert json.loads(partial.read_text())["verdict"] == "PASS"
    with pytest.raises(gate.TeacherProtocolError, match="partial artifact remains"):
        gate.load_json_artifact(str(output))


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


def test_real_freeze_refuses_a_seven_shard_subset_before_runtime():
    with pytest.raises(states.TeacherProtocolError, match="exactly 8"):
        states.freeze(SimpleNamespace(smoke=False, input=["diag"] * 7))


def test_real_freeze_refuses_eight_shards_with_less_than_1024_deals(
    tmp_path, monkeypatch,
):
    manifests = [valid_diagnostic_manifest(index)
                 for index in range(CAPTURE_SHARDS)]
    manifests[0]["capture_scanned_seeds"].pop()
    manifests[0]["capture_scanned_seeds_sha256"] = stable_digest(
        manifests[0]["capture_scanned_seeds"]
    )
    paths = []
    for index, manifest in enumerate(manifests):
        path = tmp_path / f"diagnostic-{index}.json"
        path.write_text(json.dumps(manifest) + "\n")
        paths.append(str(path))
    live = {
        key: manifests[0][key] for key in (
            "git", "python", "tree_dirty", "promotable", "fast_engine",
            "require_voids", "fast_binary_sha256", "fast_router_sha256",
            "state_script_sha256",
        )
    }
    monkeypatch.setattr(states, "runtime", lambda _smoke: live)
    monkeypatch.setattr(
        states, "actor_identity", lambda: manifests[0]["actor"],
    )
    args = SimpleNamespace(
        smoke=False, input=paths, stage="a", exclude_state_set=None,
        stage_a_gate=None, out=str(tmp_path / "stage-a.json"),
    )
    with pytest.raises(states.TeacherProtocolError, match="exact 1,024-deal"):
        states.freeze(args)


def test_stage_b_freeze_postcondition_refuses_excluded_deal_reentry(
    tmp_path, monkeypatch,
):
    actor = {"policy": "mc-strong", "identity": stable_digest("actor")}
    live = {
        "git": "abc", "python": "3.14.6", "tree_dirty": False,
        "promotable": False, "fast_engine": True, "require_voids": True,
        "fast_binary_sha256": stable_digest("binary"),
        "fast_router_sha256": stable_digest("router"),
        "state_script_sha256": stable_digest("states"),
    }
    diagnostic = {
        "schema": states.DIAGNOSTIC_SCHEMA, "complete": True,
        "records": [], "records_digest": stable_digest([]),
        "actor": actor, "exam_exclusion": {"verified": True},
        **live,
    }
    diagnostic_path = tmp_path / "diagnostic.json"
    diagnostic_path.write_text(json.dumps(diagnostic) + "\n")
    excluded_seed = SEED_START + 17
    prior_path = tmp_path / "stage-a.json"
    prior_path.write_text(json.dumps({
        "states": [{"state_id": "excluded", "seed": excluded_seed}],
    }) + "\n")
    selected = [
        {"state_id": f"selected-{index}",
         "seed": excluded_seed if index == 0 else SEED_START + 100 + index}
        for index in range(states.STAGE_B_STATES)
    ]
    monkeypatch.setattr(states, "runtime", lambda _smoke: live)
    monkeypatch.setattr(states, "actor_identity", lambda: actor)
    monkeypatch.setattr(states, "stage_a_exclusion_problems", lambda *_args: [])
    monkeypatch.setattr(states, "replay_state", lambda _state: None)
    monkeypatch.setattr(
        states, "select_gate_states", lambda *_args: (selected, []),
    )
    args = SimpleNamespace(
        smoke=True, input=[str(diagnostic_path)], stage="b",
        exclude_state_set=str(prior_path), stage_a_gate=None,
        out=str(tmp_path / "stage-b.json"),
    )
    with pytest.raises(
        states.TeacherProtocolError, match="overlap Stage A exclusions",
    ):
        states.freeze(args)

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
    records = [gold_record(0.05, SEED_START + i) for i in range(128)]
    result = stage_b_regret(records)
    assert result["passed"] is True
    assert result["n_states"] == 128
    assert result["upper_95"] == pytest.approx(0.05)
    records[-1] = gold_record(8.0, SEED_START + 1_000)
    result = stage_b_regret(records)
    assert result["passed"] is False
    assert result["upper_95"] > 0.10


def test_stage_b_nonzero_state_variance_can_fail_above_a_sub_limit_mean():
    regrets = [0.0] * 64 + [0.18] * 64
    records = [
        gold_record(regret, SEED_START + 2_000 + index)
        for index, regret in enumerate(regrets)
    ]
    result = stage_b_regret(records)
    mean = sum(regrets) / len(regrets)
    variance = sum((value - mean) ** 2 for value in regrets) / 127
    se = math.sqrt(variance / 128)
    assert mean < result["limit"]
    assert result["critical"] == pytest.approx(1.66)
    assert result["mean_regret"] == pytest.approx(mean)
    assert result["se"] == pytest.approx(se)
    assert result["upper_95"] == pytest.approx(mean + 1.66 * se)
    assert result["upper_95"] > result["limit"]
    assert result["passed"] is False


def test_stage_b_short_artifact_is_inconclusive_not_pass():
    result = stage_b_regret([gold_record(0.0, SEED_START + 3_000 + i)
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
                for SEED in range(SEED_START, SEED_START + 1_000)]
    assert all(t == states.target_for_deal(EXPERIMENT, SEED_START + i)
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
    artifact_sha256s = []
    _, records, problems = gate.load_shards(
        paths, schema=gate.GOLD_SHARD_SCHEMA, stage="b", mode="gold",
        artifact_sha256s=artifact_sha256s,
    )
    assert problems == []
    assert len(records) == 128
    assert artifact_sha256s == [gate.sha256_file(path) for path in paths]
    assert gate.artifact_drift_problems(
        paths, artifact_sha256s, population="gold label") == []

    original_last = Path(paths[-1]).read_bytes()
    Path(paths[-1]).write_bytes(original_last + b" ")
    assert "gold label artifact changed during gate validation" in \
        gate.artifact_drift_problems(
            paths, artifact_sha256s, population="gold label")
    Path(paths[-1]).write_bytes(original_last)

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
               "seed_start": SEED_START, "states": []}
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


def test_live_cheap_record_is_json_domain_before_publication():
    record = label.cheap_record(
        raw_state(), label.make_bot("mc-strong", seed=1),
        {"selection": 1, "report": 1},
    )
    assert isinstance(record["ballot_spec"]["config"], list)
    assert json.loads(json.dumps(record, sort_keys=True)) == record


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
    repaired_runtime = dict(runtime, git="f" * 40)
    assert label.state_source_problems(
        state_payload, repaired_runtime, digests) == []
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


def test_stage_b_source_transition_is_exact_and_mutation_falsifiable(
        monkeypatch):
    current_git = "c" * 40
    old_state_source = stable_digest("old-state-freezer")
    live = {
        "git": current_git,
        "fast_binary_sha256": stable_digest("compiled"),
        "fast_router_sha256": stable_digest("router"),
        "state_script_sha256": states.sha256_file(states.__file__),
    }
    diagnostic = {
        "git": states.STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
        "fast_binary_sha256": live["fast_binary_sha256"],
        "fast_router_sha256": live["fast_router_sha256"],
        "state_script_sha256": old_state_source,
    }
    state_set = {
        "git": states.STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
        "state_script_sha256": old_state_source,
    }
    gate_sources = {
        "compiled_engine": live["fast_binary_sha256"],
        "fast_router": live["fast_router_sha256"],
        "state_script": old_state_source,
        "gate_script": states.sha256_file(SCRIPTS / "teacher_v1_gate.py"),
        "label_script": states.sha256_file(SCRIPTS / "teacher_v1_label.py"),
        "producer_receipt_script": states.sha256_file(
            SCRIPTS / "teacher_v1_receipt.py"),
        "teacher_contract": states.sha256_file(
            SCRIPTS.parent / "shengji" / "teacher_v1.py"),
    }
    gate_payload = {
        "git": states.STAGE_B_TRANSITION_GATE_GIT,
        "gate_source_digests": gate_sources,
    }

    def exact_diff(parent, child):
        if (parent, child) == (
                states.STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
                states.STAGE_B_TRANSITION_GATE_GIT):
            return states.STAGE_B_TRANSITION_DIAGNOSTIC_TO_GATE_PATHS
        assert (parent, child) == (
            states.STAGE_B_TRANSITION_GATE_GIT, current_git)
        return states.STAGE_B_TRANSITION_GATE_TO_FREEZER_PATHS

    monkeypatch.setattr(states, "git_is_ancestor", lambda _parent, _child: True)
    monkeypatch.setattr(states, "git_changed_paths", exact_diff)
    problems, binding = states.stage_b_source_transition_problems(
        diagnostic, state_set, states.STAGE_B_TRANSITION_STATE_SHA256,
        gate_payload, states.STAGE_B_TRANSITION_GATE_SHA256, live,
        states.STAGE_B_SOURCE_TRANSITION_ID,
    )
    assert problems == []
    assert binding["freezer_git"] == current_git
    assert binding["frozen_state_script_sha256"] == old_state_source
    assert binding["freezer_script_sha256"] == live["state_script_sha256"]
    assert binding["historical_ancestry"] is True
    assert binding["freezer_ancestry"] is True

    problems, no_binding = states.stage_b_source_transition_problems(
        diagnostic, state_set, states.STAGE_B_TRANSITION_STATE_SHA256,
        gate_payload, states.STAGE_B_TRANSITION_GATE_SHA256, live, None,
    )
    assert problems == ["Stage-B source transition id missing or unknown"]
    assert no_binding is None

    problems, _ = states.stage_b_source_transition_problems(
        diagnostic, state_set, stable_digest("wrong-state-set"),
        gate_payload, states.STAGE_B_TRANSITION_GATE_SHA256, live,
        states.STAGE_B_SOURCE_TRANSITION_ID,
    )
    assert "Stage-B transition state-set SHA-256 drift" in problems

    mutated = copy.deepcopy(gate_payload)
    mutated["gate_source_digests"]["label_script"] = stable_digest("drift")
    problems, _ = states.stage_b_source_transition_problems(
        diagnostic, state_set, states.STAGE_B_TRANSITION_STATE_SHA256,
        mutated, states.STAGE_B_TRANSITION_GATE_SHA256, live,
        states.STAGE_B_SOURCE_TRANSITION_ID,
    )
    assert "Stage-B transition label_script source drift" in problems

    monkeypatch.setattr(
        states, "git_changed_paths",
        lambda parent, child: (
            states.STAGE_B_TRANSITION_DIAGNOSTIC_TO_GATE_PATHS
            if parent == states.STAGE_B_TRANSITION_DIAGNOSTIC_GIT else
            (*states.STAGE_B_TRANSITION_GATE_TO_FREEZER_PATHS,
             "server/shengji/engine/round.py")
        ),
    )
    problems, _ = states.stage_b_source_transition_problems(
        diagnostic, state_set, states.STAGE_B_TRANSITION_STATE_SHA256,
        gate_payload, states.STAGE_B_TRANSITION_GATE_SHA256, live,
        states.STAGE_B_SOURCE_TRANSITION_ID,
    )
    assert "Stage-B transition freezer diff scope" in problems

    monkeypatch.setattr(
        states, "git_changed_paths", exact_diff,
    )
    monkeypatch.setattr(
        states, "git_is_ancestor",
        lambda parent, _child: parent != states.STAGE_B_TRANSITION_GATE_GIT,
    )
    problems, _ = states.stage_b_source_transition_problems(
        diagnostic, state_set, states.STAGE_B_TRANSITION_STATE_SHA256,
        gate_payload, states.STAGE_B_TRANSITION_GATE_SHA256, live,
        states.STAGE_B_SOURCE_TRANSITION_ID,
    )
    assert "Stage-B transition freezer ancestry" in problems


def test_stage_a_gate_transition_skips_only_validated_git_and_freezer_source():
    old_state_source = stable_digest("old-state-freezer")
    live = {
        "git": "c" * 40, "python": "3.14.6",
        "fast_engine": True, "require_voids": True,
        "fast_binary_sha256": stable_digest("compiled"),
        "fast_router_sha256": stable_digest("router"),
        "state_script_sha256": stable_digest("new-state-freezer"),
    }
    sources = {
        "compiled_engine": live["fast_binary_sha256"],
        "fast_router": live["fast_router_sha256"],
        "state_script": old_state_source,
        "gate_script": states.sha256_file(SCRIPTS / "teacher_v1_gate.py"),
        "label_script": states.sha256_file(SCRIPTS / "teacher_v1_label.py"),
        "producer_receipt_script": states.sha256_file(
            SCRIPTS / "teacher_v1_receipt.py"),
        "teacher_contract": states.sha256_file(
            SCRIPTS.parent / "shengji" / "teacher_v1.py"),
    }
    payload = {
        "git": states.STAGE_B_TRANSITION_GATE_GIT,
        "python": live["python"], "fast_engine": True,
        "require_voids": True, "gate_source_digests": sources,
    }
    binding = {"transition_id": states.STAGE_B_SOURCE_TRANSITION_ID}
    problems = states.stage_a_gate_problems(
        payload, stable_digest("state-set"), runtime_identity=live,
        source_transition=binding,
    )
    assert "Stage-A gate/current git drift" not in problems
    assert "Stage-A gate/current executable source drift" not in problems
    assert not any("state_script source drift" in problem
                   for problem in problems)

    mutated = copy.deepcopy(payload)
    mutated["gate_source_digests"]["label_script"] = stable_digest("drift")
    assert "Stage-A gate/current label_script source drift" in \
        states.stage_a_gate_problems(
            mutated, stable_digest("state-set"), runtime_identity=live,
            source_transition=binding,
        )


def test_stage_b_packet_requires_and_binds_registered_source_transition():
    payload = {
        "stage": "b",
        "excluded_stage_a": {
            "sha256": states.STAGE_B_TRANSITION_STATE_SHA256,
        },
        "stage_a_gate": {"sha256": states.STAGE_B_TRANSITION_GATE_SHA256},
    }
    assert "state-set Stage-B source transition missing" in \
        states.state_set_packet_problems(payload)

    payload["source_transition"] = {
        "schema": "teacher-v1-stage-b-source-transition-v1",
        "transition_id": states.STAGE_B_SOURCE_TRANSITION_ID,
        "diagnostic_git": states.STAGE_B_TRANSITION_DIAGNOSTIC_GIT,
        "stage_a_gate_git": states.STAGE_B_TRANSITION_GATE_GIT,
        "freezer_git": "c" * 40,
        "state_set_sha256": states.STAGE_B_TRANSITION_STATE_SHA256,
        "stage_a_gate_sha256": states.STAGE_B_TRANSITION_GATE_SHA256,
        "diagnostic_to_gate_paths": list(
            states.STAGE_B_TRANSITION_DIAGNOSTIC_TO_GATE_PATHS),
        "gate_to_freezer_paths": list(
            states.STAGE_B_TRANSITION_GATE_TO_FREEZER_PATHS),
        "historical_ancestry": True,
        "freezer_ancestry": True,
        "frozen_state_script_sha256": stable_digest("old-state-freezer"),
        "freezer_script_sha256": stable_digest("new-state-freezer"),
    }
    payload.update({
        "git": payload["source_transition"]["freezer_git"],
        "state_script_sha256": payload["source_transition"][
            "freezer_script_sha256"],
    })
    assert "state-set Stage-B source transition binding" not in \
        states.state_set_packet_problems(payload)

    payload["source_transition"]["transition_id"] = "unregistered"
    assert "state-set Stage-B source transition binding" in \
        states.state_set_packet_problems(payload)


def valid_cheap_record_for_gate(counts=None):
    counts = counts or {"selection": 2, "report": 2}
    state = raw_state()
    rnd = replay_state(state)
    bot = make_bot("mc-strong", seed=1)
    candidates = [
        list(gate.action_key(action))
        for action in bot._candidates(rnd, state["seat"])
    ]
    assert len(candidates) > 1
    folds = {}
    for fold_name, worlds in counts.items():
        stream = derive_stream(
            experiment_id=state["experiment_id"], deal_seed=state["seed"],
            state_id=state["state_id"], purpose="belief", fold=fold_name,
        )
        utility = [
            [float(-candidate) for candidate in range(len(candidates))]
            for _ in range(worlds)
        ]
        tensor = {
            target: copy.deepcopy(utility) for target in (
                "attacker_points", "signed_points", "bracket",
                "signed_level_utility",
            )
        }
        counters = {name: 0 for name in gate.SAMPLER_COUNTERS}
        counters["sample_attempts"] = worlds
        counters["accepted_worlds"] = worlds
        folds[fold_name] = {
            "requested_worlds": worlds,
            "stream": stream,
            "draw_ids": [
                stable_digest({"stream": stream, "index": index})
                for index in range(worlds)
            ],
            "world_digests": [
                stable_digest({"fold": fold_name, "world": index})
                for index in range(worlds)
            ],
            "tensor": tensor,
            "sampler_counters": counters,
            "continuation_seeds": [
                [index * 100 + candidate for candidate in range(len(candidates))]
                for index in range(worlds)
            ],
            "evaluation_seeds": [
                [index * 1_000 + candidate
                 for candidate in range(len(candidates))]
                for index in range(worlds)
            ],
        }
    totals = {
        name: sum(fold["sampler_counters"][name] for fold in folds.values())
        for name in gate.SAMPLER_COUNTERS
    }
    paired = {}
    for fold_name, fold in folds.items():
        matrix = fold["tensor"]["signed_level_utility"]
        paired[fold_name] = [
            gate.paired_moments([row[index] - row[0] for row in matrix])
            for index in range(len(candidates))
        ]
    return {
        "state_id": state["state_id"],
        "deal_seed": state["seed"],
        "state": state,
        "replay_digest": stable_digest(state),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "ballot_spec": {"digest": gate.mc_ballot(bot).digest},
        "folds": folds,
        "sampler_counters": totals,
        "candidate_world_work": len(candidates) * sum(counts.values()),
        "cheap_selected_index": 0,
        "cheap_selection_means": [
            float(-candidate) for candidate in range(len(candidates))
        ],
        "paired_vs_candidate0": paired,
    }


def test_cheap_record_gate_falsifies_target_action_and_counter_drift():
    counts = {"selection": 2, "report": 2}
    record = valid_cheap_record_for_gate(counts)
    assert gate.cheap_record_problems(record, counts) == []

    malformed_target = copy.deepcopy(record)
    del malformed_target["folds"]["selection"]["tensor"]["bracket"]
    assert any("bracket tensor shape" in problem for problem in
               gate.cheap_record_problems(malformed_target, counts))

    altered_action = copy.deepcopy(record)
    altered_action["candidates"][0], altered_action["candidates"][1] = (
        altered_action["candidates"][1], altered_action["candidates"][0]
    )
    assert any("not the complete current ballot in order" in problem
               for problem in gate.cheap_record_problems(
                   altered_action, counts))

    bad_counters = copy.deepcopy(record)
    bad_counters["folds"]["report"]["sampler_counters"][
        "accepted_worlds"
    ] -= 1
    assert any("accepted 1 worlds, expected 2" in problem
               for problem in gate.cheap_record_problems(
                   bad_counters, counts))


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
        "git": "abc", "python": "3.14.6", "tree_dirty": False,
        "promotable": True, "fast_engine": True, "require_voids": True,
        "host": "producer-host", "experimental_sampler_ballot_flags": [],
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
    stale_runtime = {**receipt, "host": "different-host"}
    assert "producer receipt/runtime host drift" in \
        label.producer_receipt_problems(
            stale_runtime, runtime=runtime, digests=source_digests,
            stage="a", mode="cheap", state_set_sha256=state_sha,
        )
    flagged = {**receipt, "experimental_sampler_ballot_flags": ["flag"]}
    assert "producer receipt/runtime experimental_sampler_ballot_flags drift" in \
        label.producer_receipt_problems(
            flagged, runtime=runtime, digests=source_digests,
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
    missing_receipt = copy.deepcopy(manifest)
    missing_receipt["producer_receipt"]["path"] = str(
        tmp_path / "missing-receipt.json"
    )
    assert any("producer receipt unreadable" in problem for problem in
               gate.producer_receipt_problems(missing_receipt))
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


def test_label_publication_reopens_parent_receipt_runtime_and_sources(
        tmp_path, monkeypatch):
    runtime = {
        "git": "abc", "tree_dirty": False, "promotable": True,
        "host": "producer-host", "python": "3.14.6",
        "fast_engine": True, "require_voids": True,
        "experimental_sampler_ballot_flags": [],
    }
    digests = {"source": stable_digest("source")}
    parent_path = tmp_path / "stage-a-states.json"
    parent = {"complete": True, "states": [{"state_id": "state-1"}]}
    parent_path.write_text(json.dumps(parent, sort_keys=True) + "\n")
    parent_sha = label.sha256_file(parent_path)
    receipt_payload = {
        "schema": PRODUCER_RECEIPT_SCHEMA,
        "experiment_id": EXPERIMENT,
        "packet_id": CAPTURE_PACKET_ID,
        "capture_packet": capture_packet(),
        "complete": True,
        "run_id": "stage-a-primary-0001",
        "role": "stage-a-primary", "stage": "a", "mode": "cheap",
        "state_set": {"path": str(parent_path), "sha256": parent_sha},
        "nonce": stable_digest("nonce"), "created_time_ns": 1,
        "creator_pid": 1, **runtime, "source_digests": digests,
    }
    receipt_path = tmp_path / "stage-a-primary-receipt.json"
    receipt_path.write_text(json.dumps(receipt_payload, sort_keys=True) + "\n")
    receipt_sha = label.sha256_file(receipt_path)
    receipt_binding = {
        "path": str(receipt_path), "sha256": receipt_sha,
        "run_id": receipt_payload["run_id"], "role": receipt_payload["role"],
        "nonce": receipt_payload["nonce"],
    }
    monkeypatch.setattr(label, "runtime_contract", lambda _smoke: runtime)
    monkeypatch.setattr(label, "source_digests", lambda: digests)

    kwargs = {
        "parent_path": str(parent_path), "parent_sha256": parent_sha,
        "expected_parent": parent,
        "receipt_path": str(receipt_path), "receipt_sha256": receipt_sha,
        "expected_receipt": receipt_payload,
        "expected_receipt_binding": receipt_binding,
        "smoke": False, "runtime": runtime, "digests": digests,
        "stage": "a", "mode": "cheap", "state_set_sha256": parent_sha,
    }
    label.revalidate_publication_inputs(**kwargs)
    receipt.revalidate_receipt_inputs(
        state_set_path=str(parent_path), state_set_sha256=parent_sha,
        expected_state_set=parent, runtime=runtime, sources=digests,
    )

    parent_path.write_text(json.dumps({**parent, "complete": False}) + "\n")
    with pytest.raises(label.TeacherProtocolError, match="input digest mismatch"):
        label.revalidate_publication_inputs(**kwargs)
    with pytest.raises(receipt.TeacherProtocolError, match="input digest mismatch"):
        receipt.revalidate_receipt_inputs(
            state_set_path=str(parent_path), state_set_sha256=parent_sha,
            expected_state_set=parent, runtime=runtime, sources=digests,
        )
    parent_path.write_text(json.dumps(parent, sort_keys=True) + "\n")

    receipt_path.write_text(json.dumps(
        {**receipt_payload, "creator_pid": 2}, sort_keys=True) + "\n")
    with pytest.raises(label.TeacherProtocolError, match="input digest mismatch"):
        label.revalidate_publication_inputs(**kwargs)
    receipt_path.write_text(json.dumps(receipt_payload, sort_keys=True) + "\n")

    monkeypatch.setattr(
        label, "runtime_contract",
        lambda _smoke: {**runtime, "host": "different-host"},
    )
    with pytest.raises(label.TeacherProtocolError, match="runtime changed"):
        label.revalidate_publication_inputs(**kwargs)
    with pytest.raises(receipt.TeacherProtocolError, match="runtime changed"):
        receipt.revalidate_receipt_inputs(
            state_set_path=str(parent_path), state_set_sha256=parent_sha,
            expected_state_set=parent, runtime=runtime, sources=digests,
        )

    monkeypatch.setattr(label, "runtime_contract", lambda _smoke: runtime)
    monkeypatch.setattr(label, "source_digests", lambda: {"source": "drift"})
    with pytest.raises(label.TeacherProtocolError, match="digests changed"):
        label.revalidate_publication_inputs(**kwargs)
    with pytest.raises(receipt.TeacherProtocolError, match="digests changed"):
        receipt.revalidate_receipt_inputs(
            state_set_path=str(parent_path), state_set_sha256=parent_sha,
            expected_state_set=parent, runtime=runtime, sources=digests,
        )


def test_receipt_main_wires_pre_and_post_publication_verification(
        tmp_path, monkeypatch):
    runtime = {
        "git": "abc", "tree_dirty": False, "promotable": True,
        "host": "producer-host", "python": "3.14.6",
        "fast_engine": True, "require_voids": True,
        "experimental_sampler_ballot_flags": [],
    }
    digests = {"source": stable_digest("source")}
    state_set = {
        "schema": STATE_SET_SCHEMA, "experiment_id": EXPERIMENT,
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "stage": "a", "complete": True, "states": [],
        "states_digest": stable_digest([]),
    }
    state_path = tmp_path / "stage-a-states.json"
    state_path.write_text(json.dumps(state_set, sort_keys=True) + "\n")
    output = tmp_path / "primary-receipt.json"
    args = SimpleNamespace(
        run_id="stage-a-primary-0001", role="stage-a-primary",
        state_set=str(state_path),
        expected_state_set_sha256=label.sha256_file(state_path),
        out=str(output),
    )
    monkeypatch.setattr(
        receipt, "parser",
        lambda: SimpleNamespace(parse_args=lambda: args),
    )
    monkeypatch.setattr(label, "runtime_contract", lambda _smoke: runtime)
    monkeypatch.setattr(label, "source_digests", lambda: digests)
    calls = []
    real_revalidate = receipt.revalidate_receipt_inputs

    def tracked_revalidate(**kwargs):
        calls.append(kwargs)
        return real_revalidate(**kwargs)

    monkeypatch.setattr(receipt, "revalidate_receipt_inputs", tracked_revalidate)
    receipt.main()
    assert len(calls) == 2
    assert output.exists()
    assert not Path(str(output) + ".partial").exists()
    payload = json.loads(output.read_text())
    assert payload["state_set"]["sha256"] == args.expected_state_set_sha256
    assert payload["source_digests"] == digests
    assert payload["host"] == runtime["host"]


def test_label_main_wires_pre_and_post_publication_verification(
        tmp_path, monkeypatch):
    runtime = {
        "git": "abc", "tree_dirty": True, "promotable": False,
        "host": "smoke-host", "python": "3.14.3",
        "fast_engine": True, "require_voids": True,
        "experimental_sampler_ballot_flags": [],
    }
    digests = {"source": stable_digest("source")}
    source = {
        "experiment_id": EXPERIMENT,
        "packet_id": CAPTURE_PACKET_ID,
        "capture_packet": capture_packet(),
        "capture_coverage": {},
        "states": [{"state_id": "state-1"}],
    }
    source_path = tmp_path / "smoke-states.json"
    source_path.write_text(json.dumps(source, sort_keys=True) + "\n")
    output = tmp_path / "smoke-label.json"
    args = SimpleNamespace(
        mode="cheap", input=str(source_path),
        expected_input_sha256=label.sha256_file(source_path), stage="a",
        shard_index=0, shard_count=1, producer_receipt=None,
        expected_producer_receipt_sha256=None, out=str(output), smoke=True,
        selection_worlds=1, report_worlds=1,
        gold_selection_worlds=1, gold_report_worlds=1,
    )
    monkeypatch.setattr(
        label, "parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(label, "runtime_contract", lambda _smoke: runtime)
    monkeypatch.setattr(label, "source_digests", lambda: digests)
    monkeypatch.setattr(label, "state_set_problems", lambda *_args, **_kw: [])
    monkeypatch.setattr(label, "state_source_problems", lambda *_args: [])
    monkeypatch.setattr(label, "make_bot", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        label, "cheap_record",
        lambda state, _bot, _counts: {
            "state_id": state["state_id"], "elapsed_seconds": 0.0,
            "candidate_world_work": 2,
            # Regression for the real Stage-A refusal: BallotSpec.config was
            # tuple-valued before serialization, so post-link verification
            # rejected the labeller's own JSON bytes.
            "json_domain_witness": (("MAX_CANDIDATES", 8),),
        },
    )
    calls = []
    real_revalidate = label.revalidate_publication_inputs

    def tracked_revalidate(**kwargs):
        calls.append(kwargs)
        return real_revalidate(**kwargs)

    monkeypatch.setattr(label, "revalidate_publication_inputs", tracked_revalidate)
    label.main()
    assert len(calls) == 2
    assert output.exists()
    assert not Path(str(output) + ".partial").exists()
    payload = json.loads(output.read_text())
    assert payload["input_sha256"] == args.expected_input_sha256
    assert payload["source_digests"] == digests
    assert payload["host"] == runtime["host"]
    assert payload["records"][0]["json_domain_witness"] == [
        ["MAX_CANDIDATES", 8]
    ]


def test_gate_final_verifier_reopens_and_recomputes_passing_stage_a(
        tmp_path, monkeypatch):
    runtime = {
        "git": "abc", "python": "3.14.6", "fast_engine": True,
        "require_voids": True,
        "gate_source_digests": {
            "compiled_engine": stable_digest("compiled"),
            "fast_router": stable_digest("router"),
            "state_script": stable_digest("states"),
        },
    }
    state_set = {"stage": "a", "states": []}
    state_sha = stable_digest("state-set")
    payload = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "complete": True, "stage": "A", "verdict": "PASS",
        "stage_b_authorized": True, "stage_c_authorized": False,
        "problems": [],
    }
    output = tmp_path / "stage-a-gate.json"
    gate.write_gate(str(output), payload)
    monkeypatch.setattr(gate, "gate_runtime", lambda: runtime)
    monkeypatch.setattr(
        gate, "load_state_set",
        lambda *_args: (state_set, []),
    )
    calls = []

    def recompute(actual, actual_sha, actual_state_set, **kwargs):
        calls.append((actual, actual_sha, actual_state_set, kwargs))
        return []

    monkeypatch.setattr(states, "stage_a_gate_problems", recompute)
    digest = gate.verify_published_gate(
        str(output), payload, state_set=state_set,
        state_set_path=str(tmp_path / "stage-a-states.json"),
        expected_state_set_sha256=state_sha, runtime=runtime,
    )
    assert digest == gate.sha256_file(str(output))
    assert len(calls) == 1
    assert calls[0][1:3] == (state_sha, state_set)
    assert calls[0][3] == {
        "runtime_identity": {
            "git": "abc", "python": "3.14.6", "fast_engine": True,
            "require_voids": True,
            "fast_binary_sha256": stable_digest("compiled"),
            "fast_router_sha256": stable_digest("router"),
            "state_script_sha256": stable_digest("states"),
        },
        "verify_artifacts": True,
    }


def test_gate_final_verifier_reopens_and_recomputes_passing_stage_b(
        tmp_path, monkeypatch):
    runtime = {"git": "abc", "python": "3.14.6"}
    state_set = {"stage": "b", "states": []}
    state_sha = stable_digest("stage-b-state-set")
    state_path = str(tmp_path / "stage-b-states.json")
    payload = {
        "schema": states.GATE_SCHEMA, "experiment_id": EXPERIMENT,
        "complete": True, "stage": "B", "verdict": "PASS",
        "stage_c_authorized": True, "problems": [],
        "regret": {"passed": True, "inconclusive": False},
        "cheap_inputs": [], "gold_inputs": [],
    }
    output = tmp_path / "stage-b-gate.json"
    gate.write_gate(str(output), payload)
    monkeypatch.setattr(gate, "gate_runtime", lambda: runtime)
    monkeypatch.setattr(gate, "load_state_set", lambda *_args: (state_set, []))
    calls = []

    def recompute(actual, actual_state_set, actual_path, actual_sha,
                  actual_runtime):
        calls.append((actual, actual_state_set, actual_path, actual_sha,
                      actual_runtime))

    monkeypatch.setattr(gate, "verify_published_stage_b_pass", recompute)
    gate.verify_published_gate(
        str(output), payload, state_set=state_set,
        state_set_path=state_path, expected_state_set_sha256=state_sha,
        runtime=runtime,
    )
    assert calls == [(payload, state_set, state_path, state_sha, runtime)]


def test_stage_b_final_recomputation_refuses_regret_drift(monkeypatch):
    state_sha = stable_digest("stage-b-state-set")
    cheap_hash = stable_digest("cheap-label")
    gold_hash = stable_digest("gold-label")
    shared = {
        "git": "abc", "source_digests": {}, "state_contract": {},
        "state_input_sha256": state_sha, "target_schema": TARGET_SCHEMA,
        "packet_id": CAPTURE_PACKET_ID, "capture_packet": capture_packet(),
        "capture_coverage": packet_lineage()[0], "shard_index": 0,
    }
    cheap_manifest = dict(shared)
    gold_manifest = {**shared, "input_sha256": cheap_hash}
    cheap = [{"state_id": f"state-{index}"} for index in range(128)]
    gold = [{"state_id": f"state-{index}"} for index in range(128)]
    calls = []

    def load(paths, *, mode, artifact_sha256s, **kwargs):
        calls.append((paths, mode, kwargs))
        if mode == "cheap":
            artifact_sha256s.append(cheap_hash)
            return [cheap_manifest], cheap, []
        artifact_sha256s.append(gold_hash)
        return [gold_manifest], gold, []

    regret = {"passed": True, "inconclusive": False, "problems": [],
              "mean_regret": 0.01}
    monkeypatch.setattr(gate, "load_shards", load)
    monkeypatch.setattr(gate, "gate_input_runtime_problems", lambda *_args: [])
    monkeypatch.setattr(gate, "cheap_record_problems", lambda *_args: [])
    monkeypatch.setattr(gate, "stage_contract_problems", lambda *_args: [])
    monkeypatch.setattr(gate, "gold_record_problems", lambda *_args: [])
    monkeypatch.setattr(gate, "stage_b_regret", lambda _records: regret)
    monkeypatch.setattr(gate, "artifact_drift_problems", lambda *_a, **_k: [])
    payload = {
        "n_states": 128, "regret": regret,
        "packet_id": shared["packet_id"],
        "capture_packet": shared["capture_packet"],
        "capture_coverage": shared["capture_coverage"],
        "state_input_sha256": state_sha,
        "state_set": {"path": "states.json", "sha256": state_sha},
        "cheap_inputs": [
            {"path": "cheap.json", "sha256": cheap_hash,
             "shard_index": 0},
        ],
        "gold_inputs": [
            {"path": "gold.json", "sha256": gold_hash,
             "shard_index": 0},
        ],
    }
    gate.verify_published_stage_b_pass(
        payload, {"states": []}, "states.json", state_sha, {})
    assert [call[1] for call in calls] == ["cheap", "gold"]
    assert all(call[2]["verify_receipts"] is True for call in calls)

    payload["regret"] = {**regret, "mean_regret": 0.0}
    with pytest.raises(gate.TeacherProtocolError,
                       match="regret recomputation drift"):
        gate.verify_published_stage_b_pass(
            payload, {"states": []}, "states.json", state_sha, {})


def test_gate_main_keeps_partial_until_final_verification(
        tmp_path, monkeypatch):
    output = tmp_path / "stage-a-gate.json"
    args = SimpleNamespace(
        stage="stage-a", input=["primary.json"], rerun=["rerun.json"],
        state_set="stage-a-states.json",
        expected_state_set_sha256=stable_digest("state-set"),
        out=str(output),
    )
    runtime = {"git": "abc", "python": "3.14.6"}
    state_set = {"stage": "a", "states": []}
    monkeypatch.setattr(
        gate, "parser", lambda: SimpleNamespace(parse_args=lambda: args))
    monkeypatch.setattr(gate, "gate_runtime", lambda: runtime)
    monkeypatch.setattr(
        gate, "load_state_set", lambda *_args: (state_set, []))

    def refuse_shards(_paths, *, artifact_sha256s=None, **_kwargs):
        if artifact_sha256s is not None:
            artifact_sha256s.append(stable_digest(_paths[0]))
        return [], [], ["expected mechanics failure"]

    monkeypatch.setattr(gate, "load_shards", refuse_shards)
    monkeypatch.setattr(gate, "artifact_drift_problems", lambda *_a, **_k: [])
    calls = []

    def verify(path, expected, **kwargs):
        assert os.path.lexists(path + ".partial")
        assert json.loads(Path(path).read_text()) == expected
        calls.append(kwargs)
        return stable_digest(expected)

    monkeypatch.setattr(gate, "verify_published_gate", verify)
    with pytest.raises(SystemExit) as exc:
        gate.main()
    assert exc.value.code == 4
    assert len(calls) == 1
    assert output.exists()
    assert not Path(str(output) + ".partial").exists()


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
