"""Closed, restart-safe adapters for the Value-Afterstate V2 late stages.

Factories retain only ``freeze`` and ``repo``.  Inputs are reopened from the
supervisor's authenticated evidence root when invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_audit_attempt import reopen_audit_attempt_bytes
from .world_afterstate_v2_artifacts import reopen_continuation_manifest
from .world_afterstate_v2_diagnostic_producers import (
    ModelSelectorPowerReceiptV2, produce_model_selector_power_v2,
)
from .world_afterstate_v2_evaluation import EvaluationResultV2, evaluate_v2
from .world_afterstate_v2_inference import (
    build_inference_root_v2, predict_root_v2, predict_roots_v2,
    prediction_population_manifest_v2,
    validate_prediction_population_manifest_v2,
)
from .world_afterstate_v2_capacity_economics import (
    reopen_capacity_evidence_v2_bytes,
)
from .world_afterstate_v2_label_controller import (
    build_continuation_population_v2, reopen_label_stage_receipt,
)
from .world_afterstate_v2_metrics import build_natural_fit_prior
from .world_afterstate_v2_population_artifacts import reopen_population_manifest
from .world_afterstate_v2_population_controller import reopen_population_receipt_v2
from .world_afterstate_v2_prediction_artifacts import (
    prediction_population_manifest_path, publish_prediction_population_manifest,
    reopen_prediction_population_manifest,
)
from .world_afterstate_v2_protocol import TIER_SPECS
from .world_afterstate_v2_result import precision_select_learning_passed
from .world_afterstate_v2_terminal_controller import (
    COHORT_LABELS, DOSE_LABELS, EARLY_DECISIONS, EarlyTerminalInputPathsV2,
    TerminalInputPathsV2, build_early_route_evidence_bytes, run_terminal_v2,
    verify_terminal_artifact_v2,
)
from .world_afterstate_v2_training_controller import (
    CohortTrainingBuildV2, reopen_cohort_build, validate_cohort_manifest,
)
from .world_afterstate_v2_training import model_state_sha256
from .world_afterstate_v2_training_stage_inputs import build_training_stage_inputs


ABI = "world-afterstate-v2-stage-adapter-supervisor-shards-v1"
PRECISION_STAGE = "precision-select-power"
AUDIT_STAGE = "audit-attempt"
TERMINAL_STAGE = "terminal"
RECONSTRUCTION_STAGE = "reconstruction"
PRECISION_LABEL_ROOT = "precision-select-continuations"
AUDIT_LABEL_ROOT = "audit-continuations"
_WORK_PREFIX = (
    "population", "p0-labels-gates", "optimizer-canary", "fit-select-labels",
    "block-1-natural", "nested-curve", "block-1-controls", "block-2-natural",
    "block-2-controls")
_COHORTS = (
    ("natural:block-1", "block-1-natural", "natural", 1),
    ("action-association-permutation:block-1", "block-1-controls", "action-association-permutation", 1),
    ("label-permutation:block-1", "block-1-controls", "label-permutation", 1),
    ("complete-world-shuffle:block-1", "block-1-controls", "complete-world-shuffle", 1),
    ("natural:block-2", "block-2-natural", "natural", 2),
    ("complete-world-shuffle:block-2", "block-2-controls", "complete-world-shuffle", 2),
)


class LateStageAdapterUnavailable(ValueError):
    """A late-stage input, immutable shard, or reviewed dependency was refused."""


@dataclass(frozen=True)
class PrecisionSelectInputV2:
    """Compatibility-only typed witness for direct unit tests.

    Production factories never consume this object; they reopen every field
    from ``freeze`` and the supervisor.  Keeping the small witness avoids
    changing the public test ABI while the closed factory evolves.
    """
    prediction_manifests: tuple[tuple[str, Mapping[str, Any]], ...]
    outcomes: tuple[Any, ...]
    prior: Any
    frozen_audit_deal_count: int
    precision_materials: tuple[Any, ...] = ()
    label_root: Path | None = None
    workers: int = 1
    deadline_monotonic_ns: int = 2**63 - 1
    population_tier: str | None = None

    def validate(self) -> None:
        expected = ("natural:block-1", "action-association-permutation:block-1",
                    "label-permutation:block-1", "complete-world-shuffle:block-1",
                    "natural:block-2", "complete-world-shuffle:block-2")
        if tuple(label for label, _ in self.prediction_manifests) != expected:
            raise LateStageAdapterUnavailable("precision prediction cohort population drift")
        for label, manifest in self.prediction_manifests:
            if type(manifest) is not dict:
                raise LateStageAdapterUnavailable(f"precision manifest {label} drift")
            try:
                validate_prediction_population_manifest_v2(manifest)
            except Exception as exc:
                raise LateStageAdapterUnavailable(f"precision manifest {label} refused") from exc
            if manifest.get("split") != "select":
                raise LateStageAdapterUnavailable(f"precision manifest {label} split drift")
        if self.population_tier is not None:
            precision, audit = tier_counts(self.population_tier)
            if len(self.precision_materials) != precision or self.frozen_audit_deal_count != audit:
                raise LateStageAdapterUnavailable("frozen tier population drift")
        if not isinstance(self.label_root, Path) or self.label_root.is_symlink() \
                or not isinstance(self.precision_materials, tuple) or not self.precision_materials:
            raise LateStageAdapterUnavailable("precision label population missing")


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise LateStageAdapterUnavailable(f"{label} drift")
    return value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LateStageAdapterUnavailable(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise LateStageAdapterUnavailable(f"{label} canonical bytes drift")
    return value


def tier_counts(freeze_or_tier: Any) -> tuple[int, int]:
    """Return exact precision/audit counts; this implementation is D256-only."""
    tier = freeze_or_tier if isinstance(freeze_or_tier, str) else getattr(freeze_or_tier, "population_tier", None)
    spec = next((item for item in TIER_SPECS if item.name == tier), None)
    if spec is None or spec.name != "D256":
        raise LateStageAdapterUnavailable("only frozen D256 is supported")
    try:
        spec.validate()
    except Exception as exc:
        raise LateStageAdapterUnavailable("frozen tier count drift") from exc
    if (spec.select, spec.audit) != (48, 48):
        raise LateStageAdapterUnavailable("frozen D256 count drift")
    return 24, 48


def _identity(supervisor: Any, freeze: Any, repo: Path) -> Path:
    if freeze is None or not isinstance(repo, Path) or repo.is_symlink() or not repo.is_dir():
        raise LateStageAdapterUnavailable("late adapter binding unavailable")
    root = getattr(supervisor, "root", None)
    if not isinstance(root, Path) or root.is_symlink() or root != Path(getattr(freeze, "evidence_root", "")):
        raise LateStageAdapterUnavailable("supervisor root binding drift")
    try:
        _digest(freeze.sha256(), "freeze SHA-256")
        _digest(supervisor.admission.sha256(), "admission SHA-256")
    except Exception as exc:
        raise LateStageAdapterUnavailable("supervisor identity unavailable") from exc
    tier_counts(freeze)
    return root


def _prefix(supervisor: Any, stage: str) -> None:
    completed = tuple(getattr(getattr(supervisor, "state", None), "completed_stages", ()))
    expected = _WORK_PREFIX if stage == PRECISION_STAGE else (*_WORK_PREFIX, PRECISION_STAGE)
    if stage in (PRECISION_STAGE, AUDIT_STAGE) and completed != expected:
        raise LateStageAdapterUnavailable("completed stage prefix drift")


def _emit(supervisor: Any, stage: str, completed: int, total: int) -> None:
    emitter = getattr(supervisor, "emit_progress", None)
    if callable(emitter):
        try:
            emitter(stage=stage, completed=completed, total=total, force=True)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise LateStageAdapterUnavailable("late progress publication refused") from exc


def _label_resources(supervisor: Any, freeze: Any, repo: Path) -> tuple[int, int]:
    """Read the frozen label resource arm; no caller override is accepted."""
    bindings = [row for row in getattr(freeze, "artifact_bindings", ())
                if type(row) is tuple and len(row) == 3 and row[0] == "config"]
    if len(bindings) != 1:
        raise LateStageAdapterUnavailable("late config artifact binding missing")
    _, relative, expected = bindings[0]
    if type(relative) is not str or Path(relative).is_absolute() \
            or Path(relative).as_posix() != relative:
        raise LateStageAdapterUnavailable("late config artifact path drift")
    path = repo / relative
    try:
        value = _strict_json(stable_read_bytes(path), "late config artifact")
    except Exception as exc:
        raise LateStageAdapterUnavailable("late config artifact refused") from exc
    if _sha(stable_read_bytes(path)) != _digest(expected, "config artifact SHA-256"):
        raise LateStageAdapterUnavailable("late config artifact digest drift")
    if value.get("schema") != "world-afterstate-v2-early-stage-adapters-input-v2":
        raise LateStageAdapterUnavailable("late config artifact schema drift")
    workers, seconds = value.get("label_workers"), value.get("label_deadline_seconds")
    if (isinstance(workers, bool) or not isinstance(workers, int) or workers < 1
            or isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1
            or seconds > getattr(freeze, "deadline_seconds", 0)):
        raise LateStageAdapterUnavailable("late label resource binding drift")
    selected_workers = _selected_capacity_variant(
        supervisor, freeze, repo, "continuation-mechanics",
        (1, 2, 4, 8, 12, 16, 32))
    if workers != selected_workers:
        raise LateStageAdapterUnavailable("late label worker/capacity binding drift")
    return workers, seconds


def _capacity_receipt(supervisor: Any, freeze: Any, repo: Path) -> Any:
    """Reopen the exact freeze-bound capacity receipt once per adapter call."""
    bindings = [row for row in getattr(freeze, "artifact_bindings", ())
                if type(row) is tuple and len(row) == 3 and row[0] == "capacity"]
    if len(bindings) != 1:
        raise LateStageAdapterUnavailable(
            "late capacity artifact binding missing or duplicated")
    _, relative, expected = bindings[0]
    if type(relative) is not str or Path(relative).is_absolute() \
            or Path(relative).as_posix() != relative \
            or any(part in ("", ".", "..") for part in Path(relative).parts):
        raise LateStageAdapterUnavailable("late capacity artifact path drift")
    _digest(expected, "capacity artifact SHA-256")
    if expected != getattr(freeze, "capacity_sha256", None):
        raise LateStageAdapterUnavailable("late capacity freeze binding drift")
    # Admission verifies root first and repository second.  Permit either
    # canonical location here, but reject an ambiguous pair with differing
    # bytes instead of choosing one silently.
    candidates = tuple(path for path in (
        Path(getattr(supervisor, "root", "")) / relative,
        repo / relative,
    ) if path.is_file() and not path.is_symlink())
    if not candidates:
        raise LateStageAdapterUnavailable("late capacity artifact missing")
    try:
        raws = tuple(stable_read_bytes(path) for path in candidates)
    except Exception as exc:
        raise LateStageAdapterUnavailable("late capacity artifact refused") from exc
    if any(raw != raws[0] for raw in raws) or _sha(raws[0]) != expected:
        raise LateStageAdapterUnavailable("late capacity artifact digest drift")
    try:
        receipt = reopen_capacity_evidence_v2_bytes(raws[0])
        receipt.validate()
    except Exception as exc:
        raise LateStageAdapterUnavailable("late capacity receipt reopen refused") from exc
    return receipt


def _capacity_binding(supervisor: Any, freeze: Any, repo: Path) -> tuple[Path, str, Any]:
    """Return the one exact capacity path, digest, and typed receipt."""
    bindings = [row for row in getattr(freeze, "artifact_bindings", ())
                if type(row) is tuple and len(row) == 3 and row[0] == "capacity"]
    if len(bindings) != 1:
        raise LateStageAdapterUnavailable(
            "late capacity artifact binding missing or duplicated")
    _label, relative, expected = bindings[0]
    if type(relative) is not str or Path(relative).is_absolute() \
            or Path(relative).as_posix() != relative \
            or any(part in ("", ".", "..") for part in Path(relative).parts):
        raise LateStageAdapterUnavailable("late capacity artifact path drift")
    _digest(expected, "capacity artifact SHA-256")
    candidates = tuple(path for path in (
        Path(getattr(supervisor, "root", "")) / relative,
        repo / relative,
    ) if path.is_file() and not path.is_symlink())
    if not candidates:
        raise LateStageAdapterUnavailable("late capacity artifact missing")
    try:
        raws = tuple(stable_read_bytes(path) for path in candidates)
    except Exception as exc:
        raise LateStageAdapterUnavailable("late capacity artifact refused") from exc
    if any(raw != raws[0] for raw in raws) or _sha(raws[0]) != expected:
        raise LateStageAdapterUnavailable("late capacity artifact digest drift")
    try:
        receipt = reopen_capacity_evidence_v2_bytes(raws[0])
        receipt.validate()
    except Exception as exc:
        raise LateStageAdapterUnavailable("late capacity receipt reopen refused") from exc
    return candidates[0], expected, receipt


def _selected_capacity_variant(supervisor: Any, freeze: Any, repo: Path,
                               stage: str, allowed: tuple[int, ...]) -> int:
    receipt = _capacity_receipt(supervisor, freeze, repo)
    selected = tuple(arm for arm in receipt.selected_arms
                     if getattr(arm, "stage", None) == stage)
    if len(selected) != 1:
        raise LateStageAdapterUnavailable(
            f"late {stage} selected arm missing or duplicated")
    arm = selected[0]
    try:
        arm.validate()
    except Exception as exc:
        raise LateStageAdapterUnavailable(
            f"late {stage} selected arm refused") from exc
    value = getattr(arm, "variant", None)
    if isinstance(value, bool) or not isinstance(value, int) \
            or value not in allowed:
        raise LateStageAdapterUnavailable(f"late {stage} arm drift")
    return value


def _inference_batch_cap(supervisor: Any, freeze: Any, repo: Path) -> int:
    """Reopen the exact freeze-bound capacity receipt and select its arm."""
    return _selected_capacity_variant(
        supervisor, freeze, repo, "inference-batch", (32, 64, 128, 256))


def _reconstruction_workers(supervisor: Any, freeze: Any, repo: Path) -> int:
    """Select the frozen reconstruction worker arm."""
    return _selected_capacity_variant(
        supervisor, freeze, repo, "reconstruction", (1, 4, 8, 16, 32))


def _deadline(supervisor: Any, freeze: Any, seconds: int) -> int:
    try:
        now = supervisor.clock() if callable(getattr(supervisor, "clock", None)) else 0
        started = int(getattr(supervisor, "_started", now))
        return min(now + seconds * 1_000_000_000,
                   started + int(freeze.deadline_seconds) * 1_000_000_000
                   - 60 * 1_000_000_000)
    except (AttributeError, TypeError, ValueError) as exc:
        raise LateStageAdapterUnavailable("late deadline binding unavailable") from exc


def _register(supervisor: Any, stage: str, shard: str, raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise LateStageAdapterUnavailable("empty late stage shard")
    try:
        existing = tuple(supervisor.verified_shards(stage))
        if shard in existing:
            path = supervisor.root / "shards" / stage / f"{shard}.bin"
            if stable_read_bytes(path) != raw:
                raise LateStageAdapterUnavailable("immutable late shard replacement refused")
        else:
            supervisor.register_verified_shard(stage, shard, raw)
        return _strict_json(raw, f"{stage} {shard}")
    except LateStageAdapterUnavailable:
        raise
    except Exception as exc:
        raise LateStageAdapterUnavailable(f"{stage} {shard} publication refused") from exc


def _receipt(supervisor: Any, stage: str, payload: Mapping[str, Any], *, shards: tuple[str, ...]) -> dict[str, Any]:
    raw = canonical_json_bytes(dict(payload))
    existing = tuple(supervisor.verified_shards(stage))
    if existing and (not set(existing).issubset(set(shards))):
        raise LateStageAdapterUnavailable(f"{stage} shard population drift")
    return _register(supervisor, stage, "receipt", raw)


def _population(supervisor: Any, freeze: Any) -> tuple[Any, ...]:
    path = supervisor.root / "shards" / "population" / "receipt.bin"
    if "receipt" not in tuple(supervisor.verified_shards("population")):
        raise LateStageAdapterUnavailable("population receipt is not verified")
    try:
        receipt = reopen_population_receipt_v2(_strict_json(stable_read_bytes(path), "population receipt"))
        if (receipt.freeze_sha256, receipt.admission_sha256) != (freeze.sha256(), supervisor.admission.sha256()):
            raise ValueError("population receipt identity")
        return tuple(reopen_population_manifest(
            supervisor.root, expected_freeze_sha256=freeze.sha256(),
            expected_population_namespace_sha256=receipt.population_namespace_sha256,
            expected_population_sha256=receipt.population_sha256,
            expected_tier="D256", expected_split="mixed", expected_source=None))
    except Exception as exc:
        raise LateStageAdapterUnavailable("frozen population reopen refused") from exc


def _materials(supervisor: Any, freeze: Any, split: str) -> tuple[Any, ...]:
    values = tuple(item for item in _population(supervisor, freeze) if item.state.split == split)
    if split == "select":
        precision_count, _ = tier_counts(freeze)
        epoch = tuple(item for item in values if item.state.select_subfold == "epoch-select")
        precision = tuple(item for item in values if item.state.select_subfold == "precision-select")
        if len(values) != 48 or len(epoch) != precision_count or len(precision) != precision_count:
            raise LateStageAdapterUnavailable("select population is not 24/24 D256")
        return precision
    _, audit_count = tier_counts(freeze)
    if len(values) != audit_count:
        raise LateStageAdapterUnavailable("audit population is not 48 D256 deals")
    return values


def _cohort_builds(supervisor: Any, freeze: Any) -> tuple[tuple[str, tuple[Any, ...]], ...]:
    result = []
    completed = tuple(getattr(getattr(supervisor, "state", None), "completed_stages", ()))
    for label, stage, name, block in _COHORTS:
        if stage not in completed:
            raise LateStageAdapterUnavailable(f"{label} stage is not complete")
        try:
            receipt = _strict_json(stable_read_bytes(supervisor.root / "shards" / stage / "receipt.bin"), f"{stage} receipt")
            member = next(item for item in receipt["cohorts"] if item.get("name") == name)
            manifest = member["manifest"]
            validate_cohort_manifest(manifest)
            if (manifest["cohort_name"], manifest["seed_block"], manifest["freeze_sha256"]) != (name, block, freeze.sha256()):
                raise ValueError("cohort identity")
            names = tuple(member["checkpoint_shards"])
            expected = tuple(f"checkpoint-{name}-{i}" for i in range(4))
            if names != expected:
                raise ValueError("checkpoint shard population")
            verified = tuple(supervisor.verified_shards(stage))
            all_names = tuple(item_name for row in receipt["cohorts"]
                              for item_name in row["checkpoint_shards"])
            if set(verified) != {*all_names, "receipt"} or any(item not in verified for item in names):
                raise ValueError("checkpoint shard is not verified")
            all_raws = tuple(stable_read_bytes(
                supervisor.root / "shards" / stage / f"{item}.bin")
                for item in all_names)
            if tuple(_sha(item) for item in all_raws) != tuple(
                    receipt.get("checkpoint_sha256s", ())):
                raise ValueError("checkpoint receipt digest")
            selected_raws = tuple(stable_read_bytes(
                supervisor.root / "shards" / stage / f"{item}.bin") for item in names)
            build = CohortTrainingBuildV2(manifest, selected_raws)
            models, _ = reopen_cohort_build(build)
        except Exception as exc:
            raise LateStageAdapterUnavailable(f"{label} checkpoint/build reopen refused") from exc
        result.append((label, models))
    return tuple(result)


def _prediction(supervisor: Any, roots: Sequence[Any], models: Sequence[Any], *, split: str,
                control: str, block: int, subfold: str | None,
                inference_batch_cap: int = 256) -> tuple[dict[str, Any], Path]:
    path = prediction_population_manifest_path(
        supervisor.root, control, block, split, subfold)
    if path.exists() or path.is_symlink():
        try:
            reopened = reopen_prediction_population_manifest(
                supervisor.root, control_name=control, seed_block=block,
                split=split, subfold=subfold)
            expected_bindings = [
                {**root.target_free_body(), "root_sha256": root.root_sha256}
                for root in sorted(roots, key=lambda item: item.root_sha256)]
            observed_models: dict[int, set[str]] = {
                index: set() for index in range(len(models))}
            for row in reopened["predictions"]:
                member = row["member_index"]
                if member not in observed_models:
                    raise ValueError("prediction member population")
                observed_models[member].add(row["model_state_sha256"])
            expected_models = tuple(model_state_sha256(model) for model in models)
            if (reopened["root_bindings"] != expected_bindings
                    or len(models) != 4
                    or tuple(next(iter(observed_models[index]))
                             if len(observed_models[index]) == 1 else None
                             for index in range(len(models))) != expected_models):
                raise ValueError("prediction resume binding")
            return reopened, path
        except Exception as exc:
            raise LateStageAdapterUnavailable(
                f"{control} block-{block} {split} prediction resume refused") from exc
    rows = tuple(row for member, model in enumerate(models) for row in
                 predict_roots_v2(
                     model, roots, seed_block=block, member_index=member,
                     control_name=control,
                     inference_batch_cap=inference_batch_cap))
    manifest = prediction_population_manifest_v2(roots, rows, split=split, control_name=control, seed_block=block)
    try:
        artifact = publish_prediction_population_manifest(supervisor.root, manifest,
            control_name=control, seed_block=block, split=split, subfold=subfold)
        if artifact.sha256 != _sha(stable_read_bytes(path)):
            raise ValueError("prediction artifact digest")
        reopened = reopen_prediction_population_manifest(supervisor.root, control_name=control,
            seed_block=block, split=split, subfold=subfold)
        if reopened != manifest:
            raise ValueError("prediction manifest reopen")
        return manifest, path
    except Exception as exc:
        raise LateStageAdapterUnavailable(f"{control} block-{block} {split} prediction publication refused") from exc


def evaluate_precision_select_v2(prediction_manifest: Mapping[str, Any], outcomes: Sequence[Any], prior: Any,
                                *, frozen_audit_deal_count: int) -> tuple[EvaluationResultV2, ModelSelectorPowerReceiptV2]:
    try:
        if type(prediction_manifest) is not dict:
            raise ValueError("precision prediction manifest drift")
        validate_prediction_population_manifest_v2(prediction_manifest)
        if (prediction_manifest["split"], prediction_manifest["control_name"], prediction_manifest["seed_block"]) != ("select", "natural", 1):
            raise ValueError("precision natural identity drift")
        result = evaluate_v2(prediction_manifest, outcomes, prior, control_name="natural", seed_block=1)
        power = produce_model_selector_power_v2(result, frozen_audit_deal_count=frozen_audit_deal_count)
        result.validate(); power.validate()
        return result, power
    except Exception as exc:
        raise LateStageAdapterUnavailable("precision-select evaluation/power refused") from exc


@dataclass(frozen=True)
class PrecisionSelectPowerAdapterV2:
    freeze: Any
    repo: Path | None = None
    stage: str = PRECISION_STAGE
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self): return evaluate_precision_select_v2

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        # Legacy direct-construction seam retained for existing unit tests;
        # production_stage_adapter never takes this branch.
        if isinstance(self.freeze, PrecisionSelectInputV2) and self.repo is None:
            inputs = self.freeze
            inputs.validate()
            _emit(supervisor, self.stage, 0, 1)
            natural = dict(inputs.prediction_manifests)["natural:block-1"]
            receipt = build_continuation_population_v2(
                inputs.label_root, inputs.precision_materials, split="fit-select",
                workers=inputs.workers, deadline_monotonic_ns=inputs.deadline_monotonic_ns)
            outcomes = tuple(row for bundle in reopen_continuation_manifest(
                inputs.label_root, inputs.precision_materials)
                             for row in bundle.candidates)
            result, power = evaluate_precision_select_v2(
                natural, outcomes, inputs.prior,
                frozen_audit_deal_count=inputs.frozen_audit_deal_count)
            _emit(supervisor, self.stage, 1, 1)
            return result, power
        del verified_shards
        _identity(supervisor, self.freeze, self.repo); _prefix(supervisor, self.stage)
        precision_count, audit_count = tier_counts(self.freeze)
        inference_batch_cap = _inference_batch_cap(supervisor, self.freeze, self.repo)
        _emit(supervisor, self.stage, 0, 1)
        materials = _materials(supervisor, self.freeze, "select")
        roots = tuple(build_inference_root_v2(item) for item in materials)
        builds = _cohort_builds(supervisor, self.freeze)
        manifests = []
        for label, models in builds:
            _, _, control, block = next(row for row in _COHORTS if row[0] == label)
            manifests.append((label, *_prediction(
                supervisor, roots, models, split="select", control=control,
                block=block, subfold="precision-select",
                inference_batch_cap=inference_batch_cap)))
        if len(manifests) != 6:
            raise LateStageAdapterUnavailable("precision prediction population incomplete")
        label_root = supervisor.root / PRECISION_LABEL_ROOT
        workers, seconds = _label_resources(supervisor, self.freeze, self.repo)
        label_receipt = build_continuation_population_v2(
            label_root, materials, split="fit-select", workers=workers,
            deadline_monotonic_ns=_deadline(supervisor, self.freeze, seconds))
        outcomes = tuple(row for bundle in reopen_continuation_manifest(label_root, materials) for row in bundle.candidates)
        try:
            training_inputs = build_training_stage_inputs(self.freeze, self.repo, supervisor=supervisor)
            prior = build_natural_fit_prior(training_inputs.training_examples)
            result, power = evaluate_precision_select_v2(dict(manifests)["natural:block-1"], outcomes, prior, frozen_audit_deal_count=audit_count)
        except Exception as exc:
            raise LateStageAdapterUnavailable("precision target evaluation refused") from exc
        prior_payload, result_payload, power_payload = prior.payload(), result.payload(), power.payload()
        _register(supervisor, self.stage, "prior", canonical_json_bytes(prior_payload))
        _register(supervisor, self.stage, "result", canonical_json_bytes(result_payload))
        _register(supervisor, self.stage, "power", canonical_json_bytes(power_payload))
        stage_payload = {"schema": "world-afterstate-v2-precision-select-power-v2", "freeze_sha256": self.freeze.sha256(), "admission_sha256": supervisor.admission.sha256(),
                         "prediction_manifest_sha256s": [[label, m["manifest_sha256"]] for label, m, _ in manifests], "label_manifest_sha256": label_receipt.manifest_sha256,
                         "prior_sha256": _sha(canonical_json_bytes(prior_payload)), "result_sha256": _sha(canonical_json_bytes(result_payload)), "power_sha256": _sha(canonical_json_bytes(power_payload)),
                         "audit_deal_count": audit_count, "precision_deal_count": precision_count}
        sealed = _receipt(supervisor, self.stage, stage_payload, shards=("prior", "result", "power", "receipt"))
        route = ("SELECT_NONE_PREAUDIT_LEARNING"
                 if not precision_select_learning_passed(result)
                 else "STOP_UNDERPOWERED"
                 if getattr(power, "stop_underpowered", False) else None)
        if route is not None:
            try: supervisor.terminal(route)
            except Exception as exc: raise LateStageAdapterUnavailable(
                "precision terminal route publication refused") from exc
        _emit(supervisor, self.stage, 1, 1)
        return sealed


def publish_audit_attempt(supervisor: Any) -> dict[str, Any]:
    try:
        root, freeze, admission = supervisor.root, supervisor.freeze, supervisor.admission
        path = root / "audit-attempt.json"
        if not isinstance(root, Path) or path.is_symlink() or not path.is_file(): raise ValueError("marker missing")
        value = reopen_audit_attempt_bytes(stable_read_bytes(path), expected_freeze_sha256=freeze.sha256(), expected_admission_sha256=admission.sha256())
        if value["published_before_audit_labels"] is not True: raise ValueError("marker ordering")
        return value
    except Exception as exc:
        raise LateStageAdapterUnavailable("durable audit marker refused") from exc


@dataclass(frozen=True)
class AuditAttemptAdapterV2:
    freeze: Any
    repo: Path | None = None
    stage: str = AUDIT_STAGE
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self): return publish_audit_attempt

    def prepare_stage_payload(self, supervisor: Any) -> dict[str, str]:
        """Seal target-free evidence before the one-shot audit marker.

        This method is called by the closed execution controller immediately
        before ``run_stage``.  It may inspect only already verified upstream
        receipts and path occupancy; audit materials and labels remain
        unopened until ``__call__`` runs after the durable marker exists.
        """
        if self.repo is None:
            raise LateStageAdapterUnavailable(
                "audit preflight producer requires production binding")
        _identity(supervisor, self.freeze, self.repo)
        _prefix(supervisor, self.stage)
        from .world_afterstate_v2_execution import (
            AUDIT_PREFLIGHT_RELATIVE, AUDIT_PREFLIGHT_SCHEMA,
            AUDIT_PREFLIGHT_STAGES, AUDIT_UNOPENED_PATHS,
        )
        path = supervisor.root / AUDIT_PREFLIGHT_RELATIVE
        if path.exists() or path.is_symlink():
            try:
                value = _strict_json(
                    stable_read_bytes(path), "audit preflight")
            except Exception as exc:
                raise LateStageAdapterUnavailable(
                    "sealed audit preflight reopen refused") from exc
            digest = value.get("preflight_sha256")
            _digest(digest, "audit preflight SHA-256")
            return {"preflight_relative_path": AUDIT_PREFLIGHT_RELATIVE,
                    "preflight_sha256": digest}
        for relative in AUDIT_UNOPENED_PATHS:
            target = supervisor.root / relative
            if target.exists() or target.is_symlink():
                raise LateStageAdapterUnavailable(
                    "audit path opened before deterministic preflight")
        receipt_rows = []
        for stage in AUDIT_PREFLIGHT_STAGES:
            _value, _receipt_path, receipt_sha = _upstream_receipt(
                supervisor, stage)
            receipt_rows.append([stage, receipt_sha])
        body = {
            "schema": AUDIT_PREFLIGHT_SCHEMA,
            "freeze_sha256": self.freeze.sha256(),
            "admission_sha256": supervisor.admission.sha256(),
            "completed_stages": list(AUDIT_PREFLIGHT_STAGES),
            "upstream_receipt_sha256s": receipt_rows,
            "audit_paths_absent": list(AUDIT_UNOPENED_PATHS),
        }
        value = {**body, "preflight_sha256": _sha(
            canonical_json_bytes(body))}
        try:
            publish_exclusive_bytes(path, canonical_json_bytes(value))
        except Exception as exc:
            raise LateStageAdapterUnavailable(
                "audit preflight publication refused") from exc
        return {"preflight_relative_path": AUDIT_PREFLIGHT_RELATIVE,
                "preflight_sha256": value["preflight_sha256"]}

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        if self.repo is None and not hasattr(self.freeze, "sha256"):
            # Legacy direct-construction seam: marker verification remains the
            # first operation, so labels cannot run without its durable bytes.
            marker = publish_audit_attempt(supervisor)
            inputs = self.freeze
            try:
                receipt = build_continuation_population_v2(
                    inputs.audit_label_root, inputs.audit_materials, split="audit",
                    workers=inputs.workers,
                    deadline_monotonic_ns=inputs.deadline_monotonic_ns)
                return _receipt(supervisor, self.stage, {
                    "schema": "world-afterstate-v2-audit-attempt-receipt-v1",
                    "audit_attempt_sha256": _sha(canonical_json_bytes(marker)),
                    "label_receipt": receipt.payload()}, shards=("receipt",))
            except LateStageAdapterUnavailable:
                raise
            except Exception as exc:
                raise LateStageAdapterUnavailable("audit label publication refused") from exc
        del verified_shards
        _identity(supervisor, self.freeze, self.repo); _prefix(supervisor, self.stage)
        inference_batch_cap = _inference_batch_cap(supervisor, self.freeze, self.repo)
        marker = publish_audit_attempt(supervisor); _emit(supervisor, self.stage, 0, 1)
        materials = _materials(supervisor, self.freeze, "audit")
        roots = tuple(build_inference_root_v2(item) for item in materials)
        builds = _cohort_builds(supervisor, self.freeze); predictions = []
        for label, models in builds:
            _, _, control, block = next(row for row in _COHORTS if row[0] == label)
            predictions.append((label, *_prediction(
                supervisor, roots, models, split="audit", control=control,
                block=block, subfold=None,
                inference_batch_cap=inference_batch_cap)))
        if len(predictions) != 6: raise LateStageAdapterUnavailable("audit prediction population incomplete")
        workers, seconds = _label_resources(supervisor, self.freeze, self.repo)
        receipt = build_continuation_population_v2(
            supervisor.root / AUDIT_LABEL_ROOT, materials, split="audit",
            workers=workers,
            deadline_monotonic_ns=_deadline(supervisor, self.freeze, seconds))
        reopened = reopen_label_stage_receipt(receipt.payload())
        index_path, index_sha = _published_terminal_inputs(
            supervisor, self.freeze, self.repo, predictions)
        payload = {"schema": "world-afterstate-v2-audit-attempt-receipt-v2", "freeze_sha256": self.freeze.sha256(), "admission_sha256": supervisor.admission.sha256(), "audit_attempt_sha256": marker["attempt_sha256"],
                   "prediction_manifest_sha256s": [[label, m["manifest_sha256"]] for label, m, _ in predictions], "label_manifest_sha256": reopened.manifest_sha256, "audit_deal_count": len(materials),
                   "terminal_inputs_path": index_path.relative_to(supervisor.root).as_posix(), "terminal_inputs_sha256": index_sha}
        sealed = _receipt(supervisor, self.stage, payload, shards=("receipt",)); _emit(supervisor, self.stage, 1, 1); return sealed


def _path(root: Path, relative: str, label: str) -> Path:
    if type(relative) is not str or Path(relative).is_absolute() or Path(relative).as_posix() != relative or any(part in ("", ".", "..") for part in Path(relative).parts):
        raise LateStageAdapterUnavailable(f"{label} path drift")
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise LateStageAdapterUnavailable(f"{label} symlink ancestor")
    if not path.is_file(): raise LateStageAdapterUnavailable(f"{label} missing")
    return path


def _directory(root: Path, relative: str, label: str) -> Path:
    if type(relative) is not str or Path(relative).is_absolute() \
            or Path(relative).as_posix() != relative or any(
                part in ("", ".", "..") for part in Path(relative).parts):
        raise LateStageAdapterUnavailable(f"{label} path drift")
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise LateStageAdapterUnavailable(f"{label} symlink ancestor")
    if not path.is_dir(): raise LateStageAdapterUnavailable(f"{label} missing")
    return path


TERMINAL_INPUTS_SCHEMA = "world-afterstate-v2-terminal-inputs-v2"
EARLY_ROUTE_RELATIVE = "early-route.json"


def _terminal_pending_event(supervisor: Any, expected_route: str) \
        -> dict[str, Any]:
    """Reopen the one durable event that selected an early terminal route."""
    events = supervisor.root / "events"
    if events.is_symlink() or not events.is_dir():
        raise LateStageAdapterUnavailable("early terminal event directory missing")
    rows = []
    for path in sorted(events.glob("*.json")):
        try:
            value = _strict_json(stable_read_bytes(path), "early terminal event")
        except Exception as exc:
            raise LateStageAdapterUnavailable(
                "early terminal event reopen refused") from exc
        if value.get("status") == "terminal-pending":
            rows.append(value)
    if len(rows) != 1:
        raise LateStageAdapterUnavailable(
            "early terminal pending event population drift")
    event = rows[0]
    payload = event.get("payload")
    body = {key: value for key, value in event.items()
            if key != "event_sha256"}
    if type(payload) is not dict or payload.get("route") != expected_route \
            or event.get("freeze_sha256") != supervisor.freeze.sha256() \
            or event.get("admission_sha256") != supervisor.admission.sha256() \
            or event.get("event_sha256") != _sha(canonical_json_bytes(body)):
        raise LateStageAdapterUnavailable("early terminal event binding drift")
    return event


def _early_source_stage(event: Mapping[str, Any], route: str) -> str:
    resource = event["payload"].get("resource_stage")
    if route == "REFUSE_RESOURCE_INCOMPLETE":
        if resource in {"population", "p0-labels-gates"}:
            return "p0"
        if resource in {
                "optimizer-canary", "fit-select-labels", "block-1-natural",
                "nested-curve", "block-1-controls", "block-2-natural",
                "block-2-controls"}:
            return "training"
        if resource in {"precision-select-power", "audit-attempt"}:
            # The audit has not opened.  A deadline at its entry boundary is
            # therefore sealed as the last fully reached pre-audit stage.
            return "precision-select"
        raise LateStageAdapterUnavailable(
            "early terminal resource-stage drift")
    if route in {"REFUSE_MECHANICS_OR_CONTROL",
                 "STOP_NO_REPRODUCIBLE_VALUE_LABEL",
                 "STOP_BELOW_WORTHWHILE_VALUE_FLOOR"}:
        return "p0"
    if route == "REFUSE_TRAINING_RECIPE":
        return "training"
    if route in {"STOP_UNDERPOWERED", "SELECT_NONE_PREAUDIT_LEARNING"}:
        return "precision-select"
    raise LateStageAdapterUnavailable("early terminal route is not pre-audit")


def _early_cohort_paths(supervisor: Any) -> tuple[tuple[str, Path], ...]:
    completed = set(getattr(supervisor.state, "completed_stages", ()))
    paths = []
    for label, stage, name, _block in _COHORTS:
        if stage not in completed:
            continue
        receipt, _path_value, _digest_value = _upstream_receipt(
            supervisor, stage)
        rows = [row for row in receipt.get("cohorts", ())
                if type(row) is dict and row.get("name") == name]
        if len(rows) != 1 or type(rows[0].get("cohort_manifest_path")) is not str:
            raise LateStageAdapterUnavailable(
                f"early cohort {label} artifact missing")
        paths.append((label, _path(
            supervisor.root, rows[0]["cohort_manifest_path"],
            f"early cohort {label} manifest")))
    return tuple(paths)


def _early_terminal_paths(supervisor: Any, freeze: Any,
                          repo: Path) -> EarlyTerminalInputPathsV2:
    """Bind the reached-stage receipts for a terminal route before audit."""
    root = _identity(supervisor, freeze, repo)
    state = getattr(supervisor, "state", None)
    route = getattr(state, "terminal_route", None)
    if route not in EARLY_DECISIONS or getattr(state, "audit_opened", False):
        raise LateStageAdapterUnavailable("early terminal state drift")
    event = _terminal_pending_event(supervisor, route)
    source_stage = _early_source_stage(event, route)
    completed = set(getattr(state, "completed_stages", ()))

    def shard(stage: str, name: str, label: str) -> Path | None:
        if stage not in completed:
            return None
        if name not in tuple(supervisor.verified_shards(stage)):
            raise LateStageAdapterUnavailable(f"{label} is not verified")
        return _path(root, f"shards/{stage}/{name}.bin", label)

    p0 = shard("p0-labels-gates", "receipt", "early P0 report")
    canary = shard("optimizer-canary", "receipt", "early optimizer canary")
    precision = shard(PRECISION_STAGE, "result",
                      "early precision-select result")
    power = shard(PRECISION_STAGE, "power", "early model-selector power")
    cohorts = _early_cohort_paths(supervisor)
    if source_stage == "p0" and any(value is not None for value in (
            canary, precision, power)) or source_stage == "p0" and cohorts:
        raise LateStageAdapterUnavailable("downstream evidence after P0 stop")
    if source_stage == "training" and any(value is not None for value in (
            precision, power)):
        raise LateStageAdapterUnavailable(
            "downstream evidence after training stop")
    if source_stage in {"training", "precision-select"} and p0 is None:
        raise LateStageAdapterUnavailable("early terminal P0 evidence missing")
    if source_stage == "precision-select" and canary is None:
        raise LateStageAdapterUnavailable(
            "early terminal optimizer evidence missing")

    route_raw = build_early_route_evidence_bytes(
        freeze_sha256=freeze.sha256(),
        admission_sha256=supervisor.admission.sha256(),
        source_stage=source_stage,
        resource_incomplete=route == "REFUSE_RESOURCE_INCOMPLETE")
    route_path = root / EARLY_ROUTE_RELATIVE
    try:
        if route_path.exists() or route_path.is_symlink():
            if route_path.is_symlink() or stable_read_bytes(route_path) != route_raw:
                raise ValueError("early route replacement")
        else:
            publish_exclusive_bytes(route_path, route_raw)
    except Exception as exc:
        raise LateStageAdapterUnavailable(
            "early route evidence publication refused") from exc
    inputs = EarlyTerminalInputPathsV2(
        freeze_sha256=freeze.sha256(),
        admission_sha256=supervisor.admission.sha256(),
        expected_route=route, route_evidence_path=route_path,
        p0_report_path=p0, optimizer_canary_path=canary,
        precision_select_result_path=precision,
        model_selector_power_path=power,
        cohort_manifest_paths=cohorts)
    inputs.validate_shape()
    return inputs


def _selected_terminal_paths(supervisor: Any, freeze: Any, repo: Path) \
        -> TerminalInputPathsV2 | EarlyTerminalInputPathsV2:
    state = getattr(supervisor, "state", None)
    if getattr(state, "terminal_route", None) in EARLY_DECISIONS \
            and not getattr(state, "audit_opened", False):
        return _early_terminal_paths(supervisor, freeze, repo)
    return _terminal_paths(supervisor, freeze, repo)


def _relative(root: Path, path: Path, label: str) -> tuple[str, str]:
    """Return a root-contained path and its stable byte digest."""
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise LateStageAdapterUnavailable(f"{label} escapes supervisor root") from exc
    if not relative or "\\" in relative or any(part in ("", ".", "..")
                                               for part in Path(relative).parts):
        raise LateStageAdapterUnavailable(f"{label} relative path drift")
    target = _path(root, relative, label)
    try:
        raw = stable_read_bytes(target)
    except Exception as exc:
        raise LateStageAdapterUnavailable(f"{label} stable read refused") from exc
    return relative, _sha(raw)


def _upstream_receipt(supervisor: Any, stage: str) -> tuple[dict[str, Any], Path, str]:
    path = supervisor.root / "shards" / stage / "receipt.bin"
    if "receipt" not in tuple(supervisor.verified_shards(stage)):
        raise LateStageAdapterUnavailable(f"{stage} receipt is not verified")
    try:
        raw = stable_read_bytes(path)
        return _strict_json(raw, f"{stage} receipt"), path, _sha(raw)
    except Exception as exc:
        raise LateStageAdapterUnavailable(f"{stage} receipt reopen refused") from exc


def _published_terminal_inputs(
        supervisor: Any, freeze: Any, repo: Path,
    predictions: Sequence[tuple[str, Mapping[str, Any], Path]]) \
        -> tuple[Path, str]:
    """Publish the terminal path index only after all immutable inputs exist."""
    root = supervisor.root
    # The training adapters must publish these canonical files.  Embedded
    # manifests/checkpoint blobs are not silently promoted into terminal input
    # artifacts because doing so would create a second producer boundary.
    cohorts = []
    controls = {}
    for label, stage, name, block in _COHORTS:
        receipt, _receipt_path, _receipt_sha = _upstream_receipt(supervisor, stage)
        rows = [row for row in receipt.get("cohorts", ())
                if type(row) is dict and row.get("name") == name]
        if len(rows) != 1:
            raise LateStageAdapterUnavailable(f"{label} sealed cohort artifact missing")
        row = rows[0]
        manifest_rel = row.get("cohort_manifest_path")
        checkpoint_rel = row.get("checkpoint_root")
        checkpoint_manifest_rel = row.get("checkpoint_manifest_path")
        if not all(type(item) is str for item in (
                manifest_rel, checkpoint_rel, checkpoint_manifest_rel)):
            raise LateStageAdapterUnavailable(
                f"{label} requires canonical cohort_manifest_path, checkpoint_root, "
                "and checkpoint_manifest_path from training adapter")
        manifest_path = _path(root, manifest_rel, f"cohort {label} manifest")
        checkpoint_root = _directory(root, checkpoint_rel, f"checkpoint root {label}")
        checkpoint_manifest = _path(root, checkpoint_manifest_rel,
                                    f"checkpoint manifest {label}")
        manifest_digest = _relative(root, manifest_path, f"cohort {label} manifest")[1]
        checkpoint_digest = _relative(root, checkpoint_manifest,
                                      f"checkpoint manifest {label}")[1]
        cohorts.append([label, manifest_rel, manifest_digest])
        # TerminalInputPaths needs the root; the index separately binds the
        # exact aggregate manifest bytes used by its reopener.
        controls[label] = [checkpoint_rel, checkpoint_manifest_rel, checkpoint_digest]
        if name != "natural":
            evidence_path = root / "shards" / stage / f"control-evidence-{name}.bin"
            if evidence_path.is_symlink() or not evidence_path.is_file():
                raise LateStageAdapterUnavailable(f"{label} control-dose receipt missing")
            evidence_rel, evidence_digest = _relative(root, evidence_path,
                                                      f"control dose {name}")
            dose = [evidence_rel, evidence_digest]
            dose_rows = controls.setdefault("dose", {})
            prior = dose_rows.get(name)
            # Complete-world shuffle is trained independently in both seed
            # blocks but its transformation/dose evidence describes the same
            # frozen input population.  Do not silently let the later block
            # overwrite a divergent first-block receipt.
            if prior is not None and prior[1] != evidence_digest:
                raise LateStageAdapterUnavailable(
                    f"{name} cross-block control-dose drift")
            if prior is None:
                dose_rows[name] = dose
    population, _, population_sha = _upstream_receipt(supervisor, "population")
    if (population.get("freeze_sha256"), population.get("admission_sha256")) != (
            freeze.sha256(), supervisor.admission.sha256()):
        raise LateStageAdapterUnavailable("population receipt identity drift")
    pred_rows = []
    for label, manifest, path in predictions:
        rel, digest = _relative(root, path, f"prediction {label}")
        if digest != _sha(canonical_json_bytes(manifest)):
            raise LateStageAdapterUnavailable(f"prediction {label} digest drift")
        pred_rows.append([label, rel, digest])
    marker_rel, marker_digest = _relative(root, root / "audit-attempt.json", "audit marker")
    continuation_manifest = root / AUDIT_LABEL_ROOT / "continuations" / "manifest.json"
    continuation_rel, continuation_digest = _relative(root, continuation_manifest,
                                                      "audit continuation manifest")
    fixed = {}
    for key, path in {
            "p0_report": root / "shards" / "p0-labels-gates" / "receipt.bin",
            "optimizer_canary": root / "shards" / "optimizer-canary" / "receipt.bin",
            "precision_result": root / "shards" / PRECISION_STAGE / "result.bin",
            "model_selector_power": root / "shards" / PRECISION_STAGE / "power.bin",
            "prior": root / "shards" / PRECISION_STAGE / "prior.bin"}.items():
        fixed[key] = [*_relative(root, path, key)]
    dose_rows = [[name, *controls["dose"][control]] for name, control in (
        ("association", "action-association-permutation"),
        ("label", "label-permutation"),
        ("world", "complete-world-shuffle"))]
    prefix = [*getattr(supervisor.state, "completed_stages", ())]
    if prefix != [*_WORK_PREFIX, PRECISION_STAGE]:
        raise LateStageAdapterUnavailable("terminal input completed prefix drift")
    capacity_path, capacity_sha, capacity_receipt = _capacity_binding(
        supervisor, freeze, repo)
    selected_reconstruction = tuple(
        arm for arm in capacity_receipt.selected_arms
        if arm.stage == "reconstruction")
    if len(selected_reconstruction) != 1:
        raise LateStageAdapterUnavailable(
            "late reconstruction selected arm missing or duplicated")
    reconstruction_workers = selected_reconstruction[0].variant
    try:
        capacity_root = (
            "evidence" if capacity_path.is_relative_to(root) else "repo")
        capacity_relative = capacity_path.relative_to(
            root if capacity_root == "evidence" else repo).as_posix()
    except ValueError as exc:
        raise LateStageAdapterUnavailable(
            "capacity artifact path escapes its bound root") from exc
    freeze_relative, freeze_sha = _relative(
        root, root / "freeze.json", "execution freeze")
    if freeze_sha != freeze.sha256():
        raise LateStageAdapterUnavailable("execution freeze digest drift")
    body = {"schema": TERMINAL_INPUTS_SCHEMA,
            "freeze_sha256": freeze.sha256(),
            "freeze_path": [freeze_relative, freeze_sha],
            "admission_sha256": supervisor.admission.sha256(),
            "completed_stage_prefix": prefix,
            "population_receipt": ["shards/population/receipt.bin", population_sha],
            "audit_population_namespace_sha256": population["population_namespace_sha256"],
            "audit_population_tier": population["tier"],
            "audit_attempt": [marker_rel, marker_digest],
            "continuation_root": [continuation_rel, continuation_digest],
            "predictions": pred_rows, "cohorts": cohorts,
            "checkpoint_roots": [[label, *controls[label]] for label, *_ in cohorts],
            "p0_report": fixed["p0_report"], "optimizer_canary": fixed["optimizer_canary"],
            "precision_result": fixed["precision_result"],
            "model_selector_power": fixed["model_selector_power"], "prior": fixed["prior"],
            "control_doses": dose_rows,
            "capacity_path": [capacity_relative, capacity_sha],
            "capacity_root": capacity_root,
            "capacity_sha256": capacity_sha,
            "reconstruction_workers": reconstruction_workers,
            "upstream_receipt_sha256s": [[stage, _upstream_receipt(supervisor, stage)[2]]
                                          for stage in (*_WORK_PREFIX, PRECISION_STAGE)]}
    raw = canonical_json_bytes(body)
    index = root / "terminal-inputs.json"
    try:
        publish_exclusive_bytes(index, raw)
        if stable_read_bytes(index) != raw:
            raise ValueError("terminal index byte drift")
    except Exception as exc:
        raise LateStageAdapterUnavailable("terminal input index publication refused") from exc
    return index, _sha(raw)


def _terminal_paths(supervisor: Any, freeze: Any, repo: Path) -> TerminalInputPathsV2:
    root = _identity(supervisor, freeze, repo)
    completed = tuple(getattr(getattr(supervisor, "state", None), "completed_stages", ()))
    if PRECISION_STAGE not in completed:
        raise LateStageAdapterUnavailable("terminal requires precision stage")
    if AUDIT_STAGE in completed and set(supervisor.verified_shards(AUDIT_STAGE)) != {"receipt"}:
        raise LateStageAdapterUnavailable("audit verified shard registry drift")
    if (set(supervisor.verified_shards(PRECISION_STAGE))
            != {"prior", "result", "power", "receipt"}):
        raise LateStageAdapterUnavailable("precision verified shard registry drift")
    index_path = root / "terminal-inputs.json"
    if index_path.is_symlink() or not index_path.is_file():
        raise LateStageAdapterUnavailable("terminal immutable artifact index missing")
    value = _strict_json(stable_read_bytes(index_path), "terminal input index")
    required = {"schema", "freeze_sha256", "freeze_path", "admission_sha256", "completed_stage_prefix",
                "population_receipt", "audit_population_namespace_sha256",
                "audit_population_tier", "audit_attempt", "continuation_root",
                "predictions", "cohorts", "checkpoint_roots", "p0_report",
                "optimizer_canary", "precision_result", "model_selector_power",
                "prior", "control_doses", "capacity_path", "capacity_root",
                "capacity_sha256", "reconstruction_workers", "upstream_receipt_sha256s"}
    if set(value) != required or value["schema"] != TERMINAL_INPUTS_SCHEMA \
            or (value["freeze_sha256"], value["admission_sha256"]) != (freeze.sha256(), supervisor.admission.sha256()):
        raise LateStageAdapterUnavailable("terminal input index identity drift")
    if value["completed_stage_prefix"] != [*_WORK_PREFIX, PRECISION_STAGE] \
            or tuple(getattr(getattr(supervisor, "state", None), "completed_stages", ())) \
            not in (tuple(value["completed_stage_prefix"]),
                    tuple((*value["completed_stage_prefix"], AUDIT_STAGE))):
        raise LateStageAdapterUnavailable("terminal input completed prefix drift")

    def ref(raw: object, label: str) -> Path:
        if type(raw) is not list or len(raw) != 2:
            raise LateStageAdapterUnavailable(f"{label} reference drift")
        path = _path(root, raw[0], label)
        if _sha(stable_read_bytes(path)) != _digest(raw[1], f"{label} digest"):
            raise LateStageAdapterUnavailable(f"{label} digest drift")
        return path

    def external_ref(raw: object, base: Path, label: str) -> Path:
        if type(raw) is not list or len(raw) != 2 or type(raw[0]) is not str:
            raise LateStageAdapterUnavailable(f"{label} reference drift")
        path = _path(base, raw[0], label)
        if _sha(stable_read_bytes(path)) != _digest(raw[1], f"{label} digest"):
            raise LateStageAdapterUnavailable(f"{label} digest drift")
        return path

    try:
        expected_receipts = [*_WORK_PREFIX, PRECISION_STAGE]
        if type(value["upstream_receipt_sha256s"]) is not list \
                or tuple(row[0] for row in value["upstream_receipt_sha256s"]) != tuple(expected_receipts):
            raise ValueError("upstream receipt order")
        for stage, digest in value["upstream_receipt_sha256s"]:
            if type(stage) is not str or _upstream_receipt(supervisor, stage)[2] != _digest(digest, f"{stage} receipt digest"):
                raise ValueError("upstream receipt digest")
        if type(value["population_receipt"]) is not list or len(value["population_receipt"]) != 2:
            raise ValueError("population receipt reference")
        population_receipt = ref(value["population_receipt"], "population receipt")
        if population_receipt != root / "shards" / "population" / "receipt.bin":
            raise ValueError("population receipt path")
        population = reopen_population_receipt_v2(
            _strict_json(stable_read_bytes(population_receipt), "population receipt"))
        if (population.population_namespace_sha256,
                population.tier) != (value["audit_population_namespace_sha256"],
                                      value["audit_population_tier"]):
            raise ValueError("audit population binding")
        if type(value["audit_attempt"]) is not list or type(value["continuation_root"]) is not list:
            raise ValueError("terminal root references")
        continuation_ref = ref(value["continuation_root"], "continuation manifest")
        continuation_root = continuation_ref.parent.parent
        if type(value["predictions"]) is not list or len(value["predictions"]) != len(COHORT_LABELS):
            raise ValueError("prediction references")
        predictions = tuple((row[0], ref(row[1:], f"prediction {row[0]}"))
                            for row in value["predictions"])
        if tuple(label for label, _ in predictions) != COHORT_LABELS:
            raise ValueError("prediction order")
        if type(value["cohorts"]) is not list or len(value["cohorts"]) != len(COHORT_LABELS):
            raise ValueError("cohort references")
        cohorts = tuple((row[0], ref(row[1:], f"cohort {row[0]}"))
                        for row in value["cohorts"])
        if tuple(label for label, _ in cohorts) != COHORT_LABELS:
            raise ValueError("cohort order")
        if type(value["checkpoint_roots"]) is not list or len(value["checkpoint_roots"]) != len(COHORT_LABELS):
            raise ValueError("checkpoint references")
        checkpoint_roots = []
        for row in value["checkpoint_roots"]:
            if type(row) is not list or len(row) != 4 or row[0] not in COHORT_LABELS:
                raise ValueError("checkpoint reference shape")
            checkpoint_roots.append((row[0], _directory(root, row[1], f"checkpoint root {row[0]}")))
            checkpoint_manifest = ref([row[2], row[3]], f"checkpoint manifest {row[0]}")
            try:
                checkpoint_manifest.relative_to(checkpoint_roots[-1][1])
            except ValueError:
                raise ValueError("checkpoint root binding")
        if tuple(label for label, _ in checkpoint_roots) != COHORT_LABELS:
            raise ValueError("checkpoint order")
        doses = tuple((row[0], ref(row[1:], f"control dose {row[0]}"))
                      for row in value["control_doses"])
        if tuple(label for label, _ in doses) != DOSE_LABELS:
            raise ValueError("control dose order")
        if value["capacity_root"] not in ("evidence", "repo"):
            raise ValueError("capacity artifact root")
        capacity_base = root if value["capacity_root"] == "evidence" else repo
        capacity_path = external_ref(value["capacity_path"], capacity_base,
                                     "capacity artifact")
        freeze_path = ref(value["freeze_path"], "execution freeze")
        if freeze_path != root / "freeze.json":
            raise ValueError("execution freeze path")
        capacity_sha256 = _digest(value["capacity_sha256"],
                                  "capacity artifact SHA-256")
        reconstruction_workers = value["reconstruction_workers"]
        if (isinstance(reconstruction_workers, bool)
                or not isinstance(reconstruction_workers, int)
                or reconstruction_workers not in (1, 4, 8, 16, 32)):
            raise ValueError("reconstruction worker binding")
        # The controller will repeat this authentication immediately before
        # audit opening; adapter reconstruction also rejects a stale index.
        capacity_binding = tuple(row for row in freeze.artifact_bindings
                                 if row[0] == "capacity")
        if len(capacity_binding) != 1 or capacity_sha256 != capacity_binding[0][2]:
            raise ValueError("capacity freeze binding")
        return TerminalInputPathsV2(
            freeze_sha256=freeze.sha256(), admission_sha256=supervisor.admission.sha256(), audit_population_root=root,
            audit_population_namespace_sha256=value["audit_population_namespace_sha256"], audit_population_tier=value["audit_population_tier"],
            audit_attempt_path=ref(value["audit_attempt"], "audit attempt"),
            continuation_root=continuation_root,
            prediction_manifest_paths=predictions,
            cohort_manifest_paths=cohorts,
            checkpoint_roots=tuple(checkpoint_roots),
            p0_report_path=ref(value["p0_report"], "P0 report"), optimizer_canary_path=ref(value["optimizer_canary"], "optimizer canary"),
            precision_select_result_path=ref(value["precision_result"], "precision result"), model_selector_power_path=ref(value["model_selector_power"], "model selector power"),
            prior_path=ref(value["prior"], "Jeffreys prior"),
            control_dose_receipt_paths=doses,
            freeze_path=freeze_path, capacity_path=capacity_path,
            capacity_sha256=capacity_sha256,
            reconstruction_workers=reconstruction_workers)
    except (KeyError, TypeError, ValueError) as exc:
        raise LateStageAdapterUnavailable("terminal input index reconstruction refused") from exc


@dataclass(frozen=True)
class TerminalAdapterV2:
    freeze: Any
    repo: Path
    stage: str = TERMINAL_STAGE
    __world_afterstate_v2_stage_adapter__: str = ABI
    @property
    def producer(self): return run_terminal_v2
    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        inputs = _selected_terminal_paths(supervisor, self.freeze, self.repo)
        inputs.validate_shape()
        return self.producer(supervisor.root, inputs)


@dataclass(frozen=True)
class ReconstructionAdapterV2:
    freeze: Any
    repo: Path
    stage: str = RECONSTRUCTION_STAGE
    __world_afterstate_v2_stage_adapter__: str = ABI
    @property
    def producer(self): return verify_terminal_artifact_v2
    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        # Compatibility for callers that already hold typed terminal paths.
        if isinstance(self.repo, (TerminalInputPathsV2,
                                  EarlyTerminalInputPathsV2)):
            self.repo.validate_shape()
            if supervisor.root != self.freeze:
                raise LateStageAdapterUnavailable("reconstruction root binding drift")
            return self.producer(supervisor.root / "terminal", self.repo, rescore=False)
        del verified_shards
        inputs = _selected_terminal_paths(supervisor, self.freeze, self.repo)
        inputs.validate_shape()
        return self.producer(
            supervisor.root / "terminal", inputs, rescore=False)


def precision_select_power_adapter(*, freeze: Any, repo: Path) -> PrecisionSelectPowerAdapterV2:
    tier_counts(freeze)
    if not isinstance(repo, Path) or repo.is_symlink() or not repo.is_dir():
        raise LateStageAdapterUnavailable("late adapter repository drift")
    return PrecisionSelectPowerAdapterV2(freeze, repo)


def audit_attempt_adapter(*, freeze: Any, repo: Path) -> AuditAttemptAdapterV2:
    tier_counts(freeze)
    if not isinstance(repo, Path) or repo.is_symlink() or not repo.is_dir():
        raise LateStageAdapterUnavailable("late adapter repository drift")
    return AuditAttemptAdapterV2(freeze, repo)


def terminal_adapter(*, freeze: Any, repo: Path) -> TerminalAdapterV2:
    tier_counts(freeze)
    if not isinstance(repo, Path) or repo.is_symlink() or not repo.is_dir():
        raise LateStageAdapterUnavailable("late adapter repository drift")
    return TerminalAdapterV2(freeze, repo)


def reconstruction_adapter(*, freeze: Any, repo: Path) -> ReconstructionAdapterV2:
    tier_counts(freeze)
    if not isinstance(repo, Path) or repo.is_symlink() or not repo.is_dir():
        raise LateStageAdapterUnavailable("late adapter repository drift")
    return ReconstructionAdapterV2(freeze, repo)


PrecisionSelectAdapterV2 = PrecisionSelectPowerAdapterV2
PrecisionSelectPowerStageAdapterV2 = PrecisionSelectPowerAdapterV2
AuditAdapterV2 = AuditAttemptAdapterV2
AuditAttemptStageAdapterV2 = AuditAttemptAdapterV2
TerminalStageAdapterV2 = TerminalAdapterV2
ReconstructionStageAdapterV2 = ReconstructionAdapterV2


def production_stage_adapter(stage: str, *, freeze: Any, repo: Path) -> Any:
    factories = {PRECISION_STAGE: precision_select_power_adapter, AUDIT_STAGE: audit_attempt_adapter, TERMINAL_STAGE: terminal_adapter, RECONSTRUCTION_STAGE: reconstruction_adapter}
    if stage not in factories: raise LateStageAdapterUnavailable(f"late adapter unavailable for {stage}")
    return factories[stage](freeze=freeze, repo=repo)


precision_select_adapter = precision_select_power_adapter


__all__ = ["ABI", "AUDIT_LABEL_ROOT", "AuditAdapterV2", "AuditAttemptAdapterV2", "AuditAttemptStageAdapterV2", "LateStageAdapterUnavailable", "PRECISION_LABEL_ROOT", "PrecisionSelectAdapterV2", "PrecisionSelectPowerAdapterV2", "PrecisionSelectPowerStageAdapterV2", "ReconstructionAdapterV2", "ReconstructionStageAdapterV2", "TerminalAdapterV2", "TerminalStageAdapterV2", "audit_attempt_adapter", "evaluate_precision_select_v2", "precision_select_adapter", "precision_select_power_adapter", "publish_audit_attempt", "reconstruction_adapter", "terminal_adapter", "production_stage_adapter", "tier_counts"]
