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
import inspect
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
from shengji.luna.benchmark_failure_protocol import (
    FAIL_STOP, PRESERVE_ILLEGAL, attempt_disposition, summarize_scheduled,
)
from shengji.luna.benchmark_recipes import PreparedRecipe
from shengji.luna.benchmark_transport import BenchmarkTransport, CAPACITY_RETRY_DELAYS
from shengji.luna.canonical import canonical_json_bytes
from shengji.luna.game import _round_from_snapshot, _state_snapshot
from shengji.train.cwv_bury_policy import CWVBuryConfig, bury_env_recipe


SCHEMA = "w32-llm-benchmark-v1"
MODEL_NAMES = {"sol": "gpt-5.6-sol", "luna": "gpt-5.6-luna"}
INFORMATION_MODES = ("actor-only", "perfect")
PANEL_POLICIES = ("smv3-pv", "soft-pv", "js-m1-shortlist", "m1-prior",
                  "w32-original", "mc-lcb", "mc-strong", "mc", "smart")
ROOT_SOURCE_SCHEMA = "w32-llm-panel-roots-v1"
ROOT_SOURCE_SETUP_SCHEMA = "w32-llm-panel-root-setup-v1"


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


def _callable_source_identity(value: object) -> dict[str, object]:
    """Identify the exact local source used to make a common root."""
    source = inspect.getsourcefile(value)
    if source is None:
        raise BenchmarkRefusal("panel root setup source is unavailable")
    path = Path(source).resolve()
    if not path.is_file() or path.is_symlink():
        raise BenchmarkRefusal("panel root setup source is not a regular file")
    return {"module": getattr(value, "__module__", None),
            "qualname": getattr(value, "__qualname__", None),
            "path": str(path), "sha256": _sha_bytes(path.read_bytes())}


def _panel_setup_identity() -> dict[str, object]:
    """Return the allowlisted SmartBot/current-engine root setup identity."""
    from shengji.ai.env import prepare_round
    from shengji.ai.smart import SmartBot

    return {
        "schema": ROOT_SOURCE_SETUP_SCHEMA,
        "seats": 4,
        "policy": "SmartBot",
        "engine": _callable_source_identity(Game),
        "prepare_round": _callable_source_identity(prepare_round),
        "smartbot": _callable_source_identity(SmartBot),
        "snapshot": _callable_source_identity(_root_snapshot),
    }


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
    # A failed prior attempt is not allowed to disappear when its key later
    # succeeds.  Continuations put that attempt under this private field;
    # fresh rows have no such field.
    calls.extend(call for row in rows
                 for call in (row.get("prior_attempt", {}).get("calls", ())
                              if isinstance(row.get("prior_attempt"), Mapping)
                              else ())
                 if isinstance(call, Mapping))
    raw_tokens = sum(int(call.get("usage", {}).get("input_tokens", 0)) +
                     int(call.get("usage", {}).get("output_tokens", 0))
                     for call in calls if isinstance(call.get("usage"), Mapping))
    prior_failures = []
    for row in rows:
        prior = row.get("prior_attempt")
        if isinstance(prior, Mapping) and prior.get("complete") is not True:
            prior_failures.append({
                "key": row.get("key"), "error": prior.get("error"),
                "cost_tokens": prior.get("cost_tokens", 0),
                "source_row_sha256": prior.get("source_row_sha256"),
            })
    return {"arm": arm, "complete_mirrors": len(complete),
            "complete_deal_pairs": len(paired), "paired_signed_levels": paired,
            "paired_signed_level_mean": statistics.fmean(paired) if paired else None,
            "deal_cluster_ci95": _bootstrap(paired, seed=seed),
            "failures": [dict(row) for row in rows if row.get("complete") is not True],
            "prior_failures": prior_failures,
            "raw_cost_tokens": raw_tokens}


def _row_cost(row: Mapping[str, object]) -> int:
    calls = row.get("calls", ())
    return sum(int(call.get("usage", {}).get("input_tokens", 0)) +
               int(call.get("usage", {}).get("output_tokens", 0))
               for call in calls if isinstance(call, Mapping)
               and isinstance(call.get("usage"), Mapping))


def _load_json_file(path: Path, *, label: str) -> tuple[object, bytes]:
    if not path.is_file() or path.is_symlink():
        raise BenchmarkRefusal(f"prior {label} must be a regular file")
    raw = path.read_bytes()
    try:
        return json.loads(raw), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkRefusal(f"prior {label} is not valid JSON") from exc


