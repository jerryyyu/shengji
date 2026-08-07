"""One-shot, score-blind repair for the completed V11-v2 artifacts.

The immutable producer at ``cde0fec`` completed all eight registered shards,
but shard 05 failed publication because its validator treated level utility as
bounded to +/-3.  Shengji's configured house rule leaves level progression
uncapped, and the shared evaluator intentionally records
``sign * max(1, level_change)``.  A non-zero signed integer whose sign agrees
with ``won`` is therefore the correct domain.

This module never reruns a game and never rewrites or renames a source shard.
It accepts exactly the already-completed 142M artifact namespace, reopens all
raw records and manifests, normalizes only the known shard-05 validation
status in memory, delegates every other invariant to the frozen producer, and
publishes a new versioned aggregate.  The original failed bytes remain part of
the aggregate's evidence chain.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER / "scripts"))

import v11_revalidate_v2 as PARENT  # noqa: E402


SCHEMA = "v11-current-revalidation-v2-artifact-repair-v1"
AGGREGATE_SCHEMA = "v11-current-revalidation-aggregate-v2-repaired-v1"
PARENT_GIT_SHA = "cde0fecf4151685e7174be8a7aa64b0ee6478edd"
PARENT_RUNNER_SHA256 = (
    "9bc265ad3be7e7de40bd70b8c8446c4d2d163918d342ffd56f50173d22d23da2"
)
SOURCE_PREFIX = "v11-current-revalidation-v2"
SOURCE_SUFFIX = "cde0fecf41"
FAILED_SHARD_INDEX = 5
EXPECTED_FAILED_PROBLEMS = {
    "null: malformed outcome record",
    "reference: malformed outcome record",
}
ALLOWED_REPAIR_DIFF = {
    "server/scripts/v11_revalidate_v2_artifact_repair.py",
    "server/tests/test_v11_revalidate_v2_artifact_repair.py",
}
CLAIM_BOUNDARY = (
    "One-shot validation repair for the immutable completed cde0fec 142M "
    "V11-v2 population. It changes only the level-utility domain from the "
    "incorrect bounded +/-3 set to any non-zero signed integer consistent "
    "with won. It does not rerun games, change records, rehabilitate V11-v1, "
    "prove model activation, test protected composition, or authorize "
    "production."
)


ProtocolRefused = PARENT.ProtocolRefused
# Keep the literal producer validator before ``validate_source_population``
# temporarily installs the uncapped adapter.  Calling ``PARENT.record_problems``
# from inside the adapter recurses into itself and was the reason the first
# scratch repair could never execute.
_FROZEN_RECORD_PROBLEMS = PARENT.record_problems


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=SERVER.parent, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def protocol_problems() -> list[str]:
    """Prove this verifier still contains the literal frozen producer."""
    problems = []
    if PARENT.sha256(PARENT.__file__) != PARENT_RUNNER_SHA256:
        problems.append("frozen V11-v2 producer bytes drifted")
    if (PARENT.SCHEMA != "v11-current-revalidation-v2"
            or PARENT.SEED0 != 142_000_000
            or PARENT.SEED_HI != 142_002_047
            or PARENT.SHARD_COUNT != 8
            or PARENT.CLUSTERS_PER_SHARD != 256):
        problems.append("frozen V11-v2 producer geometry drifted")
    problems += [f"parent: {problem}" for problem in PARENT.protocol_problems()]
    try:
        head = git("rev-parse", "HEAD")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", PARENT_GIT_SHA, head],
            cwd=SERVER.parent,
        ).returncode == 0
        if not ancestor:
            problems.append("repair verifier does not descend from producer")
        changed = set(filter(None, git(
            "diff", "--name-only", f"{PARENT_GIT_SHA}..{head}").splitlines()))
        unexpected = sorted(changed - ALLOWED_REPAIR_DIFF)
        if unexpected:
            problems.append(f"repair branch changes producer bytes: {unexpected}")
    except (OSError, subprocess.CalledProcessError) as exc:
        problems.append(f"repair Git identity unavailable: {type(exc).__name__}")
    return sorted(set(problems))


def record_problems_uncapped(records: object, *, seed0: int,
                             clusters: int) -> list[str]:
    """Apply the frozen gate after mapping only legal uncapped utilities.

    The mapped copy is used solely to bypass the producer's erroneous finite
    set membership check.  All statistics continue to use the original,
    uncapped utilities.
    """
    normalized = copy.deepcopy(records)
    if isinstance(normalized, dict):
        for rows in normalized.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                won = row.get("won")
                utility = row.get("level_utility")
                legal = (
                    isinstance(won, int) and not isinstance(won, bool)
                    and won in (0, 1)
                    and isinstance(utility, int)
                    and not isinstance(utility, bool)
                    and utility != 0
                    and (utility > 0) == bool(won)
                )
                if legal:
                    row["level_utility"] = 1 if utility > 0 else -1
    return _FROZEN_RECORD_PROBLEMS(
        normalized, seed0=seed0, clusters=clusters)


def _source_paths(artifact_dir: Path) -> list[dict]:
    sources = []
    for index in range(PARENT.SHARD_COUNT):
        base = (
            f"{SOURCE_PREFIX}_shard{index:02d}_{SOURCE_SUFFIX}.jsonl"
        )
        failed = index == FAILED_SHARD_INDEX
        records_name = base + (".FAILED" if failed else "")
        manifest_name = base + ".manifest.json" + (".FAILED" if failed else "")
        sources.append({
            "shard_index": index,
            "failed": failed,
            "records": (artifact_dir / records_name).resolve(),
            "manifest": (artifact_dir / manifest_name).resolve(),
            # The frozen validator keys rows by the normal publication path.
            # These logical paths exist only in memory; source bytes retain
            # their literal .FAILED names.
            "logical_records": (artifact_dir / base).resolve(),
            "logical_manifest": (
                artifact_dir / (base + ".manifest.json")
            ).resolve(),
        })
    return sources


def _require_exact_inventory(artifact_dir: Path, sources: list[dict]) -> None:
    expected = {
        str(source[key])
        for source in sources for key in ("records", "manifest")
    }
    observed = {
        str(path.resolve()) for path in artifact_dir.glob(
            f"{SOURCE_PREFIX}_shard0?_{SOURCE_SUFFIX}.jsonl*")
    }
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise ProtocolRefused(
            f"V11-v2 repair inventory drifted; missing={missing}, extra={extra}"
        )


def load_source_population(artifact_dir: os.PathLike | str):
    """Reopen the exact source bytes without publishing repaired shards."""
    artifact_dir = Path(artifact_dir).resolve()
    if not artifact_dir.is_dir():
        raise ProtocolRefused(f"artifact directory is absent: {artifact_dir}")
    sources = _source_paths(artifact_dir)
    _require_exact_inventory(artifact_dir, sources)

    manifests = []
    records: dict[str, list] = {}
    for source in sources:
        manifest_path = source["manifest"]
        records_path = source["records"]
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(
                f"source manifest unreadable: {manifest_path}: {exc}"
            ) from exc
        if (not isinstance(manifest, dict)
                or manifest.get("schema") != PARENT.SCHEMA
                or manifest.get("evidence_grade") is not True):
            raise ProtocolRefused(
                f"unexpected/non-evidence source manifest: {manifest_path}"
            )
        if PARENT.sha256(records_path) != manifest.get("records_sha256"):
            raise ProtocolRefused(f"record digest drift for {records_path}")
        try:
            for line in records_path.read_text().splitlines():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record is not a mapping")
                row["_source"] = str(source["logical_records"])
                records.setdefault(row.get("label"), []).append(row)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ProtocolRefused(
                f"source records unreadable: {records_path}: {exc}"
            ) from exc
        manifests.append((source["logical_manifest"], manifest))
    return manifests, records, sources


def normalize_known_failure(manifests) -> list[tuple[Path, dict]]:
    """Normalize only the known false failure, and only in memory."""
    normalized = copy.deepcopy(manifests)
    for _, manifest in normalized:
        index = manifest.get("shard_index")
        if index == FAILED_SHARD_INDEX:
            if (manifest.get("complete") is not False
                    or set(manifest.get("problems", [])) !=
                    EXPECTED_FAILED_PROBLEMS):
                raise ProtocolRefused(
                    "shard 05 does not carry exactly the known utility-domain "
                    "false failure"
                )
            manifest["complete"] = True
            manifest["problems"] = []
        elif (manifest.get("complete") is not True
              or manifest.get("problems") != []):
            raise ProtocolRefused(
                f"unexpected source failure outside shard 05: shard {index}"
            )
    return normalized


def validate_source_population(manifests, records, runtime: dict) -> list[str]:
    normalized = normalize_known_failure(manifests)
    original_gate = PARENT.record_problems
    try:
        PARENT.record_problems = record_problems_uncapped
        return PARENT.validate_population(
            normalized, records, runtime, PARENT_GIT_SHA)
    finally:
        PARENT.record_problems = original_gate


def reopen_and_validate(artifact_dir: os.PathLike | str):
    if git("status", "--porcelain"):
        raise ProtocolRefused("V11-v2 repair refuses a dirty verifier tree")
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused(
            "V11-v2 repair protocol drift:\n  - " + "\n  - ".join(problems)
        )
    _, runtime = PARENT.require_runtime()
    manifests, records, sources = load_source_population(artifact_dir)
    problems = validate_source_population(manifests, records, runtime)
    if problems:
        raise ProtocolRefused(
            "V11-v2 repaired validation refused:\n  - "
            + "\n  - ".join(problems)
        )
    return runtime, manifests, records, sources


def preflight(args) -> None:
    reopen_and_validate(args.artifact_dir)
    print("V11_V2_ARTIFACT_REPAIR_PREFLIGHT_PASS")


def aggregate_payload(artifact_dir: os.PathLike | str,
                      out_path: os.PathLike | str) -> dict:
    runtime, manifests, records, sources = reopen_and_validate(
        artifact_dir)
    stats = PARENT.all_contrasts(records)
    dose = PARENT.accepted_dose_summary(records)
    criteria = PARENT.gate_criteria(stats, dose)
    out = Path(out_path).resolve()
    aggregate_dir = out.parent

    def relative(path: os.PathLike | str) -> str:
        return os.path.relpath(Path(path).resolve(), aggregate_dir)

    manifests_by_index = {
        manifest["shard_index"]: manifest for _, manifest in manifests
    }
    return {
        "schema": AGGREGATE_SCHEMA,
        "repair_schema": SCHEMA,
        "claim": PARENT.CLAIM,
        "claim_boundary": CLAIM_BOUNDARY,
        "complete": True,
        "producer_git_sha": PARENT_GIT_SHA,
        "repair_git_sha": git("rev-parse", "HEAD"),
        "runtime_identity": runtime,
        "encoder_contract": PARENT.EXPECTED_ENCODER_CONTRACT,
        "invalidated_v1": PARENT.INVALIDATED_V1,
        "clusters": PARENT.TOTAL_CLUSTERS,
        "seed0": PARENT.SEED0,
        "seed_hi": PARENT.SEED_HI,
        "labels": PARENT.LABELS,
        "checkpoint_sha256": PARENT.CHECKPOINT_SHA256,
        "selection_rule": PARENT.SELECTION_RULE,
        "input_shards": [
            {
                "shard_index": source["shard_index"],
                "source_status": (
                    "KNOWN_FALSE_FAILURE_REOPENED"
                    if source["failed"] else "COMPLETE"
                ),
                "manifest_path": relative(source["manifest"]),
                "manifest_sha256": PARENT.sha256(source["manifest"]),
                "records_path": relative(source["records"]),
                "records_sha256": manifests_by_index[
                    source["shard_index"]]["records_sha256"],
            }
            for source in sources
        ],
        "repair": {
            "source_bytes_rewritten": False,
            "games_rerun": False,
            "normalized_in_memory_only": True,
            "failed_shard_index": FAILED_SHARD_INDEX,
            "original_failure_messages": sorted(EXPECTED_FAILED_PROBLEMS),
            "corrected_utility_domain": (
                "nonzero signed integer with sign consistent with won"
            ),
            "producer_runner_sha256": PARENT_RUNNER_SHA256,
        },
        "record_counts": {
            label: len(rows) for label, rows in records.items()
        },
        "counter_totals": PARENT.counter_totals(records),
        "accepted_dose": dose,
        "stats": stats,
        "criteria": criteria,
        "checkpoint_compatible_with_restored_v1": criteria["all"],
        "protected_composition_authorized": False,
        "production_promotion": False,
    }


def aggregate(args) -> None:
    out = Path(args.out).resolve()
    result = aggregate_payload(args.artifact_dir, out)
    PARENT.write_exclusive_atomic(out, result)
    print(json.dumps({
        "aggregate": str(out),
        "aggregate_sha256": PARENT.sha256(out),
        "checkpoint_compatible_with_restored_v1":
            result["checkpoint_compatible_with_restored_v1"],
        "protected_composition_authorized": False,
        "production_promotion": False,
    }, indent=2, sort_keys=True))


def verify(args) -> None:
    aggregate_path = Path(args.aggregate).resolve()
    try:
        observed = json.loads(aggregate_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(
            f"repaired aggregate unreadable: {aggregate_path}: {exc}") from exc
    if not isinstance(observed, dict) or observed.get("schema") != \
            AGGREGATE_SCHEMA:
        raise ProtocolRefused("repaired aggregate identity mismatch")
    expected = aggregate_payload(args.artifact_dir, aggregate_path)
    if PARENT.stable_digest(observed) != PARENT.stable_digest(expected):
        raise ProtocolRefused(
            "repaired aggregate differs from independently reopened sources")
    print(json.dumps({
        "verified": True,
        "aggregate": str(aggregate_path),
        "aggregate_sha256": PARENT.sha256(aggregate_path),
        "checkpoint_compatible_with_restored_v1":
            expected["checkpoint_compatible_with_restored_v1"],
        "protected_composition_authorized": False,
        "production_promotion": False,
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "aggregate", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--artifact-dir", required=True)
        if name == "aggregate":
            command.add_argument("--out", required=True)
        elif name == "verify":
            command.add_argument("--aggregate", required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "aggregate":
        aggregate(args)
    else:
        verify(args)


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
