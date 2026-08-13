#!/usr/bin/env python3
"""One-shot exploratory A/B harness for the live report-LCB policy.

The comparison is deliberately stricter than a transcript-only benchmark.
Every play, returned action, history entry, policy RNG state, sampler snapshot
and work counter must be byte-identical after removing only the three
code-derived ballot identity fields named by :data:`NORMALIZED_BALLOT_FIELDS`.

Normal forced plays are not searches: ``MCBot.decide_play`` records them with
``last_decision_record is None``.  They are valid evidence when the wrapper
proves the bot's RNG, sampler and work counters did not move.  Contested plays
must instead carry a complete literal N=30 / R=300 record.

This is performance-only tooling.  It grants no strength, merge, deployment,
retry or experiment authority.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import stat
import statistics
import subprocess
import sys
import tarfile
import time
from types import MethodType
from typing import Any


DESIGN_SCHEMA = "report-lcb-perf-ab-design-v2"
ARM_SCHEMA = "report-lcb-perf-ab-arm-v2"
RESULT_SCHEMA = "report-lcb-perf-ab-result-v2"
BUNDLE_SCHEMA = "report-lcb-perf-ab-bundle-v1"
EXECUTION_SCHEMA = "report-lcb-perf-ab-execution-v1"
REVIEW_SCHEMA = "report-lcb-perf-ab-review-v1"
POLICY = "mc-s0-report-lcb"
N_DETERMINIZATIONS = 30
REPORT_WORLDS = 300
BASE_GIT = "093ec33d8d9e137d276b84ffd907ca4417ba44af"
HEAD_GIT = "bfec965cc9a266ae519fc9efa1d44a12cc81dbb4"
EXPERIMENT_ID = "report-lcb-perf-accepted-stack-v1"
PAIR_SEEDS = (
    3368250205, 194578860, 2724771798,
    2228922925, 1533007193, 1686527578,
)
PAIR_ORDERS = (
    "base_head", "head_base", "base_head",
    "head_base", "base_head", "head_base",
)
PAIR_DF = 5
PAIR_ONE_SIDED_T_95 = 2.015048373333
MINIMUM_AGGREGATE_REDUCTION_PERCENT = 3.0
MINIMUM_PAIRED_LCB_PERCENT_EXCLUSIVE = 0.0
TRACKED_SOURCE_ROOTS = ("server/shengji",)
TRACKED_BUILD_SOURCES = (
    "server/setup.py", "server/pyproject.toml", "server/uv.lock")
RUNTIME_SOURCE_SUFFIXES = (".py", ".pyx", ".pxd")
LOADABLE_BINARY_SUFFIXES = (".so", ".dylib", ".dll", ".pyd")
TOP_LEVEL_IMPORTABLE_SUFFIXES = (".py", ".pyc", *LOADABLE_BINARY_SUFFIXES)
NORMALIZED_BALLOT_FIELDS = (
    "decision_records[*].record.ballot.digest",
    "decision_records[*].record.ballot.display",
    "decision_records[*].record.ballot.source_digest",
)
CAPTURE_EXCLUDED_FIELDS = (
    "decision_records[*].record.search_secs",
    "decision_records[*].record.code",
)
BALLOT_KEYS = ("digest", "display", "source_digest")
SAMPLER_KEYS = {
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds",
}
COUNTER_KEYS = {
    "rollouts", "search_calls", "short_search_decisions",
    "zero_world_decisions", "bury_search_calls", "bury_rollouts",
    "bury_short_searches",
}
SNAPSHOT_KEYS = {"rng_state", "sampler", *COUNTER_KEYS}
DECISION_KEYS = {"action", "record", "before", "after"}
WORK_KEYS = {
    "selection_budget", "selection_rollouts", "report_budget",
    "report_rollouts", "total_budget", "total_rollouts", "complete",
}
CLAIM_BOUNDARY = {
    "execution_authorized": False,
    "exploratory_only": True,
    "merge_authority": False,
    "one_batch_no_retry_or_tuning": True,
    "performance_only": True,
    "production_deployment": False,
    "review_authority": False,
    "sampling_or_rng_change": False,
    "strength_claim": False,
}
RETENTION_CONTRACT = {
    "aggregate_statistic": "aggregate_wall_reduction_percent",
    "aggregate_minimum_percent_inclusive":
        MINIMUM_AGGREGATE_REDUCTION_PERCENT,
    "paired_statistic":
        "paired_relative_reduction_one_sided_95_lcb_percent",
    "paired_t_critical": PAIR_ONE_SIDED_T_95,
    "paired_t_df": PAIR_DF,
    "paired_minimum_percent_exclusive":
        MINIMUM_PAIRED_LCB_PERCENT_EXCLUSIVE,
}
FIXED_CHILD_ENVIRONMENT = {
    "HOME": "/nonexistent",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "MKL_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "TZ": "UTC",
}


class HarnessRefused(RuntimeError):
    """Fail-closed contract refusal, distinct from a timed candidate result."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HarnessRefused(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(token: str) -> None:
    raise HarnessRefused(f"non-finite JSON value: {token}")


