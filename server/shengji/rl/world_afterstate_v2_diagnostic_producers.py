"""Producers for the typed Section 9 diagnostic receipts.

Only values rederived from sealed training/evaluation artifacts are accepted.
The canary below is deliberately a thin runner over the reviewed trainer: it
does not accept caller metrics or provide a second optimization path.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
from typing import Any, Mapping, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_diagnostics import (
    CURVE_FRACTIONS_PPM, DELTA_MICROLEVELS, ESTIMAND_IDENTITY,
    REPLICA_COUNT, Z_ALPHA_PPM, Z_POWER_PPM, ModelSelectorPowerReceiptV2,
    NestedCurvePointV2, NestedCurveReceiptV2, OptimizerCanaryReceiptV2,
    PrimaryMemberEpochV2, PrimaryStabilityReceiptV2,
)
from .world_afterstate_v2_evaluation import (
    AbsoluteCurveScoreReceiptV2, EvaluationResultV2, NestedCurveScoreV2,
    evaluate_absolute_curve_v2, evaluate_nested_curve_v2,
)
from .world_afterstate_v2_continuation import ContinuationBundleV2
from .world_afterstate_v2_dataset import build_training_examples_v2
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_selection_contract import EpochSelectScoreV2
from .world_afterstate_v2_training import WorldAfterstateV2EpochReceipt
from .world_afterstate_v2_training import (
    WorldAfterstateV2TrainingConfig, collate_training_examples,
    new_optimizer, root_balanced_loss, train_epoch,
)
from .world_afterstate_v2_model import OUTCOME_CLASSES, new_world_afterstate_v2_model
from .world_afterstate_v2_metrics import JeffreysPriorV2
from .world_afterstate_v2_protocol import P0_CELLS, TIER_SPECS, select_p0_population
from .world_afterstate_v2_training_controller import (
    CohortTrainingBuildV2, SingleMemberTrainingBuildV2,
    reopen_cohort_build, reopen_member_build,
)
from .world_afterstate import category_signed_level


class DiagnosticProducerDependencyBlocked(RuntimeError):
    """A receipt field is not exposed by the reviewed upstream primitive."""


@dataclass(frozen=True)
class OptimizerCanaryInputV2:
    """The sealed canonical P0 labels plus their full pre-label population.

    The 128 unlabelled natural-fit materials prove that the 96 labelled
    materials are exactly the outcome-blind canonical P0 subset.  This keeps
    the canary behind P0 without spending labels on the other 32 deals.
    """

    natural_fit_materials: tuple[PopulationMaterialV2, ...]
    materials: tuple[PopulationMaterialV2, ...]
    bundles: tuple[ContinuationBundleV2, ...]

    def validate(self) -> None:
        if (type(self.natural_fit_materials) is not tuple
                or type(self.materials) is not tuple
                or type(self.bundles) is not tuple
                or len(self.natural_fit_materials) != 128
                or len(self.materials) != 96 or len(self.bundles) != 96):
            raise DiagnosticProducerDependencyBlocked(
                "optimizer canary requires complete D256/P0 materials")
        for material in self.natural_fit_materials:
            if type(material) is not PopulationMaterialV2:
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary source type drift")
            try:
                material.validate()
            except Exception as exc:
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary source seal drift") from exc
            if material.state.source != "natural" or material.state.split != "fit":
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary requires natural-fit materials")
        for material, bundle in zip(self.materials, self.bundles, strict=True):
            if type(material) is not PopulationMaterialV2 \
                    or type(bundle) is not ContinuationBundleV2:
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary source type drift")
            try:
                material.validate(); bundle.validate()
            except Exception as exc:
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary source seal drift") from exc
            if (bundle.deal_sha256, bundle.slot_sha256, bundle.state_sha256,
                    bundle.candidate_set_sha256) != (
                        material.deal_sha256, material.slot_sha256,
                        material.state_sha256, material.candidate_set_sha256):
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary material/bundle binding drift")
            if material.state.source != "natural" or material.state.split != "fit":
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary requires natural-fit materials")
        try:
            selected = select_p0_population(
                tuple(material.state for material in self.natural_fit_materials),
                tier=TIER_SPECS[0])
        except Exception as exc:
            raise DiagnosticProducerDependencyBlocked(
                "optimizer canary canonical P0 selection refused") from exc
        if ({state.deal_sha256 for state in selected}
                != {material.deal_sha256 for material in self.materials}):
            raise DiagnosticProducerDependencyBlocked(
                "optimizer canary labelled P0 selection drift")


MISSING_OPTIMIZER_TELEMETRY = (
    "canonical P0 state/material binding for the optimizer canary is missing"
)
MISSING_STABILITY_TELEMETRY = (
    "primary stability requires epoch gradient/update norm, prediction "
    "entropy, and paired-target error telemetry"
)
MISSING_CURVE_TELEMETRY = (
    "EvaluationResultV2 exposes only improvement metrics; use "
    "evaluate_absolute_curve_v2 for sealed absolute fit/select scores"
)


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise DiagnosticProducerDependencyBlocked(f"{label} is not a SHA-256")
    return value


def _empirical_floor(rows: Sequence[Any]) -> tuple[int, int]:
    """Return the root-balanced empirical entropy and exact pair floor."""
    by_root: dict[str, dict[int, list[Any]]] = {}
    for row in rows:
        by_root.setdefault(row.root_key, {}).setdefault(
            row.candidate_index, []).append(row)
    root_entropies: list[float] = []
    for candidates in by_root.values():
        if 0 not in candidates:
            raise DiagnosticProducerDependencyBlocked(
                "optimizer canary empirical incumbent missing")
        candidate_entropies: list[float] = []
        means: dict[int, Fraction] = {}
        for candidate, candidate_rows in candidates.items():
            if len(candidate_rows) != 8 \
                    or {row.replica for row in candidate_rows} != set(range(8)):
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary empirical replica population drift")
            counts: dict[int, int] = {}
            for row in candidate_rows:
                counts[row.signed_level_category] = \
                    counts.get(row.signed_level_category, 0) + 1
            candidate_entropies.append(-sum(
                (count / 8.0) * math.log(count / 8.0)
                for count in counts.values()) / math.log(OUTCOME_CLASSES))
            means[candidate] = sum(
                (Fraction(1, 8) * Fraction(str(category_signed_level(
                    row.signed_level_category))))
                for row in candidate_rows)
        root_entropies.append(sum(candidate_entropies) / len(candidate_entropies))
        incumbent = means[0]
        incumbent_rows = {row.replica: row for row in candidates[0]}
        for candidate, mean in means.items():
            if candidate == 0:
                continue
            # The target and the empirical prediction are computed from the
            # same eight-replica distributions.  Fraction arithmetic makes
            # the zero residual a checked identity, not an assertion.
            target = sum(
                Fraction(1, 8) * (
                    Fraction(str(category_signed_level(
                        row.signed_level_category)))
                    - Fraction(str(category_signed_level(
                        incumbent_rows[row.replica].signed_level_category))))
                for row in candidates[candidate])
            prediction = mean - incumbent
            if prediction - target != 0:
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary empirical paired residual drift")
    if len(root_entropies) != 16:
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary empirical root count drift")
    return round(sum(root_entropies) / len(root_entropies) * 1_000_000_000), 0


def produce_optimizer_canary_v2(*args: Any, **kwargs: Any) -> OptimizerCanaryReceiptV2:
    """Run exactly 500 reviewed optimizer steps over 16 canonical roots."""
    if len(args) != 1 or kwargs:
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary requires one sealed P0 training population")
    population = args[0]
    if type(population) is not OptimizerCanaryInputV2:
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary requires typed sealed P0 population materials")
    population.validate()
    try:
        rows = tuple(row for material, bundle in zip(
            population.materials, population.bundles, strict=True)
                     for row in build_training_examples_v2(material, bundle))
        selected_states = select_p0_population(
            tuple(material.state for material in population.natural_fit_materials),
            tier=TIER_SPECS[0])
    except Exception as exc:
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary P0 dataset construction failed") from exc
    selected_state_shas = {state.state_sha256 for state in selected_states}
    groups: dict[str, list[Any]] = {}
    try:
        for row in rows:
            row.validate()
            if row.split != "fit" or row.cohort != "primary":
                raise ValueError("fit primary rows required")
            groups.setdefault(row.root_key, []).append(row)
    except Exception as exc:
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary P0 rows refused") from exc
    # A smallest-hash selection is meaningful only against the complete
    # outcome-free P0 root population.  Accepting an already-truncated 16-root
    # caller population would let the caller choose the canary sample.
    groups = {key: value for key, value in groups.items()
              if value[0].state_sha256 in selected_state_shas}
    if len(groups) != 96:
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary canonical P0 root selection drift")
    root_cells = {}
    for key, group in groups.items():
        cells = {(row.phase, row.position, row.role) for row in group}
        if len(cells) != 1:
            raise DiagnosticProducerDependencyBlocked("optimizer canary root stratum drift")
        root_cells[key] = next(iter(cells))
    cell_counts = {cell: sum(value == cell for value in root_cells.values())
                   for cell in P0_CELLS}
    if set(cell_counts) != set(P0_CELLS) or any(
            count != 8 for count in cell_counts.values()):
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary P0 cell census drift")
    selected_keys = tuple(sorted(groups)[:16])
    selected = []
    for key in selected_keys:
        group = sorted(groups[key], key=lambda row: (row.candidate_index, row.replica))
        candidates = sorted({row.candidate_index for row in group})
        if candidates != list(range(len(candidates))) or len(candidates) < 2 \
                or [(row.candidate_index, row.replica) for row in group] != [
                (candidate, replica) for candidate in candidates for replica in range(8)]:
            raise DiagnosticProducerDependencyBlocked("optimizer canary incomplete sibling set")
        selected.extend(group)
    try:
        batch = collate_training_examples(tuple(selected))
        if batch.root_count != 16:
            raise ValueError("root count")
        config = WorldAfterstateV2TrainingConfig(
            learning_rate_ppb=10_000_000, weight_decay_ppb=0,
            gradient_norm_milli=1_000, max_epochs=1, sigma_pair_squared=1.0)
        model = new_world_afterstate_v2_model(0)
        optimizer = new_optimizer(model, config)
        empirical_entropy, paired = _empirical_floor(selected)
        # The initial loss is evaluated before the first optimizer update.  A
        # train_epoch receipt's loss is pre-update, so using its first value
        # would accidentally report a 499-step final instead of the exact
        # requested 500-step endpoint.
        with torch.no_grad():
            initial = round(float(root_balanced_loss(
                model(batch.tensors), batch, config.sigma_pair_squared))
                            * 1_000_000_000)
        receipts = []
        for _step in range(500):
            receipts.append(train_epoch(model, optimizer, (batch,), epoch=1,
                                         config=config))
            if any(parameter.grad is None
                   or not bool(torch.all(torch.isfinite(parameter.grad)))
                   or not bool(torch.all(torch.isfinite(parameter)))
                   for parameter in model.parameters()):
                raise DiagnosticProducerDependencyBlocked(
                    "optimizer canary non-finite step state")
        with torch.no_grad():
            final = round(float(root_balanced_loss(
                model(batch.tensors), batch, config.sigma_pair_squared))
                          * 1_000_000_000)
        finite = all(bool(torch.all(torch.isfinite(parameter)))
                     for parameter in model.parameters())
        gradients_finite = all(row.gradient_norm_nano >= 0 for row in receipts)
    except Exception as exc:
        raise DiagnosticProducerDependencyBlocked(
            "optimizer canary execution failed") from exc
    denominator = initial - empirical_entropy
    progress = ((initial - final) * 1_000_000 // denominator
                if denominator > 0 else 0)
    source = _sha({"schema": "world-afterstate-v2-p0-canary-source-v2",
                   "population": sorted((
                       material.state.state_sha256, bundle.bundle_sha256)
                       for material, bundle in zip(
                           population.materials, population.bundles,
                           strict=True)),
                   "selected_root_keys": list(selected_keys)})
    receipt = OptimizerCanaryReceiptV2(
        source_p0_population_sha256=source,
        root_population_sha256=_sha(list(selected_keys)), model_seed=0,
        root_count=16, optimizer_steps=500, early_stopping_used=False,
        gradients_finite=gradients_finite, weights_finite=finite,
        initial_loss_nano=initial, empirical_loss_nano=empirical_entropy,
        final_loss_nano=final, normalized_progress_ppm=max(0, progress),
        passed=(gradients_finite and finite and paired == 0
                and denominator > 0 and progress >= 800_000),
        empirical_entropy_nano=empirical_entropy,
        empirical_paired_residual_nano=paired)
    receipt.validate()
    return receipt


def produce_primary_stability_v2(*args: Any, **kwargs: Any) -> PrimaryStabilityReceiptV2:
    """Derive stability from one reopened natural cohort build."""
    if len(args) != 1 or kwargs:
        raise DiagnosticProducerDependencyBlocked("primary stability requires one cohort build")
    build = args[0]
    if type(build) is not CohortTrainingBuildV2:
        raise DiagnosticProducerDependencyBlocked("primary stability cohort build type drift")
    try:
        _models, manifest = reopen_cohort_build(build)
    except Exception as exc:
        raise DiagnosticProducerDependencyBlocked(
            "primary stability cohort build cannot be typed-reopened") from exc
    if manifest.get("cohort_name") != "natural":
        raise DiagnosticProducerDependencyBlocked("primary stability requires natural cohort")
    members = []
    selected = []
    for member_index, row in enumerate(manifest.get("members", ())):
        epochs = row.get("epoch_receipts", ())
        scores = row.get("selection_scores", ())
        if type(epochs) is not list or type(scores) is not list \
                or len(epochs) != len(scores) or not epochs:
            raise DiagnosticProducerDependencyBlocked("primary stability epoch/score rows missing")
        member_rows = []
        for epoch_payload, score_payload in zip(epochs, scores, strict=True):
            try:
                epoch = WorldAfterstateV2EpochReceipt(
                    **{key: epoch_payload[key] for key in (
                        "epoch", "batch_count", "example_count", "root_count",
                        "mean_root_loss_nano", "config_sha256", "population_sha256",
                        "schedule_sha256", "model_state_sha256_before",
                        "model_state_sha256_after", "split", "cohort",
                        "gradient_norm_nano", "update_norm_nano",
                        "prediction_entropy_nano", "paired_target_error_nano",
                        "schema")})
                epoch.validate()
                score = EpochSelectScoreV2(**score_payload)
                score.validate()
            except Exception as exc:
                raise DiagnosticProducerDependencyBlocked(
                    "primary stability epoch/selection row reconstruction failed") from exc
            if score.epoch != epoch.epoch or score.member_index != member_index \
                    or epoch.cohort != "primary":
                raise DiagnosticProducerDependencyBlocked("primary stability epoch binding drift")
            telemetry = (epoch.gradient_norm_nano, epoch.update_norm_nano,
                         epoch.prediction_entropy_nano)
            if any(value <= 0 for value in telemetry):
                raise DiagnosticProducerDependencyBlocked(
                    "primary stability telemetry is unpopulated")
            member_rows.append(PrimaryMemberEpochV2(
                member_index=member_index, epoch=epoch.epoch,
                fit_loss_nano=epoch.mean_root_loss_nano,
                select_loss_nano=score.loss_nano,
                gradient_norm_nano=epoch.gradient_norm_nano,
                update_norm_nano=epoch.update_norm_nano,
                prediction_entropy_nano=epoch.prediction_entropy_nano,
                paired_target_error_nano=epoch.paired_target_error_nano))
        members.append(tuple(member_rows))
        selected.append(min(member_rows, key=lambda row: (row.select_loss_nano,
                                                           row.epoch)).epoch)
    if len(members) != 4:
        raise DiagnosticProducerDependencyBlocked("primary stability member population drift")
    common_epoch = min(range(1, len(members[0]) + 1), key=lambda epoch: (
        sum(member[epoch - 1].select_loss_nano for member in members), epoch))
    receipt = PrimaryStabilityReceiptV2(
        members=tuple(members), selected_epochs=tuple(selected),
        common_epoch=common_epoch,
        common_epoch_dispersion=max(selected) - min(selected))
    receipt.validate()
    return receipt


@dataclass(frozen=True)
class NestedCurveInputV2:
    """One actual fit/select evaluation pair and sealed checkpoint build."""

    independent_deal_count: int
    fit: EvaluationResultV2 | NestedCurveScoreV2
    select: EvaluationResultV2 | NestedCurveScoreV2
    checkpoint_build: CohortTrainingBuildV2 | SingleMemberTrainingBuildV2
    ensemble_member_eligible: bool = False
    fit_absolute: AbsoluteCurveScoreReceiptV2 | None = None
    select_absolute: AbsoluteCurveScoreReceiptV2 | None = None
    fit_prediction_manifest: Mapping[str, Any] | None = None
    fit_outcomes: tuple[Any, ...] | None = None
    fit_prior: JeffreysPriorV2 | None = None
    select_prediction_manifest: Mapping[str, Any] | None = None
    select_outcomes: tuple[Any, ...] | None = None
    select_prior: JeffreysPriorV2 | None = None


def _checkpoint_sha(build: CohortTrainingBuildV2 | SingleMemberTrainingBuildV2) -> str:
    if type(build) is SingleMemberTrainingBuildV2:
        try:
            _model, manifest = reopen_member_build(build)
            if (manifest["seed_block"], manifest["member_index"],
                    manifest["cohort_name"]) != (1, 0, "natural"):
                raise ValueError
            if manifest["data_fraction_ppm"] not in (250_000, 500_000):
                raise ValueError
            return _digest(manifest["selected_checkpoint_external_sha256"],
                           "nested curve checkpoint")
        except Exception as exc:
            raise DiagnosticProducerDependencyBlocked(
                "nested curve single-member checkpoint cannot be typed-reopened") from exc
    if type(build) is not CohortTrainingBuildV2:
        raise DiagnosticProducerDependencyBlocked("nested curve checkpoint build type drift")
    try:
        _models, manifest = reopen_cohort_build(build)
        member = manifest["members"][0]
        digest = member["selected_checkpoint_external_sha256"]
    except Exception as exc:
        raise DiagnosticProducerDependencyBlocked(
            "nested curve checkpoint build cannot be typed-reopened") from exc
    return _digest(digest, "nested curve checkpoint")


def produce_nested_curve_v2(
        inputs: Sequence[NestedCurveInputV2], *,
        full_fit_population_sha256: str | None = None,
        primary_member0_checkpoint_sha256: str | None = None) -> NestedCurveReceiptV2:
    """Build a curve from three typed absolute fit/select score pairs."""
    if type(inputs) not in (tuple, list) or len(inputs) != 3:
        raise DiagnosticProducerDependencyBlocked("nested curve requires three actual points")
    ordered = tuple(sorted(inputs, key=lambda value: value.independent_deal_count))
    counts = tuple(value.independent_deal_count for value in ordered)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in counts) or counts[2] % 4 \
            or counts != (counts[2] // 4, counts[2] // 2, counts[2]):
        raise DiagnosticProducerDependencyBlocked("nested curve multiplicities are not 25/50/100 percent")
    points = []
    for index, item in enumerate(ordered):
        if type(item) is not NestedCurveInputV2:
            raise DiagnosticProducerDependencyBlocked("nested curve evaluation type drift")
        if type(item.fit) is not EvaluationResultV2 and type(item.fit) is not NestedCurveScoreV2 \
                or type(item.select) is not EvaluationResultV2 and type(item.select) is not NestedCurveScoreV2:
            raise DiagnosticProducerDependencyBlocked("nested curve evaluation type drift")
        item.fit.validate(); item.select.validate()
        fit_absolute = item.fit_absolute
        select_absolute = item.select_absolute
        if type(item.fit) is NestedCurveScoreV2:
            if type(item.select) is not NestedCurveScoreV2 \
                    or item.fit.fraction_ppm != CURVE_FRACTIONS_PPM[index] \
                    or item.select.fraction_ppm != CURVE_FRACTIONS_PPM[index] \
                    or item.fit.split != "fit" or item.select.split != "select" \
                    or (item.fit.control_name, item.fit.seed_block,
                        item.select.control_name, item.select.seed_block) != (
                            "natural", 1, "natural", 1) \
                    or item.fit.consumer_eligible or item.select.consumer_eligible \
                    or (index < 2 and (
                        type(item.checkpoint_build) is not SingleMemberTrainingBuildV2
                        or item.ensemble_member_eligible)) \
                    or (index == 2 and (
                        type(item.checkpoint_build) is not CohortTrainingBuildV2
                        or item.ensemble_member_eligible is not True)):
                raise DiagnosticProducerDependencyBlocked(
                    "nested curve score eligibility/binding drift")
            if index < 2:
                try:
                    _model, member_manifest = reopen_member_build(
                        item.checkpoint_build)
                except Exception as exc:
                    raise DiagnosticProducerDependencyBlocked(
                        "nested curve single-member checkpoint cannot be typed-reopened") from exc
                if (member_manifest["data_fraction_ppm"]
                        != CURVE_FRACTIONS_PPM[index]
                        or member_manifest["selected_model_state_sha256"]
                        != item.fit.model_state_sha256
                        or item.select.model_state_sha256
                        != item.fit.model_state_sha256):
                    raise DiagnosticProducerDependencyBlocked(
                        "nested curve single-member checkpoint/model binding drift")
            fit_absolute = item.fit
            select_absolute = item.select
        elif index < 2:
            raise DiagnosticProducerDependencyBlocked(
                "nested curve 25/50 require single-member absolute scores")
        if fit_absolute is None and item.fit_prediction_manifest is not None \
                and item.fit_outcomes is not None and item.fit_prior is not None:
            fit_absolute = evaluate_absolute_curve_v2(
                item.fit_prediction_manifest, item.fit_outcomes, item.fit_prior)
        if select_absolute is None and item.select_prediction_manifest is not None \
                and item.select_outcomes is not None and item.select_prior is not None:
            select_absolute = evaluate_absolute_curve_v2(
                item.select_prediction_manifest, item.select_outcomes, item.select_prior)
        if type(fit_absolute) not in (
                NestedCurveScoreV2, AbsoluteCurveScoreReceiptV2) \
                or type(select_absolute) is not type(fit_absolute) \
                or index < 2 and type(fit_absolute) is not NestedCurveScoreV2:
            raise DiagnosticProducerDependencyBlocked(MISSING_CURVE_TELEMETRY)
        fit_absolute.validate(); select_absolute.validate()
        if (fit_absolute.population_sha256 != item.fit.population_sha256
                or select_absolute.population_sha256 != item.select.population_sha256):
            raise DiagnosticProducerDependencyBlocked("nested curve absolute score binding drift")
        if index >= 2 and (item.fit.control_name, item.fit.seed_block,
                           item.select.control_name, item.select.seed_block) != (
                               "natural", 1, "natural", 1):
            raise DiagnosticProducerDependencyBlocked("nested curve natural fit/select binding drift")
        if item.fit.population_sha256 == item.select.population_sha256:
            raise DiagnosticProducerDependencyBlocked("nested curve fit/select populations must differ")
        population = _digest(item.fit.population_sha256, "nested curve population")
        checkpoint = _checkpoint_sha(item.checkpoint_build)
        if index == 2:
            if type(item.checkpoint_build) is not CohortTrainingBuildV2 \
                    or item.ensemble_member_eligible is not True:
                raise DiagnosticProducerDependencyBlocked(
                    "nested curve 100% member eligibility drift")
            try:
                full_manifest = reopen_cohort_build(item.checkpoint_build)[1]
            except Exception as exc:
                raise DiagnosticProducerDependencyBlocked(
                    "nested curve full cohort checkpoint cannot be reopened") from exc
            if (full_manifest.get("cohort_name") != "natural"
                    or full_manifest.get("seed_block") != 1
                    or full_manifest.get("members", [{}])[0].get("member_index") != 0
                    or type(item.fit) is NestedCurveScoreV2 and (
                        full_manifest["members"][0].get(
                            "selected_model_state_sha256")
                        != item.fit.model_state_sha256
                        or item.select.model_state_sha256
                        != item.fit.model_state_sha256)):
                raise DiagnosticProducerDependencyBlocked(
                    "nested curve full cohort/member-0 binding drift")
        points.append(NestedCurvePointV2(
            fraction_ppm=CURVE_FRACTIONS_PPM[index],
            independent_deal_count=item.independent_deal_count,
            population_sha256=population,
            fit_rps_nano=fit_absolute.rps_nano,
            select_rps_nano=select_absolute.rps_nano,
            fit_paired_error_nano=fit_absolute.paired_target_error_nano,
            select_paired_error_nano=select_absolute.paired_target_error_nano,
            checkpoint_sha256=checkpoint,
            ensemble_member_eligible=item.ensemble_member_eligible))
    full_population = _digest(
        full_fit_population_sha256 or ordered[-1].fit.population_sha256,
        "nested curve full fit population")
    primary_checkpoint = _digest(
        primary_member0_checkpoint_sha256 or _checkpoint_sha(ordered[-1].checkpoint_build),
        "nested curve primary checkpoint")
    if points[-1].population_sha256 != full_population \
            or points[-1].checkpoint_sha256 != primary_checkpoint:
        raise DiagnosticProducerDependencyBlocked("nested curve full-population binding drift")
    receipt = NestedCurveReceiptV2(
        points=tuple(points), full_fit_population_sha256=full_population,
        primary_member0_checkpoint_sha256=primary_checkpoint,
        fit_select_rps_gaps_nano=tuple(
            point.fit_rps_nano - point.select_rps_nano for point in points),
        fit_select_paired_error_gaps_nano=tuple(
            point.fit_paired_error_nano - point.select_paired_error_nano
            for point in points),
        fit_rps_slope=0.0, select_rps_slope=0.0,
        fit_paired_error_slope=0.0, select_paired_error_slope=0.0)
    # Recompute the four slopes through the contract's deterministic formula
    # by constructing the exact values here; validation remains authoritative.
    xs = [math.log(point.independent_deal_count) for point in points]
    def slope(values: Sequence[int]) -> float:
        mean_x, mean_y = sum(xs) / 3, sum(values) / 3
        return sum((x - mean_x) * (y - mean_y)
                   for x, y in zip(xs, values)) / sum((x - mean_x) ** 2 for x in xs)
    receipt = NestedCurveReceiptV2(
        points=tuple(points), full_fit_population_sha256=full_population,
        primary_member0_checkpoint_sha256=primary_checkpoint,
        fit_select_rps_gaps_nano=receipt.fit_select_rps_gaps_nano,
        fit_select_paired_error_gaps_nano=receipt.fit_select_paired_error_gaps_nano,
        fit_rps_slope=slope([point.fit_rps_nano for point in points]),
        select_rps_slope=slope([point.select_rps_nano for point in points]),
        fit_paired_error_slope=slope([point.fit_paired_error_nano for point in points]),
        select_paired_error_slope=slope([point.select_paired_error_nano for point in points]))
    receipt.validate()
    return receipt


def produce_model_selector_power_v2(
        precision_select: EvaluationResultV2, *,
        frozen_audit_deal_count: int) -> ModelSelectorPowerReceiptV2:
    """Derive power from the sealed precision-select action utilities."""
    if type(precision_select) is not EvaluationResultV2:
        raise DiagnosticProducerDependencyBlocked("precision-select result type drift")
    precision_select.validate()
    if (precision_select.control_name, precision_select.seed_block) != ("natural", 1):
        raise DiagnosticProducerDependencyBlocked("precision-select identity drift")
    utilities = tuple(value for _deal, value in precision_select.deal_action_utility)
    if len(utilities) != len(precision_select.deal_action_utility) \
            or len(utilities) < 2:
        raise DiagnosticProducerDependencyBlocked("precision-select action utility population missing")
    if isinstance(frozen_audit_deal_count, bool) \
            or not isinstance(frozen_audit_deal_count, int) \
            or frozen_audit_deal_count < 2:
        raise DiagnosticProducerDependencyBlocked("frozen audit deal count drift")
    mean = Fraction(sum(utilities), len(utilities))
    variance = sum((Fraction(value) - mean) ** 2 for value in utilities) \
        / (len(utilities) - 1)
    standard_deviation = math.sqrt(float(variance))
    required_fraction = Fraction((Z_ALPHA_PPM + Z_POWER_PPM) ** 2,
                                 1_000_000 ** 2) \
        * variance / (DELTA_MICROLEVELS ** 2)
    required = (required_fraction.numerator + required_fraction.denominator - 1) \
        // required_fraction.denominator
    if required < 1:
        raise DiagnosticProducerDependencyBlocked(
            "precision-select utility variance yields an invalid zero-sized power requirement")
    receipt = ModelSelectorPowerReceiptV2(
        precision_select_population_sha256=precision_select.population_sha256,
        deal_utilities_microlevels=utilities,
        precision_select_deal_count=len(utilities),
        frozen_audit_deal_count=frozen_audit_deal_count,
        s_model_microlevels=standard_deviation, n_required=required,
        stop_underpowered=required > frozen_audit_deal_count,
        replica_count=REPLICA_COUNT, estimand_identity=ESTIMAND_IDENTITY)
    receipt.validate()
    return receipt


__all__ = [
    "DiagnosticProducerDependencyBlocked", "MISSING_CURVE_TELEMETRY",
    "MISSING_OPTIMIZER_TELEMETRY", "MISSING_STABILITY_TELEMETRY",
    "NestedCurveInputV2", "OptimizerCanaryInputV2",
    "produce_model_selector_power_v2", "produce_nested_curve_v2",
    "produce_optimizer_canary_v2", "produce_primary_stability_v2",
    "build_model_selector_power_v2", "build_nested_curve_v2",
    "build_optimizer_canary_v2", "build_primary_stability_v2",
]

# Descriptive aliases mirror the terminology used by the Section 9 design.
build_optimizer_canary_v2 = produce_optimizer_canary_v2
build_nested_curve_v2 = produce_nested_curve_v2
build_primary_stability_v2 = produce_primary_stability_v2
build_model_selector_power_v2 = produce_model_selector_power_v2
