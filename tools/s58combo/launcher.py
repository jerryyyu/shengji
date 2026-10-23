"""Guarded, unarmed-by-default runner for a frozen combo screen packet.

This module only executes when an already reviewed plan explicitly carries
``dispatch_authorized`` and a matching RELEASE token. It never reads or
summarizes scientific outcomes; output remains under an unread hold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import re
import socket
import shlex


class LaunchRefused(RuntimeError):
    """The immutable packet or a host guard is not satisfied."""


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def packet_digest(plan: dict, expected: dict) -> str:
    payload = json.dumps({"plan": plan, "expected_configs": expected},
                         sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def render_wrapper(packet_sha: str, runner_sha: str, python: str = sys.executable) -> str:
    """Render a tiny immutable wrapper; its own SHA is the RELEASE token."""
    if any(not re.fullmatch(r'[0-9a-f]{64}', value) for value in (packet_sha, runner_sha)):
        raise ValueError("packet and runner hashes must be full SHA256 values")
    return """#!/bin/sh
set -eu
PACKET_SHA='%s'
RUNNER_SHA='%s'
%s -I -c 'import hashlib,sys; assert hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest() == sys.argv[2], "runner source drift"' "$4" "$RUNNER_SHA"
if [ "$#" -ge 7 ]; then
  exec %s -I -B "$4" --packet "$1" --expected "$2" --release "$3" \
    --runner-file "$4" --source "$5" --host-lock "${6:-/root/.claude-host.lock}" --hold "$7" \
    --packet-sha "$PACKET_SHA" --runner-sha "$RUNNER_SHA" --wrapper "$0"
fi
exec %s -I -B "$4" --packet "$1" --expected "$2" --release "$3" \
  --runner-file "$4" --source "$5" --host-lock "${6:-/root/.claude-host.lock}" \
  --packet-sha "$PACKET_SHA" --runner-sha "$RUNNER_SHA" --wrapper "$0"
