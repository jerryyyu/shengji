import dataclasses
import hashlib

import pytest

from shengji.rl import world_afterstate_v2_selection as selection
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_schedule import select_common_epoch
from shengji.rl.world_afterstate_v2_checkpoint import (
    checkpoint_bytes, reopen_checkpoint)
from shengji.rl.world_afterstate_v2_diagnostics import OptimizerCanaryReceiptV2
from shengji.rl.world_afterstate_v2_training import (
    WorldAfterstateV2TrainingConfig,
)
from shengji.rl.world_afterstate_v2_selection import EpochSelectPopulationV2
from shengji.rl.world_afterstate_v2_training_controller import (
    CohortTrainingBuildV2,
    SingleMemberTrainingBuildV2,
    WorldAfterstateV2TrainingControllerError,
    reopen_cohort_build, reopen_member_build, train_named_cohort, train_named_member,
    validate_cohort_manifest, validate_member_manifest,
)
from test_world_afterstate_v2_training import _rows
from test_world_afterstate_v2_evaluation import _population


def _config(max_epochs=1):
    return WorldAfterstateV2TrainingConfig(
        learning_rate_ppb=10_000_000, weight_decay_ppb=0,
        gradient_norm_milli=1_000, max_epochs=max_epochs,
        sigma_pair_squared=1.0)


def _selection_population():
    _predictions, outcomes, _prior, root = _population(
        root="controller-epoch-select")
    return EpochSelectPopulationV2(
        (dataclasses.replace(
            root, split="select", select_subfold="epoch-select"),),
        tuple(dataclasses.replace(row, split="select") for row in outcomes))


def _build(*, max_epochs=1, selection_population=None, **kwargs):
    options = {"wall_budget_nanoseconds": 10**15, "torch_threads": 1}
    options.update(kwargs)
    return train_named_cohort(
        cohort_name="natural", values=tuple(_rows("controller")),
        freeze_sha256=hashlib.sha256(b"freeze").hexdigest(),
        config=_config(max_epochs),
        selection_population=selection_population or _selection_population(),
        **options)


def test_overlapping_cohorts_keep_process_global_torch_width_pinned(
        monkeypatch):
    import shengji.rl.world_afterstate_v2_training_controller as controller

    assert controller._TORCH_THREAD_SCOPE_USERS == 0
    state = {"threads": 8}
    writes = []
    monkeypatch.setattr(
        controller.torch, "get_num_threads", lambda: state["threads"])

    def set_threads(value):
        writes.append(value)
        state["threads"] = value

    monkeypatch.setattr(controller.torch, "set_num_threads", set_threads)
    controller._acquire_torch_thread_scope(1)
    controller._acquire_torch_thread_scope(1)
    controller._release_torch_thread_scope(1)
    assert state["threads"] == 1
    controller._release_torch_thread_scope(1)
    assert state["threads"] == 8
    assert writes == [1, 8]


def test_happy_path_reopens_four_checkpoints_and_progress():
    progress = []
    build = _build(progress=lambda row: progress.append(row))
    models, manifest = reopen_cohort_build(build)
    assert len(models) == 4
    assert manifest["member_count"] == 4
    assert progress[-1]["completed_units"] == 4
    assert progress[-1]["percent_basis_points"] == 10_000
    assert all(item["authority"][key] is False
               for item in progress for key in item["authority"])


def test_controller_validates_selection_population_once_before_hot_loop(
        monkeypatch):
    original = selection._validate_population
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(selection, "_validate_population", counted)
    _build()
    assert calls == 1


def test_repeat_is_deterministic_and_common_epoch_is_rederived():
    first = _build(max_epochs=4, clock=lambda: 0)
    second = _build(max_epochs=4, clock=lambda: 0)
    assert first.manifest == second.manifest
    assert first.selected_checkpoint_raws == second.selected_checkpoint_raws
    assert select_common_epoch(
        tuple(tuple(score["loss_nano"] for score in row["selection_scores"])
              for row in first.manifest["members"])
    ).selected_epoch == 1


def test_dropped_member_and_state_chain_are_refused():
    build = _build()
    dropped = dataclasses.replace(build, selected_checkpoint_raws=build.selected_checkpoint_raws[:-1])
    with pytest.raises(WorldAfterstateV2TrainingControllerError, match="checkpoint drop"):
        reopen_cohort_build(dropped)
    forged = {**build.manifest}
    forged["members"] = [dict(row) for row in forged["members"]]
    forged["members"][1]["epoch_receipts"] = [
        dict(item) for item in forged["members"][1]["epoch_receipts"]]
    forged["members"][1]["epoch_receipts"][0]["model_state_sha256_before"] = \
        hashlib.sha256(b"forged").hexdigest()
    forged["manifest_sha256"] = hashlib.sha256(canonical_json_bytes({
        key: item for key, item in forged.items() if key != "manifest_sha256"})).hexdigest()
    with pytest.raises(WorldAfterstateV2TrainingControllerError, match="state chain"):
        validate_cohort_manifest(forged)


