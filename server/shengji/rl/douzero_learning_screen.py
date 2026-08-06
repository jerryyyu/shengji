"""Frozen, non-promotable learning screen for the Direct-Q microbaseline.

The stdlib-only launcher in ``scripts/douzero_micro_learning_screen.py`` must
admit the environment before this module is imported.  This module then binds
the compiled runtime, executes two exact training segments, captures held-out
probes and paired rounds, and independently recomputes the final gate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch

from ..ai.env import play_round
from ..ai.smart import SmartBot
from ..engine.game import Game
from .actions import enumerate_actions
from .douzero_micro import (
    ALGORITHM_SHA256,
    ALGORITHM_SOURCE_SHA256S,
    BALLOT_SCHEMA,
    EPSILON,
    EXPERIMENT,
    HISTORY_EVENT_DIM,
    ROLE_ATTACKER,
    ROLE_DEFENDER,
    ROLE_NAMES,
    UPDATE_BATCH_SIZE,
    DouZeroMicroBundle,
    OrdinaryPlayActor,
    _collate,
    acting_team_return,
    actor_batch_bytes,
    encode_public_history,
    load_actor,
    new_bundle,
    new_from_scratch_model,
    publish_initial_actor,
    terminal_attacker_return,
    validate_sample,
)
from .encode import ACT_DIM, OBS_DIM, encode_action, encode_obs
from .exact_resume import exact_resume_boundary_identity, state_digest
from .selfplay_contract import CheckpointRef, load_verified, sha256_file
from .synchronous_selfplay import (
    LearnerUpdateContext,
    SynchronousActorBatch,
    SynchronousSelfPlayRunner,
    _runner_contract_sha256,
)


SCREEN_SCHEMA = "douzero-micro-learning-screen-v1"
TRAIN_LEDGER_SCHEMA = "douzero-micro-learning-ledger-v1"
SEGMENT_SCHEMA = "douzero-micro-learning-segment-v1"
PREFLIGHT_SCHEMA = "douzero-micro-learning-preflight-v1"
PROBE_SCHEMA = "douzero-micro-heldout-probe-v1"
PROBE_MANIFEST_SCHEMA = "douzero-micro-probe-manifest-v1"
REPORT_RECORD_SCHEMA = "douzero-micro-report-round-v1"
REPORT_MANIFEST_SCHEMA = "douzero-micro-report-manifest-v1"
AGGREGATE_SCHEMA = "douzero-micro-learning-aggregate-v1"
RUNTIME_SCHEMA = "douzero-micro-learning-runtime-v1"

ITERATIONS = 512
PREFLIGHT_ITERATIONS = 32
RESUME_BOUNDARY = 256
CHECKPOINT_ITERATIONS = (0, 64, 128, 256, 512)
PROBE_SEED0 = 145_100_000
PROBE_DEALS = 128
REPORT_SEED0 = 146_000_000
REPORT_DEALS = 256
HEARTBEAT_EVERY = 16
ARMS = ("treatment", "control")
SCORE_TELEMETRY_FIELDS = (
    "loss_before", "loss_after", "gradient_norm", "prediction_min",
    "prediction_max", "target_min", "target_max",
)
REFUSED_ENVIRONMENT_KEYS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
SEED_IDENTITIES = (
    {"index": 0, "model_seed": 144_000_001,
     "learner_rng_seed": 144_010_001, "runner_root_seed": 144_020_001},
    {"index": 1, "model_seed": 144_000_002,
     "learner_rng_seed": 144_010_002, "runner_root_seed": 144_020_002},
    {"index": 2, "model_seed": 144_000_003,
     "learner_rng_seed": 144_010_003, "runner_root_seed": 144_020_003},
)

SCREEN_SPEC: dict[str, Any] = {
    "schema": SCREEN_SCHEMA,
    "claim": "learning signal only; never promotion or strength",
    "production_promotion": False,
    "base_algorithm_sha256": ALGORITHM_SHA256,
    "seeds": [dict(value) for value in SEED_IDENTITIES],
    "training": {
        "arms": list(ARMS),
        "iterations": ITERATIONS,
        "rounds_per_iteration": 1,
        "updates_per_iteration": 1,
        "update_batch_size": UPDATE_BATCH_SIZE,
        "actor_refresh": "after_every_completed_iteration",
        "control": "same_forward_backward_without_optimizer_step",
        "resume_boundary": RESUME_BOUNDARY,
        "checkpoints": list(CHECKPOINT_ITERATIONS),
    },
    "preflight": {"iterations": PREFLIGHT_ITERATIONS,
                  "score_blind": True},
    "probe": {
        "seed0": PROBE_SEED0,
        "deals": PROBE_DEALS,
        "ballot_schema": BALLOT_SCHEMA,
        "exhaustive_follows": False,
        "include_throws": False,
    },
    "report": {
        "seed0": REPORT_SEED0,
        "deals": REPORT_DEALS,
        "flips": [0, 1],
        "epsilon": EPSILON,
        "rng": "seat-tied-sha256",
        "comparison": "C512-vs-own-A0 and control-C512-vs-own-A0",
        "utility": "acting-team direct terminal bracket return",
    },
    "gate": {
        "probe_role_mse_lcb_gt": 0.0,
        "report_treatment_minus_control_lcb_gt": 0.0,
        "all_three_seed_report_means_gt": 0.0,
        "control_interval_contains": 0.0,
        "greedy_action_change": "diagnostic_only",
        "max_probe_p99_abs_q": 7.0,
        "min_final_to_initial_median_action_spread": 0.5,
    },
    "runtime": {
        "fast": True,
        "strict_voids": True,
        "refused_environment_keys": list(REFUSED_ENVIRONMENT_KEYS),
        "refusal_semantics": "key_presence_including_empty",
        "torch_deterministic": True,
    },
}
SCREEN_SPEC_SHA256 = state_digest(SCREEN_SPEC)


class LearningScreenError(RuntimeError):
    """The screen cannot support its predeclared claim."""


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _adjacent_partial(path: str | Path) -> Path:
    # Keep the lexical final path.  Resolving a concurrently substituted
    # symlink could move the marker check into an unrelated directory.
    target = Path(os.path.abspath(os.fspath(path)))
    return target.with_name(f".{target.name}.partial")


def _require_no_adjacent_partial(path: str | Path) -> None:
    partial = _adjacent_partial(path)
    if os.path.lexists(partial):
        raise LearningScreenError(
            f"incomplete adjacent artifact publication {partial}")


def _ref(value: Mapping[str, Any]) -> CheckpointRef:
    if set(value) != {"path", "sha256"}:
        raise LearningScreenError("artifact reference fields mismatch")
    ref = CheckpointRef(str(value["path"]), str(value["sha256"]))
    _require_no_adjacent_partial(ref.path)
    ref.verify()
    return ref


def _publish_bytes(path: str | Path, payload: bytes) -> CheckpointRef:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = _adjacent_partial(target)
    if os.path.lexists(target):
        raise FileExistsError(f"refusing to overwrite artifact {target}")
    try:
        with partial.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing stale artifact partial {partial}") from exc
    try:
        os.link(partial, target)
    except BaseException:
        # A remaining partial is a loud incomplete-publication marker.
        raise
    ref = CheckpointRef.capture(target)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    if ref.sha256 != expected_sha256:
        raise LearningScreenError(
            "published artifact differs from completed partial bytes")
    ref.verify()
    partial.unlink()
    _require_no_adjacent_partial(target)
    ref.verify()
    return ref


def _publish_json(path: str | Path, payload: object) -> CheckpointRef:
    return _publish_bytes(path, _canonical_json(payload))


def _load_json(ref: CheckpointRef) -> Any:
    _require_no_adjacent_partial(ref.path)
    return load_verified(
        ref, lambda path: json.loads(Path(path).read_text()))


class _ExclusiveJsonl:
    def __init__(self, path: str | Path):
        self.target = Path(path).resolve()
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.partial = _adjacent_partial(self.target)
        if os.path.lexists(self.target):
            raise FileExistsError(
                f"refusing to overwrite artifact {self.target}")
        try:
            self.handle = self.partial.open("xb")
        except FileExistsError as exc:
            raise FileExistsError(
                f"refusing stale artifact partial {self.partial}") from exc
        self.count = 0

    def write(self, value: object) -> None:
        self.handle.write(_canonical_json(value))
        self.count += 1

    def publish(self) -> CheckpointRef:
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        expected_sha256 = sha256_file(self.partial)
        os.link(self.partial, self.target)
        ref = CheckpointRef.capture(self.target)
        if ref.sha256 != expected_sha256:
            raise LearningScreenError(
                "published JSONL differs from completed partial bytes")
        ref.verify()
        self.partial.unlink()
        _require_no_adjacent_partial(self.target)
        ref.verify()
        return ref

    def abandon(self) -> None:
        if not self.handle.closed:
            self.handle.flush()
            os.fsync(self.handle.fileno())
            self.handle.close()


def _load_jsonl(ref: CheckpointRef) -> list[Any]:
    _require_no_adjacent_partial(ref.path)
    def load(path: str) -> list[Any]:
        with open(path) as handle:
            return [json.loads(line) for line in handle if line.strip()]
    return load_verified(ref, load)


def _git(*args: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True,
        text=True).stdout.strip()


def _source_identity() -> dict[str, str]:
    server = Path(__file__).resolve().parents[2]
    from ..engine import fast
    if not fast.HAVE_FAST or fast._fast is None:
        raise LearningScreenError("compiled engine is unavailable")
    return {
        **dict(ALGORITHM_SOURCE_SHA256S),
        "learning_screen": sha256_file(__file__),
        "launcher": sha256_file(
            server / "scripts" / "douzero_micro_learning_screen.py"),
        "fast_router": sha256_file(fast.__file__),
        "fast_binary": sha256_file(fast._fast.__file__),
    }


def _runtime_identity() -> dict[str, Any]:
    if os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise LearningScreenError(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1 exactly")
    present = sorted(
        name for name in REFUSED_ENVIRONMENT_KEYS if name in os.environ)
    if present:
        raise LearningScreenError(
            "experimental sampler/ballot keys must be absent: "
            f"{present}")
    from ..engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise LearningScreenError(
            "compiled engine requested but not active")
    if not torch.are_deterministic_algorithms_enabled() \
            or torch.is_deterministic_algorithms_warn_only_enabled():
        raise LearningScreenError(
            "Torch deterministic algorithms must be strict")
    dirty = _git("status", "--porcelain")
    if dirty:
        raise LearningScreenError("evidence work requires a clean tree")
    return {
        "schema": RUNTIME_SCHEMA,
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": False,
        "host": platform.node(),
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "torch": str(torch.__version__),
        "torch_git": getattr(torch.version, "git_version", None),
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "deterministic_algorithms": True,
        "deterministic_warn_only": False,
        "fast_engine": True,
        "strict_voids": True,
        "experimental_sampler_ballot_keys": [],
        "environment": {
            "SHENGJI_FAST": "1",
            "SHENGJI_REQUIRE_VOIDS": "1",
            "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),
        },
        "source_sha256s": _source_identity(),
    }


def _algorithm_sha256(arm: str) -> str:
    if arm not in ARMS:
        raise LearningScreenError(f"unsupported screen arm {arm!r}")
    return state_digest({
        "schema": "douzero-micro-learning-algorithm-v1",
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "base_algorithm_sha256": ALGORITHM_SHA256,
        "screen_source_sha256": sha256_file(__file__),
        "arm": arm,
        "optimizer_step": arm == "treatment",
    })


def _frozen_payload() -> dict[str, Any]:
    return {
        "spec": copy.deepcopy(SCREEN_SPEC),
        "spec_sha256": SCREEN_SPEC_SHA256,
        "algorithm_sha256s": {
            arm: _algorithm_sha256(arm) for arm in ARMS},
        "source_sha256s": _source_identity(),
    }


def freeze(root: str | Path) -> dict[str, CheckpointRef]:
    root = Path(root).resolve()
    runtime = _runtime_identity()
    spec_ref = _publish_json(root / "spec.json", _frozen_payload())
    runtime_ref = _publish_json(root / "runtime.json", {
        "runtime": runtime,
        "spec_ref": spec_ref.as_dict(),
    })
    return {"spec": spec_ref, "runtime": runtime_ref}


def _require_frozen(root: str | Path) \
        -> tuple[CheckpointRef, CheckpointRef, dict[str, Any]]:
    root = Path(root).resolve()
    runtime_ref = CheckpointRef.capture(root / "runtime.json")
    runtime_payload = _load_json(runtime_ref)
    if set(runtime_payload) != {"runtime", "spec_ref"}:
        raise LearningScreenError("runtime artifact fields mismatch")
    spec_ref = _ref(runtime_payload["spec_ref"])
    if _load_json(spec_ref) != _frozen_payload():
        raise LearningScreenError("frozen screen specification drift")
    current = _runtime_identity()
    if state_digest(current) != state_digest(runtime_payload["runtime"]):
        raise LearningScreenError("screen runtime identity drift")
    return spec_ref, runtime_ref, current


def _frozen_refs_only(root: str | Path) \
        -> tuple[CheckpointRef, CheckpointRef]:
    root = Path(root).resolve()
    runtime_ref = CheckpointRef.capture(root / "runtime.json")
    runtime_payload = _load_json(runtime_ref)
    if not isinstance(runtime_payload, Mapping) \
            or set(runtime_payload) != {"runtime", "spec_ref"}:
        raise LearningScreenError("runtime artifact fields mismatch")
    return _ref(runtime_payload["spec_ref"]), runtime_ref


def _require_parent_refs(payload: Mapping[str, Any], root: str | Path) -> None:
    spec_ref, runtime_ref = _frozen_refs_only(root)
    _same_ref(payload["spec_ref"], spec_ref, "screen spec parent")
    _same_ref(payload["runtime_ref"], runtime_ref, "runtime parent")


def _seed_identity(index: int) -> dict[str, int]:
    if isinstance(index, bool) or index not in range(len(SEED_IDENTITIES)):
        raise LearningScreenError("seed index must be 0, 1, or 2")
    return dict(SEED_IDENTITIES[index])


def _named_seed(*parts: object) -> int:
    payload = "|".join(str(value) for value in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _narrow_actions(rnd, seat: int):
    return enumerate_actions(
        rnd, seat, exhaustive_follows=False, include_throws=False)


def _candidate_role(*, banker: int, candidate_team: int) -> int:
    if banker not in range(4) or candidate_team not in (0, 1):
        raise LearningScreenError("invalid banker/candidate team")
    return (ROLE_DEFENDER if banker % 2 == candidate_team
            else ROLE_ATTACKER)


def _finite_tensor(value: torch.Tensor, label: str) -> None:
    if not bool(torch.all(torch.isfinite(value))):
        raise LearningScreenError(f"non-finite {label}")


@dataclass
class _TelemetryUpdate:
    arm: str
    last: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.arm not in ARMS:
            raise LearningScreenError(f"unsupported screen arm {self.arm!r}")

    def __call__(self, context: LearnerUpdateContext) -> None:
        logical = context.replay.logical_items()
        if not logical:
            raise LearningScreenError("cannot update from empty replay")
        take = min(UPDATE_BATCH_SIZE, len(logical))
        if take == len(logical):
            indices = list(range(len(logical)))
        else:
            indices = [int(value) for value in context.rng.numpy.choice(
                len(logical), size=take, replace=False)]
        samples = [logical[index] for index in indices]
        for sample in samples:
            validate_sample(
                sample,
                contract_sha256=context.batch.identity.contract_sha256)
        roles, obs, history, lengths, actions, targets = _collate(samples)
        predictions = context.learner(
            roles, obs, history, lengths, actions)
        _finite_tensor(predictions, "pre-update predictions")
        _finite_tensor(targets, "targets")
        loss = torch.mean((predictions - targets).square())
        _finite_tensor(loss.reshape(1), "loss")
        context.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_square = 0.0
        for parameter in context.learner.parameters():
            if parameter.grad is not None:
                _finite_tensor(parameter.grad, "gradient")
                gradient_square += float(torch.sum(
                    parameter.grad.detach().double().square()).item())
        gradient_norm = math.sqrt(gradient_square)
        if not math.isfinite(gradient_norm):
            raise LearningScreenError("non-finite gradient norm")
        if self.arm == "treatment":
            context.optimizer.step()
        context.optimizer.zero_grad(set_to_none=True)
        with torch.no_grad():
            post = context.learner(roles, obs, history, lengths, actions)
            post_loss = torch.mean((post - targets).square())
        _finite_tensor(post, "post-update predictions")
        _finite_tensor(post_loss.reshape(1), "post-update loss")
        for parameter in context.learner.parameters():
            _finite_tensor(parameter.detach(), "learner parameter")
        replay_roles = Counter(int(sample["role"]) for sample in logical)
        sample_roles = Counter(int(sample["role"]) for sample in samples)
        self.last = {
            "arm": self.arm,
            "selected_rows": take,
            "selected_indices": indices,
            "sample_role_counts": {
                ROLE_NAMES[role]: sample_roles.get(role, 0)
                for role in ROLE_NAMES},
            "replay_role_counts": {
                ROLE_NAMES[role]: replay_roles.get(role, 0)
                for role in ROLE_NAMES},
            "replay_size": len(logical),
            "replay_cursor": context.replay.cursor,
            "replay_game_seeds": len({
                int(sample["game_seed"]) for sample in logical}),
            "replay_actor_sha256s": sorted({
                str(sample["actor_sha256"]) for sample in logical}),
            "loss_before": float(loss.detach().item()),
            "loss_after": float(post_loss.detach().item()),
            "gradient_norm": gradient_norm,
            "prediction_min": float(predictions.detach().min().item()),
            "prediction_max": float(predictions.detach().max().item()),
            "target_min": float(targets.min().item()),
            "target_max": float(targets.max().item()),
        }


@dataclass
class _TelemetryCollector:
    expected_contract_sha256: str
    last: dict[str, Any] | None = None

    def __call__(self, identity) -> SynchronousActorBatch:
        from .douzero_micro import DouZeroMicroCollector
        batch = DouZeroMicroCollector(
            self.expected_contract_sha256)(identity)
        roles = Counter(int(sample["role"]) for sample in batch.samples)
        self.last = {
            "wire_sha256": hashlib.sha256(
                actor_batch_bytes(batch)).hexdigest(),
            "samples": len(batch.samples),
            "role_counts": {
                ROLE_NAMES[role]: roles.get(role, 0) for role in ROLE_NAMES},
            "game_seeds": sorted({
                int(sample["game_seed"]) for sample in batch.samples}),
        }
        return batch


def _seed_root(root: str | Path, index: int) -> Path:
    return Path(root).resolve() / f"seed_{index}"


def _arm_root(root: str | Path, index: int, arm: str) -> Path:
    if arm not in ARMS:
        raise LearningScreenError(f"unsupported screen arm {arm!r}")
    return _seed_root(root, index) / arm


def initialize_seed(root: str | Path, index: int) -> CheckpointRef:
    spec_ref, runtime_ref, _ = _require_frozen(root)
    identity = _seed_identity(index)
    seed_root = _seed_root(root, index)
    model = new_from_scratch_model(identity["model_seed"])
    actor_ref = publish_initial_actor(model, seed_root / "initial_actor")
    payload = {
        "schema": "douzero-micro-learning-initial-v1",
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "spec_ref": spec_ref.as_dict(),
        "runtime_ref": runtime_ref.as_dict(),
        "seed_identity": identity,
        "actor_ref": actor_ref.as_dict(),
        "learner_state_sha256": state_digest(model.state_dict()),
    }
    return _publish_json(seed_root / "initial.json", payload)


def _initial_payload(root: str | Path, index: int) \
        -> tuple[CheckpointRef, dict[str, Any], CheckpointRef]:
    path = _seed_root(root, index) / "initial.json"
    manifest_ref = CheckpointRef.capture(path)
    payload = _load_json(manifest_ref)
    expected = {
        "schema", "screen_spec_sha256", "spec_ref", "runtime_ref",
        "seed_identity", "actor_ref", "learner_state_sha256",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise LearningScreenError("initial manifest fields mismatch")
    if payload["schema"] != "douzero-micro-learning-initial-v1" \
            or payload["screen_spec_sha256"] != SCREEN_SPEC_SHA256 \
            or payload["seed_identity"] != _seed_identity(index):
        raise LearningScreenError("initial manifest identity mismatch")
    _require_parent_refs(payload, root)
    actor_ref = _ref(payload["actor_ref"])
    model = load_verified(actor_ref, load_actor)
    if state_digest(model.state_dict()) != payload["learner_state_sha256"]:
        raise LearningScreenError("initial actor state digest mismatch")
    return manifest_ref, dict(payload), actor_ref


def _new_screen_runner(
        *, bundle: DouZeroMicroBundle, actor_ref: CheckpointRef,
        snapshot_dir: Path, root_seed: int, arm: str) \
        -> SynchronousSelfPlayRunner:
    return SynchronousSelfPlayRunner(
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=_algorithm_sha256(arm),
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        snapshot_dir=snapshot_dir,
    )


def _resume_screen_runner(
        resume_ref: CheckpointRef, *, bundle: DouZeroMicroBundle,
        actor_ref: CheckpointRef, candidate_ref: CheckpointRef,
        snapshot_dir: Path, root_seed: int, arm: str) \
        -> SynchronousSelfPlayRunner:
    return SynchronousSelfPlayRunner.resume(
        resume_ref,
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=_algorithm_sha256(arm),
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        snapshot_dir=snapshot_dir,
    )


def _checkpoint_entry(
        runner: SynchronousSelfPlayRunner, path: Path) -> dict[str, Any]:
    resume_ref = runner.save_checkpoint(path)
    resume_identity = exact_resume_boundary_identity(resume_ref)
    bundle_sha256 = state_digest({
        "learner": runner.learner.state_dict(),
        "optimizer": runner.optimizer.state_dict(),
        "replay": runner.replay.state_dict(),
        "rng": runner.rng.state_dict(),
    })
    if resume_identity["bundle_sha256"] != bundle_sha256:
        raise LearningScreenError(
            "published resume bundle does not match live boundary")
    return {
        "iteration": runner.progress.next_iteration,
        "resume_ref": resume_ref.as_dict(),
        "actor_ref": runner.actor_ref.as_dict(),
        "candidate_ref": runner.candidate_ref.as_dict(),
        "bundle_sha256": bundle_sha256,
        "resume_component_sha256s": resume_identity["component_sha256s"],
        "learner_state_sha256": state_digest(runner.learner.state_dict()),
    }


def _training_row(
        *, index: int, arm: str, receipt, adopted: CheckpointRef,
        collector: _TelemetryCollector, update: _TelemetryUpdate,
        runner: SynchronousSelfPlayRunner,
        score_blind: bool) -> dict[str, Any]:
    if collector.last is None or update.last is None:
        raise LearningScreenError("missing collection/update telemetry")
    update_payload = dict(update.last)
    if score_blind:
        for name in SCORE_TELEMETRY_FIELDS:
            update_payload.pop(name)
    row = {
        "schema": TRAIN_LEDGER_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "seed_index": index,
        "arm": arm,
        "progress": receipt.progress.as_dict(),
        "batch": receipt.batch.as_dict(),
        "candidate_ref": receipt.candidate_ref.as_dict(),
        "adopted_actor_ref": adopted.as_dict(),
        "samples_added": receipt.samples_added,
        "collection": collector.last,
        "update": update_payload,
        "score_blind": score_blind,
        "learner_state_sha256": state_digest(runner.learner.state_dict()),
        "optimizer_state_sha256": state_digest(runner.optimizer.state_dict()),
        "replay_state_sha256": state_digest(runner.replay.state_dict()),
        "rng_state_sha256": state_digest(runner.rng.state_dict()),
    }
    # JSON refuses NaN, but fail before publication with a useful boundary.
    _canonical_json(row)
    return row


def _run_iterations(
        *, runner: SynchronousSelfPlayRunner, index: int, arm: str,
        start: int, stop: int, ledger: _ExclusiveJsonl,
        checkpoint_root: Path, milestones: dict[str, Any],
        heartbeat: bool = True,
        score_blind: bool = False) -> dict[str, int]:
    if runner.progress.next_iteration != start:
        raise LearningScreenError(
            f"runner starts at {runner.progress.next_iteration}, expected "
            f"{start}")
    collector = _TelemetryCollector(runner.contract_sha256)
    update = _TelemetryUpdate(arm)
    role_totals = Counter()
    samples = 0
    for iteration in range(start, stop):
        receipt = runner.run_iteration(collector, update)
        adopted = runner.adopt_current_candidate_as_actor()
        if adopted is not runner.candidate_ref \
                or adopted != receipt.candidate_ref:
            raise LearningScreenError(
                "actor refresh did not adopt the exact current candidate")
        identity = runner.next_batch_identity()
        if identity.actor_ref != adopted \
                or identity.sequence != iteration + 1:
            raise LearningScreenError("next batch does not bind adopted actor")
        ledger.write(_training_row(
            index=index,
            arm=arm,
            receipt=receipt,
            adopted=adopted,
            collector=collector,
            update=update,
            runner=runner,
            score_blind=score_blind,
        ))
        assert collector.last is not None
        for role, count in collector.last["role_counts"].items():
            role_totals[role] += int(count)
        samples += receipt.samples_added
        progress = iteration + 1
        if progress in CHECKPOINT_ITERATIONS:
            milestones[str(progress)] = _checkpoint_entry(
                runner, checkpoint_root / f"resume_{progress:03d}.pt")
        if heartbeat and progress % HEARTBEAT_EVERY == 0:
            # Deliberately omit rewards, losses and evaluation statistics.
            print(
                f"HEARTBEAT seed={index} arm={arm} "
                f"iteration={progress}/{stop} samples={samples} "
                f"replay={len(runner.replay)}",
                flush=True,
            )
    if not all(role_totals[ROLE_NAMES[role]] > 0 for role in ROLE_NAMES):
        raise LearningScreenError(
            f"training segment lacks role coverage: {dict(role_totals)}")
    return {
        "iterations": stop - start,
        "samples": samples,
        "attacker_samples": role_totals[ROLE_NAMES[ROLE_ATTACKER]],
        "defender_samples": role_totals[ROLE_NAMES[ROLE_DEFENDER]],
    }


def _segment_path(root: str | Path, index: int, arm: str,
                  segment: int) -> Path:
    return _arm_root(root, index, arm) / f"segment_{segment}.json"


def _preflight_path(root: str | Path, index: int, arm: str) -> Path:
    return (Path(root).resolve() / "preflight" / f"seed_{index}" / arm
            / "receipt.json")


def _require_preflight(root: str | Path, index: int,
                       arm: str) -> tuple[CheckpointRef, dict[str, Any]]:
    """Reopen the exact score-blind admission run before costly training."""
    ref = CheckpointRef.capture(_preflight_path(root, index, arm))
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_spec_sha256", "spec_ref", "runtime_ref",
        "seed_identity", "arm", "iterations", "totals", "ledger_ref",
        "wall_seconds", "stored_bytes", "projected_512_wall_seconds",
        "projected_512_bytes", "scores_opened", "production_promotion",
    }
    if not isinstance(payload, Mapping) \
            or set(payload) != expected_fields \
            or payload.get("schema") != PREFLIGHT_SCHEMA \
            or payload.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
            or payload.get("seed_identity") != _seed_identity(index) \
            or payload.get("arm") != arm \
            or payload.get("iterations") != PREFLIGHT_ITERATIONS \
            or payload.get("scores_opened") is not False \
            or payload.get("production_promotion") is not False:
        raise LearningScreenError("preflight receipt identity mismatch")
    _require_parent_refs(payload, root)
    wall = payload.get("wall_seconds")
    stored = payload.get("stored_bytes")
    projected_wall = payload.get("projected_512_wall_seconds")
    projected_bytes = payload.get("projected_512_bytes")
    if isinstance(wall, bool) or not isinstance(wall, (int, float)) \
            or not math.isfinite(float(wall)) or float(wall) <= 0.0 \
            or isinstance(stored, bool) or not isinstance(stored, int) \
            or stored <= 0 \
            or isinstance(projected_wall, bool) \
            or not isinstance(projected_wall, (int, float)) \
            or not math.isfinite(float(projected_wall)) \
            or float(projected_wall) != float(wall) * ITERATIONS \
            / PREFLIGHT_ITERATIONS \
            or isinstance(projected_bytes, bool) \
            or not isinstance(projected_bytes, int) \
            or projected_bytes != math.ceil(
                stored * ITERATIONS / PREFLIGHT_ITERATIONS):
        raise LearningScreenError("preflight resource projection mismatch")
    totals = payload.get("totals")
    if not isinstance(totals, Mapping) \
            or set(totals) != {
                "iterations", "samples", "attacker_samples",
                "defender_samples"} \
            or totals.get("iterations") != PREFLIGHT_ITERATIONS \
            or any(isinstance(totals.get(name), bool)
                   or not isinstance(totals.get(name), int)
                   or totals[name] <= 0
                   for name in (
                       "samples", "attacker_samples", "defender_samples")) \
            or totals["samples"] != (
                totals["attacker_samples"] + totals["defender_samples"]):
        raise LearningScreenError("preflight dose telemetry mismatch")
    rows = _load_jsonl(_ref(payload["ledger_ref"]))
    if len(rows) != PREFLIGHT_ITERATIONS:
        raise LearningScreenError("preflight ledger dose mismatch")
    _, _, previous_actor = _initial_payload(root, index)
    expected_contract_sha256 = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=_seed_identity(index)["runner_root_seed"],
        algorithm_sha256=_algorithm_sha256(arm),
    )
    samples = 0
    role_totals = Counter()
    for iteration, row in enumerate(rows):
        if not isinstance(row, Mapping) \
                or row.get("schema") != TRAIN_LEDGER_SCHEMA \
                or row.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
                or row.get("seed_index") != index \
                or row.get("arm") != arm \
                or row.get("score_blind") is not True \
                or row.get("progress") != {
                    "next_iteration": iteration + 1,
                    "next_batch": iteration + 1}:
            raise LearningScreenError("preflight ledger identity mismatch")
        batch = row.get("batch")
        collection = row.get("collection")
        if not isinstance(batch, Mapping) \
                or batch.get("sequence") != iteration \
                or batch.get("contract_sha256") \
                != expected_contract_sha256 \
                or not isinstance(collection, Mapping) \
                or row.get("samples_added") != collection.get("samples") \
                or isinstance(row.get("samples_added"), bool) \
                or not isinstance(row.get("samples_added"), int) \
                or row["samples_added"] <= 0:
            raise LearningScreenError("preflight ledger dose mismatch")
        adopted = _ref(row["adopted_actor_ref"])
        _same_ref(row["candidate_ref"], adopted,
                  "preflight exact candidate adoption")
        _same_ref(batch["actor"], previous_actor,
                  "preflight refreshed actor")
        previous_actor = adopted
        update = row.get("update")
        if not isinstance(update, Mapping) or update.get("arm") != arm \
                or any(name in update for name in SCORE_TELEMETRY_FIELDS):
            raise LearningScreenError("preflight update identity mismatch")
        samples += row["samples_added"]
        for role in ROLE_NAMES.values():
            count = collection.get("role_counts", {}).get(role)
            if isinstance(count, bool) or not isinstance(count, int) \
                    or count < 0:
                raise LearningScreenError("preflight role telemetry invalid")
            role_totals[role] += count
    if samples != totals["samples"] \
            or role_totals["attacker"] != totals["attacker_samples"] \
            or role_totals["defender"] != totals["defender_samples"]:
        raise LearningScreenError("preflight ledger totals mismatch")
    ref.verify()
    return ref, dict(payload)


def train_first_segment(root: str | Path, index: int,
                        arm: str) -> CheckpointRef:
    spec_ref, runtime_ref, _ = _require_frozen(root)
    identity = _seed_identity(index)
    initial_ref, _, actor_ref = _initial_payload(root, index)
    preflight_ref, _ = _require_preflight(root, index, arm)
    arm_root = _arm_root(root, index, arm)
    bundle = new_bundle(
        model_seed=identity["model_seed"],
        learner_rng_seed=identity["learner_rng_seed"],
    )
    if state_digest(bundle.learner.state_dict()) != \
            state_digest(load_verified(actor_ref, load_actor).state_dict()):
        raise LearningScreenError("fresh learner does not match initial actor")
    runner = _new_screen_runner(
        bundle=bundle,
        actor_ref=actor_ref,
        snapshot_dir=arm_root / "candidates",
        root_seed=identity["runner_root_seed"],
        arm=arm,
    )
    milestones = {
        "0": _checkpoint_entry(
            runner, arm_root / "checkpoints" / "resume_000.pt")}
    ledger = _ExclusiveJsonl(arm_root / "segment_0.jsonl")
    try:
        totals = _run_iterations(
            runner=runner,
            index=index,
            arm=arm,
            start=0,
            stop=RESUME_BOUNDARY,
            ledger=ledger,
            checkpoint_root=arm_root / "checkpoints",
            milestones=milestones,
        )
        ledger_ref = ledger.publish()
    except BaseException:
        ledger.abandon()
        raise
    expected_milestones = {
        str(value) for value in CHECKPOINT_ITERATIONS
        if value <= RESUME_BOUNDARY}
    if set(milestones) != expected_milestones:
        raise LearningScreenError("first-segment milestone set mismatch")
    payload = {
        "schema": SEGMENT_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "segment": 0,
        "seed_identity": identity,
        "arm": arm,
        "algorithm_sha256": _algorithm_sha256(arm),
        "spec_ref": spec_ref.as_dict(),
        "runtime_ref": runtime_ref.as_dict(),
        "initial_manifest_ref": initial_ref.as_dict(),
        "preflight_ref": preflight_ref.as_dict(),
        "parent_segment_ref": None,
        "start_iteration": 0,
        "stop_iteration": RESUME_BOUNDARY,
        "ledger_ref": ledger_ref.as_dict(),
        "totals": totals,
        "milestones": milestones,
        "requires_separate_resume": True,
        "complete": True,
        "production_promotion": False,
    }
    return _publish_json(_segment_path(root, index, arm, 0), payload)


def _load_segment(root: str | Path, index: int, arm: str,
                  segment: int) -> tuple[CheckpointRef, dict[str, Any]]:
    ref = CheckpointRef.capture(_segment_path(root, index, arm, segment))
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_spec_sha256", "segment", "seed_identity", "arm",
        "algorithm_sha256", "spec_ref", "runtime_ref",
        "initial_manifest_ref", "preflight_ref", "parent_segment_ref",
        "start_iteration", "stop_iteration", "ledger_ref", "totals", "milestones",
        "requires_separate_resume", "complete", "production_promotion",
    }
    if not isinstance(payload, Mapping) \
            or set(payload) != expected_fields \
            or payload.get("schema") != SEGMENT_SCHEMA \
            or payload.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
            or payload.get("seed_identity") != _seed_identity(index) \
            or payload.get("arm") != arm \
            or payload.get("segment") != segment \
            or payload.get("complete") is not True \
            or payload.get("production_promotion") is not False:
        raise LearningScreenError("training segment manifest mismatch")
    _require_parent_refs(payload, root)
    initial_manifest_ref = CheckpointRef.capture(
        _seed_root(root, index) / "initial.json")
    _same_ref(payload["initial_manifest_ref"], initial_manifest_ref,
              "segment initial parent")
    expected_preflight_ref, _ = _require_preflight(root, index, arm)
    _same_ref(payload["preflight_ref"], expected_preflight_ref,
              "segment preflight parent")
    _ref(payload["ledger_ref"])
    return ref, dict(payload)


def train_second_segment(root: str | Path, index: int,
                         arm: str) -> CheckpointRef:
    spec_ref, runtime_ref, _ = _require_frozen(root)
    identity = _seed_identity(index)
    initial_ref, _, _ = _initial_payload(root, index)
    parent_ref, parent = _load_segment(root, index, arm, 0)
    _validate_resume_parent(parent)
    boundary = parent.get("milestones", {}).get(str(RESUME_BOUNDARY))
    if not isinstance(boundary, Mapping) \
            or boundary.get("iteration") != RESUME_BOUNDARY:
        raise LearningScreenError("iteration-256 resume boundary missing")
    resume_ref = _ref(boundary["resume_ref"])
    actor_ref = _ref(boundary["actor_ref"])
    candidate_ref = _ref(boundary["candidate_ref"])
    if actor_ref != candidate_ref:
        raise LearningScreenError(
            "iteration-256 actor was not the adopted candidate")
    arm_root = _arm_root(root, index, arm)
    bundle = new_bundle(
        model_seed=identity["model_seed"],
        learner_rng_seed=identity["learner_rng_seed"],
    )
    runner = _resume_screen_runner(
        resume_ref,
        bundle=bundle,
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        snapshot_dir=arm_root / "candidates",
        root_seed=identity["runner_root_seed"],
        arm=arm,
    )
    if runner.progress.next_iteration != RESUME_BOUNDARY \
            or runner.next_batch_identity().actor_ref != candidate_ref:
        raise LearningScreenError("restored next actor boundary mismatch")
    milestones: dict[str, Any] = {}
    ledger = _ExclusiveJsonl(arm_root / "segment_1.jsonl")
    try:
        totals = _run_iterations(
            runner=runner,
            index=index,
            arm=arm,
            start=RESUME_BOUNDARY,
            stop=ITERATIONS,
            ledger=ledger,
            checkpoint_root=arm_root / "checkpoints",
            milestones=milestones,
        )
        ledger_ref = ledger.publish()
    except BaseException:
        ledger.abandon()
        raise
    expected_milestones = {
        str(value) for value in CHECKPOINT_ITERATIONS
        if value > RESUME_BOUNDARY}
    if set(milestones) != expected_milestones:
        raise LearningScreenError("second-segment milestone set mismatch")
    payload = {
        "schema": SEGMENT_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "segment": 1,
        "seed_identity": identity,
        "arm": arm,
        "algorithm_sha256": _algorithm_sha256(arm),
        "spec_ref": spec_ref.as_dict(),
        "runtime_ref": runtime_ref.as_dict(),
        "initial_manifest_ref": initial_ref.as_dict(),
        "preflight_ref": parent["preflight_ref"],
        "parent_segment_ref": parent_ref.as_dict(),
        "start_iteration": RESUME_BOUNDARY,
        "stop_iteration": ITERATIONS,
        "ledger_ref": ledger_ref.as_dict(),
        "totals": totals,
        "milestones": milestones,
        "requires_separate_resume": False,
        "complete": True,
        "production_promotion": False,
    }
    return _publish_json(_segment_path(root, index, arm, 1), payload)


def _validate_resume_parent(parent: Mapping[str, Any]) -> None:
    if parent.get("segment") != 0 \
            or parent.get("complete") is not True \
            or parent.get("start_iteration") != 0 \
            or parent.get("stop_iteration") != RESUME_BOUNDARY \
            or parent.get("requires_separate_resume") is not True:
        raise LearningScreenError(
            "second segment requires a complete separate iteration-256 "
            "parent")


def run_preflight(root: str | Path, index: int,
                  arm: str) -> CheckpointRef:
    spec_ref, runtime_ref, _ = _require_frozen(root)
    identity = _seed_identity(index)
    _, _, actor_ref = _initial_payload(root, index)
    preflight_root = (Path(root).resolve() / "preflight"
                      / f"seed_{index}" / arm)
    bundle = new_bundle(
        model_seed=identity["model_seed"],
        learner_rng_seed=identity["learner_rng_seed"],
    )
    runner = _new_screen_runner(
        bundle=bundle,
        actor_ref=actor_ref,
        snapshot_dir=preflight_root / "candidates",
        root_seed=identity["runner_root_seed"],
        arm=arm,
    )
    ledger = _ExclusiveJsonl(preflight_root / "ledger.jsonl")
    started = time.monotonic()
    try:
        totals = _run_iterations(
            runner=runner,
            index=index,
            arm=arm,
            start=0,
            stop=PREFLIGHT_ITERATIONS,
            ledger=ledger,
            checkpoint_root=preflight_root / "unused-checkpoints",
            milestones={},
            score_blind=True,
        )
        ledger_ref = ledger.publish()
    except BaseException:
        ledger.abandon()
        raise
    wall = time.monotonic() - started
    stored_bytes = sum(
        path.stat().st_size for path in preflight_root.rglob("*")
        if path.is_file())
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "spec_ref": spec_ref.as_dict(),
        "runtime_ref": runtime_ref.as_dict(),
        "seed_identity": identity,
        "arm": arm,
        "iterations": PREFLIGHT_ITERATIONS,
        "totals": totals,
        "ledger_ref": ledger_ref.as_dict(),
        "wall_seconds": wall,
        "stored_bytes": stored_bytes,
        "projected_512_wall_seconds": wall * ITERATIONS
        / PREFLIGHT_ITERATIONS,
        "projected_512_bytes": math.ceil(
            stored_bytes * ITERATIONS / PREFLIGHT_ITERATIONS),
        "scores_opened": False,
        "production_promotion": False,
    }
    return _publish_json(preflight_root / "receipt.json", payload)


def _ballot_identity() -> dict[str, Any]:
    return {
        "schema": BALLOT_SCHEMA,
        "enumerator": "enumerate_actions",
        "exhaustive_follows": False,
        "include_throws": False,
        "actions_source_sha256": ALGORITHM_SOURCE_SHA256S["actions"],
    }


class _SetupComposite:
    """Smart setup with one exact Direct-Q ordinary-play actor."""

    def __init__(self, actor: OrdinaryPlayActor):
        self.actor = actor
        self.control = SmartBot()

    def decide_declare(self, rnd, seat, final=False):
        return self.control.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        return self.control.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        return self.actor.decide_play(rnd, seat)


class _ProbeComposite(_SetupComposite):
    def __init__(self, actor: OrdinaryPlayActor,
                 shared_records: list[dict[str, Any]]):
        super().__init__(actor)
        self.shared_records = shared_records

    def decide_play(self, rnd, seat):
        # This is the exact training/play ballot.  The wrapped production
        # actor independently enumerates it and selects the action, making a
        # future probe-only widening or ordering drift observable.
        actions = _narrow_actions(rnd, seat)
        if not actions:
            raise LearningScreenError("held-out probe ballot is empty")
        obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32)
        history = encode_public_history(rnd, seat)
        encoded = np.asarray(
            [encode_action(action, rnd) for action in actions],
            dtype=np.float32,
        ).reshape(-1, ACT_DIM)
        chosen = super().decide_play(rnd, seat)
        chosen_key = tuple(sorted(chosen))
        matches = [
            position for position, action in enumerate(actions)
            if tuple(sorted(action)) == chosen_key]
        if len(matches) != 1:
            raise LearningScreenError(
                "production actor choice does not bind one narrow ballot row")
        self.shared_records.append({
            "seat": seat,
            "role": ROLE_ATTACKER if rnd.is_attacker(seat)
            else ROLE_DEFENDER,
            "decision_index": len(self.shared_records),
            "obs": obs.tolist(),
            "history": history.tolist(),
            "history_length": len(history),
            "actions": encoded.tolist(),
            "action_cards": [list(action) for action in actions],
            "chosen_index": matches[0],
            "chosen_cards": list(chosen),
        })
        return chosen


def _seat_actor(model, *, domain: str, deal_seed: int,
                seat: int) -> OrdinaryPlayActor:
    rng = random.Random(_named_seed(
        SCREEN_SCHEMA, domain, deal_seed, seat))
    return OrdinaryPlayActor(model, rng)


def capture_probes(root: str | Path, index: int) -> CheckpointRef:
    spec_ref, runtime_ref, _ = _require_frozen(root)
    initial_manifest_ref, _, actor_ref = _initial_payload(root, index)
    model = load_verified(actor_ref, load_actor)
    probe_root = Path(root).resolve() / "probes"
    writer = _ExclusiveJsonl(probe_root / f"seed_{index}.jsonl")
    role_counts = Counter()
    try:
        for deal_seed in range(PROBE_SEED0, PROBE_SEED0 + PROBE_DEALS):
            decisions: list[dict[str, Any]] = []
            policies = [
                _ProbeComposite(
                    _seat_actor(
                        model,
                        domain="probe-epsilon",
                        deal_seed=deal_seed,
                        seat=seat,
                    ),
                    decisions,
                )
                for seat in range(4)
            ]
            game = Game(random.Random(deal_seed))
            log = play_round(game, policies)
            attacker_return = terminal_attacker_return(log.attacker_points)
            if not decisions:
                raise LearningScreenError("held-out deal has no decisions")
            for decision in decisions:
                role = int(decision["role"])
                role_counts[ROLE_NAMES[role]] += 1
                writer.write({
                    "schema": PROBE_SCHEMA,
                    "screen_spec_sha256": SCREEN_SPEC_SHA256,
                    "seed_index": index,
                    "deal_seed": deal_seed,
                    "attacker_points": log.attacker_points,
                    "attacker_return": attacker_return,
                    "target": acting_team_return(attacker_return, role),
                    "ballot": _ballot_identity(),
                    **decision,
                })
        raw_ref = writer.publish()
    except BaseException:
        writer.abandon()
        raise
    actor_ref.verify()
    if not all(role_counts[ROLE_NAMES[role]] > 0 for role in ROLE_NAMES):
        raise LearningScreenError(
            f"probe lacks role coverage: {dict(role_counts)}")
    manifest = {
        "schema": PROBE_MANIFEST_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "spec_ref": spec_ref.as_dict(),
        "runtime_ref": runtime_ref.as_dict(),
        "initial_manifest_ref": initial_manifest_ref.as_dict(),
        "seed_index": index,
        "actor_ref": actor_ref.as_dict(),
        "seed0": PROBE_SEED0,
        "deals": PROBE_DEALS,
        "decision_rows": writer.count,
        "role_counts": dict(role_counts),
        "ballot": _ballot_identity(),
        "raw_ref": raw_ref.as_dict(),
        "scores_opened": False,
        "production_promotion": False,
    }
    return _publish_json(probe_root / f"seed_{index}.json", manifest)


def _final_candidate(
        root: str | Path, index: int, arm: str) \
        -> tuple[CheckpointRef, CheckpointRef, dict[str, Any]]:
    segment_ref, segment = _load_segment(root, index, arm, 1)
    final = segment.get("milestones", {}).get(str(ITERATIONS))
    if not isinstance(final, Mapping) or final.get("iteration") != ITERATIONS:
        raise LearningScreenError("final candidate milestone missing")
    actor_ref = _ref(final["actor_ref"])
    candidate_ref = _ref(final["candidate_ref"])
    if actor_ref != candidate_ref:
        raise LearningScreenError("final actor is not exact final candidate")
    return segment_ref, candidate_ref, dict(final)


def _model_state_sha256(ref: CheckpointRef) -> str:
    return state_digest(load_verified(ref, load_actor).state_dict())


def _report_round(
        *, candidate_model, initial_model, candidate_ref: CheckpointRef,
        initial_ref: CheckpointRef, index: int, arm: str,
        deal_seed: int, flip: int) -> dict[str, Any]:
    candidate_team = flip
    actors = []
    policies = []
    for seat in range(4):
        model = candidate_model if seat % 2 == candidate_team else initial_model
        actor = _seat_actor(
            model,
            domain="report-epsilon",
            deal_seed=deal_seed,
            seat=seat,
        )
        actors.append(actor)
        policies.append(_SetupComposite(actor))
    game = Game(random.Random(deal_seed))
    log = play_round(game, policies)
    if game.round is None:
        raise LearningScreenError("REPORT round ended without round state")
    role = _candidate_role(
        banker=int(log.banker), candidate_team=candidate_team)
    attacker_return = terminal_attacker_return(log.attacker_points)
    candidate_decisions = sum(
        len(actors[seat].records) for seat in range(4)
        if seat % 2 == candidate_team)
    initial_decisions = sum(
        len(actors[seat].records) for seat in range(4)
        if seat % 2 != candidate_team)
    return {
        "schema": REPORT_RECORD_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "seed_index": index,
        "arm": arm,
        "deal_seed": deal_seed,
        "flip": flip,
        "candidate_team": candidate_team,
        "candidate_role": ROLE_NAMES[role],
        "banker": log.banker,
        "attacker_points": log.attacker_points,
        "attacker_return": attacker_return,
        "candidate_signed_return": acting_team_return(
            attacker_return, role),
        "candidate_won": int(log.winner_team == candidate_team),
        "candidate_decisions": candidate_decisions,
        "initial_decisions": initial_decisions,
        "candidate_ref": candidate_ref.as_dict(),
        "initial_ref": initial_ref.as_dict(),
        "epsilon": EPSILON,
        "ballot": _ballot_identity(),
        "rng_identity": "seat-tied-sha256",
    }


def evaluate_report(root: str | Path, index: int,
                    arm: str) -> CheckpointRef:
    spec_ref, runtime_ref, _ = _require_frozen(root)
    initial_manifest_ref, initial, initial_ref = _initial_payload(root, index)
    segment_ref, candidate_ref, _ = _final_candidate(root, index, arm)
    initial_model = load_verified(initial_ref, load_actor)
    candidate_model = load_verified(candidate_ref, load_actor)
    initial_state = str(initial["learner_state_sha256"])
    candidate_state = state_digest(candidate_model.state_dict())
    if arm == "control" and candidate_state != initial_state:
        raise LearningScreenError("no-step control learner changed")
    if arm == "treatment" and candidate_state == initial_state:
        raise LearningScreenError("treatment learner did not change")
    report_root = Path(root).resolve() / "report"
    writer = _ExclusiveJsonl(report_root / f"seed_{index}_{arm}.jsonl")
    role_counts = Counter()
    wins = 0
    try:
        for deal_seed in range(REPORT_SEED0, REPORT_SEED0 + REPORT_DEALS):
            for flip in (0, 1):
                row = _report_round(
                    candidate_model=candidate_model,
                    initial_model=initial_model,
                    candidate_ref=candidate_ref,
                    initial_ref=initial_ref,
                    index=index,
                    arm=arm,
                    deal_seed=deal_seed,
                    flip=flip,
                )
                role_counts[row["candidate_role"]] += 1
                wins += int(row["candidate_won"])
                writer.write(row)
        raw_ref = writer.publish()
    except BaseException:
        writer.abandon()
        raise
    candidate_ref.verify()
    initial_ref.verify()
    if role_counts != Counter({"attacker": REPORT_DEALS,
                               "defender": REPORT_DEALS}):
        # Smart setup is identical in both flips; the candidate team must
        # occupy each role exactly once for every deal.
        raise LearningScreenError(
            f"REPORT role/flip coverage mismatch: {dict(role_counts)}")
    manifest = {
        "schema": REPORT_MANIFEST_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "spec_ref": spec_ref.as_dict(),
        "runtime_ref": runtime_ref.as_dict(),
        "initial_manifest_ref": initial_manifest_ref.as_dict(),
        "segment_ref": segment_ref.as_dict(),
        "seed_index": index,
        "arm": arm,
        "candidate_ref": candidate_ref.as_dict(),
        "candidate_state_sha256": candidate_state,
        "initial_ref": initial_ref.as_dict(),
        "initial_state_sha256": initial_state,
        "seed0": REPORT_SEED0,
        "deals": REPORT_DEALS,
        "flips": [0, 1],
        "rounds": writer.count,
        "role_counts": dict(role_counts),
        "wins": wins,
        "epsilon": EPSILON,
        "rng_identity": "seat-tied-sha256",
        "ballot": _ballot_identity(),
        "raw_ref": raw_ref.as_dict(),
        "production_promotion": False,
    }
    return _publish_json(
        report_root / f"seed_{index}_{arm}.json", manifest)


def paired_summary(values: list[float]) -> dict[str, float | int]:
    if len(values) < 2:
        raise LearningScreenError(
            "paired summary requires at least two independent clusters")
    if not all(isinstance(value, (int, float))
               and math.isfinite(float(value)) for value in values):
        raise LearningScreenError("paired summary contains non-finite values")
    array = np.asarray(values, dtype=np.float64)
    mean = float(array.mean())
    se = float(array.std(ddof=1) / math.sqrt(len(array)))
    half = 1.96 * se
    return {
        "n": len(values),
        "mean": mean,
        "se": se,
        "half95": half,
        "lcb95": mean - half,
        "ucb95": mean + half,
    }


def learning_gate_decision(
        *, pooled_probe: Mapping[str, Mapping[str, float]],
        seed_probe_means: Mapping[str, float],
        report_effect: Mapping[str, float],
        report_control: Mapping[str, float],
        report_seed_effects: Mapping[str, float],
        q_health: bool) -> tuple[dict[str, bool], bool, list[str]]:
    gates = {
        "probe_attacker_mse_lcb_positive":
            float(pooled_probe["attacker"]["lcb95"]) > 0.0,
        "probe_defender_mse_lcb_positive":
            float(pooled_probe["defender"]["lcb95"]) > 0.0,
        "all_seed_probe_means_positive": all(
            float(value) > 0.0 for value in seed_probe_means.values()),
        "report_treatment_minus_control_lcb_positive":
            float(report_effect["lcb95"]) > 0.0,
        "all_seed_report_means_positive": all(
            float(value) > 0.0 for value in report_seed_effects.values()),
        "control_interval_contains_zero":
            float(report_control["lcb95"]) <= 0.0
            <= float(report_control["ucb95"]),
        "q_health": q_health is True,
    }
    passed = all(gates.values())
    failures = sorted(name for name, value in gates.items() if not value)
    return gates, passed, failures


def exact_two_flip_means(
        rows: list[Mapping[str, Any]], *, seed0: int, deals: int,
        value_field: str) -> dict[int, float]:
    expected = {
        (seed, flip)
        for seed in range(seed0, seed0 + deals)
        for flip in (0, 1)}
    seen = set()
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        key = (row.get("deal_seed"), row.get("flip"))
        if key not in expected or key in seen:
            raise LearningScreenError("paired records have duplicate/extra flip")
        value = row.get(value_field)
        if not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise LearningScreenError("paired record value is non-finite")
        seen.add(key)
        grouped[int(key[0])].append(float(value))
    if seen != expected \
            or any(len(values) != 2 for values in grouped.values()):
        raise LearningScreenError("paired records lack exact two-flip coverage")
    return {
        deal: float(np.mean(values))
        for deal, values in sorted(grouped.items())}


def _same_ref(value: Mapping[str, Any], expected: CheckpointRef,
              label: str) -> None:
    if dict(value) != expected.as_dict():
        raise LearningScreenError(f"{label} artifact identity mismatch")


def _validate_training(
        root: str | Path, index: int, arm: str,
        initial_ref: CheckpointRef, initial_state_sha256: str) \
        -> tuple[dict[str, CheckpointRef], dict[str, Any]]:
    segment0_ref, segment0 = _load_segment(root, index, arm, 0)
    segment1_ref, segment1 = _load_segment(root, index, arm, 1)
    _same_ref(segment1["parent_segment_ref"], segment0_ref,
              "second-segment parent")
    if segment0.get("start_iteration") != 0 \
            or segment0.get("stop_iteration") != RESUME_BOUNDARY \
            or segment1.get("start_iteration") != RESUME_BOUNDARY \
            or segment1.get("stop_iteration") != ITERATIONS:
        raise LearningScreenError("training segment dose mismatch")
    if segment0.get("requires_separate_resume") is not True \
            or segment1.get("requires_separate_resume") is not False:
        raise LearningScreenError("separate resume contract mismatch")
    if segment0.get("algorithm_sha256") != _algorithm_sha256(arm) \
            or segment1.get("algorithm_sha256") != _algorithm_sha256(arm):
        raise LearningScreenError("training algorithm identity mismatch")
    segment_rows = [
        _load_jsonl(_ref(segment0["ledger_ref"])),
        _load_jsonl(_ref(segment1["ledger_ref"])),
    ]
    expected_segment_iterations = (
        RESUME_BOUNDARY, ITERATIONS - RESUME_BOUNDARY)
    if any(len(values) != expected_segment_iterations[position]
           for position, values in enumerate(segment_rows)):
        raise LearningScreenError("training segment ledger dose mismatch")
    rows = segment_rows[0] + segment_rows[1]
    if len(rows) != ITERATIONS:
        raise LearningScreenError(
            f"training ledger has {len(rows)} rows, expected {ITERATIONS}")
    previous_actor = initial_ref
    role_totals = Counter()
    segment_role_totals = [Counter(), Counter()]
    segment_samples = [0, 0]
    actor_by_progress: dict[int, CheckpointRef] = {0: initial_ref}
    seen_refs: dict[tuple[str, str], CheckpointRef] = {}
    expected_contract_sha256 = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=_seed_identity(index)["runner_root_seed"],
        algorithm_sha256=_algorithm_sha256(arm),
    )
    for iteration, row in enumerate(rows):
        if not isinstance(row, Mapping) \
                or row.get("schema") != TRAIN_LEDGER_SCHEMA \
                or row.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
                or row.get("seed_index") != index \
                or row.get("arm") != arm \
                or row.get("score_blind") is not False:
            raise LearningScreenError(
                f"training row {iteration} identity mismatch")
        progress = row.get("progress")
        batch = row.get("batch")
        if progress != {"next_iteration": iteration + 1,
                        "next_batch": iteration + 1} \
                or not isinstance(batch, Mapping) \
                or batch.get("sequence") != iteration:
            raise LearningScreenError(
                f"training row {iteration} progress mismatch")
        _same_ref(batch["actor"], previous_actor,
                  f"training row {iteration} actor")
        candidate = _ref(row["candidate_ref"])
        _same_ref(row["adopted_actor_ref"], candidate,
                  f"training row {iteration} adoption")
        previous_actor = candidate
        actor_by_progress[iteration + 1] = candidate
        seen_refs[(candidate.path, candidate.sha256)] = candidate
        if batch.get("contract_sha256") != expected_contract_sha256:
            raise LearningScreenError("runner contract changed within training")
        collection = row.get("collection")
        update = row.get("update")
        if not isinstance(collection, Mapping) \
                or not isinstance(update, Mapping):
            raise LearningScreenError("training telemetry is missing")
        if row.get("samples_added") != collection.get("samples") \
                or isinstance(row.get("samples_added"), bool) \
                or not isinstance(row.get("samples_added"), int) \
                or row["samples_added"] <= 0:
            raise LearningScreenError("collection dose mismatch")
        segment_index = int(iteration >= RESUME_BOUNDARY)
        segment_samples[segment_index] += row["samples_added"]
        for role in ROLE_NAMES.values():
            count = collection.get("role_counts", {}).get(role)
            if isinstance(count, bool) or not isinstance(count, int) \
                    or count < 0:
                raise LearningScreenError("collection role telemetry invalid")
            role_totals[role] += count
            segment_role_totals[segment_index][role] += count
        selected = update.get("selected_rows")
        if isinstance(selected, bool) or not isinstance(selected, int) \
                or not 1 <= selected <= UPDATE_BATCH_SIZE:
            raise LearningScreenError("update row dose invalid")
        for label in (
                "loss_before", "loss_after", "gradient_norm",
                "prediction_min", "prediction_max", "target_min",
                "target_max"):
            value = update.get(label)
            if not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)):
                raise LearningScreenError(
                    f"non-finite training telemetry {label}")
        if float(update["target_min"]) < -3.5 \
                or float(update["target_max"]) > 3.5:
            raise LearningScreenError("training target outside reward support")
        if update.get("arm") != arm \
                or isinstance(update.get("replay_size"), bool) \
                or not isinstance(update.get("replay_size"), int) \
                or not 1 <= update["replay_size"] <= 256:
            raise LearningScreenError("update replay telemetry mismatch")
    for ref in seen_refs.values():
        ref.verify()
    if not all(role_totals[role] > 0 for role in ROLE_NAMES.values()):
        raise LearningScreenError(
            f"full training lacks role coverage: {dict(role_totals)}")
    for segment_index, segment in enumerate((segment0, segment1)):
        totals = segment.get("totals")
        expected_totals = {
            "iterations": expected_segment_iterations[segment_index],
            "samples": segment_samples[segment_index],
            "attacker_samples": segment_role_totals[segment_index][
                "attacker"],
            "defender_samples": segment_role_totals[segment_index][
                "defender"],
        }
        if totals != expected_totals:
            raise LearningScreenError(
                f"training segment {segment_index} totals mismatch")
    milestones = {
        **segment0.get("milestones", {}),
        **segment1.get("milestones", {}),
    }
    if set(milestones) != {str(value) for value in CHECKPOINT_ITERATIONS}:
        raise LearningScreenError("training milestone set mismatch")
    checkpoints: dict[str, CheckpointRef] = {"0": initial_ref}
    for iteration in CHECKPOINT_ITERATIONS:
        milestone = milestones[str(iteration)]
        expected_milestone_fields = {
            "iteration", "resume_ref", "actor_ref", "candidate_ref",
            "bundle_sha256", "resume_component_sha256s",
            "learner_state_sha256",
        }
        if not isinstance(milestone, Mapping) \
                or set(milestone) != expected_milestone_fields \
                or milestone.get("iteration") != iteration:
            raise LearningScreenError("checkpoint progress mismatch")
        resume_ref = _ref(milestone["resume_ref"])
        actor = _ref(milestone["actor_ref"])
        candidate = _ref(milestone["candidate_ref"])
        resume_identity = exact_resume_boundary_identity(resume_ref)
        if resume_identity.get("experiment") != EXPERIMENT \
                or resume_identity.get("contract_sha256") \
                != expected_contract_sha256 \
                or resume_identity.get("progress") != {
                    "next_iteration": iteration,
                    "next_batch": iteration} \
                or resume_identity.get("actor_ref") != actor.as_dict() \
                or resume_identity.get("candidate_ref") \
                != candidate.as_dict() \
                or resume_identity.get("bundle_sha256") \
                != milestone.get("bundle_sha256") \
                or resume_identity.get("component_sha256s") \
                != milestone.get("resume_component_sha256s"):
            raise LearningScreenError(
                f"checkpoint {iteration} resume-boundary mismatch")
        model_state = _model_state_sha256(candidate)
        if milestone.get("learner_state_sha256") != model_state:
            raise LearningScreenError(
                f"checkpoint {iteration} learner-state mismatch")
        if resume_identity["component_sha256s"]["learner"] != model_state:
            raise LearningScreenError(
                f"checkpoint {iteration} resume learner mismatch")
        if iteration == 0:
            if actor != initial_ref or model_state != initial_state_sha256:
                raise LearningScreenError(
                    "checkpoint 0 does not preserve the initial learner")
        else:
            if actor != candidate \
                    or candidate != actor_by_progress[iteration]:
                raise LearningScreenError(
                    f"checkpoint {iteration} did not preserve exact adopted "
                    "actor")
            checkpoints[str(iteration)] = candidate
            if arm == "control" \
                    and model_state != initial_state_sha256:
                raise LearningScreenError(
                    f"control learner changed by checkpoint {iteration}")
    final_state = _model_state_sha256(checkpoints[str(ITERATIONS)])
    if arm == "control" and final_state != initial_state_sha256:
        raise LearningScreenError("control learner state changed")
    if arm == "treatment" and final_state == initial_state_sha256:
        raise LearningScreenError("treatment learner state did not change")
    return checkpoints, {
        "segment_0": segment0_ref.as_dict(),
        "segment_1": segment1_ref.as_dict(),
        "role_counts": dict(role_totals),
        "runner_contract_sha256": expected_contract_sha256,
        "final_state_sha256": final_state,
    }


def _validated_probe(
        root: str | Path, index: int, initial_ref: CheckpointRef) \
        -> tuple[CheckpointRef, list[dict[str, Any]]]:
    manifest_ref = CheckpointRef.capture(
        Path(root).resolve() / "probes" / f"seed_{index}.json")
    manifest = _load_json(manifest_ref)
    expected_fields = {
        "schema", "screen_spec_sha256", "spec_ref", "runtime_ref",
        "initial_manifest_ref", "seed_index", "actor_ref", "seed0",
        "deals", "decision_rows", "role_counts", "ballot", "raw_ref",
        "scores_opened", "production_promotion",
    }
    if not isinstance(manifest, Mapping) \
            or set(manifest) != expected_fields \
            or manifest.get("schema") != PROBE_MANIFEST_SCHEMA \
            or manifest.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
            or manifest.get("seed_index") != index \
            or manifest.get("seed0") != PROBE_SEED0 \
            or manifest.get("deals") != PROBE_DEALS \
            or manifest.get("ballot") != _ballot_identity() \
            or manifest.get("scores_opened") is not False \
            or manifest.get("production_promotion") is not False:
        raise LearningScreenError("probe manifest mismatch")
    _require_parent_refs(manifest, root)
    initial_manifest_ref = CheckpointRef.capture(
        _seed_root(root, index) / "initial.json")
    _same_ref(manifest["initial_manifest_ref"], initial_manifest_ref,
              "probe initial parent")
    _same_ref(manifest["actor_ref"], initial_ref, "probe actor")
    rows = _load_jsonl(_ref(manifest["raw_ref"]))
    if len(rows) != manifest.get("decision_rows") or not rows:
        raise LearningScreenError("probe row count mismatch")
    by_deal = defaultdict(set)
    rows_by_deal: dict[int, list[dict[str, Any]]] = defaultdict(list)
    roles = Counter()
    expected_deals = set(range(PROBE_SEED0, PROBE_SEED0 + PROBE_DEALS))
    for row in rows:
        if not isinstance(row, Mapping) \
                or row.get("schema") != PROBE_SCHEMA \
                or row.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
                or row.get("seed_index") != index \
                or row.get("ballot") != _ballot_identity():
            raise LearningScreenError("probe row identity mismatch")
        deal = row.get("deal_seed")
        decision = row.get("decision_index")
        role = row.get("role")
        if deal not in expected_deals \
                or not isinstance(decision, int) or decision < 0 \
                or role not in ROLE_NAMES:
            raise LearningScreenError("probe row key fields invalid")
        if decision in by_deal[deal]:
            raise LearningScreenError("duplicate probe decision identity")
        by_deal[deal].add(decision)
        rows_by_deal[int(deal)].append(dict(row))
        roles[ROLE_NAMES[role]] += 1
        obs = np.asarray(row.get("obs"), dtype=np.float32)
        history_length = row.get("history_length")
        if not isinstance(history_length, int) or history_length < 0:
            raise LearningScreenError("probe history length invalid")
        history = np.asarray(
            row.get("history"), dtype=np.float32).reshape(
                -1, HISTORY_EVENT_DIM)
        actions = np.asarray(row.get("actions"), dtype=np.float32)
        if obs.shape != (OBS_DIM,) \
                or len(history) != history_length \
                or actions.ndim != 2 \
                or actions.shape[1:] != (ACT_DIM,) \
                or len(actions) == 0 \
                or not np.all(np.isfinite(obs)) \
                or not np.all(np.isfinite(history)) \
                or not np.all(np.isfinite(actions)):
            raise LearningScreenError("probe tensor shape/value mismatch")
        chosen = row.get("chosen_index")
        if not isinstance(chosen, int) or chosen not in range(len(actions)):
            raise LearningScreenError("probe chosen index invalid")
        attacker_return = terminal_attacker_return(
            int(row.get("attacker_points")))
        if row.get("attacker_return") != attacker_return \
                or row.get("target") != acting_team_return(
                    attacker_return, role):
            raise LearningScreenError("probe signed target mismatch")
    if set(by_deal) != expected_deals \
            or not all(roles[ROLE_NAMES[role]] > 0 for role in ROLE_NAMES):
        raise LearningScreenError("probe deal/role coverage mismatch")
    if dict(roles) != manifest.get("role_counts"):
        raise LearningScreenError("probe role totals mismatch")
    model = load_verified(initial_ref, load_actor)
    for deal_seed in sorted(expected_deals):
        decisions: list[dict[str, Any]] = []
        policies = [
            _ProbeComposite(
                _seat_actor(
                    model,
                    domain="probe-epsilon",
                    deal_seed=deal_seed,
                    seat=seat,
                ),
                decisions,
            )
            for seat in range(4)
        ]
        game = Game(random.Random(deal_seed))
        log = play_round(game, policies)
        attacker_return = terminal_attacker_return(log.attacker_points)
        expected_rows = [
            {
                "schema": PROBE_SCHEMA,
                "screen_spec_sha256": SCREEN_SPEC_SHA256,
                "seed_index": index,
                "deal_seed": deal_seed,
                "attacker_points": log.attacker_points,
                "attacker_return": attacker_return,
                "target": acting_team_return(
                    attacker_return, int(decision["role"])),
                "ballot": _ballot_identity(),
                **decision,
            }
            for decision in decisions
        ]
        stored_rows = sorted(
            rows_by_deal[deal_seed], key=lambda row: row["decision_index"])
        if _canonical_json(stored_rows) != _canonical_json(expected_rows):
            raise LearningScreenError(
                f"probe semantic replay mismatch for deal {deal_seed}")
    return manifest_ref, [dict(row) for row in rows]


def _score_probes(ref: CheckpointRef,
                  rows: list[dict[str, Any]]) -> dict[str, Any]:
    model = load_verified(ref, load_actor)
    errors: dict[int, dict[int, list[float]]] = {
        role: defaultdict(list) for role in ROLE_NAMES}
    absolute_errors: dict[int, list[float]] = {
        role: [] for role in ROLE_NAMES}
    ranges: dict[int, list[float]] = {role: [] for role in ROLE_NAMES}
    q_abs: dict[int, list[float]] = {role: [] for role in ROLE_NAMES}
    greedy: list[int] = []
    for row in rows:
        role = int(row["role"])
        obs = np.asarray(row["obs"], dtype=np.float32)
        history = np.asarray(
            row["history"], dtype=np.float32).reshape(
                -1, HISTORY_EVENT_DIM)
        actions = np.asarray(row["actions"], dtype=np.float32).reshape(
            -1, ACT_DIM)
        values = model.score_candidates(
            role=role, obs=obs, history=history, actions=actions)
        _finite_tensor(values, "probe Q values")
        array = values.detach().cpu().numpy().astype(np.float64)
        chosen_q = float(array[int(row["chosen_index"])])
        target = float(row["target"])
        error = (chosen_q - target) ** 2
        errors[role][int(row["deal_seed"])].append(error)
        absolute_errors[role].append(abs(chosen_q - target))
        q_abs[role].extend(np.abs(array).tolist())
        if len(array) > 1:
            ranges[role].append(float(array.max() - array.min()))
        greedy.append(int(np.argmax(array)))
    per_deal = {
        ROLE_NAMES[role]: {
            str(deal): float(np.mean(values))
            for deal, values in sorted(errors[role].items())}
        for role in ROLE_NAMES}
    summary = {}
    for role in ROLE_NAMES:
        name = ROLE_NAMES[role]
        all_errors = [
            value for values in errors[role].values() for value in values]
        if not all_errors or not ranges[role] or not q_abs[role]:
            raise LearningScreenError(
                f"probe scores lack {name} action coverage")
        summary[name] = {
            "mse": float(np.mean(all_errors)),
            "mae": float(np.mean(absolute_errors[role])),
            "median_action_spread": float(np.median(ranges[role])),
            "p99_action_spread": float(np.percentile(ranges[role], 99)),
            "p99_abs_q": float(np.percentile(q_abs[role], 99)),
            "multi_action_states": len(ranges[role]),
        }
    return {"per_deal_mse": per_deal, "summary": summary,
            "greedy": greedy}


def _validated_report(
        root: str | Path, index: int, arm: str,
        expected_candidate: CheckpointRef,
        initial_ref: CheckpointRef) \
        -> tuple[CheckpointRef, dict[int, float]]:
    manifest_ref = CheckpointRef.capture(
        Path(root).resolve() / "report" / f"seed_{index}_{arm}.json")
    manifest = _load_json(manifest_ref)
    expected_fields = {
        "schema", "screen_spec_sha256", "spec_ref", "runtime_ref",
        "initial_manifest_ref", "segment_ref", "seed_index", "arm",
        "candidate_ref", "candidate_state_sha256", "initial_ref",
        "initial_state_sha256", "seed0", "deals", "flips", "rounds",
        "role_counts", "wins", "epsilon", "rng_identity", "ballot",
        "raw_ref", "production_promotion",
    }
    if not isinstance(manifest, Mapping) \
            or set(manifest) != expected_fields \
            or manifest.get("schema") != REPORT_MANIFEST_SCHEMA \
            or manifest.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
            or manifest.get("seed_index") != index \
            or manifest.get("arm") != arm \
            or manifest.get("seed0") != REPORT_SEED0 \
            or manifest.get("deals") != REPORT_DEALS \
            or manifest.get("flips") != [0, 1] \
            or manifest.get("rounds") != 2 * REPORT_DEALS \
            or manifest.get("epsilon") != EPSILON \
            or manifest.get("rng_identity") != "seat-tied-sha256" \
            or manifest.get("ballot") != _ballot_identity() \
            or manifest.get("production_promotion") is not False:
        raise LearningScreenError("REPORT manifest mismatch")
    _require_parent_refs(manifest, root)
    initial_manifest_ref = CheckpointRef.capture(
        _seed_root(root, index) / "initial.json")
    _same_ref(manifest["initial_manifest_ref"], initial_manifest_ref,
              "REPORT initial parent")
    segment_ref = CheckpointRef.capture(
        _segment_path(root, index, arm, 1))
    _same_ref(manifest["segment_ref"], segment_ref,
              "REPORT segment parent")
    _same_ref(manifest["candidate_ref"], expected_candidate,
              "REPORT candidate")
    _same_ref(manifest["initial_ref"], initial_ref, "REPORT initial")
    candidate_model = load_verified(expected_candidate, load_actor)
    initial_model = load_verified(initial_ref, load_actor)
    if manifest.get("candidate_state_sha256") != state_digest(
            candidate_model.state_dict()) \
            or manifest.get("initial_state_sha256") != state_digest(
                initial_model.state_dict()):
        raise LearningScreenError("REPORT model-state identity mismatch")
    rows = _load_jsonl(_ref(manifest["raw_ref"]))
    expected = {
        (seed, flip)
        for seed in range(REPORT_SEED0, REPORT_SEED0 + REPORT_DEALS)
        for flip in (0, 1)}
    seen = set()
    valid_rows = []
    roles = Counter()
    wins = 0
    for row in rows:
        if not isinstance(row, Mapping) \
                or row.get("schema") != REPORT_RECORD_SCHEMA \
                or row.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
                or row.get("seed_index") != index \
                or row.get("arm") != arm \
                or row.get("ballot") != _ballot_identity() \
                or row.get("epsilon") != EPSILON \
                or row.get("rng_identity") != "seat-tied-sha256":
            raise LearningScreenError("REPORT row identity mismatch")
        key = (row.get("deal_seed"), row.get("flip"))
        if key not in expected or key in seen:
            raise LearningScreenError("REPORT flip coverage mismatch")
        seen.add(key)
        _same_ref(row["candidate_ref"], expected_candidate,
                  "REPORT row candidate")
        _same_ref(row["initial_ref"], initial_ref, "REPORT row initial")
        candidate_team = int(row["flip"])
        if row.get("candidate_team") != candidate_team:
            raise LearningScreenError("REPORT candidate team mismatch")
        expected_role = _candidate_role(
            banker=int(row["banker"]), candidate_team=candidate_team)
        if row.get("candidate_role") != ROLE_NAMES[expected_role]:
            raise LearningScreenError("REPORT candidate role mismatch")
        attacker_return = terminal_attacker_return(
            int(row["attacker_points"]))
        expected_return = acting_team_return(attacker_return, expected_role)
        if row.get("attacker_return") != attacker_return \
                or row.get("candidate_signed_return") != expected_return:
            raise LearningScreenError("REPORT signed return mismatch")
        expected_row = _report_round(
            candidate_model=candidate_model,
            initial_model=initial_model,
            candidate_ref=expected_candidate,
            initial_ref=initial_ref,
            index=index,
            arm=arm,
            deal_seed=int(row["deal_seed"]),
            flip=int(row["flip"]),
        )
        if _canonical_json(dict(row)) != _canonical_json(expected_row):
            raise LearningScreenError(
                f"REPORT semantic replay mismatch for {key}")
        value = float(row["candidate_signed_return"])
        if not math.isfinite(value):
            raise LearningScreenError("REPORT return is non-finite")
        valid_rows.append(row)
        roles[row["candidate_role"]] += 1
        wins += int(row["candidate_won"])
    if seen != expected:
        raise LearningScreenError("REPORT does not contain exact two-flip deals")
    if dict(roles) != manifest.get("role_counts") \
            or wins != manifest.get("wins"):
        raise LearningScreenError("REPORT manifest totals mismatch")
    return manifest_ref, exact_two_flip_means(
        valid_rows,
        seed0=REPORT_SEED0,
        deals=REPORT_DEALS,
        value_field="candidate_signed_return",
    )


def _compute_aggregate(root: str | Path) -> dict[str, Any]:
    root = Path(root).resolve()
    spec_ref, runtime_ref, runtime = _require_frozen(root)
    inputs: dict[str, Any] = {
        "spec": spec_ref.as_dict(),
        "runtime": runtime_ref.as_dict(),
        "initial": {},
        "training": {},
        "probes": {},
        "reports": {},
    }
    curves: dict[str, Any] = {}
    final_probe: dict[str, Any] = {}
    probe_role_deltas: dict[str, dict[int, list[float]]] = {
        ROLE_NAMES[role]: defaultdict(list) for role in ROLE_NAMES}
    seed_probe_means: dict[str, float] = {}
    treatment_reports: dict[int, dict[int, float]] = {}
    control_reports: dict[int, dict[int, float]] = {}
    report_seed_effects: dict[str, float] = {}
    health_pass = True

    for index in range(len(SEED_IDENTITIES)):
        initial_manifest_ref, initial, initial_ref = _initial_payload(
            root, index)
        inputs["initial"][str(index)] = initial_manifest_ref.as_dict()
        initial_state = str(initial["learner_state_sha256"])
        treatment_checkpoints, treatment_info = _validate_training(
            root, index, "treatment", initial_ref, initial_state)
        control_checkpoints, control_info = _validate_training(
            root, index, "control", initial_ref, initial_state)
        inputs["training"][str(index)] = {
            "treatment": {
                "segment_0": treatment_info["segment_0"],
                "segment_1": treatment_info["segment_1"],
            },
            "control": {
                "segment_0": control_info["segment_0"],
                "segment_1": control_info["segment_1"],
            },
        }
        probe_ref, probe_rows = _validated_probe(root, index, initial_ref)
        inputs["probes"][str(index)] = probe_ref.as_dict()
        checkpoint_scores = {
            label: _score_probes(ref, probe_rows)
            for label, ref in treatment_checkpoints.items()
        }
        curves[str(index)] = {
            label: value["summary"]
            for label, value in checkpoint_scores.items()}
        start = checkpoint_scores["0"]
        final = checkpoint_scores[str(ITERATIONS)]
        role_metrics = {}
        all_seed_deltas = []
        for role in ROLE_NAMES.values():
            start_deals = start["per_deal_mse"][role]
            final_deals = final["per_deal_mse"][role]
            if set(start_deals) != set(final_deals):
                raise LearningScreenError("probe checkpoint deal drift")
            deltas = {
                int(deal): float(start_deals[deal] - final_deals[deal])
                for deal in start_deals}
            for deal, value in deltas.items():
                probe_role_deltas[role][deal].append(value)
            all_seed_deltas.extend(deltas.values())
            initial_spread = float(
                start["summary"][role]["median_action_spread"])
            final_spread = float(
                final["summary"][role]["median_action_spread"])
            spread_ratio = (final_spread / initial_spread
                            if initial_spread > 0 else 0.0)
            role_positions = [
                position for position, row in enumerate(probe_rows)
                if ROLE_NAMES[int(row["role"])] == role
                and len(row["actions"]) > 1]
            changed = sum(
                start["greedy"][position] != final["greedy"][position]
                for position in role_positions)
            change_rate = changed / len(role_positions)
            p99_abs_q = float(final["summary"][role]["p99_abs_q"])
            role_health = (
                p99_abs_q <= SCREEN_SPEC["gate"]["max_probe_p99_abs_q"]
                and spread_ratio >= SCREEN_SPEC["gate"][
                    "min_final_to_initial_median_action_spread"]
            )
            health_pass = health_pass and role_health
            role_metrics[role] = {
                "mse_reduction": paired_summary(list(deltas.values())),
                "median_action_spread_ratio": spread_ratio,
                "greedy_action_change_rate_diagnostic": change_rate,
                "p99_abs_q": p99_abs_q,
                "health_pass": role_health,
            }
        seed_probe_means[str(index)] = float(np.mean(all_seed_deltas))
        final_probe[str(index)] = role_metrics

        treatment_manifest_ref, treatment_by_deal = _validated_report(
            root, index, "treatment",
            treatment_checkpoints[str(ITERATIONS)], initial_ref)
        control_manifest_ref, control_by_deal = _validated_report(
            root, index, "control",
            control_checkpoints[str(ITERATIONS)], initial_ref)
        inputs["reports"][str(index)] = {
            "treatment": treatment_manifest_ref.as_dict(),
            "control": control_manifest_ref.as_dict(),
        }
        if set(treatment_by_deal) != set(control_by_deal):
            raise LearningScreenError("REPORT treatment/control deal drift")
        effects = [
            treatment_by_deal[deal] - control_by_deal[deal]
            for deal in sorted(treatment_by_deal)]
        report_seed_effects[str(index)] = float(np.mean(effects))
        treatment_reports[index] = treatment_by_deal
        control_reports[index] = control_by_deal

    pooled_probe = {}
    for role in ROLE_NAMES.values():
        by_deal = probe_role_deltas[role]
        expected = set(range(PROBE_SEED0, PROBE_SEED0 + PROBE_DEALS))
        if set(by_deal) != expected \
                or any(len(values) != len(SEED_IDENTITIES)
                       for values in by_deal.values()):
            raise LearningScreenError("pooled probe deal coverage mismatch")
        summary = paired_summary([
            float(np.mean(by_deal[deal])) for deal in sorted(by_deal)])
        pooled_probe[role] = summary

    report_deals = set(range(REPORT_SEED0, REPORT_SEED0 + REPORT_DEALS))
    pooled_effects = []
    pooled_control = []
    pooled_treatment = []
    for deal in sorted(report_deals):
        treatment_values = [
            treatment_reports[index][deal]
            for index in range(len(SEED_IDENTITIES))]
        control_values = [
            control_reports[index][deal]
            for index in range(len(SEED_IDENTITIES))]
        pooled_treatment.append(float(np.mean(treatment_values)))
        pooled_control.append(float(np.mean(control_values)))
        pooled_effects.append(float(
            np.mean(treatment_values) - np.mean(control_values)))
    report_effect = paired_summary(pooled_effects)
    report_control = paired_summary(pooled_control)
    report_treatment = paired_summary(pooled_treatment)

    gates, passed, failures = learning_gate_decision(
        pooled_probe=pooled_probe,
        seed_probe_means=seed_probe_means,
        report_effect=report_effect,
        report_control=report_control,
        report_seed_effects=report_seed_effects,
        q_health=health_pass,
    )
    return {
        "schema": AGGREGATE_SCHEMA,
        "screen_spec_sha256": SCREEN_SPEC_SHA256,
        "root": str(root),
        "runtime_sha256": state_digest(runtime),
        "inputs": inputs,
        "probe": {
            "checkpoint_curves": curves,
            "final_by_seed": final_probe,
            "seed_role_balanced_mse_reduction": seed_probe_means,
            "pooled_by_role": pooled_probe,
        },
        "report": {
            "seed_treatment_minus_control": report_seed_effects,
            "treatment": report_treatment,
            "control": report_control,
            "treatment_minus_control": report_effect,
        },
        "gates": gates,
        "failures": failures,
        "passed_learning_screen": passed,
        "authorizes": (
            "new bounded self-play pilot only" if passed else "nothing"),
        "strength_claim": False,
        "production_promotion": False,
    }


def aggregate(root: str | Path) -> CheckpointRef:
    root = Path(root).resolve()
    payload = _compute_aggregate(root)
    return _publish_json(root / "aggregate.json", payload)


def _walk_artifact_refs(value: object):
    if isinstance(value, Mapping):
        if set(value) == {"path", "sha256"}:
            yield _ref(value)
        else:
            for item in value.values():
                yield from _walk_artifact_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_artifact_refs(item)


def verify_aggregate(ref: CheckpointRef) -> dict[str, Any]:
    payload = _load_json(ref)
    if not isinstance(payload, Mapping) \
            or payload.get("schema") != AGGREGATE_SCHEMA \
            or payload.get("screen_spec_sha256") != SCREEN_SPEC_SHA256 \
            or payload.get("production_promotion") is not False \
            or payload.get("strength_claim") is not False:
        raise LearningScreenError("aggregate identity mismatch")
    for artifact in _walk_artifact_refs(payload.get("inputs")):
        artifact.verify()
    recomputed = _compute_aggregate(str(payload.get("root")))
    if state_digest(payload) != state_digest(recomputed):
        raise LearningScreenError(
            "aggregate does not match independently reopened raw artifacts")
    ref.verify()
    return dict(recomputed)


def _print_ref(label: str, ref: CheckpointRef) -> None:
    print(json.dumps({label: ref.as_dict()}, sort_keys=True), flush=True)


def cli_main(argv: list[str] | None = None) -> int:
    torch.use_deterministic_algorithms(True, warn_only=False)
    parser = argparse.ArgumentParser(
        description="Frozen non-promotable Direct-Q learning screen")
    sub = parser.add_subparsers(dest="command", required=True)

    def root_parser(name: str):
        command = sub.add_parser(name)
        command.add_argument("--root", required=True)
        return command

    root_parser("freeze")
    initialize = root_parser("initialize")
    initialize.add_argument("--seed-index", type=int, required=True)
    preflight = root_parser("preflight")
    preflight.add_argument("--seed-index", type=int, required=True)
    preflight.add_argument("--arm", choices=ARMS, required=True)
    first = root_parser("train-first")
    first.add_argument("--seed-index", type=int, required=True)
    first.add_argument("--arm", choices=ARMS, required=True)
    second = root_parser("train-second")
    second.add_argument("--seed-index", type=int, required=True)
    second.add_argument("--arm", choices=ARMS, required=True)
    probe = root_parser("probe")
    probe.add_argument("--seed-index", type=int, required=True)
    report = root_parser("report")
    report.add_argument("--seed-index", type=int, required=True)
    report.add_argument("--arm", choices=ARMS, required=True)
    root_parser("aggregate")
    verify = sub.add_parser("verify")
    verify.add_argument("--aggregate", required=True)
    args = parser.parse_args(argv)

    if args.command == "freeze":
        refs = freeze(args.root)
        print(json.dumps({
            name: ref.as_dict() for name, ref in refs.items()},
            sort_keys=True), flush=True)
    elif args.command == "initialize":
        _print_ref("initial_manifest", initialize_seed(
            args.root, args.seed_index))
    elif args.command == "preflight":
        _print_ref("preflight_receipt", run_preflight(
            args.root, args.seed_index, args.arm))
    elif args.command == "train-first":
        _print_ref("segment_0", train_first_segment(
            args.root, args.seed_index, args.arm))
    elif args.command == "train-second":
        _print_ref("segment_1", train_second_segment(
            args.root, args.seed_index, args.arm))
    elif args.command == "probe":
        _print_ref("probe_manifest", capture_probes(
            args.root, args.seed_index))
    elif args.command == "report":
        _print_ref("report_manifest", evaluate_report(
            args.root, args.seed_index, args.arm))
    elif args.command == "aggregate":
        aggregate_ref = aggregate(args.root)
        result = _load_json(aggregate_ref)
        print(json.dumps({
            "aggregate": aggregate_ref.as_dict(),
            "passed_learning_screen": result["passed_learning_screen"],
            "production_promotion": False,
        }, sort_keys=True), flush=True)
    else:
        aggregate_ref = CheckpointRef.capture(args.aggregate)
        result = verify_aggregate(aggregate_ref)
        print(json.dumps({
            "verified": True,
            "passed_learning_screen": result["passed_learning_screen"],
            "production_promotion": False,
        }, sort_keys=True), flush=True)
    return 0
