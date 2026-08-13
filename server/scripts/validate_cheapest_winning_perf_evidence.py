#!/usr/bin/env python3
"""Independent validator for durable cheapest-winning A/B evidence."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def elf_text(path: Path) -> tuple[int, str]:
    target = path.with_name(path.name + ".text.validate.tmp")
    assert not target.exists()
    try:
        subprocess.run(["objcopy", "--dump-section", f".text={target}", path],
                       check=True)
        return target.stat().st_size, sha(target)
    finally:
        target.unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--offline"):
        raise SystemExit("usage: validate_exact_ab.py ROOT [--offline]")
    root = Path(sys.argv[1]).resolve()
    offline = len(sys.argv) == 3
    design = json.loads((root / "design.json").read_bytes())
    result = json.loads((root / "result.json").read_bytes())
    manifest = json.loads((root / "bundle.manifest.json").read_bytes())
    assert manifest["schema"] == "cheapest-winning-native-perf-bundle-manifest-v1"
    assert set(path.name for path in root.iterdir() if path.is_file()) == \
        set(manifest["files"]) | {"bundle.manifest.json"}
    for name, record in manifest["files"].items():
        path = root / name
        assert path.stat().st_size == record["bytes"]
        assert sha(path) == record["sha256"]
    assert (root / "design.sha256").read_text().strip() == sha(root / "design.json")
    assert result["design_sha256"] == sha(root / "design.json")
    assert result["harness_sha256"] == design["harness"]["sha256"]
    assert sha(root / "harness.py") == design["harness"]["sha256"]
    environment = json.loads((root / "environment.json").read_bytes())
    assert environment["pythonhashseed"] == "unset"
    assert environment["python_version"] == design["runtime"]["python_version"]
    if not offline:
        assert sha(Path(environment["python_resolved"])) == environment["python_sha256"]
    for label in ("base", "head"):
        expected = design[label]
        identity = result["identities"][label]
        assert identity["git"] == expected["git"]
        assert identity["fast_pyx_sha256"] == expected["fast_pyx_sha256"] \
            == sha(root / f"{label}._fast.pyx")
        assert identity["fast_router_sha256"] == expected["fast_router_sha256"] \
            == sha(root / f"{label}.fast.py")
        assert identity.get("source_sha256s", {}) == \
            expected.get("source_sha256s", {})
        for relative, digest in expected.get("source_sha256s", {}).items():
            name = f"{label}.source.{relative.replace('/', '__')}"
            assert sha(root / name) == digest
        if offline:
            # The manifest authenticates the entire bundled ELF.  Extracting
            # its .text section is an on-host check because macOS lacks GNU
            # objcopy; the recorded section identity remains visible below.
            size = identity["fast_engine_elf_text_bytes"]
            digest = identity["fast_engine_elf_text_sha256"]
        else:
            size, digest = elf_text(root / f"{label}._fast.so")
        assert (size, digest) == (expected["fast_engine_elf_text_bytes"],
                                  expected["fast_engine_elf_text_sha256"])
        assert identity["fast_engine_elf_text_bytes"] == size
        assert identity["fast_engine_elf_text_sha256"] == digest
    assert len(result["records"]) == design["design"]["pairs"]
    assert len(result["records"]) >= 2
    assert [r["seed"] for r in result["records"]] == design["design"]["seeds"]
    assert [r["order"] for r in result["records"]] == design["design"]["orders"]
    base_times, head_times, reductions = [], [], []
    for row in result["records"]:
        seed = row["seed"]
        normalized_bytes = {}
        for arm in ("base", "head"):
            stem = f"seed-{seed}.{arm}"
            raw = root / f"{stem}.raw.json"
            norm = root / f"{stem}.normalized.json"
            stdout = root / f"{stem}.stdout.jsonl"
            stderr = root / f"{stem}.stderr.log"
            record = row[arm]
            assert raw.stat().st_size == record["raw_semantic_bytes"]
            assert sha(raw) == record["raw_semantic_sha256"]
            assert norm.stat().st_size == record["normalized_semantic_bytes"]
            assert sha(norm) == record["normalized_semantic_sha256"]
            assert sha(stdout) == record["stdout_sha256"]
            assert sha(stderr) == record["stderr_sha256"]
            summary_lines = stdout.read_text().splitlines()
            assert len(summary_lines) == 1
            summary = json.loads(summary_lines[0])
            assert summary["semantic_sha256"] == sha(raw)
            assert summary["elapsed_seconds"] == record["elapsed_seconds"]
            assert summary["history_plays"] == record["history_plays"]
            for name in ("rollouts", "search_calls", "short_search_decisions", "zero_world_decisions"):
                assert summary[name] == record[name]
            value = json.loads(raw.read_bytes())
            stats = {key: 0 for key in ("digest", "display", "source_digest")}
            for seat_records in value["decision_records"]:
                for decision in seat_records:
                    rec = decision.get("record")
                    ballot = rec.get("ballot") if isinstance(rec, dict) else None
                    if not isinstance(ballot, dict):
                        continue
                    for key in stats:
                        if key in ballot:
                            ballot.pop(key)
                            stats[key] += 1
            assert stats == record["normalization_removals"]
            assert canonical(value) == norm.read_bytes()
            normalized_bytes[arm] = norm.read_bytes()
        assert normalized_bytes["base"] == normalized_bytes["head"]
        assert row["normalized_semantics_exact"] is True
        a, b = row["base"]["elapsed_seconds"], row["head"]["elapsed_seconds"]
        base_times.append(a); head_times.append(b); reductions.append(100.0 * (a - b) / a)
    aggregate = result["aggregate"]
    assert math.isclose(sum(base_times), aggregate["base_wall_seconds"], abs_tol=1e-12)
    assert math.isclose(sum(head_times), aggregate["head_wall_seconds"], abs_tol=1e-12)
    assert math.isclose(100.0 * (sum(base_times) - sum(head_times)) / sum(base_times), aggregate["wall_reduction_percent"], abs_tol=1e-12)
    assert math.isclose(100.0 * (sum(base_times) / sum(head_times) - 1), aggregate["throughput_increase_percent"], abs_tol=1e-12)
    assert reductions == aggregate["paired_relative_reductions_percent"]
    assert math.isclose(statistics.mean(reductions), aggregate["paired_relative_mean_percent"], abs_tol=1e-12)
    critical = design["design"].get(
        "one_sided_t_critical", design["design"].get("one_sided_t95_df5"))
    assert critical is not None
    lower = statistics.mean(reductions) - critical * statistics.stdev(reductions) / math.sqrt(len(reductions))
    assert math.isclose(lower, aggregate["paired_one_sided_95_lb_percent"], abs_tol=1e-12)
    retention = result.get("retention", {
        "statistic": "wall_reduction_percent",
        "minimum": design["design"].get("minimum_wall_reduction_percent", 0.0),
    })
    assert retention == design["design"].get("retention", retention)
    if retention["statistic"] == "wall_reduction_percent":
        kept = aggregate["wall_reduction_percent"] >= retention["minimum"]
    elif retention["statistic"] == "paired_one_sided_95_lb_percent":
        kept = aggregate["paired_one_sided_95_lb_percent"] > retention["minimum"]
    else:
        raise AssertionError(retention)
    expected = "retain" if kept else "drop"
    assert result["decision"] == expected
    print(json.dumps({"status": "VERIFIED_OFFLINE" if offline else "VERIFIED_ON_HOST", "host_interpreter_revalidated": not offline, "result_sha256": sha(root / "result.json"), "decision": expected, **aggregate}, sort_keys=True))


if __name__ == "__main__":
    main()
