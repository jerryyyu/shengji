#!/usr/bin/env python3
"""Publish the race-free R4 serial-to-optimized cutover receipt.

This controller is deliberately separate from both live R4 checkouts.  It can
run only after the optimized calibration service has completed and the serial
service has been stopped.  It authenticates both exact source/evidence roots,
proves both test namespaces untouched, independently runs the optimized
pre-test reopener, and publishes one immutable receipt.  It does not stop a
service or open the test split itself.
"""

from __future__ import annotations

import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("R4 cutover receipt requires Python -P -B")

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import stat
import subprocess
from typing import Any


SCHEMA = "belief-v1-v2-r4-cutover-receipt-v1"
REVIEW_SCHEMA = "belief-v1-v2-r4-cutover-receipt-review-v1"
REVIEW_PREFIX = "BELIEF_V1_V2_R4_CUTOVER_RECEIPT_V1_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
LOCAL_HOSTNAME = "Jerrys-Mac-mini.local"
SOURCE_SPEC_SHA256 = (
    "8e7f29b286807033beacf1e4c7d46527e09c53ad7404cd063bc9578627cb1994")
SOURCE_FREEZE_SHA256 = (
    "573fcade25d985f58c0d179a581a40619b5745fc2152c52f4740e1355ae1fc16")
SOURCE_ADMISSION_SHA256 = (
    "21d9cea8a1ef2905dd0a8a85308e54141e58362e0764f04f388412bedfff0961")
SYNTHETIC_TEST_EXPECTED_ROUND_COUNT = 1_339

OPTIMIZED = {
    "alias": "shengji-perf",
    "hostname": "ubuntu-32gb-hel1-2",
    "source_git": "d82ba224eb59a25014b076fb07116eaa6513934a",
    "checkout": "/opt/belief-r4-parallel-eval-d82ba22",
    "root": "/opt/belief-r4-parallel-completion-v1-r1",
    "unit": "belief-r4-parallel-completion-d82ba22-r1.service",
    "freeze_sha256": (
        "3070cff6cf9d391a0ac1ed6aa0f12ee57baa8266a3103b40e70171ae69508318"),
    "admission_sha256": (
        "77d8d7f8c194f9f29e1ba8d6c3715d86e4c95e353534b403f169e0e6a387a374"),
    "review_sha256": (
        "414163234de2eb5aa9b4ca7a5a079790c51fb09553dfe927192efe1efd88c24e"),
    "launch_sha256": None,
    "launch_path": None,
}
SERIAL = {
    "alias": "shengji-cloud",
    "hostname": "ubuntu-32gb-hel1-1",
    "source_git": "e10cb3d3426d758f2d757d41462aba6a06bc60c8",
    "checkout": "/opt/belief-r4-completion-e10cb3d",
    "root": "/opt/belief-r4-completion-v1-r3",
    "unit": "belief-r4-completion-e10cb3d-r3.service",
    "freeze_sha256": (
        "59c747be56bdd20c792608ed09be307b9661c8aff6ad7e0e720cd8156de7fea4"),
    "admission_sha256": (
        "6e17fa33b8e6ac2efdd753d5fd285b5f0fbe8a8e59593077504c56de5e16358a"),
    "review_sha256": (
        "d4bd42f70bf4e545d7aa0cc7f547402fcffdad3d5fbb25925354dbe53b5c0709"),
    "launch_sha256": (
        "a5008eb0846138748aa4be882515b4ac90bc29a1c5d22ea7028d620e03d2f3e7"),
    "launch_path": (
        "/opt/belief-r4-completion-e10cb3d-review-support-r3/"
        "launch-r4-completion.sh"),
}
FORBIDDEN = (
    "r4-completion-test-attempt.json",
    "terminal.partial",
    "terminal",
    "r4-completion-terminal.json",
)
AUTHORITY = {
    "serial_resume_authorized": False,
    "test_opening_executed": False,
    "retry_authorized": False,
    "training_authorized": False,
    "sampler_implementation_authorized": False,
    "gameplay_strength_screen_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
    "merge_authorized": False,
}


class R4CutoverError(ValueError):
    """A live lane, review, readiness proof, or receipt drifted."""


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_git_sha(value: object) -> bool:
    return type(value) is str and len(value) == 40 and all(
        char in "0123456789abcdef" for char in value)


