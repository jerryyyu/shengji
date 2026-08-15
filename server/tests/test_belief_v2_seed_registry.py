"""Adversarial closure tests for the V2 seed registry."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from shengji.rl.belief_v2_seed_registry import (
    BeliefV2SeedRegistryError,
    SeedClassificationV1,
    SeedPopulationV1,
    build_seed_registry,
    scan_seed_sources,
    seed_registry_bytes,
    seed_scan_bytes,
    validate_seed_registry,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / "server" / "pkg").mkdir(parents=True)
    (repo / "docs_archive").mkdir()
    (repo / "server" / "pkg" / "protocol.py").write_text(
        "SEED_START = 100\nvalue = derive_seed('policy')\n",
        encoding="utf-8")
    (repo / "DESIGN.md").write_text(
        "The production round_seed population is frozen.\n",
        encoding="utf-8")
    (repo / "docs_archive" / "old.md").write_text(
        "OLD_SEED = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-qm", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def _closed(scan):
    candidates = scan["candidates"]
    classifications = []
    for candidate in candidates:
        if candidate["path"] == "DESIGN.md":
            classifications.append(SeedClassificationV1(
                candidate_id=candidate["candidate_id"],
                classification="finite-population",
                population_id="belief-v2"))
        elif "SEED_START" in candidate["line"]:
            classifications.append(SeedClassificationV1(
                candidate_id=candidate["candidate_id"],
                classification="finite-population",
                population_id="prior-v1"))
        else:
            classifications.append(SeedClassificationV1(
                candidate_id=candidate["candidate_id"],
                classification="derived-rng-stream"))
    populations = (
        SeedPopulationV1(
            population_id="belief-v2",
            source_paths=("DESIGN.md",), seeds=(1000, 1001, 1002)),
        SeedPopulationV1(
            population_id="prior-v1",
            source_paths=("server/pkg/protocol.py",), seeds=(100, 101)),
    )
    return tuple(classifications), populations


def test_scan_binds_every_tracked_active_source_and_seed_line(tmp_path):
    repo, head = _repo(tmp_path)
    scan = scan_seed_sources(repo.resolve(), expected_git=head)
    assert [row["path"] for row in scan["source_files"]] == [
        "DESIGN.md", "server/pkg/protocol.py"]
    assert scan["candidate_count"] == 3
    assert all("seed" in row["line"].lower()
               for row in scan["candidates"])
    assert b"docs_archive" not in seed_scan_bytes(scan)
    assert scan["opens_game_data"] is False
    assert scan["execution_authorized"] is False


def test_registry_requires_exact_classification_and_proves_disjoint(tmp_path):
    repo, head = _repo(tmp_path)
    scan = scan_seed_sources(repo.resolve(), expected_git=head)
    classifications, populations = _closed(scan)
    registry = build_seed_registry(
        scan, classifications=classifications, populations=populations,
        v2_population_id="belief-v2")
    validate_seed_registry(registry, scan=scan)
    assert seed_registry_bytes(registry, scan=scan).endswith(b"\n")
    assert registry["candidate_count"] == 3
    assert registry["v2_collision_count"] == 0
    assert registry["capture_authorized"] is False

    with pytest.raises(BeliefV2SeedRegistryError,
                       match="classification is incomplete"):
        build_seed_registry(
            scan, classifications=classifications[:-1],
            populations=populations, v2_population_id="belief-v2")
    with pytest.raises(BeliefV2SeedRegistryError,
                       match="classification identity"):
        build_seed_registry(
            scan, classifications=(*classifications, classifications[0]),
            populations=populations, v2_population_id="belief-v2")


def test_registry_refuses_v2_collision_and_coordinated_digest_rehash(tmp_path):
    repo, head = _repo(tmp_path)
    scan = scan_seed_sources(repo.resolve(), expected_git=head)
    classifications, populations = _closed(scan)
    colliding = (
        populations[0],
        SeedPopulationV1(
            population_id="prior-v1",
            source_paths=("server/pkg/protocol.py",), seeds=(100, 1001)),
    )
    with pytest.raises(BeliefV2SeedRegistryError, match="collides"):
        build_seed_registry(
            scan, classifications=classifications, populations=colliding,
            v2_population_id="belief-v2")

    registry = build_seed_registry(
        scan, classifications=classifications, populations=populations,
        v2_population_id="belief-v2")
    forged = copy.deepcopy(registry)
    finite = next(row for row in forged["classifications"]
                  if row["classification"] == "finite-population")
    finite["classification"] = "derived-rng-stream"
    from shengji.rl.belief_contract import canonical_json_bytes
    import hashlib
    forged["classification_sha256"] = hashlib.sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-seed-classification-population-v1",
        "classifications": forged["classifications"],
    })).hexdigest()
    with pytest.raises(BeliefV2SeedRegistryError,
                       match="classification closure"):
        validate_seed_registry(forged, scan=scan)


def test_scan_refuses_dirty_or_wrong_checkout(tmp_path):
    repo, head = _repo(tmp_path)
    (repo / "server" / "pkg" / "protocol.py").write_text(
        "SEED_START = 200\n", encoding="utf-8")
    with pytest.raises(BeliefV2SeedRegistryError, match="exact and clean"):
        scan_seed_sources(repo.resolve(), expected_git=head)
    _git(repo, "checkout", "--", "server/pkg/protocol.py")
    with pytest.raises(BeliefV2SeedRegistryError, match="exact and clean"):
        scan_seed_sources(repo.resolve(), expected_git="0" * 40)
