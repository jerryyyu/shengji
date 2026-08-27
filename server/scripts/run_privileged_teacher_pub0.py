#!/usr/bin/env python3
"""Run the public-information PT-Pub0 diagnostic on Mini's open-DEV roots.

Same launch discipline as the Sol0/Cla0 runners (whose hardened helpers are
imported verbatim, never forked), with two additions: ``--planner`` selects
the external agent (``codex`` = GPT-5.6 Sol via the Sol0 process, ``claude``
via the Cla0 adapter), and the session factory is the public-information
``Pub0GameSession`` so every planner sees acting-seat public state only and
rollouts average production-sampled worlds.
"""

from __future__ import annotations

import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("PT-Pub0 runner requires Python -P -B")

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

_SOL0_SCRIPT = Path(__file__).resolve().parent / \
    "run_privileged_teacher_sol0.py"
_SPEC = importlib.util.spec_from_file_location("pt_sol0_runner", _SOL0_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_sol0 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_sol0)

# Reviewed helpers, reused verbatim — never forked.
_read_single_link = _sol0._read_single_link
_strict_report = _sol0._strict_report
_publish_exclusive = _sol0._publish_exclusive
_git = _sol0._git
_run_with_frozen_design = _sol0._run_with_frozen_design


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--expected-design-sha256", required=True)
    parser.add_argument("--c0-report", type=Path, required=True)
    parser.add_argument("--expected-c0-external-sha256", required=True)
    parser.add_argument("--expected-c0-report-sha256", required=True)
    parser.add_argument("--expected-c0-git", required=True)
    parser.add_argument("--full-report", type=Path, required=True)
    parser.add_argument("--expected-full-external-sha256", required=True)
    parser.add_argument("--expected-full-report-sha256", required=True)
    parser.add_argument("--expected-full-git", required=True)
    parser.add_argument("--seed-secret", type=Path, required=True)
    parser.add_argument("--planner", required=True,
                        choices=("codex", "claude"))
    parser.add_argument("--claude-model", default=None)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise ValueError("PT-Pub0 runner refuses PYTHONPATH")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ValueError("PT-Pub0 runner requires strict native mode")
    repo = Path(__file__).resolve().parents[2]
    if (_git(repo, "rev-parse", "HEAD") != args.expected_git
            or _git(repo, "status", "--porcelain", "--untracked-files=all")
            or platform.node() != "Jerrys-Mac-mini.local"):
        raise ValueError("PT-Pub0 source or Mini host identity drift")
    for ancestor in (args.expected_c0_git, args.expected_full_git):
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", ancestor,
                 args.expected_git), cwd=repo, check=False).returncode != 0:
            raise ValueError("PT-Pub0 source ancestry drift")

    from shengji.engine import fast
    if not fast.activate():
        raise ValueError("PT-Pub0 runner requires active native engine")
    from shengji.rl.privileged_teacher_cla0 import (
        CLAUDE_MODEL,
        claude_version,
        make_claude_planner_process,
        require_claude_model,
        resolve_claude_binary,
    )
    from shengji.rl.privileged_teacher_pub0 import (
        Pub0Design,
        Pub0GameSession,
    )
    from shengji.rl.privileged_teacher_sol0_report import (
        report_bytes,
        run_dev,
    )

    c0_raw = _read_single_link(
        args.c0_report, mode=0o400, label="C0 report")
    full_raw = _read_single_link(
        args.full_report, mode=0o400, label="PT-Full report")
    c0_external = hashlib.sha256(c0_raw).hexdigest()
    full_external = hashlib.sha256(full_raw).hexdigest()
    if (c0_external != args.expected_c0_external_sha256
            or full_external != args.expected_full_external_sha256):
        raise ValueError("PT-Pub0 parent external identity drift")
    c0_report = _strict_report(c0_raw, "C0 report")
    full_report = _strict_report(full_raw, "PT-Full report")
    if (c0_report.get("report_sha256") !=
            args.expected_c0_report_sha256
            or full_report.get("report_sha256") !=
            args.expected_full_report_sha256):
        raise ValueError("PT-Pub0 parent internal identity drift")

    secret = _read_single_link(
        args.seed_secret, mode=0o600, label="seed secret")
    if len(secret) != 32:
        raise ValueError("PT-Pub0 seed secret identity drift")

    if args.planner == "claude":
        model = require_claude_model(args.claude_model or CLAUDE_MODEL)
        planner_binary = resolve_claude_binary()
        planner_version = claude_version(planner_binary)
        planner_process = make_claude_planner_process(model)
    else:
        if args.claude_model is not None:
            raise ValueError("--claude-model requires --planner claude")
        from shengji.rl.privileged_teacher_sol0 import MODEL as SOL_MODEL
        found = shutil.which("codex")
        if found is None:
            raise ValueError("PT-Pub0 Codex binary absent")
        planner_binary = Path(found).resolve()
        planner_version = subprocess.run(
            (str(planner_binary), "--version"), check=True,
            capture_output=True, text=True).stdout.strip()
        model = SOL_MODEL
        planner_process = None  # run_dev default = Sol0 codex process

    python_path = Path(sys.executable).resolve()
    tool_script = (repo / "server" / "scripts" /
                   "privileged_teacher_sol0_tool.py").resolve()
    if (args.private_root.exists() or args.private_root.is_symlink()
            or not tool_script.is_file()):
        raise ValueError("PT-Pub0 private root or tool identity drift")
    design = Pub0Design(
        seed_commitment_sha256=hashlib.sha256(secret).hexdigest(),
        execution_git=args.expected_git,
        native_sha256=hashlib.sha256(
            Path(fast._fast.__file__).read_bytes()).hexdigest(),
        hostname="Jerrys-Mac-mini.local",
        c0_external_sha256=c0_external,
        c0_report_sha256=args.expected_c0_report_sha256,
        c0_execution_git=args.expected_c0_git,
        full_external_sha256=full_external,
        full_report_sha256=args.expected_full_report_sha256,
        full_execution_git=args.expected_full_git,
        codex_binary_sha256=hashlib.sha256(
            planner_binary.read_bytes()).hexdigest(),
        codex_version=planner_version,
        python_binary_sha256=hashlib.sha256(
            python_path.read_bytes()).hexdigest(),
        python_version=sys.version,
        tool_script_sha256=hashlib.sha256(
            tool_script.read_bytes()).hexdigest(),
        planner=args.planner,
        planner_model=model,
    )

    def progress(row: dict[str, object]) -> None:
        print("PT_PUB0_PROGRESS " + json.dumps(
            row, sort_keys=True, separators=(",", ":")), flush=True)

    def execute_bound_design():
        args.private_root.mkdir(mode=0o700)
        return run_dev(
            design, c0_report=c0_report, c0_external_sha256=c0_external,
            full_report=full_report, full_external_sha256=full_external,
            seed_secret=secret, private_root=args.private_root,
            tool_script=tool_script, codex_binary=planner_binary,
            workers=args.workers, progress_sink=progress,
            planner_process=planner_process,
            session_factory=Pub0GameSession)

    report = _run_with_frozen_design(
        design, args.expected_design_sha256, execute_bound_design)
    raw = report_bytes(
        report, design, c0_report=c0_report,
        c0_external_sha256=c0_external, full_report=full_report,
        full_external_sha256=full_external)
    _publish_exclusive(args.out, raw)
    print(json.dumps({
        "status": report["status"],
        "completed_record_count": report["completed_record_count"],
        "incomplete_record_count": report["incomplete_record_count"],
        "report_sha256": report["report_sha256"],
        "public_output": str(args.out.resolve()),
        "private_root": str(args.private_root.resolve()),
        "scientific_execution_authorized": False,
        "strength_claim_authorized": False,
    }, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
