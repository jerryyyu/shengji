"""Fail-closed source and population registry for the BELIEF-V1 V2 freeze.

The V2 schedule is derived from a large hash namespace, so an accidental
collision is unlikely.  Probability is not provenance, however.  This module
builds the exact review artifact required by the V2 design:

* every tracked Python source and active (non-archive) Markdown document is
  content-bound from one exact clean Git commit;
* every line containing ``seed`` is emitted as a candidate and must receive
  exactly one reviewed classification; and
* the complete V2 population is compared with every registered historical
  population.  Any shared integer refuses the freeze.

It does not open game data, generate a deal, launch a worker, train a model,
or grant capture/test/gameplay/strength authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .belief_contract import canonical_json_bytes


SCAN_SCHEMA = "belief-v1-v2-seed-source-scan-v1"
REGISTRY_SCHEMA = "belief-v1-v2-seed-registry-v1"
CLASSIFICATION_SCHEMA = "belief-v1-v2-seed-classification-v1"
POPULATION_SCHEMA = "belief-v1-v2-seed-population-v1"
CLASSIFICATIONS = (
    "finite-population",
    "derived-rng-stream",
    "non-population-context",
)
MAX_SEED = 2**63 - 1


class BeliefV2SeedRegistryError(ValueError):
    """The source scan, classification, or population closure drifted."""


def _is_git_sha(value: Any) -> bool:
    return (type(value) is str and len(value) == 40
            and all(char in "0123456789abcdef" for char in value))


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git(repo: Path, *arguments: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ("git", *arguments), cwd=repo, check=True,
            capture_output=True, text=not binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefV2SeedRegistryError("seed scan Git probe failed") \
            from exc
    return result.stdout if binary else result.stdout.strip()


def _selected_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise BeliefV2SeedRegistryError("seed scan tracked path drift")
    return ((relative.startswith("server/") and relative.endswith(".py"))
            or (relative.endswith(".md")
                and not relative.startswith("docs_archive/")))


def _candidate_id(path: str, line_number: int, line_sha256: str) -> str:
    return _sha256(canonical_json_bytes({
        "path": path,
        "line_number": line_number,
        "line_sha256": line_sha256,
    }))


def _explicit_classification_required(path: str, line: str) -> bool:
    """Flag population-like constant definitions for individual review.

    All other Python hits are deterministically classed as derived RNG/context
    uses and Markdown hits as prose context.  A new upper-case seed constant
    cannot silently enter either default class.
    """
    if not path.endswith(".py"):
        return False
    match = re.match(
        r"^\s*([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=", line)
    return match is not None and "SEED" in match.group(1)


def _source_manifest_sha256(rows: list[dict[str, Any]]) -> str:
    return _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-seed-scan-source-manifest-v1",
        "files": rows,
    }))


def _candidate_report_sha256(rows: list[dict[str, Any]]) -> str:
    return _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-seed-candidate-report-v1",
        "candidates": rows,
    }))


def scan_seed_sources(repo: Path, *, expected_git: str) -> dict[str, Any]:
    """Build the complete candidate report from one exact clean checkout."""
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not _is_git_sha(expected_git):
        raise BeliefV2SeedRegistryError("seed scan input drift")
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if head != expected_git or status:
        raise BeliefV2SeedRegistryError(
            "seed scan checkout is not exact and clean")
    tracked_raw = _git(repo, "ls-files", "-z", binary=True)
    if type(tracked_raw) is not bytes:
        raise BeliefV2SeedRegistryError("seed scan tracked population drift")
    tracked = tuple(
        value.decode("utf-8") for value in tracked_raw.split(b"\0") if value)
    selected = tuple(sorted(path for path in tracked if _selected_path(path)))
    if not selected:
        raise BeliefV2SeedRegistryError("seed scan source population is empty")

    files: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for relative in selected:
        path = repo / relative
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise BeliefV2SeedRegistryError("seed scan source shape drift")
        raw = path.read_bytes()
        files.append({
            "path": relative,
            "byte_count": len(raw),
            "sha256": _sha256(raw),
        })
        for line_number, line in enumerate(raw.splitlines(), start=1):
            if b"seed" not in line.lower():
                continue
            try:
                text = line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BeliefV2SeedRegistryError(
                    "seed candidate line is not UTF-8") from exc
            line_sha = _sha256(line)
            candidates.append({
                "candidate_id": _candidate_id(
                    relative, line_number, line_sha),
                "path": relative,
                "line_number": line_number,
                "line_sha256": line_sha,
                "line": text,
                "explicit_classification_required": (
                    _explicit_classification_required(relative, text)),
            })
    if not candidates or len({row["candidate_id"] for row in candidates}) \
            != len(candidates):
        raise BeliefV2SeedRegistryError(
            "seed candidate population is empty or duplicated")
    result = {
        "schema": SCAN_SCHEMA,
        "git_commit": expected_git,
        "source_file_count": len(files),
        "source_manifest_sha256": _source_manifest_sha256(files),
        "source_files": files,
        "candidate_count": len(candidates),
        "candidate_report_sha256": _candidate_report_sha256(candidates),
        "candidates": candidates,
        "opens_game_data": False,
        "execution_authorized": False,
    }
    validate_seed_scan(result)
    return result


def validate_seed_scan(scan: dict[str, Any]) -> None:
    if type(scan) is not dict or set(scan) != {
            "schema", "git_commit", "source_file_count",
            "source_manifest_sha256", "source_files", "candidate_count",
            "candidate_report_sha256", "candidates", "opens_game_data",
            "execution_authorized"} \
            or scan["schema"] != SCAN_SCHEMA \
            or not _is_git_sha(scan["git_commit"]) \
            or type(scan["source_files"]) is not list \
            or type(scan["candidates"]) is not list \
            or type(scan["source_file_count"]) is not int \
            or scan["source_file_count"] != len(scan["source_files"]) \
            or type(scan["candidate_count"]) is not int \
            or scan["candidate_count"] != len(scan["candidates"]) \
            or scan["opens_game_data"] is not False \
            or scan["execution_authorized"] is not False:
        raise BeliefV2SeedRegistryError("seed scan identity drift")
    paths = []
    for row in scan["source_files"]:
        if type(row) is not dict or set(row) != {
                "path", "byte_count", "sha256"} \
                or type(row["path"]) is not str or not row["path"] \
                or type(row["byte_count"]) is not int \
                or row["byte_count"] < 0 or not _is_sha256(row["sha256"]):
            raise BeliefV2SeedRegistryError("seed scan source row drift")
        paths.append(row["path"])
    if paths != sorted(paths) or len(set(paths)) != len(paths) \
            or scan["source_manifest_sha256"] \
            != _source_manifest_sha256(scan["source_files"]):
        raise BeliefV2SeedRegistryError("seed scan source closure drift")
    candidate_ids = []
    for row in scan["candidates"]:
        if type(row) is not dict or set(row) != {
                "candidate_id", "path", "line_number", "line_sha256",
                "line", "explicit_classification_required"} \
                or row["path"] not in set(paths) \
                or type(row["line_number"]) is not int \
                or row["line_number"] <= 0 \
                or type(row["line"]) is not str \
                or "seed" not in row["line"].lower() \
                or type(row["explicit_classification_required"]) is not bool \
                or row["explicit_classification_required"] \
                != _explicit_classification_required(
                    row["path"], row["line"]) \
                or not _is_sha256(row["line_sha256"]) \
                or _sha256(row["line"].encode("utf-8")) \
                != row["line_sha256"] \
                or row["candidate_id"] != _candidate_id(
                    row["path"], row["line_number"], row["line_sha256"]):
            raise BeliefV2SeedRegistryError("seed candidate row drift")
        candidate_ids.append(row["candidate_id"])
    if len(candidate_ids) != len(set(candidate_ids)) \
            or scan["candidate_report_sha256"] \
            != _candidate_report_sha256(scan["candidates"]):
        raise BeliefV2SeedRegistryError("seed candidate report drift")


@dataclass(frozen=True)
class SeedClassificationV1:
    candidate_id: str
    classification: str
    population_id: str | None = None
    note: str = ""
    explicit: bool = True
    schema: str = CLASSIFICATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_id": self.candidate_id,
            "classification": self.classification,
            "population_id": self.population_id,
            "note": self.note,
            "explicit": self.explicit,
        }


def complete_seed_classifications(
        scan: dict[str, Any], *,
        explicit: Iterable[SeedClassificationV1]) \
        -> tuple[SeedClassificationV1, ...]:
    """Fill safe defaults while requiring review of population-like symbols."""
    validate_seed_scan(scan)
    supplied = tuple(explicit)
    by_id = {}
    for row in supplied:
        if type(row) is not SeedClassificationV1 \
                or row.explicit is not True \
                or row.candidate_id in by_id:
            raise BeliefV2SeedRegistryError(
                "explicit seed classification input drift")
        by_id[row.candidate_id] = row
    known = {row["candidate_id"] for row in scan["candidates"]}
    required = {row["candidate_id"] for row in scan["candidates"]
                if row["explicit_classification_required"]}
    if not set(by_id).issubset(known) or not required.issubset(by_id):
        raise BeliefV2SeedRegistryError(
            "explicit seed classification population is incomplete")
    result = []
    for candidate in scan["candidates"]:
        candidate_id = candidate["candidate_id"]
        if candidate_id in by_id:
            result.append(by_id[candidate_id])
        else:
            markdown = candidate["path"].endswith(".md")
            result.append(SeedClassificationV1(
                candidate_id=candidate_id,
                classification=("non-population-context" if markdown
                                else "derived-rng-stream"),
                note=("default:active-markdown-context" if markdown
                      else "default:python-derived-or-context"),
                explicit=False))
    return tuple(result)


@dataclass(frozen=True)
class SeedPopulationV1:
    population_id: str
    source_paths: tuple[str, ...]
    seeds: tuple[int, ...]
    schema: str = POPULATION_SCHEMA

    def summary(self) -> dict[str, Any]:
        _validate_population(self)
        digest = hashlib.sha256()
        for seed in self.seeds:
            digest.update(seed.to_bytes(8, "big"))
        return {
            "schema": self.schema,
            "population_id": self.population_id,
            "source_paths": list(self.source_paths),
            "seed_count": len(self.seeds),
            "minimum_seed": min(self.seeds),
            "maximum_seed": max(self.seeds),
            "ordered_seed_stream_sha256": digest.hexdigest(),
        }


def _validate_population(population: SeedPopulationV1) -> None:
    if type(population) is not SeedPopulationV1 \
            or population.schema != POPULATION_SCHEMA \
            or type(population.population_id) is not str \
            or not population.population_id \
            or type(population.source_paths) is not tuple \
            or not population.source_paths \
            or tuple(sorted(population.source_paths)) \
            != population.source_paths \
            or len(set(population.source_paths)) \
            != len(population.source_paths) \
            or type(population.seeds) is not tuple \
            or not population.seeds \
            or len(set(population.seeds)) != len(population.seeds) \
            or any(type(seed) is not int or not 0 <= seed <= MAX_SEED
                   for seed in population.seeds):
        raise BeliefV2SeedRegistryError("seed population identity drift")


def build_seed_registry(
        scan: dict[str, Any], *,
        classifications: Iterable[SeedClassificationV1],
        populations: Iterable[SeedPopulationV1],
        v2_population_id: str) -> dict[str, Any]:
    """Close every candidate and prove V2 disjoint from prior populations."""
    validate_seed_scan(scan)
    classification_rows = tuple(classifications)
    population_rows = tuple(populations)
    candidate_ids = {row["candidate_id"] for row in scan["candidates"]}
    by_candidate: dict[str, SeedClassificationV1] = {}
    for row in classification_rows:
        if type(row) is not SeedClassificationV1 \
                or row.schema != CLASSIFICATION_SCHEMA \
                or row.candidate_id not in candidate_ids \
                or row.candidate_id in by_candidate \
                or row.classification not in CLASSIFICATIONS \
                or type(row.note) is not str \
                or type(row.explicit) is not bool \
                or ((row.classification == "finite-population")
                    != (type(row.population_id) is str
                        and bool(row.population_id))) \
                or (row.classification == "finite-population"
                    and row.explicit is not True):
            raise BeliefV2SeedRegistryError(
                "seed classification identity drift")
        by_candidate[row.candidate_id] = row
    if set(by_candidate) != candidate_ids:
        raise BeliefV2SeedRegistryError(
            "seed candidate classification is incomplete")
    explicit_required = {
        row["candidate_id"] for row in scan["candidates"]
        if row["explicit_classification_required"]}
    if any(by_candidate[candidate_id].explicit is not True
           for candidate_id in explicit_required):
        raise BeliefV2SeedRegistryError(
            "explicit seed classification population is incomplete")

    by_population: dict[str, SeedPopulationV1] = {}
    for population in population_rows:
        _validate_population(population)
        if population.population_id in by_population:
            raise BeliefV2SeedRegistryError(
                "seed population identifier is duplicated")
        if any(path not in {row["path"] for row in scan["source_files"]}
               for path in population.source_paths):
            raise BeliefV2SeedRegistryError(
                "seed population source is outside the scan")
        by_population[population.population_id] = population
    referenced = {
        row.population_id for row in classification_rows
        if row.classification == "finite-population"}
    if referenced != set(by_population) \
            or v2_population_id not in by_population:
        raise BeliefV2SeedRegistryError(
            "seed population classification binding drift")
    candidate_paths = {
        row["candidate_id"]: row["path"] for row in scan["candidates"]}
    if any(candidate_paths[row.candidate_id]
           not in by_population[row.population_id].source_paths
           for row in classification_rows
           if row.classification == "finite-population"):
        raise BeliefV2SeedRegistryError(
            "seed population classification source drift")

    v2_seeds = set(by_population[v2_population_id].seeds)
    collision_rows = []
    for population_id, population in sorted(by_population.items()):
        if population_id == v2_population_id:
            continue
        shared = sorted(v2_seeds.intersection(population.seeds))
        if shared:
            collision_rows.append({
                "population_id": population_id,
                "shared_seed_count": len(shared),
                "first_shared_seed": shared[0],
            })
    if collision_rows:
        raise BeliefV2SeedRegistryError(
            "V2 seed population collides with a registered population")

    ordered_classifications = [
        by_candidate[candidate_id].to_dict()
        for candidate_id in sorted(by_candidate)]
    population_summaries = [
        by_population[population_id].summary()
        for population_id in sorted(by_population)]
    result = {
        "schema": REGISTRY_SCHEMA,
        "git_commit": scan["git_commit"],
        "source_manifest_sha256": scan["source_manifest_sha256"],
        "candidate_report_sha256": scan["candidate_report_sha256"],
        "candidate_count": scan["candidate_count"],
        "classification_sha256": _sha256(canonical_json_bytes({
            "schema": "belief-v1-v2-seed-classification-population-v1",
            "classifications": ordered_classifications,
        })),
        "classifications": ordered_classifications,
        "population_table_sha256": _sha256(canonical_json_bytes({
            "schema": "belief-v1-v2-seed-population-table-v1",
            "populations": population_summaries,
        })),
        "populations": population_summaries,
        "v2_population_id": v2_population_id,
        "v2_collision_count": 0,
        "opens_game_data": False,
        "capture_authorized": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    validate_seed_registry(result, scan=scan)
    return result


def validate_seed_registry(
        registry: dict[str, Any], *, scan: dict[str, Any]) -> None:
    validate_seed_scan(scan)
    expected_keys = {
        "schema", "git_commit", "source_manifest_sha256",
        "candidate_report_sha256", "candidate_count",
        "classification_sha256", "classifications",
        "population_table_sha256", "populations", "v2_population_id",
        "v2_collision_count", "opens_game_data", "capture_authorized",
        "training_authorized", "test_open_authorized",
        "gameplay_authorized", "strength_claim_authorized",
        "deployment_authorized"}
    if type(registry) is not dict or set(registry) != expected_keys \
            or registry["schema"] != REGISTRY_SCHEMA \
            or registry["git_commit"] != scan["git_commit"] \
            or registry["source_manifest_sha256"] \
            != scan["source_manifest_sha256"] \
            or registry["candidate_report_sha256"] \
            != scan["candidate_report_sha256"] \
            or registry["candidate_count"] != scan["candidate_count"] \
            or type(registry["classifications"]) is not list \
            or len(registry["classifications"]) \
            != scan["candidate_count"] \
            or type(registry["populations"]) is not list \
            or not registry["populations"] \
            or type(registry["v2_population_id"]) is not str \
            or registry["v2_collision_count"] != 0 \
            or any(registry[key] is not False for key in (
                "opens_game_data", "capture_authorized",
                "training_authorized", "test_open_authorized",
                "gameplay_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefV2SeedRegistryError("seed registry identity drift")
    if registry["classification_sha256"] != _sha256(canonical_json_bytes({
            "schema": "belief-v1-v2-seed-classification-population-v1",
            "classifications": registry["classifications"],
            })) or registry["population_table_sha256"] \
            != _sha256(canonical_json_bytes({
                "schema": "belief-v1-v2-seed-population-table-v1",
                "populations": registry["populations"],
            })):
        raise BeliefV2SeedRegistryError("seed registry digest drift")
    candidate_ids = []
    referenced_populations = set()
    candidate_paths = {
        row["candidate_id"]: row["path"] for row in scan["candidates"]}
    candidate_requires = {
        row["candidate_id"]: row["explicit_classification_required"]
        for row in scan["candidates"]}
    population_sources = {}
    for row in registry["populations"]:
        if type(row) is not dict or set(row) != {
                "schema", "population_id", "source_paths", "seed_count",
                "minimum_seed", "maximum_seed",
                "ordered_seed_stream_sha256"} \
                or row["schema"] != POPULATION_SCHEMA \
                or type(row["population_id"]) is not str \
                or not row["population_id"] \
                or row["population_id"] in population_sources \
                or type(row["source_paths"]) is not list \
                or not row["source_paths"] \
                or row["source_paths"] != sorted(row["source_paths"]) \
                or len(set(row["source_paths"])) != len(row["source_paths"]) \
                or type(row["seed_count"]) is not int \
                or row["seed_count"] <= 0 \
                or type(row["minimum_seed"]) is not int \
                or type(row["maximum_seed"]) is not int \
                or not 0 <= row["minimum_seed"] <= row["maximum_seed"] \
                <= MAX_SEED \
                or not _is_sha256(row["ordered_seed_stream_sha256"]):
            raise BeliefV2SeedRegistryError(
                "seed registry population row drift")
        population_sources[row["population_id"]] = set(row["source_paths"])
    for row in registry["classifications"]:
        if type(row) is not dict or set(row) != {
                "schema", "candidate_id", "classification",
                "population_id", "note", "explicit"} \
                or row["schema"] != CLASSIFICATION_SCHEMA \
                or row["candidate_id"] not in candidate_paths \
                or row["classification"] not in CLASSIFICATIONS \
                or type(row["note"]) is not str \
                or type(row["explicit"]) is not bool \
                or ((row["classification"] == "finite-population")
                    != (type(row["population_id"]) is str
                        and bool(row["population_id"]))) \
                or (row["classification"] == "finite-population"
                    and row["explicit"] is not True) \
                or (candidate_requires[row["candidate_id"]]
                    and row["explicit"] is not True):
            raise BeliefV2SeedRegistryError(
                "seed registry classification closure drift")
        if row["classification"] == "finite-population":
            referenced_populations.add(row["population_id"])
            if row["population_id"] not in population_sources \
                    or candidate_paths[row["candidate_id"]] \
                    not in population_sources[row["population_id"]]:
                raise BeliefV2SeedRegistryError(
                    "seed registry classification source drift")
        candidate_ids.append(row["candidate_id"])
    if set(candidate_ids) != {
            row["candidate_id"] for row in scan["candidates"]} \
            or len(candidate_ids) != len(set(candidate_ids)) \
            or referenced_populations != set(population_sources) \
            or registry["v2_population_id"] not in population_sources:
        raise BeliefV2SeedRegistryError(
            "seed registry classification closure drift")


def seed_scan_bytes(scan: dict[str, Any]) -> bytes:
    validate_seed_scan(scan)
    return canonical_json_bytes(scan)


def seed_registry_bytes(
        registry: dict[str, Any], *, scan: dict[str, Any]) -> bytes:
    validate_seed_registry(registry, scan=scan)
    return canonical_json_bytes(registry)
