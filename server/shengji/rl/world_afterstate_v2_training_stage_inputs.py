"""Closed, read-only inputs for the Value-Afterstate V2 training stage.

This is intentionally a source adapter, not a trainer.  It reopens the
freeze-bound capacity receipt, the immutable fit/select materials and label
bundles, and the sealed P0 report before constructing the objects consumed by
the existing training controller.  No caller supplied metric is accepted.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_artifacts import reopen_continuation_manifest
from .world_afterstate_v2_capacity_runner import (
    reopen_capacity_receipt_v2_bytes,
)
from .world_afterstate_v2_capacity import PINNED_TORCH_THREADS
from .world_afterstate_v2_dataset import build_training_examples_v2
from .world_afterstate_v2_inference import (
    INFERENCE_BATCH_CAPS, build_inference_root_v2,
)
from .world_afterstate_v2_label import validate_precision_label
from .world_afterstate_v2_population_artifacts import (
    material_sha256, reopen_population_manifest,
)
from .world_afterstate_v2_protocol import SELECT_SUBFOLDS, TIER_SPECS
from .world_afterstate_v2_selection import EpochSelectPopulationV2
from .world_afterstate_v2_schedule import (
    DEFAULT_BATCH_EXAMPLE_CAP, MAX_EPOCHS, training_epoch_batches,
)
from .world_afterstate_v2_training import (
    WorldAfterstateV2TrainingConfig, WorldAfterstateV2TrainingExample,
)


SCHEMA = "world-afterstate-v2-training-stage-inputs-v1"
FIT_SELECT_CONTINUATION_ROOT = "fit-select-continuations"
P0_SIGMA_FIELD = "pair_target_population_variance"
REVIEWED_LEARNING_RATE_PPB = 10_000_000
REVIEWED_WEIGHT_DECAY_PPB = 0
REVIEWED_GRADIENT_NORM_MILLI = 1_000
REVIEWED_MAX_EPOCHS = MAX_EPOCHS
REVIEWED_BATCH_EXAMPLE_CAP = DEFAULT_BATCH_EXAMPLE_CAP
CAPACITY_MEMBER_STAGE = "member-concurrency"
CAPACITY_BATCH_STAGE = "inference-batch"
P0_REPORT_RELATIVE = Path("shards/p0-labels-gates/receipt.bin")


class WorldAfterstateV2TrainingStageInputError(ValueError):
    """A freeze-bound training source or split population was refused."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorldAfterstateV2TrainingStageInputError(f"{label} drift")
    return value


def _path(root: Path, relative: object, label: str) -> Path:
    if (type(relative) is not str or not relative
            or Path(relative).is_absolute() or "\\" in relative
            or Path(relative).as_posix() != relative
            or any(part in ("", ".", "..") for part in Path(relative).parts)):
        raise WorldAfterstateV2TrainingStageInputError(f"{label} path drift")
    target = root / relative
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            f"{label} path escapes evidence root") from exc
    if target.is_symlink() or not target.is_file():
        raise WorldAfterstateV2TrainingStageInputError(f"{label} missing")
    return target


def _read(path: Path, label: str) -> bytes:
    try:
        return stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            f"{label} stable read refused") from exc


def _freeze_sha(freeze: Any) -> str:
    try:
        from .world_afterstate_v2_execution import validate_execution_freeze
        validate_execution_freeze(freeze)
        return freeze.sha256()
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "execution freeze refused") from exc


def _capacity(freeze: Any, root: Path):
    bindings = getattr(freeze, "artifact_bindings", None)
    rows = [row for row in (bindings or ())
            if type(row) is tuple and len(row) == 3 and row[0] == "capacity"]
    if len(rows) != 1:
        raise WorldAfterstateV2TrainingStageInputError(
            "capacity artifact binding missing or duplicated")
    _label, relative, expected = rows[0]
    expected = _digest(expected, "capacity artifact SHA-256")
    if expected != getattr(freeze, "capacity_sha256", None):
        raise WorldAfterstateV2TrainingStageInputError(
            "capacity artifact/freeze binding drift")
    target = _path(root, relative, "capacity artifact")
    raw = _read(target, "capacity artifact")
    if _sha_bytes(raw) != expected:
        raise WorldAfterstateV2TrainingStageInputError(
            "capacity artifact digest drift")
    try:
        receipt = reopen_capacity_receipt_v2_bytes(raw)
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "capacity receipt reopen refused") from exc
    return receipt, expected


