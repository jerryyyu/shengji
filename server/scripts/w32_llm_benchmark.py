"""Bounded, paired W32-versus-LLM benchmark (#355).

The command is deliberately a dry-run unless ``--run`` is supplied.  A run
uses one prepared private root per seed, then replays that root for all four
model/information arms and both seat mirrors.  This is an execution harness,
not a claim of production runtime parity.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from shengji.ai import env
from shengji.ai.registry import make_bot, register_cwv_bury_policies
from shengji.engine.cards import RANKS
from shengji.engine.game import Game
from shengji.luna.atomic_io import publish_exclusive_bytes
from shengji.luna.benchmark_games import play_mirror
from shengji.luna.benchmark_transport import BenchmarkTransport
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.game import _state_snapshot
from shengji.train.cwv_bury_policy import CWVBuryConfig, bury_env_recipe


SCHEMA = "w32-llm-benchmark-v1"
MODEL_NAMES = {"sol": "gpt-5.6-sol", "luna": "gpt-5.6-luna"}
INFORMATION_MODES = ("actor-only", "perfect")


class BenchmarkRefusal(ValueError):
    """The requested benchmark cannot be admitted safely."""


class BudgetStop(RuntimeError):
    """A cooperative wall or soft-token budget stopped a new operation."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _json_safe(value: object) -> object:
    """Make injected test doubles and policy receipts canonical without repr drift."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return repr(value)


def _parse_csv(value: str, *, label: str) -> list[str]:
    values = [part.strip() for part in value.split(",") if part.strip()]
    if not values:
        raise BenchmarkRefusal(f"{label} cannot be empty")
    return values


def parse_seeds(values: Sequence[str] | str) -> tuple[int, ...]:
    """Parse explicit integer seeds, accepting both repeated and CSV forms."""
    if isinstance(values, str):
        values = (values,)
    parts: list[str] = []
    for value in values:
        parts.extend(_parse_csv(str(value), label="seeds"))
    try:
        seeds = tuple(int(value, 10) for value in parts)
    except ValueError as exc:
        raise BenchmarkRefusal("seeds must be explicit integers") from exc
    if len(set(seeds)) != len(seeds):
        raise BenchmarkRefusal("seeds must be unique")
    return seeds


def _checkpoint_identity(path: str | os.PathLike) -> dict[str, str]:
    checkpoint = Path(path).expanduser().resolve()
    if not checkpoint.is_file() or checkpoint.is_symlink():
        raise BenchmarkRefusal("checkpoint must be a regular file")
    raw = checkpoint.read_bytes()
    return {"path": str(checkpoint), "sha256": _sha_bytes(raw)}


def _source_identity() -> dict[str, object]:
    source = Path(__file__).resolve()
    identity: dict[str, object] = {
        "script": str(source), "script_sha256": _sha_bytes(source.read_bytes()),
        "runtime_production_parity": False,
    }
    try:
        identity["git"] = subprocess.check_output(
            ("git", "rev-parse", "HEAD"), cwd=source.parent.parent,
            stderr=subprocess.DEVNULL, text=True, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        identity["git"] = None
    return identity


def _registered_baseline(checkpoint: str, *, register=register_cwv_bury_policies,
                         recipe_reader=bury_env_recipe) -> tuple[str, dict[str, object]]:
    """Register the explicit hybrid/static32, two-second bury recipe locally.

    ``environ`` is a copy.  In particular, this function never writes
    ``os.environ``; registry mutation is the explicit registration operation.
    """
    environ = dict(os.environ)
    environ.update({
        "SHENGJI_CWV_SHORTLIST_CKPT": str(checkpoint),
        "SHENGJI_CWV_SHORTLIST_WORLDS": "32",
        "SHENGJI_CWV_SHORTLIST_ENCODING": "mlp-static",
        "SHENGJI_CWV_BURY_ARM": "hybrid",
        "SHENGJI_CWV_BURY_SERVING_BUDGET_SECONDS": "2",
    })
    recipe = recipe_reader(environ)
    if recipe is None or len(recipe) != 6:
        raise BenchmarkRefusal("explicit W32 bury recipe could not be resolved")
    resolved_checkpoint, worlds, play_recipe, arm, bury_config, budget = recipe
    if (str(Path(resolved_checkpoint).resolve()) != str(Path(checkpoint).resolve())
            or tuple(worlds) != (32,) or arm != "hybrid"
            or type(bury_config) is not CWVBuryConfig
            or budget != 2.0 or play_recipe.get("encoding") != "mlp-static"):
        raise BenchmarkRefusal("resolved baseline recipe is not hybrid budget2s/static32")
    names = register(resolved_checkpoint, worlds, arm=arm,
                     bury_config=bury_config, serving_budget_seconds=budget,
                     **play_recipe)
    if not names:
        raise BenchmarkRefusal("baseline registration returned no policy names")
    return str(names[0]), {
        "checkpoint": str(Path(resolved_checkpoint).resolve()), "worlds": list(worlds),
        "arm": arm, "bury_config": _json_safe(vars(bury_config)),
        "serving_budget_seconds": budget, "play_recipe": _json_safe(play_recipe),
        "registered_names": list(names),
    }


@dataclass
class _Budget:
    wall_seconds: float
    token_limit: int | None
    started: float = 0.0
    tokens: int = 0

    def __post_init__(self) -> None:
        self.started = time.monotonic()
        if self.wall_seconds <= 0:
            raise BenchmarkRefusal("wall budget must be positive")
        if self.token_limit is not None and self.token_limit <= 0:
            raise BenchmarkRefusal("soft token threshold must be positive")

    @property
    def deadline_ns(self) -> int:
        return time.monotonic_ns() + max(0, int((self.wall_seconds -
            (time.monotonic() - self.started)) * 1_000_000_000))

    def check(self, what: str) -> None:
        elapsed = time.monotonic() - self.started
        if elapsed >= self.wall_seconds:
            raise BudgetStop(f"wall budget exhausted before {what}")
        if self.token_limit is not None and self.tokens >= self.token_limit:
            raise BudgetStop(f"soft token threshold exhausted before {what}")

    def charge(self, usage: object) -> None:
        if not isinstance(usage, Mapping):
            return
        inp, out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        if (isinstance(inp, bool) or not isinstance(inp, int)
                or isinstance(out, bool) or not isinstance(out, int)
                or inp < 0 or out < 0):
            return
        # Cached input is already part of input_tokens; never add it again.
        self.tokens += inp + out


class _BudgetedPlanner:
    def __init__(self, provider: Callable[[object], object], budget: _Budget):
        self.provider, self.budget = provider, budget

    @property
    def calls(self):
        return self.provider.calls

    def __call__(self, packet):
        self.budget.check("provider call")
        before = len(getattr(self.provider, "calls", ()))
        try:
            return self.provider(packet)
        finally:
            calls = getattr(self.provider, "calls", ())
            if len(calls) > before:
                receipt = calls[-1]
                self.budget.charge(receipt.get("usage") if isinstance(receipt, Mapping)
                                    else None)


def _root_snapshot(game: object, seed: int, rank_index: int) -> dict[str, object]:
    rnd = getattr(game, "round", None)
    try:
        snapshot = _state_snapshot(rnd)
    except Exception:
        snapshot = _json_safe(getattr(rnd, "__dict__", rnd))
    return {"schema": "w32-llm-benchmark-root-v1", "seed": seed,
            "rank_index": rank_index, "level_idx": _json_safe(getattr(game, "level_idx", None)),
            "banker": _json_safe(getattr(rnd, "banker", getattr(game, "banker", None))),
            "round": snapshot}


def _publish(path: Path, value: object) -> None:
    raw = canonical_json_bytes(value)
    publish_exclusive_bytes(path, raw, mode=0o400)


def _bootstrap(values: Sequence[float], *, seed: int) -> list[float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(statistics.fmean(rng.choices(list(values), k=n)) for _ in range(2000))
    return [means[49], means[1950]]


def _summary(rows: Sequence[Mapping[str, object]], *, arm: str, seed: int) -> dict[str, object]:
    complete = [row for row in rows if row.get("complete") is True]
    by_seed: dict[int, dict[int, Mapping[str, object]]] = {}
    for row in complete:
        by_seed.setdefault(int(row["seed"]), {})[int(row["flip"])] = row
    paired: list[float] = []
    for pair in by_seed.values():
        if 0 in pair and 1 in pair:
            # One deal is one paired cluster; mirrors are never treated as
            # independent deal samples.
            paired.append((float(pair[0].get("signed_levels", 0)) +
                           float(pair[1].get("signed_levels", 0))) / 2.0)
    calls = [call for row in rows for call in row.get("calls", ())
             if isinstance(call, Mapping)]
    raw_tokens = sum(int(call.get("usage", {}).get("input_tokens", 0)) +
                     int(call.get("usage", {}).get("output_tokens", 0))
                     for call in calls if isinstance(call.get("usage"), Mapping))
    return {"arm": arm, "complete_mirrors": len(complete),
            "complete_deal_pairs": len(paired), "paired_signed_levels": paired,
            "paired_signed_level_mean": statistics.fmean(paired) if paired else None,
            "deal_cluster_ci95": _bootstrap(paired, seed=seed),
            "failures": [dict(row) for row in rows if row.get("complete") is not True],
            "raw_cost_tokens": raw_tokens}


def run_benchmark(*, checkpoint: str, policy: str, output: str | os.PathLike,
                  seeds: Sequence[int], models: Sequence[str] = ("sol", "luna"),
                  information: Sequence[str] = INFORMATION_MODES,
                  wall_seconds: float = 1800.0, token_limit: int | None = None,
                  run: bool = False, codex_binary: str = "codex",
                  timeout_seconds: int = 90, runner=play_mirror,
                  transport_factory=BenchmarkTransport, game_factory=Game,
                  prepare_fn=env.prepare_round, baseline_factory=None,
                  register_fn=register_cwv_bury_policies,
                  recipe_reader=bury_env_recipe,
                  bot_factory=make_bot) -> dict[str, object]:
    """Validate, optionally execute, and return the sealed benchmark report."""
    if run and (type(token_limit) is not int or token_limit <= 0):
        raise BenchmarkRefusal("--run requires a positive --soft-token-limit")
    checkpoint_id = _checkpoint_identity(checkpoint)
    models = tuple(models)
    information = tuple(information)
    seeds = parse_seeds([str(seed) for seed in seeds])
    if any(model not in MODEL_NAMES for model in models):
        raise BenchmarkRefusal("models must be sol and/or luna")
    if any(mode not in INFORMATION_MODES for mode in information):
        raise BenchmarkRefusal("unknown information mode")
    if not models or not information or not seeds:
        raise BenchmarkRefusal("models, information, and seeds cannot be empty")
    output_path = Path(output).expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        raise BenchmarkRefusal("output must be a fresh path")
    baseline_name, baseline_recipe = _registered_baseline(
        checkpoint_id["path"], register=register_fn, recipe_reader=recipe_reader)
    if policy != baseline_name:
        raise BenchmarkRefusal(
            f"requested policy {policy!r} is not the registered baseline {baseline_name!r}")
    source = _source_identity()
    config = {"schema": SCHEMA, "checkpoint": checkpoint_id, "policy": policy,
              "seeds": list(seeds), "models": list(models),
              "information": list(information), "wall_seconds": wall_seconds,
              "soft_token_limit": token_limit, "run": bool(run),
              "baseline_recipe": baseline_recipe, "source": source,
              "claim": "benchmark execution only; runtime production parity is not claimed"}
    if not run:
        return {"schema": SCHEMA, "mode": "dry-run", "config": config,
                "planned_arms": [f"{model}-{mode}" for model in models for mode in information],
                "planned_mirrors": len(seeds) * 2 * len(models) * len(information)}

    try:
        output_path.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise BenchmarkRefusal("output must be a fresh path") from exc
    _publish(output_path / "config.json", config)
    budget = _Budget(float(wall_seconds), token_limit)
    baseline_fn = baseline_factory or (lambda seat, seed: bot_factory(policy, seed=seed + seat))
    roots: dict[int, object] = {}
    root_hashes: dict[int, str] = {}
    setup_failures: dict[int, str] = {}
    for index, seed in enumerate(seeds):
        game = game_factory(random.Random(seed))
        rank_index = index % len(RANKS)
        game.level_idx = [rank_index, rank_index]
        game.banker = seed % 4
        try:
            budget.check("deal setup")
            setup = [baseline_fn(seat, seed) for seat in range(4)]
            prepare_fn(game, setup)
            root = _root_snapshot(game, seed, rank_index)
            root_sha = _sha(root)
            receipt = {"schema": "w32-llm-benchmark-setup-v1", "seed": seed,
                       "banker": seed % 4, "rank_index": rank_index,
                       "policy": policy, "root_sha256": root_sha,
                       "bury": [_json_safe(getattr(bot, "bury_recipe_identity", None))
                                for bot in setup]}
            _publish(output_path / f"root-{seed}.json", root)
            _publish(output_path / f"setup-{seed}.json", receipt)
            roots[seed], root_hashes[seed] = game, root_sha
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            setup_failures[seed] = error
            _publish(output_path / f"setup-{seed}.error.json",
                     {"schema": "w32-llm-benchmark-setup-error-v1", "seed": seed,
                      "error": error})

    all_rows: list[dict[str, object]] = []
    summaries: dict[str, object] = {}
    for model in models:
        for mode in information:
            arm = f"{model}-{mode}"
            arm_rows: list[dict[str, object]] = []
            for seed in seeds:
                for flip in (0, 1):
                    key = f"{arm}-seed{seed}-flip{flip}"
                    if seed in setup_failures:
                        row = {"schema": "w32-llm-benchmark-mirror-v1", "key": key,
                               "arm": arm, "model": model, "information": mode,
                               "seed": seed, "flip": flip, "complete": False,
                               "status": "setup_failed", "error": setup_failures[seed],
                               "calls": []}
                    else:
                        transports: list[object] = []
                        try:
                            budget.check("mirror")
                            evidence = output_path / "evidence" / arm / f"seed-{seed}-flip-{flip}"
                            evidence.mkdir(mode=0o700, parents=True, exist_ok=True)

                            def planner_factory(seat, *, _model=model, _evidence=evidence):
                                budget.check("planner construction")
                                transport = transport_factory(
                                    evidence_root=_evidence / f"seat-{seat}",
                                    model=MODEL_NAMES[_model], codex_binary=codex_binary,
                                    timeout_seconds=timeout_seconds,
                                    deadline_provider=lambda: budget.deadline_ns)
                                transports.append(transport)
                                return _BudgetedPlanner(transport, budget)

                            row = dict(runner(
                                roots[seed], flip=flip, information=mode,
                                planner_factory=planner_factory,
                                baseline_factory=baseline_fn, seed=seed,
                                before_decision=lambda: budget.check("decision")))
                            row.update(schema="w32-llm-benchmark-mirror-v1", key=key,
                                       arm=arm, model=model, information=mode,
                                       seed=seed, flip=flip)
                            row["calls"] = [call for transport in transports
                                            for call in getattr(transport, "calls", ())]
                        except Exception as exc:
                            row = {"schema": "w32-llm-benchmark-mirror-v1", "key": key,
                                   "arm": arm, "model": model, "information": mode,
                                   "seed": seed, "flip": flip, "complete": False,
                                   "error": f"{type(exc).__name__}: {exc}",
                                   "calls": [call for transport in transports
                                             for call in getattr(transport, "calls", ())]}
                    _publish(output_path / f"mirror-{model}-{mode}-{seed}-{flip}.json", row)
                    arm_rows.append(row)
                    all_rows.append(row)
            summaries[arm] = _summary(
                arm_rows, arm=arm,
                seed=int.from_bytes(hashlib.sha256(arm.encode("ascii")).digest()[:4], "big"))
    report = {"schema": SCHEMA, "mode": "run", "config": config,
              "roots": {str(seed): root_hashes.get(seed) for seed in seeds},
              "summaries": summaries, "mirrors": all_rows,
              "budget": {"tokens": budget.tokens,
                         "wall_seconds": time.monotonic() - budget.started},
              "setup_failures": setup_failures}
    _publish(output_path / "result.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", "--out", dest="output", required=True)
    parser.add_argument("--seeds", nargs="+", required=True)
    parser.add_argument("--models", default="sol,luna")
    parser.add_argument("--information", "--info", dest="information",
                        default="actor-only,perfect")
    parser.add_argument("--wall-seconds", type=float, default=1800.0)
    parser.add_argument("--soft-token-limit", "--soft-token-stop", "--token-limit",
                        dest="token_limit", type=int)
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--run", action="store_true", help="execute provider calls")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_benchmark(
            checkpoint=args.checkpoint, policy=args.policy, output=args.output,
            seeds=args.seeds, models=_parse_csv(args.models, label="models"),
            information=_parse_csv(args.information, label="information"),
            wall_seconds=args.wall_seconds, token_limit=args.token_limit,
            run=args.run, codex_binary=args.codex_binary,
            timeout_seconds=args.timeout_seconds)
    except (BenchmarkRefusal, ValueError) as exc:
        build_parser().error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