def _load_continuation(prior: str | os.PathLike, *, seeds: tuple[int, ...],
                       checkpoint: Mapping[str, str], policy: str,
                       baseline_recipe: Mapping[str, object],
                       models: tuple[str, ...],
                       information: tuple[str, ...]) -> dict[str, object]:
    """Read and validate a sealed prior report without touching its files."""
    prior_path = Path(prior).expanduser().resolve()
    if (not prior_path.is_dir() or prior_path.is_symlink()):
        raise BenchmarkRefusal("--continue-from must name a prior output directory")
    result_path = prior_path / "result.json"
    result_obj, result_raw = _load_json_file(result_path, label="result.json")
    if not isinstance(result_obj, Mapping) or result_obj.get("schema") != SCHEMA \
            or result_obj.get("mode") != "run":
        raise BenchmarkRefusal("prior result.json is not a terminal benchmark report")
    if (not isinstance(result_obj.get("summaries"), Mapping)
            or not isinstance(result_obj.get("budget"), Mapping)
            or not isinstance(result_obj.get("setup_failures"), Mapping)):
        raise BenchmarkRefusal("prior result.json is not a terminal benchmark report")
    prior_config = result_obj.get("config")
    if not isinstance(prior_config, Mapping):
        raise BenchmarkRefusal("prior result.json has no benchmark config")
    if prior_config.get("continue_from") is not None:
        raise BenchmarkRefusal("chained --continue-from is not supported")
    prior_checkpoint = prior_config.get("checkpoint")
    if (not isinstance(prior_checkpoint, Mapping)
            or prior_checkpoint.get("sha256") != checkpoint.get("sha256")):
        raise BenchmarkRefusal("prior checkpoint SHA does not match selected checkpoint")
    if prior_config.get("policy") != policy:
        raise BenchmarkRefusal("prior policy does not match selected policy")
    if prior_config.get("baseline_recipe") != dict(baseline_recipe):
        raise BenchmarkRefusal("prior baseline recipe does not match selected recipe")
    if (prior_config.get("seeds") != list(seeds)
            or prior_config.get("models") != list(models)
            or prior_config.get("information") != list(information)):
        raise BenchmarkRefusal("prior seeds/models/information must exactly match continuation")
    roots_obj = result_obj.get("roots")
    prior_rows = result_obj.get("mirrors")
    if not isinstance(roots_obj, Mapping) or not isinstance(prior_rows, list):
        raise BenchmarkRefusal("prior result.json is missing terminal roots or mirrors")
    rows_by_key: dict[str, Mapping[str, object]] = {}
    for row in prior_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("key"), str):
            raise BenchmarkRefusal("prior mirror row is malformed")
        key = str(row["key"])
        if key in rows_by_key:
            raise BenchmarkRefusal("prior mirror keys are not unique")
        rows_by_key[key] = row
    expected_keys = {
        f"{model}-{mode}-seed{seed}-flip{flip}"
        for model in models for mode in information for seed in seeds
        for flip in (0, 1)
    }
    if set(rows_by_key) != expected_keys:
        raise BenchmarkRefusal("prior terminal report does not cover selected mirrors")
    # Seal every source row before creating the new output or invoking a
    # retry.  In particular, an incomplete row must not be discovered as
    # corrupt only after its replacement has already spent provider budget.
    source_rows: dict[str, dict[str, object]] = {}
    for model in models:
        for mode in information:
            for seed in seeds:
                for flip in (0, 1):
                    key = f"{model}-{mode}-seed{seed}-flip{flip}"
                    source_path = prior_path / f"mirror-{model}-{mode}-{seed}-{flip}.json"
                    source_obj, source_raw = _load_json_file(
                        source_path, label=f"mirror row {key}")
                    prior_row = rows_by_key[key]
                    if (not isinstance(source_obj, Mapping)
                            or source_obj.get("key") != key
                            or canonical_json_bytes(source_obj)
                            != canonical_json_bytes(prior_row)):
                        raise BenchmarkRefusal(
                            f"prior mirror row {key} disagrees with result.json")
                    source_rows[key] = {
                        "row": source_obj, "path": str(source_path),
                        "sha256": _sha_bytes(source_raw),
                    }
    imported_roots: dict[int, Mapping[str, object]] = {}
    for seed in seeds:
        root_path = prior_path / f"root-{seed}.json"
        root_obj, root_raw = _load_json_file(root_path, label=f"root-{seed}.json")
        if not isinstance(root_obj, Mapping) or root_obj.get("seed") != seed \
                or not isinstance(root_obj.get("round"), Mapping):
            raise BenchmarkRefusal(f"prior root-{seed}.json is malformed")
        expected = roots_obj.get(str(seed))
        if not isinstance(expected, str) or _sha(root_obj) != expected:
            raise BenchmarkRefusal(f"prior root hash mismatch for seed {seed}")
        # Keep the bytes identity available to callers/tests, while the root
        # itself remains the decoded private snapshot used for restoration.
        imported_roots[seed] = dict(root_obj, _source_bytes_sha256=_sha_bytes(root_raw))
    return {"path": str(prior_path), "result_sha256": _sha_bytes(result_raw),
            "result": result_obj, "rows": rows_by_key, "source_rows": source_rows,
            "roots": imported_roots,
            "prior_cost_tokens": sum(_row_cost(row) for row in rows_by_key.values()),
            "prior_attempts": len(rows_by_key)}


