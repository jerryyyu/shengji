"""Score-redacted Air capacity preflight for the Suphx O0-v2 packet.

The preflight executes one disposable iteration in each cell/arm endpoint and
a tiny disposable greedy-evaluation timing population.  It publishes only
work, coupling, timing, source, and runtime metadata.  Models, actions,
rewards, losses, values, margins, entropies, and checkpoint identities are
never retained.  A PASS permits packet freezing and review only; it grants no
training or strength authority.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from ..ai.env import play_round
from ..engine.game import Game
from .exact_resume import state_digest
from .selfplay_contract import CheckpointRef
from .suphx_actor import publish_initial_actor
from .suphx_o0_screen import _load_json, _publish_json, _require_regular_final
from .suphx_o0_v2_mechanics import CrossedCRNSpec, CrossedCRNStreams
from .suphx_o0_v2_runner import (
    CELL_CONTROL,
    CELL_MARGIN,
    CELLS,
    O0V2Algorithm,
    SuphxO0V2Collector,
    SuphxO0V2PolicyGradientUpdate,
    new_o0_v2_bundle,
    new_o0_v2_runner,
)
from .suphx_o0_v2_screen import (
    ARMS,
    CRN_SPEC,
    EVAL_DEALS,
    EVAL_SEED0,
    EXPECTED_SURFACES,
    ITERATIONS,
    MARGIN_SPEC,
    RUNNER_SPEC_SHA256,
    _GreedyOrdinary,
    _SetupComposite,
    runtime_identity,
    source_identity,
)
from .suphx_policy import surface_key


PREFLIGHT_SCHEMA = "suphx-o0-v2-air-score-redacted-preflight-v1"
CONTRACT_SCHEMA = "suphx-o0-v2-air-preflight-contract-v1"
PREFLIGHT_RELATIVE_PATH = (
    "server/runs/logs/suphx-o0-v2-air-runtime-preflight-v1.json"
)
PREFLIGHT_CRN_SPEC = CrossedCRNSpec(
    root_seed=2_026_080_950,
    training_seed_indices=tuple(range(8)),
)
PREFLIGHT_SEED_INDEX = 0
PREFLIGHT_MODEL_SEED = 2_026_081_950
PREFLIGHT_LEARNER_SEED = 2_026_082_950
PREFLIGHT_RUNNER_SEED = 2_026_083_950
PREFLIGHT_EVAL_SEED0 = 19_500_000_000
PREFLIGHT_EVAL_ROUNDS = 4
PARALLEL_JOBS = 8
TIMING_SAFETY_FACTOR = 2.0
MAX_PREFLIGHT_SECONDS = 600.0
MAX_PROJECTED_WALL_SECONDS = 8 * 60 * 60.0
TRAINING_ENDPOINTS = len(CELLS) * len(ARMS) * 8
EVALUATION_ROUNDS = 8 * len(CELLS) * 3 * EVAL_DEALS * 2

_REPO_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_PREFLIGHT_PATH = (_REPO_ROOT / PREFLIGHT_RELATIVE_PATH).resolve()
_FORBIDDEN_KEYS = {
    "action", "action_cards", "action_draw", "advantage",
    "attacker_bracket_return", "attacker_points", "behavior_log_probability",
    "behavior_value", "candidate_ref", "checkpoint", "chosen_index",
    "entropy", "gradient", "logit", "loss", "margin", "model_state",
    "reward", "score", "target", "terminal_actor", "value", "winner",
}
_ENDPOINT_FIELDS = {
    "cell", "arm", "iterations", "rounds", "temporary_updates", "samples",
    "role_surface_counts", "elapsed_seconds", "deal_seed",
    "first_public_decision_key", "decision_count", "complete",
}


class SuphxO0V2PreflightError(RuntimeError):
    """The score-redacted O0-v2 preflight contract drifted."""


def _contract() -> dict[str, Any]:
    disposable_training_deal = CrossedCRNStreams(
        PREFLIGHT_CRN_SPEC, PREFLIGHT_SEED_INDEX, 0).deal_seed()
    return {
        "schema": CONTRACT_SCHEMA,
        "claim": "disposable score-redacted Air capacity mechanics only",
        "runner_spec_sha256": RUNNER_SPEC_SHA256,
        "crn_spec": PREFLIGHT_CRN_SPEC.as_dict(),
        "seed_index": PREFLIGHT_SEED_INDEX,
        "model_seed": PREFLIGHT_MODEL_SEED,
        "learner_seed": PREFLIGHT_LEARNER_SEED,
        "runner_seed": PREFLIGHT_RUNNER_SEED,
        "endpoints": [
            {"cell": cell, "arm": arm}
            for cell in CELLS for arm in ARMS
        ],
        "iterations_per_endpoint": 1,
        "disposable_training_deal_seed": disposable_training_deal,
        "evaluation_seed0": PREFLIGHT_EVAL_SEED0,
        "evaluation_rounds": PREFLIGHT_EVAL_ROUNDS,
        "registered_training_iterations": ITERATIONS,
        "registered_training_endpoints": TRAINING_ENDPOINTS,
        "registered_evaluation_rounds": EVALUATION_ROUNDS,
        "parallel_jobs": PARALLEL_JOBS,
        "timing_safety_factor": TIMING_SAFETY_FACTOR,
        "max_preflight_seconds": MAX_PREFLIGHT_SECONDS,
        "max_projected_wall_seconds": MAX_PROJECTED_WALL_SECONDS,
        "artifact_redaction": {
            "actions": False,
            "outcomes": False,
            "rewards": False,
            "losses": False,
            "values": False,
            "logits_margins_entropies": False,
            "model_or_checkpoint_identity": False,
        },
        "authority": {
            "packet_freeze_and_review_only": True,
            "training": False,
            "o1": False,
            "strength": False,
            "production": False,
        },
    }


def _algorithm(cell: str, arm: str) -> O0V2Algorithm:
    return O0V2Algorithm(
        crn_spec=PREFLIGHT_CRN_SPEC,
        training_seed_index=PREFLIGHT_SEED_INDEX,
        arm=arm,
        cell=cell,
        margin_spec=MARGIN_SPEC if cell == CELL_MARGIN else None,
    )


def _run_endpoint(root: Path, *, cell: str, arm: str) -> dict[str, Any]:
    bundle = new_o0_v2_bundle(
        model_seed=PREFLIGHT_MODEL_SEED,
        learner_rng_seed=PREFLIGHT_LEARNER_SEED,
    )
    initial = publish_initial_actor(
        bundle.learner, root / f"initial-{cell}-{arm}")
    algorithm = _algorithm(cell, arm)
    runner = new_o0_v2_runner(
        bundle=bundle,
        actor_ref=initial,
        snapshot_dir=root / f"candidates-{cell}-{arm}",
        root_seed=PREFLIGHT_RUNNER_SEED,
        algorithm=algorithm,
    )
    collector = SuphxO0V2Collector(runner.contract_sha256, algorithm)
    update = SuphxO0V2PolicyGradientUpdate(algorithm)
    started = time.perf_counter()
    receipt = runner.run_iteration(collector, update)
    elapsed = time.perf_counter() - started
    key_receipt = collector.key_receipt
    if key_receipt is None or receipt.samples_added <= 0 \
            or receipt.progress.next_iteration != 1:
        raise SuphxO0V2PreflightError("disposable endpoint work drift")
    counts: Counter[str] = Counter()
    # Replay contains the exact sealed batch after the completed iteration.
    for sample in runner.replay.logical_items():
        counts[surface_key(
            sample["role"], sample["decision_surface"])] += 1
    if sum(counts.values()) != receipt.samples_added:
        raise SuphxO0V2PreflightError("preflight sample work count drift")
    return {
        "cell": cell,
        "arm": arm,
        "iterations": 1,
        "rounds": 1,
        "temporary_updates": 1,
        "samples": receipt.samples_added,
        "role_surface_counts": dict(sorted(counts.items())),
        "elapsed_seconds": elapsed,
        "deal_seed": key_receipt["mechanics_receipt"]["deal_seed"],
        "first_public_decision_key": key_receipt[
            "first_public_decision_key"],
        "decision_count": key_receipt["decision_count"],
        "complete": True,
    }


def _run_evaluation_timing(model) -> list[float]:
    timings = []
    for offset in range(PREFLIGHT_EVAL_ROUNDS):
        actors = [_GreedyOrdinary(model, 1.0) for _ in range(4)]
        started = time.perf_counter()
        play_round(
            Game(random.Random(PREFLIGHT_EVAL_SEED0 + offset)),
            [_SetupComposite(actor) for actor in actors],
        )
        elapsed = time.perf_counter() - started
        if elapsed <= 0.0 or not math.isfinite(elapsed) \
                or any(actor.decisions <= 0 for actor in actors):
            raise SuphxO0V2PreflightError(
                "disposable evaluation timing work drift")
        timings.append(elapsed)
    return timings


def _coupling(endpoints: list[Mapping[str, Any]]) -> dict[str, Any]:
    result = {}
    for cell in CELLS:
        by_arm = {
            endpoint["arm"]: endpoint
            for endpoint in endpoints if endpoint["cell"] == cell
        }
        if set(by_arm) != set(ARMS):
            raise SuphxO0V2PreflightError("preflight endpoint grid drift")
        oracle = by_arm["oracle"]
        public = by_arm["public"]
        result[cell] = {
            "deal_seed_equal": oracle["deal_seed"] == public["deal_seed"],
            "first_public_decision_key_equal":
                oracle["first_public_decision_key"]
                == public["first_public_decision_key"],
            "decision_counts_positive":
                oracle["decision_count"] > 0
                and public["decision_count"] > 0,
        }
    return result


def _disposable_deals_disjoint(endpoints: Sequence[Mapping[str, Any]]) -> bool:
    endpoint_deals = {endpoint.get("deal_seed") for endpoint in endpoints}
    expected_disposable_deal = CrossedCRNStreams(
        PREFLIGHT_CRN_SPEC, PREFLIGHT_SEED_INDEX, 0).deal_seed()
    if endpoint_deals != {expected_disposable_deal}:
        return False
    registered_training = {
        CrossedCRNStreams(CRN_SPEC, index, iteration).deal_seed()
        for index in CRN_SPEC.training_seed_indices
        for iteration in range(CRN_SPEC.iterations_per_arm)
    }
    registered_evaluation = set(range(EVAL_SEED0, EVAL_SEED0 + EVAL_DEALS))
    disposable_evaluation = set(range(
        PREFLIGHT_EVAL_SEED0,
        PREFLIGHT_EVAL_SEED0 + PREFLIGHT_EVAL_ROUNDS,
    ))
    return not (
        endpoint_deals & registered_training
        or endpoint_deals & registered_evaluation
        or endpoint_deals & disposable_evaluation
        or disposable_evaluation & registered_training
        or disposable_evaluation & registered_evaluation
    )


def _projection_and_criteria(
        endpoints: list[Mapping[str, Any]], evaluation_times: list[float],
        elapsed: float, coupling: Mapping[str, Mapping[str, bool]]) \
        -> tuple[dict[str, float], dict[str, bool]]:
    if len(endpoints) != 4 \
            or any(not isinstance(endpoint, Mapping)
                   for endpoint in endpoints) \
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) or float(value) <= 0.0
                   for value in evaluation_times) \
            or isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) \
            or not math.isfinite(float(elapsed)) or float(elapsed) <= 0.0:
        raise SuphxO0V2PreflightError("preflight timing population drift")
    endpoint_times = [endpoint.get("elapsed_seconds") for endpoint in endpoints]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(float(value)) or float(value) <= 0.0
           for value in endpoint_times):
        raise SuphxO0V2PreflightError("endpoint timing population drift")
    maximum_training_iteration = max(float(value) for value in endpoint_times)
    maximum_evaluation_round = max(float(value) for value in evaluation_times)
    projected_training = (
        maximum_training_iteration * ITERATIONS * TRAINING_ENDPOINTS
        / PARALLEL_JOBS * TIMING_SAFETY_FACTOR
    )
    projected_evaluation = (
        maximum_evaluation_round * EVALUATION_ROUNDS
        / PARALLEL_JOBS * TIMING_SAFETY_FACTOR
    )
    projected_total = projected_training + projected_evaluation
    projection = {
        "maximum_training_iteration_seconds": maximum_training_iteration,
        "maximum_evaluation_round_seconds": maximum_evaluation_round,
        "training_seconds_with_safety": projected_training,
        "evaluation_seconds_with_safety": projected_evaluation,
        "total_wall_seconds_with_safety": projected_total,
    }
    endpoint_shapes_valid = all(
        isinstance(endpoint, Mapping)
        and set(endpoint) == _ENDPOINT_FIELDS
        and isinstance(endpoint.get("deal_seed"), int)
        and not isinstance(endpoint.get("deal_seed"), bool)
        and endpoint["deal_seed"] >= 0
        and isinstance(endpoint.get("first_public_decision_key"), str)
        and len(endpoint["first_public_decision_key"]) == 64
        and all(character in "0123456789abcdef"
                for character in endpoint["first_public_decision_key"])
        for endpoint in endpoints
    )
    criteria = {
        "exact_four_endpoint_grid": {
            (endpoint.get("cell"), endpoint.get("arm"))
            for endpoint in endpoints
        } == {(cell, arm) for cell in CELLS for arm in ARMS}
        and endpoint_shapes_valid,
        "every_endpoint_one_round_update_and_positive_samples": all(
            endpoint.get("complete") is True
            and endpoint.get("iterations") == 1
            and endpoint.get("rounds") == 1
            and endpoint.get("temporary_updates") == 1
            and isinstance(endpoint.get("samples"), int)
            and not isinstance(endpoint.get("samples"), bool)
            and endpoint["samples"] > 0
            and endpoint.get("decision_count") == endpoint["samples"]
            and isinstance(endpoint.get("role_surface_counts"), Mapping)
            and set(endpoint["role_surface_counts"]) == set(EXPECTED_SURFACES)
            and all(isinstance(value, int) and not isinstance(value, bool)
                    and value > 0
                    for value in endpoint["role_surface_counts"].values())
            and sum(endpoint["role_surface_counts"].values())
            == endpoint["samples"]
            for endpoint in endpoints),
        "both_cells_share_first_deal_and_public_key":
            set(coupling) == set(CELLS)
            and all(all(values.values()) for values in coupling.values())
            and len({endpoint["deal_seed"] for endpoint in endpoints}) == 1
            and len({endpoint["first_public_decision_key"]
                     for endpoint in endpoints}) == 1,
        "disposable_deals_are_fresh_and_disjoint":
            _disposable_deals_disjoint(endpoints),
        "evaluation_timing_population_complete":
            len(evaluation_times) == PREFLIGHT_EVAL_ROUNDS,
        "preflight_within_600_seconds": elapsed <= MAX_PREFLIGHT_SECONDS,
        "projected_total_with_safety_within_8_hours":
            projected_total <= MAX_PROJECTED_WALL_SECONDS,
    }
    return projection, criteria


def _forbidden_paths(value: object, path: str = "$") -> list[str]:
    problems = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            declaration_only = (
                path.startswith("$.contract")
                or path == "$.source_identity.files"
                or path == "$.coupling"
            )
            if not declaration_only and normalized != "score_redacted" \
                    and any(token in normalized for token in _FORBIDDEN_KEYS):
                problems.append(f"{path}.{key}")
            problems.extend(_forbidden_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            problems.extend(_forbidden_paths(child, f"{path}[{index}]"))
    return problems


def _payload() -> dict[str, Any]:
    runtime = runtime_identity()
    sources = source_identity()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="suphx-o0-v2-preflight-") as temp:
        temporary = Path(temp)
        endpoints = [
            _run_endpoint(temporary, cell=cell, arm=arm)
            for cell in CELLS for arm in ARMS
        ]
        model = new_o0_v2_bundle(
            model_seed=PREFLIGHT_MODEL_SEED,
            learner_rng_seed=PREFLIGHT_LEARNER_SEED,
        ).learner
        evaluation_times = _run_evaluation_timing(model)
    elapsed = time.perf_counter() - started
    coupling = _coupling(endpoints)
    projection, criteria = _projection_and_criteria(
        endpoints, evaluation_times, elapsed, coupling)
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "claim": "score-redacted Air capacity only; no learning conclusion",
        "complete": True,
        "score_redacted": True,
        "source_identity": sources,
        "runtime": runtime,
        "contract": _contract(),
        "contract_sha256": state_digest(_contract()),
        "endpoints": endpoints,
        "coupling": coupling,
        "evaluation_elapsed_seconds": evaluation_times,
        "preflight_elapsed_seconds": elapsed,
        "projection": projection,
        "criteria": criteria,
        "passed": all(criteria.values()),
        "temporary_training_updates": 4,
        "temporary_models_retained": False,
        "packet_freeze_and_review_authorized": all(criteria.values()),
        "training_authorized": False,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    forbidden = _forbidden_paths(payload)
    if forbidden:
        raise SuphxO0V2PreflightError(
            f"preflight payload leaked forbidden result fields: {forbidden}")
    return payload


def _require_out(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if resolved != Path(EXPECTED_PREFLIGHT_PATH).resolve():
        raise SuphxO0V2PreflightError(
            "preflight output differs from exact packet path")
    return resolved


def run_preflight(path: str | Path) -> CheckpointRef:
    out = _require_out(path)
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"refusing to overwrite preflight artifact: {out}")
    ref = _publish_json(out, _payload())
    verify_preflight(out)
    return ref


def verify_preflight(path: str | Path) -> dict[str, Any]:
    target = _require_out(path)
    ref = CheckpointRef.capture(_require_regular_final(target))
    payload = _load_json(ref)
    expected_fields = {
        "schema", "claim", "complete", "score_redacted", "source_identity",
        "runtime", "contract", "contract_sha256", "endpoints", "coupling",
        "evaluation_elapsed_seconds", "preflight_elapsed_seconds",
        "projection", "criteria", "passed", "temporary_training_updates",
        "temporary_models_retained", "packet_freeze_and_review_authorized",
        "training_authorized", "o1_authorized", "strength_claim",
        "production_promotion",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_fields \
            or payload.get("schema") != PREFLIGHT_SCHEMA \
            or payload.get("claim") \
            != "score-redacted Air capacity only; no learning conclusion" \
            or payload.get("complete") is not True \
            or payload.get("score_redacted") is not True \
            or payload.get("contract") != _contract() \
            or payload.get("contract_sha256") != state_digest(_contract()) \
            or payload.get("source_identity") != source_identity() \
            or payload.get("runtime") != runtime_identity() \
            or payload.get("temporary_training_updates") != 4 \
            or payload.get("temporary_models_retained") is not False \
            or any(payload.get(name) is not False for name in (
                "training_authorized", "o1_authorized", "strength_claim",
                "production_promotion")):
        raise SuphxO0V2PreflightError("preflight identity/authority drift")
    endpoints = payload.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 4 \
            or {(value.get("cell"), value.get("arm"))
                for value in endpoints if isinstance(value, Mapping)} \
            != {(cell, arm) for cell in CELLS for arm in ARMS}:
        raise SuphxO0V2PreflightError("preflight endpoint population drift")
    coupling = _coupling(endpoints)
    if payload.get("coupling") != coupling:
        raise SuphxO0V2PreflightError("preflight coupling recomputation drift")
    evaluation_times = payload.get("evaluation_elapsed_seconds")
    elapsed = payload.get("preflight_elapsed_seconds")
    if not isinstance(evaluation_times, list):
        raise SuphxO0V2PreflightError("preflight evaluation timings drift")
    projection, expected_criteria = _projection_and_criteria(
        endpoints, evaluation_times, elapsed, coupling)
    if payload.get("projection") != projection \
            or payload.get("criteria") != expected_criteria:
        raise SuphxO0V2PreflightError("preflight projection/criteria drift")
    criteria = payload.get("criteria")
    if not isinstance(criteria, Mapping) or not criteria \
            or any(not isinstance(value, bool) for value in criteria.values()) \
            or payload.get("passed") is not all(criteria.values()) \
            or payload.get("packet_freeze_and_review_authorized") \
            is not payload.get("passed"):
        raise SuphxO0V2PreflightError("preflight verdict arithmetic drift")
    if _forbidden_paths(payload):
        raise SuphxO0V2PreflightError("preflight contains forbidden result key")
    ref.verify()
    return dict(payload)


def cli_main(argv: list[str] | None = None) -> int:
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True, warn_only=False)
    parser = argparse.ArgumentParser(
        description="Score-redacted Air O0-v2 capacity preflight")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--out", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            ref = run_preflight(args.out)
            payload = verify_preflight(args.out)
            print(json.dumps({
                "preflight": ref.as_dict(),
                "passed": payload["passed"],
                "packet_freeze_and_review_authorized": payload[
                    "packet_freeze_and_review_authorized"],
                "training_authorized": False,
                "strength_claim": False,
                "production_promotion": False,
            }, sort_keys=True), flush=True)
            return 0 if payload["passed"] else 4
        payload = verify_preflight(args.input)
        print(json.dumps({
            "verified": True,
            "passed": payload["passed"],
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
        }, sort_keys=True), flush=True)
        return 0 if payload["passed"] else 4
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 3
