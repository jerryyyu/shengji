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
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import stat
import subprocess
import sys
import time
from types import MethodType
from typing import Any


DESIGN_SCHEMA = "report-lcb-perf-ab-design-v1"
ARM_SCHEMA = "report-lcb-perf-ab-arm-v1"
RESULT_SCHEMA = "report-lcb-perf-ab-result-v1"
POLICY = "mc-s0-report-lcb"
N_DETERMINIZATIONS = 30
REPORT_WORLDS = 300
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
        "python", "harness", "base", "head",
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
        if not isinstance(experiment["id"], str) or not experiment["id"]:
            problems.append("experiment id is empty")
        if experiment["policy"] != POLICY:
            problems.append("policy is not literal live report-LCB")
        if experiment["n_determinizations"] != N_DETERMINIZATIONS:
            problems.append("selection dose is not N=30")
        if experiment["report_fold_worlds"] != REPORT_WORLDS:
            problems.append("report dose is not R=300")
        seeds, orders = experiment["seeds"], experiment["orders"]
        if (not isinstance(seeds, list) or len(seeds) < 2
                or len(seeds) % 2 != 0
                or any(not _is_int(seed) or seed < 0 for seed in seeds)
                or len(set(seeds)) != len(seeds)):
            problems.append("seeds must be distinct non-negative even-count pairs")
        if (not isinstance(orders, list) or len(orders) != len(seeds)
                or Counter(orders) != {
                    "base_head": len(seeds) // 2,
                    "head_base": len(seeds) // 2,
                }):
            problems.append("execution order is not exactly balanced")
        if experiment["normalization_removed_fields"] != \
                list(NORMALIZED_BALLOT_FIELDS):
            problems.append("normalization allowlist drift")
        if experiment["capture_excluded_fields"] != \
                list(CAPTURE_EXCLUDED_FIELDS):
            problems.append("semantic capture exclusion drift")
        retention = experiment["retention"]
        if (not isinstance(retention, dict)
                or set(retention) != {"statistic", "minimum_percent"}
                or retention.get("statistic") !=
                "aggregate_wall_reduction_percent"
                or isinstance(retention.get("minimum_percent"), bool)
                or not isinstance(retention.get("minimum_percent"), (int, float))
                or not math.isfinite(float(retention["minimum_percent"]))):
            problems.append("retention contract drift")

    root = design.get("evidence_root")
    if not isinstance(root, str) or not Path(root).is_absolute():
        problems.append("evidence root must be absolute")

    python = design.get("python")
    if not isinstance(python, dict) or set(python) != {
            "executable", "resolved", "version", "sha256"}:
        problems.append("python identity field set drift")
    else:
        if not all(isinstance(python[key], str) and python[key]
                   for key in ("executable", "resolved", "version")):
            problems.append("python identity is incomplete")
        check(lambda: _require_sha(python["sha256"], "python SHA"))

    harness = design.get("harness")
    if not isinstance(harness, dict) or set(harness) != {"path", "sha256"}:
        problems.append("harness identity field set drift")
    else:
        if not isinstance(harness["path"], str) or not Path(harness["path"]).is_absolute():
            problems.append("harness path must be absolute")
        check(lambda: _require_sha(harness["sha256"], "harness SHA"))

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

    if os.environ.get("SHENGJI_FAST") != "1" or not fast.activate():
        raise HarnessRefused("compiled engine is required")
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

    started = time.perf_counter()
    log = play_round(Game(random.Random(seed)), bots, record=True)
    elapsed = time.perf_counter() - started
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
        "elapsed_seconds": elapsed,
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


