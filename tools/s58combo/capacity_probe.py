"""Bounded, score-free heavy-path rehearsal for a frozen screen packet.

This is a host qualification helper, not a screen launcher.  It runs one
small queue per arm with fourteen clusters and records only process/resource
metadata.  Screen seeds and scientific outputs are deliberately excluded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import re
import socket
import subprocess
import time

from launcher import LaunchRefused, _clean_env, _live_group, _lock, _require_clean_source
from launcher import _verify_artifacts
from shengji.train.screen_deadline import RECIPE as DEADLINE_RECIPE


WORKERS = 14
CLUSTERS = 14
MAX_RSS_KIB = 24 * 1024 * 1024
REHEARSAL_SEEDS = (701_001, 801_001, 901_001, 1_001_001)
FORBIDDEN_SCREEN_BASE = 230_060_910
SCREEN_WINDOWS = tuple((FORBIDDEN_SCREEN_BASE + index * 100_000,
                        FORBIDDEN_SCREEN_BASE + index * 100_000 + CLUSTERS)
                       for index in range(10))


def build_rehearsal_commands(plan: dict, *, output: Path,
                             seeds=REHEARSAL_SEEDS, workers: int = WORKERS,
                             clusters: int = CLUSTERS) -> list[dict]:
    """Build exactly one score-free queue command per arm.

    The seed values are fixed engineering witnesses and are refused if they
    overlap the proposed screen interval.  They are never added to the screen
    reservation registry by this module.
    """
    if type(workers) is not int or workers != WORKERS:
        raise ValueError("capacity rehearsal is pinned to 14 workers")
    if type(clusters) is not int or clusters != CLUSTERS:
        raise ValueError("capacity rehearsal is pinned to 14 clusters")
    if len(seeds) != 4 or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError("four nonnegative queue seeds required")
    ordered = sorted(seeds)
    if any(right < left + CLUSTERS for left, right in zip(ordered, ordered[1:])):
        raise ValueError("capacity seed windows overlap")
    if any(seed < end and seed + CLUSTERS > start
           for seed in seeds for start, end in SCREEN_WINDOWS):
        raise ValueError("rehearsal seed overlaps proposed screen interval")
    root = Path(output).resolve()
    arms = plan.get("arms")
    if not isinstance(arms, dict) or set(arms) != {"candidate", "comparator"}:
        raise ValueError("plan must carry candidate and comparator arms")
    commands = []
    kinds = ("first", "fixed_banker")
    for index, (side, kind, seed) in enumerate(zip(
            ("candidate", "candidate", "comparator", "comparator"),
            ("first", "fixed_banker", "first", "fixed_banker"), seeds, strict=True)):
        arm = arms[side]
        name = arm.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("arm identity missing")
        target = root / f"capacity-{side}-{kind}-{seed}"
        ranks = "2" if kind == "first" else "2,3,4,5,6,7,8,9,10,J,Q,K,A"
        commands.append({
            "side": side, "kind": kind, "seed": seed, "output": str(target),
            "argv": ["--arm-policy", name, "--out", str(root),
                     "--name", f"capacity-{side}-{kind}", "--workers", str(workers),
                     "--clusters", str(clusters), "--seeds", str(seed),
                     "--decision-deadline", "300", "--trump-ranks",
                     ranks, "--round-kind", kind],
        })
    return commands


def run_rehearsal(plan: dict, *, source: Path, output: Path,
                  host_lock: Path, hold: Path | None = None,
                  legacy_locks: tuple[Path, ...] = (),
                  seeds=REHEARSAL_SEEDS,
                  runner=(os.sys.executable, "-B", "-m", "shengji.train.cwv_screen_queue")) -> dict:
    """Run the two bounded queues and return score-free metadata.

    No retry or child termination is attempted.  A live child preserves the
    host lock and output for operator recovery; a failed child leaves a typed
    failure record.  The function is intentionally not called by tests.
    """
    source, output, host_lock = Path(source), Path(output), Path(host_lock)
    if socket.gethostname() != plan.get("host_identity", {}).get("hostname"):
        raise LaunchRefused("capacity host identity mismatch")
    if output.exists():
        raise LaunchRefused("capacity output already exists; no retry")
    if hold and hold.exists():
        raise LaunchRefused("HOLD marker present")
    if plan.get("source_path") != str(source.resolve()):
        raise LaunchRefused("capacity source path drift")
    if not isinstance(plan.get("source_head"), str) or not re.fullmatch(r"[0-9a-f]{40}", plan["source_head"]):
        raise LaunchRefused("capacity source head is not pinned")
    if plan.get("host_lock") != str(host_lock) or plan.get("hold") != str(hold):
        raise LaunchRefused("capacity guard path drift")
    if plan.get("legacy_locks") != [str(path) for path in legacy_locks]:
        raise LaunchRefused("capacity legacy guard drift")
    _verify_artifacts(plan)
    _require_clean_source(source, plan["source_head"])
    commands = build_rehearsal_commands(plan, output=output, seeds=seeds)
    _lock(host_lock)
    owns_output = False
    process = None
    metadata = {"schema": "s58combo-capacity-rehearsal-v1", "status": "RUNNING",
                "host": socket.gethostname(), "workers": WORKERS,
                "clusters_per_arm": CLUSTERS, "arms": [], "max_rss_aggregate_kib": 0,
                "maxrss_note": "aggregate process-tree RSS sampled from ps; getrusage maxrss is per child",
                "completed_queues": 0, "complete": False}
    def write_progress():
        temporary = output / ".capacity.json.tmp"
        temporary.write_text(json.dumps(metadata, sort_keys=True) + "\n")
        temporary.replace(output / "capacity.json")

    def sample_tree_rss(pid):
        result = subprocess.run(["ps", "-eo", "pid=,ppid=,rss="], text=True,
                                capture_output=True, check=True)
        rows = {}
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) != 3:
                continue
            try:
                rows[int(fields[0])] = (int(fields[1]), int(fields[2]))
            except ValueError:
                continue
        descendants = {pid}
        changed = True
        while changed:
            changed = False
            for child, (parent, _) in rows.items():
                if parent in descendants and child not in descendants:
                    descendants.add(child); changed = True
        return sum(rows[item][1] for item in descendants if item in rows)

    def wait_with_progress(proc, command):
        peak = 0
        samples = 0
        peak = max(peak, sample_tree_rss(proc.pid)); samples += 1
        next_heartbeat = started + 10
        while True:
            try:
                rc = proc.wait(timeout=1)
                peak = max(peak, sample_tree_rss(proc.pid)); samples += 1
                return rc, peak, samples
            except subprocess.TimeoutExpired:
                peak = max(peak, sample_tree_rss(proc.pid))
                samples += 1
                now = time.monotonic()
                if now < next_heartbeat:
                    continue
                metadata["active_arm"] = command["side"]
                metadata["active_kind"] = command["kind"]
                metadata["active_elapsed_seconds"] = now - started
                metadata["active_process_tree_rss_kib"] = peak
                metadata["active_rss_samples"] = samples
                target = Path(command["output"])
                metadata["active_cluster_files"] = sum(
                    1 for path in target.glob("cluster-*")
                    if path.is_file() and not path.is_symlink()) if target.is_dir() else 0
                metadata["max_rss_aggregate_kib"] = max(metadata["max_rss_aggregate_kib"], peak)
                write_progress()
                next_heartbeat = now + 10
    try:
        output.mkdir(parents=False)
        owns_output = True
        (output / "logs").mkdir()
        (output / "READOUT_HOLD").write_text("Capacity metadata only; scientific outcomes remain closed.\n")
        if any(path.exists() for path in legacy_locks):
            raise LaunchRefused("legacy lane lock present")
        write_progress()
        for command in commands:
            if hold and hold.exists():
                raise LaunchRefused("HOLD marker appeared before next arm")
            if any(path.exists() for path in legacy_locks):
                raise LaunchRefused("legacy lane lock appeared before next arm")
            _require_clean_source(source, plan["source_head"])
            _verify_artifacts(plan)
            env = _clean_env(plan["arms"][command["side"]], source)
            if env.get("SHENGJI_FAST") not in ("0", "1"):
                raise LaunchRefused("capacity engine mode is not pinned")
            log_path = output / "logs" / f"{command['side']}-{command['kind']}.log"
            started = time.monotonic()
            usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
            with log_path.open("wb") as stream:
                process = subprocess.Popen([*runner, *command["argv"]], cwd=source,
                                           env=env, start_new_session=True,
                                           stdout=stream, stderr=subprocess.STDOUT)
                returncode, peak_rss, rss_samples = wait_with_progress(process, command)
            if _live_group(process.pid):
                raise LaunchRefused(f"capacity child group still live: {command['side']}")
            usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            entry = {"side": command["side"], "kind": command["kind"], "seed": command["seed"],
                     "returncode": returncode, "elapsed_seconds": time.monotonic() - started,
                     "user_seconds": usage_after.ru_utime - usage_before.ru_utime,
                     "system_seconds": usage_after.ru_stime - usage_before.ru_stime,
                     "maxrss_child_kib": usage_after.ru_maxrss,
                     "maxrss_tree_peak_kib": peak_rss, "rss_samples": rss_samples}
            metadata["max_rss_aggregate_kib"] = max(metadata["max_rss_aggregate_kib"], peak_rss)
            if peak_rss <= 0 or rss_samples == 0:
                metadata["status"] = "FAILED"
                write_progress()
                raise LaunchRefused("capacity process tree RSS was not sampled")
            if peak_rss > MAX_RSS_KIB:
                metadata["status"] = "FAILED"
                write_progress()
                raise LaunchRefused("capacity process tree exceeds 24 GiB")
            metadata["arms"].append(entry)
            if returncode != 0:
                metadata["status"] = "FAILED"
                (output / "capacity.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")
                raise LaunchRefused(f"capacity arm failed: {command['side']} rc={returncode}")
            config_path = Path(command["output"]) / "config.json"
            if not config_path.is_file() or config_path.is_symlink():
                raise LaunchRefused(f"capacity config missing: {command['side']}")
            config = json.loads(config_path.read_text())
            arm = plan["arms"][command["side"]]
            expected_config = {
                "arm_policy": arm["name"],
                "arm_policy_identity": arm["identity"],
                "seed0": command["seed"], "clusters": CLUSTERS,
                "trump_ranks": ["2"] if command["kind"] == "first"
                    else "2,3,4,5,6,7,8,9,10,J,Q,K,A".split(","),
                "round_kind": command["kind"], "decision_deadline": DEADLINE_RECIPE,
            }
            if (config.get("round_kind", "first") != expected_config["round_kind"]
                    or any(config.get(key) != expected for key, expected in expected_config.items()
                           if key != "round_kind")):
                raise LaunchRefused(f"capacity config arm mismatch: {command['side']}")
            target = Path(command["output"])
            wanted = {f"cluster-{index:05}.json" for index in range(CLUSTERS)}
            cluster_files = [path for path in target.iterdir()
                             if path.name.startswith("cluster-") and path.is_file() and not path.is_symlink()]
            entry["complete"] = True
            entry["completed_clusters"] = CLUSTERS
            entry["cluster_files"] = len(cluster_files)
            if (entry["cluster_files"] != CLUSTERS
                    or {path.name for path in cluster_files} != wanted):
                metadata["status"] = "FAILED"
                (output / "capacity.json").write_text(json.dumps(metadata, sort_keys=True) + "\n")
                raise LaunchRefused(f"capacity arm incomplete: {command['side']}")
            metadata["completed_queues"] += 1
            for key in ("active_arm", "active_kind", "active_elapsed_seconds", "active_process_tree_rss_kib", "active_cluster_files"):
                metadata.pop(key, None)
            write_progress()
        metadata["status"] = "COMPLETE"
        metadata["complete"] = True
        metadata.pop("active_arm", None)
        write_progress()
        return metadata
    except BaseException:
        live = process is not None and (process.poll() is None or _live_group(process.pid))
        if owns_output and metadata.get("status") != "FAILED":
            metadata["status"] = "INTERRUPTED_LIVE_CHILD" if live else "INTERRUPTED"
            metadata["child_pid"] = process.pid if process is not None else None
            write_progress()
        raise
    finally:
        if not (process is not None and (process.poll() is None or _live_group(process.pid))):
            owner = host_lock / "owner"
            if owner.is_file() and owner.read_text() == f"pid={os.getpid()}\n":
                owner.unlink(); host_lock.rmdir()

