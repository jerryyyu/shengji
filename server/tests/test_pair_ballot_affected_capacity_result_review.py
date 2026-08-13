"""Adversarial tests for the read-only Pair V3 capacity result reviewer."""

from __future__ import annotations

import copy
import importlib.util
import json
import py_compile
import subprocess
import sys
import types
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
# The production reviewer must start in a fresh process.  Recreate that exact
# boundary even when pytest collected another Pair module first.
sys.dont_write_bytecode = True
for _dependency_name in (
        "pair_ballot_affected_aggregate",
        "pair_ballot_affected_capacity_design",
        "pair_ballot_affected_capacity_preflight",
        "pair_ballot_affected_eval",
        "pair_ballot_affected_states"):
    sys.modules.pop(_dependency_name, None)
import pair_ballot_affected_capacity_result_review as R  # noqa: E402


def _runtime() -> dict:
    return {
        "host": "ubuntu-32gb-hel1-2",
        "machine": "x86_64",
        "python": "3.14.4",
        "python_executable": "/usr/bin/python3.14",
        "cpu_count": 16,
        "memory_bytes": 32 * (1 << 30),
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": "f" * 64,
    }


def _design() -> dict:
    lane = {"states_by_band": {"early": 56, "mid": 6, "late": 2}}
    return {
        "selection": {
            "states": 1_024,
            "states_by_band": {"early": 896, "mid": 96, "late": 32},
        },
        "schedule": {"lanes": [copy.deepcopy(lane) for _ in range(16)]},
    }


def _packet() -> dict:
    return {
        "git": R.EXPECTED_GIT,
        "internal_sha256": R.EXPECTED_PACKET_INTERNAL_SHA256,
        "runtime": _runtime(),
    }


def _review() -> tuple[dict, bytes]:
    claim = R.CAPACITY.packet_review_claim(
        expected_git=R.EXPECTED_GIT,
        packet_sha256=R.EXPECTED_PACKET_SHA256,
        packet_internal_sha256=R.EXPECTED_PACKET_INTERNAL_SHA256)
    marker = R.CAPACITY._canonical_marker(
        R.CAPACITY.PACKET_REVIEW_PREFIX, claim)
    return ({
        "commit": R.PACKET_REVIEW_GIT,
        "marker_sha256": R.CAPACITY.sha256_file_from_bytes(marker),
        "claim": claim,
    }, marker)


