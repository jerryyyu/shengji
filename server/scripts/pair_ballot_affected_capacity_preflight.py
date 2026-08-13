#!/usr/bin/env python3
"""Freeze and run one score-free Pair V3 capacity preflight.

The reviewed capacity design fixes the full 1,024-state DEV/CALIB workload,
but authorizes only implementation of this controller.  Freezing a packet
requires the exact external design marker; executing the six-state sizing
sample requires a second, packet-specific marker.  The preflight computes the
normal evaluator internally, validates it, immediately discards every action
and utility, and publishes only timing, work, sampler and selector-dose counts.

No command in this module can run the full scored exploration or access REPORT.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import platform
import secrets
import stat
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SCRIPT.parent))

import pair_ballot_affected_aggregate as AGG  # noqa: E402
import pair_ballot_affected_capacity_design as DESIGN  # noqa: E402
import pair_ballot_affected_eval as EVAL  # noqa: E402
import pair_ballot_affected_states as STATES  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402


DESIGN_GIT = "373de8429261d7271b98f4d427760412cea930e2"
DESIGN_REVIEW_PREFIX = "PAIR_BALLOT_AFFECTED_CAPACITY_DESIGN_V1_REVIEW "
PACKET_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_CAPACITY_PREFLIGHT_PACKET_V1_REVIEW "
)
PACKET_SCHEMA = "pair-ballot-affected-capacity-preflight-packet-v1"
ADMISSION_SCHEMA = "pair-ballot-affected-capacity-preflight-admission-v1"
RESULT_SCHEMA = "pair-ballot-affected-capacity-preflight-result-v1"
RUN_ID = "pair-ballot-affected-capacity-preflight-v1"
NAMESPACE = SERVER / "runs/logs" / RUN_ID
PACKET_PATH = NAMESPACE / "controller-packet.json"
DESIGN_REVIEW_PATH = NAMESPACE / "design-review-snapshot.md"
PACKET_REVIEW_PATH = NAMESPACE / "packet-review-snapshot.md"
ADMISSION_PATH = SERVER / "runs/locks" / f"{RUN_ID}.admission.consumed.json"
RESULT_PATH = NAMESPACE / "capacity.json"

# One defender row from every split/band cell.  Two measurements per band let
# the projection use the design's exact band mixture without evaluating REPORT.
PREFLIGHT_CELLS = (
    ("dev", "early"), ("calib", "early"),
    ("dev", "mid"), ("calib", "mid"),
    ("dev", "late"), ("calib", "late"),
)
PREFLIGHT_STATES = len(PREFLIGHT_CELLS)
THROUGHPUT_SAFETY_FACTOR = 2.0
MIN_CPUS = 16
MIN_MEMORY_BYTES = 30 * (1 << 30)

FORBIDDEN_RESULT_KEYS = frozenset({
    "action", "actions", "attacker_points", "banker", "cards", "estimands",
    "external_report", "history", "level_change", "level_utility",
    "mean_acting_level_utility", "outcomes", "points",
    "raw_attacker_points", "records", "utility", "winner", "winner_team",
    "won",
})


class CapacityPreflightRefused(RuntimeError):
    """The packet, review authority, runtime or score-free boundary drifted."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def require_regular_unlinked(path: Path, *, label: str) -> None:
    partial = Path(str(path) + ".partial")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise CapacityPreflightRefused(f"{label} is missing") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or os.path.lexists(partial)):
        raise CapacityPreflightRefused(
            f"{label} is linked, nonregular, or partial")


def write_exclusive(path: Path, payload: object) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CapacityPreflightRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(payload)
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if json.loads(partial.read_bytes()) != payload:
        raise CapacityPreflightRefused("exclusive partial failed exact reopen")
    os.link(partial, path)
    partial.unlink()
    if path.read_bytes() != raw:
        raise CapacityPreflightRefused("published artifact differs from bytes")


