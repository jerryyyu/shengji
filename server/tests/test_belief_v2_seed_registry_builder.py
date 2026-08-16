"""Real population-table and source-selector witnesses for V2."""

from __future__ import annotations

import subprocess
from pathlib import Path

from shengji.rl.belief_v2_seed_registry import (
    scan_seed_sources,
    seed_registry_bytes,
)
from shengji.rl.belief_v2_seed_registry_builder import (
    build_reviewed_seed_registry,
    reviewed_population_specs,
    v2_population_id,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _selector_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    by_path: dict[str, set[str]] = {}
    for spec in reviewed_population_specs():
        for path, needle in spec.selectors:
            by_path.setdefault(path, set()).add(needle)
    for relative, needles in by_path.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        # The production ledger markers carry seed fields later on the same
        # canonical JSON line.  Preserve that scan altitude in this compact
        # selector fixture even when the unique selector itself omits "seed".
        path.write_text("\n".join(
            f"{needle} seed" for needle in sorted(needles)) + "\n",
            encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Test", "-c",
         "user.email=test@example.com", "commit", "-qm", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_real_population_table_is_compact_complete_and_disjoint(tmp_path):
    specs = reviewed_population_specs()
    populations = {spec.population.population_id: spec.population
                   for spec in specs}
    assert len(populations) == len(specs)
    assert len(populations[v2_population_id].seeds) == 13_312
    assert len(populations["belief-v1-v2-capacity-preflight"].seeds) == 416
    assert len(populations["belief-v1-c4-synthetic-training"].seeds) == 4_096
    assert populations["teacher-stage-c-state-scan"].ranges == (
        (188_000_000, 188_016_383),)
    assert populations["t4-midlate-composition-screen"].ranges == (
        (192_000_000, 192_000_003),
        (193_000_000, 193_002_047),
    )
    assert populations["s6-full-hand-preflight-and-screen"].ranges == (
        (436_000_000_000, 436_009_000_051),
        (437_000_000_000, 458_501_121_839),
    )
    assert populations["s4-future-c2-retired-and-reseeded"].ranges == (
        (300_000_000_000, 349_150_778_511),
        (360_000_000_000, 409_150_778_511),
    )
    affected = populations["pair-affected-state-capture"]
    assert affected.ranges == ((310_000_000, 321_999_999),)
    assert affected.seeds == ()

    repo, head = _selector_repo(tmp_path)
    scan = scan_seed_sources(repo.resolve(), expected_git=head)
    registry = build_reviewed_seed_registry(scan)
    assert registry["v2_population_id"] == v2_population_id
    assert registry["v2_collision_count"] == 0
    assert len(registry["populations"]) == len(specs)
    assert all(row["explicit"] is True
               for row in registry["classifications"]
               if row["classification"] == "finite-population")
    assert seed_registry_bytes(registry, scan=scan).endswith(b"\n")