def test_deadline_before_first_epoch_refuses_without_partial_training():
    clock_values = iter((10, 11))
    with pytest.raises(WorldAfterstateV2TrainingControllerError, match="deadline before epoch"):
        _build(clock=lambda: next(clock_values), wall_budget_nanoseconds=1)


def test_truncation_preserves_forensic_build_but_is_not_audit_eligible():
    clock_values = iter((0, 0, 0, 1, 1, 1, 1, 1, 1))
    build = _build(max_epochs=4, clock=lambda: next(clock_values),
                   wall_budget_nanoseconds=1)
    assert build.manifest["truncated_by_deadline"] is True
    assert build.manifest["audit_eligible"] is False
    reopen_cohort_build(build)


def test_epoch_select_injection_and_invalid_concurrency_are_rejected():
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="sealed epoch-select population"):
        _build(selection_population={"audit": 1})
    with pytest.raises(WorldAfterstateV2TrainingControllerError, match="resource request"):
        _build(member_workers=3)


@pytest.mark.parametrize("torch_threads", (2, 4))
def test_training_calls_and_manifests_refuse_cross_width_torch_threads(
        torch_threads):
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource request"):
        _build(torch_threads=torch_threads)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource request"):
        _member_build(torch_threads=torch_threads)

    cohort_manifest = dict(_build().manifest)
    cohort_manifest["torch_threads"] = torch_threads
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource/identity"):
        validate_cohort_manifest(cohort_manifest)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource/identity"):
        reopen_cohort_build(CohortTrainingBuildV2(
            cohort_manifest, tuple(_build().selected_checkpoint_raws)))

    member_manifest = dict(_member_build().manifest)
    member_manifest["torch_threads"] = torch_threads
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource/identity"):
        validate_member_manifest(member_manifest)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource/identity"):
        reopen_member_build(SingleMemberTrainingBuildV2(
            member_manifest, _member_build().selected_checkpoint_raw))


def test_control_reuses_natural_root_schedule():
    natural = tuple(_rows("matched", cohort="primary"))
    control = tuple(dataclasses.replace(row, cohort="control") for row in natural)
    build = train_named_cohort(
        cohort_name="complete-world-shuffle", values=control,
        natural_values=natural,
        freeze_sha256=hashlib.sha256(b"freeze").hexdigest(), config=_config(),
        selection_population=_selection_population(),
        wall_budget_nanoseconds=10**15, torch_threads=1)
    assert build.manifest["cohort_name"] == "complete-world-shuffle"
    assert build.manifest["members"][0]["epoch_receipts"]


def test_optimizer_canary_is_diagnostics_only_and_reopened():
    canary = OptimizerCanaryReceiptV2(
        source_p0_population_sha256=hashlib.sha256(b"p0").hexdigest(),
        root_population_sha256=hashlib.sha256(b"roots").hexdigest(),
        model_seed=7, root_count=16, optimizer_steps=500,
        early_stopping_used=False, gradients_finite=True,
        weights_finite=True, initial_loss_nano=200,
        empirical_loss_nano=100, final_loss_nano=120,
        normalized_progress_ppm=800_000, passed=True,
        empirical_entropy_nano=100, empirical_paired_residual_nano=0)
    build = _build(optimizer_canary=lambda: canary)
    assert build.manifest["optimizer_canary"]["optimizer_steps"] == 500
    reopen_cohort_build(build)


def test_failed_optimizer_canary_and_bool_worker_count_are_refused():
    failed = OptimizerCanaryReceiptV2(
        source_p0_population_sha256=hashlib.sha256(b"p0").hexdigest(),
        root_population_sha256=hashlib.sha256(b"roots").hexdigest(),
        model_seed=7, root_count=16, optimizer_steps=500,
        early_stopping_used=False, gradients_finite=True,
        weights_finite=True, initial_loss_nano=200,
        empirical_loss_nano=100, final_loss_nano=190,
        normalized_progress_ppm=100_000, passed=False,
        empirical_entropy_nano=100, empirical_paired_residual_nano=0)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="optimizer canary refused"):
        _build(optimizer_canary=lambda: failed)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource request"):
        _build(member_workers=True)