def _compatible_panel_setup(recorded: object, *, report_sha256: str) -> bool:
    """Compare setup content, not checkout location; admit one reviewed legacy source.

    The original panel recorded the whole benchmark module as the snapshot
    identity. Retry/accounting edits in that module do not change its snapshot
    producer. Only the exact sealed Oct 2 report gets that compatibility bridge,
    and only while the snapshot functions and their engine serializer remain
    byte-identical to the reviewed producer. Root hashes and exact restoration
    are still checked independently by the caller.
    """
    expected = _panel_setup_identity()
    if not isinstance(recorded, Mapping) or set(recorded) != set(expected):
        return False
    for key in ("schema", "seats", "policy"):
        if recorded[key] != expected[key] or type(recorded[key]) is not type(expected[key]):
            return False
    normalized = {}
    current = {}
    for key in ("engine", "prepare_round", "smartbot", "snapshot"):
        value = recorded[key]
        if (not isinstance(value, Mapping) or set(value) != set(expected[key])
                or any(type(item) is not str for item in value.values())):
            return False
        normalized[key] = {k: v for k, v in value.items() if k != "path"}
        current[key] = {k: v for k, v in expected[key].items() if k != "path"}
    if normalized == current:
        return True
    if report_sha256 != "8ed56de254e7c7ff4341905a02a9a3dd2346412db04b6902f2098b0b839c5f5e":
        return False
    if normalized["snapshot"].get("sha256") != "bd52ee31cb2d07345b4a2de1063c659dd1558313ba4605572f1e6a397ac90700":
        return False
    normalized["snapshot"]["sha256"] = current["snapshot"]["sha256"]
    if normalized['prepare_round'] != current['prepare_round']:
        # Exact reviewed whole-file pair: the sole delta adds an optional
        # play-error callback to play_prepared_round, not prepare_round.
        # This does not admit arbitrary future edits or any other root source.
        if (normalized['prepare_round'].get('sha256') !=
                'c61f7cebf2133ad1cc6daaad8698f246178d6ebf41a4b6e569888a7b373a6d26'
                or current['prepare_round'].get('sha256') !=
                'fe434d5a30e32d38c4c3aa3c4812e11c10c8534b31a4a23da9155c34428ecd87'):
            return False
        normalized['prepare_round']['sha256'] = current['prepare_round']['sha256']
    if normalized != current:
        return False
    definitions = (
        (_root_snapshot, "dacbb1e2dc74aa3ed191732ccdfe2bd95da2b9e682a10a6d5a479b250408e392"),
        (_json_safe, "ed50cd407eaee087abc37cc6075dc243878c35e84f1404ff8e5877b8fd47351c"),
    )
    if any(_sha_bytes(inspect.getsource(fn).strip().encode()) != digest
           for fn, digest in definitions):
        return False
    return _callable_source_identity(_state_snapshot)["sha256"] == \
        "03c8569ca8232c49218264047d7221c310288701e7bc6ca1cd81b08e8064787f"

def _prepared_root_identity(root: Mapping[str, object], *, seed: int,
                            rank_index: int, expected_banker: int | None = None) -> None:
    """Validate the private, replayable root contract used by root-only imports."""
    if root.get("schema") != "w32-llm-benchmark-root-v1":
        raise BenchmarkRefusal(f"prior root-{seed}.json has an unknown schema")
    if (type(root.get("seed")) is not int or root.get("seed") != seed
            or type(root.get("rank_index")) is not int
            or root.get("rank_index") != rank_index):
        raise BenchmarkRefusal(f"prior root-{seed}.json seed/rank_index mismatch")
    levels = root.get("level_idx")
    if (type(levels) is not list or len(levels) != 2
            or any(type(level) is not int or not 0 <= level < len(RANKS)
                   for level in levels)
            or levels != [rank_index, rank_index]):
        raise BenchmarkRefusal(f"prior root-{seed}.json has invalid level_idx")
    banker = root.get("banker")
    if (type(banker) is not int or not 0 <= banker < 4):
        raise BenchmarkRefusal(f"prior root-{seed}.json has invalid banker")
    if expected_banker is not None and banker != expected_banker:
        raise BenchmarkRefusal(f"prior root-{seed}.json banker identity mismatch")
    snapshot = root.get("round")
    if (not isinstance(snapshot, Mapping) or snapshot.get("phase") != "play"
            or snapshot.get("banker") != banker):
        raise BenchmarkRefusal(f"prior root-{seed}.json is not a play-phase root")


