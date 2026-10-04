"""The authenticated, one-shot M9 observation worker.

This file deliberately starts as a standard-library-only bootstrap.  Packet
and application bytes are authenticated before the Shengji package is put on
``sys.path``; the imported runtime adapter then performs its stronger import
and dependency checks.  The worker never starts a child process or retries.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sys


_MAX_PACKET_BYTES = 1024 * 1024
_MAX_RUNTIME_BYTES = 1024 * 1024
_MAX_CLAIM_BYTES = 64 * 1024
_PACKET_SCHEMA = "m9-admission-v1"
_PACKET_KEYS = frozenset({
    "schema", "recipe", "environment", "source_commit", "hostname", "runtime",
    "watchdog", "read_complete", "queue", "release", "hold", "host_lock",
    "other_locks", "reservation", "status", "claim",
})
_CLAIM_KEYS = frozenset({
    "schema", "packet_sha256", "status", "comparison_validated", "owner_pid",
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


def _read_packet(packet_path, packet_sha):
    path = _canonical_absolute(packet_path, "packet")
    _strict_sha(packet_sha, "packet SHA")
    raw, _ = _stable_read(path, _MAX_PACKET_BYTES)
    if hashlib.sha256(raw).hexdigest() != packet_sha:
        raise ValueError("packet SHA mismatch")
    packet = _parse_object(raw)
    if set(packet) != _PACKET_KEYS or packet.get("schema") != _PACKET_SCHEMA:
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


def _import_application(server: Path):
    # This is the first point at which importing Shengji is permitted.
    import importlib

    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    recipe = importlib.import_module("shengji.eval.observation_recipe")
    runtime = importlib.import_module("shengji.eval.observation_runtime")
    guards = importlib.import_module("shengji.eval.observation_queue")
    tactical = importlib.import_module("scripts.tactical_report")
    return recipe, runtime, guards, tactical


def _verify_claim_and_controls(packet, packet_sha, guards):
    controls = {}
    for key in ("release", "hold", "host_lock", "reservation", "status", "claim"):
        controls[key] = _canonical_absolute(packet[key], key)
    other_locks = packet["other_locks"]
    if type(other_locks) is not list or not other_locks:
        raise ValueError("explicit peer lock paths required")
    other_locks = [_canonical_absolute(path, "peer lock") for path in other_locks]

    claim_raw, _ = _stable_read(controls["claim"], _MAX_CLAIM_BYTES)
    claim = _parse_object(claim_raw)
    if (set(claim) != _CLAIM_KEYS or claim.get("schema") != "m9-owner-attempt-v1"
            or claim.get("packet_sha256") != packet_sha
            or claim.get("status") != "spent_no_retry"
            or claim.get("comparison_validated") is not False):
        raise ValueError("strict spent owner claim required")
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
    if not guards.guard_release(
            controls["release"], {"schema": "m9-release-v1", "packet_sha256": packet_sha}):
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
    if owner_text != f"m9 {owner_pid} {packet_sha}\n":
        raise ValueError("host lock owner mismatch")
    if _stamp(host_lock) != lock_before:
        raise ValueError("host lock changed during verification")
    return controls


def run_packet(packet_path, packet_sha):
    """Authenticate and invoke one fixed tactical report in this process."""
    _, packet = _read_packet(packet_path, packet_sha)
    repo = _repository_root()
    recipe_value = packet.get("recipe")
    if type(recipe_value) is not dict or recipe_value.get("source_root") != str(repo):
        raise ValueError("recipe source is not this repository")
    server = repo / "server"
    runtime_manifest = _read_runtime(packet, server)

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


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    run_packet(args.packet, args.sha256)


if __name__ == "__main__":
    main()
