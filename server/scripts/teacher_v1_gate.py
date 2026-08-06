"""Independent fail-closed gates for teacher-v1 Stages A and B.

Stage A requires two deterministic executions of the same frozen 64 states.
Stage B recomputes cheap and gold choices from their selection tensors, then
computes the one-sided clustered regret bound from one gold-report mean per
deal.  A mechanics PASS never authorizes the 2,048-state wave; only a Stage-B
PASS does.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.registry import make_bot                           # noqa: E402
from shengji.engine.ballot import mc_ballot                        # noqa: E402
from shengji.teacher_v1 import (CAPTURE_PACKET_ID, CAPTURE_SHARDS, # noqa: E402
                                CHEAP_FOLDS, CHEAP_SHARD_SCHEMA,
                                EXPERIMENT, GATE_SCHEMA, GOLD_FOLDS,
                                GOLD_SHARD_SCHEMA, REPRESENTATIVE_CELLS,
                                PRODUCER_RECEIPT_SCHEMA,
                                SAMPLER_COUNTERS, STAGE_A_OTHER_STATES,
                                STAGE_A_REPRESENTATIVE_PER_CELL,
                                STAGE_A_STATES, STAGE_B_STATES,
                                STAGE_B_BOUNDARY_STATES,
                                STAGE_B_REPRESENTATIVE_PER_CELL,
                                STAGE_B_UNCERTAINTY_STATES,
                                TeacherProtocolError, action_key,
                                TARGET_SCHEMA,
                                ballot_problems, counter_problems,
                                canonical_state_partition,
                                capture_coverage, capture_packet,
                                derive_stream, paired_moments,
                                is_run_id, is_sha256,
                                replay_state, stable_digest,
                                stage_b_regret, tensor_problems)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def gate_source_digests() -> dict[str, str]:
    """Executable files whose bytes define Stage-A/B gate acceptance."""
    import shengji.teacher_v1 as teacher
    from shengji.engine import fast

    paths = {
        "gate_script": Path(__file__),
        "label_script": Path(__file__).with_name("teacher_v1_label.py"),
        "producer_receipt_script": Path(__file__).with_name(
            "teacher_v1_receipt.py"),
        "state_script": Path(__file__).with_name("teacher_v1_states.py"),
        "teacher_contract": Path(teacher.__file__),
        "fast_router": Path(fast.__file__),
        "compiled_engine": Path(fast._fast.__file__),
    }
    return {name: sha256_file(str(path)) for name, path in sorted(paths.items())}


def gate_runtime() -> dict:
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise TeacherProtocolError("set SHENGJI_REQUIRE_VOIDS=1")
    if os.environ.get("SHENGJI_FAST") != "1":
        raise TeacherProtocolError("set SHENGJI_FAST=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise TeacherProtocolError("compiled engine requested but not active")
    dirty = git_output("status", "--porcelain")
    if dirty:
        raise TeacherProtocolError("real teacher gate refuses a dirty tree")
    return {
        "git": git_output("rev-parse", "HEAD"),
        "tree_dirty": False,
        "promotable": True,
        "host": os.uname().nodename,
        "python": sys.version.split()[0],
        "fast_engine": True,
        "require_voids": True,
        "gate_source_digests": gate_source_digests(),
    }


def gate_input_runtime_problems(manifest: dict, runtime: dict) -> list[str]:
    """Require the gate and label evidence to share one executable identity."""
    bad = []
    for key in ("git", "python", "fast_engine", "require_voids"):
        if manifest.get(key) != runtime.get(key):
            bad.append(f"gate/label {key} drift")
    label_sources = manifest.get("source_digests", {})
    gate_sources = runtime.get("gate_source_digests", {})
    mapping = {
        "compiled_engine": "compiled_engine",
        "fast_router": "fast_router",
        "label_script": "label_script",
        "producer_receipt_script": "producer_receipt_script",
        "state_script": "state_freezer",
        "teacher_contract": "teacher_contract",
    }
    for gate_name, label_name in mapping.items():
        if gate_sources.get(gate_name) != label_sources.get(label_name):
            bad.append(f"gate/label {gate_name} source drift")
    return bad


def deterministic_record(record: dict) -> dict:
    out = dict(record)
    out.pop("elapsed_seconds", None)
    return out


def records_digest(records: list[dict]) -> str:
    return stable_digest([deterministic_record(record) for record in records])


def label_packet_problems(manifest: dict) -> list[str]:
    """Bind a label shard to the exact capture population, not its schema."""
    bad = []
    contract = manifest.get("state_contract", {})
    if not is_run_id(manifest.get("producer_run_id")):
        bad.append("label producer run identity")
    receipt = manifest.get("producer_receipt", {})
    if (not isinstance(receipt, dict)
            or receipt.get("run_id") != manifest.get("producer_run_id")
            or not is_sha256(receipt.get("sha256"))
            or not is_sha256(receipt.get("nonce"))
            or receipt.get("role") not in {
                "stage-a-primary", "stage-a-rerun",
                "stage-b-cheap", "stage-b-gold"}
            or not isinstance(receipt.get("path"), str)):
        bad.append("label producer receipt binding")
    if manifest.get("packet_id") != CAPTURE_PACKET_ID \
            or contract.get("packet_id") != CAPTURE_PACKET_ID:
        bad.append("label capture packet id")
    if (manifest.get("capture_packet") != capture_packet()
            or contract.get("capture_packet") != capture_packet()):
        bad.append("label capture packet identity/range")
    manifest_coverage = manifest.get("capture_coverage", {})
    contract_coverage = contract.get("capture_coverage", {})
    for key, value in capture_coverage().items():
        if (manifest_coverage.get(key) != value
                or contract_coverage.get(key) != value):
            bad.append(f"label capture coverage {key}")
    if manifest_coverage != contract_coverage:
        bad.append("label top-level/state-contract coverage drift")
    diagnostic_inputs = contract.get("diagnostic_inputs", [])
    indices = [item.get("capture_shard_index") for item in diagnostic_inputs
               if isinstance(item, dict)]
    hashes = [item.get("sha256") for item in diagnostic_inputs
              if isinstance(item, dict)]
    if (len(diagnostic_inputs) != CAPTURE_SHARDS
            or not all(isinstance(index, int) for index in indices)
            or sorted(indices) != list(range(CAPTURE_SHARDS))):
        bad.append("label diagnostic shard population")
    if (len(hashes) != CAPTURE_SHARDS or len(set(hashes)) != CAPTURE_SHARDS
            or any(not is_sha256(value) for value in hashes)):
        bad.append("label diagnostic artifact hashes")
    parent_map = contract_coverage.get("capture_parent_sha256", {})
    diagnostic_map = contract_coverage.get("diagnostic_records_sha256", {})
    expected_keys = {str(index) for index in range(CAPTURE_SHARDS)}
    for name, values in (
        ("capture-parent", parent_map),
        ("diagnostic-record", diagnostic_map),
    ):
        if (not isinstance(values, dict) or set(values) != expected_keys
                or any(not is_sha256(value) for value in values.values())):
            bad.append(f"label {name} coverage map")
    for item in diagnostic_inputs:
        if not isinstance(item, dict):
            continue
        index = item.get("capture_shard_index")
        if parent_map.get(str(index)) != item.get("capture_parent_sha256"):
            bad.append("label capture-parent binding")
        if diagnostic_map.get(str(index)) != item.get(
                "diagnostic_records_sha256"):
            bad.append("label diagnostic-record binding")
    state_sha = contract.get("state_set_sha256")
    if (not is_sha256(state_sha)
            or manifest.get("state_input_sha256") != state_sha):
        bad.append("label exact state-set binding")
    partition = manifest.get("state_partition", {})
    records = manifest.get("records", [])
    record_ids = [record.get("state_id") for record in records]
    if (partition.get("schema") != "teacher-v1-state-partition-v1"
            or partition.get("shard_index") != manifest.get("shard_index")
            or partition.get("shard_count") != manifest.get("shard_count")
            or partition.get("state_ids") != record_ids
            or partition.get("state_ids_sha256") != stable_digest(record_ids)
            or partition.get("assignment")
            != "sorted_state_id_then_interleaved_position"):
        bad.append("label state partition identity")
    return sorted(set(bad))


def producer_receipt_problems(manifest: dict) -> list[str]:
    """Reopen the predeclared receipt and bind it to this label population."""
    binding = manifest.get("producer_receipt", {})
    path = binding.get("path") if isinstance(binding, dict) else None
    expected = binding.get("sha256") if isinstance(binding, dict) else None
    if not isinstance(path, str) or not is_sha256(expected):
        return ["producer receipt path/hash binding"]
    try:
        actual = sha256_file(path)
        with open(path) as fh:
            receipt = json.load(fh)
    except Exception as exc:
        return [f"producer receipt unreadable: {type(exc).__name__}: {exc}"]
    bad = []
    if actual != expected:
        bad.append("producer receipt exact byte hash")
    if (receipt.get("schema") != PRODUCER_RECEIPT_SCHEMA
            or receipt.get("complete") is not True
            or receipt.get("experiment_id") != EXPERIMENT):
        bad.append("producer receipt identity/completion")
    if (receipt.get("packet_id") != CAPTURE_PACKET_ID
            or receipt.get("capture_packet") != capture_packet()):
        bad.append("producer receipt capture packet")
    for key in ("run_id", "role", "nonce"):
        if receipt.get(key) != binding.get(key):
            bad.append(f"producer receipt {key} binding")
    roles = {
        "stage-a-primary": ("a", "cheap"),
        "stage-a-rerun": ("a", "cheap"),
        "stage-b-cheap": ("b", "cheap"),
        "stage-b-gold": ("b", "gold"),
    }
    expected_stage_mode = (manifest.get("stage"), manifest.get("mode"))
    if (roles.get(receipt.get("role")) != expected_stage_mode
            or (receipt.get("stage"), receipt.get("mode"))
            != expected_stage_mode):
        bad.append("producer receipt role/stage/mode")
    if ((receipt.get("state_set") or {}).get("sha256")
            != manifest.get("state_input_sha256")):
        bad.append("producer receipt exact state-set binding")
    for key in ("git", "python", "fast_engine", "require_voids"):
        if receipt.get(key) != manifest.get(key):
            bad.append(f"producer receipt/label {key} drift")
    if (receipt.get("tree_dirty") or receipt.get("promotable") is not True
            or receipt.get("source_digests") != manifest.get("source_digests")):
        bad.append("producer receipt/label executable provenance")
    return sorted(set(bad))


def stage_a_receipt_independence_problems(primary: dict,
                                          rerun: dict) -> list[str]:
    """Require two genuinely distinct predeclared Stage-A populations."""
    bad = []
    primary_run = primary.get("producer_run_id")
    rerun_run = rerun.get("producer_run_id")
    if primary_run == rerun_run:
        bad.append("primary/rerun producer run identity reused")
    primary_receipt = primary.get("producer_receipt", {})
    rerun_receipt = rerun.get("producer_receipt", {})
    if primary_receipt.get("role") != "stage-a-primary":
        bad.append("primary population lacks primary receipt role")
    if rerun_receipt.get("role") != "stage-a-rerun":
        bad.append("rerun population lacks rerun receipt role")
    if (primary_receipt.get("sha256") == rerun_receipt.get("sha256")
            or primary_receipt.get("nonce") == rerun_receipt.get("nonce")):
        bad.append("primary/rerun producer receipt reused")
    return bad


def load_shards(paths: list[str], *, schema: str, stage: str,
                mode: str, expected_states: list[dict] | None = None,
                expected_state_sha256: str | None = None,
                verify_receipts: bool = False,
                ) -> tuple[list[dict], list[dict], list[str]]:
    manifests, problems = [], []
    for path in paths:
        try:
            with open(path) as fh:
                manifest = json.load(fh)
        except Exception as exc:
            problems.append(f"{path}: unreadable: {type(exc).__name__}: {exc}")
            continue
        manifests.append(manifest)
        if manifest.get("schema") != schema:
            problems.append(f"{path}: schema")
        if manifest.get("experiment_id") != EXPERIMENT:
            problems.append(f"{path}: experiment")
        if manifest.get("stage") != stage or manifest.get("mode") != mode:
            problems.append(f"{path}: stage/mode")
        if not manifest.get("complete"):
            problems.append(f"{path}: incomplete")
        records = manifest.get("records", [])
        if manifest.get("n_records") != len(records):
            problems.append(f"{path}: record count")
        if manifest.get("records_digest") != records_digest(records):
            problems.append(f"{path}: records digest")
        problems += [f"{path}: {problem}"
                     for problem in label_packet_problems(manifest)]
        if verify_receipts:
            problems += [f"{path}: {problem}"
                         for problem in producer_receipt_problems(manifest)]
    if not manifests:
        return [], [], problems or ["no input shards"]

    first = manifests[0]
    shared = (
        "experiment_id", "stage", "mode", "git", "tree_dirty",
        "promotable", "fast_engine", "require_voids", "source_digests",
        "target_schema", "packet_id", "capture_packet", "capture_coverage",
        "state_input_sha256", "producer_run_id", "producer_receipt",
        "shard_count", "continuation", "counts", "state_contract",
    )
    shared += (("input_sha256",) if mode == "cheap" else ())
    for index, manifest in enumerate(manifests[1:], 1):
        for key in shared:
            if manifest.get(key) != first.get(key):
                problems.append(f"shard {index}: {key} drift")
    shard_count = first.get("shard_count")
    raw_indices = [manifest.get("shard_index") for manifest in manifests]
    indices = sorted(raw_indices) if all(
        isinstance(index, int) for index in raw_indices
    ) else raw_indices
    if len(manifests) != CAPTURE_SHARDS:
        problems.append(
            f"label shard count {len(manifests)}, required {CAPTURE_SHARDS}")
    if shard_count != CAPTURE_SHARDS:
        problems.append(f"registered shard count {shard_count}, required 8")
    elif indices != list(range(shard_count)):
        problems.append(f"shard indices {indices}, expected 0..{shard_count - 1}")
    expected_records = (
        STAGE_A_STATES if stage == "a" else STAGE_B_STATES
    ) // CAPTURE_SHARDS
    for index, manifest in enumerate(manifests):
        if len(manifest.get("records", [])) != expected_records:
            problems.append(
                f"shard {index}: records {len(manifest.get('records', []))}, "
                f"required {expected_records}"
            )
    if first.get("tree_dirty") or not first.get("promotable"):
        problems.append("tree was dirty or run was non-promotable")
    if not first.get("fast_engine") or not first.get("require_voids"):
        problems.append("compiled/strict runtime contract")
    if first.get("target_schema") != TARGET_SCHEMA:
        problems.append("teacher target schema drift")
    contract = first.get("state_contract", {})
    exclusion = contract.get("exam_exclusion") or {}
    if (contract.get("one_state_per_deal") is not True
            or not exclusion.get("verified") or exclusion.get("overlap") != 0
            or not exclusion.get("sources")):
        problems.append("fresh one-state/deal exam-exclusion contract")
    actor = contract.get("actor") or {}
    if actor.get("policy") != "mc-strong" or not actor.get("identity"):
        problems.append("actor identity")

    records = [record for manifest in manifests
               for record in manifest.get("records", [])]
    state_ids = [record.get("state_id") for record in records]
    if len(state_ids) != len(set(state_ids)):
        problems.append("duplicate state across shards")
    partition_source = expected_states if expected_states is not None else records
    if expected_state_sha256 is not None:
        if not is_sha256(expected_state_sha256):
            problems.append("expected state-set SHA-256 syntax")
        for index, manifest in enumerate(manifests):
            if manifest.get("state_input_sha256") != expected_state_sha256:
                problems.append(f"shard {index}: exact state-set SHA drift")
    if len({record.get("state_id") for record in partition_source}) != \
            len(partition_source):
        problems.append("expected state set has duplicate identities")
    else:
        for manifest in manifests:
            shard = manifest.get("shard_index")
            if not isinstance(shard, int) or not 0 <= shard < CAPTURE_SHARDS:
                continue
            try:
                expected_ids = [record["state_id"] for record in
                                canonical_state_partition(
                                    partition_source, shard, CAPTURE_SHARDS)]
            except ValueError as exc:
                problems.append(f"state partition source: {exc}")
                break
            actual_ids = [record.get("state_id")
                          for record in manifest.get("records", [])]
            if actual_ids != expected_ids:
                problems.append(
                    f"shard {shard}: records do not match registered state partition")
    return manifests, records, problems


def load_state_set(path: str, expected_sha256: str, stage: str
                   ) -> tuple[dict, list[str]]:
    """Open the exact state-set bytes the label shards claim to partition."""
    problems = []
    if not is_sha256(expected_sha256):
        return {}, ["state-set expected SHA-256 syntax"]
    try:
        actual = sha256_file(path)
        with open(path) as fh:
            payload = json.load(fh)
    except Exception as exc:
        return {}, [f"state set unreadable: {type(exc).__name__}: {exc}"]
    if actual != expected_sha256:
        problems.append("state-set exact byte hash mismatch")
    if (payload.get("schema") != "teacher-v1-state-set-v1"
            or payload.get("experiment_id") != EXPERIMENT
            or payload.get("stage") != stage
            or payload.get("complete") is not True):
        problems.append("state-set identity/stage/completion")
    states = payload.get("states", [])
    if payload.get("states_digest") != stable_digest(states):
        problems.append("state-set records digest")
    required = STAGE_A_STATES if stage == "a" else STAGE_B_STATES
    if len(states) != required:
        problems.append(f"state-set states {len(states)}, required {required}")
    ids = [state.get("state_id") for state in states]
    if (not all(isinstance(state_id, str) for state_id in ids)
            or len(ids) != len(set(ids))):
        problems.append("state-set state identities")
    return payload, problems


def _matrix_means(matrix: list[list[float]]) -> list[float]:
    return [sum(row[i] for row in matrix) / len(matrix)
            for i in range(len(matrix[0]))]


def _fold_stream_problems(record: dict, fold_name: str, fold: dict) -> list[str]:
    state = record["state"]
    expected = derive_stream(
        experiment_id=state["experiment_id"], deal_seed=state["seed"],
        state_id=state["state_id"], purpose="belief", fold=fold_name,
    )
    bad = []
    if fold.get("stream") != expected:
        bad.append(f"{fold_name} belief stream")
    expected_draw_ids = [stable_digest({"stream": expected, "index": i})
                         for i in range(fold.get("requested_worlds", 0))]
    if fold.get("draw_ids") != expected_draw_ids:
        bad.append(f"{fold_name} draw identity")
    return bad


def cheap_record_problems(record: dict, counts: dict[str, int]) -> list[str]:
    state_id = record.get("state_id", "?")
    bad = []
    try:
        state = record["state"]
        rnd = replay_state(state)
    except Exception as exc:
        return [f"{state_id}: replay {type(exc).__name__}: {exc}"]
    if record.get("replay_digest") != stable_digest(state):
        bad.append(f"{state_id}: replay digest")
    if record.get("deal_seed") != state["seed"] or state_id != state["state_id"]:
        bad.append(f"{state_id}: state identity")
    candidates = record.get("candidates", [])
    bad += [f"{state_id}: {p}" for p in ballot_problems(
        rnd, state["seat"], candidates
    )]
    bot = make_bot("mc-strong", seed=1)
    live = [list(action_key(action))
            for action in bot._candidates(rnd, state["seat"])]
    if candidates != live:
        bad.append(f"{state_id}: not the complete current ballot in order")
    if record.get("ballot_spec", {}).get("digest") != mc_ballot(bot).digest:
        bad.append(f"{state_id}: BallotSpec digest")
    if record.get("candidate_count") != len(candidates):
        bad.append(f"{state_id}: candidate count")

    folds = record.get("folds", {})
    summed = Counter({name: 0 for name in SAMPLER_COUNTERS})
    for fold_name in ("selection", "report"):
        fold = folds.get(fold_name, {})
        bad += [f"{state_id}/{fold_name}: {p}" for p in tensor_problems(
            fold, counts[fold_name], len(candidates)
        )]
        bad += [f"{state_id}: {p}"
                for p in _fold_stream_problems(record, fold_name, fold)]
        counters = fold.get("sampler_counters", {})
        bad += [f"{state_id}/{fold_name}: {p}" for p in counter_problems(
            counters, counts[fold_name]
        )]
        summed.update(counters)
        for seed_matrix in ("continuation_seeds", "evaluation_seeds"):
            matrix = fold.get(seed_matrix)
            if (not isinstance(matrix, list) or len(matrix) != counts[fold_name]
                    or any(not isinstance(row, list)
                           or len(row) != len(candidates) for row in matrix)):
                bad.append(f"{state_id}/{fold_name}: {seed_matrix} shape")
    if folds.get("selection", {}).get("stream", {}).get("seed") == \
            folds.get("report", {}).get("stream", {}).get("seed"):
        bad.append(f"{state_id}: selection/report stream collision")
    if set(folds.get("selection", {}).get("draw_ids", ())) & \
            set(folds.get("report", {}).get("draw_ids", ())):
        bad.append(f"{state_id}: selection/report draw identity overlap")
    if record.get("sampler_counters") != dict(summed):
        bad.append(f"{state_id}: sampler counter total")
    expected_work = len(candidates) * sum(counts.values())
    if record.get("candidate_world_work") != expected_work:
        bad.append(f"{state_id}: candidate-world work")

    selection = folds.get("selection", {}).get("tensor", {}).get(
        "signed_level_utility"
    )
    if selection and candidates:
        means = _matrix_means(selection)
        selected = max(range(len(candidates)), key=lambda i: (means[i], -i))
        if record.get("cheap_selected_index") != selected:
            bad.append(f"{state_id}: cheap action not frozen on selection")
        stored_means = record.get("cheap_selection_means", [])
        if len(stored_means) != len(means) or any(
            not math.isclose(a, b, rel_tol=0, abs_tol=1e-12)
            for a, b in zip(stored_means, means)
        ):
            bad.append(f"{state_id}: cheap selection mean drift")
        paired = record.get("paired_vs_candidate0", {})
        for fold_name in ("selection", "report"):
            matrix = folds[fold_name]["tensor"]["signed_level_utility"]
            expected = [paired_moments([row[i] - row[0] for row in matrix])
                        for i in range(len(candidates))]
            if paired.get(fold_name) != expected:
                bad.append(f"{state_id}/{fold_name}: paired moments")
    return bad


def stage_contract_problems(records: list[dict], stage: str) -> list[str]:
    bad = []
    required = STAGE_A_STATES if stage == "a" else STAGE_B_STATES
    name = stage.upper()
    if len(records) != required:
        bad.append(f"Stage {name} records {len(records)}, required {required}")
    deals = [record.get("deal_seed") for record in records]
    if len(deals) != len(set(deals)):
        bad.append(f"Stage {name} is not one-state-per-deal")
    representative_want = (STAGE_A_REPRESENTATIVE_PER_CELL
                           if stage == "a"
                           else STAGE_B_REPRESENTATIVE_PER_CELL)
    representative = Counter(
        (record.get("stratum", {}).get("phase"),
         record.get("stratum", {}).get("role"),
         record.get("stratum", {}).get("decision"))
        for record in records if record.get("kind") == "representative"
    )
    for cell in REPRESENTATIVE_CELLS:
        if representative[cell] != representative_want:
            bad.append(f"representative {cell}: {representative[cell]}")
    boundary_want = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                     else STAGE_B_BOUNDARY_STATES)
    uncertainty_want = (STAGE_A_OTHER_STATES // 2 if stage == "a"
                        else STAGE_B_UNCERTAINTY_STATES)
    boundary = sum(record.get("kind") == "boundary" for record in records)
    uncertainty = sum(record.get("kind") == "uncertainty" for record in records)
    if boundary != boundary_want:
        bad.append(f"boundary states {boundary}, required {boundary_want}")
    if uncertainty != uncertainty_want:
        bad.append(f"uncertainty states {uncertainty}, required {uncertainty_want}")
    return bad


def deterministic_rerun_problems(primary: list[dict], rerun: list[dict]) -> list[str]:
    by_primary = {record["state_id"]: stable_digest(deterministic_record(record))
                  for record in primary}
    by_rerun = {record["state_id"]: stable_digest(deterministic_record(record))
                for record in rerun}
    if by_primary != by_rerun:
        changed = sorted(set(by_primary) ^ set(by_rerun))
        changed += sorted(state for state in set(by_primary) & set(by_rerun)
                          if by_primary[state] != by_rerun[state])
        return [f"deterministic rerun mismatch in {len(set(changed))} states: "
                f"{changed[:5]}"]
    return []


def gold_record_problems(gold: dict, cheap: dict,
                         counts: dict[str, int]) -> list[str]:
    state_id = gold.get("state_id", "?")
    bad = []
    for key in ("state_id", "deal_seed", "split", "state", "replay_digest",
                "ballot_spec", "candidates", "candidate_count",
                "cheap_selected_index"):
        if gold.get(key) != cheap.get(key):
            bad.append(f"{state_id}: cheap/gold {key} drift")
    candidates = gold.get("candidates", [])
    folds = gold.get("folds", {})
    outer = Counter({name: 0 for name in SAMPLER_COUNTERS})
    inner = Counter({name: 0 for name in SAMPLER_COUNTERS})
    for fold_name in ("gold_selection", "gold_report"):
        fold = folds.get(fold_name, {})
        bad += [f"{state_id}/{fold_name}: {p}" for p in tensor_problems(
            fold, counts[fold_name], len(candidates)
        )]
        bad += [f"{state_id}: {p}"
                for p in _fold_stream_problems(gold, fold_name, fold)]
        counters = fold.get("sampler_counters", {})
        bad += [f"{state_id}/{fold_name}: {p}" for p in counter_problems(
            counters, counts[fold_name]
        )]
        outer.update(counters)
        fold_inner = fold.get("inner_sampler_counters", {})
        if set(fold_inner) != set(SAMPLER_COUNTERS):
            bad.append(f"{state_id}/{fold_name}: inner counter schema")
        else:
            if fold_inner["sample_attempts"] != (
                fold_inner["accepted_worlds"] + fold_inner["failed_worlds"]
            ):
                bad.append(f"{state_id}/{fold_name}: inner attempts")
            forbidden = {name: fold_inner[name] for name in (
                "failed_worlds", "rejected_worlds", "impossible_worlds",
                "short_search_decisions", "zero_world_decisions",
            ) if fold_inner[name]}
            if forbidden:
                bad.append(f"{state_id}/{fold_name}: inner failures {forbidden}")
            inner.update(fold_inner)
        for name in ("continuation_trace_digests", "continuation_decisions"):
            matrix = fold.get(name)
            if (not isinstance(matrix, list) or len(matrix) != counts[fold_name]
                    or any(not isinstance(row, list)
                           or len(row) != len(candidates) for row in matrix)):
                bad.append(f"{state_id}/{fold_name}: {name} shape")
        if fold.get("continuation_policy") != "mc-strong" \
                or fold.get("continuation_n") != 30:
            bad.append(f"{state_id}/{fold_name}: not production N=30 gold")
        for name in ("continuation_rollouts", "continuation_searches"):
            if not isinstance(fold.get(name), int) or fold[name] < 0:
                bad.append(f"{state_id}/{fold_name}: invalid {name}")
    if gold.get("outer_sampler_counters") != dict(outer):
        bad.append(f"{state_id}: outer counter total")
    if gold.get("inner_sampler_counters") != dict(inner):
        bad.append(f"{state_id}: inner counter total")
    expected_work = len(candidates) * sum(counts.values())
    if gold.get("candidate_world_work") != expected_work:
        bad.append(f"{state_id}: gold candidate-world work")
    rollout_values = [folds.get(name, {}).get("continuation_rollouts")
                      for name in ("gold_selection", "gold_report")]
    search_values = [folds.get(name, {}).get("continuation_searches")
                     for name in ("gold_selection", "gold_report")]
    continuation_rollouts = (sum(rollout_values)
                             if all(isinstance(v, int) for v in rollout_values)
                             else -1)
    continuation_searches = (sum(search_values)
                             if all(isinstance(v, int) for v in search_values)
                             else -1)
    if gold.get("continuation_rollouts") != continuation_rollouts:
        bad.append(f"{state_id}: continuation rollout total")
    if gold.get("continuation_searches") != continuation_searches:
        bad.append(f"{state_id}: continuation search total")
    if gold.get("total_rollout_work") != expected_work + continuation_rollouts:
        bad.append(f"{state_id}: total rollout work")

    selection = folds.get("gold_selection", {}).get("tensor", {}).get(
        "signed_level_utility"
    )
    report = folds.get("gold_report", {}).get("tensor", {}).get(
        "signed_level_utility"
    )
    if selection and report and candidates:
        means = _matrix_means(selection)
        gold_i = max(range(len(candidates)), key=lambda i: (means[i], -i))
        if gold.get("gold_reference_index") != gold_i:
            bad.append(f"{state_id}: gold action not frozen on gold-selection")
        cheap_i = cheap.get("cheap_selected_index")
        diffs = [row[gold_i] - row[cheap_i] for row in report]
        regret = sum(diffs) / len(diffs)
        if not math.isclose(gold.get("gold_report_regret", float("nan")), regret,
                            rel_tol=0, abs_tol=1e-12):
            bad.append(f"{state_id}: gold-report regret drift")
        if gold.get("gold_report_regret_moments") != paired_moments(diffs):
            bad.append(f"{state_id}: gold-report moments")
    return bad


def write_gate(path: str, payload: dict) -> None:
    partial = path + ".partial"
    if os.path.exists(path) or os.path.exists(partial):
        raise TeacherProtocolError(f"refusing to overwrite {path}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(partial, "x") as fh:
            json.dump(payload, fh, sort_keys=True, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(partial, path)
    except Exception:
        if os.path.exists(partial):
            os.remove(partial)
        raise


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="stage", required=True)
    a = sub.add_parser("stage-a")
    a.add_argument("--input", action="append", required=True)
    a.add_argument("--rerun", action="append", required=True)
    a.add_argument("--state-set", required=True)
    a.add_argument("--expected-state-set-sha256", required=True)
    a.add_argument("--out", required=True)
    b = sub.add_parser("stage-b")
    b.add_argument("--cheap", action="append", required=True)
    b.add_argument("--gold", action="append", required=True)
    b.add_argument("--state-set", required=True)
    b.add_argument("--expected-state-set-sha256", required=True)
    b.add_argument("--out", required=True)
    return ap


def main() -> None:
    args = parser().parse_args()
    problems: list[str] = []
    runtime = gate_runtime()
    state_stage = "a" if args.stage == "stage-a" else "b"
    state_set, state_bad = load_state_set(
        args.state_set, args.expected_state_set_sha256, state_stage)
    problems += state_bad
    expected_states = state_set.get("states", [])
    if args.stage == "stage-a":
        manifests, records, bad = load_shards(
            args.input, schema=CHEAP_SHARD_SCHEMA, stage="a", mode="cheap",
            expected_states=expected_states,
            expected_state_sha256=args.expected_state_set_sha256,
            verify_receipts=True,
        )
        rerun_manifests, rerun, rerun_bad = load_shards(
            args.rerun, schema=CHEAP_SHARD_SCHEMA, stage="a", mode="cheap",
            expected_states=expected_states,
            expected_state_sha256=args.expected_state_set_sha256,
            verify_receipts=True,
        )
        problems += bad + [f"rerun: {p}" for p in rerun_bad]
        if manifests:
            problems += gate_input_runtime_problems(manifests[0], runtime)
        if rerun_manifests:
            problems += [f"rerun: {problem}" for problem in
                         gate_input_runtime_problems(
                             rerun_manifests[0], runtime)]
        for record in records:
            problems += cheap_record_problems(record, CHEAP_FOLDS)
        for record in rerun:
            problems += [f"rerun: {p}"
                         for p in cheap_record_problems(record, CHEAP_FOLDS)]
        problems += stage_contract_problems(records, "a")
        problems += [f"rerun: {p}" for p in stage_contract_problems(rerun, "a")]
        problems += deterministic_rerun_problems(records, rerun)
        if manifests and rerun_manifests:
            for key in (
                "input_sha256", "state_input_sha256", "git",
                "source_digests", "counts", "packet_id", "capture_packet",
                "capture_coverage", "state_contract",
            ):
                if manifests[0].get(key) != rerun_manifests[0].get(key):
                    problems.append(f"primary/rerun {key} drift")
            problems += stage_a_receipt_independence_problems(
                manifests[0], rerun_manifests[0])
        primary_inputs = [
            {"path": path, "sha256": sha256_file(path),
             "shard_index": manifest.get("shard_index")}
            for path, manifest in zip(args.input, manifests)
        ]
        rerun_inputs = [
            {"path": path, "sha256": sha256_file(path),
             "shard_index": manifest.get("shard_index")}
            for path, manifest in zip(args.rerun, rerun_manifests)
        ]
        if ({item["sha256"] for item in primary_inputs}
                & {item["sha256"] for item in rerun_inputs}):
            problems.append("primary/rerun artifact identity overlap")
        elapsed = sum(m.get("measured_record_seconds", 0) for m in manifests)
        work = sum(m.get("candidate_world_work", 0) for m in manifests)
        projection = elapsed / len(records) * 2048 if records else None
        result = {
            "schema": GATE_SCHEMA, "experiment_id": EXPERIMENT,
            **runtime,
            "complete": True,
            "stage": "A", "verdict": "PASS" if not problems else "FAIL",
            "stage_b_authorized": not problems,
            "stage_c_authorized": False,
            "problems": problems,
            "n_states": len(records), "candidate_world_work": work,
            "packet_id": (
                manifests[0].get("packet_id") if manifests else None),
            "capture_packet": (
                manifests[0].get("capture_packet") if manifests else None),
            "capture_coverage": (
                manifests[0].get("capture_coverage") if manifests else None),
            "state_input_sha256": (
                manifests[0].get("state_input_sha256") if manifests else None),
            "state_set": {"path": args.state_set,
                          "sha256": args.expected_state_set_sha256},
            "primary_producer_run_id": (
                manifests[0].get("producer_run_id") if manifests else None),
            "rerun_producer_run_id": (
                rerun_manifests[0].get("producer_run_id")
                if rerun_manifests else None),
            "primary_producer_receipt": (
                manifests[0].get("producer_receipt") if manifests else None),
            "rerun_producer_receipt": (
                rerun_manifests[0].get("producer_receipt")
                if rerun_manifests else None),
            "measured_seconds": elapsed,
            "projected_2048_seconds": projection,
            "inputs": primary_inputs,
            "reruns": rerun_inputs,
        }
    else:
        cheap_manifests, cheap, cheap_bad = load_shards(
            args.cheap, schema=CHEAP_SHARD_SCHEMA, stage="b", mode="cheap",
            expected_states=expected_states,
            expected_state_sha256=args.expected_state_set_sha256,
            verify_receipts=True,
        )
        gold_manifests, gold, gold_bad = load_shards(
            args.gold, schema=GOLD_SHARD_SCHEMA, stage="b", mode="gold",
            expected_states=expected_states,
            expected_state_sha256=args.expected_state_set_sha256,
            verify_receipts=True,
        )
        problems += cheap_bad + [f"gold: {p}" for p in gold_bad]
        if cheap_manifests:
            problems += gate_input_runtime_problems(
                cheap_manifests[0], runtime)
        if gold_manifests:
            problems += [f"gold: {problem}" for problem in
                         gate_input_runtime_problems(
                             gold_manifests[0], runtime)]
        for record in cheap:
            problems += cheap_record_problems(record, CHEAP_FOLDS)
        cheap_by = {record.get("state_id"): record for record in cheap}
        if len(cheap) != STAGE_B_STATES:
            problems.append(f"Stage B cheap states {len(cheap)}, required {STAGE_B_STATES}")
        if len(gold) != STAGE_B_STATES:
            problems.append(f"Stage B gold states {len(gold)}, required {STAGE_B_STATES}")
        problems += stage_contract_problems(cheap, "b")
        for record in gold:
            match = cheap_by.get(record.get("state_id"))
            if match is None:
                problems.append(f"{record.get('state_id')}: no cheap record")
            else:
                problems += gold_record_problems(record, match, GOLD_FOLDS)
        if set(cheap_by) != {record.get("state_id") for record in gold}:
            problems.append("cheap/gold state-set mismatch")
        if cheap_manifests and gold_manifests:
            for key in (
                "git", "source_digests", "state_contract",
                "state_input_sha256", "target_schema", "packet_id",
                "capture_packet", "capture_coverage",
            ):
                # The same labeller file defines both modes, so executable
                # identities must match exactly. Input digests differ by design.
                if cheap_manifests[0].get(key) != gold_manifests[0].get(key):
                    problems.append(f"cheap/gold {key} drift")
            cheap_parent_by_shard = {
                manifest.get("shard_index"): sha256_file(path)
                for path, manifest in zip(args.cheap, cheap_manifests)
            }
            for path, manifest in zip(args.gold, gold_manifests):
                index = manifest.get("shard_index")
                if manifest.get("input_sha256") != cheap_parent_by_shard.get(index):
                    problems.append(
                        f"gold shard {index} is not bound to its exact cheap parent")
        regret = stage_b_regret(gold)
        problems += regret["problems"]
        passed = not problems and regret["passed"]
        verdict = "PASS" if passed else (
            "INCONCLUSIVE" if problems or regret["inconclusive"] else "FAIL"
        )
        result = {
            "schema": GATE_SCHEMA, "experiment_id": EXPERIMENT,
            **runtime,
            "complete": True,
            "stage": "B", "verdict": verdict,
            "stage_c_authorized": passed,
            "problems": problems, "regret": regret,
            "n_states": len(gold),
            "packet_id": (
                cheap_manifests[0].get("packet_id")
                if cheap_manifests else None),
            "capture_packet": (
                cheap_manifests[0].get("capture_packet")
                if cheap_manifests else None),
            "capture_coverage": (
                cheap_manifests[0].get("capture_coverage")
                if cheap_manifests else None),
            "state_input_sha256": (
                cheap_manifests[0].get("state_input_sha256")
                if cheap_manifests else None),
            "state_set": {"path": args.state_set,
                          "sha256": args.expected_state_set_sha256},
            "cheap_inputs": [
                {"path": path, "sha256": sha256_file(path),
                 "shard_index": manifest.get("shard_index")}
                for path, manifest in zip(args.cheap, cheap_manifests)
            ],
            "gold_inputs": [
                {"path": path, "sha256": sha256_file(path),
                 "shard_index": manifest.get("shard_index")}
                for path, manifest in zip(args.gold, gold_manifests)
            ],
        }
    try:
        write_gate(args.out, result)
    except (OSError, TeacherProtocolError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3)
    print(json.dumps(result, indent=2), flush=True)
    raise SystemExit(0 if result["verdict"] == "PASS" else 4)


if __name__ == "__main__":
    main()
