from __future__ import annotations

import copy
import hashlib

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_model import CAPACITY_SHAPES
from shengji.rl.world_afterstate_v1_controls import (
    action_association_permutation)
from shengji.rl.world_afterstate_v1_dataset import join_advantage_examples
from shengji.rl.world_afterstate_v1_schedule import build_subsplit_manifest
from shengji.rl.world_afterstate_v1_training import (
    AdvantageTrainingConfigV1)
from shengji.rl.world_afterstate_v1_training_controller import (
    AUTHORITY, WorldAfterstateV1TrainingControllerError,
    publish_cohort_build, reopen_cohort_build, reopen_cohort_directory,
    train_named_cohort, validate_cohort_manifest)

from test_world_afterstate_v1_schedule import _fixture


def _config(max_epochs=1):
    return AdvantageTrainingConfigV1(
        learning_rate_ppb=1_000_000,
        weight_decay_ppb=10_000_000,
        gradient_norm_milli=1_000,
        max_epochs=max_epochs,
        early_stop_patience=1,
        minimum_improvement_nanoloss=1)


def _population():
    rows, bindings = _fixture()
    joined = list(join_advantage_examples(rows))
    manifest = build_subsplit_manifest(
        bindings, v0_population_manifest_sha256="d" * 64)
    return joined, manifest


def _run(*, cohort_name="natural", controlled=False, max_epochs=1,
         wall=10**12, progress=None):
    joined, manifest = _population()
    values = joined
    if controlled:
        values, _evidence = action_association_permutation(joined)
    return train_named_cohort(
        cohort_name=cohort_name, values=values,
        subsplit_manifest=manifest, freeze_sha256="f" * 64,
        shape_name="small", initialization_seeds=tuple(range(801, 809)),
        config=_config(max_epochs), pair_cap=24, schedule_seed=61,
        wall_budget_nanoseconds=wall, progress=progress)


def _rehash_manifest(value):
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    value["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()


def test_natural_cohort_seals_and_reopens_all_eight_selected_members():
    progress = []
    build = _run(progress=progress.append)
    models, manifest = reopen_cohort_build(build)
    assert len(models) == 8
    assert manifest["cohort_name"] == "natural"
    assert manifest["control_population"] is False
    assert manifest["stop_reason"] == "max-epochs"
    assert manifest["audit_rows_opened"] is False
    assert manifest["report_rows_opened"] is False
    assert manifest["authority"] == AUTHORITY
    assert progress[-1]["percent_basis_points"] == 10_000
    assert progress[-1]["audit_rows_opened"] is False


def test_deadline_truncation_seals_a_valid_control_common_epoch():
    build = _run(
        cohort_name="action-association-permutation", controlled=True,
        max_epochs=3, wall=1)
    models, manifest = reopen_cohort_build(build)
    assert len(models) == 8
    assert manifest["control_population"] is True
    assert manifest["truncated_by_deadline"] is True
    assert manifest["stop_reason"] == "deadline-truncation"
    assert manifest["epoch_count"] == 1
    assert manifest["common_epoch"]["selected_epoch"] == 1


def test_manifest_and_selected_checkpoint_bindings_have_teeth():
    build = _run()
    forged = copy.deepcopy(build.manifest)
    forged["fit_schedule_receipts"][0]["batch_pair_keys"][0].reverse()
    with pytest.raises(WorldAfterstateV1TrainingControllerError,
                       match="schedule"):
        validate_cohort_manifest(forged)

    altered = bytearray(build.selected_checkpoint_raws[0])
    altered[-2] ^= 1
    broken = copy.copy(build)
    object.__setattr__(broken, "selected_checkpoint_raws",
                       (bytes(altered), *build.selected_checkpoint_raws[1:]))
    with pytest.raises(WorldAfterstateV1TrainingControllerError,
                       match="external binding drift"):
        reopen_cohort_build(broken)

    forged_selection = copy.deepcopy(build.manifest)
    forged_selection["members"][0]["selection_loss_nano"][0] += 8
    _rehash_manifest(forged_selection)
    with pytest.raises(WorldAfterstateV1TrainingControllerError,
                       match="common epoch selection drift"):
        validate_cohort_manifest(forged_selection)


def test_control_source_cannot_masquerade_as_natural():
    joined, manifest = _population()
    controlled, _evidence = action_association_permutation(joined)
    with pytest.raises(WorldAfterstateV1TrainingControllerError,
                       match="source population drift"):
        train_named_cohort(
            cohort_name="natural", values=controlled,
            subsplit_manifest=manifest, freeze_sha256="f" * 64,
            shape_name="small", initialization_seeds=tuple(range(801, 809)),
            config=_config(), pair_cap=24, schedule_seed=61,
            wall_budget_nanoseconds=10**12)


def test_checkpoint_shape_remains_the_frozen_small_capacity():
    build = _run()
    models, _manifest = reopen_cohort_build(build)
    assert all(model.shape == CAPACITY_SHAPES["small"] for model in models)


def test_cohort_directory_is_immutable_exact_and_single_publication(tmp_path):
    build = _run()
    target = tmp_path / "cohort"
    publish_cohort_build(target, build)
    models, manifest = reopen_cohort_directory(target)
    assert len(models) == 8
    assert manifest == build.manifest
    assert {path.relative_to(target).as_posix()
            for path in target.rglob("*") if path.is_file()} == {
        "manifest.json", *(f"checkpoints/member-{index:02d}.json"
                           for index in range(8)),
    }
    with pytest.raises(WorldAfterstateV1TrainingControllerError,
                       match="namespace occupied"):
        publish_cohort_build(target, build)

    target.chmod(0o700)
    extra = target / "extra.json"
    extra.write_bytes(b"{}\n")
    extra.chmod(0o400)
    with pytest.raises(WorldAfterstateV1TrainingControllerError,
                       match="file population drift"):
        reopen_cohort_directory(target)
