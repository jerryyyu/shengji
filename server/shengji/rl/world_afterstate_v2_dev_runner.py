"""Small, resumable development runner for the reviewed Value V2 D64 arm."""

from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_dev_protocol import build_value_v2_dev_protocol
from .world_afterstate_v2_label_controller import (
    build_continuation_population_v2, reopen_label_stage_receipt,
)
from .world_afterstate_v2_population_artifacts import reopen_population_manifest
from .world_afterstate_v2_population_controller import (
    collect_population_v2, reopen_population_collection_v2,
)
from .world_afterstate_v2_protocol import D256_MAX_ATTEMPTS_PER_SLOT
from .world_afterstate_v2_artifacts import reopen_continuation_manifest
from .world_afterstate_v2_dataset import build_training_examples_v2
from .world_afterstate_v2_inference import (
    build_inference_root_v2, predict_roots_v2, prediction_population_manifest_v2,
)
from .world_afterstate_v2_metrics import build_natural_fit_prior
from .world_afterstate_v2_reopen import reopen_jeffreys_prior_v2
from .world_afterstate_v2_selection import EpochSelectPopulationV2
from .world_afterstate_v2_training import (
    WorldAfterstateV2TrainingConfig,
)
from .world_afterstate_v2_training_controller import (
    CohortTrainingBuildV2, reopen_cohort_build, train_named_cohort,
)
from .world_afterstate_v2_schedule import training_epoch_batches
from .world_afterstate_v2_training_recovery_store import (
    RecoveryStoreBindingV2, WorldAfterstateV2RecoveryStore,
)
from .world_afterstate_v2_evaluation import evaluate_v2
from .world_afterstate import category_signed_level


