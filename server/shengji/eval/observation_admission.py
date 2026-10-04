"""One-shot M9 owning caller, not a bootstrap or a grant of launch authority.

An authenticated bootstrap must bind these source bytes before import. The
reviewed packet is authenticated again here. No waiting, retries, RELEASE
creation, or scientific-result acceptance. Linux qualification and the actual
worker's runtime check remain mandatory integration gates.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone

from . import observation_queue as guards
from .observation_lease import Lease, file_stamp
from .observation_process import run_observation_process
from .observation_recipe import build_observation_command, validate_recipe
from .observation_runtime import ObservationRuntime, ENVIRONMENT
from .m9_panel_recipe import validate_panel_recipe, build_panel_worker_command


SCHEMA = "m9-admission-v1"
PANEL_SCHEMA = "m9-panel-admission-v1"
HOST_LOCK = Path("/root/.claude-host.lock")
REQUIRED_ANCESTOR = "94350c39b56ff845fcb37e61d27ab72a0fe6abe5"  # merged #729, includes #723–726
READ_RECEIPT_SHA = "431b731d7cd88b5da6126874bad82007d873c12bd70c462ec36e44262d69bf20"
_SYSTEM_SERVICES = {
    ("/usr/bin/python3", "/usr/bin/networkd-dispatcher", "--run-startup-triggers"),
    ("/usr/bin/python3", "/usr/share/unattended-upgrades/unattended-upgrade-shutdown",
     "--wait-for-signal"),
}
_KEYS = {"schema", "recipe", "environment", "source_commit", "hostname", "runtime",
         "watchdog", "read_complete", "queue", "release", "hold", "host_lock",
         "other_locks", "reservation", "status", "claim"}


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def _git(source, *args):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(source),
                             "-c", "core.fsmonitor=false", *args],
                            check=True, capture_output=True, text=True, timeout=10)
    return result.stdout.strip()


def _source(source, commit):
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("exact source commit required")
    if _git(source, "rev-parse", "HEAD") != commit:
        raise ValueError("source commit drift")
    if _git(source, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("clean merged source required")
    _git(source, "merge-base", "--is-ancestor", REQUIRED_ANCESTOR, "HEAD")


def _quiet_host():
    """Conservative Linux census: no foreign Python/known job launcher.

    Ignore only this process and its ancestors, not its descendants. An
    unreadable live process fails closed. Cooperative shared-lock users still
    must obey the lease; this is not adversarial process isolation.
    """
    if not sys.platform.startswith("linux"):
        raise ValueError("Linux host required")
    ancestors = set()
    pid = os.getpid()
    while pid > 0 and pid not in ancestors:
        ancestors.add(pid)
        stat = Path(f"/proc/{pid}/stat").read_text()
        pid = int(stat.rsplit(")", 1)[1].split()[1])
    busy = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal() or int(entry.name) in ancestors:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except FileNotFoundError:
            if entry.exists():
                raise ValueError("live process census incomplete")
            continue
        args = tuple(raw.rstrip(b"\0").decode("utf-8", errors="replace").split("\0"))
        if args in _SYSTEM_SERVICES:
            # The two observed distro services are not experiment workers.
            # Require init ownership as well as their exact argv, not a broad
            # Python or path-prefix exemption.
            parent = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
            if parent == 1:
                continue
        argv = " ".join(args)
        if re.search(r"python|tactical_report|cwv_screen_queue|claude_.*(?:screen|datagen)|--arm", argv):
            busy.append(int(entry.name))
    if busy:
        raise ValueError(f"host has live peer/child processes: {busy}")


def _hash_file(path):
    before = file_stamp(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if file_stamp(path) != before:
        raise ValueError("input changed during hash")
    return digest.hexdigest(), before


def run_packet(packet_path, packet_sha):
    """Consume one authenticated packet after all guards, invoke at most once.

    On any exception after lease acquisition, retain the lease and artifacts.
    A failed/expired child can release only after positive host drain and
    unchanged ownership are checked. Process exit0 never accepts the science.
    """
    return _run_packet(packet_path, packet_sha, panel=False)


def run_panel_packet(packet_path, packet_sha):
    """Dedicated panel admission. No implicit conversion of original packets."""
    return _run_packet(packet_path, packet_sha, panel=True)


def _run_packet(packet_path, packet_sha, *, panel):
    packet_path = guards._canonical_absolute(str(packet_path), "packet")
    guards._strict_sha(packet_sha, "packet SHA")
    raw, stamp = guards._stable_read(packet_path, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != packet_sha:
        raise ValueError("packet SHA mismatch")
    packet = guards._parse_finite_object(raw)
    keys = (_KEYS - {"read_complete"}) | {"timeout_seconds"} if panel else _KEYS
    if set(packet) != keys or packet["schema"] != (PANEL_SCHEMA if panel else SCHEMA):
        raise ValueError("exact M9 packet required")
    recipe = packet["recipe"]
    if panel:
        validate_panel_recipe(recipe)
        timeout = packet["timeout_seconds"]
        if type(timeout) is not int or timeout <= 0:
            raise ValueError("explicit positive integer panel deadline required")
        inner_command = build_panel_worker_command(recipe, str(packet_path), packet_sha)
    else:
        validate_recipe(recipe)
        timeout = recipe["timeout_seconds"]
        inner_command = build_observation_command(recipe)
    source = Path(recipe["source_root"])
    command = (recipe["python"], "-I", "-B",
               str(source / "server/scripts/observation_worker.py"),
               "--packet", str(packet_path), "--sha256", packet_sha)
    if panel:
        command = inner_command
    namespace = "m9-panel" if panel else "m9"
    if (packet["environment"] != ENVIRONMENT or packet["hostname"] != socket.gethostname()
            or Path(recipe["python"]).resolve() != Path(sys.executable).resolve()):
        raise ValueError("host/interpreter/environment binding mismatch")
    _source(source, packet["source_commit"])
    stamps = {packet_path: stamp}
    launcher = source / "server/scripts/observation_worker.py"
    launcher_sha, launcher_stamp = _hash_file(launcher)
    stamps[launcher] = launcher_stamp

    def read_ref(ref, label):
        if type(ref) is not dict or set(ref) != {"path", "sha256"}:
            raise ValueError(f"exact {label} reference required")
        path = guards._canonical_absolute(ref["path"], label)
        guards._strict_sha(ref["sha256"], label)
        data, mark = guards._stable_read(path, 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError(f"{label} hash mismatch")
        stamps[path] = mark
        return path, data

    runtime_path, runtime_raw = read_ref(packet["runtime"], "runtime")
    watchdog, _ = read_ref(packet["watchdog"], "watchdog")
    if not panel:
        read_ref(packet["read_complete"], "read-complete")
        if packet["read_complete"]["sha256"] != READ_RECEIPT_SHA:
            raise ValueError("v49 saved-read-complete witness required")
    inputs = [("model", "model_sha256"), ("fixtures", "fixture_sha256")]
    if panel:
        inputs.append(("saved_readout", "saved_readout_sha256"))
    for key, sha_key in inputs:
        path = guards._canonical_absolute(recipe[key], key)
        digest, mark = _hash_file(path)
        if digest != recipe[sha_key]:
            raise ValueError(f"{key} hash mismatch")
        stamps[path] = mark
    runtime_manifest = guards._parse_finite_object(runtime_raw)
    if runtime_manifest.get("source_root") != str(source / "server"):
        raise ValueError("runtime source binding mismatch")
    runtime = (ObservationRuntime(runtime_manifest, profile="panel") if panel
               else ObservationRuntime(runtime_manifest))
    controls = {key: guards._canonical_absolute(packet[key], key) for key in
                ("release", "hold", "host_lock", "reservation", "status", "claim")}
    if controls["host_lock"] != HOST_LOCK:
        raise ValueError("shared host directory lease required")
    if type(packet["other_locks"]) is not list or not packet["other_locks"]:
        raise ValueError("explicit peer lock paths required")
    other_locks = [guards._canonical_absolute(p, "peer lock") for p in packet["other_locks"]]
    queue_spec = guards.validate_queue_spec(packet["queue"])
    if not panel and not any(r["lane"] == "v49tc" for r in queue_spec["reservations"]):
        raise ValueError("v49 predecessor missing from completed queue")
    if controls["reservation"].parent != Path(queue_spec["reservation_dir"]):
        raise ValueError("own reservation must use shared queue directory")
    output = Path(recipe["output_dir"] if panel else recipe["output"])
    evidence = Path(recipe["evidence"])
    outputs = ([output] if panel else [output, Path(str(output) + ".attempt"),
                                      output.with_name("." + output.name + ".partial")])
    fresh = [*outputs, evidence,
             controls["reservation"], controls["status"], controls["claim"]]
    protected = set(stamps) | {source, Path(recipe["python"]), *other_locks,
                              controls["release"], controls["hold"], controls["host_lock"]}
    for record in queue_spec["reservations"]:
        for key in ("path", "launcher", "status"):
            protected.add(Path(record[key]))
        data, _ = guards._stable_read(Path(record["path"]), 65536)
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("queue reservation drift")
        reservation = guards._parse_finite_object(data)
        for key in ("output", "output_root"):
            if key in reservation:
                protected.add(guards._canonical_absolute(reservation[key], "peer output"))
    for i, path in enumerate(fresh):
        guards._canonical_absolute(str(path), "fresh artifact")
        if os.path.lexists(path) or not path.parent.is_dir():
            raise ValueError("fresh artifact with existing parent required")
        if any(_overlap(path, p) for p in protected | set(fresh[i + 1:])):
            raise ValueError("fresh artifact overlaps protected path")
        if path != controls["reservation"] and _overlap(path, Path(queue_spec["reservation_dir"])):
            raise ValueError("fresh artifact overlaps queue directory")
    expected_release = {"schema": f"{namespace}-release-v1", "packet_sha256": packet_sha}

    def still_fresh(excluded=()):
        for path in fresh:
            if path not in excluded and (os.path.lexists(path) or not path.parent.is_dir()):
                raise ValueError("fresh artifact changed before dispatch")

    def checks():
        if os.path.lexists(controls["hold"]) or any(os.path.lexists(p) for p in other_locks):
            raise ValueError("HOLD or peer lock present")
        if not guards.guard_release(controls["release"], expected_release):
            raise ValueError("exact RELEASE missing or changed")
        if any(file_stamp(path) != mark for path, mark in stamps.items()) or not runtime.check():
            raise ValueError("pinned input/runtime drift")
        _source(source, packet["source_commit"])
        _quiet_host()

    checks()
    queue = guards.capture_queue(queue_spec)
    if os.path.lexists(controls["host_lock"]):
        raise ValueError("host lease busy before claim")
    claim = {
        "schema": f"{namespace}-owner-attempt-v1", "packet_sha256": packet_sha,
        "status": "spent_no_retry", "comparison_validated": False,
        "owner_pid": os.getpid(),
        "inner_command": list(inner_command),
    }
    if panel:
        claim["queue_snapshot"] = queue
    guards.write_exclusive_json(controls["claim"], claim)
    stamps[controls["claim"]] = file_stamp(controls["claim"])
    lease = Lease(controls["host_lock"], f"{namespace} {os.getpid()} {packet_sha}\n")
    if not lease.acquire():
        raise ValueError("host lease busy; packet spent")
    # No unconditional finally-release: an ambiguous child/ownership failure
    # retains the lease for investigation, never exposes a possibly busy host.
    checks()
    still_fresh((controls["claim"],))
    if not lease.check() or not guards.queue_unchanged(queue_spec, queue):
        raise ValueError("admission changed under lease")
    guards.write_exclusive_json(controls["reservation"], {
        "schema": f"codex-{namespace}-reservation-v1", "lane": namespace,
        "launcher": str(launcher), "launcher_sha256": launcher_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "packet_sha256": packet_sha, "pid": os.getpid(),
        "output": str(output if panel else output.parent),
        "output_root": str(output if panel else output.parent),
        "result": str(output), "evidence": str(evidence),
        "status": str(controls["status"]), "count": 15 if panel else 12, "seeds": [0, 1, 2],
        "seed_kind": "observation-world seeds, not generated-deal windows",
    })
    own = {"path": str(controls["reservation"]),
           "stamp": list(file_stamp(controls["reservation"]))}
    checks()
    still_fresh((controls["claim"], controls["reservation"]))
    if not lease.check() or not guards.queue_unchanged(queue_spec, queue, owned_record=own):
        raise ValueError("reservation/lease changed before dispatch")
    result = run_observation_process(command, workspace=source / "server",
                                     env=dict(packet["environment"]), watchdog_script=watchdog,
                                     timeout_seconds=timeout, evidence=evidence)
    checks()  # includes positive no-peer/no-child census, not merely exit0
    if (not lease.check() or not guards.queue_unchanged(queue_spec, queue, owned_record=own)
            or type(result.get("returncode")) is not int
            or result.get("status") not in {"exited", "failed", "timeout"}):
        raise ValueError("child drain/lease/queue unconfirmed; lease retained")
    guards.write_exclusive_json(controls["status"], {
        "schema": f"{namespace}-owner-terminal-v1", "packet_sha256": packet_sha,
        "process_status": result["status"], "returncode": result["returncode"],
        "utc": datetime.now(timezone.utc).isoformat(), "comparison_validated": False,
    })
    if not lease.release():
        raise ValueError("owned lease release failed")
    return result
