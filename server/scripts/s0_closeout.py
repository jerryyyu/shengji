#!/usr/bin/env python3
"""Independently verify a terminal S0 packet, then optionally clean services.

This is deliberately outside the evidence-producing S0 runner, aggregator and
packet generator.  Its default mode is read-only: rerun the packet verifier,
require byte identity with the durable packet, and check that the handoff bar is
complete.  Launch-service removal is a separate explicit terminal-only action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Callable


TERMINAL_STATES = {"S0_COMPLETE_PROMOTE", "S0_COMPLETE_SELECT_NONE"}
PHASE_RE = re.compile(
    r"^(s0a|s0b-[a-z0-9-]+|s0c-[a-z0-9-]+) manifests \(8/8\):",
    re.MULTILINE,
)
RunCommand = Callable[..., subprocess.CompletedProcess]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def packet_phases(text: str) -> list[str]:
    """Return reached phases in packet order."""
    return PHASE_RE.findall(text)


def _has_line(text: str, prefix: str) -> bool:
    return any(line.startswith(prefix) for line in text.splitlines())


def packet_problems(text: str, expected_state: str) -> list[str]:
    """Check the independently generated packet covers the handoff exit bar."""
    problems: list[str] = []
    if expected_state not in TERMINAL_STATES:
        problems.append(f"nonterminal supervisor state: {expected_state!r}")
        return problems

    state_lines = [line for line in text.splitlines()
                   if line.startswith("STATE: ")]
    if state_lines != [f"STATE: {expected_state}"]:
        problems.append(
            f"packet STATE differs from supervisor: {state_lines!r}")

    phases = packet_phases(text)
    families = [phase.split("-", 1)[0] for phase in phases]
    if not phases or phases[0] != "s0a":
        problems.append(f"first reached phase is not s0a: {phases!r}")
    if len(families) != len(set(families)):
        problems.append(f"packet repeats a phase family: {phases!r}")
    has_s0b = "s0b" in families
    has_s0c = "s0c" in families
    if has_s0b != has_s0c:
        problems.append(
            f"terminal packet must reach both S0b and S0c or neither: {phases!r}")
    if families not in (["s0a"], ["s0a", "s0b", "s0c"]):
        problems.append(f"reached phases are out of protocol order: {phases!r}")
    if expected_state == "S0_COMPLETE_PROMOTE" and not has_s0c:
        problems.append("PROMOTE is impossible without an S0c confirmation")

    always = (
        "HEAD / origin / dirty:",
        "S0a effects:",
        "Final production decision from registered rule:",
        "CALIB / REPORT: sealed and unscored",
    )
    for prefix in always:
        if not _has_line(text, prefix):
            problems.append(f"missing packet field: {prefix}")

    for phase in phases:
        required = (
            f"{phase} manifests (8/8):",
            f"{phase} aggregate:",
            f"{phase} coverage:",
            f"{phase} provenance:",
            f"{phase} sampler counters:",
        )
        for prefix in required:
            if not _has_line(text, prefix):
                problems.append(f"missing packet field: {prefix}")

        manifests = next((line for line in text.splitlines()
                          if line.startswith(f"{phase} manifests (8/8):")), "")
        if manifests and manifests.count("sha256=") != 8:
            problems.append(f"{phase} does not list eight manifest hashes")
        aggregate = next((line for line in text.splitlines()
                          if line.startswith(f"{phase} aggregate:")), "")
        if aggregate and any(bit not in aggregate
                             for bit in ("sha256=", "survivor=")):
            problems.append(f"{phase} aggregate identity is incomplete")

        coverage = next((line for line in text.splitlines()
                         if line.startswith(f"{phase} coverage:")), "")
        if coverage and "exact=true" not in coverage:
            problems.append(f"{phase} coverage is not marked exact")
        provenance = next((line for line in text.splitlines()
                           if line.startswith(f"{phase} provenance:")), "")
        provenance_bar = (
            "host=", "python=", "compiled_binary_sha256=",
            "within_phase=true", "cross_phase=true", "frozen_identity=true")
        if provenance and any(bit not in provenance for bit in provenance_bar):
            problems.append(f"{phase} provenance bar is incomplete")

    if has_s0b:
        for prefix in (
            "S0b allocation contrasts:",
            "S0c confirmation contrasts:",
            "S0c criteria:",
        ):
            if not _has_line(text, prefix):
                problems.append(f"missing packet field: {prefix}")
        for prefix in (
            "  adaptive-report_uniform:",
            "  adaptive-random:",
            "  arm-reference:",
            "  arm-null:",
            "  null-reference:",
        ):
            if not _has_line(text, prefix):
                problems.append(f"missing registered contrast: {prefix.strip()}")
    else:
        for line in ("S0b: NOT REACHED", "S0c: NOT REACHED"):
            if line not in text.splitlines():
                problems.append(f"missing packet field: {line}")

    decision_prefix = "Final production decision from registered rule: "
    decision = next((line.removeprefix(decision_prefix)
                     for line in text.splitlines()
                     if line.startswith(decision_prefix)), "")
    if expected_state == "S0_COMPLETE_PROMOTE" and not decision.startswith("PROMOTE "):
        problems.append(f"PROMOTE state has non-promotion decision: {decision!r}")
    if (expected_state == "S0_COMPLETE_SELECT_NONE" and
            not decision.startswith("SELECT NONE;")):
        problems.append(f"SELECT NONE state has different decision: {decision!r}")
    return problems


def verify_terminal_packet(
        server: Path, python: Path, packet: Path, packet_script: Path,
        *, run_command: RunCommand = subprocess.run) -> dict:
    """Regenerate a terminal packet and require byte-for-byte durability."""
    state_path = server / "runs/logs/s0_pipeline_supervisor.state.json"
    if not state_path.exists():
        raise RuntimeError(f"missing supervisor state: {state_path}")
    state = json.loads(state_path.read_text())
    status = state.get("status")
    if status not in TERMINAL_STATES:
        raise RuntimeError(f"S0 is not terminal: {state}")
    if not packet.exists():
        raise RuntimeError(f"missing durable terminal packet: {packet}")

    completed = run_command(
        [str(python), str(packet_script),
         "--server", str(server), "--python", str(python)],
        cwd=server, check=True, capture_output=True,
    )
    fresh = completed.stdout
    if isinstance(fresh, str):
        fresh = fresh.encode()
    stored = packet.read_bytes()
    if fresh != stored:
        raise RuntimeError(
            "fresh independent packet differs from durable terminal packet")
    text = stored.decode()
    problems = packet_problems(text, status)
    if problems:
        raise RuntimeError(f"terminal packet misses the handoff bar: {problems}")
    return {
        "state": status,
        "packet": str(packet),
        "packet_sha256": sha256_bytes(stored),
        "phases": packet_phases(text),
    }


def expected_launchctl_labels(phases: list[str]) -> list[str]:
    """Enumerate only services owned by the reached authoritative Mini chain."""
    labels: list[str] = []
    for phase in phases:
        if not re.fullmatch(r"s0a|s0b-[a-z0-9-]+|s0c-[a-z0-9-]+", phase):
            raise ValueError(f"unsafe S0 phase for service cleanup: {phase!r}")
        prefix = phase.replace("-", "_")
        labels.extend(f"com.shengji.s0mini.{prefix}.{i}" for i in range(8))
    labels.extend((
        "com.shengji.s0mini.keepawake",
        "com.shengji.s0mini.supervisor",
    ))
    return labels


def parse_launchctl_list(output: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-1] != "Label":
            entries[fields[-1]] = fields[0]
    return entries


def launchctl_entries(
        *, run_command: RunCommand = subprocess.run) -> dict[str, str]:
    completed = run_command(
        ["launchctl", "list"], check=True, text=True, capture_output=True)
    return parse_launchctl_list(completed.stdout)


def cleanup_launchctl(
        labels: list[str], *, run_command: RunCommand = subprocess.run) -> dict:
    """Remove exact inactive S0 jobs only after the caller verified terminality."""
    before = launchctl_entries(run_command=run_command)
    keepawake = "com.shengji.s0mini.keepawake"
    active = [label for label in labels
              if label != keepawake and before.get(label, "-") != "-"]
    if active:
        raise RuntimeError(
            f"refusing cleanup while terminal S0 services are active: {active}")

    # Workers first, keepawake next, supervisor last.  Unknown services are
    # intentionally untouched, even when they share the s0mini namespace.
    loaded = [label for label in labels if label in before]
    supervisor = "com.shengji.s0mini.supervisor"
    ordered = [label for label in loaded
               if label not in {keepawake, supervisor}]
    ordered.extend(label for label in (keepawake, supervisor) if label in loaded)
    for label in ordered:
        run_command(["launchctl", "remove", label], check=True,
                    text=True, capture_output=True)

    after = launchctl_entries(run_command=run_command)
    remaining = [label for label in labels if label in after]
    if remaining:
        raise RuntimeError(f"S0 services remain loaded after cleanup: {remaining}")
    return {
        "loaded_before": {label: before[label] for label in loaded},
        "removed": ordered,
        "remaining": remaining,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, default=Path.cwd())
    parser.add_argument("--python", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--packet-script", type=Path)
    parser.add_argument("--cleanup-launchctl", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    server = args.server.resolve()
    python = (args.python or server / ".venv/bin/python").resolve()
    packet = (args.packet or
              server / "runs/logs/s0-final-packet.txt").resolve()
    packet_script = (args.packet_script or
                     Path(__file__).with_name("s0_packet.py")).resolve()
    result = {
        "schema": "s0-terminal-closeout-v1",
        **verify_terminal_packet(server, python, packet, packet_script),
    }
    labels = expected_launchctl_labels(result["phases"])
    result["expected_launchctl_labels"] = labels
    result["cleanup_requested"] = args.cleanup_launchctl
    if args.cleanup_launchctl:
        result["launchctl_cleanup"] = cleanup_launchctl(labels)

    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if args.out:
        if args.out.exists():
            raise RuntimeError(f"refusing to overwrite closeout artifact: {args.out}")
        args.out.write_text(text)


if __name__ == "__main__":
    main()
