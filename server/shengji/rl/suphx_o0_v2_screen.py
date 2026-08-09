"""Frozen Air packet and terminal screen for the Suphx O0-v2 battery.

The packet is deliberately separate from the reviewed mechanics and runner.
It freezes a fresh eight-seed population, the two factorial cells, evaluation
deals, exact-resume work, and a seed-clustered terminal rule.  Freezing a packet
does not authorize training: an exact independent-review marker must be copied
into the namespace before any endpoint runner can start.

The terminal result is a mechanism-screen verdict only.  A positive cell may
authorize design and independent review of O1; it cannot establish bot
strength, launch O1, promote a model, or change production.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from ..ai.env import play_round
from ..ai.smart import SmartBot
from ..engine.game import Game
from ..engine.round import Round
from .actions import enumerate_actions
from .douzero_micro import BALLOT_SCHEMA, ROLE_NAMES, acting_team_return
from .encode import ACT_DIM, encode_action
from .exact_resume import exact_resume_boundary_identity, state_digest
from .selfplay_contract import (
    CheckpointRef,
    load_verified,
    sha256_file,
)
from .suphx_actor import (
    clipped_attacker_bracket_return,
    load_actor,
    publish_initial_actor,
)
from .suphx_micro import PERFECT_DIM, apply_privilege_mask, encode_feature_partition
from .suphx_o0_screen import (
    _ExclusiveJsonl,
    _load_json,
    _load_jsonl,
    _publish_bytes,
    _publish_json,
    _ref,
    _require_regular_final,
)
from .suphx_o0_v2_integration import cross_arm_coupling_gate
from .suphx_o0_v2_mechanics import (
    ARMS,
    CrossedCRNSpec,
    CrossedCRNStreams,
    LogitMarginSpec,
)
from .suphx_o0_v2_runner import (
    CELL_CONTROL,
    CELL_MARGIN,
    CELLS,
    EXPERIMENT,
    LEARNING_RATE,
    RUNNER_SPEC_SHA256,
    O0V2Algorithm,
    SuphxO0V2Collector,
    SuphxO0V2PolicyGradientUpdate,
    new_o0_v2_bundle,
    new_o0_v2_runner,
    resume_o0_v2_runner,
)
from .suphx_policy import (
    POLICY_SPEC,
    SuphxPolicyValue,
    new_from_scratch_model,
    role_for,
    surface_for,
    surface_key,
)
from .synchronous_selfplay import _runner_contract_sha256


SCREEN_SCHEMA = "suphx-o0-v2-air-seed-clustered-screen-v1"
SPEC_SCHEMA = "suphx-o0-v2-air-frozen-spec-v1"
PACKET_SCHEMA = "suphx-o0-v2-air-launch-packet-v1"
ADMISSION_SCHEMA = "suphx-o0-v2-air-review-admission-v1"
INITIAL_SCHEMA = "suphx-o0-v2-air-initial-model-v1"
TRAIN_SCHEMA = "suphx-o0-v2-air-training-manifest-v1"
TRAIN_ROW_SCHEMA = "suphx-o0-v2-air-training-iteration-v1"
EVAL_SCHEMA = "suphx-o0-v2-air-evaluation-manifest-v1"
EVAL_ROW_SCHEMA = "suphx-o0-v2-air-evaluation-round-v1"
GATE_SCHEMA = "suphx-o0-v2-air-terminal-gate-v1"
PACKET_REVIEW_SCHEMA = "suphx-o0-v2-air-packet-review-v1"
PACKET_REVIEW_MARKER = "SUPHX_O0_V2_AIR_PACKET_REVIEW_V1 "

RUN_ID = "suphx-o0-v2-air-8seed-v1"
RUN_RELATIVE_ROOT = "server/runs/logs/suphx-o0-v2-air-8seed-v1"
PREFLIGHT_RELATIVE_PATH = (
    "server/runs/logs/suphx-o0-v2-air-runtime-preflight-v1.json"
)
EXPECTED_HOST = "Jerrys-MacBook-Air.local"
EXPECTED_PYTHON = "3.14.6"
REQUIRED_EXECUTION_ENVIRONMENT = {
    "SHENGJI_FAST": "1",
    "SHENGJI_REQUIRE_VOIDS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

ITERATIONS = 64
RESUME_BOUNDARY = 32
CRN_ROOT_SEED = 2_026_080_900
TRAINING_SEED_INDICES = tuple(range(8))
CRN_SPEC = CrossedCRNSpec(
    root_seed=CRN_ROOT_SEED,
    training_seed_indices=TRAINING_SEED_INDICES,
)
MARGIN_SPEC = LogitMarginSpec(target_margin=1.0, coefficient=0.01)
SEED_IDENTITIES = tuple({
    "index": index,
    "model_seed": 161_000_001 + index,
    "learner_rng_seed": 161_010_001 + index,
    "runner_root_seed": 161_020_001 + index,
} for index in TRAINING_SEED_INDICES)

EVAL_SEED0 = 161_100_000
EVAL_DEALS = 128
COMPARISONS = (
    "oracle_minus_public",
    "oracle_minus_initial",
    "same_model_null",
)
EXPECTED_SURFACES = tuple(POLICY_SPEC["surfaces"])

# Two predeclared cell-level oracle-minus-public tests share a family-wise
# one-sided alpha of at most .05 by Bonferroni (.025 each), df=8-1.
ONE_SIDED_ALPHA_EACH = 0.025
FAMILY_ALPHA_MAX = 0.05
T_CRITICAL_DF7 = 2.3646242515927844

_REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_RUN_ROOT = (_REPO_ROOT / RUN_RELATIVE_ROOT).resolve()
_MATERIAL_RELATIVE_PATHS = (
    "server/scripts/suphx_o0_v2_preflight.py",
    "server/scripts/suphx_o0_v2_screen.py",
    "server/shengji/rl/suphx_o0_v2_preflight.py",
    "server/shengji/rl/suphx_o0_v2_screen.py",
    "server/shengji/rl/suphx_o0_v2_runner.py",
    "server/shengji/rl/suphx_o0_v2_integration.py",
    "server/shengji/rl/suphx_o0_v2_mechanics.py",
    "server/shengji/rl/suphx_o0_screen.py",
    "server/shengji/rl/suphx_micro.py",
    "server/shengji/rl/suphx_policy.py",
    "server/shengji/rl/suphx_actor.py",
    "server/shengji/rl/suphx_learning.py",
    "server/shengji/rl/actions.py",
    "server/shengji/rl/douzero_micro.py",
    "server/shengji/rl/encode.py",
    "server/shengji/rl/exact_resume.py",
    "server/shengji/rl/selfplay_contract.py",
    "server/shengji/rl/synchronous_selfplay.py",
    "server/shengji/ai/env.py",
    "server/shengji/ai/smart.py",
    "server/shengji/engine/cards.py",
    "server/shengji/engine/combos.py",
    "server/shengji/engine/fast.py",
    "server/shengji/engine/game.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
)


class SuphxO0V2ScreenError(RuntimeError):
    """The frozen O0-v2 population, work, or authority boundary drifted."""


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=_REPO_ROOT, check=check,
        capture_output=True, text=True)


def _material_status() -> str:
    return _git(
        "status", "--porcelain", "--untracked-files=all", "--",
        *_MATERIAL_RELATIVE_PATHS,
    ).stdout.strip()


def source_identity() -> dict[str, Any]:
    from shengji.engine import fast

    compiled = getattr(fast, "_fast", None)
    compiled_path = getattr(compiled, "__file__", None)
    if not fast.HAVE_FAST or not compiled_path:
        raise SuphxO0V2ScreenError("compiled engine binary is unavailable")
    compiled_file = Path(compiled_path)
    expected_engine = (_REPO_ROOT / "server" / "shengji" / "engine").resolve()
    if compiled_file.is_symlink() \
            or compiled_file.resolve().parent != expected_engine:
        raise SuphxO0V2ScreenError(
            "compiled engine is not a regular binary in the exact worktree")
    files = {
        path: sha256_file(_REPO_ROOT / path)
        for path in _MATERIAL_RELATIVE_PATHS
    }
    files["compiled_engine"] = sha256_file(compiled_file)
    return {
        "schema": "suphx-o0-v2-air-material-source-identity-v1",
        "files": files,
    }


def runtime_identity() -> dict[str, Any]:
    from shengji.engine import combos, fast

    environment_drift = {
        name: os.environ.get(name)
        for name, expected in REQUIRED_EXECUTION_ENVIRONMENT.items()
        if os.environ.get(name) != expected
    }
    if environment_drift:
        raise SuphxO0V2ScreenError(
            f"exact execution environment is not active: {environment_drift}")
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise SuphxO0V2ScreenError("compiled engine routing is not active")
    dirty = _material_status()
    if dirty:
        raise SuphxO0V2ScreenError(
            "material O0-v2 source paths are dirty: " + dirty)
    runtime = {
        "git": _git("rev-parse", "HEAD").stdout.strip(),
        "material_tree_clean": True,
        "host": platform.node(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "numpy": np.__version__,
        "torch": torch.__version__,
        "device": "cpu",
        "cpu_count": os.cpu_count(),
        "torch_num_threads": torch.get_num_threads(),
        "torch_num_interop_threads": torch.get_num_interop_threads(),
        "fast_engine": True,
        "require_voids": True,
    }
    if runtime["host"] != EXPECTED_HOST \
            or runtime["python"] != EXPECTED_PYTHON \
            or runtime["torch_num_threads"] != 1 \
            or runtime["torch_num_interop_threads"] != 1:
        raise SuphxO0V2ScreenError(
            "O0-v2 packet is pinned to exact Air host/Python")
    return runtime


def _require_run_root(root: str | Path) -> Path:
    resolved = Path(root).resolve()
    if resolved != Path(EXPECTED_RUN_ROOT).resolve():
        raise SuphxO0V2ScreenError(
            "O0-v2 artifact root differs from the exact packet namespace")
    return resolved


def _seed_identity(index: int) -> dict[str, int]:
    if isinstance(index, bool) or not isinstance(index, int) \
            or index not in TRAINING_SEED_INDICES:
        raise SuphxO0V2ScreenError("training seed index is outside population")
    return dict(SEED_IDENTITIES[index])


def _algorithm(index: int, cell: str, arm: str) -> O0V2Algorithm:
    _seed_identity(index)
    if cell not in CELLS or arm not in ARMS:
        raise SuphxO0V2ScreenError("algorithm cell/arm is unsupported")
    return O0V2Algorithm(
        crn_spec=CRN_SPEC,
        training_seed_index=index,
        arm=arm,
        cell=cell,
        margin_spec=MARGIN_SPEC if cell == CELL_MARGIN else None,
    )


def _training_deals() -> dict[str, list[int]]:
    return {
        str(index): [
            CrossedCRNStreams(CRN_SPEC, index, iteration).deal_seed()
            for iteration in range(ITERATIONS)
        ]
        for index in TRAINING_SEED_INDICES
    }


def _deal_collision_proof() -> dict[str, Any]:
    by_seed = _training_deals()
    flat = [deal for values in by_seed.values() for deal in values]
    evaluation = list(range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS))
    if any(len(values) != ITERATIONS or len(set(values)) != ITERATIONS
           for values in by_seed.values()):
        raise SuphxO0V2ScreenError("within-seed training deal collision")
    if len(set(flat)) != len(flat):
        raise SuphxO0V2ScreenError("between-seed training deal collision")
    if set(flat) & set(evaluation):
        raise SuphxO0V2ScreenError("training/evaluation deal collision")
    if any(0 <= value <= evaluation[-1] for value in flat):
        raise SuphxO0V2ScreenError(
            "derived training deal entered sequential evidence namespace")
    return {
        "schema": "suphx-o0-v2-air-deal-collision-proof-v1",
        "training_deals_by_seed": by_seed,
        "training_deal_digest_by_seed": {
            key: state_digest(value) for key, value in by_seed.items()},
        "training_deals_total": len(flat),
        "unique_training_deals": len(set(flat)),
        "evaluation_deals": evaluation,
        "evaluation_deal_digest": state_digest(evaluation),
        "within_seed_collisions": 0,
        "between_seed_collisions": 0,
        "training_evaluation_collisions": 0,
        "training_sequential_namespace_collisions": 0,
        "cells_and_arms_share_training_deals": True,
    }


def _spec_payload() -> dict[str, Any]:
    return {
        "schema": SPEC_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "artifact_root": RUN_RELATIVE_ROOT,
        "claim": (
            "fresh seed-clustered oracle-acquisition mechanism battery; "
            "not bot strength or production evidence"
        ),
        "runner_spec_sha256": RUNNER_SPEC_SHA256,
        "crn_spec": CRN_SPEC.as_dict(),
        "fixed_population": [dict(value) for value in SEED_IDENTITIES],
        "cells": [
            {
                "name": CELL_CONTROL,
                "shared_public_crn": True,
                "margin_spec": None,
            },
            {
                "name": CELL_MARGIN,
                "shared_public_crn": True,
                "margin_spec": MARGIN_SPEC.as_dict(),
            },
        ],
        "training": {
            "arms": [
                {"name": "oracle", "keep_probability": 1.0},
                {"name": "public", "keep_probability": 0.0},
            ],
            "iterations_per_endpoint": ITERATIONS,
            "rounds_per_iteration": 1,
            "updates_per_iteration": 1,
            "learning_rate": LEARNING_RATE,
            "resume_boundary": RESUME_BOUNDARY,
            "initial_weights_equal_across_cells_and_arms_within_seed": True,
            "learner_rng_equal_across_cells_and_arms_within_seed": True,
            "runner_root_equal_across_cells_and_arms_within_seed": True,
            "public_key_draws_equal_until_policy_fork": True,
            "actor_refresh": "after_every_completed_iteration",
            "terminal_candidate_adopted": True,
            "unchanged_from_o0": [
                "dose", "reward_target", "feature_schedule", "optimizer",
                "learning_rate", "value_loss", "entropy_controller",
            ],
        },
        "evaluation": {
            "seed0": EVAL_SEED0,
            "deals": EVAL_DEALS,
            "deal_seeds": list(range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS)),
            "fresh_and_disjoint": True,
            "flips": [0, 1],
            "comparisons": list(COMPARISONS),
            "ordinary_policy": "deterministic_greedy_first_argmax",
            "ballot_schema": BALLOT_SCHEMA,
            "declaration": "SmartBot",
            "burial": "SmartBot",
            "training_use": False,
        },
        "inference": {
            "unit": "training seed mean over 128 paired deals and two flips",
            "training_seed_count": len(TRAINING_SEED_INDICES),
            "primary_per_cell": "oracle_minus_public",
            "one_sided_alpha_each": ONE_SIDED_ALPHA_EACH,
            "two_cell_family_alpha_max": FAMILY_ALPHA_MAX,
            "distribution": "Student t",
            "df": len(TRAINING_SEED_INDICES) - 1,
            "critical_value": T_CRITICAL_DF7,
            "primary_lcb_gt": 0.0,
            "every_seed_oracle_minus_public_mean_gt": 0.0,
            "every_seed_oracle_minus_initial_mean_gt": 0.0,
            "cell_verdicts_are_predeclared_without_best_cell_selection": True,
            "cross_cell_interaction": "diagnostic_only",
        },
        "terminal_rule": {
            "advance_cell": (
                "complete CRN coupling and health; oracle-minus-public LCB>0; "
                "every seed oracle-minus-public>0; every seed "
                "oracle-minus-initial>0; exact same-model null"
            ),
            "possible_verdicts": [
                "ADVANCE_BOTH", "ADVANCE_CRN_CONTROL",
                "ADVANCE_CRN_PLUS_MARGIN", "SELECT_NONE",
            ],
            "positive_authority": "O1 design and independent review only",
            "negative_authority": "stop same-recipe oracle thread",
        },
        "preflight": {
            "artifact": PREFLIGHT_RELATIVE_PATH,
            "score_redacted": True,
            "four_disposable_endpoint_iterations": True,
            "disposable_evaluation_timing_rounds": 4,
            "packet_freeze_requires_pass": True,
            "training_authorized": False,
        },
        "authority": {
            "packet_review_required_before_training": True,
            "o1_training": False,
            "strength": False,
            "production": False,
        },
    }


def _artifact_names() -> dict[str, str]:
    return {
        "admission": "review_admission.json",
        "review_copy": "review_record.txt",
        "training": "train/{cell}/seed_{index}_{arm}.json",
        "training_rows": "train/{cell}/seed_{index}_{arm}.jsonl",
        "evaluation": "eval/{cell}/seed_{index}.json",
        "evaluation_rows": "eval/{cell}/seed_{index}.jsonl",
        "gate": "gate.json",
    }


def _packet_path(root: Path) -> Path:
    return root / "launch_packet.json"


def _preflight_ref() -> CheckpointRef:
    from .suphx_o0_v2_preflight import verify_preflight

    path = _REPO_ROOT / PREFLIGHT_RELATIVE_PATH
    payload = verify_preflight(path)
    if payload.get("passed") is not True \
            or payload.get("packet_freeze_and_review_authorized") is not True \
            or any(payload.get(name) is not False for name in (
                "training_authorized", "o1_authorized", "strength_claim",
                "production_promotion")):
        raise SuphxO0V2ScreenError("Air preflight authority/capacity drift")
    return CheckpointRef.capture(_require_regular_final(path))


def _initial_path(root: Path, index: int) -> Path:
    return root / "initial" / f"seed_{index}.json"


def _training_path(root: Path, index: int, cell: str, arm: str) -> Path:
    return root / "train" / cell / f"seed_{index}_{arm}.json"


def _evaluation_path(root: Path, index: int, cell: str) -> Path:
    return root / "eval" / cell / f"seed_{index}.json"


def _same_ref(value: object, expected: CheckpointRef, label: str) -> None:
    if _ref(value, label=label) != expected:
        raise SuphxO0V2ScreenError(f"{label} identity mismatch")


def freeze_packet(root: str | Path) -> CheckpointRef:
    root = _require_run_root(root)
    if root.exists() and any(root.iterdir()):
        raise SuphxO0V2ScreenError("packet root must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    runtime = runtime_identity()
    sources = source_identity()
    preflight_ref = _preflight_ref()
    spec_ref = _publish_json(root / "spec.json", _spec_payload())
    initial_refs: dict[str, dict[str, str]] = {}
    for identity in SEED_IDENTITIES:
        index = identity["index"]
        model = new_from_scratch_model(identity["model_seed"])
        actor_ref = publish_initial_actor(
            model, root / "initial" / f"seed_{index}_actor")
        state_sha = state_digest(model.state_dict())
        if state_digest(load_verified(
                actor_ref, load_actor).state_dict()) != state_sha:
            raise SuphxO0V2ScreenError("initial actor failed exact reopen")
        manifest_ref = _publish_json(_initial_path(root, index), {
            "schema": INITIAL_SCHEMA,
            "screen_schema": SCREEN_SCHEMA,
            "seed_identity": dict(identity),
            "actor_ref": actor_ref.as_dict(),
            "model_state_sha256": state_sha,
            "equal_across_cells_and_arms": True,
            "training_updates": 0,
            "strength_claim": False,
            "production_promotion": False,
        })
        initial_refs[str(index)] = manifest_ref.as_dict()
    packet = {
        "schema": PACKET_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "artifact_root": RUN_RELATIVE_ROOT,
        "spec_ref": spec_ref.as_dict(),
        "preflight_ref": preflight_ref.as_dict(),
        "initial_manifest_refs": initial_refs,
        "deal_collision_proof": _deal_collision_proof(),
        "source_identity": sources,
        "runtime": runtime,
        "required_execution_environment": dict(REQUIRED_EXECUTION_ENVIRONMENT),
        "artifact_names": _artifact_names(),
        "review_required": True,
        "training_authorized": False,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    packet_ref = _publish_json(_packet_path(root), packet)
    verify_packet(packet_ref)
    return packet_ref


def _verify_initial(
        root: Path, index: int) \
        -> tuple[CheckpointRef, CheckpointRef, dict[str, Any]]:
    identity = _seed_identity(index)
    manifest_ref = CheckpointRef.capture(
        _require_regular_final(_initial_path(root, index)))
    payload = _load_json(manifest_ref)
    expected_fields = {
        "schema", "screen_schema", "seed_identity", "actor_ref",
        "model_state_sha256", "equal_across_cells_and_arms",
        "training_updates", "strength_claim", "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != INITIAL_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("seed_identity") != identity \
            or payload.get("equal_across_cells_and_arms") is not True \
            or payload.get("training_updates") != 0 \
            or payload.get("strength_claim") is not False \
            or payload.get("production_promotion") is not False:
        raise SuphxO0V2ScreenError("initial model manifest drift")
    actor_ref = _ref(payload["actor_ref"], label="initial actor")
    expected = new_from_scratch_model(identity["model_seed"])
    expected_state = state_digest(expected.state_dict())
    if payload.get("model_state_sha256") != expected_state \
            or state_digest(load_verified(
                actor_ref, load_actor).state_dict()) != expected_state:
        raise SuphxO0V2ScreenError("initial model seed/bytes drift")
    return manifest_ref, actor_ref, dict(payload)


def verify_packet(ref: CheckpointRef) -> dict[str, Any]:
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "run_id", "artifact_root", "spec_ref",
        "preflight_ref", "initial_manifest_refs", "deal_collision_proof",
        "source_identity",
        "runtime", "required_execution_environment", "artifact_names",
        "review_required",
        "training_authorized", "o1_authorized", "strength_claim",
        "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != PACKET_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("run_id") != RUN_ID \
            or payload.get("artifact_root") != RUN_RELATIVE_ROOT \
            or payload.get("required_execution_environment") \
            != REQUIRED_EXECUTION_ENVIRONMENT \
            or payload.get("artifact_names") != _artifact_names() \
            or payload.get("review_required") is not True \
            or any(payload.get(name) is not False for name in (
                "training_authorized", "o1_authorized", "strength_claim",
                "production_promotion")):
        raise SuphxO0V2ScreenError("launch packet identity/authority drift")
    root = _require_run_root(Path(ref.path).resolve().parent)
    if Path(ref.path).resolve() != _packet_path(root):
        raise SuphxO0V2ScreenError("launch packet is outside exact namespace")
    spec_ref = CheckpointRef.capture(_require_regular_final(root / "spec.json"))
    _same_ref(payload["spec_ref"], spec_ref, "packet spec")
    _same_ref(payload["preflight_ref"], _preflight_ref(), "packet preflight")
    if _load_json(spec_ref) != _spec_payload():
        raise SuphxO0V2ScreenError("frozen O0-v2 spec drift")
    refs = payload.get("initial_manifest_refs")
    if not isinstance(refs, Mapping) \
            or set(refs) != {str(index) for index in TRAINING_SEED_INDICES}:
        raise SuphxO0V2ScreenError("initial manifest population drift")
    for index in TRAINING_SEED_INDICES:
        initial_ref, _, _ = _verify_initial(root, index)
        _same_ref(refs[str(index)], initial_ref, "packet initial manifest")
    if payload.get("deal_collision_proof") != _deal_collision_proof():
        raise SuphxO0V2ScreenError("deal collision proof drift")
    current_runtime = runtime_identity()
    if payload.get("runtime") != current_runtime \
            or payload.get("source_identity") != source_identity():
        raise SuphxO0V2ScreenError("packet source/runtime drift")
    ref.verify()
    return dict(payload)


def _packet_review_claim(
        review_bytes: bytes, packet_ref: CheckpointRef) -> dict[str, Any]:
    try:
        text = review_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuphxO0V2ScreenError("review record is not UTF-8") from exc
    markers = [
        line[len(PACKET_REVIEW_MARKER):]
        for line in text.splitlines()
        if line.startswith(PACKET_REVIEW_MARKER)
    ]
    if len(markers) != 1:
        raise SuphxO0V2ScreenError(
            "review record must contain exactly one O0-v2 packet marker")
    try:
        claim = json.loads(markers[0])
    except json.JSONDecodeError as exc:
        raise SuphxO0V2ScreenError("review marker JSON is invalid") from exc
    expected_fields = {
        "schema", "git", "run_id", "packet_sha256", "host", "python",
        "independent_review", "training_authorized", "o1_authorized",
        "strength_claim", "production_promotion", "verdict",
    }
    packet = _load_json(packet_ref)
    if not isinstance(claim, Mapping) or set(claim) != expected_fields \
            or claim.get("schema") != PACKET_REVIEW_SCHEMA \
            or claim.get("git") != packet["runtime"]["git"] \
            or claim.get("run_id") != RUN_ID \
            or claim.get("packet_sha256") != packet_ref.sha256 \
            or claim.get("host") != EXPECTED_HOST \
            or claim.get("python") != EXPECTED_PYTHON \
            or claim.get("independent_review") is not True \
            or claim.get("training_authorized") is not True \
            or claim.get("o1_authorized") is not False \
            or claim.get("strength_claim") is not False \
            or claim.get("production_promotion") is not False \
            or claim.get("verdict") != "PASS":
        raise SuphxO0V2ScreenError("review marker authority/identity drift")
    return dict(claim)


def admit_packet(
        packet_ref: CheckpointRef, *, expected_packet_sha256: str,
        review_record: str | Path, expected_review_sha256: str) \
        -> CheckpointRef:
    if packet_ref.sha256 != expected_packet_sha256:
        raise SuphxO0V2ScreenError("expected packet SHA-256 mismatch")
    packet = verify_packet(packet_ref)
    root = _require_run_root(Path(packet_ref.path).resolve().parent)
    review_path = _require_regular_final(review_record)
    review_ref = CheckpointRef.capture(review_path)
    if review_ref.sha256 != expected_review_sha256:
        raise SuphxO0V2ScreenError("expected review SHA-256 mismatch")
    review_bytes = review_path.read_bytes()
    claim = _packet_review_claim(review_bytes, packet_ref)
    copied_ref = _publish_bytes(root / "review_record.txt", review_bytes)
    admission = {
        "schema": ADMISSION_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "packet_ref": packet_ref.as_dict(),
        "review_source_sha256": review_ref.sha256,
        "review_copy_ref": copied_ref.as_dict(),
        "review_claim": claim,
        "runtime_sha256": state_digest(packet["runtime"]),
        "training_authorized": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    ref = _publish_json(root / "review_admission.json", admission)
    _require_admission(root)
    return ref


def _require_admission(
        root: str | Path) -> tuple[CheckpointRef, CheckpointRef, dict[str, Any]]:
    root = _require_run_root(root)
    packet_ref = CheckpointRef.capture(
        _require_regular_final(_packet_path(root)))
    packet = verify_packet(packet_ref)
    admission_ref = CheckpointRef.capture(
        _require_regular_final(root / "review_admission.json"))
    admission = _load_json(admission_ref)
    expected_fields = {
        "schema", "screen_schema", "run_id", "packet_ref",
        "review_source_sha256", "review_copy_ref", "review_claim",
        "runtime_sha256", "training_authorized", "o1_authorized",
        "strength_claim", "production_promotion",
    }
    if not isinstance(admission, Mapping) or set(admission) != expected_fields \
            or admission.get("schema") != ADMISSION_SCHEMA \
            or admission.get("screen_schema") != SCREEN_SCHEMA \
            or admission.get("run_id") != RUN_ID \
            or admission.get("runtime_sha256") \
            != state_digest(packet["runtime"]) \
            or admission.get("training_authorized") is not True \
            or any(admission.get(name) is not False for name in (
                "o1_authorized", "strength_claim", "production_promotion")):
        raise SuphxO0V2ScreenError("review admission authority drift")
    _same_ref(admission["packet_ref"], packet_ref, "admitted packet")
    review_copy = _ref(admission["review_copy_ref"], label="review copy")
    review_bytes = Path(review_copy.path).read_bytes()
    if review_copy.sha256 != admission.get("review_source_sha256") \
            or admission.get("review_claim") != _packet_review_claim(
                review_bytes, packet_ref):
        raise SuphxO0V2ScreenError("review record copy/claim drift")
    admission_ref.verify()
    return packet_ref, admission_ref, dict(admission)


class _ObservedCollector:
    def __init__(self, inner: SuphxO0V2Collector):
        self.inner = inner
        self.samples = 0
        self.surface_counts: Counter[str] = Counter()
        self.game_seed: int | None = None

    @property
    def key_receipt(self) -> dict[str, Any] | None:
        return self.inner.key_receipt

    def __call__(self, identity):
        batch = self.inner(identity)
        game_seeds = set()
        for sample in batch.samples:
            self.surface_counts[surface_key(
                sample["role"], sample["decision_surface"])] += 1
            game_seeds.add(sample["game_seed"])
        self.samples = len(batch.samples)
        if self.samples <= 0 or len(game_seeds) != 1:
            raise SuphxO0V2ScreenError(
                "training iteration did not produce one complete round")
        self.game_seed = next(iter(game_seeds))
        return batch


def _finite_model(model: SuphxPolicyValue) -> bool:
    return all(bool(torch.all(torch.isfinite(value)))
               for value in model.state_dict().values())


def _entropy_controller(model: SuphxPolicyValue) -> dict[str, float]:
    values = {
        key: float(head.entropy_alpha.item())
        for key, head in model.surfaces.items()
    }
    if set(values) != set(EXPECTED_SURFACES) \
            or any(not math.isfinite(value) or not 0.0 <= value <= 0.1
                   for value in values.values()):
        raise SuphxO0V2ScreenError("entropy-controller state is invalid")
    return values


def _run_iteration_block(
        *, runner, algorithm: O0V2Algorithm, writer: _ExclusiveJsonl,
        index: int, cell: str, arm: str, start: int, stop: int,
        totals: Counter[str], game_seeds: list[int]) -> None:
    for sequence in range(start, stop):
        collector = _ObservedCollector(SuphxO0V2Collector(
            runner.contract_sha256, algorithm))
        update = SuphxO0V2PolicyGradientUpdate(algorithm)
        receipt = runner.run_iteration(collector, update)
        adopted = runner.adopt_current_candidate_as_actor()
        expected_deal = CrossedCRNStreams(
            CRN_SPEC, index, sequence).deal_seed()
        if receipt.batch.sequence != sequence \
                or receipt.progress.next_iteration != sequence + 1 \
                or receipt.progress.next_batch != sequence + 1 \
                or receipt.samples_added != collector.samples \
                or collector.game_seed != expected_deal \
                or collector.key_receipt is None \
                or adopted != receipt.candidate_ref:
            raise SuphxO0V2ScreenError(
                "synchronous O0-v2 iteration/adoption drift")
        totals["iterations"] += 1
        totals["rounds"] += 1
        totals["updates"] += 1
        totals["samples"] += collector.samples
        for key, count in collector.surface_counts.items():
            totals[key] += count
        game_seeds.append(expected_deal)
        writer.write({
            "schema": TRAIN_ROW_SCHEMA,
            "screen_schema": SCREEN_SCHEMA,
            "run_id": RUN_ID,
            "seed_index": index,
            "cell": cell,
            "arm": arm,
            "sequence": sequence,
            "algorithm_sha256": algorithm.sha256,
            "batch_identity": receipt.batch.as_dict(),
            "candidate_ref": receipt.candidate_ref.as_dict(),
            "key_receipt": collector.key_receipt,
            "samples": collector.samples,
            "surface_counts": {
                key: collector.surface_counts[key]
                for key in EXPECTED_SURFACES
            },
            "game_seed": expected_deal,
            "margin_summary": update.margin_summary,
            "progress": {
                "next_iteration": receipt.progress.next_iteration,
                "next_batch": receipt.progress.next_batch,
            },
            "outcomes": None,
            "strength_scores": None,
            "strength_claim": False,
            "production_promotion": False,
        })
        if (sequence + 1) % 8 == 0:
            print(
                f"PROGRESS O0-v2 seed={index} cell={cell} arm={arm} "
                f"{sequence + 1}/{ITERATIONS}", flush=True)


def train_endpoint(
        root: str | Path, index: int, cell: str, arm: str) -> CheckpointRef:
    root = _require_run_root(root)
    if cell not in CELLS or arm not in ARMS:
        raise SuphxO0V2ScreenError("training endpoint is unsupported")
    packet_ref, admission_ref, _ = _require_admission(root)
    identity = _seed_identity(index)
    initial_manifest_ref, initial_actor_ref, initial = _verify_initial(
        root, index)
    algorithm = _algorithm(index, cell, arm)
    bundle = new_o0_v2_bundle(
        model_seed=identity["model_seed"],
        learner_rng_seed=identity["learner_rng_seed"],
    )
    if state_digest(bundle.learner.state_dict()) != \
            initial["model_state_sha256"]:
        raise SuphxO0V2ScreenError("learner differs from frozen initial model")
    endpoint_root = root / "train" / cell / f"seed_{index}_{arm}"
    runner = new_o0_v2_runner(
        bundle=bundle,
        actor_ref=initial_actor_ref,
        snapshot_dir=endpoint_root / "candidates",
        root_seed=identity["runner_root_seed"],
        algorithm=algorithm,
    )
    ledger = _ExclusiveJsonl(
        root / "train" / cell / f"seed_{index}_{arm}.jsonl")
    totals: Counter[str] = Counter()
    game_seeds: list[int] = []
    try:
        _run_iteration_block(
            runner=runner, algorithm=algorithm, writer=ledger,
            index=index, cell=cell, arm=arm,
            start=0, stop=RESUME_BOUNDARY,
            totals=totals, game_seeds=game_seeds,
        )
        midpoint_ref = runner.save_checkpoint(
            endpoint_root / f"resume_{RESUME_BOUNDARY:03d}.pt")
        midpoint_actor = runner.actor_ref
        midpoint_candidate = runner.candidate_ref
        midpoint_boundary = exact_resume_boundary_identity(midpoint_ref)
        resumed_bundle = new_o0_v2_bundle(
            model_seed=identity["model_seed"],
            learner_rng_seed=identity["learner_rng_seed"],
        )
        runner = resume_o0_v2_runner(
            midpoint_ref,
            bundle=resumed_bundle,
            actor_ref=midpoint_actor,
            candidate_ref=midpoint_candidate,
            snapshot_dir=endpoint_root / "candidates",
            root_seed=identity["runner_root_seed"],
            algorithm=algorithm,
        )
        if runner.progress.next_iteration != RESUME_BOUNDARY \
                or runner.actor_ref != midpoint_candidate:
            raise SuphxO0V2ScreenError("midpoint exact-resume drift")
        _run_iteration_block(
            runner=runner, algorithm=algorithm, writer=ledger,
            index=index, cell=cell, arm=arm,
            start=RESUME_BOUNDARY, stop=ITERATIONS,
            totals=totals, game_seeds=game_seeds,
        )
        terminal_ref = runner.save_checkpoint(
            endpoint_root / f"resume_{ITERATIONS:03d}.pt")
        ledger_ref = ledger.publish()
    except BaseException:
        ledger.abandon()
        raise
    terminal_actor = runner.actor_ref
    if terminal_actor != runner.candidate_ref \
            or runner.progress.next_iteration != ITERATIONS \
            or runner.progress.next_batch != ITERATIONS:
        raise SuphxO0V2ScreenError("terminal candidate was not adopted")
    expected_deals = _training_deals()[str(index)]
    surface_counts = {key: totals[key] for key in EXPECTED_SURFACES}
    if game_seeds != expected_deals \
            or any(count <= 0 for count in surface_counts.values()) \
            or totals["iterations"] != ITERATIONS \
            or totals["rounds"] != ITERATIONS \
            or totals["updates"] != ITERATIONS \
            or totals["samples"] != sum(surface_counts.values()) \
            or not _finite_model(runner.learner):
        raise SuphxO0V2ScreenError("terminal training work/health drift")
    terminal_boundary = exact_resume_boundary_identity(terminal_ref)
    expected_contract = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=identity["runner_root_seed"],
        algorithm_sha256=algorithm.sha256,
    )
    if terminal_boundary.get("contract_sha256") != expected_contract \
            or terminal_boundary.get("progress") != {
                "next_iteration": ITERATIONS, "next_batch": ITERATIONS} \
            or terminal_boundary.get("actor_ref") != terminal_actor.as_dict() \
            or terminal_boundary.get("candidate_ref") \
            != terminal_actor.as_dict():
        raise SuphxO0V2ScreenError("terminal exact-resume identity drift")
    payload = {
        "schema": TRAIN_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "packet_ref": packet_ref.as_dict(),
        "admission_ref": admission_ref.as_dict(),
        "initial_manifest_ref": initial_manifest_ref.as_dict(),
        "seed_identity": identity,
        "cell": cell,
        "arm": arm,
        "algorithm": algorithm.as_dict(),
        "algorithm_sha256": algorithm.sha256,
        "runner_contract_sha256": expected_contract,
        "ledger_ref": ledger_ref.as_dict(),
        "midpoint_resume_ref": midpoint_ref.as_dict(),
        "midpoint_boundary_sha256": state_digest(midpoint_boundary),
        "terminal_resume_ref": terminal_ref.as_dict(),
        "terminal_boundary_sha256": state_digest(terminal_boundary),
        "terminal_actor_ref": terminal_actor.as_dict(),
        "terminal_model_state_sha256": state_digest(
            runner.learner.state_dict()),
        "entropy_controller": _entropy_controller(runner.learner),
        "iterations": totals["iterations"],
        "rounds": totals["rounds"],
        "updates": totals["updates"],
        "samples": totals["samples"],
        "surface_counts": surface_counts,
        "deal_seed_digest": state_digest(game_seeds),
        "exact_midpoint_resume_exercised": True,
        "terminal_candidate_adopted": True,
        "model_finite": True,
        "complete": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    ref = _publish_json(_training_path(root, index, cell, arm), payload)
    _load_training(root, index, cell, arm)
    return ref


def _load_training(
        root: str | Path, index: int, cell: str, arm: str) \
        -> tuple[CheckpointRef, CheckpointRef, dict[str, Any], list[dict[str, Any]]]:
    root = _require_run_root(root)
    packet_ref, admission_ref, _ = _require_admission(root)
    identity = _seed_identity(index)
    algorithm = _algorithm(index, cell, arm)
    initial_manifest_ref, _, initial = _verify_initial(root, index)
    ref = CheckpointRef.capture(
        _require_regular_final(_training_path(root, index, cell, arm)))
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "run_id", "packet_ref", "admission_ref",
        "initial_manifest_ref", "seed_identity", "cell", "arm", "algorithm",
        "algorithm_sha256", "runner_contract_sha256", "ledger_ref",
        "midpoint_resume_ref", "midpoint_boundary_sha256",
        "terminal_resume_ref", "terminal_boundary_sha256",
        "terminal_actor_ref", "terminal_model_state_sha256",
        "entropy_controller", "iterations", "rounds", "updates", "samples",
        "surface_counts", "deal_seed_digest", "exact_midpoint_resume_exercised",
        "terminal_candidate_adopted", "model_finite", "complete",
        "o1_authorized", "strength_claim", "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != TRAIN_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("run_id") != RUN_ID \
            or payload.get("seed_identity") != identity \
            or payload.get("cell") != cell or payload.get("arm") != arm \
            or payload.get("algorithm") != algorithm.as_dict() \
            or payload.get("algorithm_sha256") != algorithm.sha256 \
            or payload.get("iterations") != ITERATIONS \
            or payload.get("rounds") != ITERATIONS \
            or payload.get("updates") != ITERATIONS \
            or payload.get("exact_midpoint_resume_exercised") is not True \
            or payload.get("terminal_candidate_adopted") is not True \
            or payload.get("model_finite") is not True \
            or payload.get("complete") is not True \
            or any(payload.get(name) is not False for name in (
                "o1_authorized", "strength_claim", "production_promotion")):
        raise SuphxO0V2ScreenError("training manifest identity/authority drift")
    _same_ref(payload["packet_ref"], packet_ref, "training packet")
    _same_ref(payload["admission_ref"], admission_ref, "training admission")
    _same_ref(
        payload["initial_manifest_ref"], initial_manifest_ref,
        "training initial manifest")
    ledger_ref = _ref(payload["ledger_ref"], label="training ledger")
    midpoint_ref = _ref(
        payload["midpoint_resume_ref"], label="midpoint resume")
    terminal_ref = _ref(
        payload["terminal_resume_ref"], label="terminal resume")
    terminal_actor = _ref(
        payload["terminal_actor_ref"], label="terminal actor")
    midpoint = exact_resume_boundary_identity(midpoint_ref)
    terminal = exact_resume_boundary_identity(terminal_ref)
    expected_contract = _runner_contract_sha256(
        experiment=EXPERIMENT,
        root_seed=identity["runner_root_seed"],
        algorithm_sha256=algorithm.sha256,
    )
    if payload.get("runner_contract_sha256") != expected_contract \
            or payload.get("midpoint_boundary_sha256") \
            != state_digest(midpoint) \
            or payload.get("terminal_boundary_sha256") \
            != state_digest(terminal) \
            or midpoint.get("progress") != {
                "next_iteration": RESUME_BOUNDARY,
                "next_batch": RESUME_BOUNDARY,
            } \
            or terminal.get("progress") != {
                "next_iteration": ITERATIONS,
                "next_batch": ITERATIONS,
            } \
            or terminal.get("actor_ref") != terminal_actor.as_dict() \
            or terminal.get("candidate_ref") != terminal_actor.as_dict():
        raise SuphxO0V2ScreenError("training exact-resume identity drift")
    rows = _load_jsonl(ledger_ref)
    expected_deals = _training_deals()[str(index)]
    if len(rows) != ITERATIONS:
        raise SuphxO0V2ScreenError("training ledger dose drift")
    totals: Counter[str] = Counter()
    receipts: list[dict[str, Any]] = []
    _, initial_actor, _ = _verify_initial(root, index)
    expected_actor = initial_actor
    for sequence, row in enumerate(rows):
        if not isinstance(row, Mapping) \
                or row.get("schema") != TRAIN_ROW_SCHEMA \
                or row.get("screen_schema") != SCREEN_SCHEMA \
                or row.get("run_id") != RUN_ID \
                or row.get("seed_index") != index \
                or row.get("cell") != cell or row.get("arm") != arm \
                or row.get("sequence") != sequence \
                or row.get("algorithm_sha256") != algorithm.sha256 \
                or row.get("game_seed") != expected_deals[sequence] \
                or row.get("outcomes") is not None \
                or row.get("strength_scores") is not None \
                or row.get("strength_claim") is not False \
                or row.get("production_promotion") is not False \
                or row.get("progress") != {
                    "next_iteration": sequence + 1,
                    "next_batch": sequence + 1,
                }:
            raise SuphxO0V2ScreenError("training ledger row drift")
        batch_identity = row.get("batch_identity")
        if not isinstance(batch_identity, Mapping) \
                or batch_identity.get("sequence") != sequence \
                or batch_identity.get("contract_sha256") != expected_contract \
                or batch_identity.get("actor") != expected_actor.as_dict():
            raise SuphxO0V2ScreenError("training batch identity drift")
        candidate_ref = _ref(
            row.get("candidate_ref"), label="training candidate")
        expected_actor = candidate_ref
        counts = row.get("surface_counts")
        if not isinstance(counts, Mapping) \
                or set(counts) != set(EXPECTED_SURFACES) \
                or any(isinstance(counts[key], bool)
                       or not isinstance(counts[key], int)
                       or counts[key] < 0 for key in EXPECTED_SURFACES) \
                or row.get("samples") != sum(counts.values()) \
                or row.get("samples", 0) <= 0:
            raise SuphxO0V2ScreenError("training ledger work count drift")
        key_receipt = row.get("key_receipt")
        if not isinstance(key_receipt, Mapping) \
                or key_receipt.get("arm") != arm \
                or key_receipt.get("decision_count") != row["samples"]:
            raise SuphxO0V2ScreenError("training key receipt drift")
        margin = row.get("margin_summary")
        positive_surfaces = {
            key for key in EXPECTED_SURFACES if counts[key] > 0}
        if not isinstance(margin, Mapping) \
                or set(margin) != positive_surfaces:
            raise SuphxO0V2ScreenError("training margin summary population drift")
        for key, summary in margin.items():
            if not isinstance(summary, Mapping) \
                    or set(summary) != {
                        "decisions", "mean_top_two_margin"} \
                    or summary.get("decisions") != counts[key] \
                    or isinstance(summary.get("mean_top_two_margin"), bool) \
                    or not isinstance(
                        summary.get("mean_top_two_margin"), (int, float)) \
                    or not math.isfinite(float(
                        summary["mean_top_two_margin"])):
                raise SuphxO0V2ScreenError("training margin summary drift")
        receipts.append(dict(key_receipt))
        totals["samples"] += row["samples"]
        for key in EXPECTED_SURFACES:
            totals[key] += counts[key]
    if expected_actor != terminal_actor \
            or payload.get("samples") != totals["samples"] \
            or payload.get("surface_counts") != {
                key: totals[key] for key in EXPECTED_SURFACES} \
            or payload.get("deal_seed_digest") != state_digest(expected_deals):
        raise SuphxO0V2ScreenError("terminal training totals drift")
    model = load_verified(terminal_actor, load_actor)
    if not _finite_model(model) \
            or payload.get("terminal_model_state_sha256") \
            != state_digest(model.state_dict()) \
            or payload.get("terminal_model_state_sha256") \
            == initial["model_state_sha256"] \
            or payload.get("entropy_controller") != _entropy_controller(model):
        raise SuphxO0V2ScreenError("terminal model/controller drift")
    ref.verify()
    return ref, terminal_actor, dict(payload), receipts


class _GreedyOrdinary:
    def __init__(self, model: SuphxPolicyValue, gamma: float):
        if gamma not in (0.0, 1.0):
            raise SuphxO0V2ScreenError("evaluation gamma must be an endpoint")
        self.model = model
        self.gamma = gamma
        self.decisions = 0
        self.multi_action_decisions = 0
        self.entropy_sum = 0.0
        self.margin_sum = 0.0

    def decide_play(self, rnd: Round, seat: int):
        actions = enumerate_actions(
            rnd, seat, exhaustive_follows=False, include_throws=False)
        if not actions:
            raise SuphxO0V2ScreenError("evaluation ballot is empty")
        partition = encode_feature_partition(rnd, seat)
        candidates = np.asarray(
            [encode_action(action, rnd) for action in actions],
            dtype=np.float32,
        ).reshape(-1, ACT_DIM)
        logits, _ = self.model.score_candidates(
            role=role_for(rnd, seat),
            surface=surface_for(rnd),
            observation=partition["observation"],
            legal_private=partition["legal_private"],
            history=partition["public_history"],
            masked_perfect=apply_privilege_mask(
                partition["perfect"],
                np.full(PERFECT_DIM, self.gamma, dtype=np.float32),
            ),
            actions=candidates,
        )
        self.decisions += 1
        if len(logits) > 1:
            probabilities = torch.softmax(logits, dim=0)
            entropy = float((-(probabilities * torch.log(
                probabilities))).sum().item()) / math.log(len(logits))
            top = torch.topk(logits, 2).values
            margin = float((top[0] - top[1]).item())
            if not math.isfinite(entropy) or not math.isfinite(margin):
                raise SuphxO0V2ScreenError(
                    "evaluation entropy/margin is non-finite")
            self.multi_action_decisions += 1
            self.entropy_sum += entropy
            self.margin_sum += margin
        return list(actions[int(torch.argmax(logits).item())])

    def diagnostics(self) -> dict[str, float | int | None]:
        count = self.multi_action_decisions
        return {
            "decisions": self.decisions,
            "multi_action_decisions": count,
            "mean_normalized_entropy": None if not count
            else self.entropy_sum / count,
            "mean_top_two_margin": None if not count
            else self.margin_sum / count,
        }


class _SetupComposite:
    def __init__(self, ordinary: _GreedyOrdinary):
        self.ordinary = ordinary
        self.control = SmartBot()

    def decide_declare(self, rnd, seat, final=False):
        return self.control.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        return self.control.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        return self.ordinary.decide_play(rnd, seat)


def _candidate_role(banker: int, candidate_team: int) -> int:
    if banker not in range(4) or candidate_team not in (0, 1):
        raise SuphxO0V2ScreenError("evaluation candidate role is invalid")
    expected_name = "defender" if banker % 2 == candidate_team else "attacker"
    return next(role for role, name in ROLE_NAMES.items() if name == expected_name)


def _comparison_round(
        *, comparison: str, index: int, cell: str, deal_seed: int, flip: int,
        candidate_model: SuphxPolicyValue, reference_model: SuphxPolicyValue,
        candidate_ref: CheckpointRef, reference_ref: CheckpointRef,
        candidate_gamma: float, reference_gamma: float) -> dict[str, Any]:
    if comparison not in COMPARISONS or cell not in CELLS \
            or flip not in (0, 1) \
            or deal_seed not in range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS):
        raise SuphxO0V2ScreenError("evaluation comparison identity drift")
    candidate_team = flip
    actors: list[_GreedyOrdinary] = []
    policies = []
    for seat in range(4):
        if seat % 2 == candidate_team:
            actor = _GreedyOrdinary(candidate_model, candidate_gamma)
        else:
            actor = _GreedyOrdinary(reference_model, reference_gamma)
        actors.append(actor)
        policies.append(_SetupComposite(actor))
    game = Game(random.Random(deal_seed))
    log = play_round(game, policies)
    role = _candidate_role(log.banker, candidate_team)
    attacker_return = clipped_attacker_bracket_return(log.attacker_points)
    signed = acting_team_return(attacker_return, role)
    return {
        "schema": EVAL_ROW_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "seed_index": index,
        "cell": cell,
        "comparison": comparison,
        "deal_seed": deal_seed,
        "flip": flip,
        "candidate_team": candidate_team,
        "banker": log.banker,
        "candidate_role": ROLE_NAMES[role],
        "attacker_points": log.attacker_points,
        "attacker_bracket_return": attacker_return,
        "candidate_signed_return": signed,
        "candidate_won": int(log.winner_team == candidate_team),
        "candidate_diagnostics": {
            str(seat): actors[seat].diagnostics()
            for seat in range(4) if seat % 2 == candidate_team
        },
        "reference_diagnostics": {
            str(seat): actors[seat].diagnostics()
            for seat in range(4) if seat % 2 != candidate_team
        },
        "candidate_ref": candidate_ref.as_dict(),
        "reference_ref": reference_ref.as_dict(),
        "candidate_gamma": candidate_gamma,
        "reference_gamma": reference_gamma,
        "ballot_schema": BALLOT_SCHEMA,
        "ordinary_policy": "deterministic_greedy_first_argmax",
        "setup_controls": "SmartBot_declaration_and_burial",
    }


def evaluate_seed_cell(
        root: str | Path, index: int, cell: str) -> CheckpointRef:
    root = _require_run_root(root)
    if cell not in CELLS:
        raise SuphxO0V2ScreenError("evaluation cell is unsupported")
    packet_ref, admission_ref, _ = _require_admission(root)
    initial_manifest_ref, initial_ref, _ = _verify_initial(root, index)
    oracle_train_ref, oracle_ref, _, _ = _load_training(
        root, index, cell, "oracle")
    public_train_ref, public_ref, _, _ = _load_training(
        root, index, cell, "public")
    models = {
        "initial": load_verified(initial_ref, load_actor),
        "oracle": load_verified(oracle_ref, load_actor),
        "public": load_verified(public_ref, load_actor),
    }
    definitions = {
        "oracle_minus_public": (
            models["oracle"], models["public"], oracle_ref, public_ref, 1.0, 0.0),
        "oracle_minus_initial": (
            models["oracle"], models["initial"], oracle_ref, initial_ref, 1.0, 1.0),
        "same_model_null": (
            models["initial"], models["initial"], initial_ref, initial_ref, 1.0, 1.0),
    }
    writer = _ExclusiveJsonl(
        root / "eval" / cell / f"seed_{index}.jsonl")
    counts: Counter[str] = Counter()
    try:
        for comparison in COMPARISONS:
            (candidate_model, reference_model, candidate_ref, reference_ref,
             candidate_gamma, reference_gamma) = definitions[comparison]
            for offset, deal_seed in enumerate(
                    range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS)):
                for flip in (0, 1):
                    writer.write(_comparison_round(
                        comparison=comparison,
                        index=index,
                        cell=cell,
                        deal_seed=deal_seed,
                        flip=flip,
                        candidate_model=candidate_model,
                        reference_model=reference_model,
                        candidate_ref=candidate_ref,
                        reference_ref=reference_ref,
                        candidate_gamma=candidate_gamma,
                        reference_gamma=reference_gamma,
                    ))
                    counts[comparison] += 1
                if (offset + 1) % 16 == 0:
                    print(
                        f"PROGRESS O0-v2 EVAL seed={index} cell={cell} "
                        f"comparison={comparison} {counts[comparison]}/"
                        f"{2 * EVAL_DEALS}", flush=True)
        rows_ref = writer.publish()
    except BaseException:
        writer.abandon()
        raise
    if any(counts[name] != 2 * EVAL_DEALS for name in COMPARISONS):
        raise SuphxO0V2ScreenError("evaluation comparison dose drift")
    payload = {
        "schema": EVAL_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "packet_ref": packet_ref.as_dict(),
        "admission_ref": admission_ref.as_dict(),
        "initial_manifest_ref": initial_manifest_ref.as_dict(),
        "oracle_training_ref": oracle_train_ref.as_dict(),
        "public_training_ref": public_train_ref.as_dict(),
        "seed_index": index,
        "cell": cell,
        "model_refs": {
            "initial": initial_ref.as_dict(),
            "oracle": oracle_ref.as_dict(),
            "public": public_ref.as_dict(),
        },
        "comparisons": list(COMPARISONS),
        "deal_seed0": EVAL_SEED0,
        "deals": EVAL_DEALS,
        "flips": [0, 1],
        "rounds": writer.count,
        "comparison_rounds": dict(counts),
        "rows_ref": rows_ref.as_dict(),
        "complete": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    ref = _publish_json(_evaluation_path(root, index, cell), payload)
    _load_evaluation(root, index, cell, semantic_replay=False)
    return ref


def _validate_diagnostics(value: object, *, team: int) -> None:
    expected_seats = {
        str(seat) for seat in range(4) if seat % 2 == team}
    if not isinstance(value, Mapping) or set(value) != expected_seats:
        raise SuphxO0V2ScreenError("evaluation seat diagnostics drift")
    for summary in value.values():
        if not isinstance(summary, Mapping) or set(summary) != {
                "decisions", "multi_action_decisions",
                "mean_normalized_entropy", "mean_top_two_margin"}:
            raise SuphxO0V2ScreenError("evaluation diagnostic fields drift")
        decisions = summary["decisions"]
        multi = summary["multi_action_decisions"]
        if isinstance(decisions, bool) or not isinstance(decisions, int) \
                or decisions <= 0 or isinstance(multi, bool) \
                or not isinstance(multi, int) or not 0 <= multi <= decisions:
            raise SuphxO0V2ScreenError("evaluation diagnostic counts drift")
        for name in ("mean_normalized_entropy", "mean_top_two_margin"):
            result = summary[name]
            if (multi == 0) != (result is None):
                raise SuphxO0V2ScreenError("evaluation diagnostic null drift")
            if result is not None and (
                    isinstance(result, bool)
                    or not isinstance(result, (int, float))
                    or not math.isfinite(float(result))):
                raise SuphxO0V2ScreenError("evaluation diagnostic nonfinite")


def _exact_two_flip_means(
        rows: Sequence[Mapping[str, Any]]) -> dict[int, float]:
    expected = {
        (seed, flip)
        for seed in range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS)
        for flip in (0, 1)
    }
    seen = set()
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        key = (row.get("deal_seed"), row.get("flip"))
        value = row.get("candidate_signed_return")
        if key not in expected or key in seen \
                or isinstance(value, bool) \
                or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)):
            raise SuphxO0V2ScreenError("evaluation two-flip row drift")
        seen.add(key)
        grouped[int(key[0])].append(float(value))
    if seen != expected \
            or any(len(values) != 2 for values in grouped.values()):
        raise SuphxO0V2ScreenError("evaluation two-flip coverage drift")
    return {
        deal: float(np.mean(values))
        for deal, values in sorted(grouped.items())
    }


def _load_evaluation(
        root: str | Path, index: int, cell: str, *, semantic_replay: bool) \
        -> tuple[CheckpointRef, dict[str, dict[int, float]], dict[str, Any]]:
    root = _require_run_root(root)
    packet_ref, admission_ref, _ = _require_admission(root)
    initial_manifest_ref, initial_ref, _ = _verify_initial(root, index)
    oracle_train_ref, oracle_ref, _, _ = _load_training(
        root, index, cell, "oracle")
    public_train_ref, public_ref, _, _ = _load_training(
        root, index, cell, "public")
    ref = CheckpointRef.capture(
        _require_regular_final(_evaluation_path(root, index, cell)))
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "run_id", "packet_ref", "admission_ref",
        "initial_manifest_ref", "oracle_training_ref", "public_training_ref",
        "seed_index", "cell", "model_refs", "comparisons", "deal_seed0",
        "deals", "flips", "rounds", "comparison_rounds", "rows_ref",
        "complete", "o1_authorized", "strength_claim", "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != EVAL_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("run_id") != RUN_ID \
            or payload.get("seed_index") != index \
            or payload.get("cell") != cell \
            or payload.get("comparisons") != list(COMPARISONS) \
            or payload.get("deal_seed0") != EVAL_SEED0 \
            or payload.get("deals") != EVAL_DEALS \
            or payload.get("flips") != [0, 1] \
            or payload.get("rounds") != 2 * EVAL_DEALS * len(COMPARISONS) \
            or payload.get("comparison_rounds") != {
                name: 2 * EVAL_DEALS for name in COMPARISONS} \
            or payload.get("complete") is not True \
            or any(payload.get(name) is not False for name in (
                "o1_authorized", "strength_claim", "production_promotion")):
        raise SuphxO0V2ScreenError("evaluation manifest identity drift")
    for value, expected, label in (
        (payload["packet_ref"], packet_ref, "evaluation packet"),
        (payload["admission_ref"], admission_ref, "evaluation admission"),
        (payload["initial_manifest_ref"], initial_manifest_ref,
         "evaluation initial manifest"),
        (payload["oracle_training_ref"], oracle_train_ref,
         "evaluation oracle training"),
        (payload["public_training_ref"], public_train_ref,
         "evaluation public training"),
    ):
        _same_ref(value, expected, label)
    model_refs = payload.get("model_refs")
    if not isinstance(model_refs, Mapping) \
            or set(model_refs) != {"initial", "oracle", "public"}:
        raise SuphxO0V2ScreenError("evaluation model population drift")
    for name, expected in (
        ("initial", initial_ref), ("oracle", oracle_ref),
        ("public", public_ref),
    ):
        _same_ref(model_refs[name], expected, f"evaluation {name} model")
    models = {
        "initial": load_verified(initial_ref, load_actor),
        "oracle": load_verified(oracle_ref, load_actor),
        "public": load_verified(public_ref, load_actor),
    }
    definitions = {
        "oracle_minus_public": (
            models["oracle"], models["public"], oracle_ref, public_ref, 1.0, 0.0),
        "oracle_minus_initial": (
            models["oracle"], models["initial"], oracle_ref, initial_ref, 1.0, 1.0),
        "same_model_null": (
            models["initial"], models["initial"], initial_ref, initial_ref, 1.0, 1.0),
    }
    rows = _load_jsonl(_ref(payload["rows_ref"], label="evaluation rows"))
    expected_count = 2 * EVAL_DEALS * len(COMPARISONS)
    if len(rows) != expected_count:
        raise SuphxO0V2ScreenError("evaluation row population drift")
    expected_keys = {
        (comparison, deal_seed, flip)
        for comparison in COMPARISONS
        for deal_seed in range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS)
        for flip in (0, 1)
    }
    seen = set()
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, Mapping) \
                or row.get("schema") != EVAL_ROW_SCHEMA \
                or row.get("screen_schema") != SCREEN_SCHEMA \
                or row.get("run_id") != RUN_ID \
                or row.get("seed_index") != index \
                or row.get("cell") != cell \
                or row.get("comparison") not in COMPARISONS \
                or row.get("ballot_schema") != BALLOT_SCHEMA \
                or row.get("ordinary_policy") \
                != "deterministic_greedy_first_argmax" \
                or row.get("setup_controls") \
                != "SmartBot_declaration_and_burial":
            raise SuphxO0V2ScreenError("evaluation row identity drift")
        key = (row["comparison"], row.get("deal_seed"), row.get("flip"))
        if key not in expected_keys or key in seen:
            raise SuphxO0V2ScreenError("evaluation row collision")
        seen.add(key)
        definition = definitions[row["comparison"]]
        candidate_model, reference_model, candidate_ref, reference_ref, \
            candidate_gamma, reference_gamma = definition
        if row.get("candidate_ref") != candidate_ref.as_dict() \
                or row.get("reference_ref") != reference_ref.as_dict() \
                or row.get("candidate_gamma") != candidate_gamma \
                or row.get("reference_gamma") != reference_gamma:
            raise SuphxO0V2ScreenError("evaluation endpoint reference drift")
        candidate_team = int(row["flip"])
        if row.get("candidate_team") != candidate_team:
            raise SuphxO0V2ScreenError("evaluation team flip drift")
        _validate_diagnostics(
            row.get("candidate_diagnostics"), team=candidate_team)
        _validate_diagnostics(
            row.get("reference_diagnostics"), team=1 - candidate_team)
        banker = row.get("banker")
        attacker_points = row.get("attacker_points")
        if isinstance(banker, bool) or not isinstance(banker, int) \
                or banker not in range(4) \
                or isinstance(attacker_points, bool) \
                or not isinstance(attacker_points, int) \
                or attacker_points < 0:
            raise SuphxO0V2ScreenError("evaluation engine outcome drift")
        role = _candidate_role(banker, candidate_team)
        attacker_return = clipped_attacker_bracket_return(attacker_points)
        signed = acting_team_return(attacker_return, role)
        if row.get("candidate_role") != ROLE_NAMES[role] \
                or row.get("attacker_bracket_return") != attacker_return \
                or row.get("candidate_signed_return") != signed \
                or row.get("candidate_won") != int(signed > 0.0):
            raise SuphxO0V2ScreenError("evaluation signed utility drift")
        if semantic_replay:
            expected = _comparison_round(
                comparison=row["comparison"],
                index=index,
                cell=cell,
                deal_seed=row["deal_seed"],
                flip=row["flip"],
                candidate_model=candidate_model,
                reference_model=reference_model,
                candidate_ref=candidate_ref,
                reference_ref=reference_ref,
                candidate_gamma=candidate_gamma,
                reference_gamma=reference_gamma,
            )
            if dict(row) != expected:
                raise SuphxO0V2ScreenError("evaluation semantic replay drift")
        grouped[row["comparison"]].append(row)
    if seen != expected_keys:
        raise SuphxO0V2ScreenError("evaluation expected population drift")
    by_comparison = {
        comparison: _exact_two_flip_means(grouped[comparison])
        for comparison in COMPARISONS
    }
    ref.verify()
    return ref, by_comparison, dict(payload)


def _student_t_summary(values: Sequence[float]) -> dict[str, float | int]:
    if len(values) != len(TRAINING_SEED_INDICES) \
            or any(not math.isfinite(float(value)) for value in values):
        raise SuphxO0V2ScreenError("seed-clustered inference population drift")
    array = np.asarray(values, dtype=np.float64)
    mean = float(array.mean())
    se = float(array.std(ddof=1) / math.sqrt(len(array)))
    return {
        "n": len(values),
        "mean": mean,
        "se": se,
        "one_sided_alpha": ONE_SIDED_ALPHA_EACH,
        "df": len(values) - 1,
        "critical_value": T_CRITICAL_DF7,
        "lcb": mean - T_CRITICAL_DF7 * se,
    }


def _terminal_verdict(advanced: Sequence[str]) -> str:
    cells = set(advanced)
    if cells == set(CELLS):
        return "ADVANCE_BOTH"
    if cells == {CELL_CONTROL}:
        return "ADVANCE_CRN_CONTROL"
    if cells == {CELL_MARGIN}:
        return "ADVANCE_CRN_PLUS_MARGIN"
    if not cells:
        return "SELECT_NONE"
    raise SuphxO0V2ScreenError("terminal advanced-cell population drift")


def _cell_criteria(
        *, cell: str, primary: Mapping[str, object],
        seed_means: Mapping[str, Mapping[str, float]],
        coupling: Mapping[str, object], null_exact: bool) -> dict[str, bool]:
    expected_seeds = {str(index) for index in TRAINING_SEED_INDICES}
    if cell not in CELLS or set(seed_means) != expected_seeds \
            or not isinstance(primary.get("lcb"), (int, float)) \
            or isinstance(primary.get("lcb"), bool):
        raise SuphxO0V2ScreenError("cell criterion population drift")
    for values in seed_means.values():
        if not isinstance(values, Mapping) \
                or any(name not in values for name in (
                    "oracle_minus_public", "oracle_minus_initial")) \
                or any(isinstance(values[name], bool)
                       or not isinstance(values[name], (int, float))
                       or not math.isfinite(float(values[name]))
                       for name in (
                           "oracle_minus_public", "oracle_minus_initial")):
            raise SuphxO0V2ScreenError("cell criterion seed mean drift")
    return {
        "complete_cross_arm_public_key_coupling":
            coupling.get("passed") is True,
        "exact_same_model_two_flip_null_zero": null_exact is True,
        "oracle_minus_public_seed_clustered_lcb_positive":
            float(primary["lcb"]) > 0.0,
        "every_seed_oracle_minus_public_mean_positive": all(
            seed_means[str(index)]["oracle_minus_public"] > 0.0
            for index in TRAINING_SEED_INDICES),
        "every_seed_oracle_minus_initial_mean_positive": all(
            seed_means[str(index)]["oracle_minus_initial"] > 0.0
            for index in TRAINING_SEED_INDICES),
    }


def _compute_gate(root: str | Path) -> dict[str, Any]:
    root = _require_run_root(root)
    packet_ref, admission_ref, _ = _require_admission(root)
    inputs: dict[str, Any] = {
        "packet": packet_ref.as_dict(),
        "admission": admission_ref.as_dict(),
        "training": {},
        "evaluation": {},
    }
    seed_means: dict[str, dict[str, dict[str, float]]] = {
        cell: {} for cell in CELLS}
    coupling: dict[str, dict[str, Any]] = {}
    cell_null_exact: dict[str, bool] = {cell: True for cell in CELLS}
    for cell in CELLS:
        inputs["training"][cell] = {}
        inputs["evaluation"][cell] = {}
        cell_receipts: list[dict[str, Any]] = []
        for index in TRAINING_SEED_INDICES:
            inputs["training"][cell][str(index)] = {}
            for arm in ARMS:
                training_ref, _, _, receipts = _load_training(
                    root, index, cell, arm)
                inputs["training"][cell][str(index)][arm] = \
                    training_ref.as_dict()
                cell_receipts.extend(receipts)
            evaluation_ref, comparisons, _ = _load_evaluation(
                root, index, cell, semantic_replay=False)
            inputs["evaluation"][cell][str(index)] = evaluation_ref.as_dict()
            seed_means[cell][str(index)] = {
                comparison: float(np.mean(list(values.values())))
                for comparison, values in comparisons.items()
            }
            cell_null_exact[cell] = cell_null_exact[cell] and all(
                value == 0.0
                for value in comparisons["same_model_null"].values())
        coupling[cell] = cross_arm_coupling_gate(CRN_SPEC, cell_receipts)

    primary = {
        cell: _student_t_summary([
            seed_means[cell][str(index)]["oracle_minus_public"]
            for index in TRAINING_SEED_INDICES
        ])
        for cell in CELLS
    }
    interaction_values = [
        seed_means[CELL_MARGIN][str(index)]["oracle_minus_public"]
        - seed_means[CELL_CONTROL][str(index)]["oracle_minus_public"]
        for index in TRAINING_SEED_INDICES
    ]
    interaction = {
        "n": len(interaction_values),
        "seed_differences": interaction_values,
        "mean": float(np.mean(interaction_values)),
        "se": float(np.std(
            np.asarray(interaction_values, dtype=np.float64), ddof=1)
            / math.sqrt(len(interaction_values))),
        "gate": False,
    }
    criteria: dict[str, dict[str, bool]] = {}
    advanced: list[str] = []
    for cell in CELLS:
        cell_criteria = _cell_criteria(
            cell=cell,
            primary=primary[cell],
            seed_means=seed_means[cell],
            coupling=coupling[cell],
            null_exact=cell_null_exact[cell],
        )
        criteria[cell] = cell_criteria
        if all(cell_criteria.values()):
            advanced.append(cell)
    verdict = _terminal_verdict(advanced)
    return {
        "schema": GATE_SCHEMA,
        "screen_schema": SCREEN_SCHEMA,
        "run_id": RUN_ID,
        "root": str(root),
        "inputs": inputs,
        "training_seeds_are_inference_units": True,
        "seed_comparison_means": seed_means,
        "cell_primary": primary,
        "cross_cell_interaction_diagnostic": interaction,
        "cross_arm_coupling": coupling,
        "cell_criteria": criteria,
        "advanced_cells": advanced,
        "verdict": verdict,
        "authorizes_o1_freeze_and_independent_review": bool(advanced),
        "authorizes_o1_training": False,
        "strength_claim": False,
        "production_promotion": False,
    }


def run_gate(root: str | Path) -> CheckpointRef:
    root = _require_run_root(root)
    ref = _publish_json(root / "gate.json", _compute_gate(root))
    verify_gate(ref)
    return ref


def _walk_refs(value: object):
    if isinstance(value, Mapping):
        if set(value) == {"path", "sha256"}:
            yield _ref(value, label="gate input")
        else:
            for child in value.values():
                yield from _walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_refs(child)


def verify_gate(ref: CheckpointRef) -> dict[str, Any]:
    payload = _load_json(ref)
    expected_fields = {
        "schema", "screen_schema", "run_id", "root", "inputs",
        "training_seeds_are_inference_units", "seed_comparison_means",
        "cell_primary", "cross_cell_interaction_diagnostic",
        "cross_arm_coupling", "cell_criteria", "advanced_cells", "verdict",
        "authorizes_o1_freeze_and_independent_review",
        "authorizes_o1_training", "strength_claim", "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != GATE_SCHEMA \
            or payload.get("screen_schema") != SCREEN_SCHEMA \
            or payload.get("run_id") != RUN_ID \
            or payload.get("training_seeds_are_inference_units") is not True \
            or payload.get("verdict") not in {
                "ADVANCE_BOTH", "ADVANCE_CRN_CONTROL",
                "ADVANCE_CRN_PLUS_MARGIN", "SELECT_NONE"} \
            or payload.get("authorizes_o1_training") is not False \
            or payload.get("strength_claim") is not False \
            or payload.get("production_promotion") is not False:
        raise SuphxO0V2ScreenError("terminal gate identity/authority drift")
    root = _require_run_root(payload["root"])
    if Path(ref.path).resolve() != root / "gate.json":
        raise SuphxO0V2ScreenError("terminal gate is outside exact namespace")
    for artifact in _walk_refs(payload["inputs"]):
        artifact.verify()
    recomputed = _compute_gate(root)
    if payload != recomputed:
        raise SuphxO0V2ScreenError("terminal gate recomputation drift")
    advanced = payload["advanced_cells"]
    if payload["verdict"] != _terminal_verdict(advanced) \
            or payload["authorizes_o1_freeze_and_independent_review"] \
            is not bool(advanced) \
            or advanced != [
                cell for cell in CELLS
                if all(payload["cell_criteria"][cell].values())]:
        raise SuphxO0V2ScreenError("terminal gate verdict arithmetic drift")
    ref.verify()
    return dict(payload)


def _print_ref(label: str, ref: CheckpointRef) -> None:
    print(json.dumps({label: ref.as_dict()}, sort_keys=True), flush=True)


def cli_main(argv: list[str] | None = None) -> int:
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True, warn_only=False)
    parser = argparse.ArgumentParser(
        description="Frozen Air Suphx O0-v2 seed-clustered screen")
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--root", required=True)
    verify_packet_parser = sub.add_parser("verify-packet")
    verify_packet_parser.add_argument("--packet", required=True)
    admit = sub.add_parser("admit")
    admit.add_argument("--root", required=True)
    admit.add_argument("--expected-packet-sha256", required=True)
    admit.add_argument("--review-record", required=True)
    admit.add_argument("--expected-review-sha256", required=True)
    train = sub.add_parser("train")
    train.add_argument("--root", required=True)
    train.add_argument("--seed-index", type=int, required=True)
    train.add_argument("--cell", choices=CELLS, required=True)
    train.add_argument("--arm", choices=ARMS, required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--root", required=True)
    evaluate.add_argument("--seed-index", type=int, required=True)
    evaluate.add_argument("--cell", choices=CELLS, required=True)
    gate = sub.add_parser("gate")
    gate.add_argument("--root", required=True)
    verify_gate_parser = sub.add_parser("verify-gate")
    verify_gate_parser.add_argument("--gate", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            _print_ref("launch_packet", freeze_packet(args.root))
            return 0
        if args.command == "verify-packet":
            packet_ref = CheckpointRef.capture(
                _require_regular_final(args.packet))
            verify_packet(packet_ref)
            _print_ref("verified_packet", packet_ref)
            return 0
        if args.command == "admit":
            root = _require_run_root(args.root)
            packet_ref = CheckpointRef.capture(
                _require_regular_final(_packet_path(root)))
            _print_ref("review_admission", admit_packet(
                packet_ref,
                expected_packet_sha256=args.expected_packet_sha256,
                review_record=args.review_record,
                expected_review_sha256=args.expected_review_sha256,
            ))
            return 0
        if args.command == "train":
            _print_ref("training_manifest", train_endpoint(
                args.root, args.seed_index, args.cell, args.arm))
            return 0
        if args.command == "evaluate":
            _print_ref("evaluation_manifest", evaluate_seed_cell(
                args.root, args.seed_index, args.cell))
            return 0
        if args.command == "gate":
            ref = run_gate(args.root)
            payload = _load_json(ref)
            _print_ref("gate", ref)
            print(json.dumps({
                "verdict": payload["verdict"],
                "advanced_cells": payload["advanced_cells"],
                "authorizes_o1_freeze_and_independent_review": payload[
                    "authorizes_o1_freeze_and_independent_review"],
                "authorizes_o1_training": False,
                "strength_claim": False,
                "production_promotion": False,
            }, sort_keys=True), flush=True)
            return 0 if payload["advanced_cells"] else 4
        gate_ref = CheckpointRef.capture(
            _require_regular_final(args.gate))
        payload = verify_gate(gate_ref)
        print(json.dumps({
            "verified": True,
            "verdict": payload["verdict"],
            "authorizes_o1_training": False,
            "strength_claim": False,
            "production_promotion": False,
        }, sort_keys=True), flush=True)
        return 0 if payload["advanced_cells"] else 4
    except (FileExistsError, OSError, RuntimeError, ValueError,
            subprocess.SubprocessError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 3