def _load_root_source_roots(result_obj: Mapping[str, object], result_raw: bytes,
                            prior_path: Path, *, seeds: tuple[int, ...],
                            game_factory: Callable[[object], object]) -> dict[str, object]:
    """Load the dedicated provider-free roots-only source schema."""
    if result_raw != canonical_json_bytes(result_obj):
        raise BenchmarkRefusal("prepared roots-only result.json is not canonical JSON")
    if (result_obj.get("mode") != "roots-only"
            or result_obj.get("root_schema") != "w32-llm-benchmark-root-v1"
            or result_obj.get("roots_only") is not True
            or result_obj.get("gameplay") is not False
            or result_obj.get("provider_calls") != 0
            or result_obj.get("model_calls") != 0):
        raise BenchmarkRefusal("prepared root source is not a roots-only attestation")
    config = result_obj.get("config")
    if not isinstance(config, Mapping):
        raise BenchmarkRefusal("prepared roots-only source has no config")
    if (result_obj.get("seeds") != list(seeds)
            or result_obj.get("policies") != list(PANEL_POLICIES)
            or result_obj.get("setup") != config.get("setup")):
        raise BenchmarkRefusal("prepared roots-only top-level identity mismatch")
    if config.get("schema") != ROOT_SOURCE_SCHEMA:
        raise BenchmarkRefusal("prepared roots-only source config schema mismatch")
    if "continue_from" in config or "prepared_roots_from" in config:
        raise BenchmarkRefusal("prepared roots-only source cannot be recycled")
    if config.get("seeds") != list(seeds):
        raise BenchmarkRefusal("prepared root config seeds must exactly match requested seeds")
    if config.get("policies") != list(PANEL_POLICIES):
        raise BenchmarkRefusal("prepared roots-only policy roster mismatch")
    if not _compatible_panel_setup(config.get("setup"), report_sha256=_sha_bytes(result_raw)):
        raise BenchmarkRefusal("prepared roots-only setup identity mismatch")
    roots_obj = result_obj.get("roots")
    expected_keys = {str(seed) for seed in seeds}
    if not isinstance(roots_obj, Mapping) or set(roots_obj) != expected_keys:
        raise BenchmarkRefusal("prepared root result.json does not cover requested seeds")

    roots: dict[int, Mapping[str, object]] = {}
    games: dict[int, object] = {}
    hashes: dict[str, str] = {}
    for index, seed in enumerate(seeds):
        root_path = prior_path / f"root-{seed}.json"
        root_obj, root_raw = _load_json_file(root_path, label=f"root-{seed}.json")
        if not isinstance(root_obj, Mapping):
            raise BenchmarkRefusal(f"prior root-{seed}.json is malformed")
        if root_raw != canonical_json_bytes(root_obj):
            raise BenchmarkRefusal(f"prior root-{seed}.json is not canonical JSON")
        _prepared_root_identity(root_obj, seed=seed,
                                rank_index=index % len(RANKS),
                                expected_banker=seed % 4)
        root_hash = _sha(root_obj)
        if roots_obj.get(str(seed)) != root_hash:
            raise BenchmarkRefusal(f"prior root hash mismatch for seed {seed}")
        try:
            restored = _restore_game(root_obj, seed, game_factory)
        except Exception as exc:
            raise BenchmarkRefusal(
                f"prior root-{seed}.json cannot restore game state") from exc
        if (getattr(restored, "level_idx", None) != root_obj["level_idx"]
                or getattr(getattr(restored, "round", None), "phase", None) != "play"
                or _state_snapshot(restored.round) != root_obj["round"]):
            raise BenchmarkRefusal(
                f"prior root-{seed}.json restored game state mismatch")
        roots[seed] = dict(root_obj, _source_bytes_sha256=_sha_bytes(root_raw))
        games[seed] = restored
        hashes[str(seed)] = root_hash
    return {"path": str(prior_path), "result_sha256": _sha_bytes(result_raw),
            "source_config": config, "roots": roots, "games": games,
            "root_hashes": hashes}


