"""Durability, separation, and admission witnesses for V2 stages."""

from __future__ import annotations

import hashlib
import random
from dataclasses import replace
from pathlib import Path

import pytest
import torch

import shengji.rl.belief_v2_cohort_training as COHORT_STAGE
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.rl.belief_capture import CHAMPION_POLICY, _capture_with_policies
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_controller import (
    BeliefV2ControllerError,
    reopen_actor_capture_lane_manifest,
    reopen_capture_lane,
    reopen_reference_lane,
    reopen_synthetic_training_lane_examples,
    run_capture_lane,
    run_reference_lane,
)
from shengji.rl.belief_v2_execution_identity import (
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
    source_manifest_sha256,
)
from shengji.rl.belief_v2_device_qualification import (
    V2DeviceQualificationArmV1,
    build_qualification_plan,
    derive_qualification_result,
    qualification_protocol_sha256,
)
from shengji.rl.belief_v2_device_controller import (
    reopen_device_qualification,
    run_device_qualification,
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
from shengji.rl.belief_v2_human_controller import (
    BeliefV2HumanControllerError,
    reopen_human_training_group_examples,
    run_human_group_capture,
)
from shengji.rl.belief_v2_human_corpus import (
    V2HumanGroupCaptureV1,
    capture_human_corpus_pair,
)
from shengji.rl.belief_v2_human_inventory import (
    H0_INVENTORY_SCHEMA,
    _group_digest,
    build_h0_group_split,
    group_split_bytes,
    inventory_bytes,
)
from shengji.rl.belief_v2_protocol import (
    v2_policy_seeds,
    v2_round_coordinates,
)
from shengji.rl.belief_v2_schedule import (
    realize_v2_cohorts,
    realize_v2_common_calibration,
    training_row,
)
from shengji.rl.belief_v2_training import (
    build_human_training_example,
    build_synthetic_training_example,
)
from shengji.rl.belief_v2_training_controller import (
    BeliefV2TrainingControllerError,
    _resource_row,
    reopen_training_cohort,
    run_training_cohort,
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
        seed_candidate_report_sha256=_sha("4"),
        training_candidate_device="mps",
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256("mps")),
        cohorts=_cohorts(),
        resource_caps=V2ResourceCapsV1(
            capture_core_hours=64, capture_wall_seconds=14_400,
            capture_bytes=16 * 1024**3,
            reference_core_hours=16, reference_wall_seconds=7_200,
            reference_bytes=16 * 1024**3,
            training_device_hours=128, training_wall_seconds=86_400,
            training_bytes=32 * 1024**3,
            training_host_memory_bytes=24 * 1024**3,
            training_device_memory_bytes=12 * 1024**3),
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


def test_training_reader_authenticates_lane_without_opening_test_targets(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    coordinates = v2_round_coordinates()
    train = next(row for row in coordinates if row.split == "train")
    test = next(row for row in coordinates
                if row.lane == train.lane and row.split == "test")
    lane_coordinates = (train, test)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.v2_lane_coordinates",
        lambda lane: lane_coordinates)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.capture_v2_champion_round",
        _heuristic_capture)
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=train.lane,
        review_marker=b"review")
    test_filename = next(
        row["private_filename"] for row in result["rounds"]
        if row["split"] == "test")
    import shengji.rl.belief_v2_controller as controller
    real_read = controller.stable_read_bytes

    def test_target_tripwire(path):
        if path.name == test_filename:
            raise AssertionError("training opened a test target bundle")
        return real_read(path)

    monkeypatch.setattr(controller, "stable_read_bytes", test_target_tripwire)
    examples = reopen_synthetic_training_lane_examples(
        root / "capture" / f"lane-{train.lane:02d}",
        freeze=freeze, admission=admission, lane=train.lane,
        split="train")
    assert examples
    assert {example.split for example in examples} == {"train"}
    with pytest.raises(BeliefV2ControllerError,
                       match="split is not train/calibration"):
        reopen_synthetic_training_lane_examples(
            root / "capture" / f"lane-{train.lane:02d}",
            freeze=freeze, admission=admission, lane=train.lane,
            split="test")


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