def _validate_search(record: dict[str, Any], before: dict[str, Any],
                     after: dict[str, Any], action: list[str], label: str) -> None:
    if record.get("policy") != POLICY:
        raise HarnessRefused(f"{label} searched policy drift")
    if record.get("n_determinizations") != N_DETERMINIZATIONS:
        raise HarnessRefused(f"{label} searched decision is not N=30")
    if record.get("report_worlds_requested") != REPORT_WORLDS:
        raise HarnessRefused(f"{label} searched decision is not R=300")
    if record.get("played") != action:
        raise HarnessRefused(f"{label} searched record/action drift")
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
            or report.get("worlds") != REPORT_WORLDS):
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
        "decision_records", "final_bots",
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
    for seat, final in enumerate(finals):
        _validate_snapshot(final, f"final seat {seat}")

    seen = [0, 0, 0, 0]
    searched_by_seat = [0, 0, 0, 0]
    forced_by_seat = [0, 0, 0, 0]
    adjusted_by_seat = [0, 0, 0, 0]
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
        record = decision["record"]
        if record is None:
            if before != after:
                raise HarnessRefused(
                    f"{label} forced/no-search play changed bot state")
            forced_by_seat[seat] += 1
        elif isinstance(record, dict):
            _validate_search(record, before, after, action, label)
            searched_by_seat[seat] += 1
        else:
            raise HarnessRefused(f"{label} decision record shape drift")
    if seen != [len(seat_rows) for seat_rows in rows]:
        raise HarnessRefused("decision wrappers contain plays absent from history")
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
            if not isinstance(ballot, dict):
                continue
            for key in BALLOT_KEYS:
                if key in ballot:
                    ballot.pop(key)
                    removals[key] += 1
    if any(count == 0 for count in removals.values()):
        raise HarnessRefused(
            f"normalization seam was not fully exercised: {removals}")
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


