#!/usr/bin/env python3
"""Build the HANDOFF_ACTIVE S0 return packet from independently verified artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


SHA = "be1e39cd9281f752d610ff770f6a280098024388"
SHORT = SHA[:10]
EXPECTED_RUNTIME_IDENTITY = {
    "host": "Jerrys-Mac-mini.local",
    "python": "3.14.6",
    "fast_engine": True,
    "require_voids": True,
    "digests": {
        "evaluation": "4b75a5e643c8a2514c6d14707085f89a33e0c534adc2989229894f2f219a6b16",
        "fast_binary": "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1",
        "fast_router": "f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e",
        "mcbot": "3b97b651f9ce7324b22ec50e361ab2de46f4314eb33fe3d12ec7fd069a05b31f",
        "registry": "2a5e15480dc345abbf01c9b17cb3e3be90609a473ab8934a96a825730c1652d4",
        "runner": "c895234e5d5c2799d6421738f6fc6640edece2e968dd699c688eefac9fc5171a",
    },
}
S0A_TO_S0B = {
    "mc-s0-report-mean": "s0b-mean",
    "mc-s0-report-lcb": "s0b-lcb",
}
S0B_TO_S0C = {
    "mc-s0-report-mean": "s0c-report-mean",
    "mc-s0-adaptive-mean": "s0c-adaptive-mean",
    "mc-s0-report-lcb": "s0c-report-lcb",
    "mc-s0-adaptive": "s0c-adaptive-lcb",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def git(server: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=server, text=True, check=True,
        capture_output=True,
    ).stdout.strip()


def aggregate_name(phase: str) -> str:
    return "s0a-v1.aggregate.json" if phase == "s0a" else f"{phase}-v1.aggregate.json"


def verify_aggregate(server: Path, logs: Path, phase: str,
                     python: Path) -> tuple[Path, dict]:
    path = logs / aggregate_name(phase)
    if not path.exists():
        raise RuntimeError(f"missing aggregate: {path}")
    pattern = f"runs/logs/s0-protocol-v2_{phase}_shard0?_{SHORT}.jsonl.manifest.json"
    env = dict(os.environ)
    env["S0_SOURCE_SERVER"] = str(server)
    completed = subprocess.run(
        [str(python), str(Path(__file__).with_name("s0_aggregate.py")), phase,
         "--pattern", pattern],
        cwd=server, text=True, check=True, capture_output=True, env=env,
    )
    fresh = json.loads(completed.stdout)
    stored = json.loads(path.read_text())
    if fresh != stored:
        raise RuntimeError(f"stored aggregate differs from fresh verifier: {path}")
    return path, stored


def verify_parent(child: dict, parent_path: Path, parent: dict) -> None:
    """Prove the child is bound to the exact aggregate inspected here."""
    identity = child.get("parent")
    if not isinstance(identity, dict):
        raise RuntimeError(f"{child.get('phase')} has no parent identity")
    expected = {
        "sha256": sha256(parent_path),
        "schema": parent.get("schema"),
        "phase": parent.get("phase"),
        "git_sha": parent.get("git_sha"),
        "clusters": parent.get("clusters"),
        "survivor_label": parent.get("survivor_label"),
        "survivor_policy": parent.get("survivor_policy"),
        "runtime_identity": parent.get("runtime_identity"),
    }
    drift = {key: {"actual": identity.get(key), "expected": value}
             for key, value in expected.items()
             if identity.get(key) != value}
    if drift:
        raise RuntimeError(
            f"{child.get('phase')} parent hash/identity drift: {drift}")


def load_manifests(logs: Path, phase: str) -> list[tuple[Path, dict]]:
    out = []
    for i in range(8):
        path = logs / f"s0-protocol-v2_{phase}_shard{i:02d}_{SHORT}.jsonl.manifest.json"
        if not path.exists():
            raise RuntimeError(f"missing manifest: {path}")
        value = json.loads(path.read_text())
        if not value.get("complete") or value.get("problems"):
            raise RuntimeError(f"manifest is not cleanly complete: {path}")
        out.append((path, value))
    return out


def manifest_runtime(manifest: dict) -> dict:
    return {
        "host": manifest.get("host"),
        "python": manifest.get("python"),
        "fast_engine": manifest.get("fast_engine"),
        "require_voids": manifest.get("require_voids"),
        "digests": manifest.get("digests"),
    }


def verify_runtime_chain(phase_values: dict[str, tuple[Path, dict]],
                         phase_manifests: dict[str, list[tuple[Path, dict]]],
                         expected: dict = EXPECTED_RUNTIME_IDENTITY) -> dict:
    """Reject within-phase, cross-phase, or frozen-runtime provenance drift."""
    observed = {}
    for phase, (_, aggregate) in phase_values.items():
        manifests = phase_manifests[phase]
        runtimes = [manifest_runtime(manifest) for _, manifest in manifests]
        if not runtimes or any(runtime != runtimes[0] for runtime in runtimes[1:]):
            raise RuntimeError(f"{phase} manifests disagree on runtime identity")
        if aggregate.get("runtime_identity") != runtimes[0]:
            raise RuntimeError(f"{phase} aggregate runtime differs from manifests")
        observed[phase] = runtimes[0]
    unique = {json.dumps(value, sort_keys=True) for value in observed.values()}
    if len(unique) != 1:
        raise RuntimeError(f"cross-phase runtime identity drift: {observed}")
    runtime = next(iter(observed.values()))
    if runtime != expected:
        raise RuntimeError(
            f"runtime identity differs from frozen Mini identity: {runtime}")
    return runtime


def fmt_effect(value: dict) -> str:
    mean = float(value["mean"])
    half = float(value["half_width_95"])
    return (f"{mean:+.6f} +/- {half:.6f} "
            f"95%=[{mean-half:+.6f}, {mean+half:+.6f}], "
            f"clusters={value['clusters']}")


def counter_summary(aggregate: dict) -> dict:
    result = {}
    for label, sides in aggregate["counter_totals"].items():
        totals = {key: sum(int(side.get(key, 0)) for side in sides.values())
                  for key in ("sample_attempts", "accepted_worlds", "failed_worlds",
                              "short_searches", "zero_world", "void_fallbacks")}
        totals["reconciled"] = (
            totals["sample_attempts"] ==
            totals["accepted_worlds"] + totals["failed_worlds"])
        result[label] = totals
    return result


def artifact_lines(server: Path, phase: str, aggregate_path: Path,
                   aggregate: dict, manifests: list[tuple[Path, dict]]) -> list[str]:
    manifest_bits = []
    for path, _ in manifests:
        manifest_bits.append(f"{path.relative_to(server)} sha256={sha256(path)}")
    lines = [
        f"{phase} manifests ({len(manifests)}/8): " + "; ".join(manifest_bits),
        (f"{phase} aggregate: {aggregate_path.relative_to(server)} "
         f"sha256={sha256(aggregate_path)} survivor={aggregate.get('survivor_policy')!r} "
         f"promotion={aggregate.get('promotion')}"),
        (f"{phase} coverage: records={json.dumps(aggregate['record_counts'], sort_keys=True)}; "
         f"seeds={aggregate['seed0']}..{aggregate['seed_hi']}; flips=[0,1]; exact=true"),
    ]
    runtime = aggregate["runtime_identity"]
    lines.append(
        f"{phase} provenance: host={runtime['host']}; python={runtime['python']}; "
        f"compiled_binary_sha256={runtime['digests']['fast_binary']}; "
        "within_phase=true; cross_phase=true; frozen_identity=true"
    )
    counters = counter_summary(aggregate)
    if not all(v["reconciled"] and not v["short_searches"] and
               not v["zero_world"] and not v["void_fallbacks"]
               for v in counters.values()):
        raise RuntimeError(f"counter packet gate failed in {phase}: {counters}")
    lines.append(f"{phase} sampler counters: {json.dumps(counters, sort_keys=True)}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, default=Path.cwd())
    parser.add_argument("--python", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    server = args.server.resolve()
    python = args.python or server / ".venv/bin/python"
    logs = server / "runs/logs"
    state_path = logs / "s0_pipeline_supervisor.state.json"
    state = json.loads(state_path.read_text())
    if state.get("status") not in {"S0_COMPLETE_PROMOTE", "S0_COMPLETE_SELECT_NONE"}:
        raise RuntimeError(f"S0 is not terminal: {state}")

    head = git(server, "rev-parse", "HEAD")
    origin = git(server, "rev-parse", "origin/main")
    dirty = git(server, "status", "--porcelain")
    if head != SHA:
        raise RuntimeError(f"packet checkout HEAD {head} != frozen {SHA}")
    if dirty:
        raise RuntimeError(f"packet checkout is dirty: {dirty}")

    phases = ["s0a"]
    s0a_path, s0a = verify_aggregate(server, logs, "s0a", python)
    s0b_phase = S0A_TO_S0B.get(s0a.get("survivor_policy"))
    if s0b_phase:
        phases.append(s0b_phase)
        s0b_path, s0b = verify_aggregate(server, logs, s0b_phase, python)
        verify_parent(s0b, s0a_path, s0a)
        s0c_phase = S0B_TO_S0C.get(s0b.get("survivor_policy"))
        if not s0c_phase:
            raise RuntimeError(f"unregistered S0b survivor: {s0b.get('survivor_policy')!r}")
        phases.append(s0c_phase)
        s0c_path, s0c = verify_aggregate(server, logs, s0c_phase, python)
        verify_parent(s0c, s0b_path, s0b)
    else:
        s0b_path = s0b = s0c_path = s0c = None

    expected_terminal = (
        "S0_COMPLETE_PROMOTE" if s0c and s0c.get("promotion")
        else "S0_COMPLETE_SELECT_NONE")
    if state["status"] != expected_terminal:
        raise RuntimeError(f"supervisor state {state['status']} != {expected_terminal}")

    lines = [
        f"STATE: {expected_terminal}",
        f"HEAD / origin / dirty: HEAD={head}; origin/main={origin}; dirty={dirty!r}",
    ]
    phase_values = {"s0a": (s0a_path, s0a)}
    if s0b_phase:
        phase_values[s0b_phase] = (s0b_path, s0b)
        phase_values[s0c_phase] = (s0c_path, s0c)
    phase_manifests = {
        phase: load_manifests(logs, phase)
        for phase in phases
    }
    verify_runtime_chain(phase_values, phase_manifests)
    for phase in phases:
        path, aggregate = phase_values[phase]
        manifests = phase_manifests[phase]
        lines.extend(artifact_lines(server, phase, path, aggregate, manifests))

    stats = s0a["stats"]
    lines.append("S0a effects:")
    for key in sorted(stats):
        lines.append(f"  {key}: {fmt_effect(stats[key])}")
    if s0b_phase:
        lines.append("S0b allocation contrasts:")
        for key in ("adaptive-report_uniform", "adaptive-random"):
            lines.append(f"  {key}: {fmt_effect(s0b['stats'][key])}")
        lines.append("S0c confirmation contrasts:")
        for key in ("arm-reference", "arm-null", "null-reference"):
            lines.append(f"  {key}: {fmt_effect(s0c['stats'][key])}")
        lines.append(f"S0c criteria: {json.dumps(s0c['criteria'], sort_keys=True)}")
    else:
        lines.extend(["S0b: NOT REACHED", "S0c: NOT REACHED"])

    decision = (f"PROMOTE {s0c.get('survivor_policy')}"
                if expected_terminal == "S0_COMPLETE_PROMOTE"
                else "SELECT NONE; production remains mc-strong")
    lines.extend([
        f"Final production decision from registered rule: {decision}",
        ("CALIB / REPORT: sealed and unscored; the committed S0 runner consumes "
         "only its disjoint literal random-seed blocks and no CALIB/REPORT asset."),
    ])
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if args.out:
        if args.out.exists():
            raise RuntimeError(f"refusing to overwrite packet: {args.out}")
        args.out.write_text(text)


if __name__ == "__main__":
    main()
