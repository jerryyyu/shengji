"""Score-redacted runtime admission preflight for the Suphx O0 screen.

This module executes a tiny fixed number of disposable synchronous updates at
the full-information and public-only endpoints.  It publishes timing and work
counts only: no reward, action, loss, value, entropy, gradient, or learned
checkpoint result may cross the artifact boundary.  A PASS recommends a
bounded sub-hour dose for a later frozen launch packet; it never authorizes a
learning job by itself.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch

from .exact_resume import state_digest
from .selfplay_contract import sha256_file
from .suphx_actor import derive_deal_seed, publish_initial_actor
from .suphx_learning import (
    SuphxPolicyGradientUpdate,
    SuphxSchedule,
    SuphxScheduledCollector,
    new_bundle,
    new_runner,
)
from .suphx_micro import EXPERIMENT
from .suphx_policy import surface_key


PREFLIGHT_SCHEMA = "suphx-o0-score-redacted-runtime-preflight-v1"
CONTRACT_SCHEMA = "suphx-o0-score-redacted-runtime-contract-v1"
PREFLIGHT_ITERATIONS = 3
ENDPOINTS = (("oracle", 1.0), ("public", 0.0))
MODEL_SEED = 2_026_080_701
LEARNER_RNG_SEED = 2_026_080_703
RUNNER_ROOT_SEED = 2_026_080_707
DEAL_STREAM_ROOT_SEED = 2_026_080_709
LEARNING_RATE = 1e-3
MAX_PREFLIGHT_SECONDS = 600.0
LAUNCH_WINDOW_SECONDS = 3_300.0
TIMING_SAFETY_FACTOR = 2.0
MIN_RECOMMENDED_ITERATIONS = 8
MAX_RECOMMENDED_ITERATIONS = 64
EXPECTED_SURFACES = (
    "attacker_follow",
    "attacker_lead",
    "defender_follow",
    "defender_lead",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MATERIAL_RELATIVE_PATHS = (
    "server/scripts/suphx_o0_runtime_preflight.py",
    "server/shengji/rl/suphx_o0_preflight.py",
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
    "server/shengji/ai/heuristic.py",
    "server/shengji/ai/mcbot.py",
    "server/shengji/ai/memory.py",
    "server/shengji/ai/smart.py",
    "server/shengji/engine/cards.py",
    "server/shengji/engine/combos.py",
    "server/shengji/engine/fast.py",
    "server/shengji/engine/game.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
)
_ENDPOINT_FIELDS = {
    "name",
    "keep_probability",
    "iterations",
    "rounds",
    "temporary_training_updates",
    "samples_by_iteration",
    "samples_total",
    "role_surface_counts",
    "deal_seed_digest",
    "elapsed_seconds_by_iteration",
    "collect_seconds_by_iteration",
    "update_seconds_by_iteration",
    "publication_seconds_by_iteration",
    "total_elapsed_seconds",
    "terminal_progress",
    "complete",
}
_TOP_LEVEL_FIELDS = {
    "schema",
    "claim",
    "complete",
    "score_redacted",
    "source_identity",
    "contract",
    "contract_sha256",
    "runtime",
    "initial_model_state_sha256",
    "endpoints",
    "preflight_elapsed_seconds",
    "dose_recommendation",
    "criteria",
    "passed",
    "temporary_training_updates",
    "terminal_candidates_retained",
    "o0_launch_authorized",
    "o1_authorized",
    "training_authorized",
    "production_promotion",
}
_FORBIDDEN_RESULT_KEYS = {
    "action_cards",
    "action_draw",
    "attacker_bracket_return",
    "behavior_log_probability",
    "behavior_value",
    "candidate_ref",
    "chosen_index",
    "entropy",
    "gradient_norm",
    "loss",
    "reward",
    "target",
    "terminal_model_state_sha256",
    "value",
}


class SuphxO0PreflightError(RuntimeError):
    """The score-redacted O0 runtime boundary was violated."""


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
        raise SuphxO0PreflightError(
            "compiled engine binary is unavailable")
    files = {
        path: sha256_file(_REPO_ROOT / path)
        for path in _MATERIAL_RELATIVE_PATHS
    }
    files["compiled_engine"] = sha256_file(Path(compiled_path))
    return {
        "schema": "suphx-o0-material-source-identity-v1",
        "files": files,
    }


def runtime_identity() -> dict[str, Any]:
    from shengji.engine import combos, fast

    if os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise SuphxO0PreflightError(
            "compiled strict environment is not active")
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise SuphxO0PreflightError("compiled engine routing is not active")
    dirty = _material_status()
    if dirty:
        raise SuphxO0PreflightError(
            "material O0 source paths are dirty: " + dirty)
    return {
        "git": _git("rev-parse", "HEAD").stdout.strip(),
        "material_tree_clean": True,
        "host": platform.node(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": torch.__version__,
        "device": "cpu",
        "cpu_count": os.cpu_count(),
        "torch_num_threads": torch.get_num_threads(),
        "fast_engine": True,
        "require_voids": True,
    }


def preflight_contract(sources: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": CONTRACT_SCHEMA,
        "claim": "fixed-dose score-redacted runtime mechanics only",
        "experiment": EXPERIMENT,
        "source_identity": dict(sources),
        "endpoints": [
            {"name": name, "keep_probability": keep}
            for name, keep in ENDPOINTS
        ],
        "preflight_iterations_per_endpoint": PREFLIGHT_ITERATIONS,
        "rounds_per_iteration": 1,
        "model_seed": MODEL_SEED,
        "learner_rng_seed": LEARNER_RNG_SEED,
        "runner_root_seed": RUNNER_ROOT_SEED,
        "deal_stream_root_seed": DEAL_STREAM_ROOT_SEED,
        "learning_rate": LEARNING_RATE,
        "max_preflight_seconds": MAX_PREFLIGHT_SECONDS,
        "dose_formula": {
            "launch_window_seconds": LAUNCH_WINDOW_SECONDS,
            "timing_safety_factor": TIMING_SAFETY_FACTOR,
            "basis": (
                "max observed oracle iteration plus max observed public "
                "iteration; safe even if endpoint arms execute serially"
            ),
            "minimum_iterations_per_arm": MIN_RECOMMENDED_ITERATIONS,
            "maximum_iterations_per_arm": MAX_RECOMMENDED_ITERATIONS,
        },
        "redaction": {
            "artifact_contains_rewards": False,
            "artifact_contains_actions": False,
            "artifact_contains_losses": False,
            "artifact_contains_values": False,
            "artifact_contains_entropies_or_gradients": False,
            "artifact_contains_terminal_checkpoint_identity": False,
        },
        "authority": {
            "o0_launch": False,
            "o1": False,
            "training": False,
            "production": False,
        },
    }


def recommended_iterations(
        oracle_seconds: list[float], public_seconds: list[float]) -> int:
    if len(oracle_seconds) != PREFLIGHT_ITERATIONS \
            or len(public_seconds) != PREFLIGHT_ITERATIONS:
        raise SuphxO0PreflightError("timing dose is incomplete")
    values = [*oracle_seconds, *public_seconds]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(float(value)) or float(value) <= 0.0
           for value in values):
        raise SuphxO0PreflightError("timings must be finite and positive")
    paired_worst = max(oracle_seconds) + max(public_seconds)
    raw = math.floor(
        LAUNCH_WINDOW_SECONDS / (TIMING_SAFETY_FACTOR * paired_worst))
    return min(MAX_RECOMMENDED_ITERATIONS, max(0, raw))


class _TimedCollector:
    def __init__(self, inner):
        self.inner = inner
        self.elapsed_seconds: float | None = None
        self.samples: int | None = None
        self.surface_counts: Counter[str] | None = None
        self.game_seed: int | None = None

    def __call__(self, identity):
        started = time.perf_counter()
        batch = self.inner(identity)
        self.elapsed_seconds = time.perf_counter() - started
        self.samples = len(batch.samples)
        counts: Counter[str] = Counter()
        game_seeds = set()
        for sample in batch.samples:
            counts[surface_key(
                sample["role"], sample["decision_surface"])] += 1
            game_seeds.add(sample["game_seed"])
        if self.samples <= 0 or len(game_seeds) != 1:
            raise SuphxO0PreflightError(
                "timed collector did not produce one complete round")
        self.surface_counts = counts
        self.game_seed = next(iter(game_seeds))
        return batch


class _TimedUpdate:
    def __init__(self, inner):
        self.inner = inner
        self.elapsed_seconds: float | None = None

    def __call__(self, context) -> None:
        started = time.perf_counter()
        result = self.inner(context)
        self.elapsed_seconds = time.perf_counter() - started
        if result is not None:
            raise SuphxO0PreflightError(
                "timed learner update returned hidden state")


def _run_endpoint(
        root: Path, *, name: str, keep_probability: float
        ) -> tuple[dict[str, Any], str]:
    schedule = SuphxSchedule(
        segment_id=f"o0-runtime-{name}",
        keep_probabilities=(keep_probability,) * PREFLIGHT_ITERATIONS,
        learning_rate=LEARNING_RATE,
        deal_stream_root_seed=DEAL_STREAM_ROOT_SEED,
    )
    bundle = new_bundle(
        model_seed=MODEL_SEED,
        learner_rng_seed=LEARNER_RNG_SEED,
        learning_rate=LEARNING_RATE,
    )
    initial_model = state_digest(bundle.learner.state_dict())
    actor_ref = publish_initial_actor(bundle.learner, root / "actor")
    runner = new_runner(
        bundle=bundle,
        actor_ref=actor_ref,
        snapshot_dir=root / "candidates",
        root_seed=RUNNER_ROOT_SEED,
        schedule=schedule,
    )
    samples_by_iteration = []
    elapsed_by_iteration = []
    collect_by_iteration = []
    update_by_iteration = []
    publication_by_iteration = []
    surface_counts: Counter[str] = Counter()
    game_seeds = []
    endpoint_started = time.perf_counter()
    for sequence in range(PREFLIGHT_ITERATIONS):
        collector = _TimedCollector(SuphxScheduledCollector(
            runner.contract_sha256, schedule))
        update = _TimedUpdate(SuphxPolicyGradientUpdate(schedule))
        iteration_started = time.perf_counter()
        receipt = runner.run_iteration(collector, update)
        runner.adopt_current_candidate_as_actor()
        iteration_elapsed = time.perf_counter() - iteration_started
        if (receipt.batch.sequence != sequence
                or receipt.progress.next_iteration != sequence + 1
                or receipt.progress.next_batch != sequence + 1
                or collector.samples != receipt.samples_added
                or collector.elapsed_seconds is None
                or update.elapsed_seconds is None
                or collector.surface_counts is None
                or collector.game_seed is None):
            raise SuphxO0PreflightError(
                "timed synchronous iteration failed work reconciliation")
        overhead = max(
            0.0,
            iteration_elapsed
            - collector.elapsed_seconds
            - update.elapsed_seconds,
        )
        samples_by_iteration.append(receipt.samples_added)
        elapsed_by_iteration.append(iteration_elapsed)
        collect_by_iteration.append(collector.elapsed_seconds)
        update_by_iteration.append(update.elapsed_seconds)
        publication_by_iteration.append(overhead)
        surface_counts.update(collector.surface_counts)
        game_seeds.append(collector.game_seed)
    return ({
        "name": name,
        "keep_probability": keep_probability,
        "iterations": PREFLIGHT_ITERATIONS,
        "rounds": PREFLIGHT_ITERATIONS,
        "temporary_training_updates": PREFLIGHT_ITERATIONS,
        "samples_by_iteration": samples_by_iteration,
        "samples_total": sum(samples_by_iteration),
        "role_surface_counts": {
            key: surface_counts[key] for key in EXPECTED_SURFACES},
        "deal_seed_digest": state_digest(game_seeds),
        "elapsed_seconds_by_iteration": elapsed_by_iteration,
        "collect_seconds_by_iteration": collect_by_iteration,
        "update_seconds_by_iteration": update_by_iteration,
        "publication_seconds_by_iteration": publication_by_iteration,
        "total_elapsed_seconds": time.perf_counter() - endpoint_started,
        "terminal_progress": {
            "next_iteration": runner.progress.next_iteration,
            "next_batch": runner.progress.next_batch,
        },
        "complete": True,
    }, initial_model)


def _finite_timing_endpoint(endpoint: Mapping[str, Any]) -> bool:
    fields = (
        "elapsed_seconds_by_iteration",
        "collect_seconds_by_iteration",
        "update_seconds_by_iteration",
        "publication_seconds_by_iteration",
    )
    return all(
        isinstance(endpoint.get(field), list)
        and len(endpoint[field]) == PREFLIGHT_ITERATIONS
        and all(not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
                and float(value) >= 0.0
                for value in endpoint[field])
        for field in fields
    ) and isinstance(endpoint.get("total_elapsed_seconds"), (int, float)) \
        and not isinstance(endpoint.get("total_elapsed_seconds"), bool) \
        and math.isfinite(float(endpoint["total_elapsed_seconds"])) \
        and float(endpoint["total_elapsed_seconds"]) > 0.0 \
        and all(float(value) > 0.0
                for value in endpoint["elapsed_seconds_by_iteration"])


def _forbidden_result_paths(value: Any, path: str = "artifact") -> list[str]:
    problems = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in _FORBIDDEN_RESULT_KEYS:
                problems.append(child_path)
            problems += _forbidden_result_paths(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems += _forbidden_result_paths(child, f"{path}[{index}]")
    return problems


def _expected_dose(endpoints: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_name = {endpoint.get("name"): endpoint for endpoint in endpoints}
    oracle = by_name.get("oracle", {})
    public = by_name.get("public", {})
    try:
        iterations = recommended_iterations(
            oracle["elapsed_seconds_by_iteration"],
            public["elapsed_seconds_by_iteration"],
        )
        paired_worst = max(oracle["elapsed_seconds_by_iteration"]) \
            + max(public["elapsed_seconds_by_iteration"])
    except (KeyError, TypeError, ValueError, SuphxO0PreflightError):
        iterations, paired_worst = -1, None
    return {
        "schema": "suphx-o0-subhour-dose-recommendation-v1",
        "iterations_per_arm": iterations,
        "paired_worst_iteration_seconds": paired_worst,
        "safety_factor": TIMING_SAFETY_FACTOR,
        "projected_serial_seconds": (
            None if paired_worst is None or iterations < 0
            else paired_worst * iterations * TIMING_SAFETY_FACTOR
        ),
        "launch_window_seconds": LAUNCH_WINDOW_SECONDS,
        "minimum_required_iterations": MIN_RECOMMENDED_ITERATIONS,
        "maximum_allowed_iterations": MAX_RECOMMENDED_ITERATIONS,
        "recommendation_only": True,
        "launch_authorized": False,
    }


def _expected_criteria(payload: Mapping[str, Any]) -> dict[str, bool]:
    raw_endpoints = payload.get("endpoints", [])
    endpoints = raw_endpoints if isinstance(raw_endpoints, list) else []
    by_name = {
        endpoint.get("name"): endpoint
        for endpoint in endpoints
        if isinstance(endpoint, Mapping)
        and isinstance(endpoint.get("name"), str)
    }
    fixed = (
        isinstance(raw_endpoints, list)
        and len(endpoints) == len(ENDPOINTS)
        and all(isinstance(endpoint, Mapping) for endpoint in endpoints)
        and set(by_name) == {name for name, _ in ENDPOINTS}
        and all(by_name[name].get("keep_probability") == keep
                for name, keep in ENDPOINTS)
    )
    complete = fixed and all(
        endpoint.get("complete") is True
        and endpoint.get("iterations") == PREFLIGHT_ITERATIONS
        and endpoint.get("rounds") == PREFLIGHT_ITERATIONS
        and endpoint.get("temporary_training_updates") ==
        PREFLIGHT_ITERATIONS
        and endpoint.get("terminal_progress") == {
            "next_iteration": PREFLIGHT_ITERATIONS,
            "next_batch": PREFLIGHT_ITERATIONS,
        }
        for endpoint in by_name.values()
    )
    expected_deal_digest = state_digest([
        derive_deal_seed(DEAL_STREAM_ROOT_SEED, sequence, 0)
        for sequence in range(PREFLIGHT_ITERATIONS)
    ])
    deals = fixed and all(
        endpoint.get("deal_seed_digest") == expected_deal_digest
        for endpoint in by_name.values()
    )
    exact_work = fixed and all(
        isinstance(endpoint.get("samples_by_iteration"), list)
        and len(endpoint["samples_by_iteration"]) == PREFLIGHT_ITERATIONS
        and all(isinstance(value, int) and not isinstance(value, bool)
                and value > 0
                for value in endpoint["samples_by_iteration"])
        and endpoint.get("samples_total") ==
        sum(endpoint["samples_by_iteration"])
        and isinstance(endpoint.get("role_surface_counts"), Mapping)
        and all(isinstance(value, int) and not isinstance(value, bool)
                and value > 0
                for value in endpoint["role_surface_counts"].values())
        and sum(endpoint["role_surface_counts"].values()) ==
        endpoint["samples_total"]
        for endpoint in by_name.values()
    )
    surfaces = fixed and all(
        isinstance(endpoint.get("role_surface_counts"), Mapping)
        and set(endpoint["role_surface_counts"]) == set(EXPECTED_SURFACES)
        and all(isinstance(value, int) and not isinstance(value, bool)
                and value > 0
                for value in endpoint["role_surface_counts"].values())
        for endpoint in by_name.values()
    )
    timings = fixed and all(
        _finite_timing_endpoint(endpoint) for endpoint in by_name.values())
    recommendation = payload.get("dose_recommendation", {})
    return {
        "fixed_endpoint_population": fixed,
        "complete_fixed_iteration_dose": complete,
        "shared_causal_deal_sequence": deals,
        "exact_work_accounting": exact_work,
        "all_role_surfaces_observed": surfaces,
        "finite_score_redacted_timings": timings,
        "preflight_under_runtime_cap": (
            isinstance(payload.get("preflight_elapsed_seconds"), (int, float))
            and not isinstance(payload.get("preflight_elapsed_seconds"), bool)
            and math.isfinite(float(payload["preflight_elapsed_seconds"]))
            and 0.0 < float(payload["preflight_elapsed_seconds"])
            <= MAX_PREFLIGHT_SECONDS
        ),
        "subhour_dose_available": (
            isinstance(recommendation, Mapping)
            and isinstance(recommendation.get("iterations_per_arm"), int)
            and not isinstance(
                recommendation.get("iterations_per_arm"), bool)
            and recommendation["iterations_per_arm"] >=
            MIN_RECOMMENDED_ITERATIONS
            and isinstance(
                recommendation.get("projected_serial_seconds"), (int, float))
            and recommendation["projected_serial_seconds"] <=
            LAUNCH_WINDOW_SECONDS
        ),
        "score_redaction_enforced": (
            payload.get("score_redacted") is True
            and not _forbidden_result_paths(payload)
        ),
        "material_source_clean": (
            isinstance(payload.get("runtime"), Mapping)
            and payload["runtime"].get("material_tree_clean") is True
        ),
    }


def artifact_problems(payload: object) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["preflight artifact is not an object"]
    problems = []
    if set(payload) != _TOP_LEVEL_FIELDS:
        problems.append("preflight top-level fields")
    if (payload.get("schema") != PREFLIGHT_SCHEMA
            or payload.get("complete") is not True):
        problems.append("preflight identity/completion")
    sources = payload.get("source_identity")
    contract = payload.get("contract")
    if not isinstance(sources, Mapping) \
            or contract != preflight_contract(sources) \
            or payload.get("contract_sha256") != state_digest(contract):
        problems.append("preflight contract/source binding")
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list) \
            or any(not isinstance(endpoint, Mapping)
                   or set(endpoint) != _ENDPOINT_FIELDS
                   for endpoint in endpoints):
        problems.append("preflight endpoint fields")
        endpoints = []
    if endpoints and payload.get("dose_recommendation") != \
            _expected_dose(endpoints):
        problems.append("preflight dose arithmetic")
    expected_criteria = _expected_criteria(payload)
    if payload.get("criteria") != expected_criteria:
        problems.append("preflight criteria recomputation")
    expected_pass = bool(expected_criteria) and all(expected_criteria.values())
    if payload.get("passed") is not expected_pass:
        problems.append("preflight verdict recomputation")
    if payload.get("temporary_training_updates") != \
            PREFLIGHT_ITERATIONS * len(ENDPOINTS):
        problems.append("preflight temporary update accounting")
    if (payload.get("terminal_candidates_retained") is not False
            or payload.get("o0_launch_authorized") is not False
            or payload.get("o1_authorized") is not False
            or payload.get("training_authorized") is not False
            or payload.get("production_promotion") is not False):
        problems.append("preflight authority boundary")
    forbidden = _forbidden_result_paths(payload)
    if forbidden:
        problems.append(f"preflight leaked result fields {forbidden}")
    return sorted(set(problems))


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise SuphxO0PreflightError(
            "preflight output or partial already exists")
    raw = (json.dumps(
        payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    try:
        with partial.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        reopened = json.loads(path.read_bytes())
        if path.read_bytes() != raw or artifact_problems(reopened):
            raise SuphxO0PreflightError(
                "published preflight failed exact reopen")
        partial.unlink()
    except BaseException:
        # A linked final and/or partial is deliberate terminal evidence of a
        # failed publication; never overwrite it in place.
        raise


def run_preflight(out: Path) -> dict[str, Any]:
    if os.path.lexists(out) or os.path.lexists(str(out) + ".partial"):
        raise SuphxO0PreflightError(
            "preflight output or partial already exists")
    sources = source_identity()
    runtime = runtime_identity()
    contract = preflight_contract(sources)
    deterministic = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(
                prefix="shengji-suphx-o0-preflight-") as temporary:
            root = Path(temporary)
            endpoint_records = []
            initial_models = []
            for name, keep_probability in ENDPOINTS:
                record, initial_model = _run_endpoint(
                    root / name,
                    name=name,
                    keep_probability=keep_probability,
                )
                endpoint_records.append(record)
                initial_models.append(initial_model)
    finally:
        torch.use_deterministic_algorithms(
            deterministic, warn_only=warn_only)
    if len(set(initial_models)) != 1:
        raise SuphxO0PreflightError(
            "O0 endpoints did not start from equal model bytes")
    elapsed = time.perf_counter() - started
    payload: dict[str, Any] = {
        "schema": PREFLIGHT_SCHEMA,
        "claim": (
            "score-redacted fixed-dose runtime mechanics only; "
            "recommendation is not launch authority"
        ),
        "complete": True,
        "score_redacted": True,
        "source_identity": sources,
        "contract": contract,
        "contract_sha256": state_digest(contract),
        "runtime": runtime,
        "initial_model_state_sha256": initial_models[0],
        "endpoints": endpoint_records,
        "preflight_elapsed_seconds": elapsed,
        "dose_recommendation": _expected_dose(endpoint_records),
        "criteria": {},
        "passed": False,
        "temporary_training_updates": (
            PREFLIGHT_ITERATIONS * len(ENDPOINTS)),
        "terminal_candidates_retained": False,
        "o0_launch_authorized": False,
        "o1_authorized": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    payload["criteria"] = _expected_criteria(payload)
    payload["passed"] = all(payload["criteria"].values())
    problems = artifact_problems(payload)
    if problems:
        raise SuphxO0PreflightError(
            "preflight candidate artifact: " + "; ".join(problems))
    _write_exclusive(out, payload)
    return payload


def _verification_problems(payload: object) -> list[str]:
    problems = artifact_problems(payload)
    if not isinstance(payload, Mapping):
        return problems
    try:
        current_sources = source_identity()
        current_runtime = runtime_identity()
    except (OSError, subprocess.SubprocessError, SuphxO0PreflightError) as exc:
        return problems + [f"current runtime refused: {exc}"]
    if current_sources != payload.get("source_identity"):
        problems.append("preflight material source changed")
    producer_runtime = payload.get("runtime", {})
    producer_git = producer_runtime.get("git")
    if not isinstance(producer_git, str) or len(producer_git) != 40:
        problems.append("preflight producer git identity")
    else:
        if _git(
                "merge-base", "--is-ancestor", producer_git,
                current_runtime["git"], check=False).returncode:
            problems.append("preflight producer git is not an ancestor")
        changed = _git(
            "diff", "--name-only", f"{producer_git}..{current_runtime['git']}",
            "--", *_MATERIAL_RELATIVE_PATHS,
        ).stdout.strip()
        if changed:
            problems.append("preflight material paths changed since producer")
    for key in (
        "material_tree_clean", "host", "machine", "python", "numpy",
        "torch", "device", "cpu_count", "torch_num_threads",
        "fast_engine", "require_voids",
    ):
        if current_runtime.get(key) != producer_runtime.get(key):
            problems.append(f"preflight runtime {key} drift")
    return sorted(set(problems))


def verify_preflight(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() \
            or os.path.lexists(str(path) + ".partial"):
        raise SuphxO0PreflightError(
            "preflight artifact is missing, linked, or partial")
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SuphxO0PreflightError(
            f"preflight artifact is unreadable: {exc}") from exc
    problems = _verification_problems(payload)
    if problems:
        raise SuphxO0PreflightError(
            "preflight verification: " + "; ".join(problems))
    return payload


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--out", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--artifact", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            payload = run_preflight(Path(args.out))
        else:
            payload = verify_preflight(Path(args.artifact))
    except (OSError, ValueError, subprocess.SubprocessError,
            SuphxO0PreflightError) as exc:
        print(f"REFUSING: {exc}", file=os.sys.stderr)
        return 3
    summary = {
        "schema": payload["schema"],
        "passed": payload["passed"],
        "score_redacted": payload["score_redacted"],
        "preflight_elapsed_seconds": payload["preflight_elapsed_seconds"],
        "recommended_iterations_per_arm": payload[
            "dose_recommendation"]["iterations_per_arm"],
        "o0_launch_authorized": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 4