def _actual_identity(label: str, expected: dict[str, Any]) -> dict[str, Any]:
    repo = Path(expected["repo"])
    git = subprocess.check_output(
        ["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    if git != expected["git"]:
        raise HarnessRefused(f"{label} git drift")
    if subprocess.check_output(
            ["git", "-C", repo, "status", "--porcelain"], text=True):
        raise HarnessRefused(f"{label} worktree is dirty")
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


def _require_runtime(design: dict[str, Any], script_path: Path) -> None:
    expected = design["python"]
    executable = Path(expected["executable"])
    if (str(executable.resolve()) != expected["resolved"]
            or sha256_file(executable.resolve()) != expected["sha256"]
            or subprocess.check_output(
                [executable, "-c", "import platform;print(platform.python_version())"],
                text=True).strip() != expected["version"]):
        raise HarnessRefused("python runtime identity drift")
    harness = design["harness"]
    if (script_path.resolve() != Path(harness["path"]).resolve()
            or sha256_file(script_path) != harness["sha256"]):
        raise HarnessRefused("harness source identity drift")


def _run_batch(design_path: Path) -> None:
    design_bytes = _require_immutable_design(design_path)
    design = require_design(load_json_bytes(design_bytes))
    script_path = Path(__file__).resolve()
    _require_runtime(design, script_path)
    # A checked design describes a future one-shot batch; it cannot authorize
    # itself.  The operator/reviewer must separately bind this exact design
    # digest in the environment used to launch the durable service.
    design_sha = sha256_bytes(design_bytes)
    if os.environ.get("PERF_AB_EXTERNAL_DESIGN_SHA256") != design_sha:
        raise HarnessRefused("external design authorization is absent or stale")
    review_sha = os.environ.get("PERF_AB_REVIEW_RECORD_SHA256")
    try:
        _require_sha(review_sha, "external review-record SHA")
    except HarnessRefused:
        raise HarnessRefused("external review-record binding is absent")
    if os.environ.get("PERF_EXPERIMENT_ID") != design["experiment"]["id"]:
        raise HarnessRefused("experiment identity drift")
    if os.environ.get("INVOCATION_ID") is None:
        raise HarnessRefused("durable systemd invocation is required")
    identities = {
        label: _actual_identity(label, design[label])
        for label in ("base", "head")
    }
    root = Path(design["evidence_root"])
    root.mkdir(mode=0o755, parents=False, exist_ok=False)
    frozen_design = root / "design.json"
    _exclusive_write(frozen_design, design_bytes)
    env = dict(os.environ)
    env.pop("PYTHONHASHSEED", None)
    env.update({
        "SHENGJI_FAST": "1",
        "SHENGJI_REQUIRE_VOIDS": "1",
        "PERF_AB_DESIGN_SHA256": design_sha,
    })
    rows = []
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
                design["python"]["executable"], str(script_path), "run-arm",
                str(frozen_design), label, str(seed), str(raw),
            ]
            with stdout.open("xb") as out, stderr.open("xb") as err:
                process = subprocess.run(
                    command, cwd=Path(design[label]["repo"]) / "server",
                    env=env, stdout=out, stderr=err)
            stdout.chmod(0o444)
            stderr.chmod(0o444)
            if process.returncode != 0:
                raise HarnessRefused(f"{stem} exited {process.returncode}")
            lines = stdout.read_text().splitlines()
            if len(lines) != 1:
                raise HarnessRefused(f"{stem} emitted {len(lines)} lines")
            summary = load_json_bytes(lines[0].encode())
            expected_summary = {
                "elapsed_seconds", "semantic_bytes", "semantic_sha256",
                "history_plays", "searched_decisions",
                "forced_no_search_decisions", "engine_adjusted_plays",
                "searched_decisions_by_seat",
                "forced_no_search_decisions_by_seat",
                "engine_adjusted_plays_by_seat",
            }
            if (not isinstance(summary, dict) or set(summary) != expected_summary
                    or isinstance(summary["elapsed_seconds"], bool)
                    or not isinstance(summary["elapsed_seconds"], (int, float))
                    or not math.isfinite(float(summary["elapsed_seconds"]))
                    or summary["elapsed_seconds"] <= 0):
                raise HarnessRefused(f"{stem} summary contract drift")
            raw_bytes = raw.read_bytes()
            if summary["semantic_sha256"] != sha256_bytes(raw_bytes):
                raise HarnessRefused(f"{stem} semantic digest drift")
            value = load_json_bytes(raw_bytes)
            validation = validate_arm_semantics(value, design, seed)
            if any(summary.get(key) != value_ for key, value_ in validation.items()):
                raise HarnessRefused(f"{stem} validation summary drift")
            normalized_bytes, removals = normalize_arm(value)
            normalized_path = root / f"{stem}.normalized.json"
            _exclusive_write(normalized_path, normalized_bytes)
            normalized[label] = normalized_bytes
            row[label] = {
                "elapsed_seconds": summary["elapsed_seconds"],
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

    base_wall = sum(row["base"]["elapsed_seconds"] for row in rows)
    head_wall = sum(row["head"]["elapsed_seconds"] for row in rows)
    reduction = 100.0 * (base_wall - head_wall) / base_wall
    forced = sum(row["base"]["forced_no_search_decisions"] for row in rows)
    searched = sum(row["base"]["searched_decisions"] for row in rows)
    adjusted = sum(row["base"]["engine_adjusted_plays"] for row in rows)
    minimum = float(spec["retention"]["minimum_percent"])
    result = {
        "schema": RESULT_SCHEMA,
        "claim_boundary": CLAIM_BOUNDARY,
        "design_sha256": design_sha,
        "identities": identities,
        "records": rows,
        "aggregate": {
            "base_wall_seconds": base_wall,
            "head_wall_seconds": head_wall,
            "wall_reduction_percent": reduction,
            "throughput_increase_percent": 100.0 * (base_wall / head_wall - 1),
            "normalized_semantics_exact": True,
            "searched_decisions": searched,
            "forced_no_search_decisions": forced,
            "engine_adjusted_plays": adjusted,
        },
        "retention": spec["retention"],
        "decision": "retain" if reduction >= minimum else "drop",
    }
    _exclusive_write(
        root / "result.json",
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False).encode()
        + b"\n")
    print(json.dumps({
        "status": "COMPLETE", "decision": result["decision"],
        "result_sha256": sha256_file(root / "result.json"),
        **result["aggregate"],
    }, sort_keys=True), flush=True)


def main() -> None:
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
        "usage: report_lcb_perf_ab.py check-design DESIGN | "
        "run-batch DESIGN")


if __name__ == "__main__":
    try:
        main()
    except HarnessRefused as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
