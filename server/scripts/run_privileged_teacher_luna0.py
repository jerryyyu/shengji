#!/usr/bin/env python3
"""Run the bounded, paired PT-Luna0 descriptive benchmark."""

from __future__ import annotations

import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("PT-Luna0 runner requires Python -P -B")

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess


def _read_single_link(path: Path, *, mode: int, label: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ValueError(f"PT-Luna0 {label} open refused") from exc
    try:
        before = os.fstat(descriptor)
        chunks = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        stable = tuple(getattr(before, field) for field in fields) == tuple(
            getattr(after, field) for field in fields)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != mode
                or not stable or len(raw) != before.st_size):
            raise ValueError(f"PT-Luna0 {label} identity drift")
        return raw
    finally:
        os.close(descriptor)


def _strict_report(raw: bytes, label: str) -> dict[str, object]:
    from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"PT-Luna0 {label} is not canonical JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise ValueError(f"PT-Luna0 {label} is not canonical JSON")
    return payload


def _publish_exclusive(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("PT-Luna0 output already exists")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        raise


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(("git", *args), cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def _run_with_frozen_design(design: object, expected_design_sha256: str,
                            execute):
    from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
    if (len(expected_design_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in expected_design_sha256)):
        raise ValueError("PT-Luna0 expected design SHA-256 is invalid")
    actual = hashlib.sha256(canonical_json_bytes(design.payload())).hexdigest()
    if actual != expected_design_sha256:
        raise ValueError("PT-Luna0 frozen runtime design drift")
    return execute()


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
    parser.add_argument("--sol0-report", type=Path, required=True)
    parser.add_argument("--expected-sol0-external-sha256", required=True)
    parser.add_argument("--expected-sol0-report-sha256", required=True)
    parser.add_argument("--expected-sol0-git", required=True)
    parser.add_argument("--expected-sol0-design-sha256", required=True)
    parser.add_argument("--seed-secret", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise ValueError("PT-Luna0 runner refuses PYTHONPATH")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ValueError("PT-Luna0 runner requires strict native mode")
    if args.workers != 2:
        raise ValueError("PT-Luna0 runner requires exactly two workers")
    repo = Path(__file__).resolve().parents[2]
    if (_git(repo, "rev-parse", "HEAD") != args.expected_git
            or _git(repo, "status", "--porcelain", "--untracked-files=all")
            or platform.node() != "Jerrys-Mac-mini.local"):
        raise ValueError("PT-Luna0 source or Mini host identity drift")
    for ancestor in (args.expected_c0_git, args.expected_full_git,
                     args.expected_sol0_git):
        if subprocess.run(("git", "merge-base", "--is-ancestor", ancestor,
                           args.expected_git), cwd=repo,
                          check=False).returncode != 0:
            raise ValueError("PT-Luna0 source ancestry drift")
    from shengji.engine import fast
    if not fast.activate():
        raise ValueError("PT-Luna0 runner requires active native engine")
    from shengji.rl.privileged_teacher_luna0_report import (
        Luna0Design, report_bytes, run_dev)
    c0_raw = _read_single_link(args.c0_report, mode=0o400, label="C0 report")
    full_raw = _read_single_link(args.full_report, mode=0o400, label="PT-Full report")
    sol_raw = _read_single_link(args.sol0_report, mode=0o400, label="PT-Sol0 report")
    c0_external = hashlib.sha256(c0_raw).hexdigest()
    full_external = hashlib.sha256(full_raw).hexdigest()
    sol_external = hashlib.sha256(sol_raw).hexdigest()
    if (c0_external != args.expected_c0_external_sha256
            or full_external != args.expected_full_external_sha256
            or sol_external != args.expected_sol0_external_sha256):
        raise ValueError("PT-Luna0 parent external identity drift")
    c0_report = _strict_report(c0_raw, "C0 report")
    full_report = _strict_report(full_raw, "PT-Full report")
    sol_report = _strict_report(sol_raw, "PT-Sol0 report")
    if (c0_report.get("report_sha256") != args.expected_c0_report_sha256
            or full_report.get("report_sha256") != args.expected_full_report_sha256
            or sol_report.get("report_sha256") != args.expected_sol0_report_sha256):
        raise ValueError("PT-Luna0 parent internal identity drift")
    secret = _read_single_link(args.seed_secret, mode=0o600, label="seed secret")
    if len(secret) != 32:
        raise ValueError("PT-Luna0 seed secret identity drift")
    codex_path_raw = shutil.which("codex")
    if codex_path_raw is None:
        raise ValueError("PT-Luna0 Codex binary absent")
    codex_path = Path(codex_path_raw).resolve()
    codex_version = subprocess.run((str(codex_path), "--version"), check=True,
                                   capture_output=True, text=True).stdout.strip()
    python_path = Path(sys.executable).resolve()
    tool_script = (repo / "server" / "scripts" /
                   "privileged_teacher_sol0_tool.py").resolve()
    if (args.private_root.exists() or args.private_root.is_symlink()
            or not tool_script.is_file()):
        raise ValueError("PT-Luna0 private root or tool identity drift")
    design = Luna0Design(
        seed_commitment_sha256=hashlib.sha256(secret).hexdigest(),
        execution_git=args.expected_git,
        native_sha256=hashlib.sha256(Path(fast._fast.__file__).read_bytes()).hexdigest(),
        hostname="Jerrys-Mac-mini.local",
        c0_external_sha256=c0_external,
        c0_report_sha256=args.expected_c0_report_sha256,
        c0_execution_git=args.expected_c0_git,
        full_external_sha256=full_external,
        full_report_sha256=args.expected_full_report_sha256,
        full_execution_git=args.expected_full_git,
        codex_binary_sha256=hashlib.sha256(codex_path.read_bytes()).hexdigest(),
        codex_version=codex_version,
        python_binary_sha256=hashlib.sha256(python_path.read_bytes()).hexdigest(),
        python_version=sys.version,
        tool_script_sha256=hashlib.sha256(tool_script.read_bytes()).hexdigest(),
        sol0_external_sha256=sol_external,
        sol0_report_sha256=args.expected_sol0_report_sha256,
        sol0_execution_git=args.expected_sol0_git,
        sol0_design_sha256=args.expected_sol0_design_sha256,
    )
    def progress(row: dict[str, object]) -> None:
        print("PT_LUNA0_PROGRESS " + json.dumps(row, sort_keys=True,
                                               separators=(",", ":")), flush=True)
    def execute_bound_design():
        args.private_root.mkdir(mode=0o700)
        return run_dev(
            design, c0_report=c0_report, c0_external_sha256=c0_external,
            full_report=full_report, full_external_sha256=full_external,
            sol0_report=sol_report, sol0_external_sha256=sol_external,
            seed_secret=secret, private_root=args.private_root,
            tool_script=tool_script, codex_binary=codex_path,
            workers=args.workers, progress_sink=progress)
    report = _run_with_frozen_design(design, args.expected_design_sha256,
                                     execute_bound_design)
    raw = report_bytes(
        report, design, c0_report=c0_report, c0_external_sha256=c0_external,
        full_report=full_report, full_external_sha256=full_external,
        sol0_report=sol_report, sol0_external_sha256=sol_external)
    _publish_exclusive(args.out, raw)
    print(json.dumps({"status": report["status"],
                      "completed_record_count": report["completed_record_count"],
                      "incomplete_record_count": report["incomplete_record_count"],
                      "refusal_count": report["refusal_count"],
                      "report_sha256": report["report_sha256"],
                      "public_output": str(args.out.resolve()),
                      "private_root": str(args.private_root.resolve()),
                      "scientific_execution_authorized": False,
                      "strength_claim_authorized": False},
                     sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