""" % (packet_sha, runner_sha, shlex.quote(python), shlex.quote(python), shlex.quote(python))


def _clean_env(arm: dict, source: Path) -> dict:
    if arm.get("environment", {}).get("SHENGJI_FAST") not in ("0", "1"):
        raise LaunchRefused("explicit engine mode SHENGJI_FAST=0 or 1 required")
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("SHENGJI_") and key not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(arm.get("environment", {}))
    env["PYTHONPATH"] = str(source / "server")
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    return env


def _assert_plan(plan: dict, expected: dict, source: Path, output: Path) -> None:
    if plan.get("python_executable") != sys.executable:
        raise LaunchRefused("interpreter differs from frozen packet")
    if plan.get("schema") != "s58combo-unarmed-window-plan-v1":
        raise LaunchRefused("unexpected plan schema")
    if plan.get("dispatch_authorized") is not True:
        raise LaunchRefused("dispatch is not authorized in the frozen plan")
    windows = plan.get("windows")
    if not isinstance(windows, list) or len(windows) != 20 or len({w.get("output") for w in windows}) != 20:
        raise LaunchRefused("window inventory is not exactly 20 unique outputs")
    if set(expected) != {w.get("output") for w in windows}:
        raise LaunchRefused("expected config inventory drift")
    head = plan.get("source_head")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise LaunchRefused("source_head must be a full 40-hex commit")
    if plan.get("host_identity") != {"hostname": socket.gethostname()}:
        raise LaunchRefused("host identity mismatch")
    if plan.get("source_path") != str(source.resolve()):
        raise LaunchRefused("source path drift")
    if not source.is_dir() or not (source / ".git").exists():
        raise LaunchRefused("source checkout is not a git root")
    root = output.resolve()
    for window in windows:
        target = Path(window["output"])
        if target.resolve().parent != root or target.is_symlink():
            raise LaunchRefused("window output is not an immediate child of output root")
        argv = window.get("argv")
        if not isinstance(argv, list) or "--out" not in argv or "--name" not in argv or "--seeds" not in argv:
            raise LaunchRefused("window argv lacks pinned routing")
        if argv[argv.index("--out") + 1] != str(root):
            raise LaunchRefused("window --out drift")
        if argv[argv.index("--name") + 1] != target.name.rsplit("-", 1)[0]:
            raise LaunchRefused("window --name drift")
        if int(argv[argv.index("--seeds") + 1]) != window.get("seed"):
            raise LaunchRefused("window --seeds drift")


def _lock(path: Path):
    try:
        path.mkdir(parents=False)
    except FileExistsError as exc:
        raise LaunchRefused(f"host lock busy: {path}") from exc
    (path / "owner").write_text(f"pid={os.getpid()}\n", encoding="utf-8")


def _require_clean_source(source: Path, expected_head: str | None) -> None:
    if expected_head:
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if actual != expected_head:
            raise LaunchRefused("source HEAD drift")
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True)
    if dirty:
        raise LaunchRefused("source checkout is dirty")


def _verify_binding(plan, expected, *, packet_sha, runner_sha, runner_file):
    if not isinstance(packet_sha, str) or packet_digest(plan, expected) != packet_sha:
        raise LaunchRefused("packet digest drift")
    runner_file = Path(runner_file)
    if runner_file.resolve() != Path(__file__).resolve() or _sha(runner_file) != runner_sha:
        raise LaunchRefused("runner source drift")


def _verify_release(release: Path, launcher: Path):
    if not release.is_file() or release.read_text(encoding="utf-8").strip() != _sha(launcher):
        raise LaunchRefused("RELEASE does not match launcher SHA")


def _verify_artifacts(plan):
    pins = plan.get('artifact_sha256')
    if not isinstance(pins, dict) or not pins:
        raise LaunchRefused('missing runtime artifact pins')
    for name, digest in pins.items():
        path = Path(name)
        if (not path.is_absolute() or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or not path.is_file() or path.is_symlink() or _sha(path) != digest):
            raise LaunchRefused(f'runtime artifact mismatch: {name}')


def _live_group(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _validate_window(target: Path, expected: dict):
    if not target.is_dir():
        raise LaunchRefused("window output directory missing")
    config = target / "config.json"
    summary = target / "summary.json"
    try:
        if json.loads(config.read_text(encoding="utf-8")) != expected:
            raise LaunchRefused("window config drift")
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchRefused("window completion metadata missing") from exc
    # The pinned queue refuses rc0 without complete metadata. Its summary
    # also contains outcomes, so the supervisor only seals those bytes.
    if not summary.is_file() or summary.is_symlink():
        raise LaunchRefused("window summary missing or symlinked")
    wanted = [f"cluster-{i:05}.json" for i in range(520)]
    entries = list(target.iterdir())
    allowed = {"config.json", "summary.json", ".screen.lock", *wanted}
    if any(p.name not in allowed or not p.is_file() or p.is_symlink() for p in entries):
        raise LaunchRefused("window cluster inventory is incomplete or has extras")
    clusters = sorted(p.name for p in entries if p.name.startswith("cluster-"))
    if clusters != wanted:
        raise LaunchRefused("window cluster inventory is incomplete or has extras")


def seal_window(target: Path, expected: dict, seal_path: Path) -> str:
    """Bind completed producer bytes without parsing scientific outcomes."""
    _validate_window(target, expected)
    paths = [target / name for name in ('config.json', 'summary.json')]
    paths += [target / f'cluster-{i:05}.json' for i in range(520)]
    files = {path.name: dict(size=path.stat().st_size, sha256=_sha(path)) for path in paths}
    seal = dict(schema='s58combo-window-seal-v1', output=str(target.resolve()), files=files)
    with seal_path.open('x', encoding='utf-8') as stream:
        json.dump(seal, stream, sort_keys=True)
        stream.write('\n')
    return _sha(seal_path)


def run_plan(plan: dict, expected: dict, *, source: Path, output: Path,
             release: Path, launcher: Path, packet_sha: str | None = None,
             runner_sha: str | None = None, runner_file: Path | None = None,
             hold: Path | None = None,
             host_lock: Path = Path("/root/.claude-host.lock"),
             legacy_locks: tuple[Path, ...] = (),
             runner: tuple[str, ...] = (sys.executable, "-B", "-m", "shengji.train.cwv_screen_queue"),
             dry_run: bool = False) -> dict:
    """Run windows serially, preserving every partial output and refusing retry."""
    source = Path(source); output = Path(output); release = Path(release); launcher = Path(launcher)
    _assert_plan(plan, expected, source, output)
    _require_clean_source(source, plan.get("source_head"))
    if packet_sha is None:
        packet_sha = packet_digest(plan, expected)
    if runner_file is None:
        raise LaunchRefused("runner source path is required")
    if runner_sha is None:
        runner_sha = _sha(Path(runner_file))
    _verify_binding(plan, expected, packet_sha=packet_sha, runner_sha=runner_sha, runner_file=runner_file)
    if launcher.read_text() != render_wrapper(packet_sha, runner_sha):
        raise LaunchRefused("wrapper does not bind this packet and executing runner")
    if (plan.get('host_lock') != str(host_lock) or plan.get('hold') != str(hold)
            or plan.get('legacy_locks') != [str(p) for p in legacy_locks]):
        raise LaunchRefused("guard paths differ from frozen packet")
    wrapper_sha = _sha(launcher)
    _verify_artifacts(plan)
    if hold and hold.exists():
        raise LaunchRefused("HOLD marker present")
    if any(path.exists() for path in legacy_locks):
        raise LaunchRefused("legacy lane lock present")
    if dry_run:
        return {"status": "PACKET_DRYRUN", "packet_sha256": packet_sha,
                "windows": len(plan["windows"]), "release_checked": False}
    _verify_release(release, launcher)
    if output.exists():
        raise LaunchRefused("output root already exists; partial output will not be retried")
    digest = packet_sha
    keep_lock = False
    proc = None
    results = []
    terminal_written = False
    owns_output = False
    _lock(host_lock)
    try:
        # The lock is acquired before reserving the output root.  Any setup
        # failure therefore follows the same ownership/retention path as a
        # dispatch failure.
        output.mkdir(parents=False)
        owns_output = True
        (output / "seals").mkdir()
        (output / "reservation.json").write_text(json.dumps({
            "schema": "s58combo-reservation-v1", "packet_sha256": digest,
            "status": "READOUT_HOLD", "created_at": time.time()}, sort_keys=True) + "\n", encoding="utf-8")
        (output / 'READOUT_HOLD').write_text('Raw outcomes remain closed pending exact reader review and named ownership.\n')
        for window in plan["windows"]:
            if _sha(launcher) != wrapper_sha:
                raise LaunchRefused("launcher changed after admission")
            if hold and hold.exists():
                raise LaunchRefused("HOLD marker appeared before next window")
            _verify_binding(plan, expected, packet_sha=packet_sha, runner_sha=runner_sha, runner_file=runner_file)
            _verify_release(release, launcher)
            _require_clean_source(source, plan["source_head"])
            if any(path.exists() for path in legacy_locks):
                raise LaunchRefused("legacy lane lock appeared before next window")
            target = Path(window["output"])
            if target.exists():
                raise LaunchRefused(f"pre-existing window output: {target}")
            env = _clean_env(plan["arms"][window["side"]], source)
            command = [*runner, *window["argv"]]
            log = output / f"{target.name}.worker.log"
            with log.open("wb") as stream:
                proc = subprocess.Popen(command, cwd=source, env=env, start_new_session=True,
                                        stdout=stream, stderr=subprocess.STDOUT)
                proc.wait()
            if _live_group(proc.pid):
                keep_lock = True
                raise LaunchRefused(f"window process group still live: {target}")
            results.append({"output": str(target), "returncode": proc.returncode})
            if proc.returncode != 0:
                (output / "terminal.json").write_text(json.dumps({"status": "ABORT", "results": results}, sort_keys=True) + "\n", encoding="utf-8")
                terminal_written = True
                raise LaunchRefused(f"window failed: {target} rc={proc.returncode}")
            seal_path = output / "seals" / f"{target.name}.json"
            results[-1]["seal_sha256"] = seal_window(target, expected[window["output"]], seal_path)
        (output / "terminal.json").write_text(json.dumps({"status": "LANE_DONE", "results": results,
                                                            "readout": "HOLD", "packet_sha256": digest,
                                                            "reservation_sha256": _sha(output / "reservation.json")}, sort_keys=True) + "\n", encoding="utf-8")
        terminal_written = True
        return {"status": "LANE_DONE", "packet_sha256": digest, "windows": len(results), "readout": "HOLD"}
    except BaseException:
        if proc is not None and (proc.poll() is None or _live_group(proc.pid)):
            keep_lock = True
        if owns_output and not terminal_written:
            (output / "terminal.json").write_text(json.dumps({
                "status": "INTERRUPTED_LIVE_CHILD" if keep_lock else "INTERRUPTED",
                "child_pid": proc.pid if proc is not None else None, "results": results,
                "readout": "HOLD"}, sort_keys=True) + "\n", encoding="utf-8")
        raise
    finally:
        if not keep_lock:
            owner = host_lock / "owner"
            if owner.is_file() and owner.read_text(encoding="utf-8") == f"pid={os.getpid()}\n":
                owner.unlink()
                host_lock.rmdir()
            else:
                raise LaunchRefused("host lock ownership changed; preserving lock")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--launcher", type=Path, default=Path(__file__))
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument("--packet-sha", required=True)
    parser.add_argument("--runner-sha", required=True)
    parser.add_argument("--runner-file", type=Path, required=True)
    parser.add_argument("--host-lock", type=Path, default=Path("/root/.claude-host.lock"))
    parser.add_argument("--hold", type=Path)
    args = parser.parse_args(argv)
    plan = json.loads(args.packet.read_text()); expected = json.loads(args.expected.read_text())
    output = args.output or Path(plan["windows"][0]["output"]).parent
    print(json.dumps(run_plan(plan, expected, source=args.source, output=output,
                             release=args.release, launcher=args.wrapper,
                             packet_sha=args.packet_sha, runner_sha=args.runner_sha,
                             runner_file=args.runner_file, hold=args.hold,
                             legacy_locks=tuple(Path(value) for value in plan.get("legacy_locks", ())),
                             host_lock=args.host_lock), sort_keys=True))


if __name__ == "__main__":
    main()