def write_bytes_exclusive(path: Path, raw: bytes) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CapacityPreflightRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    if path.read_bytes() != raw:
        raise CapacityPreflightRefused("published bytes differ from source")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True,
        text=True).stdout.strip()


def require_exact_clean_git(expected_git: str) -> None:
    if (not isinstance(expected_git, str) or len(expected_git) != 40
            or any(char not in "0123456789abcdef" for char in expected_git)
            or git("rev-parse", "HEAD") != expected_git
            or git("status", "--porcelain", "--untracked-files=all")):
        raise CapacityPreflightRefused("execution requires exact clean git")
    if subprocess.run(
            ["git", "merge-base", "--is-ancestor", DESIGN_GIT, expected_git],
            cwd=REPO, capture_output=True).returncode != 0:
        raise CapacityPreflightRefused("reviewed design is not an ancestor")


def expected_design_review_claim() -> dict:
    return {
        "attacker_rows_descriptive_only": True,
        "capacity_preflight_execution_authorized": False,
        "capacity_preflight_implementation_authorized": True,
        "champion_natural_role_dose_required": True,
        "cluster_unit": "deal_seed",
        "combined_dev_calib_primary": True,
        "defender_deal_clusters": DESIGN.DEFENDER_DEAL_CLUSTERS,
        "defender_membership_sha256":
            DESIGN.REVIEWED_DEFENDER_MEMBERSHIP_SHA256,
        "defender_rows": DESIGN.DEFENDER_ROWS,
        "design_file_sha256": (
            "be21b547659e49399dbaf7ea732c4a6a94f953c59c197765112e12d366dbf439"),
        "design_internal_sha256": (
            "cd8ada0d53c914adf9862171bcbf8308496129e3b1d66e63fee0a6efe4ac4f9d"),
        "design_source_sha256": (
            "caa2d0d9c5580c56828e72c39e3e5ad0cf5be0d3eb7a8a77603e31c73e786317"),
        "git": DESIGN_GIT,
        "identity_membership_sha256":
            DESIGN.REVIEWED_IDENTITY_MEMBERSHIP_SHA256,
        "mde_at_target_power": 0.040889289223836306,
        "parent_git": DESIGN.PARENT_REVIEW_GIT,
        "population_sha256": DESIGN.POPULATION_FILE_SHA256,
        "power_at_worthwhile_effect": 0.9186636345219327,
        "production_deployment": False,
        "production_promotion": False,
        "python_311_312_314_byte_identical": True,
        "report_access_authorized": False,
        "schema": "pair-ballot-affected-capacity-design-review-v1",
        "scored_evaluation_authorized": False,
        "selection_sha256": DESIGN.REVIEWED_SELECTION_SHA256,
        "smartbot_trajectory_dose_only": True,
        "states": 1_024,
        "strength_claim": False,
        "test_sha256": (
            "bc103baa97a6deffa68c4bbcec82c0697c54a0521c9842d72fd683f45aa904dc"),
        "training_authorized": False,
        "verdict": "PASS",
    }


def parse_marker(path: Path, prefix: str, expected: dict, *, label: str) -> dict:
    require_regular_unlinked(path, label=label)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CapacityPreflightRefused(f"cannot read {label}") from exc
    matches = [line[len(prefix):] for line in lines if line.startswith(prefix)]
    if len(matches) != 1:
        raise CapacityPreflightRefused(
            f"{label} must contain exactly one raw marker")
    try:
        observed = json.loads(matches[0])
    except ValueError as exc:
        raise CapacityPreflightRefused(f"{label} marker is malformed") from exc
    if observed != expected:
        raise CapacityPreflightRefused(f"{label} marker payload drift")
    return {"sha256": sha256_file(path), "claim": observed}


def memory_bytes() -> int:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError):
        return 0
    return pages * page_size


