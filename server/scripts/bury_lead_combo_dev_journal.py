#!/usr/bin/env python3
"""Resumable reusable-DEV execution for bury/first-lead exploration.

The expensive unit is one selected public banker state.  Each completed state
is therefore written as its own immutable record and can be reused after an
interruption.  A run manifest binds the exact opened-DEV selection, source Git,
native engine, RNG recipe and work settings; changing any of them requires a
new output directory.  This preserves exploratory learning without granting a
confirmatory, strength, promotion or deployment claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import bury_lead_combo_exploration as EXPLORE  # noqa: E402
import bury_lead_combo_population as POPULATION  # noqa: E402


MANIFEST_SCHEMA = "bury-first-lead-dev-journal-manifest-v1"
RECORD_SCHEMA = "bury-first-lead-dev-journal-record-v1"
SUMMARY_SCHEMA = "bury-first-lead-dev-journal-summary-v1"
MANIFEST_NAME = "run-manifest.json"


class JournalRefused(RuntimeError):
    """The reusable exploration journal or its runtime identity drifted."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()


def stable_digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def _load_json(path: Path, *, label: str) -> dict:
    if not _is_regular_unlinked(path):
        raise JournalRefused(f"{label} is missing, linked, or nonregular")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise JournalRefused(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise JournalRefused(f"{label} is not an object")
    return value


def _write_exclusive(path: Path, value: Mapping[str, object]) -> None:
    """Publish through a unique temporary inode without overwriting a result."""
    if os.path.lexists(path):
        raise JournalRefused(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temp.open("xb") as handle:
            handle.write(_canonical(dict(value)) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp, path)
    except FileExistsError as exc:
        raise JournalRefused(f"concurrent writer owns {path}") from exc
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True).stdout.strip()


def strict_runtime() -> dict:
    """Authenticate the exploratory implementation and compiled local engine."""
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise JournalRefused(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise JournalRefused("compiled engine requested but not active")
    if _git("status", "--porcelain"):
        raise JournalRefused("bury exploration journal refuses a dirty tree")
    return {
        "git": _git("rev-parse", "HEAD"),
        "tree_dirty": False,
        "python": ".".join(map(str, sys.version_info[:3])),
        "fast_binary_sha256": sha256_file(Path(fast._fast.__file__)),
        "population_source_sha256": sha256_file(Path(POPULATION.__file__)),
        "scorer_source_sha256": sha256_file(Path(EXPLORE.__file__)),
        "journal_source_sha256": sha256_file(SCRIPT),
    }


def state_rng_seed(state_id: str, base_seed: int) -> int:
    if isinstance(base_seed, bool) or not isinstance(base_seed, int) \
            or base_seed < 0:
        raise ValueError("base_seed must be a nonnegative integer")
    digest = stable_digest({
        "purpose": "bury-first-lead-dev-state-rng-v1",
        "state_id": state_id,
        "base_seed": base_seed,
    })
    return int(digest[:16], 16)


def expected_manifest(
    selection: Mapping[str, object], *,
    worlds: int,
    base_seed: int,
    attempt_factor: int,
    max_candidate_rollouts: int,
    runtime: Mapping[str, object],
) -> dict:
    for value, label in (
            (worlds, "worlds"), (attempt_factor, "attempt_factor"),
            (max_candidate_rollouts, "max_candidate_rollouts")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{label} must be a positive integer")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int) \
            or base_seed < 0:
        raise ValueError("base_seed must be a nonnegative integer")
    if POPULATION.selection_problems(selection):
        raise JournalRefused("selection failed exact population validation")
    selection_rows = selection["selection"]["rows"]
    return {
        "schema": MANIFEST_SCHEMA,
        "population_id": POPULATION.POPULATION_ID,
        "selection_sha256": stable_digest(selection),
        "selection_rows_sha256": stable_digest(selection_rows),
        "states": len(selection_rows),
        "worlds_per_state": worlds,
        "base_seed": base_seed,
        "attempt_factor": attempt_factor,
        "max_candidate_rollouts_per_state": max_candidate_rollouts,
        "runtime": dict(runtime),
        "state_rng_recipe": "sha256(state_id,base_seed) first 64 bits",
        "per_state_immutable_journal": True,
        "resume_reuses_only_exact_valid_records": True,
        "opened_reusable_dev": True,
        "exploration_only": True,
        "confirmatory_inference": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def _record_payload(
    selection_row: Mapping[str, object], *,
    manifest: Mapping[str, object],
    scorer: Callable = EXPLORE.score_state,
) -> dict:
    seed = int(selection_row["deal_seed"])
    census = POPULATION.census_state(seed)
    expected_row = {
        "state_id": census["state_id"],
        "source_state_id": census["source_state_id"],
        "deal_seed": seed,
        "selection_group": selection_row["selection_group"],
        "selection_reason": selection_row["selection_reason"],
        "combo_count": census["combo_count"],
    }
    if dict(selection_row) != expected_row:
        raise JournalRefused("selected row no longer matches reconstruction")
    rnd, incumbent, _ = POPULATION.build_bury_state(
        seed, POPULATION.CHAMPION)
    seat = rnd.banker
    if seat is None:
        raise JournalRefused("selected reconstruction lost banker")
    rng_seed = state_rng_seed(
        str(selection_row["state_id"]), int(manifest["base_seed"]))
    bot = POPULATION.make_bot(POPULATION.CHAMPION, seed=rng_seed)
    result = scorer(
        rnd, seat, bot=bot, incumbent_bury=incumbent,
        worlds=int(manifest["worlds_per_state"]),
        attempt_factor=int(manifest["attempt_factor"]),
        max_candidate_rollouts=int(
            manifest["max_candidate_rollouts_per_state"]))
    payload = {
        "schema": RECORD_SCHEMA,
        "manifest_sha256": stable_digest(manifest),
        "state_id": selection_row["state_id"],
        "deal_seed": seed,
        "state_rng_seed": rng_seed,
        "selection_row": dict(selection_row),
        "source_census": census,
        "result": result,
        "opened_reusable_dev": True,
        "exploration_only": True,
        "confirmatory_inference": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def record_problems(
    value: object, *,
    selection_row: Mapping[str, object],
    manifest: Mapping[str, object],
) -> list[str]:
    if not isinstance(value, Mapping):
        return ["record is not an object"]
    problems = []
    expected_keys = {
        "schema", "manifest_sha256", "state_id", "deal_seed",
        "state_rng_seed", "selection_row", "source_census", "result",
        "opened_reusable_dev", "exploration_only", "confirmatory_inference",
        "strength_claim", "production_promotion", "production_deployment",
        "internal_sha256",
    }
    if set(value) != expected_keys or value.get("schema") != RECORD_SCHEMA:
        problems.append("record fields or schema")
    without_digest = dict(value)
    recorded_digest = without_digest.pop("internal_sha256", None)
    if recorded_digest != stable_digest(without_digest):
        problems.append("record internal digest")
    if value.get("manifest_sha256") != stable_digest(manifest):
        problems.append("record manifest")
    if value.get("selection_row") != dict(selection_row):
        problems.append("record selection row")
    if (value.get("state_id") != selection_row.get("state_id")
            or value.get("deal_seed") != selection_row.get("deal_seed")):
        problems.append("record state identity")
    if value.get("state_rng_seed") != state_rng_seed(
            str(selection_row.get("state_id")), int(manifest["base_seed"])):
        problems.append("record RNG identity")
    census = value.get("source_census")
    if not isinstance(census, Mapping) or POPULATION.state_problems(census):
        problems.append("record source census")
    elif (census.get("state_id") != selection_row.get("state_id")
          or census.get("source_state_id") !=
          selection_row.get("source_state_id")
          or census.get("deal_seed") != selection_row.get("deal_seed")
          or census.get("combo_count") != selection_row.get("combo_count")):
        problems.append("record census/selection identity")
    result = value.get("result")
    if not isinstance(result, Mapping) or result.get("schema") != \
            EXPLORE.SCHEMA:
        problems.append("record exploration result")
    else:
        if result.get("candidate_count") != selection_row.get("combo_count"):
            problems.append("record candidate count")
        work = result.get("work")
        if (not isinstance(work, Mapping)
                or work.get("worlds_requested") !=
                manifest["worlds_per_state"]
                or work.get("candidate_rollout_cap") !=
                manifest["max_candidate_rollouts_per_state"]):
            problems.append("record work contract")
        if (result.get("exploration_only") is not True
                or result.get("confirmatory_inference") is not False
                or result.get("strength_claim") is not False
                or result.get("production_deployment") is not False):
            problems.append("record result authority")
    if (value.get("opened_reusable_dev") is not True
            or value.get("exploration_only") is not True
            or value.get("confirmatory_inference") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False):
        problems.append("record authority")
    return sorted(set(problems))


def journal_selection(
    selection: Mapping[str, object],
    output_dir: Path,
    *,
    worlds: int,
    base_seed: int,
    attempt_factor: int = EXPLORE.DEFAULT_ATTEMPT_FACTOR,
    max_candidate_rollouts: int = EXPLORE.DEFAULT_MAX_CANDIDATE_ROLLOUTS,
    limit: int | None = None,
    runtime: Mapping[str, object] | None = None,
    scorer: Callable = EXPLORE.score_state,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    """Compute missing states and reuse only byte-valid completed records."""
    problems = POPULATION.selection_problems(selection)
    if problems:
        raise JournalRefused("; ".join(problems))
    rows = list(selection["selection"]["rows"])
    if limit is not None and (isinstance(limit, bool)
                              or not isinstance(limit, int) or limit < 1):
        raise ValueError("limit must be a positive integer or None")
    selected_rows = rows[:limit]
    runtime = strict_runtime() if runtime is None else dict(runtime)
    manifest = expected_manifest(
        selection, worlds=worlds, base_seed=base_seed,
        attempt_factor=attempt_factor,
        max_candidate_rollouts=max_candidate_rollouts, runtime=runtime)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / MANIFEST_NAME
    if os.path.lexists(manifest_path):
        if _load_json(manifest_path, label="run manifest") != manifest:
            raise JournalRefused("existing run manifest differs")
    else:
        _write_exclusive(manifest_path, manifest)

    new_records = 0
    reused_records = 0
    status_counts: dict[str, int] = {}
    for index, row in enumerate(selected_rows):
        path = output_dir / f"state-{int(row['deal_seed'])}.json"
        if os.path.lexists(path):
            record = _load_json(path, label=f"state record {index}")
            existing_problems = record_problems(
                record, selection_row=row, manifest=manifest)
            if existing_problems:
                raise JournalRefused("; ".join(existing_problems))
            reused_records += 1
            event = "reused"
        else:
            record = _record_payload(row, manifest=manifest, scorer=scorer)
            generated_problems = record_problems(
                record, selection_row=row, manifest=manifest)
            if generated_problems:
                raise JournalRefused("; ".join(generated_problems))
            _write_exclusive(path, record)
            new_records += 1
            event = "completed"
        status = str(record["result"]["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        if progress is not None:
            progress({
                "event": event,
                "index": index,
                "states_requested": len(selected_rows),
                "state_id": row["state_id"],
                "status": status,
            })
    return {
        "schema": SUMMARY_SCHEMA,
        "manifest_sha256": stable_digest(manifest),
        "states_in_frozen_selection": len(rows),
        "states_requested_this_pass": len(selected_rows),
        "states_complete": len(selected_rows),
        "new_records": new_records,
        "reused_records": reused_records,
        "status_counts": status_counts,
        "per_state_immutable_journal": True,
        "opened_reusable_dev": True,
        "exploration_only": True,
        "confirmatory_inference": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def materialize_selection(output: Path) -> dict:
    """Rebuild the score-free 512-state census and publish its 32+32 slice."""
    rows = [
        POPULATION.census_state(seed)
        for seed in range(
            POPULATION.DEAL_SEED0,
            POPULATION.DEAL_SEED0 + POPULATION.POPULATION_STATES)
    ]
    selection = POPULATION.select_dev_states(rows)
    _write_exclusive(output, selection)
    return selection


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    census = subparsers.add_parser("census")
    census.add_argument("--out", required=True)
    score = subparsers.add_parser("score")
    score.add_argument("--selection", required=True)
    score.add_argument("--out-dir", required=True)
    score.add_argument("--worlds", type=int, required=True)
    score.add_argument("--base-seed", type=int, default=20260812)
    score.add_argument("--attempt-factor", type=int,
                       default=EXPLORE.DEFAULT_ATTEMPT_FACTOR)
    score.add_argument("--max-candidate-rollouts", type=int,
                       default=EXPLORE.DEFAULT_MAX_CANDIDATE_ROLLOUTS)
    score.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.command == "census":
        result = materialize_selection(Path(args.out))
    else:
        selection = _load_json(Path(args.selection), label="selection")
        result = journal_selection(
            selection, Path(args.out_dir), worlds=args.worlds,
            base_seed=args.base_seed, attempt_factor=args.attempt_factor,
            max_candidate_rollouts=args.max_candidate_rollouts,
            limit=args.limit,
            progress=lambda event: print(
                json.dumps(event, sort_keys=True), flush=True))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (JournalRefused, POPULATION.PopulationRefused,
            EXPLORE.ComboExplorationRefused) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
