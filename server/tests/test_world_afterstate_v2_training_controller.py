import dataclasses
import hashlib

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_schedule import select_common_epoch
from shengji.rl.world_afterstate_v2_checkpoint import (
    checkpoint_bytes, reopen_checkpoint)
from shengji.rl.world_afterstate_v2_diagnostics import OptimizerCanaryReceiptV2
from shengji.rl.world_afterstate_v2_training import (
    WorldAfterstateV2TrainingConfig, model_state_sha256,
)
from shengji.rl.world_afterstate_v2_training_controller import (
    CohortTrainingBuildV2, EpochSelectScoreV2,
    WorldAfterstateV2TrainingControllerError,
    reopen_cohort_build, train_named_cohort, validate_cohort_manifest,
)
from test_world_afterstate_v2_training import _rows


def _config(max_epochs=1):
    return WorldAfterstateV2TrainingConfig(
        learning_rate_ppb=10_000_000, weight_decay_ppb=0,
        gradient_norm_milli=1_000, max_epochs=max_epochs,
        sigma_pair_squared=1.0)


def _build(*, max_epochs=1, scorer=None, **kwargs):
    scorer = scorer or _scorer()
    options = {"wall_budget_nanoseconds": 10**15, "torch_threads": 1}
    options.update(kwargs)
    return train_named_cohort(
        cohort_name="natural", values=tuple(_rows("controller")),
        freeze_sha256=hashlib.sha256(b"freeze").hexdigest(),
        config=_config(max_epochs), selection_loss=scorer,
        **options)


def _scorer(*, seed_block=1, control_name="natural", loss=None):
    def score(model, epoch, member):
        return EpochSelectScoreV2(
            epoch=epoch, seed_block=seed_block, member_index=member,
            control_name=control_name,
            model_state_sha256=model_state_sha256(model),
            selection_population_sha256=hashlib.sha256(
                b"epoch-select-population").hexdigest(),
            prediction_manifest_sha256=hashlib.sha256(
                f"prediction:{seed_block}:{control_name}:{epoch}:{member}".encode()
            ).hexdigest(),
            loss_nano=(loss(epoch) if loss is not None else epoch))
    return score


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


def test_repeat_is_deterministic_and_common_epoch_is_rederived():
    first = _build(max_epochs=4, scorer=_scorer(loss=lambda epoch: 100 + epoch),
                   clock=lambda: 0)
    second = _build(max_epochs=4, scorer=_scorer(loss=lambda epoch: 100 + epoch),
                    clock=lambda: 0)
    assert first.manifest == second.manifest
    assert first.selected_checkpoint_raws == second.selected_checkpoint_raws
    assert first.manifest["common_epoch"]["selected_epoch"] == 1
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


def test_audit_scorer_injection_and_invalid_concurrency_are_rejected():
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="typed epoch-select"):
        _build(scorer=lambda _model, _epoch, _member: {"audit": 1})
    with pytest.raises(WorldAfterstateV2TrainingControllerError, match="resource request"):
        _build(member_workers=3)


def test_control_reuses_natural_root_schedule():
    natural = tuple(_rows("matched", cohort="primary"))
    control = tuple(dataclasses.replace(row, cohort="control") for row in natural)
    build = train_named_cohort(
        cohort_name="complete-world-shuffle", values=control,
        natural_values=natural,
        freeze_sha256=hashlib.sha256(b"freeze").hexdigest(), config=_config(),
        selection_loss=_scorer(control_name="complete-world-shuffle"),
        wall_budget_nanoseconds=10**15, torch_threads=1)
    assert build.manifest["cohort_name"] == "complete-world-shuffle"
    assert build.manifest["members"][0]["epoch_receipts"]


def test_optimizer_canary_is_diagnostics_only_and_reopened():
    canary = OptimizerCanaryReceiptV2(
        root_population_sha256=hashlib.sha256(b"roots").hexdigest(),
        model_seed=7, root_count=16, optimizer_steps=500,
        early_stopping_used=False, gradients_finite=True,
        weights_finite=True, initial_loss_nano=200,
        empirical_loss_nano=100, final_loss_nano=120,
        normalized_progress_ppm=800_000, passed=True)
    build = _build(optimizer_canary=lambda: canary)
    assert build.manifest["optimizer_canary"]["optimizer_steps"] == 500
    reopen_cohort_build(build)


def test_failed_optimizer_canary_and_bool_worker_count_are_refused():
    failed = OptimizerCanaryReceiptV2(
        root_population_sha256=hashlib.sha256(b"roots").hexdigest(),
        model_seed=7, root_count=16, optimizer_steps=500,
        early_stopping_used=False, gradients_finite=True,
        weights_finite=True, initial_loss_nano=200,
        empirical_loss_nano=100, final_loss_nano=190,
        normalized_progress_ppm=100_000, passed=False)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="optimizer canary refused"):
        _build(optimizer_canary=lambda: failed)
    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="resource request"):
        _build(member_workers=True)


def test_selection_score_model_and_population_bindings_are_refused():
    foreign_model = _scorer()

    def wrong_model(model, epoch, member):
        return dataclasses.replace(
            foreign_model(model, epoch, member),
            model_state_sha256=hashlib.sha256(b"foreign-model").hexdigest())

    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="score/model binding"):
        _build(scorer=wrong_model)

    base = _scorer()

    def mixed_population(model, epoch, member):
        score = base(model, epoch, member)
        if member == 3:
            score = dataclasses.replace(
                score,
                selection_population_sha256=hashlib.sha256(
                    b"foreign-select-population").hexdigest())
        return score

    with pytest.raises(WorldAfterstateV2TrainingControllerError,
                       match="population mixing"):
        _build(scorer=mixed_population)


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