def runtime_snapshot() -> dict:
    fast_binary = getattr(fast, "_fast", None)
    fast_path = None if fast_binary is None else Path(fast_binary.__file__).resolve()
    return {
        "host": platform.node(),
        "machine": platform.machine().lower(),
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "cpu_count": int(os.cpu_count() or 0),
        "memory_bytes": memory_bytes(),
        "fast_required": os.environ.get("SHENGJI_FAST") == "1",
        "strict_voids_required":
            os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1",
        "fast_binary_sha256": (
            sha256_file(fast_path) if fast_path is not None else None),
    }


def runtime_problems(runtime: object) -> list[str]:
    if not isinstance(runtime, dict) or set(runtime) != {
            "host", "machine", "python", "python_executable", "cpu_count",
            "memory_bytes", "fast_required", "strict_voids_required",
            "fast_binary_sha256"}:
        return ["runtime field population"]
    problems = []
    if runtime["machine"] not in {"x86_64", "amd64"}:
        problems.append("runtime is not x86-64")
    if runtime["cpu_count"] < MIN_CPUS:
        problems.append("runtime has fewer than 16 CPUs")
    if runtime["memory_bytes"] < MIN_MEMORY_BYTES:
        problems.append("runtime has less than 30 GiB memory")
    if runtime["fast_required"] is not True:
        problems.append("runtime does not require compiled routing")
    if runtime["strict_voids_required"] is not True:
        problems.append("runtime does not require strict voids")
    if not is_sha256(runtime["fast_binary_sha256"]):
        problems.append("runtime fast binary is unauthenticated")
    if (not runtime["host"] or not runtime["python"]
            or not runtime["python_executable"]):
        problems.append("runtime identity is incomplete")
    return sorted(set(problems))


def require_qualified_runtime() -> dict:
    runtime = runtime_snapshot()
    problems = runtime_problems(runtime)
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        problems.append("runtime is not compiled strict routing")
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    return runtime


def load_population(path: Path) -> dict:
    payload = EVAL.load_population(path)
    if (sha256_file(path) != DESIGN.POPULATION_FILE_SHA256
            or payload.get("artifact_sha256")
            != DESIGN.POPULATION_ARTIFACT_SHA256):
        raise CapacityPreflightRefused("reviewed population identity drift")
    return payload


def preflight_manifest(population: dict) -> list[dict]:
    selected: list[dict] = []
    used_deals: set[int] = set()
    for split, band in PREFLIGHT_CELLS:
        candidates = sorted(
            (row for row in population["states"]
             if row.get("split") == split and row.get("band") == band
             and row.get("role") == "defender"
             and row.get("search_eligible") is True),
            key=lambda row: (
                int(row["deal_seed"]), int(row["trick"]), int(row["seat"]),
                str(row["state_id"])))
        row = next(
            (candidate for candidate in candidates
             if int(candidate["deal_seed"]) not in used_deals), None)
        if row is None:
            raise CapacityPreflightRefused(
                f"no distinct defender preflight row for {split}/{band}")
        used_deals.add(int(row["deal_seed"]))
        selected.append({
            "state_id": row["state_id"],
            "state_sha256": row["state_sha256"],
            "deal_seed": int(row["deal_seed"]),
            "split": split,
            "band": band,
            "role": "defender",
            "lane_index": int(row["deal_seed"]) % DESIGN.SHARD_COUNT,
        })
    if len(selected) != PREFLIGHT_STATES or len(used_deals) != PREFLIGHT_STATES:
        raise CapacityPreflightRefused("preflight state population drift")
    return selected


def design_ref(design_path: Path, population_path: Path) -> tuple[dict, dict]:
    design = DESIGN.verify_design(population_path, design_path)
    raw_sha = sha256_file(design_path)
    if (raw_sha != expected_design_review_claim()["design_file_sha256"]
            or design["design_sha256"]
            != expected_design_review_claim()["design_internal_sha256"]):
        raise CapacityPreflightRefused("reviewed capacity design identity drift")
    return design, {
        "path": str(design_path),
        "sha256": raw_sha,
        "internal_sha256": design["design_sha256"],
        "reviewed_git": DESIGN_GIT,
    }


