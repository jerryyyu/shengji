from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1 import evaluate_label_ceiling
from shengji.rl.world_afterstate_v1_capacity import (
    ARTIFACT_PATHS, AUTHORITY, CapacityBuildV1,
    WorldAfterstateV1CapacityError, reopen_capacity_build,
    validate_capacity_receipt)
from shengji.rl.world_afterstate_v1_controls import (
    action_association_permutation, identical_successor_control,
    label_permutation)
from shengji.rl.world_afterstate_v1_dataset import (
    build_advantage_manifest, join_advantage_examples)
from shengji.rl.world_afterstate_v1_schedule import build_subsplit_manifest

import shengji.rl.world_afterstate_v1_capacity as capacity
from shengji.rl.world_afterstate_v1_rehearsal import (
    TRAIN_STATE_COUNT, _row, _training_population)
from test_world_afterstate_v1_dataset import _row as _dataset_row


def _build():
    train, bindings = _training_population()
    p0 = evaluate_label_ceiling(
        tuple(value.pair for value in train),
        bootstrap_replicates=capacity.BOOTSTRAP_REPLICATES)
    assert p0["passed"] is True
    manifest = build_advantage_manifest(
        train,
        v0_dataset_manifest_sha256=
            capacity.V0_DATASET_MANIFEST_SHA256)
    subsplit = build_subsplit_manifest(
        bindings,
        v0_population_manifest_sha256=
            capacity.V0_POPULATION_MANIFEST_SHA256)
    _identical, identical_evidence = identical_successor_control(train)
    _association, association_evidence = \
        action_association_permutation(train)
    _labels, label_evidence = label_permutation(train)
    evidence = {
        "identical-successor": identical_evidence,
        "action-association-permutation": association_evidence,
        "label-permutation": label_evidence,
    }
    files = {
        "p0/label-ceiling.json": canonical_json_bytes(p0),
        "p1/advantage-manifest.json": canonical_json_bytes(manifest),
        "p1/subsplit.json": canonical_json_bytes(subsplit),
    }
    for path in capacity.CONTROL_ARTIFACT_PATHS:
        files[path] = canonical_json_bytes(evidence[path.split("/")[-1][:-5]])
    runtime = {
        "host": "capacity-host", "platform": "Linux-test",
        "machine": "x86_64", "python": "3.test", "torch": "2.test",
        "numpy": "2.test", "cpu_count": 16,
        "torch_threads_at_entry": 16, "torch_interop_threads": 16,
        "torch_deterministic_algorithms": True,
        "environment": dict(capacity.REQUIRED_ENVIRONMENT),
        "python_executable": "/runtime/python",
        "python_executable_sha256": "1" * 64,
        "fast_router_path": "/runtime/fast.py",
        "fast_router_sha256": "2" * 64,
        "native_path": "/runtime/_fast.so", "native_sha256": "3" * 64,
        "compiled_engine_active": True, "safe_path": True,
        "dont_write_bytecode": True, "pythonpath_absent": True,
    }
    row_measurements = []
    schedule_index = 0
    for repetition in range(capacity.ROW_REPETITIONS):
        order = (capacity.ROW_WORKER_COUNTS if repetition % 2 == 0
                 else tuple(reversed(capacity.ROW_WORKER_COUNTS)))
        for workers in order:
            wall = (20 - workers) * 100_000_000
            cpu = wall * workers // 2
            row_measurements.append({
                "schedule_index": schedule_index,
                "repetition": repetition, "workers": workers,
                "row_count": 180,
                "rows_per_second_ppm": 180 * 10**15 // wall,
                "output_population_sha256": "4" * 64,
                "wall_nanoseconds": wall,
                "cpu_nanoseconds": cpu,
                "average_cores_milli": workers * 500,
                "host_cpu_utilization_ppm": workers * 31_250,
                "memory_current_bytes_at_finish": 10_000,
                "memory_peak_bytes_at_finish": 20_000,
            })
            schedule_index += 1
    cohort_measurements = []
    for index, workers in enumerate(capacity.MEMBER_WORKER_COUNTS):
        wall = 5_000_000_000 if workers == 4 else 10_000_000_000
        cohort_measurements.append({
            "schedule_index": index, "member_workers": workers,
            "torch_threads": 16 // workers, "member_count": 8,
            "pair_count": len(train),
            "member_pairs_per_second_ppm": (
                len(train) * 8 * 10**15 // wall),
            "output_population_sha256": f"{5 + index}" * 64,
            "wall_nanoseconds": wall,
            "cpu_nanoseconds": wall * 8,
            "average_cores_milli": 8_000,
            "host_cpu_utilization_ppm": 500_000,
            "memory_current_bytes_at_finish": 10_000,
            "memory_peak_bytes_at_finish": 20_000,
        })
    body = {
        "schema": capacity.CAPACITY_SCHEMA, "source_git": "a" * 40,
        "source_tree_clean": True, "runtime": runtime,
        "source_bindings": [{
            "relative_path": path, "byte_count": 1, "sha256": "9" * 64,
        } for path in capacity.SOURCE_PATHS],
        "review": {
            "review_commit": "b" * 40,
            "canonical_remote_tip_at_admission": "c" * 40,
            "review_marker_sha256": "d" * 64,
            "review_claim_sha256": capacity._sha(
                capacity.expected_review_claim("a" * 40)),
        },
        "v0_inputs": {
            "population_external_sha256":
                capacity.V0_POPULATION_EXTERNAL_SHA256,
            "population_manifest_sha256":
                capacity.V0_POPULATION_MANIFEST_SHA256,
            "dataset_external_sha256": capacity.V0_DATASET_EXTERNAL_SHA256,
            "dataset_manifest_sha256":
                capacity.V0_DATASET_MANIFEST_SHA256,
            "freeze_external_sha256": capacity.V0_FREEZE_EXTERNAL_SHA256,
            "freeze_sha256": capacity.V0_FREEZE_SHA256,
            "capacity_external_sha256":
                capacity.V0_CAPACITY_EXTERNAL_SHA256,
        },
        "schedule": {
            "row_worker_counts": list(capacity.ROW_WORKER_COUNTS),
            "row_repetitions": capacity.ROW_REPETITIONS,
            "member_worker_counts": list(capacity.MEMBER_WORKER_COUNTS),
            "pair_cap": capacity.PAIR_CAP,
            "shape_name": capacity.SHAPE_NAME,
            "bootstrap_replicates": capacity.BOOTSTRAP_REPLICATES,
            "capacity_config": capacity._training_config().payload(),
            "initialization_seeds": list(capacity._initialization_seeds()),
            "schedule_seed": capacity._schedule_seed(),
            "wall_cap_nanoseconds": capacity.MAX_CAPACITY_WALL_NANOSECONDS,
        },
        "train_population": {
            "train_row_count": 180,
            "eligible_state_count": manifest["state_count"],
            "pair_count": manifest["pair_count"],
            "fit_state_count": subsplit["fit_state_count"],
            "select_state_count": subsplit["select_state_count"],
            "train_row_population_sha256": "4" * 64,
            "advantage_manifest_sha256": manifest["manifest_sha256"],
            "subsplit_manifest_sha256": subsplit["manifest_sha256"],
            "label_ceiling_result_sha256": p0["result_sha256"],
            "label_ceiling_passed": True,
            "calibration_row_bytes_opened": False,
            "report_row_bytes_opened": False,
            "provider_audit_row_bytes_opened": False,
        },
        "row_reopen_measurements": row_measurements,
        "cohort_measurements": cohort_measurements,
        "selection": {
            "row_workers": 16, "member_workers": 4, "torch_threads": 4,
            "selection_uses_outcomes_or_model_quality": False,
        },
        "terminal_route": "PASS_TO_P1_CAPACITY",
        "aggregate_resources": {
            "method": "linux-cgroup-v2", "path": "/sys/fs/cgroup/test",
            "started_memory_current_bytes": 1_000,
            "started_memory_peak_bytes": 2_000,
            "finished_memory_current_bytes": 10_000,
            "finished_memory_peak_bytes": 20_000,
            "started_cpu_usage_nanoseconds": 1_000,
            "finished_cpu_usage_nanoseconds": 10_000,
            "wall_nanoseconds": 20_000,
            "memory_limit_bytes": capacity.CAPACITY_MEMORY_LIMIT_BYTES,
            "within_wall_and_memory_caps": True,
        },
        "artifacts": capacity._artifact_rows(files),
        "authority": dict(AUTHORITY),
    }
    receipt = {**body, "receipt_sha256": capacity._sha(body)}
    return CapacityBuildV1(
        receipt=receipt,
        files=tuple((path, files[path]) for path in ARTIFACT_PATHS))


def test_capacity_build_reopens_exact_artifacts_and_selects_throughput_only():
    build = _build()
    assert reopen_capacity_build(build) == build
    assert build.receipt["selection"] == {
        "row_workers": 16, "member_workers": 4, "torch_threads": 4,
        "selection_uses_outcomes_or_model_quality": False,
    }
    assert build.receipt["authority"] == AUTHORITY


def test_capacity_artifact_and_selection_cross_bindings_have_teeth():
    build = _build()
    altered = bytearray(build.files[0][1])
    altered[-2] ^= 1
    forged_build = copy.copy(build)
    object.__setattr__(forged_build, "files", (
        (build.files[0][0], bytes(altered)), *build.files[1:]))
    with pytest.raises(WorldAfterstateV1CapacityError,
                       match="file binding drift"):
        reopen_capacity_build(forged_build)

    forged = copy.deepcopy(build.receipt)
    forged["selection"]["member_workers"] = 8
    body = {key: item for key, item in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = capacity._sha(body)
    with pytest.raises(WorldAfterstateV1CapacityError,
                       match="throughput-only selection drift"):
        validate_capacity_receipt(forged)

    forged = copy.deepcopy(build.receipt)
    forged["review"]["review_claim_sha256"] = "0" * 64
    body = {key: item for key, item in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = capacity._sha(body)
    with pytest.raises(WorldAfterstateV1CapacityError,
                       match="review claim binding drift"):
        validate_capacity_receipt(forged)


def test_capacity_review_marker_is_external_append_only_and_exact(monkeypatch):
    source = "a" * 40
    review = "b" * 40
    parent = "c" * 40
    remote = "d" * 40
    previous = b"# ledger\n"
    marker = capacity.REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(capacity.expected_review_claim(source))
    current = previous + marker
    monkeypatch.setattr(capacity, "_canonical_remote_tip", lambda _repo: remote)

    def fake_git(_repo, *arguments, binary=False):
        if arguments == ("rev-parse", "origin/main"):
            return remote
        if arguments == ("show", "-s", "--format=%P", review):
            return parent
        if arguments[:3] == ("show", "-s", "--format=%an"):
            return capacity.REVIEWER_NAME
        if arguments[:3] == ("show", "-s", "--format=%ae"):
            return capacity.REVIEWER_EMAIL
        if arguments[:3] == ("show", "-s", "--format=%cn"):
            return capacity.REVIEWER_NAME
        if arguments[:3] == ("show", "-s", "--format=%ce"):
            return capacity.REVIEWER_EMAIL
        if arguments == ("show", "-s", "--format=%B", review):
            return capacity.REVIEWER_SESSION_TRAILER + "fixture"
        if arguments[:5] == (
                "diff-tree", "--no-commit-id", "--name-only", "-r", review):
            return capacity.REVIEW_LEDGER
        if arguments == ("show", f"{review}:{capacity.REVIEW_LEDGER}"):
            return current
        if arguments == ("show", f"{parent}:{capacity.REVIEW_LEDGER}"):
            return previous
        raise AssertionError(arguments)

    monkeypatch.setattr(capacity, "_git", fake_git)
    monkeypatch.setattr(
        capacity.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0))
    result = capacity.authenticate_review_commit(
        Path.cwd(), expected_git=source, review_commit=review)
    assert result["review_commit"] == review
    assert result["review_marker_sha256"] == capacity._sha_bytes(marker)

    current = previous
    with pytest.raises(WorldAfterstateV1CapacityError,
                       match="marker introduction drift"):
        capacity.authenticate_review_commit(
            Path.cwd(), expected_git=source, review_commit=review)


def test_capacity_receipt_refuses_any_held_out_opening_claim():
    forged = copy.deepcopy(_build().receipt)
    forged["train_population"]["calibration_row_bytes_opened"] = True
    body = {key: item for key, item in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = capacity._sha(body)
    with pytest.raises(WorldAfterstateV1CapacityError,
                       match="train population drift"):
        validate_capacity_receipt(forged)


def test_capacity_run_wires_train_only_reader_through_every_measurement(
        monkeypatch, tmp_path):
    template = _build().receipt
    monkeypatch.setattr(
        capacity, "_source_bindings",
        lambda _repo, _git: copy.deepcopy(template["source_bindings"]))
    monkeypatch.setattr(
        capacity, "authenticate_review_commit",
        lambda _repo, *, expected_git, review_commit:
            copy.deepcopy(template["review"]))
    monkeypatch.setattr(
        capacity, "_runtime", lambda: copy.deepcopy(template["runtime"]))
    monkeypatch.setattr(capacity, "_sealed_read", lambda _path, _label: b"{}\n")
    snapshot_index = 0

    def snapshot():
        nonlocal snapshot_index
        snapshot_index += 1
        return {
            "method": "linux-cgroup-v2", "path": "/sys/fs/cgroup/test",
            "memory_current_bytes": 10_000,
            "memory_peak_bytes": 20_000,
            "cpu_usage_nanoseconds": snapshot_index * 1_000_000,
        }

    monkeypatch.setattr(capacity, "_cgroup_snapshot", snapshot)
    reopened = []
    for state_index in range(TRAIN_STATE_COUNT):
        for candidate in range(3):
            for replicate in range(2):
                row = _row(
                    fold="train", state_index=state_index,
                    candidate_index=candidate, replicate=replicate)
                outcome = row.evaluation_outcome
                reopened.append(({
                    "state_group_id": outcome.state_group_id,
                    "candidate_index": candidate, "replicate": replicate,
                }, row))
    singleton_rows = []
    for replicate in range(2):
        row = _row(
            fold="train", state_index=TRAIN_STATE_COUNT,
            candidate_index=0, replicate=replicate)
        outcome = row.evaluation_outcome
        singleton_rows.append(({
            "state_group_id": outcome.state_group_id,
            "candidate_index": 0, "replicate": replicate,
        }, row))
    reopened.extend(singleton_rows)
    candidate_counts = {}
    for _binding, row in reopened:
        outcome = row.evaluation_outcome
        candidate_counts[outcome.state_group_id] = max(
            candidate_counts.get(outcome.state_group_id, 0),
            outcome.candidate_index + 1)
    population_manifest = {"groups": [
        {
            "state_group_id": state_group_id, "fold": "train",
            "candidate_count": candidate_count,
        }
        for state_group_id, candidate_count in sorted(candidate_counts.items())
    ]}
    monkeypatch.setattr(
        capacity, "_validate_v0_inputs",
        lambda _population, _dataset, _freeze:
            (population_manifest, {}, {}))
    calls = []

    def reopen(_manifest, *, population_manifest, row_root,
               allowed_folds, reconstruct_continuations,
               reconstruction_workers, deadline_monotonic_ns, progress):
        assert allowed_folds == ("train",)
        assert reconstruct_continuations is False
        calls.append(reconstruction_workers)
        progress(len(reopened), len(reopened))
        return tuple(reopened)

    monkeypatch.setattr(capacity, "reopen_dataset_manifest", reopen)

    remaining_budgets = iter((401, 307, 211, 103))
    monkeypatch.setattr(
        capacity, "_remaining_capacity_wall",
        lambda _started_wall: next(remaining_budgets))
    received_budgets = []

    def train(**kwargs):
        received_budgets.append(kwargs["wall_budget_nanoseconds"])
        return SimpleNamespace(manifest={
            "members": [{"selected_model_state_sha256": f"{index:x}" * 64}
                        for index in range(8)]})

    monkeypatch.setattr(capacity, "train_named_cohort", train)
    result = capacity.run_capacity(
        repo=Path.cwd().parent.resolve(), expected_git="a" * 40,
        population_path=tmp_path / "population.json",
        dataset_manifest_path=tmp_path / "dataset.json",
        freeze_path=tmp_path / "freeze.json", row_root=tmp_path,
        review_commit="b" * 40)
    assert result.receipt["terminal_route"] == "PASS_TO_P1_CAPACITY"
    assert result.receipt["train_population"]["train_row_count"] \
        == len(reopened)
    assert result.receipt["train_population"]["eligible_state_count"] \
        == TRAIN_STATE_COUNT
    assert calls == [
        *capacity.ROW_WORKER_COUNTS,
        *reversed(capacity.ROW_WORKER_COUNTS),
        result.receipt["selection"]["row_workers"],
    ]
    assert received_budgets == [401, 307, 211, 103]
    assert result.receipt["train_population"][
        "calibration_row_bytes_opened"] is False


def test_capacity_composed_deadline_refuses_before_cohort_training(
        monkeypatch):
    started = 17
    monkeypatch.setattr(
        capacity.time, "monotonic_ns",
        lambda: started + capacity.MAX_CAPACITY_WALL_NANOSECONDS)
    with pytest.raises(
            WorldAfterstateV1CapacityError,
            match="^capacity wall deadline expired before cohort training$"):
        capacity._remaining_capacity_wall(started)


def test_failed_p0_still_reopens_as_a_complete_stop_packet():
    natural = tuple(join_advantage_examples([
        _dataset_row(
            f"zero-{state}", candidate, replicate, 100 + replicate)
        for state in range(30)
        for candidate in range(3)
        for replicate in range(2)
    ]))
    p0 = evaluate_label_ceiling(
        tuple(value.pair for value in natural),
        bootstrap_replicates=capacity.BOOTSTRAP_REPLICATES)
    assert p0["passed"] is False
    manifest = build_advantage_manifest(
        natural,
        v0_dataset_manifest_sha256=
            capacity.V0_DATASET_MANIFEST_SHA256)
    bindings = [{
        "deal_group_sha256": value.pair.deal_group_sha256,
        "state_group_id": value.pair.state_group_id, "fold": "train",
    } for value in natural[::4]]
    assert len(bindings) == 30
    subsplit = build_subsplit_manifest(
        bindings,
        v0_population_manifest_sha256=
            capacity.V0_POPULATION_MANIFEST_SHA256)
    files = {
        "p0/label-ceiling.json": canonical_json_bytes(p0),
        "p1/advantage-manifest.json": canonical_json_bytes(manifest),
        "p1/subsplit.json": canonical_json_bytes(subsplit),
    }
    receipt = copy.deepcopy(_build().receipt)
    population = receipt["train_population"]
    population.update({
        "eligible_state_count": manifest["state_count"],
        "pair_count": manifest["pair_count"],
        "fit_state_count": subsplit["fit_state_count"],
        "select_state_count": subsplit["select_state_count"],
        "advantage_manifest_sha256": manifest["manifest_sha256"],
        "subsplit_manifest_sha256": subsplit["manifest_sha256"],
        "label_ceiling_result_sha256": p0["result_sha256"],
        "label_ceiling_passed": False,
    })
    receipt["cohort_measurements"] = []
    receipt["selection"].update({
        "member_workers": None, "torch_threads": None})
    receipt["terminal_route"] = "STOP_NO_REPRODUCIBLE_ACTION_LABEL"
    receipt["artifacts"] = capacity._artifact_rows(files)
    body = {key: item for key, item in receipt.items()
            if key != "receipt_sha256"}
    receipt["receipt_sha256"] = capacity._sha(body)
    build = CapacityBuildV1(
        receipt=receipt,
        files=tuple((path, files[path])
                    for path in capacity.BASE_ARTIFACT_PATHS))
    assert reopen_capacity_build(build) == build
