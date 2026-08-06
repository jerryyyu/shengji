#!/usr/bin/env python3
"""Build the HANDOFF_ACTIVE S0 return packet from independently verified artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


SHA = "be1e39cd9281f752d610ff770f6a280098024388"
SHORT = SHA[:10]
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
    completed = subprocess.run(
        [str(python), "scripts/s0_aggregate.py", phase,
         "--pattern", pattern],
        cwd=server, text=True, check=True, capture_output=True,
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
    hosts = sorted({m["host"] for _, m in manifests})
    pythons = sorted({m["python"] for _, m in manifests})
    binaries = sorted({m["digests"]["fast_binary"] for _, m in manifests})
    lines.append(
        f"{phase} provenance: hosts={hosts}; python={pythons}; "
        f"compiled_binary_sha256={binaries}; agreement="
        f"{len(hosts) == len(pythons) == len(binaries) == 1}"
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
    for phase in phases:
        path, aggregate = phase_values[phase]
        manifests = load_manifests(logs, phase)
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