def _selected_variant(receipt: Any, stage: str, label: str) -> int:
    arms = tuple(getattr(receipt, "selected_arms", ()))
    matches = tuple(arm for arm in arms if getattr(arm, "stage", None) == stage)
    if len(matches) != 1:
        raise WorldAfterstateV2TrainingStageInputError(
            f"{label} selected arm missing or duplicated")
    arm = matches[0]
    variant = getattr(arm, "variant", None)
    if isinstance(variant, bool) or not isinstance(variant, int) or variant < 1:
        raise WorldAfterstateV2TrainingStageInputError(f"{label} variant drift")
    # The receipt validator authenticates the complete arm grid and selected
    # arm identity.  Recheck the selected arm itself so a foreign typed object
    # cannot enter through a duck-typed receipt in an adapter test.
    try:
        arm.validate()
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            f"{label} selected arm refused") from exc
    return variant


def _capacity_resources(receipt: Any) -> tuple[int, int, int, int]:
    receipt_threads = getattr(receipt, "torch_threads", None)
    if (isinstance(receipt_threads, bool)
            or type(receipt_threads) is not int
            or receipt_threads != PINNED_TORCH_THREADS):
        raise WorldAfterstateV2TrainingStageInputError(
            "training resource arm drift")
    member_workers = _selected_variant(receipt, CAPACITY_MEMBER_STAGE,
                                        "model-training-concurrency")
    # Inference batching is selected independently and consumed only by the
    # prediction adapters.  Training retains its reviewed fixed batch cap;
    # coupling the two makes a valid fastest inference arm alter the recipe.
    inference_batch_cap = _selected_variant(
        receipt, CAPACITY_BATCH_STAGE, "inference batch")
    batch_cap = REVIEWED_BATCH_EXAMPLE_CAP
    if REVIEWED_BATCH_EXAMPLE_CAP != 256:
        raise WorldAfterstateV2TrainingStageInputError(
            "reviewed training batch cap drift")
    torch_threads = PINNED_TORCH_THREADS
    if member_workers not in (1, 2, 4):
        raise WorldAfterstateV2TrainingStageInputError(
            "training resource arm drift")
    if inference_batch_cap not in INFERENCE_BATCH_CAPS:
        raise WorldAfterstateV2TrainingStageInputError(
            "inference batch arm drift")
    return member_workers, torch_threads, batch_cap, inference_batch_cap


def _p0_sigma(path: Path) -> tuple[float, str]:
    raw = _read(path, "P0 report")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 report is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2TrainingStageInputError("P0 report canonical drift")
    try:
        validate_precision_label(value)
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 report reopen refused") from exc
    # Do not substitute the similarly named incumbent-relative Bessel SD.
    # Section 9 freezes the exact population variance across all complete
    # eight-replica non-incumbent advantages, represented as a reduced
    # rational in the sealed P0 report.
    payload = value.get(P0_SIGMA_FIELD)
    if type(payload) is not dict or set(payload) != {"numerator", "denominator"}:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 report does not expose a sound sigma field")
    numerator = payload["numerator"]
    denominator = payload["denominator"]
    if (isinstance(numerator, bool) or not isinstance(numerator, int)
            or numerator < 0 or isinstance(denominator, bool)
            or not isinstance(denominator, int) or denominator <= 0):
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 report does not expose a sound sigma field")
    exact = Fraction(numerator, denominator)
    if {"numerator": exact.numerator, "denominator": exact.denominator} != payload:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 sigma fraction is not reduced")
    sigma = float(exact)
    if not math.isfinite(sigma) or sigma < 0:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 sigma derivation drift")
    return sigma, _sha_bytes(raw)


