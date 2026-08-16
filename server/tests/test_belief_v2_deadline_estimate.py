"""Wiring and reconstruction witnesses for the V2 deadline preflight."""

from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest
import scripts.belief_v2_deadline_preflight as DEADLINE_CLI
import shengji.rl.belief_v2_deadline_estimate as ESTIMATE

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_contract import (
    build_actor_observation,
    canonical_json_bytes,
)
from shengji.rl.belief_v2_deadline_estimate import (
    BeliefV2DeadlineEstimateError,
    DEADLINE_PROBE_ROUND_COUNT,
    V2DeadlineProbeMeasurement,
    deadline_estimate_receipt_bytes,
    deadline_probe_coordinates,
    derive_deadline_estimate_receipt,
    run_deadline_estimate_preflight,
    validate_deadline_estimate_receipt,
)
from shengji.rl.belief_v2_protocol import V2_RANKS


def _sha(char: str) -> str:
    return char * 64


def _preflight():
    return {
        "runtime": {"git_head": "a" * 40},
        "lanes": [{"rounds": [
            {"wall_nanoseconds": 100 + lane * 32 + index}
            for index in range(32)]}
            for lane in range(16)],
    }


def _receipt(monkeypatch):
    monkeypatch.setattr(
        ESTIMATE, "preflight_result_bytes", canonical_json_bytes)
    return derive_deadline_estimate_receipt(
        execution_git="a" * 40, runtime_profile_sha256=_sha("b"),
        training_device="cpu",
        preflight_result=_preflight(),
        reference_wall_nanoseconds=tuple(
            1_000 + index for index in range(DEADLINE_PROBE_ROUND_COUNT)),
        reference_worker_process_ids=tuple(
            10_000 + index % 16 for index in range(32)),
        reference_started_monotonic_nanoseconds=tuple(
            100 + index // 16 * 2_000 for index in range(32)),
        reference_finished_monotonic_nanoseconds=tuple(
            100 + index // 16 * 2_000 + 1_000 + index
            for index in range(32)),
        reference_manifest_population_sha256s=tuple(
            _sha("c") for _ in range(DEADLINE_PROBE_ROUND_COUNT)),
        training_probe_wall_nanoseconds=(2_000, 2_100),
        training_probe_receipt_sha256s=(_sha("d"), _sha("d")))


def test_probe_schedule_is_exact_rank_diverse_and_out_of_population():
    rows = deadline_probe_coordinates()
    assert len(rows) == DEADLINE_PROBE_ROUND_COUNT
    assert len({row.round_seed for row in rows}) == len(rows)
    assert {row.trump_rank for row in rows} == set(V2_RANKS)
    assert rows == deadline_probe_coordinates()


def test_measure_coordinate_drives_real_corpus_pair_observer(monkeypatch):
    coordinate = deadline_probe_coordinates()[0]
    monkeypatch.setattr(
        ESTIMATE, "deadline_probe_coordinates", lambda: (coordinate,))
    monkeypatch.setattr(
        ESTIMATE, "_validate_live_run_environment", lambda: None)
    monkeypatch.setattr(
        ESTIMATE, "make_bot", lambda _name, *, seed: HeuristicBot())
    calls = []

    def reference(rnd, seat, transcript, *, sampler_seed):
        assert type(sampler_seed) is int
        calls.append((seat, sampler_seed))
        actor = build_actor_observation(rnd, seat, transcript)
        return SimpleNamespace(
            actor=actor, manifest_sha256=lambda: _sha("9"))

    monkeypatch.setattr(ESTIMATE, "capture_ref_c_worlds", reference)
    measured = ESTIMATE._measure_coordinate(coordinate)
    assert measured.coordinate == coordinate
    assert measured.training_pairs
    assert len(calls) == len(measured.training_pairs)
    assert len(measured.reference_manifest_population_sha256) == 64


def test_receipt_reopens_raw_samples_projection_and_authority(monkeypatch):
    receipt = _receipt(monkeypatch)
    validate_deadline_estimate_receipt(receipt)
    assert receipt["capture_sample_count"] == 512
    assert receipt["reference_sample_count"] == 32
    assert receipt["training_epoch_sample_count"] == 2
    assert receipt["pipeline_execution_authorized"] is False
    assert receipt["production_seed_opened"] is False
    assert deadline_estimate_receipt_bytes(receipt) \
        == canonical_json_bytes(receipt)
    for mutation in (
            {**receipt, "capture_wall_nanoseconds":
             receipt["capture_wall_nanoseconds"][:-1]},
            {**receipt, "reference_p95_wall_nanoseconds":
             receipt["reference_p95_wall_nanoseconds"] - 1},
            {**receipt, "training_epoch_wall_estimate_nanoseconds":
             receipt["training_epoch_wall_estimate_nanoseconds"][:-1]},
            {**receipt, "safety_reserve_nanoseconds":
             receipt["safety_reserve_nanoseconds"] + 1},
            {**receipt, "pipeline_execution_authorized": True}):
        with pytest.raises(BeliefV2DeadlineEstimateError):
            validate_deadline_estimate_receipt(mutation)


class _Executor:
    def __init__(self, *, max_workers):
        assert max_workers == 16

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def map(self, function, coordinates):
        del function
        return tuple(V2DeadlineProbeMeasurement(
            coordinate=row, worker_process_id=10_000 + index % 16,
            started_monotonic_nanoseconds=100 + index // 16 * 2_000,
            finished_monotonic_nanoseconds=(
                100 + index // 16 * 2_000 + 1_000 + index),
            reference_wall_nanoseconds=1_000 + index,
            training_pairs=(f"pair-{index}",),
            reference_manifest_population_sha256=_sha("e"))
            for index, row in enumerate(coordinates))


def test_run_wires_measured_reference_and_training_receipts(monkeypatch):
    monkeypatch.setattr(
        ESTIMATE.concurrent.futures, "ProcessPoolExecutor", _Executor)
    monkeypatch.setattr(
        ESTIMATE, "build_synthetic_training_example", lambda pair: pair)
    monkeypatch.setattr(
        ESTIMATE, "collate_v2_training_examples", lambda examples: examples)
    calls = []

    def training_probe(batches, *, device, repeat):
        calls.append((batches, device, repeat))
        return 2_000 + repeat, _sha("f"), (_sha("1"),), (7,)

    monkeypatch.setattr(ESTIMATE, "_training_probe", training_probe)
    monkeypatch.setattr(
        ESTIMATE, "preflight_result_bytes", canonical_json_bytes)
    runtime = SimpleNamespace(to_dict=lambda: {"runtime": "exact"})
    receipt = run_deadline_estimate_preflight(
        execution_git="a" * 40, runtime=runtime,
        preflight_result=_preflight(), training_device="cpu")
    assert len(calls) == 3  # one warmup, two retained probes
    assert [call[2] for call in calls] == [0, 0, 1]
    assert receipt["reference_sample_count"] == 32
    assert receipt["training_probe_receipt_sha256s"] == [_sha("f")] * 2
    assert receipt["model_or_loss_artifacts_retained"] is False


def test_run_refuses_semantically_different_training_repeats(monkeypatch):
    monkeypatch.setattr(
        ESTIMATE.concurrent.futures, "ProcessPoolExecutor", _Executor)
    monkeypatch.setattr(
        ESTIMATE, "build_synthetic_training_example", lambda pair: pair)
    monkeypatch.setattr(
        ESTIMATE, "collate_v2_training_examples", lambda examples: examples)
    calls = 0

    def training_probe(batches, *, device, repeat):
        nonlocal calls
        del batches, device
        calls += 1
        # Warmup is ignored.  The two retained repeats disagree in receipt.
        return 2_000, _sha(str(repeat + 1)), (_sha("1"),), (7,)

    monkeypatch.setattr(ESTIMATE, "_training_probe", training_probe)
    with pytest.raises(BeliefV2DeadlineEstimateError,
                       match="semantic repeatability"):
        run_deadline_estimate_preflight(
            execution_git="a" * 40,
            runtime=SimpleNamespace(to_dict=lambda: {"runtime": "exact"}),
            preflight_result=_preflight(), training_device="cpu")
    assert calls == 3


def test_deadline_cli_validates_device_object_but_passes_canonical_name(
        monkeypatch, tmp_path, capsys):
    output = tmp_path / "deadline.json"
    preflight = tmp_path / "preflight.json"
    seen = []
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr(
        sys, "argv", ["belief_v2_deadline_preflight.py", "run",
                      "--expected-git", "a" * 40,
                      "--preflight-result", str(preflight),
                      "--training-device", "cpu", "--out", str(output)])
    monkeypatch.setattr(
        DEADLINE_CLI, "configure_numerical_runtime", lambda: None)
    monkeypatch.setattr(
        DEADLINE_CLI, "build_source_bindings", lambda *a, **k: None)
    runtime = SimpleNamespace(to_dict=lambda: {"runtime": "exact"})
    monkeypatch.setattr(DEADLINE_CLI, "build_runtime_profile", lambda: runtime)
    validated_device_object = object()
    monkeypatch.setattr(
        DEADLINE_CLI, "require_training_device",
        lambda value: validated_device_object)
    monkeypatch.setattr(DEADLINE_CLI, "_load", lambda path: {})
    monkeypatch.setattr(
        DEADLINE_CLI, "verify_preflight_result", lambda value: None)

    def run(*, execution_git, runtime, preflight_result, training_device):
        assert execution_git == "a" * 40
        assert training_device == "cpu"
        assert training_device is not validated_device_object
        seen.append((runtime, preflight_result))
        return {
            "capture_sample_count": 416,
            "reference_sample_count": 32,
            "training_epoch_sample_count": 2,
        }

    monkeypatch.setattr(DEADLINE_CLI, "run_deadline_estimate_preflight", run)
    monkeypatch.setattr(
        DEADLINE_CLI, "deadline_estimate_receipt_bytes", lambda value: b"{}\n")
    monkeypatch.setattr(
        DEADLINE_CLI, "publish_exclusive_bytes",
        lambda path, raw: _sha("f"))
    DEADLINE_CLI.main()
    assert seen == [(runtime, {})]
    assert '"pipeline_execution_authorized":false' in capsys.readouterr().out
