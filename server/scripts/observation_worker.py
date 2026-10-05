"""The authenticated, one-shot M9 observation worker.

This file deliberately starts as a standard-library-only bootstrap.  Packet
and application bytes are authenticated before the Shengji package is put on
``sys.path``; the imported runtime adapter then performs its stronger import
and dependency checks. Worker mode never starts a child process or retries;
explicit ``--admit`` mode delegates to the guarded owning caller.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sys
import time


_MAX_PACKET_BYTES = 1024 * 1024
_MAX_RUNTIME_BYTES = 1024 * 1024
_MAX_CLAIM_BYTES = 64 * 1024
_PACKET_SCHEMA = "m9-admission-v1"
_PACKET_KEYS = frozenset({
    "schema", "recipe", "environment", "source_commit", "hostname", "runtime",
    "watchdog", "read_complete", "queue", "release", "hold", "host_lock",
    "other_locks", "reservation", "status", "claim",
})
_PANEL_PACKET_SCHEMA = "m9-panel-admission-v1"
_PANEL_PACKET_KEYS = frozenset((*(_PACKET_KEYS - {"read_complete"}),
                                "timeout_seconds", "process_timeout_seconds"))
_CLAIM_KEYS = frozenset({
    "schema", "packet_sha256", "status", "comparison_validated", "owner_pid",
    "inner_command",
})
_SOURCE_SUFFIXES = {".py", ".so"}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(token):
    raise ValueError(f"nonfinite JSON constant: {token}")


def _finite_float(token):
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _parse_object(raw: bytes):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_reject_constant, parse_float=_finite_float)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("strict finite JSON object required") from exc
    if type(value) is not dict:
        raise ValueError("strict finite JSON object required")
    return value


def _nonsymlink_ancestry(path: Path) -> bool:
    try:
        return all(not part.is_symlink() for part in (path, *path.parents))
    except OSError:
        return False


def _canonical_absolute(value, label: str) -> Path:
    if type(value) is not str or not value or not value.startswith("/") \
            or value.startswith("//") or "\x00" in value:
        raise ValueError(f"{label} must be a canonical absolute path")
    path = Path(value)
    if str(path) != value or ".." in path.parts or not _nonsymlink_ancestry(path):
        raise ValueError(f"{label} must be a canonical absolute path")
    return path


def _strict_sha(value, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _stamp(path: Path):
    if (not _nonsymlink_ancestry(path) or path.is_symlink()
            or not path.exists()):
        raise ValueError(f"regular nonsymlink path required: {path}")
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _stable_read(path: Path, limit: int):
    before = _stamp(path)
    if before[2] > limit or not path.is_file():
        raise ValueError(f"bounded regular file required: {path}")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    after = _stamp(path)
    if len(raw) > limit or before != after:
        raise ValueError(f"file changed during bounded read: {path}")
    return raw, after


def _sha_file(path: Path) -> str:
    before = _stamp(path)
    if not path.is_file():
        raise ValueError(f"regular file required: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if _stamp(path) != before:
        raise ValueError(f"file changed during hash: {path}")
    return digest.hexdigest()


def _repository_root() -> Path:
    script = Path(__file__).resolve(strict=True)
    return script.parents[2]


def _read_packet(packet_path, packet_sha, *, panel=False):
    path = _canonical_absolute(packet_path, "packet")
    _strict_sha(packet_sha, "packet SHA")
    raw, _ = _stable_read(path, _MAX_PACKET_BYTES)
    if hashlib.sha256(raw).hexdigest() != packet_sha:
        raise ValueError("packet SHA mismatch")
    packet = _parse_object(raw)
    expected_keys = _PANEL_PACKET_KEYS if panel else _PACKET_KEYS
    expected_schema = _PANEL_PACKET_SCHEMA if panel else _PACKET_SCHEMA
    if set(packet) != expected_keys or packet.get("schema") != expected_schema:
        raise ValueError("exact M9 packet required")
    return path, packet


def _source_inventory(source: Path):
    found = {}
    for name in ("shengji", "scripts"):
        folder = source / name
        if (not folder.is_dir() or folder.is_symlink()
                or not _nonsymlink_ancestry(folder)):
            raise ValueError("missing application source directory")
        for path in folder.rglob("*"):
            if path.is_symlink():
                raise ValueError("symlink in source inventory")
            if path.suffix == ".pyc":
                raise ValueError("stale source bytecode forbidden")
            if path.is_file() and path.suffix in _SOURCE_SUFFIXES:
                relative = path.relative_to(source).as_posix()
                found[relative] = path
    return found


def _declared_relative_path(value):
    if (type(value) is not str or not value or value.startswith("/")
            or "\\" in value or "\x00" in value):
        raise ValueError("source file path must be relative POSIX path")
    path = Path(value)
    if (str(path) != value or ".." in path.parts or "." in path.parts
            or path.parts[0] not in {"shengji", "scripts"}
            or path.suffix not in _SOURCE_SUFFIXES):
        raise ValueError("source file path is outside application inventory")
    return value


def _verify_source_files(manifest, source: Path) -> None:
    declared = manifest.get("source_files")
    if type(declared) is not dict:
        raise ValueError("runtime source file map required")
    actual = _source_inventory(source)
    normalized = {}
    for relative, digest in declared.items():
        normalized[_declared_relative_path(relative)] = _strict_sha(
            digest, f"source file {relative}")
    if set(normalized) != set(actual):
        raise ValueError("runtime source file set mismatch")
    before = {relative: _stamp(path) for relative, path in actual.items()}
    for relative, path in actual.items():
        if _sha_file(path) != normalized[relative]:
            raise ValueError(f"runtime source hash mismatch: {relative}")
    after = _source_inventory(source)
    if set(after) != set(actual) or any(_stamp(after[key]) != before[key]
                                        for key in actual):
        raise ValueError("runtime source drift")


def _read_runtime(packet, source: Path):
    reference = packet.get("runtime")
    if type(reference) is not dict or set(reference) != {"path", "sha256"}:
        raise ValueError("exact runtime reference required")
    path = _canonical_absolute(reference["path"], "runtime")
    digest = _strict_sha(reference["sha256"], "runtime SHA")
    raw, _ = _stable_read(path, _MAX_RUNTIME_BYTES)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("runtime hash mismatch")
    manifest = _parse_object(raw)
    if manifest.get("source_root") != str(source):
        raise ValueError("runtime source binding mismatch")
    _verify_source_files(manifest, source)
    return manifest


def _import_application(server: Path, *, panel=False):
    # This is the first point at which importing Shengji is permitted.
    import importlib

    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    recipe = importlib.import_module("shengji.eval.observation_recipe")
    runtime = importlib.import_module("shengji.eval.observation_runtime")
    guards = importlib.import_module("shengji.eval.observation_queue")
    tactical = importlib.import_module("scripts.tactical_report")
    if panel:
        recipe = importlib.import_module("shengji.eval.m9_panel_recipe")
        panel_execution = importlib.import_module("shengji.eval.m9_panel_execution")
        return recipe, runtime, guards, tactical, panel_execution
    return recipe, runtime, guards, tactical


def _verify_claim_and_controls(packet, packet_sha, guards, *, panel=False,
                               packet_path=None):
    if panel:
        from shengji.eval.m9_panel_recipe import build_panel_worker_command
    else:
        from shengji.eval.observation_recipe import build_observation_command
    controls = {}
    for key in ("release", "hold", "host_lock", "reservation", "status", "claim"):
        controls[key] = _canonical_absolute(packet[key], key)
    if controls["host_lock"] != Path("/root/.claude-host.lock"):
        raise ValueError("shared host directory lease required")
    other_locks = packet["other_locks"]
    if type(other_locks) is not list or not other_locks:
        raise ValueError("explicit peer lock paths required")
    other_locks = [_canonical_absolute(path, "peer lock") for path in other_locks]
    if panel:
        controls["_other_locks"] = other_locks

    claim_raw, claim_stamp = _stable_read(controls["claim"], _MAX_CLAIM_BYTES)
    claim = _parse_object(claim_raw)
    claim_keys = _CLAIM_KEYS | ({"queue_snapshot", "deadline_monotonic"} if panel else set())
    claim_schema = "m9-panel-owner-attempt-v1" if panel else "m9-owner-attempt-v1"
    if (set(claim) != claim_keys or claim.get("schema") != claim_schema
            or claim.get("packet_sha256") != packet_sha
            or claim.get("status") != "spent_no_retry"
            or claim.get("comparison_validated") is not False):
        raise ValueError("strict spent owner claim required")
    if panel:
        if packet_path is None:
            raise ValueError("panel packet path required for owner command")
        expected_command = build_panel_worker_command(
            packet["recipe"], str(packet_path), packet_sha)
    else:
        expected_command = build_observation_command(packet["recipe"])
    if claim["inner_command"] != list(expected_command):
        raise ValueError("owner inner command mismatch")
    owner_pid = claim.get("owner_pid")
    if type(owner_pid) is not int or owner_pid <= 0:
        raise ValueError("strict positive owner pid required")
    try:
        os.kill(owner_pid, 0)
    except PermissionError:
        pass
    except (ProcessLookupError, OSError) as exc:
        raise ValueError("owner process is stale") from exc

    if os.path.lexists(controls["hold"]) \
            or any(os.path.lexists(path) for path in other_locks):
        raise ValueError("HOLD or peer lock present")
    release_schema = "m9-panel-release-v1" if panel else "m9-release-v1"
    if not guards.guard_release(
            controls["release"], {"schema": release_schema, "packet_sha256": packet_sha}):
        raise ValueError("exact RELEASE missing or changed")

    host_lock = controls["host_lock"]
    if (not host_lock.is_dir() or host_lock.is_symlink()
            or not _nonsymlink_ancestry(host_lock)):
        raise ValueError("host lock must be a regular directory")
    owner = host_lock / "owner"
    if (set(host_lock.iterdir()) != {owner} or owner.is_symlink()
            or not owner.is_file()):
        raise ValueError("host lock owner file required")
    lock_before = _stamp(host_lock)
    owner_raw, _ = _stable_read(owner, 256)
    try:
        owner_text = owner_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("host lock owner is not UTF-8") from exc
    owner_prefix = "m9-panel" if panel else "m9"
    if owner_text != f"{owner_prefix} {owner_pid} {packet_sha}\n":
        raise ValueError("host lock owner mismatch")
    if _stamp(host_lock) != lock_before:
        raise ValueError("host lock changed during verification")
    if panel:
        controls["_claim"] = claim
        controls["_claim_stamp"] = list(claim_stamp)
    return controls


def _bootstrap(packet_path, packet_sha, *, panel=False):
    """Authenticate all application bytes using only the standard library."""
    if panel:
        _, packet = _read_packet(packet_path, packet_sha, panel=True)
    else:
        # Keep the historical two-argument call shape for test/adaptor users.
        _, packet = _read_packet(packet_path, packet_sha)
    repo = _repository_root()
    recipe_value = packet.get("recipe")
    if type(recipe_value) is not dict or recipe_value.get("source_root") != str(repo):
        raise ValueError("recipe source is not this repository")
    server = repo / "server"
    runtime_manifest = _read_runtime(packet, server)
    return packet, server, runtime_manifest


def _import_owner(server: Path, *, panel=False):
    import importlib

    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    return importlib.import_module("shengji.eval.observation_admission")


def run_owner_packet(packet_path, packet_sha, *, panel=False):
    """Bootstrap the owning caller; this does not create RELEASE or skip guards."""
    if panel:
        _, server, _ = _bootstrap(packet_path, packet_sha, panel=True)
        owner = _import_owner(server)
        return owner.run_panel_packet(packet_path, packet_sha)
    _, server, _ = _bootstrap(packet_path, packet_sha)
    owner = _import_owner(server)
    return owner.run_packet(packet_path, packet_sha)


def run_packet(packet_path, packet_sha):
    """Authenticate and invoke one fixed tactical report in this process."""
    packet, server, runtime_manifest = _bootstrap(packet_path, packet_sha)
    recipe_value = packet["recipe"]

    recipe, runtime_adapter, guards, tactical = _import_application(server)
    recipe.validate_recipe(recipe_value)
    if Path(str(recipe_value["python"])).resolve() != Path(sys.executable).resolve():
        raise ValueError("worker interpreter mismatch")
    fixtures = _canonical_absolute(recipe_value["fixtures"], "fixtures")
    if _sha_file(fixtures) != recipe_value["fixture_sha256"]:
        raise ValueError("fixture hash mismatch")
    runtime = runtime_adapter.ObservationRuntime(runtime_manifest)
    if not runtime.check():
        raise ValueError("runtime changed during worker admission")
    controls = _verify_claim_and_controls(packet, packet_sha, guards)

    command = recipe.build_observation_command(recipe_value)
    original_argv = sys.argv
    try:
        sys.argv = list(command[3:])
        tactical.main()
    finally:
        sys.argv = original_argv


def _panel_reservation(controls, packet, packet_sha, owner_pid, recipe):
    """Read and bind the owner's reservation without importing application code."""
    raw, stamp = _stable_read(controls["reservation"], _MAX_CLAIM_BYTES)
    record = _parse_object(raw)
    if (type(record) is not dict
            or record.get("schema") != "codex-m9-panel-reservation-v1"
            or record.get("lane") != "m9-panel"
            or record.get("packet_sha256") != packet_sha
            or record.get("pid") != owner_pid
            or record.get("output_root") != recipe["output_dir"]
            or record.get("count") != 15
            or record.get("status") != str(controls["status"])):
        raise ValueError("panel reservation binding mismatch")
    return {"path": str(controls["reservation"]), "stamp": list(stamp)}