def _admission(review: dict) -> dict:
    value = {
        "schema": R.CAPACITY.ADMISSION_SCHEMA,
        "run_id": R.CAPACITY.RUN_ID,
        "git": R.EXPECTED_GIT,
        "packet_sha256": R.EXPECTED_PACKET_SHA256,
        "packet_review_commit": R.PACKET_REVIEW_GIT,
        "packet_review_marker_sha256": review["marker_sha256"],
        "nonce": "a" * 64,
        "created_time_ns": 1_786_590_000_000_000_000,
        "systemd_invocation_id": "b" * 32,
        "one_score_free_preflight_authorized": True,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = R.CAPACITY.digest(value)
    return value


def _result(*, admission_sha256: str) -> dict:
    bands = [band for _split, band in R.CAPACITY.PREFLIGHT_CELLS]
    bands.extend(["early"] * 10)
    work_per_state = (
        2 * R.CAPACITY.DESIGN.POLICY_WORK_PER_STATE
        + R.CAPACITY.EVAL.REPORT_WORLDS)
    normalized = R.CAPACITY.DESIGN.MAX_WORK_PER_STATE / work_per_state
    timings = [{
        "split": ("dev" if lane % 2 == 0 else "calib"),
        "band": band,
        "lane_index": lane,
        "elapsed_seconds": 1.0,
        "observed_candidate_world_rollouts": work_per_state,
        "normalized_max_work_seconds": normalized,
    } for lane, band in enumerate(bands)]
    seconds = {band: normalized for band in R.CAPACITY.DESIGN.BANDS}
    lane_hours = [
        normalized * 64 * R.CAPACITY.THROUGHPUT_SAFETY_FACTOR / 3_600
        for _lane in range(R.CAPACITY.DESIGN.SHARD_COUNT)]
    projection = {
        "fleet_hours": (
            normalized * 1_024 * R.CAPACITY.THROUGHPUT_SAFETY_FACTOR
            / 3_600),
        "max_lane_wall_hours": max(lane_hours),
        "lane_wall_hours": lane_hours,
        "normalized_seconds_per_state_by_band": seconds,
        "target_states": 1_024,
        "safety_factor": R.CAPACITY.THROUGHPUT_SAFETY_FACTOR,
    }
    criteria = {
        "all_capacity_states_complete": True,
        "exact_evaluator_work_complete": True,
        "sampler_nonempty": True,
        "fleet_hours_le_cap": True,
        "max_lane_wall_hours_le_cap": True,
        "all": True,
    }
    accepted = R.CAPACITY.PREFLIGHT_STATES * (
        2 * (R.CAPACITY.DESIGN.SELECTION_WORLDS
             + R.CAPACITY.DESIGN.POLICY_REPORT_WORLDS)
        + R.CAPACITY.EVAL.REPORT_WORLDS)
    value = {
        "schema": R.CAPACITY.RESULT_SCHEMA,
        "run_id": R.CAPACITY.RUN_ID,
        "git": R.EXPECTED_GIT,
        "complete": True,
        "score_free": True,
        "outcomes_computed_in_memory": True,
        "outcomes_discarded": True,
        "outcomes_published": False,
        "records_discarded": R.CAPACITY.PREFLIGHT_STATES,
        "capacity_only_no_effect_estimate": True,
        "saturated_parallel_lanes": R.CAPACITY.DESIGN.SHARD_COUNT,
        "packet_internal_sha256": R.EXPECTED_PACKET_INTERNAL_SHA256,
        "runtime": _runtime(),
        "timing_rows": timings,
        "work_totals": {
            "current_policy_rollouts": (
                R.CAPACITY.PREFLIGHT_STATES
                * R.CAPACITY.DESIGN.POLICY_WORK_PER_STATE),
            "retained_policy_rollouts": (
                R.CAPACITY.PREFLIGHT_STATES
                * R.CAPACITY.DESIGN.POLICY_WORK_PER_STATE),
            "external_comparison_rollouts": (
                R.CAPACITY.PREFLIGHT_STATES
                * R.CAPACITY.EVAL.REPORT_WORLDS),
        },
        "sampler_totals": {
            "accepted_worlds": accepted,
            "sample_attempts": accepted,
            "rejected_worlds": 0,
            "failed_worlds": 0,
            "impossible_worlds": 0,
        },
        "selector_dose": {
            "policy_action_changes": 1,
            "retained_raw_winner_insertions": 2,
            "current_raw_winner_evictions": 0,
        },
        "projection": projection,
        "criteria": criteria,
        "status": "AUTHORIZE_CAPACITY_RESULT_REVIEW",
        "scored_packet_design_authorized": False,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
        "admission_sha256": admission_sha256,
        "packet_sha256": R.EXPECTED_PACKET_SHA256,
    }
    value["internal_sha256"] = R.CAPACITY.digest(value)
    return value


def _write(path: Path, value: dict) -> str:
    path.write_bytes(R.CAPACITY.canonical(value))
    return R.CAPACITY.sha256_file(path)


def _fixture(tmp_path: Path, monkeypatch) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    population_path = tmp_path / "population.json"
    shards = []
    for index in range(R.STATES.SHARD_COUNT):
        shard_path = R.STATES.shard_path(
            population_path, index, R.STATES.SHARD_COUNT)
        shard_path.write_bytes(b"{}\n")
        shards.append({"shard_index": index, "path": shard_path.name})
    population = {"shards": shards}
    population_path.write_bytes(R.CAPACITY.canonical(population))
    design_path = tmp_path / "design.json"
    design_path.write_bytes(R.CAPACITY.canonical(_design()))
    packet = _packet()
    packet_path = tmp_path / "packet.json"
    packet_sha = _write(packet_path, packet)
    monkeypatch.setattr(R, "EXPECTED_PACKET_SHA256", packet_sha)
    review, marker = _review()
    review_path = tmp_path / "packet-review-snapshot.md"
    review_path.write_bytes(marker)
    admission_path = tmp_path / "admission.json"
    admission_sha = _write(admission_path, _admission(review))
    result_path = tmp_path / "capacity.json"
    result_sha = _write(
        result_path, _result(admission_sha256=admission_sha))
    monkeypatch.setattr(
        R.CAPACITY, "load_packet", lambda *_args, **_kwargs: (_ for _ in ())
        .throw(AssertionError("reviewer must not use double-read load_packet")))
    monkeypatch.setattr(
        R.CAPACITY, "packet_problems", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        R.CAPACITY, "canonical_review_record",
        lambda **_kwargs: (copy.deepcopy(review), marker))
    monkeypatch.setattr(
        R.CAPACITY, "load_population", lambda *_args: copy.deepcopy(population))
    monkeypatch.setattr(R.DESIGN, "verify_design", lambda *_args: _design())
    return {
        "population_path": population_path,
        "design_path": design_path,
        "packet_path": packet_path,
        "packet_review_snapshot_path": review_path,
        "admission_path": admission_path,
        "expected_admission_sha256": admission_sha,
        "result_path": result_path,
        "expected_result_sha256": result_sha,
    }


def test_verified_claim_authorizes_design_only(tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    claim = R.verify(**args)
    assert claim["verdict"] == "PASS"
    assert claim["score_free_capacity_pass"] is True
    assert claim["scored_packet_design_authorized"] is True
    assert claim["scored_packet_freeze_authorized"] is False
    assert claim["scored_packet_run_authorized"] is False
    assert claim["scored_evaluation_authorized"] is False
    assert claim["report_access_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["retry_authorized"] is False
    assert claim["extension_authorized"] is False
    assert claim["result_reviewer_script_sha256"] == (
        R._sha256_file(Path(R.__file__)))
    assert claim["reviewer_dependency_sha256s"] == (
        R.EXPECTED_DEPENDENCY_SHA256S)


def test_stable_read_refuses_path_swap_during_fd_read(tmp_path, monkeypatch):
    target = tmp_path / "evidence.json"
    replacement = tmp_path / "replacement.json"
    displaced = tmp_path / "displaced.json"
    target.write_bytes(b"a" * ((1 << 20) + 1))
    replacement.write_bytes(b"b" * ((1 << 20) + 1))
    real_read = R.os.read
    swapped = False

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        chunk = real_read(descriptor, size)
        if not swapped:
            target.rename(displaced)
            replacement.rename(target)
            swapped = True
        return chunk

    monkeypatch.setattr(R.os, "read", racing_read)
    with pytest.raises(
            R.CapacityResultReviewRefused, match="changed during stable read"):
        R._stable_bytes(target, label="racing evidence")


def test_dependency_shard_mutation_during_reconstruction_refuses(
        tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    shard_path = R.STATES.shard_path(
        args["population_path"], 7, R.STATES.SHARD_COUNT)

    def mutate_after_snapshot(*_args, **_kwargs):
        shard_path.write_bytes(b'{"changed":true}\n')
        return []

    monkeypatch.setattr(R.CAPACITY, "packet_problems", mutate_after_snapshot)
    with pytest.raises(
            R.CapacityResultReviewRefused,
            match="source shard 07 changed during evidence validation"):
        R.verify(**args)


def test_symlink_is_not_hidden_by_cli_path_normalization(tmp_path):
    target = tmp_path / "target.json"
    link = tmp_path / "link.json"
    target.write_bytes(b"{}\n")
    link.symlink_to(target)
    lexical = R._absolute_lexical(link)
    assert lexical.is_symlink()
    with pytest.raises(
            R.CapacityResultReviewRefused, match="linked, nonregular"):
        R._stable_bytes(lexical, label="symlink evidence")


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value.__setitem__("score", 1), "forbidden outcome field"),
    (lambda value: value["runtime"].__setitem__("host", "other"),
     "runtime differs"),
    (lambda value: value["work_totals"].__setitem__(
        "current_policy_rollouts", 1), "work totals"),
    (lambda value: value["projection"].__setitem__(
        "fleet_hours", 0.1), "projection math"),
    (lambda value: value.__setitem__(
        "scored_evaluation_authorized", True), "authority escalation"),
])
def test_result_mutations_refuse_even_with_reforged_hashes(
        tmp_path, monkeypatch, mutation, expected):
    args = _fixture(tmp_path, monkeypatch)
    value = json.loads(args["result_path"].read_bytes())
    mutation(value)
    value.pop("internal_sha256")
    value["internal_sha256"] = R.CAPACITY.digest(value)
    args["expected_result_sha256"] = _write(args["result_path"], value)
    with pytest.raises(R.CapacityResultReviewRefused, match=expected):
        R.verify(**args)


def test_admission_and_review_snapshot_mutations_refuse(tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    admission = json.loads(args["admission_path"].read_bytes())
    admission["packet_review_commit"] = "0" * 40
    admission.pop("internal_sha256")
    admission["internal_sha256"] = R.CAPACITY.digest(admission)
    args["expected_admission_sha256"] = _write(
        args["admission_path"], admission)
    with pytest.raises(R.CapacityResultReviewRefused, match="identity"):
        R.verify(**args)

    args = _fixture(tmp_path / "second", monkeypatch)
    args["packet_review_snapshot_path"].write_bytes(b"forged\n")
    with pytest.raises(
            R.CapacityResultReviewRefused, match="snapshot is unreadable"):
        R.verify(**args)


def test_file_hash_and_self_hash_both_fail_closed(tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    with pytest.raises(R.CapacityResultReviewRefused, match="file SHA-256"):
        R.verify(**{**args, "expected_result_sha256": "0" * 64})

    value = json.loads(args["result_path"].read_bytes())
    value["internal_sha256"] = "0" * 64
    args["expected_result_sha256"] = _write(args["result_path"], value)
    with pytest.raises(R.CapacityResultReviewRefused, match="internal digest"):
        R.verify(**args)


def test_dishonest_capacity_file_hasher_cannot_bypass_result_hash(
        tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    result_path = args["result_path"]
    expected_result_sha256 = args["expected_result_sha256"]
    result_path.write_bytes(result_path.read_bytes() + b"\n")

    def dishonest_sha256_file(path: Path) -> str:
        if Path(path) == result_path:
            return expected_result_sha256
        return R._sha256_file(Path(path))

    monkeypatch.setattr(
        R.CAPACITY, "sha256_file", dishonest_sha256_file)
    with pytest.raises(
            R.CapacityResultReviewRefused,
            match="score-free capacity result file SHA-256 drift"):
        R.verify(**args)


@pytest.mark.parametrize("payload", [
    b'{"schema":"x","schema":"y"}',
    b'{"schema":"x","elapsed":NaN}',
    b'{"schema":"x","elapsed":Infinity}',
])
def test_strict_json_refuses_duplicates_and_nonfinite(
        tmp_path, payload):
    path = tmp_path / "hostile.json"
    path.write_bytes(payload)
    expected = R.CAPACITY.sha256_file(path)
    with pytest.raises(R.CapacityResultReviewRefused, match="unreadable"):
        R._load_exact_json(path, expected, label="hostile artifact")


def test_dependency_source_and_loaded_module_identity_fail_closed(monkeypatch):
    name = "pair_ballot_affected_capacity_preflight.py"
    monkeypatch.setitem(R.EXPECTED_DEPENDENCY_SHA256S, name, "0" * 64)
    with pytest.raises(R.CapacityResultReviewRefused, match="dependency identity"):
        R._require_dependency_sources()
    monkeypatch.undo()
    original = R.DEPENDENCY_MODULES[name]
    forged = types.ModuleType(original.__name__)
    forged.__file__ = original.__file__
    monkeypatch.setitem(R.DEPENDENCY_MODULES, name, forged)
    with pytest.raises(R.CapacityResultReviewRefused, match="dependency identity"):
        R._require_dependency_sources()


def test_dishonest_capacity_hasher_cannot_bypass_dependency_source_gate(
        monkeypatch):
    name = "pair_ballot_affected_capacity_preflight.py"
    monkeypatch.setitem(R.EXPECTED_DEPENDENCY_SHA256S, name, "0" * 64)
    monkeypatch.setattr(
        R.CAPACITY, "sha256_file", lambda _path: "0" * 64)
    with pytest.raises(
            R.CapacityResultReviewRefused,
            match="dependency identity drift"):
        R._require_dependency_sources()


def test_preloaded_dependency_refuses_even_with_expected_source_path(monkeypatch):
    monkeypatch.setattr(
        R, "PRELOADED_DEPENDENCIES",
        ("pair_ballot_affected_capacity_preflight",))
    with pytest.raises(R.CapacityResultReviewRefused, match="was preloaded"):
        R._require_dependency_sources()


def test_modified_dependency_never_executes_before_preimport_refusal(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    reviewer_name = Path(R.__file__).name
    copied_names = [
        reviewer_name,
        *(f"{name}.py" for name in R.DEPENDENCY_IMPORT_NAMES),
    ]
    for name in copied_names:
        (scripts / name).write_bytes((SCRIPTS / name).read_bytes())

    tripwire = tmp_path / "dependency-imported"
    target = scripts / "pair_ballot_affected_capacity_preflight.py"
    source = target.read_text()
    future = "from __future__ import annotations\n"
    side_effect = (
        future
        + "\nfrom pathlib import Path as _TripwirePath\n"
        + f"_TripwirePath({str(tripwire)!r}).write_text('executed')\n")
    target.write_text(source.replace(future, side_effect, 1))

    completed = subprocess.run(
        [sys.executable, "-B", str(scripts / reviewer_name)],
        cwd=tmp_path, capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert "review dependency source drift before import" in completed.stderr
    assert not tripwire.exists()


def test_unchecked_dependency_pyc_is_never_executed(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    reviewer_name = Path(R.__file__).name
    copied_names = [
        reviewer_name,
        *(f"{name}.py" for name in R.DEPENDENCY_IMPORT_NAMES),
    ]
    for name in copied_names:
        (scripts / name).write_bytes((SCRIPTS / name).read_bytes())

    tripwire = tmp_path / "dependency-pyc-imported"
    target = scripts / "pair_ballot_affected_capacity_preflight.py"
    hostile_source = tmp_path / "hostile_capacity.py"
    hostile_source.write_text(
        "from pathlib import Path\n"
        + f"Path({str(tripwire)!r}).write_text('executed')\n")
    cache = Path(importlib.util.cache_from_source(str(target)))
    cache.parent.mkdir()
    py_compile.compile(
        str(hostile_source), cfile=str(cache), dfile=str(target), doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)

    completed = subprocess.run(
        [sys.executable, "-B", str(scripts / reviewer_name)],
        cwd=tmp_path, capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    assert "the following arguments are required" in completed.stderr
    assert not tripwire.exists()


def test_reviewer_source_has_no_writer_or_launcher_surface():
    source = Path(R.__file__).read_text()
    for forbidden in (
            "write_exclusive", "write_bytes_exclusive", "measure_preflight",
            "run_command", "systemd-run", "evaluate_state", "REPORT_PATH"):
        assert forbidden not in source