def _bound_p0_sigma(root: Path, supervisor: Any, *,
                    freeze: Any) -> tuple[float, str]:
    """Reopen only the P0 receipt registered by this exact supervisor."""
    # This receipt is a stage-order authority boundary, so duck typing is not
    # sufficient: an arbitrary object with a fabricated ``verified_shards``
    # tuple must not bless label bytes.  Import lazily to avoid an execution ->
    # adapter -> input cycle at module import time.
    from .world_afterstate_v2_execution import StageSupervisorV2
    if type(supervisor) is not StageSupervisorV2:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 supervisor identity drift")
    try:
        supervisor_root = Path(supervisor.root)
        supervisor_freeze_sha = supervisor.freeze.sha256()
        expected_freeze_sha = freeze.sha256()
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 supervisor identity drift") from exc
    if (supervisor_root.resolve() != root.resolve()
            or supervisor_freeze_sha != expected_freeze_sha):
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 supervisor identity drift")
    state = getattr(supervisor, "state", None)
    completed = getattr(state, "completed_stages", ())
    verified = getattr(state, "verified_shards", ())
    if "p0-labels-gates" not in completed or type(verified) is not tuple:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 supervisor stage binding missing")
    identity = "p0-labels-gates:receipt"
    rows = tuple(row for row in verified
                 if type(row) is tuple and len(row) == 2 and row[0] == identity)
    if len(rows) != 1:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 supervisor shard binding missing or duplicated")
    expected = _digest(rows[0][1], "P0 supervisor shard SHA-256")
    path = root / P0_REPORT_RELATIVE
    sigma, actual = _p0_sigma(path)
    if actual != expected:
        raise WorldAfterstateV2TrainingStageInputError(
            "P0 supervisor shard digest drift")
    return sigma, actual