def _human_state(seed=12101):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(9):
        seat = rnd.turn
        rnd.play(seat, bot.decide_play(rnd, seat))
    return rnd


def _human_receipts():
    source_raws = tuple(f"source-{index:02d}".encode("ascii")
                        for index in range(10))
    source_shas = tuple(hashlib.sha256(raw).hexdigest()
                        for raw in source_raws)
    rnd = _human_state()
    groups = [{
        "group_digest": _group_digest(source_sha),
        "source_bytes": len(raw),
        "complete_rounds": 1,
        "incomplete_rounds": 0,
        "human_play_decisions": 1,
        "trump_rank_counts": {rnd.trump_rank: 1},
        "attempted_channel_counts": {"absent": 1},
    } for raw, source_sha in zip(source_raws, source_shas, strict=True)]
    population_sha = hashlib.sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-human-source-digest-population-v1",
        "sha256s": sorted(source_shas),
    })).hexdigest()
    inventory = {
        "schema": H0_INVENTORY_SCHEMA,
        "source_manifest_sha256": _sha("5"),
        "source_file_count": 10,
        "source_digest_population_sha256": population_sha,
        "group_count": 10,
        "groups": sorted(groups, key=lambda row: row["group_digest"]),
        "rounds_seen": 10,
        "complete_rounds": 10,
        "incomplete_rounds": 0,
        "human_play_decisions": 10,
        "trump_rank_counts": {rnd.trump_rank: 10},
        "attempted_channel_counts": {"absent": 10},
        "hidden_ownership_labels_reconstructable_for_complete_rounds": True,
        "group_split_unit": "source-log-session-digest",
        "raw_player_identity_published": False,
        "model_rows_published": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    }
    group_split = build_h0_group_split(inventory)
    return source_raws, source_shas, rnd, inventory, group_split


def _captured_human_group(source_raw, source_sha, rnd, split):
    group_digest = _group_digest(source_sha)
    round_digest = hashlib.sha256(
        f"test-human-round|{group_digest}".encode("ascii")).hexdigest()
    pair = capture_human_corpus_pair(
        rnd, rnd.turn, group_digest=group_digest,
        round_digest=round_digest, decision_index=9, split=split)
    return V2HumanGroupCaptureV1(
        source_sha256=source_sha, group_digest=group_digest, split=split,
        complete_round_count=1, incomplete_round_count=0,
        human_decision_count=1,
        trump_rank_counts=((rnd.trump_rank, 1),),
        attempted_channel_counts=(("absent", 1),), pairs=(pair,))