def _load_prepared_roots(prior: str | os.PathLike, *, seeds: tuple[int, ...],
                         game_factory: Callable[[object], object],
                         expected_result_sha256: str | None = None) -> dict[str, object]:
    """Load only sealed roots, validating restoration before output creation."""
    prior_path = Path(prior).expanduser()
    if (not prior_path.is_dir() or prior_path.is_symlink()):
        raise BenchmarkRefusal(
            "--prepared-roots-from must name a prior output directory")
    prior_path = prior_path.resolve()
    result_path = prior_path / "result.json"
    result_obj, result_raw = _load_json_file(result_path, label="result.json")
    if (expected_result_sha256 is not None
            and _sha_bytes(result_raw) != expected_result_sha256):
        raise BenchmarkRefusal("prepared root source report SHA256 mismatch")
    if isinstance(result_obj, Mapping) \
            and result_obj.get("schema") == ROOT_SOURCE_SCHEMA:
        return _load_root_source_roots(result_obj, result_raw, prior_path,
                                       seeds=seeds, game_factory=game_factory)
    if (not isinstance(result_obj, Mapping) or result_obj.get("schema") != SCHEMA
            or result_obj.get("mode") != "run"):
        raise BenchmarkRefusal(
            "prepared root result.json is not a terminal benchmark report")
    config = result_obj.get("config")
    if (isinstance(config, Mapping)
            and ("prepared_roots_from" in config or "continue_from" in config)):
        raise BenchmarkRefusal("prepared roots require an original root-producing report")
    if (not isinstance(config, Mapping)
            or config.get("seeds") != list(seeds)):
        raise BenchmarkRefusal(
            "prepared root config seeds must exactly match requested seeds")
    roots_obj = result_obj.get("roots")
    expected_keys = {str(seed) for seed in seeds}
    if (not isinstance(roots_obj, Mapping)
            or set(roots_obj) != expected_keys):
        raise BenchmarkRefusal(
            "prepared root result.json does not cover requested seeds")

    roots: dict[int, Mapping[str, object]] = {}
    games: dict[int, object] = {}
    hashes: dict[str, str] = {}
    for index, seed in enumerate(seeds):
        root_path = prior_path / f"root-{seed}.json"
        root_obj, root_raw = _load_json_file(root_path, label=f"root-{seed}.json")
        if not isinstance(root_obj, Mapping):
            raise BenchmarkRefusal(f"prior root-{seed}.json is malformed")
        _prepared_root_identity(root_obj, seed=seed,
                                rank_index=index % len(RANKS))
        root_hash = _sha(root_obj)
        if roots_obj.get(str(seed)) != root_hash:
            raise BenchmarkRefusal(f"prior root hash mismatch for seed {seed}")
        try:
            restored = _restore_game(root_obj, seed, game_factory)
        except Exception as exc:
            raise BenchmarkRefusal(
                f"prior root-{seed}.json cannot restore game state") from exc
        if (getattr(restored, "level_idx", None) != root_obj["level_idx"]
                or getattr(getattr(restored, "round", None), "phase", None) != "play"
                or _state_snapshot(restored.round) != root_obj["round"]):
            raise BenchmarkRefusal(
                f"prior root-{seed}.json restored game state mismatch")
        roots[seed] = dict(root_obj, _source_bytes_sha256=_sha_bytes(root_raw))
        games[seed] = restored
        hashes[str(seed)] = root_hash
    return {"path": str(prior_path), "result_sha256": _sha_bytes(result_raw),
            "source_config": config,
            "roots": roots, "games": games, "root_hashes": hashes}



def _restore_game(root: Mapping[str, object], seed: int, game_factory: Callable[[object], object]):
    """Restore a Game from an imported private root; never deal or bury it."""
    level_idx = root.get("level_idx")
    banker = root.get("banker")
    if (not isinstance(level_idx, list) or len(level_idx) != 2
            or not isinstance(banker, int) or isinstance(banker, bool)
            or not 0 <= banker < 4):
        raise BenchmarkRefusal(f"prior root-{seed}.json has invalid game identity")
    game = game_factory(random.Random(seed))
    game.level_idx = list(level_idx)
    game.banker = banker
    game.round = _round_from_snapshot(root["round"])
    if getattr(game.round, "banker", None) != banker:
        raise BenchmarkRefusal(f"prior root-{seed}.json banker mismatch")
    return game