@dataclass(frozen=True)
class WorldAfterstateV2TrainingStageInputs:
    """All immutable, split-safe inputs required by a future trainer."""

    training_examples: tuple[WorldAfterstateV2TrainingExample, ...]
    epoch_select_population: EpochSelectPopulationV2
    config: WorldAfterstateV2TrainingConfig
    member_workers: int
    torch_threads: int
    batch_example_cap: int
    inference_batch_cap: int
    source_digests: tuple[tuple[str, str], ...]
    schema: str = SCHEMA

    @property
    def examples(self) -> tuple[WorldAfterstateV2TrainingExample, ...]:
        return self.training_examples

    @property
    def epoch_select(self) -> EpochSelectPopulationV2:
        return self.epoch_select_population

    def validate(self) -> None:
        if self.schema != SCHEMA or type(self.training_examples) is not tuple \
                or not self.training_examples \
                or any(type(row) is not WorldAfterstateV2TrainingExample
                       for row in self.training_examples):
            raise WorldAfterstateV2TrainingStageInputError(
                "training example population drift")
        if type(self.epoch_select_population) is not EpochSelectPopulationV2:
            raise WorldAfterstateV2TrainingStageInputError(
                "epoch-select population type drift")
        try:
            self.epoch_select_population.validate()
        except Exception as exc:
            raise WorldAfterstateV2TrainingStageInputError(
                "epoch-select population refused") from exc
        if type(self.config) is not WorldAfterstateV2TrainingConfig:
            raise WorldAfterstateV2TrainingStageInputError("training config type drift")
        self.config.validate()
        if self.config.learning_rate_ppb != REVIEWED_LEARNING_RATE_PPB \
                or self.config.weight_decay_ppb != REVIEWED_WEIGHT_DECAY_PPB \
                or self.config.gradient_norm_milli != REVIEWED_GRADIENT_NORM_MILLI \
                or self.config.max_epochs != REVIEWED_MAX_EPOCHS:
            raise WorldAfterstateV2TrainingStageInputError(
                "reviewed training config drift")
        if (self.member_workers not in (1, 2, 4)
                or isinstance(self.torch_threads, bool)
                or not isinstance(self.torch_threads, int)
                or self.torch_threads != PINNED_TORCH_THREADS
                or self.batch_example_cap != REVIEWED_BATCH_EXAMPLE_CAP
                or isinstance(self.inference_batch_cap, bool)
                or type(self.inference_batch_cap) is not int
                or self.inference_batch_cap not in INFERENCE_BATCH_CAPS):
            raise WorldAfterstateV2TrainingStageInputError(
                "training resource configuration drift")
        if (type(self.source_digests) is not tuple
                or not self.source_digests
                or any(type(row) is not tuple or len(row) != 2
                       or type(row[0]) is not str for row in self.source_digests)
                or tuple(sorted(self.source_digests)) != self.source_digests
                or len({row[0] for row in self.source_digests})
                != len(self.source_digests)):
            raise WorldAfterstateV2TrainingStageInputError(
                "training source digest population drift")
        for _label, digest in self.source_digests:
            _digest(digest, "training source digest")
        source_map = dict(self.source_digests)
        if "capacity" not in source_map or "capacity-inference-batch" not in source_map:
            raise WorldAfterstateV2TrainingStageInputError(
                "training capacity source binding missing")
        expected_inference_binding = _sha({
            "capacity_sha256": source_map["capacity"],
            "inference_batch_cap": self.inference_batch_cap,
        })
        if source_map["capacity-inference-batch"] != expected_inference_binding:
            raise WorldAfterstateV2TrainingStageInputError(
                "training inference batch source binding drift")
        keys = tuple(row.example_key for row in self.training_examples)
        if len(keys) != len(set(keys)) \
                or any(row.split != "fit" or row.cohort != "primary"
                       or row.source not in ("natural", "mechanics")
                       for row in self.training_examples):
            raise WorldAfterstateV2TrainingStageInputError(
                "training split/source leakage")
        try:
            training_epoch_batches(
                self.training_examples, epoch=1, data_order_seed=0,
                cohort="primary", control_name="natural",
                batch_example_cap=self.batch_example_cap)
        except Exception as exc:
            raise WorldAfterstateV2TrainingStageInputError(
                "training example root population refused") from exc

    def manifest(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "training_example_count": len(self.training_examples),
            "training_root_count": len({row.root_key for row in self.training_examples}),
            "epoch_select_root_count": len(self.epoch_select_population.roots),
            "epoch_select_outcome_count": len(self.epoch_select_population.outcomes),
            "config_sha256": self.config.sha256(),
            "member_workers": self.member_workers,
            "torch_threads": self.torch_threads,
            "batch_example_cap": self.batch_example_cap,
            "inference_batch_cap": self.inference_batch_cap,
            "source_digests": [list(row) for row in self.source_digests],
            "training_authorized": False,
            "audit_opening_authorized": False,
        }


