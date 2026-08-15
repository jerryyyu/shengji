"""Durability, separation, and admission witnesses for V2 stages."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_capture import CHAMPION_POLICY, _capture_with_policies
from shengji.rl.belief_v2_controller import (
    BeliefV2ControllerError,
    reopen_actor_capture_lane_manifest,
    reopen_capture_lane,
    reopen_reference_lane,
    run_capture_lane,
    run_reference_lane,
)
from shengji.rl.belief_v2_execution_identity import (
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
    source_manifest_sha256,
)
from shengji.rl.belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_WORK_RULE,
    NO_HUMAN_DECISIONS,
    PRIMARY_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    SCALE_WORK_RULE,
    V2CohortPlanV1,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
    V2ResourceCapsV1,
)
from shengji.rl.belief_v2_protocol import (
    v2_policy_seeds,
    v2_round_coordinates,
)


def _sha(char: str) -> str:
    return char * 64


def _bindings():
    paths = sorted((
        "BELIEF_V1_SPEC.md", "BELIEF_V1_V2_DESIGN.md",
        "server/pyproject.toml", "server/setup.py", "server/uv.lock",
        "server/scripts/belief_v2_worker.py",
        "server/shengji/__init__.py"))
    return tuple(V2SourceBindingV1(
        path=path, byte_count=index + 1,
        sha256=f"{index + 1:x}" * 64)
        for index, path in enumerate(paths))


def _distribution(name, char):
    return V2InstalledDistributionV1(
        name=name, version="1.0", root=f"/runtime/{name}",
        file_count=10, payload_sha256=_sha(char))


def _runtime():
    return V2RuntimeProfileV1(
        hostname="host", operating_system="system", machine="machine",
        cpu_count=16, memory_bytes=32 * 1024**3,
        boot_identity=_sha("8"), python_executable="/runtime/python",
        python_executable_sha256=_sha("9"), python_version="3.14.4",
        torch=_distribution("torch", "a"),
        torch_config_sha256=_sha("b"),
        numpy=_distribution("numpy", "c"),
        native_path="/runtime/_fast.so", native_sha256=_sha("d"),
        required_environment=(
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTHONHASHSEED", "0"),
            ("SHENGJI_FAST", "1"),
            ("SHENGJI_REQUIRE_VOIDS", "1")))


def _cohorts():
    return (
        V2CohortPlanV1(
            cohort_id="synthetic-primary", kind="synthetic-primary",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id=None),
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="human-mixture", kind="human-mixture",
            synthetic_selection_rule=MIXED_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=ALL_HUMAN_TRAIN_DECISIONS,
            work_match_rule=MIXED_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="synthetic-scale-50", kind="synthetic-scale",
            synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=2,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=SCALE_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
    )


def _freeze(root: Path):
    bindings = _bindings()
    return V2ExecutionFreezeV1(
        execution_git="a" * 40,
        source_manifest_sha256=source_manifest_sha256("a" * 40, bindings),
        source_bindings=bindings, runtime=_runtime(),
        source_review_commit="b" * 40,
        v1_terminal_route="v1-pass-to-b3",
        v1_terminal_result_sha256=_sha("b"),
        v1_resource_receipt_sha256=_sha("c"),
        v2_reentry_rationale_sha256=None,
        h0_inventory_sha256=_sha("d"),
        h0_source_manifest_sha256=_sha("e"),
        h0_source_digest_population_sha256=_sha("f"),
        human_group_split_sha256=_sha("0"),
        human_group_count=30, human_train_group_count=24,
        human_calibration_group_count=3, human_test_group_count=3,
        human_complete_round_count=122,
        human_eligible_decision_count=2830,
        human_train_eligible_decision_count=2240,
        human_calibration_eligible_decision_count=416,
        human_test_eligible_decision_count=174,
        preflight_result_sha256=_sha("1"),
        preflight_runtime_sha256=_sha("2"),
        seed_registry_sha256=_sha("3"),
        seed_candidate_report_sha256=_sha("4"), cohorts=_cohorts(),
        resource_caps=V2ResourceCapsV1(
            capture_core_hours=64, capture_wall_seconds=14_400,
            capture_bytes=16 * 1024**3,
            reference_core_hours=16, reference_wall_seconds=7_200,
            reference_bytes=16 * 1024**3,
            training_device_hours=128, training_wall_seconds=86_400,
            training_bytes=32 * 1024**3),
        evidence_root=str(root))


def _admission(freeze):
    return V2PipelineAdmissionV1(
        freeze_sha256=freeze.sha256(), execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        review_commit="c" * 40, canonical_remote_tip="d" * 40,
        review_marker_sha256=_sha("e"), evidence_root=freeze.evidence_root)


def _coordinate(split="calibration"):
    return next(row for row in v2_round_coordinates() if row.split == split)


def _heuristic_capture(coordinate):
    seeds = v2_policy_seeds(coordinate)
    return _capture_with_policies(
        coordinate.round_seed, CHAMPION_POLICY, seeds,
        [HeuristicBot() for _ in range(4)],
        trump_rank=coordinate.trump_rank)


def _prepare(monkeypatch, tmp_path, split="calibration"):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    coordinate = _coordinate(split)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    # Full 256-world mechanics are already pinned by the reference suite; this
    # controller test exercises publication/reopen wiring at a bounded count.
    monkeypatch.setattr(
        "shengji.rl.belief_refc_capture.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference._WORLD_UNIT_PPB", 250_000_000)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.v2_lane_coordinates",
        lambda lane: (coordinate,))
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.capture_v2_champion_round",
        _heuristic_capture)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_reference.make_bot",
        lambda *args, **kwargs: HeuristicBot())
    return root, freeze, admission, coordinate


def test_capture_publishes_one_search_private_and_actor_only_bytes(
        tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    calls = []

    def capture(value):
        calls.append(value)
        return _heuristic_capture(value)

    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.capture_v2_champion_round",
        capture)
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    assert calls == [coordinate]
    assert result["round_count"] == 1
    row = result["rounds"][0]
    assert row["private_bundle_sha256"] != row["actor_bundle_sha256"]
    assert row["decision_count"] > 0
    assert result["contains_round_outcomes"] is False
    assert result["actor_contains_privileged_targets"] is False
    assert reopen_capture_lane(
        root / "capture" / f"lane-{coordinate.lane:02d}",
        freeze=freeze, admission=admission, lane=coordinate.lane) == result


def test_reference_opens_no_private_capture_bundle(tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    import shengji.rl.belief_v2_controller as controller
    real_read = controller.stable_read_bytes

    def target_blind(path):
        if path.parent.name == "private":
            raise AssertionError("reference opened a private target bundle")
        return real_read(path)

    monkeypatch.setattr(controller, "stable_read_bytes", target_blind)
    result = run_reference_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    assert result["job_count"] == 2
    assert result["input_surface"] == "actor-only-capture-bundles"
    assert result["contains_privileged_training_targets"] is False
    assert reopen_reference_lane(
        root / "reference" / f"lane-{coordinate.lane:02d}",
        capture_directory=(
            root / "capture" / f"lane-{coordinate.lane:02d}"),
        freeze=freeze, admission=admission, lane=coordinate.lane) == result


def test_public_capture_reopen_requires_private_file_population(
        tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    directory = root / "capture" / f"lane-{coordinate.lane:02d}"
    row = result["rounds"][0]
    (directory / "private" / row["private_filename"]).unlink()
    with pytest.raises(BeliefV2ControllerError,
                       match="private file population drift"):
        reopen_actor_capture_lane_manifest(
            directory, freeze=freeze, admission=admission,
            lane=coordinate.lane)


def test_capture_refuses_before_write_when_stage_gate_fails(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)

    def refuse(**kwargs):
        raise BeliefV2ControllerError("gate refused")

    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller._stage_gate", refuse)
    with pytest.raises(BeliefV2ControllerError, match="gate refused"):
        run_capture_lane(
            root, freeze, admission, repo=Path("/unused"), lane=0,
            review_marker=b"review")
    assert not (root / "capture").exists()


def test_capture_reopen_refuses_mutated_exact_bundle(tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    row = result["rounds"][0]
    path = (root / "capture" / f"lane-{coordinate.lane:02d}"
            / "actor-only" / row["actor_filename"])
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"x")
    path.chmod(0o400)
    with pytest.raises(BeliefV2ControllerError,
                       match="bundle byte binding"):
        reopen_capture_lane(
            root / "capture" / f"lane-{coordinate.lane:02d}",
            freeze=freeze, admission=admission, lane=coordinate.lane)


def test_capture_slot_is_no_retry(tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    with pytest.raises(BeliefV2ControllerError, match="slot is occupied"):
        run_capture_lane(
            root, freeze, admission, repo=Path("/unused"),
            lane=coordinate.lane, review_marker=b"review")