def expected_review_claim(execution_git: str) -> dict[str, object]:
    if not _is_git_sha(execution_git):
        raise R4CutoverError("R4 cutover execution Git drift")
    return {
        "schema": REVIEW_SCHEMA,
        "execution_git": execution_git,
        "optimized_lane": dict(OPTIMIZED),
        "serial_lane": dict(SERIAL),
        "required_observations": {
            "optimized_calibration_complete": True,
            "optimized_pretest_independently_reopened": True,
            "both_services_inactive_and_workerless": True,
            "both_test_namespaces_absent": True,
            "serial_stopped_before_receipt": True,
        },
        "receipt_only": True,
        "authority": dict(AUTHORITY),
    }


def expected_review_marker(execution_git: str) -> bytes:
    return REVIEW_PREFIX.encode() + canonical_json_bytes(
        expected_review_claim(execution_git))


def _git(repo: Path, *args: str, binary: bool = False):
    result = subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=not binary)
    return result.stdout if binary else result.stdout.strip()


def authenticate_review(
        repo: Path, *, review_commit: str, execution_git: str) -> bytes:
    """Authenticate one append-only Claude marker on real remote main."""
    if not repo.is_absolute() or not _is_git_sha(review_commit):
        raise R4CutoverError("R4 cutover review input drift")
    try:
        subprocess.run(
            ("git", "fetch", "origin", "main"), cwd=repo, check=True,
            capture_output=True)
        remote = subprocess.run(
            ("git", "ls-remote", "--exit-code", "origin",
             "refs/heads/main"), cwd=repo, check=True, capture_output=True,
            text=True).stdout.splitlines()
        local = _git(repo, "rev-parse", "origin/main")
        if len(remote) != 1 or remote[0].split()[0] != local:
            raise R4CutoverError("R4 cutover canonical main drift")
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 "origin/main"), cwd=repo).returncode != 0:
            raise R4CutoverError("R4 cutover review is not on main")
        parents = _git(repo, "show", "-s", "--format=%P", review_commit).split()
        identity = tuple(_git(
            repo, "show", "-s", f"--format={field}", review_commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        message = _git(repo, "show", "-s", "--format=%B", review_commit)
        changed = _git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            review_commit).splitlines()
        if len(parents) != 1 \
                or identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                                REVIEWER_NAME, REVIEWER_EMAIL) \
                or REVIEWER_SESSION_TRAILER not in message \
                or changed != [REVIEW_LEDGER]:
            raise R4CutoverError("R4 cutover review provenance drift")
        current = _git(
            repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(
            repo, "show", f"{parents[0]}:{REVIEW_LEDGER}", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise R4CutoverError("R4 cutover review authentication failed") from exc
    marker = expected_review_marker(execution_git)
    prefix = REVIEW_PREFIX.encode()
    if not current.startswith(previous) \
            or [line for line in current.splitlines(keepends=True)
                if line.startswith(prefix)] != [marker] \
            or any(line.startswith(prefix)
                   for line in previous.splitlines(keepends=True)):
        raise R4CutoverError("R4 cutover review marker drift")
    return marker


_REMOTE_PROBE = r'''
import datetime, hashlib, json, os, pathlib, socket, subprocess, sys
checkout, root_text, unit, launch_text = sys.argv[1:5]
root = pathlib.Path(root_text)
def digest(path):
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    except OSError:
        return None
def git(*args):
    p=subprocess.run(("git","-C",checkout,*args),capture_output=True,text=True)
    return p.returncode,p.stdout.strip()
props=("LoadState","ActiveState","SubState","MainPID","NRestarts","ExecMainStatus")
p=subprocess.run(("systemctl","show",unit,*sum((["-p",x] for x in props),[]),"--no-pager"),capture_output=True,text=True)
status={x:"" for x in props}
for line in p.stdout.splitlines():
    if "=" in line:
        k,v=line.split("=",1)
        status[k]=v
workers=[]
for item in pathlib.Path("/proc").glob("[0-9]*"):
    try:
        pid=int(item.name)
        if pid==os.getpid(): continue
        raw=(item/"cmdline").read_bytes().replace(b"\0",b" ")
    except (OSError,ValueError):
        continue
    if root_text.encode() in raw and b"belief_v2_worker.py" in raw:
        workers.append(pid)
rc,head=git("rev-parse","HEAD")
src_rc,dirty=git("status","--porcelain","--untracked-files=all")
forbidden={name:(root/name).exists() or (root/name).is_symlink() for name in (
 "r4-completion-test-attempt.json","terminal.partial","terminal","r4-completion-terminal.json")}
payload={
 "hostname":socket.gethostname(),"boot_identity":pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
 "observed_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "source_git":head if rc==0 else None,"source_clean":src_rc==0 and not dirty,
 "root_exists":root.exists(),"root_is_directory":root.is_dir(),"root_is_symlink":root.is_symlink(),
 "freeze_sha256":digest(root/"freeze.json"),"admission_sha256":digest(root/"admission.json"),"review_sha256":digest(root/"review.md"),
 "launch_sha256":None if launch_text=="-" else digest(launch_text),
 "unit_load_state":status["LoadState"] or "not-found","unit_active_state":status["ActiveState"] or "inactive",
 "unit_sub_state":status["SubState"] or "dead","unit_main_pid":int(status["MainPID"] or 0),
 "unit_n_restarts":int(status["NRestarts"] or 0),"unit_exec_main_status":int(status["ExecMainStatus"] or 0),
 "matching_worker_pids":sorted(workers),"forbidden_paths_present":forbidden,
 "calibration_completion_exists":(root/"calibration/completion.json").is_file(),
 "calibration_selection_manifest_exists":(root/"calibration/selection/manifest.json").is_file(),
 "calibration_partial_present":(root/"calibration/selection.partial").exists() or (root/"calibration/selection.partial").is_symlink(),
 "calibration_completion_sha256":digest(root/"calibration/completion.json"),
 "calibration_selection_manifest_sha256":digest(root/"calibration/selection/manifest.json"),
}
print(json.dumps(payload,sort_keys=True,separators=(",",":")))
'''


def _ssh_json(alias: str, command: tuple[str, ...]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ("ssh", "-o", "BatchMode=yes", alias, shlex.join(command)),
            check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError,
            UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R4CutoverError(f"R4 cutover remote probe failed on {alias}") \
            from exc
    if type(payload) is not dict \
            or canonical_json_bytes(payload).decode().strip() \
            != result.stdout.strip():
        raise R4CutoverError(f"R4 cutover remote probe drift on {alias}")
    return payload


def probe_lane(spec: dict[str, object]) -> dict[str, Any]:
    launch = spec["launch_path"] or "-"
    return _ssh_json(str(spec["alias"]), (
        "/usr/bin/python3", "-P", "-B", "-c", _REMOTE_PROBE,
        str(spec["checkout"]), str(spec["root"]), str(spec["unit"]),
        str(launch)))


def _validate_lane(
        observed: dict[str, Any], spec: dict[str, object], *,
        calibration_required: bool) -> None:
    forbidden = observed.get("forbidden_paths_present") \
        if type(observed) is dict else None
    if type(observed) is not dict \
            or observed.get("hostname") != spec["hostname"] \
            or type(observed.get("boot_identity")) is not str \
            or len(observed["boot_identity"]) != 36 \
            or type(observed.get("observed_utc")) is not str \
            or observed.get("source_git") != spec["source_git"] \
            or observed.get("source_clean") is not True \
            or observed.get("root_exists") is not True \
            or observed.get("root_is_directory") is not True \
            or observed.get("root_is_symlink") is not False \
            or observed.get("freeze_sha256") != spec["freeze_sha256"] \
            or observed.get("admission_sha256") != spec["admission_sha256"] \
            or observed.get("review_sha256") != spec["review_sha256"] \
            or observed.get("launch_sha256") != spec["launch_sha256"] \
            or observed.get("unit_active_state") not in {"inactive", "failed"} \
            or observed.get("unit_sub_state") not in {"dead", "failed"} \
            or observed.get("unit_main_pid") != 0 \
            or observed.get("unit_n_restarts") != 0 \
            or (calibration_required
                and observed.get("unit_exec_main_status") != 0) \
            or observed.get("matching_worker_pids") != [] \
            or type(forbidden) is not dict \
            or set(forbidden) != set(FORBIDDEN) \
            or any(value is not False for value in forbidden.values()) \
            or observed.get("calibration_partial_present") is not False \
            or (calibration_required and (
                observed.get("calibration_completion_exists") is not True
                or observed.get("calibration_selection_manifest_exists")
                is not True
                or type(observed.get("calibration_completion_sha256"))
                is not str
                or len(observed["calibration_completion_sha256"]) != 64
                or type(observed.get(
                    "calibration_selection_manifest_sha256")) is not str
                or len(observed[
                    "calibration_selection_manifest_sha256"]) != 64)):
        raise R4CutoverError(
            f"R4 cutover {spec['alias']} lane is not quiescent and clean")


def _validate_probe_stability(
        before: dict[str, Any], after: dict[str, Any],
        spec: dict[str, object], *, calibration_required: bool) -> None:
    _validate_lane(before, spec, calibration_required=calibration_required)
    _validate_lane(after, spec, calibration_required=calibration_required)
    stable_fields = (
        "hostname", "boot_identity", "source_git", "freeze_sha256",
        "admission_sha256", "review_sha256", "launch_sha256",
        "calibration_completion_sha256",
        "calibration_selection_manifest_sha256")
    if any(before.get(field) != after.get(field) for field in stable_fields):
        raise R4CutoverError(
            f"R4 cutover {spec['alias']} changed during pretest reopen")


def optimized_pretest_readiness() -> dict[str, Any]:
    command = (
        "/usr/bin/env", "-u", "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED=0",
        "SHENGJI_FAST=1", "SHENGJI_REQUIRE_VOIDS=1",
        "/opt/belief-r4-parallel-completion-d82ba22-venv/bin/python",
        "-P", "-B", "scripts/belief_v2_worker.py",
        "r4-verify-calibration", "--root", str(OPTIMIZED["root"]))
    try:
        result = subprocess.run(
            ("ssh", "-o", "BatchMode=yes", str(OPTIMIZED["alias"]),
             "cd /opt/belief-r4-parallel-eval-d82ba22/server && "
             + shlex.join(command)), check=True, capture_output=True,
            text=True)
        payload = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError,
            UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R4CutoverError("R4 optimized pretest reopen failed") from exc
    if type(payload) is not dict \
            or canonical_json_bytes(payload).decode() != result.stdout \
            or payload.get("schema") != (
                "belief-v1-v2-r4-completion-pretest-readiness-v1") \
            or payload.get("completion_execution_git") != OPTIMIZED["source_git"] \
            or payload.get("completion_freeze_sha256") != OPTIMIZED["freeze_sha256"] \
            or payload.get("completion_admission_sha256") != OPTIMIZED["admission_sha256"] \
            or payload.get("source_spec_sha256") != SOURCE_SPEC_SHA256 \
            or payload.get("source_freeze_sha256") != SOURCE_FREEZE_SHA256 \
            or payload.get("source_admission_sha256") != SOURCE_ADMISSION_SHA256 \
            or type(payload.get("source_calibration_manifest_sha256")) is not str \
            or len(payload["source_calibration_manifest_sha256"]) != 64 \
            or payload.get("synthetic_test_expected_round_count") != SYNTHETIC_TEST_EXPECTED_ROUND_COUNT \
            or payload.get("calibration_independently_reopened") is not True \
            or payload.get("test_population_metadata_opened") is not False \
            or payload.get("test_attempt_file_absent") is not True \
            or payload.get("terminal_population_absent") is not True \
            or payload.get("source_test_split_decision_open_count") != 0 \
            or payload.get("test_opening_executed") is not False \
            or payload.get("execution_authorized") is not False \
            or payload.get("strength_claim_authorized") is not False \
            or payload.get("deployment_authorized") is not False:
        raise R4CutoverError("R4 optimized pretest readiness drift")
    return payload


def build_receipt(
        *, execution_git: str, review_commit: str, review_marker: bytes,
        optimized_pre_observation: dict[str, Any],
        serial_pre_observation: dict[str, Any],
        optimized_observation: dict[str, Any],
        serial_observation: dict[str, Any],
        readiness: dict[str, Any]) -> dict[str, object]:
    _validate_probe_stability(
        optimized_pre_observation, optimized_observation, OPTIMIZED,
        calibration_required=True)
    _validate_probe_stability(
        serial_pre_observation, serial_observation, SERIAL,
        calibration_required=False)
    # Validate the injected/reopened payload at the same altitude as the live
    # reader; tests can therefore prove every refusal branch without SSH.
    if type(readiness) is not dict \
            or readiness.get("schema") != (
                "belief-v1-v2-r4-completion-pretest-readiness-v1") \
            or readiness.get("completion_execution_git") != OPTIMIZED["source_git"] \
            or readiness.get("completion_freeze_sha256") != OPTIMIZED["freeze_sha256"] \
            or readiness.get("completion_admission_sha256") != OPTIMIZED["admission_sha256"] \
            or readiness.get("source_spec_sha256") != SOURCE_SPEC_SHA256 \
            or readiness.get("source_freeze_sha256") != SOURCE_FREEZE_SHA256 \
            or readiness.get("source_admission_sha256") != SOURCE_ADMISSION_SHA256 \
            or readiness.get("source_calibration_manifest_sha256") != optimized_observation.get(
                "calibration_selection_manifest_sha256") \
            or readiness.get("synthetic_test_expected_round_count") != SYNTHETIC_TEST_EXPECTED_ROUND_COUNT \
            or readiness.get("calibration_independently_reopened") is not True \
            or readiness.get("test_population_metadata_opened") is not False \
            or readiness.get("test_attempt_file_absent") is not True \
            or readiness.get("terminal_population_absent") is not True \
            or readiness.get("source_test_split_decision_open_count") != 0 \
            or readiness.get("test_opening_executed") is not False \
            or readiness.get("execution_authorized") is not False \
            or readiness.get("strength_claim_authorized") is not False \
            or readiness.get("deployment_authorized") is not False:
        raise R4CutoverError("R4 optimized pretest readiness drift")
    marker = expected_review_marker(execution_git)
    if review_marker != marker or not _is_git_sha(review_commit):
        raise R4CutoverError("R4 cutover review binding drift")
    body = {
        "schema": SCHEMA,
        "execution_git": execution_git,
        "review_commit": review_commit,
        "review_marker_sha256": _sha(marker),
        "pre_readiness_lane_observations": {
            "optimized": optimized_pre_observation,
            "serial": serial_pre_observation,
        },
        "optimized_lane": optimized_observation,
        "serial_lane": serial_observation,
        "optimized_pretest_readiness": readiness,
        "both_services_inactive_and_workerless": True,
        "both_test_namespaces_absent": True,
        "serial_stopped_before_receipt": True,
        "optimized_calibration_complete": True,
        "optimized_test_open_preconditions_met": True,
        "source_test_split_decision_open_count": 0,
        "test_opening_executed": False,
        "authority": dict(AUTHORITY),
    }
    return {**body, "receipt_sha256": _sha(canonical_json_bytes(body))}


def _publish(path: Path, raw: bytes) -> None:
    output = path.resolve()
    if not output.is_absolute() or output.exists() or output.is_symlink() \
            or not output.parent.is_dir() or output.parent.is_symlink():
        raise R4CutoverError("R4 cutover output path drift")
    descriptor = os.open(
        output, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0), 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        parent = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        raise
    if stat.S_IMODE(output.stat().st_mode) != 0o400:
        raise R4CutoverError("R4 cutover output mode drift")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--review-commit", required=True)
    args = parser.parse_args()
    if os.environ.get("PYTHONPATH"):
        raise R4CutoverError("R4 cutover runner refuses PYTHONPATH")
    repo = Path(__file__).resolve().parents[2]
    if platform.node() != LOCAL_HOSTNAME \
            or _git(repo, "rev-parse", "HEAD") != args.expected_git \
            or _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise R4CutoverError("R4 cutover local source identity drift")
    marker = authenticate_review(
        repo, review_commit=args.review_commit,
        execution_git=args.expected_git)
    optimized_pre = probe_lane(OPTIMIZED)
    serial_pre = probe_lane(SERIAL)
    readiness = optimized_pretest_readiness()
    # Probe both hosts again after the potentially long independent reopen.
    # The receipt binds only the second observation, closing the stale-check
    # window before publication.
    optimized = probe_lane(OPTIMIZED)
    serial = probe_lane(SERIAL)
    receipt = build_receipt(
        execution_git=args.expected_git, review_commit=args.review_commit,
        review_marker=marker, optimized_pre_observation=optimized_pre,
        serial_pre_observation=serial_pre,
        optimized_observation=optimized, serial_observation=serial,
        readiness=readiness)
    raw = canonical_json_bytes(receipt)
    _publish(args.out, raw)
    print(canonical_json_bytes({
        "status": "READY",
        "receipt_sha256": receipt["receipt_sha256"],
        "output": str(args.out.resolve()),
        "optimized_test_open_preconditions_met": True,
        "test_opening_executed": False,
        "retry_authorized": False,
    }).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