def load_json_bytes(payload: bytes) -> Any:
    try:
        return json.loads(
            payload, object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_nonfinite)
    except HarnessRefused:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessRefused(f"invalid JSON: {exc}") from exc


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_sha(value: Any, label: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise HarnessRefused(f"{label} is not a lowercase SHA-256")


def _require_git(value: Any, label: str) -> None:
    if (not isinstance(value, str) or len(value) != 40
            or any(char not in "0123456789abcdef" for char in value)):
        raise HarnessRefused(f"{label} is not a full lowercase Git identity")


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise HarnessRefused(f"{label} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise HarnessRefused(f"{label} is not a normalized relative path")
    return value


def design_problems(design: Any) -> list[str]:
    """Return deterministic, side-effect-free design problems."""

    problems: list[str] = []

    def check(callable_) -> None:
        try:
            callable_()
        except (HarnessRefused, KeyError, TypeError, ValueError) as exc:
            problems.append(str(exc))

    if not isinstance(design, dict):
        return ["design is not an object"]
    expected = {
        "schema", "claim_boundary", "experiment", "evidence_root",
        "python", "harness", "validator", "execution", "base", "head",
    }
    if set(design) != expected:
        problems.append("design field set drift")
        return problems
    if design.get("schema") != DESIGN_SCHEMA:
        problems.append("design schema drift")
    if design.get("claim_boundary") != CLAIM_BOUNDARY:
        problems.append("claim boundary drift")

    experiment = design.get("experiment")
    expected_experiment = {
        "id", "policy", "n_determinizations", "report_fold_worlds",
        "seeds", "orders", "capture_excluded_fields",
        "normalization_removed_fields", "retention",
    }
    if not isinstance(experiment, dict) or set(experiment) != expected_experiment:
        problems.append("experiment field set drift")
    else:
        if experiment["id"] != EXPERIMENT_ID:
            problems.append("experiment id drift")
        if experiment["policy"] != POLICY:
            problems.append("policy is not literal live report-LCB")
        if experiment["n_determinizations"] != N_DETERMINIZATIONS:
            problems.append("selection dose is not N=30")
        if experiment["report_fold_worlds"] != REPORT_WORLDS:
            problems.append("report dose is not R=300")
        if experiment["seeds"] != list(PAIR_SEEDS):
            problems.append("seeds are not the six preregistered fresh pairs")
        if experiment["orders"] != list(PAIR_ORDERS):
            problems.append(
                "execution order is not the preregistered alternation")
        if experiment["normalization_removed_fields"] != \
                list(NORMALIZED_BALLOT_FIELDS):
            problems.append("normalization allowlist drift")
        if experiment["capture_excluded_fields"] != \
                list(CAPTURE_EXCLUDED_FIELDS):
            problems.append("semantic capture exclusion drift")
        if experiment["retention"] != RETENTION_CONTRACT:
            problems.append("retention contract drift")

    root = design.get("evidence_root")
    if not isinstance(root, str) or not Path(root).is_absolute():
        problems.append("evidence root must be absolute")

    python = design.get("python")
    python_keys = {
        "executable", "resolved", "version", "sha256", "implementation",
        "cache_tag", "soabi", "platform", "machine",
    }
    if not isinstance(python, dict) or set(python) != python_keys:
        problems.append("python identity field set drift")
    else:
        if not all(isinstance(python[key], str) and python[key]
                   for key in python_keys - {"sha256"}):
            problems.append("python identity is incomplete")
        check(lambda: _require_sha(python["sha256"], "python SHA"))

    for label in ("harness", "validator"):
        source = design.get(label)
        if not isinstance(source, dict) or set(source) != {"path", "sha256"}:
            problems.append(f"{label} identity field set drift")
        else:
            if (not isinstance(source["path"], str)
                    or not Path(source["path"]).is_absolute()):
                problems.append(f"{label} path must be absolute")
            check(lambda value=source["sha256"], name=label:
                  _require_sha(value, f"{name} SHA"))

    execution = design.get("execution")
    if not isinstance(execution, dict) or set(execution) != {
            "child_environment", "host_profile", "systemd_unit", "timer"}:
        problems.append("execution identity field set drift")
    else:
        if execution["child_environment"] != FIXED_CHILD_ENVIRONMENT:
            problems.append("child environment drift")
        if execution["timer"] != "time.perf_counter_ns":
            problems.append("timer contract drift")
        for label in ("host_profile", "systemd_unit"):
            item = execution[label]
            if (not isinstance(item, dict)
                    or set(item) != {"path", "sha256"}
                    or not isinstance(item.get("path"), str)
                    or not Path(item["path"]).is_absolute()):
                problems.append(f"{label} identity field set drift")
            else:
                check(lambda value=item["sha256"], name=label:
                      _require_sha(value, f"{name} SHA"))

    identity_keys = {"repo", "git", "source_sha256s", "native"}
    for label in ("base", "head"):
        identity = design.get(label)
        if not isinstance(identity, dict) or set(identity) != identity_keys:
            problems.append(f"{label} identity field set drift")
            continue
        if not isinstance(identity["repo"], str) or not Path(identity["repo"]).is_absolute():
            problems.append(f"{label} repo must be absolute")
        check(lambda value=identity["git"], name=label:
              _require_git(value, f"{name} git"))
        wanted_git = BASE_GIT if label == "base" else HEAD_GIT
        if identity.get("git") != wanted_git:
            problems.append(f"{label} Git is not the preregistered exact head")
        sources = identity["source_sha256s"]
        if not isinstance(sources, dict) or not sources:
            problems.append(f"{label} source identity is empty")
        else:
            for relative, digest in sources.items():
                check(lambda value=relative, name=label:
                      _safe_relative(value, f"{name} source path"))
                check(lambda value=digest, name=label:
                      _require_sha(value, f"{name} source SHA"))
        native = identity["native"]
        if not isinstance(native, dict) or set(native) != {"path", "sha256"}:
            problems.append(f"{label} native identity field set drift")
        else:
            check(lambda value=native["path"], name=label:
                  _safe_relative(value, f"{name} native path"))
            check(lambda value=native["sha256"], name=label:
                  _require_sha(value, f"{name} native SHA"))
    if (isinstance(design.get("base"), dict)
            and isinstance(design.get("head"), dict)
            and isinstance(design["base"].get("source_sha256s"), dict)
            and isinstance(design["head"].get("source_sha256s"), dict)
            and set(design["base"]["source_sha256s"])
            != set(design["head"]["source_sha256s"])):
        problems.append("base/head source path sets differ")
    if (isinstance(design.get("base"), dict)
            and isinstance(design.get("head"), dict)
            and design["base"].get("git") == design["head"].get("git")):
        problems.append("base/head Git identities are equal")
    return problems


def require_design(design: Any) -> dict[str, Any]:
    problems = design_problems(design)
    if problems:
        raise HarnessRefused("; ".join(problems))
    return design


def _snapshot(bot: Any) -> dict[str, Any]:
    return {
        "rng_state": bot.rng.getstate(),
        "sampler": bot._sampler_snapshot(),
        **{key: int(getattr(bot, key, 0)) for key in COUNTER_KEYS},
    }


def _semantic_record(record: Any) -> Any:
    if record is None:
        return None
    value = copy.deepcopy(record)
    # Time and whole-code identity are captured outside the semantic equality
    # object.  The later normalization pass removes only BALLOT_KEYS.
    value.pop("search_secs", None)
    value.pop("code", None)
    return value


def _run_arm(design_path: Path, label: str, seed: int, raw_path: Path) -> None:
    design_bytes = design_path.read_bytes()
    design = require_design(load_json_bytes(design_bytes))
    expected_design_sha = os.environ.get("PERF_AB_DESIGN_SHA256")
    if expected_design_sha != sha256_bytes(design_bytes):
        raise HarnessRefused("child design identity drift")
    if label not in {"base", "head"} or seed not in design["experiment"]["seeds"]:
        raise HarnessRefused("child arm or seed is outside design")
    _require_runtime(design, Path(__file__).resolve())
    _actual_identity(label, design[label])
    repo = Path(design[label]["repo"])
    sys.path.insert(0, str(repo / "server"))

    from shengji.ai.env import play_round
    from shengji.ai.registry import make_bot
    from shengji.engine import fast
    from shengji.engine.game import Game

    _require_import_origins(repo)

    if os.environ.get("SHENGJI_FAST") != "1" or not fast.activate():
        raise HarnessRefused("compiled engine is required")
    _require_actual_native(repo, design[label]["native"], fast)
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise HarnessRefused("void-respecting sampler is required")
    if os.environ.get("PERF_EXPERIMENT_ID") != design["experiment"]["id"]:
        raise HarnessRefused("experiment identity drift")
    if os.environ.get("INVOCATION_ID") is None:
        raise HarnessRefused("durable systemd invocation is required")

    bots = [make_bot(POLICY, seed=seed * 100 + seat) for seat in range(4)]
    records: list[list[dict[str, Any]]] = [[] for _ in bots]
    for seat, bot in enumerate(bots):
        decide = bot.decide_play

        def recorded(self, rnd, actor, *, _decide=decide, _seat=seat):
            before = _snapshot(self)
            action = _decide(rnd, actor)
            after = _snapshot(self)
            records[_seat].append({
                "action": list(action),
                "record": _semantic_record(self.last_decision_record),
                "before": before,
                "after": after,
            })
            return action

        bot.decide_play = MethodType(recorded, bot)

    game_rng = random.Random(seed)
    started = time.perf_counter_ns()
    log = play_round(Game(game_rng), bots, record=True)
    elapsed_ns = time.perf_counter_ns() - started
    # Dynamic policy imports must stay inside the bound arm too.  Checking
    # again after the round closes modules first reached by rollout paths.
    _require_import_origins(repo)
    _require_actual_native(repo, design[label]["native"], fast)
    _actual_identity(label, design[label])
    semantic = {
        "schema": ARM_SCHEMA,
        "seed": seed,
        "policy": POLICY,
        "trump_rank": log.trump_rank,
        "banker": log.banker,
        "attacker_points": log.attacker_points,
        "winner_team": log.winner_team,
        "level_change": log.level_change,
        "history": log.history,
        "game_rng_state": game_rng.getstate(),
        "decision_records": records,
        "final_bots": [_snapshot(bot) for bot in bots],
    }
    payload = canonical(semantic)
    # Validate the exact JSON representation that will be compared.  RoundLog
    # uses tuples in memory, while canonical JSON intentionally records lists.
    validation = validate_arm_semantics(
        load_json_bytes(payload), design, seed)
    _exclusive_write(raw_path, payload)
    print(json.dumps({
        "elapsed_ns": elapsed_ns,
        "semantic_bytes": len(payload),
        "semantic_sha256": sha256_bytes(payload),
        **validation,
    }, sort_keys=True), flush=True)


def _validate_snapshot(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != SNAPSHOT_KEYS:
        raise HarnessRefused(f"{label} snapshot field set drift")
    if (not isinstance(value["sampler"], dict)
            or set(value["sampler"]) != SAMPLER_KEYS
            or any(not _is_int(item) or item < 0
                   for item in value["sampler"].values())):
        raise HarnessRefused(f"{label} sampler snapshot drift")
    if any(not _is_int(value[key]) or value[key] < 0 for key in COUNTER_KEYS):
        raise HarnessRefused(f"{label} work counter drift")
    if not isinstance(value["rng_state"], (list, tuple)):
        raise HarnessRefused(f"{label} RNG state drift")
    if (value["short_search_decisions"] != 0
            or value["zero_world_decisions"] != 0
            or value["bury_short_searches"] != 0):
        raise HarnessRefused(f"{label} contains short or zero-world work")
    sampler = value["sampler"]
    if (sampler["sample_attempts"] !=
            sampler["accepted_worlds"] + sampler["failed_worlds"]
            or sampler["rejected_worlds"] > sampler["failed_worlds"]
            or sampler["impossible_worlds"] != 0):
        raise HarnessRefused(f"{label} sampler totals do not reconcile")


def _validate_search(record: dict[str, Any], before: dict[str, Any],
                     after: dict[str, Any], attempted: list[str],
                     label: str) -> None:
    if record.get("policy") != POLICY:
        raise HarnessRefused(f"{label} searched policy drift")
    if record.get("n_determinizations") != N_DETERMINIZATIONS:
        raise HarnessRefused(f"{label} searched decision is not N=30")
    if record.get("report_worlds_requested") != REPORT_WORLDS:
        raise HarnessRefused(f"{label} searched decision is not R=300")
    # The decision record names the move returned by the bot.  A failed throw
    # can subsequently be reduced by Round.play, so comparing this field with
    # engine history would reject valid searched throws (or tempt a caller to
    # overwrite the attempted action).  Both objects remain in the semantic
    # payload and must match independently across arms.
    if record.get("played") != attempted:
        raise HarnessRefused(f"{label} searched record/attempt drift")
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise HarnessRefused(f"{label} searched ballot is not contested")
    work = record.get("work")
    if not isinstance(work, dict) or set(work) != WORK_KEYS:
        raise HarnessRefused(f"{label} work field set drift")
    if work["complete"] is not True:
        raise HarnessRefused(f"{label} searched work is incomplete")
    expected_selection = N_DETERMINIZATIONS * len(candidates)
    expected_report = 2 * REPORT_WORLDS
    expected_total = expected_selection + expected_report
    expected_work = {
        "selection_budget": expected_selection,
        "selection_rollouts": expected_selection,
        "report_budget": expected_report,
        "report_rollouts": expected_report,
        "total_budget": expected_total,
        "total_rollouts": expected_total,
        "complete": True,
    }
    if work != expected_work:
        raise HarnessRefused(f"{label} searched work is not exact")
    if record.get("worlds") != N_DETERMINIZATIONS:
        raise HarnessRefused(f"{label} selection world dose drift")
    if record.get("n_by_candidate") != \
            [N_DETERMINIZATIONS] * len(candidates):
        raise HarnessRefused(f"{label} candidate world dose drift")
    report = record.get("report_fold")
    if (not isinstance(report, dict) or report.get("complete") is not True
            or report.get("worlds") != REPORT_WORLDS
            or not _is_int(report.get("attempts"))
            or not _is_int(report.get("rejected"))
            or report["attempts"] != report["worlds"] + report["rejected"]):
        raise HarnessRefused(f"{label} report world dose drift")
    sampler = record.get("sampler_counters")
    if (not isinstance(sampler, dict)
            or set(sampler) != {"before", "after", "delta"}
            or sampler["before"] != before["sampler"]
            or sampler["after"] != after["sampler"]
            or any(after["sampler"][key] < before["sampler"][key]
                   for key in SAMPLER_KEYS)
            or sampler["delta"] != {
                key: after["sampler"][key] - before["sampler"][key]
                for key in SAMPLER_KEYS
            }):
        raise HarnessRefused(f"{label} sampler accounting drift")
    delta = sampler["delta"]
    if (delta["accepted_worlds"] !=
            N_DETERMINIZATIONS + REPORT_WORLDS
            or delta["sample_attempts"] !=
            delta["accepted_worlds"] + delta["failed_worlds"]
            or delta["rejected_worlds"] > delta["failed_worlds"]
            or delta["impossible_worlds"] != 0):
        raise HarnessRefused(f"{label} sampler dose is not exact")
    if record.get("rng_state") != before["rng_state"]:
        raise HarnessRefused(f"{label} pre-search RNG state drift")
    if after["search_calls"] - before["search_calls"] != 1:
        raise HarnessRefused(f"{label} search call accounting drift")
    if after["rollouts"] - before["rollouts"] != expected_total:
        raise HarnessRefused(f"{label} rollout accounting drift")
    for key in ("short_search_decisions", "zero_world_decisions"):
        if after[key] != before[key]:
            raise HarnessRefused(f"{label} {key} changed on complete search")
    for key in ("bury_search_calls", "bury_rollouts", "bury_short_searches"):
        if after[key] != before[key]:
            raise HarnessRefused(f"{label} bury work changed during play")


def validate_arm_semantics(value: Any, design: dict[str, Any],
                           seed: int) -> dict[str, Any]:
    """Validate one arm and disclose searched versus forced play counts."""

    require_design(design)
    expected_top = {
        "schema", "seed", "policy", "trump_rank", "banker",
        "attacker_points", "winner_team", "level_change", "history",
        "game_rng_state", "decision_records", "final_bots",
    }
    if not isinstance(value, dict) or set(value) != expected_top:
        raise HarnessRefused("arm semantic field set drift")
    if value["schema"] != ARM_SCHEMA or value["seed"] != seed \
            or value["policy"] != POLICY:
        raise HarnessRefused("arm schema/seed/policy drift")
    rows, finals, history = (
        value["decision_records"], value["final_bots"], value["history"])
    if (not isinstance(rows, list) or len(rows) != 4
            or not all(isinstance(seat_rows, list) for seat_rows in rows)
            or not isinstance(finals, list) or len(finals) != 4
            or not isinstance(history, list)):
        raise HarnessRefused("arm play collection shape drift")
    if not isinstance(value["game_rng_state"], (list, tuple)):
        raise HarnessRefused("game RNG state drift")
    for seat, final in enumerate(finals):
        _validate_snapshot(final, f"final seat {seat}")

    seen = [0, 0, 0, 0]
    searched_by_seat = [0, 0, 0, 0]
    forced_by_seat = [0, 0, 0, 0]
    adjusted_by_seat = [0, 0, 0, 0]
    previous_after: list[dict[str, Any] | None] = [None] * 4
    for play_index, play in enumerate(history):
        if (not isinstance(play, list) or len(play) != 2
                or not _is_int(play[0]) or not 0 <= play[0] < 4
                or not isinstance(play[1], list)
                or any(not isinstance(card, str) for card in play[1])):
            raise HarnessRefused(f"history play {play_index} shape drift")
        seat, action = play
        if seen[seat] >= len(rows[seat]):
            raise HarnessRefused(f"history has an unrecorded seat {seat} play")
        decision = rows[seat][seen[seat]]
        seen[seat] += 1
        label = f"history play {play_index} seat {seat}"
        if not isinstance(decision, dict) or set(decision) != DECISION_KEYS:
            raise HarnessRefused(f"{label} wrapper field set drift")
        attempted = decision["action"]
        if (not isinstance(attempted, list)
                or any(not isinstance(card, str) for card in attempted)):
            raise HarnessRefused(f"{label} action shape drift")
        # A failed multi-component throw can be engine-adjusted after the bot
        # returns.  Preserve both attempted action and engine history, count
        # the event, and require the complete objects to match across arms.
        if attempted != action:
            adjusted_by_seat[seat] += 1
        before, after = decision["before"], decision["after"]
        _validate_snapshot(before, f"{label} before")
        _validate_snapshot(after, f"{label} after")
        if previous_after[seat] is None:
            if (any(before[key] != 0 for key in COUNTER_KEYS)
                    or any(before["sampler"][key] != 0
                           for key in SAMPLER_KEYS)):
                raise HarnessRefused(f"{label} initial counters are not zero")
        elif previous_after[seat] != before:
            raise HarnessRefused(f"{label} snapshot chain drift")
        previous_after[seat] = after
        record = decision["record"]
        if record is None:
            if before != after:
                raise HarnessRefused(
                    f"{label} forced/no-search play changed bot state")
            forced_by_seat[seat] += 1
        elif isinstance(record, dict):
            _validate_search(record, before, after, attempted, label)
            searched_by_seat[seat] += 1
        else:
            raise HarnessRefused(f"{label} decision record shape drift")
    if seen != [len(seat_rows) for seat_rows in rows]:
        raise HarnessRefused("decision wrappers contain plays absent from history")
    for seat, final in enumerate(finals):
        if previous_after[seat] is not None and final != previous_after[seat]:
            raise HarnessRefused(f"final seat {seat} snapshot chain drift")
    if sum(searched_by_seat) == 0:
        raise HarnessRefused("round exercised no searched decision")
    return {
        "history_plays": len(history),
        "searched_decisions": sum(searched_by_seat),
        "forced_no_search_decisions": sum(forced_by_seat),
        "engine_adjusted_plays": sum(adjusted_by_seat),
        "searched_decisions_by_seat": searched_by_seat,
        "forced_no_search_decisions_by_seat": forced_by_seat,
        "engine_adjusted_plays_by_seat": adjusted_by_seat,
    }


def normalize_arm(value: Any) -> tuple[bytes, dict[str, int]]:
    """Remove only the explicitly allowed code-derived ballot fields."""

    normalized = copy.deepcopy(value)
    removals = {key: 0 for key in BALLOT_KEYS}
    for seat_rows in normalized["decision_records"]:
        for decision in seat_rows:
            record = decision["record"]
            ballot = record.get("ballot") if isinstance(record, dict) else None
            if record is None:
                continue
            if (not isinstance(ballot, dict)
                    or not set(BALLOT_KEYS).issubset(ballot)):
                raise HarnessRefused(
                    "searched ballot lacks the normalization identity seam")
            for key in BALLOT_KEYS:
                ballot.pop(key)
                removals[key] += 1
    if len(set(removals.values())) != 1 or next(iter(removals.values())) == 0:
        raise HarnessRefused(f"normalization seam population drift: {removals}")
    return canonical(normalized), removals


def _require_immutable_design(path: Path) -> bytes:
    status = path.stat()
    if (path.is_symlink() or not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1
            or status.st_mode & 0o222):
        raise HarnessRefused(
            "design must be regular, unlinked and non-writable before run")
    payload = path.read_bytes()
    require_design(load_json_bytes(payload))
    return payload


def _exclusive_write(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        written = 0
        while written < len(payload):
            written += os.write(fd, payload[written:])
        os.fsync(fd)
    finally:
        os.close(fd)


def _exclusive_copy(path: Path, source: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with source.open("rb") as incoming, os.fdopen(fd, "wb", closefd=False) as out:
            while block := incoming.read(1024 * 1024):
                out.write(block)
            out.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def _source_archive(path: Path, identity: dict[str, Any]) -> None:
    repo = Path(identity["repo"])
    with tarfile.open(path, "x") as archive:
        for relative in sorted(identity["source_sha256s"]):
            payload = (repo / relative).read_bytes()
            info = tarfile.TarInfo(relative)
            info.size = len(payload)
            info.mode = 0o444
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))
    path.chmod(0o444)


def _actual_identity(label: str, expected: dict[str, Any]) -> dict[str, Any]:
    repo = Path(expected["repo"])
    git = subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    if git != expected["git"]:
        raise HarnessRefused(f"{label} git drift")
    if subprocess.check_output(
            ["git", "-C", repo, "status", "--porcelain"], text=True):
        raise HarnessRefused(f"{label} worktree is dirty")
    tracked = _tracked_source_paths(repo, git)
    if set(expected["source_sha256s"]) != tracked:
        raise HarnessRefused(f"{label} tracked source manifest is incomplete")
    package_root = repo / "server/shengji"
    actual_runtime_sources = {
        path.relative_to(repo).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and path.suffix in RUNTIME_SOURCE_SUFFIXES
    }
    tracked_runtime_sources = {
        path for path in tracked
        if path.startswith("server/shengji/")
        and Path(path).suffix in RUNTIME_SOURCE_SUFFIXES
    }
    if actual_runtime_sources != tracked_runtime_sources:
        raise HarnessRefused(
            f"{label} untracked or missing runtime source path")
    _require_runtime_tree(repo, expected["native"]["path"])
    sources = {
        relative: sha256_file(repo / relative)
        for relative in expected["source_sha256s"]
    }
    if sources != expected["source_sha256s"]:
        raise HarnessRefused(f"{label} source identity drift")
    native_path = repo / expected["native"]["path"]
    native = {"path": expected["native"]["path"],
              "sha256": sha256_file(native_path)}
    if native != expected["native"]:
        raise HarnessRefused(f"{label} native identity drift")
    return {"git": git, "source_sha256s": sources, "native": native}


def _require_runtime_tree(repo: Path, native_relative: str) -> None:
    """Refuse ignored bytecode or an unbound loadable beside tracked source."""

    server_root = repo / "server"
    package_root = repo / "server/shengji"
    native = (repo / native_relative).resolve()
    allowed_top_level = set(TRACKED_BUILD_SOURCES)
    for path in server_root.iterdir():
        if (path.is_file() and path.suffix in TOP_LEVEL_IMPORTABLE_SUFFIXES
                and path.relative_to(repo).as_posix() not in allowed_top_level):
            raise HarnessRefused(
                f"unbound top-level import shadow exists: {path}")
        if path.is_dir() and path != package_root:
            for candidate in path.iterdir():
                if (candidate.is_file() and candidate.stem.startswith("__init__")
                        and candidate.suffix in TOP_LEVEL_IMPORTABLE_SUFFIXES):
                    raise HarnessRefused(
                        f"unbound top-level package shadow exists: {path}")
    for path in package_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".pyc":
            raise HarnessRefused(
                f"ignored bytecode exists in runtime tree: {path}")
        if path.suffix in LOADABLE_BINARY_SUFFIXES \
                and path.resolve() != native:
            raise HarnessRefused(
                f"unbound loadable exists in runtime tree: {path}")


def _require_actual_native(repo: Path, expected: dict[str, Any],
                           fast: Any) -> None:
    module = getattr(fast, "_fast", None)
    origin = getattr(module, "__file__", None)
    wanted = (repo / expected["path"]).resolve()
    if (not isinstance(origin, str) or Path(origin).resolve() != wanted
            or sha256_file(wanted) != expected["sha256"]):
        raise HarnessRefused("imported native extension identity drift")


def _tracked_source_paths(repo: Path, git: str) -> set[str]:
    """Return the complete tracked package/build source closure at ``git``."""

    output = subprocess.check_output([
        "git", "-C", repo, "ls-tree", "-r", "--name-only", git, "--",
        *TRACKED_SOURCE_ROOTS, *TRACKED_BUILD_SOURCES,
    ], text=True)
    paths = {line for line in output.splitlines() if line}
    if not paths or not set(TRACKED_BUILD_SOURCES).issubset(paths):
        raise HarnessRefused("tracked package/build source closure is incomplete")
    for relative in paths:
        _safe_relative(relative, "tracked source path")
        path = repo / relative
        status = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(status.st_mode):
            raise HarnessRefused(f"tracked source is not a regular file: {relative}")
    return paths


def _require_import_origins(repo: Path) -> None:
    """Refuse a preloaded or dynamically imported foreign ``shengji`` module."""

    package_root = (repo / "server/shengji").resolve()
    seen = 0
    for name, module in tuple(sys.modules.items()):
        if name != "shengji" and not name.startswith("shengji."):
            continue
        origin = getattr(module, "__file__", None)
        if not isinstance(origin, str):
            raise HarnessRefused(f"loaded module has no file origin: {name}")
        try:
            Path(origin).resolve().relative_to(package_root)
        except ValueError as exc:
            raise HarnessRefused(
                f"loaded module origin escaped bound repo: {name}") from exc
        seen += 1
    if seen == 0:
        raise HarnessRefused("bound shengji package was not imported")


def _require_runtime(design: dict[str, Any], script_path: Path) -> None:
    if _python_identity(Path(design["python"]["executable"])) != \
            design["python"]:
        raise HarnessRefused("python runtime identity drift")
    harness = design["harness"]
    if (script_path.resolve() != Path(harness["path"]).resolve()
            or sha256_file(script_path) != harness["sha256"]):
        raise HarnessRefused("harness source identity drift")
    for label in ("validator",):
        item = design[label]
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise HarnessRefused(f"{label} source identity drift")
    for label in ("host_profile", "systemd_unit"):
        item = design["execution"][label]
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise HarnessRefused(f"{label} identity drift")


def _python_identity(executable: Path) -> dict[str, str]:
    executable = executable.absolute()
    program = (
        "import json,platform,sys,sysconfig;"
        "print(json.dumps({"
        "'version':platform.python_version(),"
        "'implementation':platform.python_implementation(),"
        "'cache_tag':sys.implementation.cache_tag or '',"
        "'soabi':sysconfig.get_config_var('SOABI') or '',"
        "'platform':platform.platform(),"
        "'machine':platform.machine()}))"
    )
    try:
        details = load_json_bytes(subprocess.check_output(
            [executable, "-I", "-c", program]))
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HarnessRefused(f"could not identify Python runtime: {exc}") from exc
    if not isinstance(details, dict):
        raise HarnessRefused("Python runtime identity output drift")
    resolved = executable.resolve()
    return {
        "executable": str(executable),
        "resolved": str(resolved),
        "sha256": sha256_file(resolved),
        **details,
    }


def _collect_identity(label: str, repo: Path, native_relative: str,
                      expected_git: str) -> dict[str, Any]:
    repo = repo.resolve()
    git = subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    if git != expected_git:
        raise HarnessRefused(f"{label} is not exact preregistered Git")
    tracked = _tracked_source_paths(repo, git)
    expected = {
        "repo": str(repo),
        "git": git,
        "source_sha256s": {
            relative: sha256_file(repo / relative)
            for relative in sorted(tracked)
        },
        "native": {
            "path": _safe_relative(native_relative, f"{label} native path"),
            "sha256": sha256_file(repo / native_relative),
        },
    }
    _actual_identity(label, expected)
    return expected


def _prepare_design(output: Path, evidence_root: Path, python: Path,
                    base_repo: Path, base_native: str, head_repo: Path,
                    head_native: str, validator: Path, systemd_unit: Path,
                    host_profile: Path) -> dict[str, Any]:
    """Freeze host-specific identities around the fixed reviewed protocol."""

    script = Path(__file__).resolve()
    design = {
        "schema": DESIGN_SCHEMA,
        "claim_boundary": CLAIM_BOUNDARY,
        "experiment": {
            "id": EXPERIMENT_ID,
            "policy": POLICY,
            "n_determinizations": N_DETERMINIZATIONS,
            "report_fold_worlds": REPORT_WORLDS,
            "seeds": list(PAIR_SEEDS),
            "orders": list(PAIR_ORDERS),
            "capture_excluded_fields": list(CAPTURE_EXCLUDED_FIELDS),
            "normalization_removed_fields": list(NORMALIZED_BALLOT_FIELDS),
            "retention": RETENTION_CONTRACT,
        },
        "evidence_root": str(evidence_root.resolve()),
        "python": _python_identity(python),
        "harness": {"path": str(script), "sha256": sha256_file(script)},
        "validator": {
            "path": str(validator.resolve()),
            "sha256": sha256_file(validator.resolve()),
        },
        "execution": {
            "child_environment": FIXED_CHILD_ENVIRONMENT,
            "host_profile": {
                "path": str(host_profile.resolve()),
                "sha256": sha256_file(host_profile.resolve()),
            },
            "systemd_unit": {
                "path": str(systemd_unit.resolve()),
                "sha256": sha256_file(systemd_unit.resolve()),
            },
            "timer": "time.perf_counter_ns",
        },
        "base": _collect_identity(
            "base", base_repo, base_native, BASE_GIT),
        "head": _collect_identity(
            "head", head_repo, head_native, HEAD_GIT),
    }
    require_design(design)
    _exclusive_write(output.resolve(), canonical(design))
    return design


def _require_root_owned_regular(path: Path, label: str) -> bytes:
    status = path.stat()
    if (path.is_symlink() or not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1 or status.st_uid != 0
            or status.st_mode & 0o222):
        raise HarnessRefused(
            f"{label} must be root-owned, regular, unlinked and non-writable")
    return path.read_bytes()


def _require_root_owned_directory(path: Path, label: str) -> None:
    status = path.stat()
    if (path.is_symlink() or not stat.S_ISDIR(status.st_mode)
            or status.st_uid != 0 or status.st_mode & 0o022):
        raise HarnessRefused(
            f"{label} must be root-owned and not group/world writable")


def _review_record(path: Path, expected_sha: str,
                   design_sha: str) -> tuple[dict[str, Any], bytes]:
    payload = _require_root_owned_regular(path, "review record")
    if sha256_bytes(payload) != expected_sha:
        raise HarnessRefused("external review-record digest drift")
    value = load_json_bytes(payload)
    if (not isinstance(value, dict) or set(value) != {
            "schema", "design_sha256", "verdict", "reviewer", "summary"}
            or value.get("schema") != REVIEW_SCHEMA
            or value.get("design_sha256") != design_sha
            or value.get("verdict") != "PASS"
            or not isinstance(value.get("reviewer"), str)
            or not value["reviewer"]
            or not isinstance(value.get("summary"), str)):
        raise HarnessRefused("external review record is not an exact PASS")
    return value, payload


def _require_root_execution(design_path: Path, design: dict[str, Any],
                            invocation_id: str) -> None:
    if os.geteuid() != 0:
        raise HarnessRefused("one-shot batch must run as root under systemd")
    _require_root_owned_regular(design_path, "design")
    for label in ("harness", "validator"):
        _require_root_owned_regular(Path(design[label]["path"]), label)
    for label in ("host_profile", "systemd_unit"):
        _require_root_owned_regular(
            Path(design["execution"][label]["path"]), label)
    _require_root_owned_regular(Path(design["python"]["resolved"]), "python")
    for label in ("base", "head"):
        identity = design[label]
        repo = Path(identity["repo"])
        _require_root_owned_directory(repo, f"{label} repo")
        for relative in (*identity["source_sha256s"],
                         identity["native"]["path"]):
            target = repo / relative
            _require_root_owned_regular(target, f"{label} runtime")
            current = target.parent
            while current != repo:
                _require_root_owned_directory(current, f"{label} runtime dir")
                current = current.parent
    parent = Path(design["evidence_root"]).parent
    _require_root_owned_directory(parent, "evidence parent")
    invocation = Path(f"/run/systemd/units/invocation:{invocation_id}")
    if (not os.path.lexists(invocation)
            or not invocation.is_symlink()
            or Path(os.readlink(invocation)).name !=
            Path(design["execution"]["systemd_unit"]["path"]).name):
        raise HarnessRefused("systemd invocation/unit binding is not live")


def paired_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != len(PAIR_SEEDS):
        raise HarnessRefused("paired statistics require exactly six rows")
    reductions = []
    for row, seed, order in zip(rows, PAIR_SEEDS, PAIR_ORDERS, strict=True):
        if row.get("seed") != seed or row.get("order") != order:
            raise HarnessRefused("result rows drifted from seed/order design")
        base, head = row.get("base", {}), row.get("head", {})
        base_ns, head_ns = base.get("elapsed_ns"), head.get("elapsed_ns")
        if (not _is_int(base_ns) or not _is_int(head_ns)
                or base_ns <= 0 or head_ns <= 0):
            raise HarnessRefused("elapsed nanoseconds must be positive integers")
        reductions.append(100.0 * (base_ns - head_ns) / base_ns)
    mean = statistics.fmean(reductions)
    sample_sd = statistics.stdev(reductions)
    lower = mean - PAIR_ONE_SIDED_T_95 * sample_sd / math.sqrt(len(rows))
    return {
        "relative_reduction_percent_by_seed": reductions,
        "relative_reduction_mean_percent": mean,
        "relative_reduction_sample_sd_percent": sample_sd,
        "one_sided_95_lcb_percent": lower,
        "t_critical": PAIR_ONE_SIDED_T_95,
        "t_df": PAIR_DF,
    }


def build_result(design: dict[str, Any], design_sha: str, review_sha: str,
                 invocation_id: str, execution_sha: str,
                 identities: dict[str, Any],
                 rows: list[dict[str, Any]]) -> dict[str, Any]:
    require_design(design)
    paired = paired_statistics(rows)
    base_wall = sum(row["base"]["elapsed_ns"] for row in rows)
    head_wall = sum(row["head"]["elapsed_ns"] for row in rows)
    reduction = 100.0 * (base_wall - head_wall) / base_wall
    aggregate = {
        "base_wall_ns": base_wall,
        "head_wall_ns": head_wall,
        "wall_reduction_percent": reduction,
        "throughput_increase_percent": 100.0 * (base_wall / head_wall - 1),
        "normalized_semantics_exact": True,
        "searched_decisions": sum(
            row["base"]["searched_decisions"] for row in rows),
        "forced_no_search_decisions": sum(
            row["base"]["forced_no_search_decisions"] for row in rows),
        "engine_adjusted_plays": sum(
            row["base"]["engine_adjusted_plays"] for row in rows),
    }
    decision = "retain" if (
        reduction >= MINIMUM_AGGREGATE_REDUCTION_PERCENT
        and paired["one_sided_95_lcb_percent"] >
        MINIMUM_PAIRED_LCB_PERCENT_EXCLUSIVE) else "drop"
    return {
        "schema": RESULT_SCHEMA,
        "claim_boundary": CLAIM_BOUNDARY,
        "design_sha256": design_sha,
        "review_record_sha256": review_sha,
        "systemd_invocation_id": invocation_id,
        "execution_sha256": execution_sha,
        "identities": identities,
        "records": rows,
        "aggregate": aggregate,
        "paired": paired,
        "retention": RETENTION_CONTRACT,
        "decision": decision,
    }


def _artifact_entry(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    status = path.stat()
    if (path.is_symlink() or not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1 or status.st_uid != 0
            or status.st_gid != 0 or status.st_mode & 0o222):
        raise HarnessRefused(f"artifact is not immutable root-owned: {relative}")
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "bytes": status.st_size,
        "mode": stat.S_IMODE(status.st_mode),
        "uid": status.st_uid,
        "gid": status.st_gid,
        "nlink": status.st_nlink,
    }


def _run_batch(design_path: Path) -> None:
    started_unix_ns = time.time_ns()
    design_bytes = _require_immutable_design(design_path)
    design = require_design(load_json_bytes(design_bytes))
    script_path = Path(__file__).resolve()
    _require_runtime(design, script_path)
    design_sha = sha256_bytes(design_bytes)
    if os.environ.get("PERF_AB_EXTERNAL_DESIGN_SHA256") != design_sha:
        raise HarnessRefused("external design authorization is absent or stale")
    review_sha = os.environ.get("PERF_AB_REVIEW_RECORD_SHA256")
    review_path_value = os.environ.get("PERF_AB_REVIEW_RECORD_PATH")
    try:
        _require_sha(review_sha, "external review-record SHA")
    except HarnessRefused:
        raise HarnessRefused("external review-record binding is absent")
    if not review_path_value or not Path(review_path_value).is_absolute():
        raise HarnessRefused("external review-record path is absent")
    if os.environ.get("PERF_EXPERIMENT_ID") != EXPERIMENT_ID:
        raise HarnessRefused("experiment identity drift")
    invocation_id = os.environ.get("INVOCATION_ID")
    if not invocation_id:
        raise HarnessRefused("durable systemd invocation is required")
    _require_root_execution(design_path, design, invocation_id)
    _, review_bytes = _review_record(
        Path(review_path_value), review_sha, design_sha)
    identities = {
        label: _actual_identity(label, design[label])
        for label in ("base", "head")
    }

    root = Path(design["evidence_root"])
    root.mkdir(mode=0o755, parents=False, exist_ok=False)
    frozen_design = root / "design.json"
    _exclusive_write(frozen_design, design_bytes)
    _exclusive_write(root / "review.json", review_bytes)
    _exclusive_write(root / "harness.py", script_path.read_bytes())
    _exclusive_write(
        root / "validator.py", Path(design["validator"]["path"]).read_bytes())
    _exclusive_write(
        root / "systemd.unit",
        Path(design["execution"]["systemd_unit"]["path"]).read_bytes())
    _exclusive_write(
        root / "host-profile.json",
        Path(design["execution"]["host_profile"]["path"]).read_bytes())
    for label, identity in identities.items():
        _exclusive_write(root / f"{label}.identity.json", canonical(identity))
        _source_archive(root / f"{label}.source.tar", identity)
        _exclusive_copy(
            root / f"{label}.native.bin",
            Path(identity["repo"]) / identity["native"]["path"])
    _exclusive_copy(root / "python.bin", Path(design["python"]["resolved"]))

    env = dict(FIXED_CHILD_ENVIRONMENT)
    env.update({
        "INVOCATION_ID": invocation_id,
        "SHENGJI_FAST": "1",
        "SHENGJI_REQUIRE_VOIDS": "1",
        "PERF_AB_DESIGN_SHA256": design_sha,
        "PERF_EXPERIMENT_ID": EXPERIMENT_ID,
    })
    rows = []
    arm_sequence = []
    spec = design["experiment"]
    for seed, order in zip(spec["seeds"], spec["orders"], strict=True):
        row: dict[str, Any] = {"seed": seed, "order": order}
        normalized: dict[str, bytes] = {}
        for label in order.split("_"):
            stem = f"seed-{seed}.{label}"
            raw = root / f"{stem}.raw.json"
            stdout = root / f"{stem}.stdout.jsonl"
            stderr = root / f"{stem}.stderr.log"
            command = [
                design["python"]["executable"], "-I", "-P", "-c",
                "import runpy,sys;"
                "sys.argv=['report_lcb_perf_ab.py',*sys.argv[1:]];"
                f"runpy.run_path({str(script_path)!r},run_name='__main__')",
                "run-arm", str(frozen_design), label, str(seed), str(raw),
            ]
            arm_started = time.monotonic_ns()
            with stdout.open("xb") as out, stderr.open("xb") as err:
                process = subprocess.run(
                    command, cwd=Path(design[label]["repo"]) / "server",
                    env=env, stdout=out, stderr=err)
            arm_finished = time.monotonic_ns()
            arm_sequence.append({
                "sequence_index": len(arm_sequence),
                "seed": seed,
                "label": label,
                "started_monotonic_ns": arm_started,
                "finished_monotonic_ns": arm_finished,
                "returncode": process.returncode,
            })
            stdout.chmod(0o444)
            stderr.chmod(0o444)
            if process.returncode != 0:
                raise HarnessRefused(f"{stem} exited {process.returncode}")
            if stderr.stat().st_size:
                raise HarnessRefused(f"{stem} emitted stderr")
            lines = stdout.read_text().splitlines()
            if len(lines) != 1:
                raise HarnessRefused(f"{stem} emitted {len(lines)} lines")
            summary = load_json_bytes(lines[0].encode())
            expected_summary = {
                "elapsed_ns", "semantic_bytes", "semantic_sha256",
                "history_plays", "searched_decisions",
                "forced_no_search_decisions", "engine_adjusted_plays",
                "searched_decisions_by_seat",
                "forced_no_search_decisions_by_seat",
                "engine_adjusted_plays_by_seat",
            }
            if (not isinstance(summary, dict) or set(summary) != expected_summary
                    or not _is_int(summary["elapsed_ns"])
                    or summary["elapsed_ns"] <= 0):
                raise HarnessRefused(f"{stem} summary contract drift")
            raw_bytes = raw.read_bytes()
            if (summary["semantic_sha256"] != sha256_bytes(raw_bytes)
                    or summary["semantic_bytes"] != len(raw_bytes)):
                raise HarnessRefused(f"{stem} semantic digest/size drift")
            value = load_json_bytes(raw_bytes)
            validation = validate_arm_semantics(value, design, seed)
            if any(summary.get(key) != observed
                   for key, observed in validation.items()):
                raise HarnessRefused(f"{stem} validation summary drift")
            normalized_bytes, removals = normalize_arm(value)
            normalized_path = root / f"{stem}.normalized.json"
            _exclusive_write(normalized_path, normalized_bytes)
            normalized[label] = normalized_bytes
            row[label] = {
                "elapsed_ns": summary["elapsed_ns"],
                "raw_semantic_sha256": sha256_bytes(raw_bytes),
                "raw_semantic_bytes": len(raw_bytes),
                "normalized_semantic_sha256": sha256_bytes(normalized_bytes),
                "normalized_semantic_bytes": len(normalized_bytes),
                "normalization_removals": removals,
                "stdout_sha256": sha256_file(stdout),
                "stderr_sha256": sha256_file(stderr),
                **validation,
            }
        if normalized["base"] != normalized["head"]:
            raise HarnessRefused(f"seed {seed}: normalized semantics diverged")
        if (row["base"]["normalization_removals"]
                != row["head"]["normalization_removals"]):
            raise HarnessRefused(
                f"seed {seed}: normalization field populations diverged")
        row["normalized_semantics_exact"] = True
        rows.append(row)

    execution = {
        "schema": EXECUTION_SCHEMA,
        "design_sha256": design_sha,
        "review_record_sha256": review_sha,
        "review_record_source_path": str(Path(review_path_value).resolve()),
        "systemd_invocation_id": invocation_id,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "started_unix_ns": started_unix_ns,
        "finished_arms_unix_ns": time.time_ns(),
        "arms_completed": 12,
        "arm_sequence": arm_sequence,
        "child_environment": env,
        "systemd_unit_sha256":
            design["execution"]["systemd_unit"]["sha256"],
        "host_profile_sha256":
            design["execution"]["host_profile"]["sha256"],
    }
    _exclusive_write(root / "execution.json", canonical(execution))
    execution_sha = sha256_file(root / "execution.json")
    result = build_result(
        design, design_sha, review_sha, invocation_id, execution_sha,
        identities, rows)
    _exclusive_write(
        root / "result.json",
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False).encode()
        + b"\n")

    artifact_paths = sorted(
        (path for path in root.iterdir() if path.name != "manifest.json"),
        key=lambda path: path.name)
    manifest = {
        "schema": BUNDLE_SCHEMA,
        "design_sha256": design_sha,
        "review_record_sha256": review_sha,
        "systemd_invocation_id": invocation_id,
        "artifacts": [_artifact_entry(root, path) for path in artifact_paths],
    }
    _exclusive_write(root / "manifest.json", canonical(manifest))
    root.chmod(0o555)
    print(json.dumps({
        "status": "COMPLETE_UNVERIFIED",
        "decision": result["decision"],
        "result_sha256": sha256_file(root / "result.json"),
        "manifest_sha256": sha256_file(root / "manifest.json"),
        **result["aggregate"],
        **{"paired_one_sided_95_lcb_percent":
           result["paired"]["one_sided_95_lcb_percent"]},
    }, sort_keys=True), flush=True)


def main() -> None:
    if len(sys.argv) == 12 and sys.argv[1] == "prepare-design":
        design = _prepare_design(
            Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
            Path(sys.argv[5]), sys.argv[6], Path(sys.argv[7]), sys.argv[8],
            Path(sys.argv[9]), Path(sys.argv[10]), Path(sys.argv[11]))
        print(json.dumps({
            "status": "FROZEN", "schema": design["schema"],
            "design_sha256": sha256_file(Path(sys.argv[2]).resolve()),
        }, sort_keys=True))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "check-design":
        path = Path(sys.argv[2]).resolve()
        design = require_design(load_json_bytes(path.read_bytes()))
        print(json.dumps({
            "status": "VALID", "schema": design["schema"],
            "design_sha256": sha256_file(path),
        }, sort_keys=True))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "run-batch":
        _run_batch(Path(sys.argv[2]).resolve())
        return
    if len(sys.argv) == 6 and sys.argv[1] == "run-arm":
        _run_arm(
            Path(sys.argv[2]).resolve(), sys.argv[3], int(sys.argv[4]),
            Path(sys.argv[5]).resolve())
        return
    raise SystemExit(
        "usage: report_lcb_perf_ab.py check-design DESIGN | run-batch DESIGN | "
        "prepare-design OUT EVIDENCE_ROOT PYTHON BASE_REPO BASE_NATIVE "
        "HEAD_REPO HEAD_NATIVE VALIDATOR SYSTEMD_UNIT HOST_PROFILE")


if __name__ == "__main__":
    try:
        main()
    except HarnessRefused as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