def run_panel_packet(packet_path, packet_sha):
    """Authenticate and run one admitted fixed panel in this process."""
    started = time.monotonic()
    packet, server, runtime_manifest = _bootstrap(packet_path, packet_sha, panel=True)
    packet_path = _canonical_absolute(str(packet_path), "packet")
    recipe_value = packet["recipe"]
    recipe, runtime_adapter, guards, _tactical, panel_execution = _import_application(
        server, panel=True)
    recipe.validate_panel_recipe(recipe_value)
    if Path(str(recipe_value["python"])).resolve() != Path(sys.executable).resolve():
        raise ValueError("panel interpreter mismatch")
    if packet.get("hostname") != socket.gethostname():
        raise ValueError("panel hostname mismatch")
    if packet.get("environment") != runtime_adapter.ENVIRONMENT:
        raise ValueError("panel environment mismatch")
    timeout = packet.get("timeout_seconds")
    if type(timeout) is not int or timeout <= 0:
        raise ValueError("panel timeout_seconds must be a strict positive integer")
    process_timeout = packet.get("process_timeout_seconds")
    if type(process_timeout) is not int or process_timeout <= timeout:
        raise ValueError("panel process timeout must exceed inner deadline")

    controls = _verify_claim_and_controls(
        packet, packet_sha, guards, panel=True, packet_path=packet_path)
    owner_pid = controls["_claim"]["owner_pid"]
    deadline = controls["_claim"].get("deadline_monotonic")
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or deadline <= 0 or deadline > started + timeout):
        raise ValueError("owner-bound monotonic panel deadline required")
    own = _panel_reservation(controls, packet, packet_sha, owner_pid, recipe_value)
    queue_spec = guards.validate_queue_spec(packet["queue"])
    if controls["reservation"].parent != Path(queue_spec["reservation_dir"]):
        raise ValueError("panel reservation must use shared queue directory")
    snapshot = controls["_claim"].get("queue_snapshot")
    if not guards.queue_unchanged(queue_spec, snapshot, owned_record=own):
        raise ValueError("panel queue changed before body")

    packet_stamp = list(_stamp(packet_path))
    release_stamp = list(_stamp(controls["release"]))
    claim_stamp = controls["_claim_stamp"]
    reservation_stamp = own["stamp"]
    host_lock = controls["host_lock"]
    host_owner = host_lock / "owner"
    lock_stamp = list(_stamp(host_lock))
    owner_stamp = list(_stamp(host_owner))
    expected_release = {"schema": "m9-panel-release-v1", "packet_sha256": packet_sha}
    expected_owner = f"m9-panel {owner_pid} {packet_sha}\n"

    def check_admission():
        try:
            if list(_stamp(packet_path)) != packet_stamp:
                raise ValueError("panel packet changed")
            if os.path.lexists(controls["hold"]):
                raise ValueError("HOLD or peer lock present")
            if any(os.path.lexists(path) for path in controls["_other_locks"]):
                raise ValueError("HOLD or peer lock present")
            if list(_stamp(controls["release"])) != release_stamp or not guards.guard_release(
                    controls["release"], expected_release):
                raise ValueError("panel RELEASE changed")
            if list(_stamp(controls["claim"])) != claim_stamp:
                raise ValueError("panel claim changed")
            try:
                os.kill(owner_pid, 0)
            except PermissionError:
                pass
            except (ProcessLookupError, OSError) as exc:
                raise ValueError("panel owner process is stale") from exc
            if list(_stamp(controls["reservation"])) != reservation_stamp:
                raise ValueError("panel reservation changed")
            if os.path.lexists(controls["status"]):
                raise ValueError("panel terminal status appeared")
            if (list(_stamp(host_lock)) != lock_stamp
                    or list(_stamp(host_owner)) != owner_stamp
                    or host_owner.read_text(encoding="utf-8") != expected_owner):
                raise ValueError("panel host lease changed")
            if not guards.queue_unchanged(queue_spec, snapshot, owned_record=own):
                raise ValueError("panel queue changed")
            return True
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("panel admission control unreadable") from exc

    def check_budget():
        if time.monotonic() >= deadline:
            raise TimeoutError("panel deadline exceeded")

    return panel_execution.run_panel_body(
        recipe_value, runtime_manifest,
        check_admission=check_admission, check_budget=check_budget)