def _population_namespace(freeze: Any, root: Path,
                          repo: Path | None) -> str:
    """Read the reviewed stage config that names the population namespace."""
    bindings = getattr(freeze, "artifact_bindings", None)
    rows = [row for row in (bindings or ())
            if type(row) is tuple and len(row) == 3 and row[0] == "config"]
    if len(rows) != 1:
        raise WorldAfterstateV2TrainingStageInputError(
            "population config binding missing or duplicated")
    _label, relative, expected = rows[0]
    expected = _digest(expected, "population config SHA-256")
    base = repo if repo is not None else root
    if not isinstance(base, Path) or base.is_symlink() or not base.is_dir():
        raise WorldAfterstateV2TrainingStageInputError("population config root drift")
    path = _path(base, relative, "population config")
    raw = _read(path, "population config")
    if _sha_bytes(raw) != expected:
        raise WorldAfterstateV2TrainingStageInputError(
            "population config digest drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "population config is not canonical JSON") from exc
    namespace = value.get("population_namespace_sha256") \
        if type(value) is dict else None
    return _digest(namespace, "population namespace SHA-256")


def _d256_fit_materials(materials: tuple[Any, ...]) -> tuple[Any, ...]:
    """Validate the exact reviewed D256 fit-source population."""
    if type(materials) is not tuple:
        raise WorldAfterstateV2TrainingStageInputError(
            "fit/select material population drift")
    counts = {
        source: sum(getattr(material.state, "source", None) == source
                    for material in materials)
        for source in ("natural", "mechanics")}
    if (len(materials) != 160
            or counts != {"natural": 128, "mechanics": 32}
            or any(getattr(material.state, "split", None) != "fit"
                   for material in materials)):
        raise WorldAfterstateV2TrainingStageInputError(
            "fit/select material population drift")
    return materials


def build_training_stage_inputs(
        freeze: Any, repo: Path | None = None, *, supervisor: Any,
        evidence_root: Path | None = None) -> WorldAfterstateV2TrainingStageInputs:
    """Reopen exact frozen sources and return read-only trainer inputs."""
    freeze_digest = _freeze_sha(freeze)
    root = Path(getattr(freeze, "evidence_root", ""))
    if evidence_root is not None:
        if not isinstance(evidence_root, Path):
            raise WorldAfterstateV2TrainingStageInputError("evidence root type drift")
        root = evidence_root
    if root.is_symlink() or not root.is_dir():
        raise WorldAfterstateV2TrainingStageInputError("evidence root drift")
    if Path(getattr(freeze, "evidence_root")) != root:
        raise WorldAfterstateV2TrainingStageInputError(
            "evidence root differs from freeze")
    receipt, capacity_digest = _capacity(freeze, root)
    (member_workers, torch_threads, batch_cap,
     inference_batch_cap) = _capacity_resources(receipt)
    sigma, p0_digest = _bound_p0_sigma(root, supervisor, freeze=freeze)

    try:
        tier = getattr(freeze, "population_tier")
        # The current reviewed material adapter is intentionally D256-only.
        # Capacity still projects the larger tiers, but marks their exact
        # source supply false; a freeze must never select a tier that this
        # implementation would discover only after training begins.
        if tier != "D256":
            raise WorldAfterstateV2TrainingStageInputError(
                "training exact source supply is unavailable for frozen tier")
        namespace = _population_namespace(freeze, root, repo)
        materials = reopen_population_manifest(
            root, expected_freeze_sha256=freeze_digest,
            expected_population_namespace_sha256=namespace,
            expected_tier=tier, expected_split="fit", expected_source=None)
        select_materials = reopen_population_manifest(
            root, expected_freeze_sha256=freeze_digest,
            expected_population_namespace_sha256=namespace,
            expected_tier=tier, expected_split="select", expected_source="natural")
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "fit/select material reopen refused") from exc
    # D256 trains on all 160 fit deals: 128 natural plus the 32 frozen
    # mechanics-hard deals.  "Natural" below names the unpermuted training
    # cohort, not the population source, so dropping mechanics here would both
    # violate the reviewed tier and make the authentic population impossible
    # to run.
    fit = _d256_fit_materials(tuple(materials))
    epoch_materials = tuple(material for material in select_materials
                            if material.state.select_subfold == "epoch-select")
    # The population manifest also authenticates the untouched
    # precision-select rows.  They are deliberately not reopened into roots,
    # bundles, or examples below; only the sixteen epoch-select rows cross
    # this stage boundary.
    expected_select = TIER_SPECS[0].select
    expected_subfold = expected_select // len(SELECT_SUBFOLDS)
    subfold_counts = {
        name: sum(material.state.select_subfold == name
                  for material in select_materials)
        for name in SELECT_SUBFOLDS}
    if (len(select_materials) != expected_select
            or len(epoch_materials) != expected_subfold
            or subfold_counts != {name: expected_subfold
                                  for name in SELECT_SUBFOLDS}):
        raise WorldAfterstateV2TrainingStageInputError(
            "fit/select material population drift")
    if any(material.state.split != "fit" for material in fit) \
            or any(material.state.split != "select" for material in epoch_materials):
        raise WorldAfterstateV2TrainingStageInputError("training split leakage")

    all_materials = (*fit, *epoch_materials)
    try:
        bundles = reopen_continuation_manifest(
            root / FIT_SELECT_CONTINUATION_ROOT, all_materials)
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "fit-select continuation reopen refused") from exc
    by_deal = {bundle.deal_sha256: bundle for bundle in bundles}
    if len(by_deal) != len(all_materials) or set(by_deal) != {
            material.deal_sha256 for material in all_materials}:
        raise WorldAfterstateV2TrainingStageInputError(
            "fit-select bundle/material population mismatch")

    examples: list[WorldAfterstateV2TrainingExample] = []
    for material in fit:
        try:
            rows = build_training_examples_v2(material, by_deal[material.deal_sha256])
        except Exception as exc:
            raise WorldAfterstateV2TrainingStageInputError(
                "primary training example construction refused") from exc
        examples.extend(rows)
    training_examples = tuple(examples)
    roots = tuple(build_inference_root_v2(material) for material in epoch_materials)
    outcomes = tuple(row for material in epoch_materials
                     for row in by_deal[material.deal_sha256].candidates)
    selection = EpochSelectPopulationV2(roots=roots, outcomes=outcomes)
    try:
        selection.validate()
    except Exception as exc:
        raise WorldAfterstateV2TrainingStageInputError(
            "epoch-select population construction refused") from exc
    config = WorldAfterstateV2TrainingConfig(
        learning_rate_ppb=REVIEWED_LEARNING_RATE_PPB,
        weight_decay_ppb=REVIEWED_WEIGHT_DECAY_PPB,
        gradient_norm_milli=REVIEWED_GRADIENT_NORM_MILLI,
        max_epochs=REVIEWED_MAX_EPOCHS, sigma_pair_squared=sigma)
    source_rows = [
        ("capacity", capacity_digest),
        ("capacity-inference-batch", _sha({
            "capacity_sha256": capacity_digest,
            "inference_batch_cap": inference_batch_cap,
        })),
        ("p0-report", p0_digest),
    ]
    source_rows.extend((f"fit-material:{material.deal_sha256}", material_sha256(material))
                       for material in fit)
    source_rows.extend((f"fit-bundle:{material.deal_sha256}",
                        by_deal[material.deal_sha256].bundle_sha256)
                       for material in fit)
    source_rows.extend((f"epoch-select-material:{material.deal_sha256}",
                        material_sha256(material)) for material in epoch_materials)
    source_rows.extend((f"epoch-select-bundle:{material.deal_sha256}",
                        by_deal[material.deal_sha256].bundle_sha256)
                       for material in epoch_materials)
    result = WorldAfterstateV2TrainingStageInputs(
        training_examples=training_examples,
        epoch_select_population=selection, config=config,
        member_workers=member_workers, torch_threads=torch_threads,
        batch_example_cap=batch_cap,
        inference_batch_cap=inference_batch_cap,
        source_digests=tuple(sorted(source_rows)))
    result.validate()
    return result


# Descriptive aliases for adapters that use the full contract name.
build_world_afterstate_v2_training_stage_inputs = build_training_stage_inputs
build_v2_training_stage_inputs = build_training_stage_inputs
WorldAfterstateV2TrainingInputs = WorldAfterstateV2TrainingStageInputs


__all__ = [
    "CAPACITY_BATCH_STAGE", "CAPACITY_MEMBER_STAGE", "PINNED_TORCH_THREADS",
    "FIT_SELECT_CONTINUATION_ROOT", "P0_REPORT_RELATIVE", "P0_SIGMA_FIELD", "SCHEMA",
    "WorldAfterstateV2TrainingStageInputError",
    "WorldAfterstateV2TrainingStageInputs", "WorldAfterstateV2TrainingInputs",
    "build_training_stage_inputs", "build_v2_training_stage_inputs",
    "build_world_afterstate_v2_training_stage_inputs",
]