def run_benchmark(*, checkpoint: str | None, policy: str, output: str | os.PathLike,
                  seeds: Sequence[int], models: Sequence[str] = ("sol", "luna"),
                  information: Sequence[str] = INFORMATION_MODES,
                  wall_seconds: float = 1800.0, token_limit: int | None = None,
                  continue_from: str | os.PathLike | None = None,
                  prepared_roots_from: str | os.PathLike | None = None,
                  prepared_roots_sha256: str | None = None,
                  prepared_recipe: PreparedRecipe | None = None,
                  capacity_retries: bool = False,
                  accept_recovered_reconnects: bool = False,
                  invalid_action_feedback: bool = False,
                  classify_final_action_failures: bool = False,
                  failure_protocol: str = FAIL_STOP,
                  illegal_failure_limit: int = 8,
                  run: bool = False, codex_binary: str = "codex",
                  timeout_seconds: int = 90, runner=play_mirror,
                  transport_factory=BenchmarkTransport, game_factory=Game,
                  prepare_fn=env.prepare_round, baseline_factory=None,
                  register_fn=register_cwv_bury_policies,
                  recipe_reader=bury_env_recipe,
                  bot_factory=make_bot) -> dict[str, object]:
    """Validate, optionally execute, and return the sealed benchmark report."""
    if failure_protocol not in (FAIL_STOP, PRESERVE_ILLEGAL):
        raise BenchmarkRefusal("unknown benchmark failure protocol")
    if type(illegal_failure_limit) is not int or illegal_failure_limit <= 0:
        raise BenchmarkRefusal("illegal_failure_limit must be a positive integer")
    for name, value in (("capacity_retries", capacity_retries),
                        ("accept_recovered_reconnects", accept_recovered_reconnects),
                        ("invalid_action_feedback", invalid_action_feedback),
                        ("classify_final_action_failures", classify_final_action_failures)):
        if type(value) is not bool:
            raise BenchmarkRefusal(f"{name} must be boolean")
    if run and (type(token_limit) is not int or token_limit <= 0):
        raise BenchmarkRefusal("--run requires a positive --soft-token-limit")
    if continue_from is not None and prepared_roots_from is not None:
        raise BenchmarkRefusal("continuation and prepared roots are mutually exclusive")
    if prepared_roots_sha256 is not None and prepared_roots_from is None:
        raise BenchmarkRefusal("root-source SHA256 requires prepared roots")
    if prepared_recipe is not None:
        if type(prepared_recipe) is not PreparedRecipe:
            raise BenchmarkRefusal("prepared_recipe must be an explicit PreparedRecipe")
        if prepared_roots_from is None or continue_from is not None:
            raise BenchmarkRefusal("panel recipes require root-only import, not continuation")
        if baseline_factory is not None:
            raise BenchmarkRefusal("prepared recipe cannot be combined with a baseline override")
        if (type(prepared_roots_sha256) is not str or len(prepared_roots_sha256) != 64
                or any(c not in "0123456789abcdef" for c in prepared_roots_sha256)):
            raise BenchmarkRefusal("panel requires a pinned root-source report SHA256")
        identity = prepared_recipe.identity
        if checkpoint != identity.get("checkpoint"):
            raise BenchmarkRefusal("checkpoint disagrees with the prepared recipe")
        checkpoint_id = ({"path": identity["checkpoint"], "sha256": identity["sha256"]}
                         if "checkpoint" in identity else None)
    else:
        checkpoint_id = _checkpoint_identity(checkpoint)
    models = tuple(models)
    if failure_protocol == PRESERVE_ILLEGAL and (
            prepared_recipe is None or models != ("sol",) or continue_from is not None
            or not classify_final_action_failures):
        raise BenchmarkRefusal("preserve protocol requires prepared Sol with final-action attribution")
    if (capacity_retries or accept_recovered_reconnects or invalid_action_feedback
            or classify_final_action_failures) and (
            prepared_recipe is None or models != ("sol",)):
        raise BenchmarkRefusal("recovery controls require the explicit Sol prepared-recipe path")
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
    if prepared_recipe is not None:
        baseline_name, baseline_recipe = prepared_recipe.policy, prepared_recipe.identity
    else:
        baseline_name, baseline_recipe = _registered_baseline(
            checkpoint_id["path"], register=register_fn, recipe_reader=recipe_reader)
    if policy != baseline_name:
        raise BenchmarkRefusal(
            f"requested policy {policy!r} is not the registered baseline {baseline_name!r}")
    source = _source_identity()
    continuation = None
    prepared_roots = None
    if continue_from is not None:
        if not run:
            raise BenchmarkRefusal("--continue-from requires --run")
        continuation = _load_continuation(
            continue_from, seeds=seeds, checkpoint=checkpoint_id, policy=policy,
            baseline_recipe=baseline_recipe, models=models, information=information)
    if prepared_roots_from is not None:
        prepared_roots = _load_prepared_roots(
            prepared_roots_from, seeds=seeds, game_factory=game_factory,
            expected_result_sha256=prepared_roots_sha256)
    config = {"schema": SCHEMA, "checkpoint": checkpoint_id, "policy": policy,
              "seeds": list(seeds), "models": list(models),
              "information": list(information), "wall_seconds": wall_seconds,
              "soft_token_limit": token_limit, "run": bool(run),
              "baseline_recipe": baseline_recipe, "source": source,
              "claim": "benchmark execution only; runtime production parity is not claimed"}
    if continuation is not None:
        config["continue_from"] = {
            "path": continuation["path"],
            "result_sha256": continuation["result_sha256"],
        }
    if prepared_roots is not None:
        config["prepared_roots_from"] = {
            "path": prepared_roots["path"], "result_sha256": prepared_roots["result_sha256"],
            "root_hashes": prepared_roots["root_hashes"],
            "source_config": prepared_roots["source_config"],
        }
    for name, enabled in (("invalid_action_feedback", invalid_action_feedback),
                          ("classify_final_action_failures", classify_final_action_failures)):
        if enabled:
            config[name] = True
    if failure_protocol == PRESERVE_ILLEGAL:
        config["failure_protocol"] = failure_protocol
        config["illegal_failure_limit"] = illegal_failure_limit
    if capacity_retries:
        config["provider_capacity_retry_delays"] = list(CAPACITY_RETRY_DELAYS)
    if accept_recovered_reconnects:
        config["accept_recovered_reconnects"] = True
    if not run:
        result = {"schema": SCHEMA, "mode": "dry-run", "config": config,
                "planned_arms": [f"{model}-{mode}" for model in models for mode in information],
                "planned_mirrors": len(seeds) * 2 * len(models) * len(information)}
        if prepared_roots is not None:
            result["prepared_roots"] = {
                "source": prepared_roots["path"],
                "result_sha256": prepared_roots["result_sha256"],
                "root_hashes": prepared_roots["root_hashes"],
            }
        return result

    try:
        output_path.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise BenchmarkRefusal("output must be a fresh path") from exc
    _publish(output_path / "config.json", config)
    budget = _Budget(float(wall_seconds), token_limit)
    if prepared_recipe is not None:
        baseline_fn = lambda seat, seed: prepared_recipe.factory(seed=seed + seat)
    else:
        baseline_fn = baseline_factory or (lambda seat, seed: bot_factory(policy, seed=seed + seat))
    roots: dict[int, object] = {}
    root_hashes: dict[int, str] = {}
    setup_failures: dict[int, str] = {}
    if continuation is not None:
        # Imported roots are already dealt/buried.  In particular, do not
        # invoke baseline setup or prepare_round on this path.
        for seed in seeds:
            root = continuation["roots"][seed]
            try:
                roots[seed] = _restore_game(root, seed, game_factory)
                root_hashes[seed] = _sha({key: value for key, value in root.items()
                                          if key != "_source_bytes_sha256"})
                _publish(output_path / f"root-{seed}.json",
                         {key: value for key, value in root.items()
                          if key != "_source_bytes_sha256"})
                _publish(output_path / f"setup-{seed}.json", {
                    "schema": "w32-llm-benchmark-imported-setup-v1", "seed": seed,
                    "policy": policy, "root_sha256": root_hashes[seed],
                    "source": continuation["path"],
                })
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                setup_failures[seed] = error
                _publish(output_path / f"setup-{seed}.error.json",
                         {"schema": "w32-llm-benchmark-setup-error-v1", "seed": seed,
                          "error": error})
    elif prepared_roots is not None:
        for seed in seeds:
            root = prepared_roots["roots"][seed]
            roots[seed] = prepared_roots["games"][seed]
            root_hashes[seed] = prepared_roots["root_hashes"][str(seed)]
            _publish(output_path / f"root-{seed}.json",
                     {key: value for key, value in root.items() if key != "_source_bytes_sha256"})
            _publish(output_path / f"setup-{seed}.json", {
                "schema": "w32-llm-benchmark-imported-setup-v1", "seed": seed,
                "policy": policy, "root_sha256": root_hashes[seed],
                "source": prepared_roots["path"],
                "source_result_sha256": prepared_roots["result_sha256"],
                "source_root_sha256": root_hashes[seed],
            })
    else:
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
    panel_stopped = False
    model_failure_count = 0
    scheduled_stop_reason = None
    for model in models:
        for mode in information:
            arm = f"{model}-{mode}"
            arm_rows: list[dict[str, object]] = []
            for seed in seeds:
                for flip in (0, 1):
                    key = f"{arm}-seed{seed}-flip{flip}"
                    prior_row = (continuation["rows"].get(key)
                                 if continuation is not None else None)
                    if prior_row is not None and prior_row.get("complete") is True:
                        source = continuation["source_rows"][key]
                        row = dict(source["row"])
                        row["lineage"] = {
                            "source": continuation["path"],
                            "source_result_sha256": continuation["result_sha256"],
                            "source_row": source["path"],
                            "source_row_sha256": source["sha256"],
                            "kind": "imported-complete",
                        }
                    elif panel_stopped:
                        row = {"schema": "w32-llm-benchmark-mirror-v1", "key": key,
                               "arm": arm, "model": model, "information": mode,
                               "seed": seed, "flip": flip, "complete": False,
                               "status": "not_run",
                               "error": ("panel stopped after first incomplete mirror"
                                         if scheduled_stop_reason is None
                                         else "panel stopped: " + scheduled_stop_reason["category"]),
                               "calls": []}
                    elif seed in setup_failures:
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
                                recovery_options = {}
                                if capacity_retries:
                                    recovery_options["capacity_retry_delays"] = CAPACITY_RETRY_DELAYS
                                if accept_recovered_reconnects:
                                    recovery_options["accept_recovered_reconnects"] = True
                                transport = transport_factory(
                                    evidence_root=_evidence / f"seat-{seat}",
                                    model=MODEL_NAMES[_model], codex_binary=codex_binary,
                                    timeout_seconds=timeout_seconds,
                                    deadline_provider=lambda: budget.deadline_ns,
                                    **recovery_options)
                                transports.append(transport)
                                return _BudgetedPlanner(transport, budget)

                            action_options = {}
                            if invalid_action_feedback:
                                action_options["invalid_action_feedback"] = True
                            if classify_final_action_failures:
                                action_options["classify_final_action_failures"] = True
                            row = dict(runner(
                                roots[seed], flip=flip, information=mode,
                                planner_factory=planner_factory,
                                baseline_factory=baseline_fn, seed=seed,
                                before_decision=lambda: budget.check("decision"),
                                **action_options))
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
                        if prior_row is not None:
                            # The previous incomplete attempt is deliberately
                            # retained even if this whole-mirror retry succeeds.
                            source = continuation["source_rows"][key]
                            row["prior_attempt"] = {
                                "complete": prior_row.get("complete") is True,
                                "error": prior_row.get("error"),
                                "calls": list(prior_row.get("calls", ())),
                                "cost_tokens": _row_cost(prior_row),
                                "source": continuation["path"],
                                "source_result_sha256": continuation["result_sha256"],
                                "source_row": source["path"],
                                "source_row_sha256": source["sha256"],
                            }
                    _publish(output_path / f"mirror-{model}-{mode}-{seed}-{flip}.json", row)
                    if (failure_protocol == FAIL_STOP and prepared_recipe is not None
                            and row.get("complete") is not True):
                        panel_stopped = True
                    if failure_protocol == PRESERVE_ILLEGAL and not panel_stopped:
                        disposition = attempt_disposition(row, protocol=PRESERVE_ILLEGAL)
                        if disposition == "retained-model-failure":
                            model_failure_count += 1
                            if model_failure_count >= illegal_failure_limit:
                                panel_stopped = True
                                scheduled_stop_reason = {
                                    "category": "model_failure_limit",
                                    "failure_count": model_failure_count,
                                    "failure_limit": illegal_failure_limit,
                                }
                        elif disposition != "complete":
                            panel_stopped = True
                            scheduled_stop_reason = {
                                "category": "unclassified_infrastructure_failure",
                                "key": key, "error": row.get("error"),
                            }
                    arm_rows.append(row)
                    all_rows.append(row)
            summaries[arm] = _summary(
                arm_rows, arm=arm,
                seed=int.from_bytes(hashlib.sha256(arm.encode("ascii")).digest()[:4], "big"))
    prior_meta = None
    if continuation is not None:
        prior_meta = {
            "source": continuation["path"],
            "result_sha256": continuation["result_sha256"],
            "attempts": continuation["prior_attempts"],
            "cost_tokens": continuation["prior_cost_tokens"],
        }
    report = {"schema": SCHEMA, "mode": "run", "config": config,
              "roots": {str(seed): root_hashes.get(seed) for seed in seeds},
              "summaries": summaries, "mirrors": all_rows,
              "budget": {"tokens": budget.tokens,
                         "new_tokens": budget.tokens,
                         "prior_tokens": continuation["prior_cost_tokens"]
                         if continuation is not None else 0,
                         "combined_tokens": budget.tokens +
                         (continuation["prior_cost_tokens"] if continuation is not None else 0),
                         "wall_seconds": time.monotonic() - budget.started},
              "prior": prior_meta,
              "setup_failures": setup_failures}
    if failure_protocol == PRESERVE_ILLEGAL:
        if (scheduled_stop_reason is not None and scheduled_stop_reason["category"]
                == "unclassified_infrastructure_failure"):
            report["scheduled_summary"] = {
                "protocol": PRESERVE_ILLEGAL, "failure_limit": illegal_failure_limit,
                "blocked": True, "blocked_reason": scheduled_stop_reason,
            }
        else:
            report["scheduled_summary"] = summarize_scheduled(
                all_rows, failure_limit=illegal_failure_limit)
    if prepared_roots is not None:
        report["prepared_roots"] = {
            "source": prepared_roots["path"],
            "result_sha256": prepared_roots["result_sha256"],
            "root_hashes": prepared_roots["root_hashes"],
        }
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
    parser.add_argument("--continue-from", metavar="DIR",
                        help="continue incomplete mirrors from a terminal prior output")
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
            continue_from=args.continue_from,
            run=args.run, codex_binary=args.codex_binary,
            timeout_seconds=args.timeout_seconds)
    except (BenchmarkRefusal, ValueError) as exc:
        build_parser().error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