def test_human_group_stage_persists_separate_rows_and_training_is_test_blind(
        tmp_path, monkeypatch):
    source_raws, source_shas, rnd, inventory, group_split = _human_receipts()
    split_by_digest = {
        digest: split for split, row in group_split["splits"].items()
        for digest in row["group_digests"]}
    selected = {}
    for raw, digest in zip(source_raws, source_shas, strict=True):
        split = split_by_digest[_group_digest(digest)]
        if split in {"train", "test"} and split not in selected:
            selected[split] = (raw, digest)
    assert set(selected) == {"train", "test"}
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    base = _freeze(root)
    splits = group_split["splits"]
    freeze = replace(
        base,
        h0_inventory_sha256=hashlib.sha256(
            inventory_bytes(inventory)).hexdigest(),
        h0_source_manifest_sha256=inventory["source_manifest_sha256"],
        h0_source_digest_population_sha256=(
            inventory["source_digest_population_sha256"]),
        human_group_split_sha256=hashlib.sha256(
            group_split_bytes(group_split, inventory=inventory)).hexdigest(),
        human_group_count=inventory["group_count"],
        human_train_group_count=splits["train"]["group_count"],
        human_calibration_group_count=splits["calibration"]["group_count"],
        human_test_group_count=splits["test"]["group_count"],
        human_complete_round_count=inventory["complete_rounds"],
        human_eligible_decision_count=inventory["human_play_decisions"],
        human_train_eligible_decision_count=(
            splits["train"]["human_play_decisions"]),
        human_calibration_eligible_decision_count=(
            splits["calibration"]["human_play_decisions"]),
        human_test_eligible_decision_count=(
            splits["test"]["human_play_decisions"]),
    )
    admission = _admission(freeze)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_controller._stage_gate",
        lambda **kwargs: None)

    captures = {}
    for split, (raw, digest) in selected.items():
        source = tmp_path / f"{split}.jsonl"
        source.write_bytes(raw)
        source.chmod(0o400)
        captured = _captured_human_group(raw, digest, rnd, split)
        monkeypatch.setattr(
            "shengji.rl.belief_v2_human_controller."
            "capture_human_source_group",
            lambda *args, value=captured, **kwargs: value)
        manifest = run_human_group_capture(
            root, freeze, admission, repo=Path("/unused"),
            source_path=source, inventory=inventory,
            group_split=group_split, review_marker=b"review")
        assert manifest["split"] == split
        assert manifest["actor_target_files_separate"] is True
        captures[split] = root / "human-capture" / (
            f"group-{captured.group_digest}")

    import shengji.rl.belief_v2_human_controller as human_controller
    real_read = human_controller.stable_read_bytes
    test_targets = captures["test"] / "private-targets"

    def test_target_tripwire(path):
        if path.parent == test_targets:
            raise AssertionError("human training opened test targets")
        return real_read(path)

    monkeypatch.setattr(
        human_controller, "stable_read_bytes", test_target_tripwire)
    examples = reopen_human_training_group_examples(
        captures["train"], freeze=freeze, admission=admission,
        split="train")
    assert len(examples) == 1
    assert examples[0].source_kind == "human"
    with pytest.raises(BeliefV2HumanControllerError,
                       match="split is not train/calibration"):
        reopen_human_training_group_examples(
            captures["test"], freeze=freeze, admission=admission,
            split="test")


def _cpu_fallback_qualification(freeze):
    batches = tuple((_sha256_text(f"qualification-{index}"),)
                    for index in range(40))
    plan = build_qualification_plan(
        execution_git=freeze.execution_git,
        candidate_device=freeze.training_candidate_device,
        batch_decision_keys=batches,
        batch_active_label_counts=tuple(100 for _ in batches),
        host_memory_cap_bytes=(
            freeze.resource_caps.training_host_memory_bytes),
        device_memory_cap_bytes=(
            freeze.resource_caps.training_device_memory_bytes))
    arms = []
    for index, (device, warmup, pair_index) in enumerate(plan.arm_order):
        arms.append(V2DeviceQualificationArmV1(
            arm_index=index, device=device, warmup=warmup,
            pair_index=pair_index, plan_sha256=plan.sha256(),
            batch_population_sha256=plan.selected_population_sha256,
            batch_schedule_sha256=plan.selected_schedule_sha256,
            decision_count=plan.decision_count,
            active_label_count=plan.active_label_count,
            member_checkpoint_sha256s=tuple(
                _sha256_text(f"{device}-checkpoint-{member}")
                for member in range(8)),
            member_loss_nanonats=tuple(
                1000 + member for member in range(8)),
            member_epoch_receipt_sha256s=tuple(
                _sha256_text(f"{device}-receipt-{member}")
                for member in range(8)),
            wall_nanoseconds=50 if warmup else (
                100 if device == "cpu" else 120),
            peak_host_memory_bytes=1024,
            peak_device_memory_bytes=0 if device == "cpu" else 2048,
            actual_device=device))
    return plan, derive_qualification_result(plan, tuple(arms))