SCHEMA = "world-afterstate-v2-dev-d64-runner-v1"
STAGE_WATCHDOG_SECONDS = 24 * 60 * 60
AUTHORITY = {
    "downstream_authorized": False, "gameplay_authorized": False,
    "strength_claim_authorized": False, "merge_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateV2DevRunnerError(ValueError):
    """A development run or immutable artifact could not be reopened."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2DevRunnerError(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2DevRunnerError(f"{label} is not canonical JSON")
    return value


def _publish(path: Path, value: object) -> tuple[dict[str, Any], str]:
    raw = value if type(value) is bytes else canonical_json_bytes(value)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        publish_exclusive_bytes(path, raw)
        if stable_read_bytes(path) != raw:
            raise ValueError("artifact byte drift")
    except Exception as exc:
        raise WorldAfterstateV2DevRunnerError(
            f"immutable publication refused: {path.name}") from exc
    return (_json(raw, path.name) if type(value) is not bytes else {}, _sha_bytes(raw))


def _open(path: Path, label: str) -> tuple[bytes, str]:
    try:
        raw = stable_read_bytes(path)
    except Exception as exc:
        raise WorldAfterstateV2DevRunnerError(f"{label} missing") from exc
    return raw, _sha_bytes(raw)


def _publish_or_verify(path: Path, value: object, label: str) -> str:
    raw = value if type(value) is bytes else canonical_json_bytes(value)
    if path.exists():
        try:
            existing = stable_read_bytes(path)
        except Exception as exc:
            raise WorldAfterstateV2DevRunnerError(f"{label} reopen refused") from exc
        if existing != raw:
            raise WorldAfterstateV2DevRunnerError(f"{label} rehash")
        return _sha_bytes(existing)
    _publish(path, value)
    return _sha_bytes(raw)


def _persistent_progress(root: Path,
                         callback: Callable[[dict[str, Any]], None] | None
                         ) -> Callable[[dict[str, Any]], None]:
    directory = root / "private" / "progress"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    entries = tuple(directory.iterdir())
    expected = tuple(f"event-{index:08d}.json" for index in range(len(entries)))
    if tuple(sorted(path.name for path in entries)) != expected \
            or any(not path.is_file() or path.is_symlink() for path in entries):
        raise WorldAfterstateV2DevRunnerError("progress artifact population drift")
    next_index = len(entries)
    def emit(value: dict[str, Any]) -> None:
        nonlocal next_index
        # The caller has already reduced this to cardinality/timing fields.
        _publish(directory / f"event-{next_index:08d}.json", value)
        next_index += 1
        if callback is not None:
            callback(dict(value))
    return emit


def _git_sha(repo: Path) -> str:
    try:
        value = subprocess.check_output(
            ("git", "-C", str(repo), "rev-parse", "HEAD"),
            text=True, stderr=subprocess.DEVNULL).strip()
        status = subprocess.check_output(
            ("git", "-C", str(repo), "status", "--porcelain",
             "--untracked-files=all"), text=True,
            stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorldAfterstateV2DevRunnerError("source Git SHA unavailable") from exc
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2DevRunnerError("source Git SHA drift")
    if status:
        raise WorldAfterstateV2DevRunnerError("source Git worktree is not clean")
    return value


def _identity(run_id: str, label: str) -> str:
    return _sha({"schema": SCHEMA, "run_id": run_id, "identity": label})


def _report(progress: Callable[[dict[str, Any]], None] | None, *, stage: str,
            completed: int, total: int, active_workers: int, started: int) -> None:
    if progress is None:
        return
    elapsed = max(0, time.monotonic_ns() - started)
    remaining = max(0, total - completed)
    eta = (elapsed * remaining // completed) if completed else 0
    progress({"stage": stage, "completed": completed, "total": total,
              "percent": completed * 100 // max(total, 1),
              "active_workers": active_workers, "elapsed_nanoseconds": elapsed,
              "eta_nanoseconds": eta})


def _safe_low_level_progress(progress: Callable[[dict[str, Any]], None] | None,
                             stage: str) -> Callable[[dict[str, Any]], None] | None:
    if progress is None:
        return None
    started = time.monotonic_ns()
    def emit(value: dict[str, Any]) -> None:
        # Deliberately copy only cardinality/timing fields.  No target or
        # result-bearing object is ever passed to the public progress hook.
        completed = value.get("completed", value.get("completed_deals",
                           value.get("completed_slots", value.get("completed_units", 0))))
        total = value.get("total", value.get("total_deals",
                     value.get("total_slots", value.get("total_units", 1))))
        _report(progress, stage=stage, completed=int(completed), total=int(total),
                active_workers=int(value.get("active_workers", 0)), started=started)
    return emit


def _payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "payload") and callable(value.payload):
        result = value.payload()
        if type(result) is dict:
            return result
    if type(value) is dict:
        return dict(value)
    raise WorldAfterstateV2DevRunnerError("receipt payload unavailable")


def _population(root: Path, run_id: str, *, repo: Path, workers: int,
                progress: Callable[[dict[str, Any]], None] | None) -> tuple[Any, tuple[Any, ...], str]:
    private = root / "private"
    receipt_path = private / "d256-population-receipt.json"
    freeze, namespace, admission = (_identity(run_id, item) for item in (
        "legacy-freeze", "legacy-population-namespace", "legacy-admission"))
    started = time.monotonic_ns()
    _report(progress, stage="d256-population", completed=0, total=256,
            active_workers=workers, started=started)
    if receipt_path.exists():
        receipt_value = _json(stable_read_bytes(receipt_path), "D256 receipt")
        receipt = reopen_population_collection_v2(
            root, freeze_sha256=freeze, population_namespace_sha256=namespace,
            admission_sha256=admission, max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
    else:
        receipt = collect_population_v2(
            root, freeze_sha256=freeze, population_namespace_sha256=namespace,
            admission_sha256=admission,
            max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT, workers=workers,
            deadline_seconds=STAGE_WATCHDOG_SECONDS,
            progress_callback=_safe_low_level_progress(progress, "d256-population"))
        receipt_value = _payload(receipt)
        _publish(receipt_path, receipt_value)
    try:
        population_sha = receipt_value["population_sha256"]
        materials = reopen_population_manifest(
            root, expected_freeze_sha256=freeze,
            expected_population_namespace_sha256=namespace,
            expected_tier="D256", expected_split=None, expected_source=None,
            expected_population_sha256=population_sha)
    except Exception as exc:
        # Test seams may return typed materials directly; production always
        # takes the authenticated population-manifest path above.
        direct = receipt if isinstance(receipt, (tuple, list)) else None
        if direct is None:
            raise WorldAfterstateV2DevRunnerError("D256 population reopen refused") from exc
        materials = tuple(direct)
    if len(materials) != 256:
        raise WorldAfterstateV2DevRunnerError("D256 population count drift")
    _report(progress, stage="d256-population", completed=256, total=256,
            active_workers=0, started=started)
    return receipt, tuple(materials), _sha_bytes(stable_read_bytes(receipt_path))


def sigma_pair_squared_from_targets(targets: Sequence[Sequence[Any]]) -> float:
    """Population variance of complete eight-replica non-incumbent advantages."""
    if type(targets) not in (tuple, list) or len(targets) < 2:
        raise WorldAfterstateV2DevRunnerError("sigma target population drift")
    rows = [tuple(row) for row in targets]
    if any(len(row) != 8 for row in rows):
        raise WorldAfterstateV2DevRunnerError("sigma requires eight replicas")
    incumbent = rows[0]
    means = []
    for row in rows[1:]:
        try:
            means.append(sum((Fraction(row[i]) - Fraction(incumbent[i])
                              for i in range(8)), Fraction(0)) / 8)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            raise WorldAfterstateV2DevRunnerError("sigma target value drift") from exc
    mean = sum(means, Fraction(0)) / len(means)
    return float(sum((value - mean) ** 2 for value in means) / len(means))


def _sigma_from_outcomes(outcomes: Sequence[Any]) -> float:
    grouped: dict[tuple[str, int], dict[int, Any]] = defaultdict(dict)
    for row in outcomes:
        grouped[(row.state_sha256, row.candidate_index)][row.replica] = row
    by_state: dict[str, dict[int, tuple[Any, ...]]] = defaultdict(dict)
    for (state, candidate), values in grouped.items():
        if set(values) != set(range(8)):
            raise WorldAfterstateV2DevRunnerError("sigma outcome replica drop")
        by_state[state][candidate] = tuple(values[i] for i in range(8))
    targets: list[Fraction] = []
    for candidates in by_state.values():
        if 0 not in candidates:
            raise WorldAfterstateV2DevRunnerError("sigma incumbent drop")
        incumbent = candidates[0]
        for candidate in sorted(candidates):
            if candidate:
                targets.append(sum((
                    Fraction(str(category_signed_level(row.signed_level_category))) -
                    Fraction(str(category_signed_level(incumbent[i].signed_level_category)))
                    for i, row in enumerate(candidates[candidate])), Fraction(0)) / 8)
    if not targets:
        raise WorldAfterstateV2DevRunnerError("sigma target population empty")
    mean = sum(targets, Fraction(0)) / len(targets)
    return float(sum((value - mean) ** 2 for value in targets) / len(targets))


def _label_stage(root: Path, name: str, materials: Sequence[Any], *, workers: int,
                 progress: Callable[[dict[str, Any]], None] | None) -> tuple[Any, tuple[Any, ...]]:
    private = root / "private" / "labels" / name
    receipt_path = private / "receipt.json"
    values = tuple(materials)
    if receipt_path.exists():
        receipt = reopen_label_stage_receipt(_json(stable_read_bytes(receipt_path), name))
    else:
        receipt = build_continuation_population_v2(
            private, values, split=("audit" if name == "audit" else "fit-select"),
            workers=workers, deadline_monotonic_ns=time.monotonic_ns() +
            STAGE_WATCHDOG_SECONDS * 1_000_000_000,
            progress=_safe_low_level_progress(progress, name))
        _publish(receipt_path, _payload(receipt))
    bundles = reopen_continuation_manifest(private, values)
    return receipt, bundles


def _train(root: Path, run_id: str, values: Sequence[Any], bundles: Sequence[Any],
           epoch_values: Sequence[Any], epoch_bundles: Sequence[Any], sigma: float,
           *, progress: Callable[[dict[str, Any]], None] | None) -> tuple[tuple[Any, ...], dict[str, Any], str, dict[str, Any]]:
    private = root / "private" / "training"
    receipt_path = private / "receipt.json"
    if receipt_path.exists():
        value = _json(stable_read_bytes(receipt_path), "training receipt")
        training_body = {key: item for key, item in value.items()
                         if key != "receipt_sha256"}
        if value.get("receipt_sha256") != _sha(training_body):
            raise WorldAfterstateV2DevRunnerError("training receipt hash drift")
        if not (private / "recovery").is_dir():
            raise WorldAfterstateV2DevRunnerError("checkpoint/recovery drop or rehash")
        raws = tuple(stable_read_bytes(private / f"checkpoint-{i}.bin") for i in range(4))
        if any(_sha_bytes(raw) != row["sha256"] for raw, row in zip(raws, value["checkpoints"], strict=True)):
            raise WorldAfterstateV2DevRunnerError("checkpoint/recovery drop or rehash")
        build = CohortTrainingBuildV2(manifest=value["manifest"], selected_checkpoint_raws=raws)
        try:
            models, manifest = reopen_cohort_build(build)
        except Exception as exc:
            raise WorldAfterstateV2DevRunnerError("checkpoint reopen refused") from exc
        return models, manifest, value["receipt_sha256"], value
    rows = tuple(row for material, bundle in zip(values, bundles, strict=True)
                 for row in build_training_examples_v2(material, bundle))
    prior = build_natural_fit_prior(rows)
    roots = tuple(build_inference_root_v2(material) for material in epoch_values)
    outcomes = tuple(row for bundle in epoch_bundles for row in bundle.candidates)
    selection = EpochSelectPopulationV2(roots=roots, outcomes=outcomes)
    config = WorldAfterstateV2TrainingConfig(
        learning_rate_ppb=10_000_000, weight_decay_ppb=0,
        gradient_norm_milli=1_000, max_epochs=20, sigma_pair_squared=sigma)
    schedule, _ = training_epoch_batches(
        rows, epoch=1, data_order_seed=0, cohort="primary",
        control_name="natural", batch_example_cap=256)
    binding = RecoveryStoreBindingV2(
        freeze_sha256=_identity(run_id, "legacy-freeze"),
        admission_sha256=_identity(run_id, "legacy-admission"),
        cohort_name="natural", seed_block=1,
        population_sha256=schedule.population_sha256,
        selection_population_sha256=selection.population_sha256,
        config_sha256=config.sha256(), member_count=4)
    store = WorldAfterstateV2RecoveryStore(private / "recovery", binding=binding)
    history = store.reopen_history()
    def recover(raws: tuple[bytes, ...]) -> None:
        store.publish_epoch(len(store.reopen_history()) + 1, raws)
    build = train_named_cohort(
        cohort_name="natural", values=rows, freeze_sha256=binding.freeze_sha256,
        config=config, selection_population=selection, seed_block=1,
        member_workers=4, torch_threads=1,
        wall_budget_nanoseconds=STAGE_WATCHDOG_SECONDS * 1_000_000_000,
        progress=_safe_low_level_progress(progress, "training"),
        recovery_history=history, recovery_callback=recover)
    models, manifest = reopen_cohort_build(build)
    raws = tuple(build.selected_checkpoint_raws)
    checkpoint_rows = []
    for i, raw in enumerate(raws):
        _publish_or_verify(private / f"checkpoint-{i}.bin", raw, "checkpoint")
        checkpoint_rows.append({"member": i, "sha256": _sha_bytes(raw)})
    body = {"schema": SCHEMA, "manifest": manifest, "checkpoints": checkpoint_rows,
            "prior": prior.payload(), "sigma_pair_squared": sigma,
            "config": config.payload()}
    value = {**body, "receipt_sha256": _sha(body)}
    _publish(receipt_path, value)
    return models, manifest, value["receipt_sha256"], value


def run_value_v2_dev_d64(root: Path, *, repo: Path, run_id: str,
                          population_workers: int = 8, label_workers: int = 8,
                          progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    if not isinstance(root, Path) or not isinstance(repo, Path) or not isinstance(run_id, str) or not run_id:
        raise WorldAfterstateV2DevRunnerError("runner arguments drift")
    if population_workers != 8 or label_workers not in (1, 2, 4, 8, 12, 16, 32):
        raise WorldAfterstateV2DevRunnerError("runner worker configuration drift")
    if root.is_symlink():
        raise WorldAfterstateV2DevRunnerError("runner root drift")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    private = root / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    if (root / "terminal.json").exists():
        return reopen_value_v2_dev_d64(root, expected_run_id=run_id)
    public_progress = _persistent_progress(root, progress)
    source_git = _git_sha(repo)
    invocation = {"run_id": run_id, "source_git_sha": source_git,
                  "invocation_sha256": _sha({"run_id": run_id, "source_git_sha": source_git})}
    invocation_path = private / "invocations" / f"{invocation['invocation_sha256']}.json"
    if invocation_path.exists():
        if _json(stable_read_bytes(invocation_path), "invocation head") != invocation:
            raise WorldAfterstateV2DevRunnerError("invocation head rehash")
    else:
        _publish(invocation_path, invocation)
    invocation_heads = tuple(sorted(
        path.stem for path in (private / "invocations").glob("*.json")))
    stage_timings: dict[str, int] = {}
    stage_started = time.monotonic_ns()
    receipt, population, population_hash = _population(
        root, run_id, repo=repo, workers=population_workers, progress=public_progress)
    stage_timings["d256_population"] = max(0, time.monotonic_ns() - stage_started)
    stage_started = time.monotonic_ns()
    subset_path = private / "d64-subset.json"
    subset = build_value_v2_dev_protocol(population)
    subset_payload = subset.payload()
    if subset_path.exists() and _json(stable_read_bytes(subset_path), "D64 subset") != subset_payload:
        raise WorldAfterstateV2DevRunnerError("D64 subset receipt drift")
    if not subset_path.exists():
        _publish(subset_path, subset_payload)
    stage_timings["d64_subset"] = max(0, time.monotonic_ns() - stage_started)
    materials = subset.materials
    fit = materials[:40]
    epoch = materials[40:46]  # natural-select epoch-select
    precision = materials[46:52]  # natural-select precision-select
    stage_started = time.monotonic_ns()
    # Only fit and epoch-selection labels exist while the model is training.
    # Precision labels are opened after its predictions have been sealed.
    fit_receipt, fit_bundles = _label_stage(
        root, "fit-epoch", materials[:46], workers=label_workers,
        progress=public_progress)
    stage_timings["fit_select_labels"] = max(0, time.monotonic_ns() - stage_started)
    fit_bundle_map = {item.deal_sha256: item for item in fit_bundles}
    epoch_bundles = tuple(fit_bundle_map[item.deal_sha256] for item in epoch)
    fit_bundles_ordered = tuple(fit_bundle_map[item.deal_sha256] for item in fit)
    natural_fit_bundles = tuple(fit_bundle_map[item.deal_sha256]
                                for item in materials[:32])
    fit_outcomes = tuple(row for bundle in natural_fit_bundles
                         for row in bundle.candidates)
    sigma = _sigma_from_outcomes(fit_outcomes)
    stage_started = time.monotonic_ns()
    models, checkpoint_manifest, training_hash, training_value = _train(
        root, run_id, fit, fit_bundles_ordered, epoch, epoch_bundles, sigma, progress=public_progress)
    stage_timings["training"] = max(0, time.monotonic_ns() - stage_started)
    prior = reopen_jeffreys_prior_v2(training_value["prior"])
    stage_started = time.monotonic_ns()
    precision_roots = tuple(build_inference_root_v2(item) for item in precision)
    all_predictions = tuple(
        row for member, model in enumerate(models)
        for row in predict_roots_v2(model, precision_roots, seed_block=1,
                                    member_index=member))
    precision_manifest = prediction_population_manifest_v2(
        precision_roots, all_predictions, split="select", control_name="natural", seed_block=1)
    precision_manifest_path = private / "precision-prediction.json"
    if precision_manifest_path.exists() and _json(stable_read_bytes(precision_manifest_path), "precision prediction") != precision_manifest:
        raise WorldAfterstateV2DevRunnerError("prediction artifact rehash")
    if not precision_manifest_path.exists():
        _publish(precision_manifest_path, precision_manifest)
    precision_receipt, precision_bundles = _label_stage(
        root, "precision-select", precision, workers=label_workers,
        progress=public_progress)
    precision_outcomes = tuple(row for item in precision_bundles for row in item.candidates)
    precision_result = evaluate_v2(precision_manifest, precision_outcomes, prior, control_name="natural", seed_block=1)
    stage_timings["precision_calibration"] = max(0, time.monotonic_ns() - stage_started)
    stage_started = time.monotonic_ns()
    audit_receipt, audit_bundles = _label_stage(root, "audit", materials[52:], workers=label_workers, progress=public_progress)
    stage_timings["audit_labels"] = max(0, time.monotonic_ns() - stage_started)
    stage_started = time.monotonic_ns()
    audit = materials[52:]
    audit_roots = tuple(build_inference_root_v2(item) for item in audit)
    audit_outcomes = tuple(row for bundle in audit_bundles for row in bundle.candidates)
    audit_predictions = tuple(
        row for member, model in enumerate(models)
        for row in predict_roots_v2(model, audit_roots, seed_block=1,
                                    member_index=member))
    audit_manifest = prediction_population_manifest_v2(
        audit_roots, audit_predictions, split="audit", control_name="natural", seed_block=1)
    audit_manifest_path = private / "audit-prediction.json"
    if audit_manifest_path.exists() and _json(stable_read_bytes(audit_manifest_path), "audit prediction") != audit_manifest:
        raise WorldAfterstateV2DevRunnerError("audit prediction artifact rehash")
    if not audit_manifest_path.exists():
        _publish(audit_manifest_path, audit_manifest)
    audit_result = evaluate_v2(audit_manifest, audit_outcomes, prior, control_name="natural", seed_block=1)
    stage_timings["audit_evaluation"] = max(0, time.monotonic_ns() - stage_started)
    body = {
        "schema": SCHEMA, "route": "D64_DEV_SEALED",
        "run_id": run_id, "source_git_sha": source_git,
        "source_git_shas": {"repo": source_git},
        "invocation_heads": [
            _json(stable_read_bytes(private / "invocations" / f"{head}.json"), "invocation head")["source_git_sha"]
            for head in invocation_heads],
        "fixed": {"population_workers": 8, "label_workers": label_workers,
                   "max_attempts_per_slot": D256_MAX_ATTEMPTS_PER_SLOT,
                   "stage_watchdog_seconds": STAGE_WATCHDOG_SECONDS,
                   "member_workers": 4, "torch_threads": 1,
                   "learning_rate_ppb": 10_000_000, "weight_decay_ppb": 0,
                   "gradient_norm_milli": 1_000, "max_epochs": 20,
                   "sigma_pair_squared": sigma},
        "population": {"receipt_sha256": population_hash, "population_sha256": _payload(receipt).get("population_sha256")},
        "d64_subset": {"receipt_sha256": _sha_bytes(stable_read_bytes(subset_path)), "manifest_sha256": subset.manifest_sha256},
        "labels": {"fit_epoch_receipt_sha256": _sha_bytes(stable_read_bytes(private / "labels" / "fit-epoch" / "receipt.json")),
                   "fit_epoch_manifest_sha256": _payload(fit_receipt).get("manifest_sha256"),
                   "precision_select_receipt_sha256": _sha_bytes(stable_read_bytes(private / "labels" / "precision-select" / "receipt.json")),
                   "precision_select_manifest_sha256": _payload(precision_receipt).get("manifest_sha256"),
                   "audit_receipt_sha256": _sha_bytes(stable_read_bytes(private / "labels" / "audit" / "receipt.json")),
                   "audit_manifest_sha256": _payload(audit_receipt).get("manifest_sha256")},
        "training": {"receipt_sha256": training_hash, "manifest_sha256": _sha(checkpoint_manifest),
                      "artifact_sha256": _sha_bytes(stable_read_bytes(root / "private" / "training" / "receipt.json")),
                      "checkpoint_sha256s": [item["sha256"] for item in training_value["checkpoints"]]},
        "precision_select": {"prediction_manifest_sha256": precision_manifest["manifest_sha256"],
                              "prediction_artifact_sha256": _sha_bytes(stable_read_bytes(precision_manifest_path)),
                              "evaluation_sha256": _sha(_payload(precision_result)),
                              "evaluation": _payload(precision_result)},
        "audit": {"prediction_manifest_sha256": audit_manifest["manifest_sha256"],
                  "prediction_artifact_sha256": _sha_bytes(stable_read_bytes(audit_manifest_path)),
                  "evaluation_sha256": _sha(_payload(audit_result)),
                  "evaluation": _payload(audit_result)},
        "stage_timings": stage_timings, "authority": dict(AUTHORITY),
    }
    terminal = {**body, "terminal_sha256": _sha(body)}
    terminal_path = root / "terminal.json"
    if terminal_path.exists():
        existing = _json(stable_read_bytes(terminal_path), "terminal seal")
        if existing != terminal:
            raise WorldAfterstateV2DevRunnerError("terminal seal rehash")
    else:
        _publish(terminal_path, terminal)
    return terminal


def reopen_value_v2_dev_d64(root: Path, *, expected_run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(root, Path) or root.is_symlink():
        raise WorldAfterstateV2DevRunnerError("runner root drift")
    raw, _ = _open(root / "terminal.json", "terminal seal")
    value = _json(raw, "terminal seal")
    if expected_run_id is not None and value.get("run_id") != expected_run_id:
        raise WorldAfterstateV2DevRunnerError("run identity drift")
    body = {key: item for key, item in value.items() if key != "terminal_sha256"}
    if value.get("schema") != SCHEMA or value.get("route") != "D64_DEV_SEALED" \
            or value.get("terminal_sha256") != _sha(body):
        raise WorldAfterstateV2DevRunnerError("terminal seal hash drift")
    if value.get("authority") != AUTHORITY:
        raise WorldAfterstateV2DevRunnerError("terminal authority drift")
    # A terminal seal is meaningful only while every referenced immutable
    # private artifact still has its sealed bytes.
    refs = {
        "d256-population-receipt.json": value.get("population", {}).get("receipt_sha256"),
        "d64-subset.json": value.get("d64_subset", {}).get("receipt_sha256"),
        "labels/fit-epoch/receipt.json": value.get("labels", {}).get(
            "fit_epoch_receipt_sha256"),
        "labels/precision-select/receipt.json": value.get("labels", {}).get(
            "precision_select_receipt_sha256"),
        "labels/audit/receipt.json": value.get("labels", {}).get(
            "audit_receipt_sha256"),
        "training/receipt.json": value.get("training", {}).get("artifact_sha256",
                                                                  value.get("training", {}).get("receipt_sha256")),
        "precision-prediction.json": value.get("precision_select", {}).get("prediction_artifact_sha256",
                                                                               value.get("precision_select", {}).get("prediction_manifest_sha256")),
        "audit-prediction.json": value.get("audit", {}).get("prediction_artifact_sha256",
                                                               value.get("audit", {}).get("prediction_manifest_sha256")),
    }
    private = root / "private"
    for relative, expected in refs.items():
        if expected is None:
            continue
        path = private / relative
        try:
            raw = stable_read_bytes(path)
        except Exception as exc:
            raise WorldAfterstateV2DevRunnerError(
                f"bound artifact missing: {relative}") from exc
        actual = _sha_bytes(raw)
        if actual != expected:
            raise WorldAfterstateV2DevRunnerError(
                f"bound artifact rehash: {relative}")
    for relative, expected in (
            ("precision-prediction.json", value.get("precision_select", {}).get("prediction_manifest_sha256")),
            ("audit-prediction.json", value.get("audit", {}).get("prediction_manifest_sha256"))):
        if expected is None:
            continue
        parsed = _json(stable_read_bytes(private / relative), relative)
        if parsed.get("manifest_sha256") != expected:
            raise WorldAfterstateV2DevRunnerError(
                f"bound prediction manifest rehash: {relative}")
    checkpoint_hashes = value.get("training", {}).get("checkpoint_sha256s", ())
    if checkpoint_hashes:
        for index, expected in enumerate(checkpoint_hashes):
            try:
                actual = _sha_bytes(stable_read_bytes(private / "training" / f"checkpoint-{index}.bin"))
            except Exception as exc:
                raise WorldAfterstateV2DevRunnerError(
                    "bound checkpoint missing") from exc
            if actual != expected:
                raise WorldAfterstateV2DevRunnerError("bound checkpoint rehash")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run_value_v2_dev_d64(args.root, repo=args.repo, run_id=args.run_id)


if __name__ == "__main__":
    main()
