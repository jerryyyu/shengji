"""Authenticated, one-shot bootstrap for the M9 panel readout publication.

This module intentionally imports only the Python standard library.  The
invocation, this helper, and the complete application source/runtime manifest
are authenticated before Shengji is placed on ``sys.path``.  This is a
bootstrap boundary, not a scientific or host-use qualification.  Final seal,
RELEASE, invocation authorization, and real-use qualification remain the
responsibility of a canonical externally reviewed handoff.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import stat
import types


_MAX_HELPER_BYTES = 256 * 1024
_MAX_INVOCATION_BYTES = 1024 * 1024
_MAX_COLLECTION_PACKET_BYTES = 1024 * 1024
_INVOCATION_SCHEMA = "m9-panel-readout-invocation-v1"
_INVOCATION_KEYS = frozenset({
    "schema", "files", "packet_sha256", "collection_packet", "output_dir",
    "runtime", "controls", "terminal_seal",
})
_HELPER_NAME = "_m9_panel_readout_observation_worker"


def _strict_sha_shape(value, label: str) -> str:
    """Validate a digest before invoking any authenticated helper code."""
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return value


def _stamp(path: Path):
    """Return the identity metadata used for the bounded helper read."""
    if (not path.is_absolute() or path.is_symlink() or not path.exists()
            or not path.is_file()):
        raise ValueError("regular nonsymlink helper required")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("regular nonsymlink helper ancestry required")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("regular nonsymlink helper required")
    return (metadata.st_dev, metadata.st_ino, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns)


def _read_helper(path: Path, expected_sha: str) -> bytes:
    """Read one bounded, stable helper snapshot and authenticate its bytes."""
    _strict_sha_shape(expected_sha, "bootstrap SHA")
    before = _stamp(path)
    if before[2] > _MAX_HELPER_BYTES:
        raise ValueError("bootstrap helper exceeds size limit")
    with path.open("rb") as handle:
        raw = handle.read(_MAX_HELPER_BYTES + 1)
    after = _stamp(path)
    if len(raw) > _MAX_HELPER_BYTES or before != after:
        raise ValueError("bootstrap helper changed during read")
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("bootstrap helper SHA mismatch")
    return raw


def _runtime_gate() -> None:
    """Refuse non-qualified interpreters before executing helper bytes."""
    if not sys.platform.startswith("linux"):
        raise ValueError("Linux interpreter required")
    if not sys.flags.isolated:
        raise ValueError("isolated interpreter required")
    if not sys.dont_write_bytecode:
        raise ValueError("bytecode writes must be disabled")
    if any(name == "shengji" or name.startswith("shengji.")
           or name == "scripts" or name.startswith("scripts.")
           for name in sys.modules):
        raise ValueError("application modules must not already be imported")


def _load_helper(expected_sha: str):
    """Execute the exact authenticated sibling helper under a non-main name."""
    helper_path = Path(__file__).parent / "observation_worker.py"
    raw = _read_helper(helper_path, expected_sha)
    module = types.ModuleType(_HELPER_NAME)
    module.__file__ = str(helper_path)
    module.__package__ = ""
    module.__loader__ = None
    # Keep the same authenticated module available for the duration of this
    # process; no helper CLI or second source read is involved.
    sys.modules[_HELPER_NAME] = module
    code = compile(raw, str(helper_path), "exec")
    exec(code, module.__dict__)
    module._strict_sha(expected_sha, "bootstrap SHA")
    return module


def _canonical_json(value) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invocation must have canonical finite JSON") from exc


def _read_invocation(helper, invocation_path, invocation_sha: str) -> dict:
    """Authenticate canonical invocation bytes before interpreting their fields."""
    helper._strict_sha(invocation_sha, "invocation SHA")
    path = helper._canonical_absolute(invocation_path, "invocation")
    _stamp(path)
    raw, _ = helper._stable_read(path, _MAX_INVOCATION_BYTES)
    if hashlib.sha256(raw).hexdigest() != invocation_sha:
        raise ValueError("invocation SHA mismatch")
    invocation = helper._parse_object(raw)
    if _canonical_json(invocation) != raw:
        raise ValueError("invocation JSON must be canonical")
    if (set(invocation) != _INVOCATION_KEYS
            or invocation.get("schema") != _INVOCATION_SCHEMA):
        raise ValueError("exact M9 panel readout invocation required")

    files = invocation.get("files")
    if type(files) is not dict or len(files) != 20:
        raise ValueError("exact twenty M9 panel input pins required")
    for name, entry in files.items():
        if (type(name) is not str or not name
                or type(entry) is not dict or set(entry) != {"path", "sha256"}):
            raise ValueError("exact path/SHA input pin required")
        helper._canonical_absolute(entry["path"], f"input {name}")
        helper._strict_sha(entry["sha256"], f"input SHA for {name}")
    helper._strict_sha(invocation["packet_sha256"], "packet SHA")
    collection_packet = invocation.get("collection_packet")
    if (type(collection_packet) is not dict
            or set(collection_packet) != {"path", "sha256"}):
        raise ValueError("exact collection packet reference required")
    helper._canonical_absolute(collection_packet["path"], "collection packet")
    helper._strict_sha(collection_packet["sha256"], "collection packet SHA")
    if collection_packet["sha256"] != invocation["packet_sha256"]:
        raise ValueError("collection packet SHA differs from packet SHA")
    helper._canonical_absolute(invocation["output_dir"], "output_dir")
    runtime = invocation.get("runtime")
    if type(runtime) is not dict or set(runtime) != {"path", "sha256"}:
        raise ValueError("exact runtime reference required")
    helper._canonical_absolute(runtime["path"], "runtime")
    helper._strict_sha(runtime["sha256"], "runtime SHA")
    return invocation


def _read_collection_packet(helper, invocation: dict) -> tuple[Path, dict]:
    """Authenticate and parse the original panel packet before app import."""
    reference = invocation["collection_packet"]
    path = helper._canonical_absolute(reference["path"], "collection packet")
    # The authenticated helper's stamp is intentionally metadata-only; apply
    # this bootstrap's regular-file check before delegating the stable read.
    _stamp(path)
    raw, _ = helper._stable_read(path, _MAX_COLLECTION_PACKET_BYTES)
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("collection packet SHA mismatch")
    packet = helper._parse_object(raw)
    if (set(packet) != helper._PANEL_PACKET_KEYS
            or packet.get("schema") != helper._PANEL_PACKET_SCHEMA):
        raise ValueError("exact M9 panel collection packet required")
    return path, packet


def _read_controls(helper, invocation, packet):
    """Bind historical execution records; never inspect live launch guards.

    These pins still need an externally reviewed terminal inventory. Matching
    JSON records alone are not proof of authorization or scientific provenance.
    """
    expected = {name: packet[name] for name in ("release", "claim", "reservation")}
    expected["process_claim"] = str(Path(packet["recipe"]["evidence"]) / "claim.json")
    pins = invocation["controls"]
    if type(pins) is not dict or set(pins) != set(expected):
        raise ValueError("exact four historical control pins required")
    buffers = {}
    paths = set()
    for name, target in expected.items():
        ref = pins[name]
        if type(ref) is not dict or set(ref) != {"path", "sha256"}:
            raise ValueError("exact control path/SHA pin required")
        path = helper._canonical_absolute(ref["path"], name)
        if path != helper._canonical_absolute(target, name) or path in paths:
            raise ValueError("control path differs from collection packet")
        paths.add(path)
        helper._strict_sha(ref["sha256"], name)
        _stamp(path)
        raw, _ = helper._stable_read(path, 64 * 1024)
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("historical control SHA mismatch")
        buffers[name] = raw
    records = {name: helper._parse_object(raw) for name, raw in buffers.items()}
    digest = invocation["packet_sha256"]
    if records["release"] != {"schema": "m9-panel-release-v1", "packet_sha256": digest}:
        raise ValueError("historical RELEASE differs from collection packet")
    recipe = packet["recipe"]
    command = [recipe["python"], "-I", "-B",
               str(Path(recipe["source_root"]) / "server/scripts/observation_worker.py"),
               "--panel", "--packet", invocation["collection_packet"]["path"],
               "--sha256", digest]
    claim = records["claim"]
    if (set(claim) != {"schema", "packet_sha256", "status", "comparison_validated",
                       "owner_pid", "inner_command", "queue_snapshot", "deadline_monotonic"}
            or claim["schema"] != "m9-panel-owner-attempt-v1"
            or claim["packet_sha256"] != digest or claim["status"] != "spent_no_retry"
            or claim["comparison_validated"] is not False
            or type(claim["owner_pid"]) is not int or claim["owner_pid"] <= 0
            or claim["inner_command"] != command or type(claim["queue_snapshot"]) is not dict
            or type(claim["deadline_monotonic"]) not in (int, float)
            or not math.isfinite(claim["deadline_monotonic"]) or claim["deadline_monotonic"] <= 0):
        raise ValueError("historical owner claim binding mismatch")
    reservation = records["reservation"]
    for key, value in {
        "schema": "codex-m9-panel-reservation-v1", "lane": "m9-panel",
        "packet_sha256": digest, "pid": claim["owner_pid"], "count": 15,
        "seeds": [0, 1, 2], "status": packet["status"],
        "output": recipe["output_dir"], "output_root": recipe["output_dir"],
        "result": recipe["output_dir"], "evidence": recipe["evidence"],
        "launcher": command[3],
    }.items():
        if _canonical_json(reservation.get(key)) != _canonical_json(value):
            raise ValueError("historical reservation binding mismatch")
    process = records["process_claim"]
    timeout = packet["process_timeout_seconds"]
    if (type(timeout) is not int or timeout <= 0 or set(process) != {
            "schema", "command", "timeout_seconds", "comparison_validated"}
            or process["schema"] != "m9-process-attempt-v1"
            or process["command"] != command
            or type(process["timeout_seconds"]) not in (int, float)
            or process["timeout_seconds"] != timeout
            or process["comparison_validated"] is not False):
        raise ValueError("historical process claim binding mismatch")
    return records


def _verify_terminal_seal(helper, invocation, packet):
    """Authenticate an exact SHA256SUMS inventory without opening outcomes.

    The externally reviewed seal covers the 26 consumed collection inputs:
    20 reader files, four controls, collection packet and collection runtime.
    Unconsumed raw captures/logs remain archive material, not another readout.
    The seal's authority comes from the canonical handoff, never its filename.
    """
    ref = invocation["terminal_seal"]
    if type(ref) is not dict or set(ref) != {"path", "sha256"}:
        raise ValueError("exact terminal seal pin required")
    path = helper._canonical_absolute(ref["path"], "terminal seal")
    helper._strict_sha(ref["sha256"], "terminal seal")
    _stamp(path)
    raw, _ = helper._stable_read(path, 64 * 1024)
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("terminal seal SHA mismatch")
    expected = {}
    refs = [*invocation["files"].values(), *invocation["controls"].values(),
            invocation["collection_packet"], packet["runtime"]]
    if len(refs) != 26:
        raise ValueError("exact 26 collection input pins required")
    for entry in refs:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise ValueError("exact sealed input pin required")
        target = str(helper._canonical_absolute(entry["path"], "sealed input"))
        helper._strict_sha(entry["sha256"], "sealed input")
        if target in expected or target == str(path):
            raise ValueError("distinct seal and input paths required")
        expected[target] = entry["sha256"]
    text = raw.decode("utf-8")
    if not text.endswith("\n") or "\r" in text:
        raise ValueError("seal requires newline-terminated SHA256SUMS")
    found = {}
    for line in text[:-1].split("\n"):
        if len(line) < 67 or line[64:66] != "  ":
            raise ValueError("malformed terminal seal entry")
        digest, name = line[:64], line[66:]
        helper._strict_sha(digest, "seal entry")
        helper._canonical_absolute(name, "seal entry")
        if name in found:
            raise ValueError("duplicate terminal seal entry")
        found[name] = digest
    if found != expected:
        raise ValueError("terminal seal differs from readout input pins")


def _read_collection_runtime(helper, packet, records):
    """Bind the sealed collection launcher without rehashing old source trees."""
    ref = packet["runtime"]  # exact pin already validated by seal check
    path = helper._canonical_absolute(ref["path"], "collection runtime")
    _stamp(path)
    raw, _ = helper._stable_read(path, 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("collection runtime SHA mismatch")
    manifest = helper._parse_object(raw)
    source = str(Path(packet["recipe"]["source_root"]) / "server")
    if (manifest.get("schema") != "shengji-m9-runtime-v1"
            or manifest.get("source_root") != source
            or type(manifest.get("source_files")) is not dict):
        raise ValueError("collection runtime source binding mismatch")
    launcher_sha = manifest["source_files"].get("scripts/observation_worker.py")
    helper._strict_sha(launcher_sha, "collection launcher SHA")
    if records["reservation"].get("launcher_sha256") != launcher_sha:
        raise ValueError("reservation launcher differs from sealed collection runtime")


def _qualification_paths(helper) -> tuple[Path, Path]:
    """Return the authenticated reader and its server source root."""
    reader = Path(__file__)
    if (not reader.is_absolute() or reader.is_symlink() or not reader.is_file()
            or any(parent.is_symlink() for parent in (reader, *reader.parents))):
        raise ValueError("canonical nonsymlink reader path required")
    server = reader.parent.parent
    if (not server.is_absolute() or not server.is_dir()
            or server.is_symlink()
            or any(parent.is_symlink() for parent in (server, *server.parents))):
        raise ValueError("canonical nonsymlink server root required")
    # Keep qualification's path checks on the authenticated helper's exact
    # canonical-path rules, rather than allowing a spelling alias here.
    return helper._canonical_absolute(str(reader), "reader"), \
        helper._canonical_absolute(str(server), "server root")


def _qualification_output(helper, value, server: Path) -> Path:
    """Validate an exclusive manifest output outside the checkout."""
    target = helper._canonical_absolute(value, "qualification output")
    if target.is_relative_to(server.parent):
        raise ValueError("qualification output must be outside the source checkout")
    if target.exists() or target.is_symlink():
        raise ValueError("qualification output exists; preserve it")
    if (not target.parent.is_dir()
            or any(parent.is_symlink() for parent in (target.parent, *target.parent.parents))):
        raise ValueError("qualification output parent must be a nonsymlink directory")
    return target


def _read_qualification_runtime(helper, path, digest: str, server: Path,
                                bootstrap_sha: str) -> dict:
    """Read and authenticate one runtime manifest before application imports."""
    path = helper._canonical_absolute(path, "runtime manifest")
    _stamp(path)
    helper._strict_sha(digest, "runtime SHA")
    manifest = helper._read_runtime(
        {"runtime": {"path": str(path), "sha256": digest}}, server)
    if (type(manifest) is not dict
            or manifest.get("schema") != "shengji-m9-runtime-v1"
            or any(key not in manifest for key in
                   ("source_root", "source_files", "environment"))):
        raise ValueError("qualified runtime manifest schema mismatch")
    source_files = manifest.get("source_files") if type(manifest) is dict else None
    if (type(source_files) is not dict
            or source_files.get("scripts/observation_worker.py") != bootstrap_sha):
        raise ValueError("runtime manifest does not bind authenticated bootstrap")
    return manifest


def _import_readout_application(server: Path):
    """Import exactly the runtime/recipe/publication closure used by real runs."""
    import importlib

    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    runtime_adapter = importlib.import_module("shengji.eval.observation_runtime")
    recipe = importlib.import_module("shengji.eval.m9_panel_recipe")
    publication = importlib.import_module("shengji.eval.m9_panel_publication")
    return runtime_adapter, recipe, publication


def capture_runtime(baseline_path: str, baseline_sha: str, bootstrap_sha: str,
                    output: str) -> dict:
    """Capture a model-free panel-readout runtime through the real closure."""
    _runtime_gate()
    helper = _load_helper(bootstrap_sha)
    _reader, server = _qualification_paths(helper)
    baseline = _read_qualification_runtime(
        helper, baseline_path, baseline_sha, server, bootstrap_sha)
    target = _qualification_output(helper, output, server)
    runtime_adapter, _recipe, _publication = _import_readout_application(server)
    manifest = runtime_adapter.capture(server, profile="panel-readout")
    if (type(manifest) is not dict
            or any(key not in manifest for key in
                   ("source_root", "source_files", "environment"))):
        raise ValueError("qualified runtime manifest is incomplete")
    for key in ("source_root", "source_files", "environment"):
        if manifest.get(key) != baseline.get(key):
            raise ValueError("qualified application changed: " + key)
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    # Recheck the path immediately before the exclusive create to catch a
    # symlink or competing output appearing during the import-only capture.
    target = _qualification_output(helper, output, server)
    with target.open("xb") as handle:
        handle.write(raw)
    digest = hashlib.sha256(raw).hexdigest()
    print("M9 PANEL READOUT RUNTIME CAPTURED sha256=" + digest, flush=True)
    return manifest


def verify_runtime(runtime_path: str, runtime_sha: str, bootstrap_sha: str):
    """Verify one authenticated panel-readout runtime without collection access."""
    _runtime_gate()
    helper = _load_helper(bootstrap_sha)
    _reader, server = _qualification_paths(helper)
    manifest = _read_qualification_runtime(
        helper, runtime_path, runtime_sha, server, bootstrap_sha)
    runtime_adapter, _recipe, _publication = _import_readout_application(server)
    admitted = runtime_adapter.ObservationRuntime(manifest, profile="panel-readout")
    if admitted.check() is not True:
        raise ValueError("readout runtime verification failed")
    print("M9 PANEL READOUT RUNTIME VERIFIED", flush=True)
    return admitted


def run(invocation_path: str, invocation_sha: str, bootstrap_sha: str):
    """Authenticate and perform one already-reviewed publication invocation."""
    _runtime_gate()
    helper = _load_helper(bootstrap_sha)
    invocation = _read_invocation(helper, invocation_path, invocation_sha)
    _collection_packet_path, collection_packet = _read_collection_packet(
        helper, invocation)

    # The worker is itself under server/scripts; do not resolve through a
    # symlink and thereby silently admit a different source tree.
    worker_path = Path(__file__)
    if (not worker_path.is_absolute() or worker_path.is_symlink()
            or any(part.is_symlink() for part in (worker_path, *worker_path.parents))):
        raise ValueError("canonical nonsymlink worker path required")
    server = Path(__file__).parents[1]
    if not server.is_absolute() or any(part.is_symlink() for part in (server, *server.parents)):
        raise ValueError("canonical nonsymlink server root required")
    # The sibling helper's reusable bounded reader is intentionally generic;
    # establish the manifest as a regular file before handing it that path.
    _stamp(Path(invocation["runtime"]["path"]))
    manifest = helper._read_runtime(invocation, server)
    source_files = manifest.get("source_files") if type(manifest) is dict else None
    if (type(source_files) is not dict
            or source_files.get("scripts/observation_worker.py") != bootstrap_sha):
        raise ValueError("runtime manifest does not bind authenticated bootstrap")

    _verify_terminal_seal(helper, invocation, collection_packet)
    controls = _read_controls(helper, invocation, collection_packet)
    _read_collection_runtime(helper, collection_packet, controls)

    import importlib

    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    runtime_adapter = importlib.import_module("shengji.eval.observation_runtime")
    admitted = runtime_adapter.ObservationRuntime(manifest, profile="panel-readout")
    recipe = importlib.import_module("shengji.eval.m9_panel_recipe")
    recipe.validate_panel_recipe(collection_packet["recipe"])
    publication = importlib.import_module("shengji.eval.m9_panel_publication")
    return publication.publish_m9_panel_readout_once(
        invocation, invocation_sha256=invocation_sha, runtime_check=admitted.check,
        collection_packet=collection_packet)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        if args and args[0] == "--capture-runtime":
            if len(args) != 5:
                raise ValueError("capture-runtime requires five arguments")
            capture_runtime(args[1], args[2], args[3], args[4])
        elif args and args[0] == "--verify-runtime":
            if len(args) != 4:
                raise ValueError("verify-runtime requires four arguments")
            verify_runtime(args[1], args[2], args[3])
        else:
            if len(args) != 3:
                raise ValueError("three positional arguments required")
            run(args[0], args[1], args[2])
    except BaseException as exc:
        # Deliberately do not expose paths, scientific values, or exception
        # messages at this boundary.  The reviewed handoff owns diagnostics.
        print(type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