def qualify_panel_runtime(packet_path, packet_sha, *, destination=None):
    """Model-free qualification using the actual child worker entrypoint.

    The input packet authenticates the source via its pinned existing runtime
    manifest. Capture may replace entrypoint-bound dependency identity, never
    application bytes/environment. Verification uses the packet's manifest.
    No owner, queue, claim, RELEASE, fixture or model code is invoked here.
    A qualified manifest is preparation, not permission to collect a panel.
    """
    _packet, server, baseline = _bootstrap(packet_path, packet_sha, panel=True)
    target = None
    if destination is not None:
        target = _canonical_absolute(str(destination), "qualification output")
        if target.is_relative_to(server.parent):
            raise ValueError("qualification output must be outside the source checkout")
        if target.exists():
            raise ValueError("qualification output exists; preserve it")
    _recipe, adapter, _guards, _tactical, _execution = _import_application(server, panel=True)
    if target is None:
        runtime = adapter.ObservationRuntime(baseline, profile="panel")
        if not runtime.check():
            raise ValueError("panel worker runtime verification failed")
        print("PANEL WORKER RUNTIME VERIFIED; no model or claim access", flush=True)
        return
    manifest = adapter.capture(server, profile="panel")
    for key in ("source_root", "source_files", "environment"):
        if manifest[key] != baseline[key]:
            raise ValueError("qualified application changed: " + key)
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    with target.open("xb") as handle:
        handle.write(raw)
    print("PANEL WORKER RUNTIME CAPTURED sha256=" + hashlib.sha256(raw).hexdigest(), flush=True)


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--admit", action="store_true",
                        help="bootstrap the owning caller; exact RELEASE and all admission guards required")
    parser.add_argument("--panel", action="store_true",
                        help="use the authenticated fixed M9 panel packet and child")
    qualification = parser.add_mutually_exclusive_group()
    qualification.add_argument("--capture-panel-runtime", metavar="OUTPUT",
                               help="model-free capture through this child entrypoint")
    qualification.add_argument("--verify-panel-runtime", action="store_true",
                               help="model-free verification of the packet runtime")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.capture_panel_runtime is not None or args.verify_panel_runtime:
        if not args.panel or args.admit:
            parser.error("runtime qualification requires --panel and forbids --admit")
        qualify_panel_runtime(args.packet, args.sha256,
                              destination=args.capture_panel_runtime)
        return
    if args.admit:
        result = (run_owner_packet(args.packet, args.sha256, panel=True)
                  if args.panel else run_owner_packet(args.packet, args.sha256))
    else:
        result = (run_panel_packet(args.packet, args.sha256)
                  if args.panel else run_packet(args.packet, args.sha256))
    if args.admit:
        if (type(result) is not dict or result.get("status") != "exited"
                or type(result.get("returncode")) is not int or result["returncode"] != 0):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
