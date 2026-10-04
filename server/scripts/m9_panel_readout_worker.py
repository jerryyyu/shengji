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
from pathlib import Path
import sys
import stat
import types


_MAX_HELPER_BYTES = 256 * 1024
_MAX_INVOCATION_BYTES = 1024 * 1024
_INVOCATION_SCHEMA = "m9-panel-readout-invocation-v1"
_INVOCATION_KEYS = frozenset({
    "schema", "files", "packet_sha256", "output_dir", "runtime",
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
    helper._canonical_absolute(invocation["output_dir"], "output_dir")
    runtime = invocation.get("runtime")
    if type(runtime) is not dict or set(runtime) != {"path", "sha256"}:
        raise ValueError("exact runtime reference required")
    helper._canonical_absolute(runtime["path"], "runtime")
    helper._strict_sha(runtime["sha256"], "runtime SHA")
    return invocation


def run(invocation_path: str, invocation_sha: str, bootstrap_sha: str):
    """Authenticate and perform one already-reviewed publication invocation."""
    _runtime_gate()
    helper = _load_helper(bootstrap_sha)
    invocation = _read_invocation(helper, invocation_path, invocation_sha)

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

    import importlib

    sys.path.insert(0, str(server))
    importlib.invalidate_caches()
    runtime_adapter = importlib.import_module("shengji.eval.observation_runtime")
    admitted = runtime_adapter.ObservationRuntime(manifest, profile="panel-readout")
    publication = importlib.import_module("shengji.eval.m9_panel_publication")
    return publication.publish_m9_panel_readout_once(
        invocation, invocation_sha256=invocation_sha, runtime_check=admitted.check)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    try:
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