def test_epoch_select_audit_population_is_refused():
    population = _selection_population()
    invalid = EpochSelectPopulationV2(
        (dataclasses.replace(population.roots[0], split="audit"),),
        population.outcomes)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="epoch-select population refused"):
        _build(selection_population=invalid)


@pytest.mark.parametrize("identity", ("init-seed", "schedule"))
def test_recovery_binds_checkpoint_init_seed_and_selected_schedule(identity):
    build = _build()
    models, manifest = reopen_cohort_build(build)
    original_raw = build.selected_checkpoint_raws[0]
    _original_model, metadata = reopen_checkpoint(original_raw)
    kwargs = {
        "seed_block": metadata["seed_block"],
        "member_index": metadata["member_index"],
        "control_name": metadata["control_name"],
        "init_seed": metadata["init_seed"],
        "selected_epoch": metadata["selected_epoch"],
        "freeze_sha256": metadata["freeze_sha256"],
        "config_sha256": metadata["config_sha256"],
        "population_sha256": metadata["population_sha256"],
        "schedule_sha256": metadata["schedule_sha256"],
        "common_epoch_sha256": metadata["common_epoch_sha256"],
    }
    if identity == "init-seed":
        kwargs["init_seed"] += 1
    else:
        kwargs["schedule_sha256"] = hashlib.sha256(
            b"foreign-schedule").hexdigest()
    foreign_raw = checkpoint_bytes(models[0], **kwargs)
    _foreign_model, foreign_metadata = reopen_checkpoint(foreign_raw)
    forged_manifest = {**manifest, "members": [dict(row)
                                                for row in manifest["members"]]}
    forged_manifest["members"][0].update({
        "selected_checkpoint_external_sha256": hashlib.sha256(
            foreign_raw).hexdigest(),
        "selected_checkpoint_sha256": foreign_metadata["checkpoint_sha256"],
        "selected_model_state_sha256": foreign_metadata["model_state_sha256"],
    })
    forged_manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes({key: item for key, item in forged_manifest.items()
                              if key != "manifest_sha256"})).hexdigest()
    forged_raws = list(build.selected_checkpoint_raws)
    forged_raws[0] = foreign_raw
    forged = CohortTrainingBuildV2(forged_manifest, tuple(forged_raws))
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="checkpoint metadata binding"):
        reopen_cohort_build(forged)


def _member_build(*, fraction=0.25, max_epochs=1, **kwargs):
    options = {"wall_budget_nanoseconds": 10**15, "torch_threads": 1,
               "clock": lambda: 0}
    options.update(kwargs)
    return train_named_member(
        values=tuple(_rows("nested-member")), data_fraction=fraction,
        freeze_sha256=hashlib.sha256(b"freeze").hexdigest(),
        config=_config(max_epochs), selection_population=_selection_population(),
        **options)


def test_single_member_nested_point_is_deterministic_and_reopens():
    first = _member_build(fraction=0.25)
    second = _member_build(fraction=0.25)
    assert type(first) is SingleMemberTrainingBuildV2
    assert first.manifest == second.manifest
    assert first.selected_checkpoint_raw == second.selected_checkpoint_raw
    model, manifest = reopen_member_build(first)
    assert manifest["member_name"] == "nested-curve-25"
    assert manifest["member_index"] == 0
    assert manifest["audit_eligible"] is False
    assert manifest["consumer_eligible"] is False
    assert model.training is True
    promoted = dict(manifest)
    promoted["consumer_eligible"] = True
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="identity"):
        validate_member_manifest(promoted)


def test_single_member_rejects_control_and_invalid_member():
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="natural cohort"):
        _member_build(cohort_name="complete-world-shuffle")
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="member index"):
        _member_build(member_index=1)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="primary seed block"):
        _member_build(seed_block=2)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource"):
        _member_build(member_workers=2)


def test_single_member_progress_and_deadline_routes():
    progress = []
    build = _member_build(fraction=0.5, max_epochs=2,
                          progress=lambda row: progress.append(row))
    assert progress[-1]["completed_units"] == 2
    assert progress[-1]["total_units"] == 2
    assert progress[-1]["percent_basis_points"] == 10_000
    assert progress[-1]["active_workers"] == 1
    validate_member_manifest(build.manifest)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="deadline before epoch"):
        _member_build(wall_budget_nanoseconds=1, clock=iter((10, 11)).__next__)