def _sha256_text(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _tiny_training_population(freeze):
    train_capture = _heuristic_capture(_coordinate("train"))
    synthetic = tuple(build_synthetic_training_example(pair)
                      for pair in train_capture.pairs[:5])
    source_raw = b"training-human-source"
    source_sha = hashlib.sha256(source_raw).hexdigest()
    human_capture = _captured_human_group(
        source_raw, source_sha, _human_state(), "train")
    human = tuple(build_human_training_example(
        pair.actor_bytes, pair.target_bytes)
        for pair in human_capture.pairs)
    realizations = realize_v2_cohorts(
        freeze.cohorts,
        synthetic_rows=tuple(training_row(row) for row in synthetic),
        human_rows=tuple(training_row(row) for row in human))
    primary = next(row for row in realizations
                   if row.kind == "synthetic-primary")
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    training_examples = tuple(
        by_key[row.decision_key] for row in primary.rows)
    calibration = tuple(build_synthetic_training_example(pair)
                        for pair in _heuristic_capture(
                            _coordinate("calibration")).pairs[:2])
    calibration_schedule = realize_v2_common_calibration(calibration)
    return primary, training_examples, calibration, calibration_schedule


def test_device_qualification_stage_publishes_raw_reopenable_cpu_fallback(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    primary, training_examples, _, _ = _tiny_training_population(freeze)
    plan, result = _cpu_fallback_qualification(freeze)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._expected_plan",
        lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_in_memory",
        lambda **kwargs: (plan, result))
    manifest = run_device_qualification(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", primary=primary,
        primary_examples=training_examples)
    reopened, reopened_plan, reopened_result = reopen_device_qualification(
        root / "device-qualification" / "result",
        freeze=freeze, admission=admission, primary=primary)
    assert reopened == manifest
    assert reopened_plan == plan
    assert reopened_result == result
    assert manifest["selected_device"] == "cpu"
    assert manifest["accelerator_retained"] is False
    assert manifest["fallback_arm_count"] == 0
    assert manifest["training_authorized_by_this_artifact"] is False


def test_training_stage_publishes_reopenable_cpu_fallback_checkpoints(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration, calibration_schedule = (
        _tiny_training_population(freeze))
    qualification_plan, qualification_result = (
        _cpu_fallback_qualification(freeze))
    assert qualification_result.selected_device == "cpu"
    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller._validate_device_binding",
        lambda *args, **kwargs: "cpu")
    monkeypatch.setattr(COHORT_STAGE, "TRAIN_MAX_EPOCHS", 1)
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        manifest = run_training_cohort(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", primary=primary,
            realization=primary, training_examples=training_examples,
            calibration=calibration_schedule,
            calibration_examples=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result)
        directory = root / "training" / primary.cohort_id
        reopened, trained = reopen_training_cohort(
            directory, freeze=freeze, admission=admission,
            primary=primary, realization=primary,
            training_examples=training_examples,
            calibration=calibration_schedule,
            calibration_examples=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result)
    finally:
        torch.use_deterministic_algorithms(previous)
    assert reopened == manifest
    assert trained.training_device == "cpu"
    assert manifest["resources"]["peak_host_memory_bytes"] > 0
    assert manifest["resources"]["peak_device_memory_bytes"] == 0
    assert manifest["test_split_opened"] is False
    assert manifest["deployment_authorized"] is False
    checkpoint = directory / "member-00.checkpoint.bin"
    checkpoint.chmod(0o600)
    checkpoint.write_bytes(checkpoint.read_bytes() + b"x")
    checkpoint.chmod(0o400)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="persisted trained cohort"):
        reopen_training_cohort(
            directory, freeze=freeze, admission=admission,
            primary=primary, realization=primary,
            training_examples=training_examples,
            calibration=calibration_schedule,
            calibration_examples=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result)


def test_full_training_resource_receipt_enforces_its_own_memory_peaks(
        tmp_path):
    freeze = _freeze((tmp_path / "evidence").resolve())
    caps = freeze.resource_caps
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="resource cap"):
        _resource_row(
            freeze, started=10, finished=20, cpu_nanoseconds=5,
            artifact_bytes=1, selected_device="mps",
            peak_host_memory_bytes=caps.training_host_memory_bytes + 1,
            peak_device_memory_bytes=0)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="resource cap"):
        _resource_row(
            freeze, started=10, finished=20, cpu_nanoseconds=5,
            artifact_bytes=1, selected_device="mps",
            peak_host_memory_bytes=1,
            peak_device_memory_bytes=caps.training_device_memory_bytes + 1)
