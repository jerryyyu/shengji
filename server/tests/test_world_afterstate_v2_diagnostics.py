import dataclasses
import hashlib
import math

import pytest

from shengji.rl.world_afterstate_v2_diagnostics import (
    AUTHORITY, CANARY_PROGRESS_PPM, ESTIMAND_IDENTITY,
    ModelSelectorPowerReceiptV2, NestedCurvePointV2, NestedCurveReceiptV2,
    OptimizerCanaryReceiptV2, PrimaryMemberEpochV2, PrimaryStabilityReceiptV2,
    WorldAfterstateV2DiagnosticsError, validate_model_selector_power_v2,
)


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _canary(**changes):
    body = dict(root_population_sha256=_sha("p0"), model_seed=7,
                root_count=16, optimizer_steps=500,
                early_stopping_used=False, gradients_finite=True,
                weights_finite=True, initial_loss_nano=1_000,
                empirical_loss_nano=100, final_loss_nano=280,
                normalized_progress_ppm=800_000, passed=True)
    body.update(changes)
    return OptimizerCanaryReceiptV2(**body)


def _slope(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum(
        (x - mx) ** 2 for x in xs)


def _curve(**changes):
    points = tuple(NestedCurvePointV2(
        fraction_ppm=fraction, independent_deal_count=count,
        population_sha256=_sha(f"population-{fraction}"),
        fit_rps_nano=1000 + count, select_rps_nano=1200 + count,
        fit_paired_error_nano=800 + count, select_paired_error_nano=900 + count,
        checkpoint_sha256=_sha(f"checkpoint-{fraction}"),
        ensemble_member_eligible=(fraction == 1_000_000))
                   for fraction, count in ((250_000, 25), (500_000, 50),
                                            (1_000_000, 100)))
    xs = [math.log(point.independent_deal_count) for point in points]
    body = dict(
        points=points, full_fit_population_sha256=points[-1].population_sha256,
        primary_member0_checkpoint_sha256=points[-1].checkpoint_sha256,
        fit_select_rps_gaps_nano=tuple(point.fit_rps_nano - point.select_rps_nano
                                       for point in points),
        fit_select_paired_error_gaps_nano=tuple(
            point.fit_paired_error_nano - point.select_paired_error_nano
            for point in points),
        fit_rps_slope=_slope(xs, [point.fit_rps_nano for point in points]),
        select_rps_slope=_slope(xs, [point.select_rps_nano for point in points]),
        fit_paired_error_slope=_slope(xs, [point.fit_paired_error_nano for point in points]),
        select_paired_error_slope=_slope(xs, [point.select_paired_error_nano for point in points]))
    body.update(changes)
    return NestedCurveReceiptV2(**body)


def _stability(**changes):
    members = tuple(tuple(PrimaryMemberEpochV2(
        member_index=member, epoch=epoch, fit_loss_nano=1000 - epoch,
        select_loss_nano=1100 - epoch, gradient_norm_nano=10,
        update_norm_nano=2, prediction_entropy_nano=500,
        paired_target_error_nano=20)
                        for epoch in (1, 2, 3)) for member in range(4))
    body = dict(members=members, selected_epochs=(3, 3, 3, 3),
                common_epoch=3, common_epoch_dispersion=0)
    body.update(changes)
    return PrimaryStabilityReceiptV2(**body)


def _power(**changes):
    utilities = (0, 100_000, 200_000, 300_000)
    mean = sum(utilities) / len(utilities)
    sd = math.sqrt(sum((value - mean) ** 2 for value in utilities) / 3)
    required = math.ceil(((1.644854 + 0.841621) * sd / 100_000) ** 2)
    body = dict(precision_select_population_sha256=_sha("select"),
                deal_utilities_microlevels=utilities,
                precision_select_deal_count=len(utilities),
                frozen_audit_deal_count=len(utilities), s_model_microlevels=sd,
                n_required=required, stop_underpowered=required > len(utilities))
    body.update(changes)
    return ModelSelectorPowerReceiptV2(**body)


def test_optimizer_canary_is_exactly_fixed_and_progress_is_rederived():
    receipt = _canary()
    receipt.validate()
    assert receipt.normalized_progress_ppm == CANARY_PROGRESS_PPM
    assert not any(AUTHORITY.values())
    for changes, match in ((("root_count", 15), "identity"),
                           (("optimizer_steps", 499), "identity"),
                           (("normalized_progress_ppm", 800_001), "progress"),
                           (("final_loss_nano", 900), "progress")):
        with pytest.raises(WorldAfterstateV2DiagnosticsError, match=match):
            _canary(**{changes[0]: changes[1]}).validate()
    failed = _canary(early_stopping_used=True, passed=False)
    failed.validate()
    with pytest.raises(WorldAfterstateV2DiagnosticsError,
                       match="gate reconstruction"):
        dataclasses.replace(failed, passed=True).validate()


def test_nested_curve_binds_prefixes_gaps_slopes_and_member_zero_checkpoint():
    receipt = _curve()
    receipt.validate()
    forged = _curve(fit_select_rps_gaps_nano=(0, 0, 0))
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="gap"):
        forged.validate()
    forged = _curve(primary_member0_checkpoint_sha256=_sha("wrong"))
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="100%"):
        forged.validate()
    forged = _curve(fit_rps_slope=0.0)
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="slope"):
        forged.validate()


def test_primary_stability_requires_four_complete_members_and_common_epoch():
    _stability().validate()
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="population"):
        _stability(members=_stability().members[:3]).validate()
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="member binding"):
        members = list(_stability().members)
        members[0] = tuple(dataclasses.replace(row, member_index=1)
                           for row in members[0])
        _stability(members=tuple(members)).validate()
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="common epoch"):
        _stability(selected_epochs=(2, 3, 3, 3),
                   common_epoch_dispersion=0).validate()
    members = list(_stability().members)
    members[0] = (members[0][0], members[0][2])
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="common epoch"):
        _stability(members=tuple(members)).validate()


def test_model_selector_power_rederives_exact_constants_bessel_sd_and_stop():
    receipt = _power()
    receipt.validate()
    assert receipt.estimand_identity == ESTIMAND_IDENTITY
    validate_model_selector_power_v2(receipt)
    for field, value in (("z_alpha_ppm", 1_644_855),
                         ("z_power_ppm", 841_622),
                         ("delta_microlevels", 100_001),
                         ("replica_count", 4),
                         ("n_required", receipt.n_required + 1)):
        with pytest.raises(WorldAfterstateV2DiagnosticsError):
            dataclasses.replace(receipt, **{field: value}).validate()
    with pytest.raises(WorldAfterstateV2DiagnosticsError, match="Bessel"):
        dataclasses.replace(receipt, s_model_microlevels=1.0).validate()