def packet_payload(*, expected_git: str, population_path: Path,
                   design_path: Path, design_review_record: Path,
                   runtime: dict | None = None) -> dict:
    design, design_reference = design_ref(design_path, population_path)
    population = load_population(population_path)
    design_review = parse_marker(
        design_review_record, DESIGN_REVIEW_PREFIX,
        expected_design_review_claim(), label="Pair V3 design review")
    observed_runtime = require_qualified_runtime() if runtime is None else runtime
    problems = runtime_problems(observed_runtime)
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    manifest = preflight_manifest(population)
    payload = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "git": expected_git,
        "design": design_reference,
        "design_review": design_review,
        "population": {
            "path": str(population_path),
            "sha256": DESIGN.POPULATION_FILE_SHA256,
            "artifact_sha256": DESIGN.POPULATION_ARTIFACT_SHA256,
            "report_permitted": False,
        },
        "runtime": observed_runtime,
        "preflight": {
            "selection_rule": "first distinct defender deal in each split/band cell",
            "states": manifest,
            "state_count": PREFLIGHT_STATES,
            "selection_sha256": digest(manifest),
            "report_worlds": EVAL.REPORT_WORLDS,
            "outcomes_computed_in_memory": True,
            "outcomes_discarded": True,
            "outcomes_published": False,
        },
        "projection": {
            "target_states": design["selection"]["states"],
            "target_states_by_band": design["selection"]["states_by_band"],
            "logical_lanes": DESIGN.SHARD_COUNT,
            "max_fleet_hours": DESIGN.MAX_FLEET_HOURS,
            "max_lane_wall_hours": DESIGN.MAX_LANE_WALL_HOURS,
            "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
            "normalize_each_timing_to_max_work": True,
        },
        "authority": {
            "one_score_free_preflight_execution_authorized": False,
            "capacity_result_review_authorized": True,
            "scored_packet_design_authorized": False,
            "scored_evaluation_authorized": False,
            "report_access_authorized": False,
            "strength_claim": False,
            "training_authorized": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    payload["internal_sha256"] = digest(payload)
    return payload


def packet_review_claim(*, expected_git: str, packet_sha256: str,
                        packet_internal_sha256: str) -> dict:
    return {
        "git": expected_git,
        "independent_review": True,
        "one_score_free_preflight_authorized": True,
        "packet_internal_sha256": packet_internal_sha256,
        "packet_sha256": packet_sha256,
        "production_deployment": False,
        "production_promotion": False,
        "report_access_authorized": False,
        "run_id": RUN_ID,
        "schema": "pair-ballot-affected-capacity-preflight-packet-review-v1",
        "scored_evaluation_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "verdict": "PASS",
    }


def packet_problems(packet: object, *, expected_git: str,
                    population_path: Path, design_path: Path,
                    design_review_record: Path) -> list[str]:
    try:
        if not isinstance(packet, dict):
            return ["packet is not an object"]
        expected = packet_payload(
            expected_git=expected_git, population_path=population_path,
            design_path=design_path, design_review_record=design_review_record,
            runtime=copy.deepcopy(packet.get("runtime")))
    except Exception as exc:
        return [f"cannot reconstruct packet: {type(exc).__name__}: {exc}"]
    return [] if packet == expected else ["packet differs from reconstruction"]


def load_packet(path: Path, expected_sha256: str, *, expected_git: str,
                population_path: Path, design_path: Path,
                design_review_record: Path) -> dict:
    require_regular_unlinked(path, label="Pair V3 preflight packet")
    if not is_sha256(expected_sha256) or sha256_file(path) != expected_sha256:
        raise CapacityPreflightRefused("preflight packet SHA-256 drift")
    try:
        packet = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CapacityPreflightRefused("preflight packet unreadable") from exc
    problems = packet_problems(
        packet, expected_git=expected_git, population_path=population_path,
        design_path=design_path, design_review_record=design_review_record)
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    return packet


def score_free_result_problems(value: object) -> list[str]:
    problems: list[str] = []

    def walk(item: object, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in FORBIDDEN_RESULT_KEYS:
                    problems.append(f"forbidden outcome field {path}{key}")
                walk(child, f"{path}{key}.")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}{index}.")

    walk(value, "")
    if (not isinstance(value, dict)
            or value.get("score_free") is not True
            or value.get("outcomes_published") is not False):
        problems.append("score-free identity")
    return sorted(set(problems))


def _sampler_totals(result: dict) -> dict:
    totals = Counter({name: 0 for name in AGG.COUNTER_FIELDS})
    for policy in ("current", "retained"):
        totals.update(result[policy]["sampler_counters"])
    totals.update(result["external_report"]["sampler"]["counters"])
    return dict(sorted(totals.items()))


def measure_preflight(packet: dict, population_path: Path, *,
                      clock: Callable[[], float] = time.perf_counter) -> dict:
    population = load_population(population_path)
    rows = {row["state_id"]: row for row in population["states"]}
    elapsed_by_band: dict[str, list[float]] = defaultdict(list)
    sampler_totals = Counter({name: 0 for name in AGG.COUNTER_FIELDS})
    observed_work = Counter()
    selector_dose = Counter()
    timings = []
    for expected in packet["preflight"]["states"]:
        row = rows.get(expected["state_id"])
        if row is None or any(row.get(name) != expected[name] for name in (
                "state_id", "state_sha256", "deal_seed", "split", "band",
                "role")):
            raise CapacityPreflightRefused("preflight state identity drift")
        if row["split"] not in EVAL.ALLOWED_SPLITS or row["role"] != "defender":
            raise CapacityPreflightRefused("preflight admitted forbidden row")
        started = clock()
        result = EVAL.evaluate_state(row, report_worlds=EVAL.REPORT_WORLDS)
        elapsed = clock() - started
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise CapacityPreflightRefused("preflight timing is not positive")
        AGG._validate_result(
            result, split=row["split"], report_worlds=EVAL.REPORT_WORLDS)
        AGG._validate_source_binding(result, row)
        work = result["candidate_world_work"]
        total_work = sum(int(value) for value in work.values())
        if (work["current_policy"] != DESIGN.POLICY_WORK_PER_STATE
                or work["retained_policy"] != DESIGN.POLICY_WORK_PER_STATE
                or work["external_report"] not in {
                    EVAL.REPORT_WORLDS * count
                    for count in range(1, DESIGN.MAX_EXTERNAL_ACTIONS + 1)}
                or total_work > DESIGN.MAX_WORK_PER_STATE):
            raise CapacityPreflightRefused("preflight exact work drift")
        normalized = elapsed * DESIGN.MAX_WORK_PER_STATE / total_work
        elapsed_by_band[row["band"]].append(normalized)
        observed_work.update(work)
        sampler_totals.update(_sampler_totals(result))
        selector_dose.update({
            "policy_action_changes": int(result["policy_action_changed"]),
            "retained_raw_winner_insertions": int(
                result["retained_raw_winner_is_inserted"]),
            "current_raw_winner_evictions": int(
                result["current_raw_winner_was_evicted"]),
        })
        timings.append({
            "split": row["split"], "band": row["band"],
            "lane_index": expected["lane_index"],
            "elapsed_seconds": elapsed,
            "observed_candidate_world_rollouts": total_work,
            "normalized_max_work_seconds": normalized,
        })
        del result

    if (len(timings) != PREFLIGHT_STATES
            or set(elapsed_by_band) != set(DESIGN.BANDS)
            or any(len(values) != 2 for values in elapsed_by_band.values())):
        raise CapacityPreflightRefused("preflight cell completion drift")
    seconds_by_band = {
        band: math.fsum(values) / len(values)
        for band, values in sorted(elapsed_by_band.items())
    }
    design = DESIGN.build_design(population_path)
    target_seconds = math.fsum(
        seconds_by_band[band] * count
        for band, count in design["selection"]["states_by_band"].items())
    fleet_hours = (
        target_seconds * THROUGHPUT_SAFETY_FACTOR / 3_600)
    lane_hours = []
    for lane in design["schedule"]["lanes"]:
        seconds = math.fsum(
            seconds_by_band[band] * count
            for band, count in lane["states_by_band"].items())
        lane_hours.append(seconds * THROUGHPUT_SAFETY_FACTOR / 3_600)
    projection = {
        "fleet_hours": fleet_hours,
        "max_lane_wall_hours": max(lane_hours),
        "lane_wall_hours": lane_hours,
        "normalized_seconds_per_state_by_band": seconds_by_band,
        "target_states": design["selection"]["states"],
        "safety_factor": THROUGHPUT_SAFETY_FACTOR,
    }
    criteria = {
        "all_six_cells_complete": len(timings) == PREFLIGHT_STATES,
        "exact_evaluator_work_complete": (
            observed_work["current_policy"]
            == PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE
            and observed_work["retained_policy"]
            == PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE),
        "sampler_nonempty": sampler_totals["accepted_worlds"] > 0,
        "fleet_hours_le_cap": fleet_hours <= DESIGN.MAX_FLEET_HOURS,
        "max_lane_wall_hours_le_cap": (
            max(lane_hours) <= DESIGN.MAX_LANE_WALL_HOURS),
    }
    criteria["all"] = all(criteria.values())
    payload = {
        "schema": RESULT_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "complete": True,
        "score_free": True,
        "outcomes_computed_in_memory": True,
        "outcomes_discarded": True,
        "outcomes_published": False,
        "records_discarded": PREFLIGHT_STATES,
        "packet_internal_sha256": packet["internal_sha256"],
        "runtime": packet["runtime"],
        "timing_rows": timings,
        "work_totals": {
            "current_policy_rollouts": observed_work["current_policy"],
            "retained_policy_rollouts": observed_work["retained_policy"],
            "external_comparison_rollouts": observed_work["external_report"],
        },
        "sampler_totals": dict(sorted(sampler_totals.items())),
        "selector_dose": dict(sorted(selector_dose.items())),
        "projection": projection,
        "criteria": criteria,
        "status": ("AUTHORIZE_CAPACITY_RESULT_REVIEW"
                   if criteria["all"] else "HOLD"),
        "scored_packet_design_authorized": False,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    problems = score_free_result_problems(payload)
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    payload["internal_sha256"] = digest(payload)
    return payload


def freeze_command(args: argparse.Namespace) -> None:
    require_exact_clean_git(args.expected_git)
    if Path(args.out).resolve() != PACKET_PATH.resolve():
        raise CapacityPreflightRefused("packet output path is not canonical")
    source_review = Path(args.design_review_record).resolve()
    packet = packet_payload(
        expected_git=args.expected_git,
        population_path=Path(args.population).resolve(),
        design_path=Path(args.design).resolve(),
        design_review_record=source_review)
    collisions = [path for path in (PACKET_PATH, DESIGN_REVIEW_PATH)
                  if os.path.lexists(path) or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise CapacityPreflightRefused("preflight freeze slot already consumed")
    write_bytes_exclusive(DESIGN_REVIEW_PATH, source_review.read_bytes())
    packet["design_review"]["sha256"] = sha256_file(DESIGN_REVIEW_PATH)
    packet["internal_sha256"] = digest(
        {key: value for key, value in packet.items()
         if key != "internal_sha256"})
    write_exclusive(PACKET_PATH, packet)
    print(json.dumps({
        "packet_sha256": sha256_file(PACKET_PATH),
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_claim": packet_review_claim(
            expected_git=args.expected_git,
            packet_sha256=sha256_file(PACKET_PATH),
            packet_internal_sha256=packet["internal_sha256"]),
        "one_score_free_preflight_authorized": False,
    }, sort_keys=True))


def verify_command(args: argparse.Namespace) -> None:
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git,
        population_path=Path(args.population).resolve(),
        design_path=Path(args.design).resolve(),
        design_review_record=Path(args.design_review_record).resolve())
    print(json.dumps({
        "packet_sha256": args.expected_packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "verified": True,
    }, sort_keys=True))


def run_command(args: argparse.Namespace) -> None:
    require_exact_clean_git(args.expected_git)
    if (Path(args.admission).resolve() != ADMISSION_PATH.resolve()
            or Path(args.out).resolve() != RESULT_PATH.resolve()):
        raise CapacityPreflightRefused("preflight evidence path is not canonical")
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git,
        population_path=Path(args.population).resolve(),
        design_path=Path(args.design).resolve(),
        design_review_record=DESIGN_REVIEW_PATH)
    if require_qualified_runtime() != packet["runtime"]:
        raise CapacityPreflightRefused("execution runtime differs from packet")
    claim = packet_review_claim(
        expected_git=args.expected_git,
        packet_sha256=args.expected_packet_sha256,
        packet_internal_sha256=packet["internal_sha256"])
    review_source = Path(args.packet_review_record).resolve()
    review = parse_marker(
        review_source, PACKET_REVIEW_PREFIX, claim,
        label="Pair V3 preflight packet review")
    collisions = [path for path in (
        ADMISSION_PATH, PACKET_REVIEW_PATH, RESULT_PATH)
        if os.path.lexists(path) or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise CapacityPreflightRefused("preflight execution slot already consumed")
    write_bytes_exclusive(PACKET_REVIEW_PATH, review_source.read_bytes())
    admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "git": args.expected_git,
        "packet_sha256": args.expected_packet_sha256,
        "packet_review_sha256": review["sha256"],
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "one_score_free_preflight_authorized": True,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    admission["internal_sha256"] = digest(admission)
    write_exclusive(ADMISSION_PATH, admission)
    result = measure_preflight(packet, Path(args.population).resolve())
    result["admission_sha256"] = sha256_file(ADMISSION_PATH)
    result["packet_sha256"] = args.expected_packet_sha256
    result.pop("internal_sha256", None)
    result["internal_sha256"] = digest(result)
    if score_free_result_problems(result):
        raise CapacityPreflightRefused("final result score-free boundary drift")
    write_exclusive(RESULT_PATH, result)
    print(json.dumps({
        "status": result["status"],
        "result_sha256": sha256_file(RESULT_PATH),
        "result_internal_sha256": result["internal_sha256"],
        "scored_evaluation_authorized": False,
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--expected-git", required=True)
    freeze.add_argument("--population", required=True)
    freeze.add_argument("--design", required=True)
    freeze.add_argument("--design-review-record", required=True)
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(func=freeze_command)

    verify = commands.add_parser("verify")
    verify.add_argument("--expected-git", required=True)
    verify.add_argument("--population", required=True)
    verify.add_argument("--design", required=True)
    verify.add_argument("--design-review-record", required=True)
    verify.add_argument("--packet", required=True)
    verify.add_argument("--expected-packet-sha256", required=True)
    verify.set_defaults(func=verify_command)

    run = commands.add_parser("run-preflight")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--population", required=True)
    run.add_argument("--design", required=True)
    run.add_argument("--packet", required=True)
    run.add_argument("--expected-packet-sha256", required=True)
    run.add_argument("--packet-review-record", required=True)
    run.add_argument("--admission", required=True)
    run.add_argument("--out", required=True)
    run.set_defaults(func=run_command)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.func(args)
    except (CapacityPreflightRefused, DESIGN.CapacityDesignRefused,
            EVAL.EvalRefused, STATES.CaptureRefused,
            subprocess.CalledProcessError, OSError, ValueError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc


if __name__ == "__main__":
    main()
