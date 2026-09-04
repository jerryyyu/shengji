"""Runtime attestation for the PT-Luna collector.

One :func:`source_identity` call stamps everything a run is bound to: the
pure-engine environment, the Git head (dirty trees are stamped, not
refused), the boot session, the hashed source set, and the Codex binary's
zero-tool feature catalog.  The dictionary is hashed into the ledger genesis
and every attempt, so a restart under a different runtime refuses to resume.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading

from .transport import (
    CodexTurnTransportError,
    MODEL,
    REASONING_EFFORT,
    attest_codex_runtime,
)
from .canonical import canonical_json_bytes


RUNTIME_SCHEMA = "pt-luna-turn-rpc-runtime-v2"
FAILURE_STAGES = (
    "none", "dispatch", "provider-response", "validation", "engine-apply",
    "journal-commit", "terminal-verification", "resource-meter",
)
FAILURE_KINDS = (
    "none", "game-deadline", "call-timeout", "provider-process",
    "provider-schema", "forbidden-tool", "transport-validation",
    "engine-validation", "journal-io", "resource-meter", "unknown",
)
NO_FAILURE_MESSAGE_SHA256 = hashlib.sha256(b"").hexdigest()
REQUIRED_ENGINE_ENVIRONMENT = {
    "SHENGJI_FAST": None,
    "SHENGJI_REQUIRE_VOIDS": "1",
}
LOADABLE_SHADOW_SUFFIXES = (".pyc", ".pyo", ".so", ".dylib", ".pyd")
SOURCE_PATHS = (
    "shengji/luna/__init__.py",
    "shengji/luna/canonical.py",
    "shengji/luna/game.py",
    "shengji/luna/turn.py",
    "shengji/luna/transport.py",
    "shengji/luna/watchdog.py",
    "shengji/luna/atomic_io.py",
    "shengji/luna/journal.py",
    "shengji/luna/runtime.py",
    "shengji/luna/ledger.py",
    "shengji/luna/attempt.py",
    "shengji/luna/supervisor.py",
    "scripts/luna.py",
)


class RuntimeAttestationError(ValueError):
    """The execution environment, source set, or Codex runtime is unusable."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


class RPCConcurrency:
    """Count live provider RPCs across worker threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.maximum = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def leave(self) -> None:
        with self._lock:
            if self.active <= 0:
                raise RuntimeAttestationError("RPC concurrency underflow")
            self.active -= 1

    def reset_maximum(self) -> None:
        with self._lock:
            if self.active != 0:
                raise RuntimeAttestationError("RPC concurrency reset while active")
            self.maximum = 0


def _source_hashes() -> dict[str, str]:
    server_root = Path(__file__).resolve().parents[2]
    return {name: _sha_bytes((server_root / name).read_bytes())
            for name in SOURCE_PATHS}


def _boot_identity_bytes() -> bytes:
    source = Path("/proc/sys/kernel/random/boot_id")
    try:
        if source.is_file():
            value = source.read_bytes().strip()
        elif sys.platform == "darwin":
            value = subprocess.check_output(
                ["sysctl", "-n", "kern.bootsessionuuid"],
                stderr=subprocess.DEVNULL).strip()
        else:
            raise RuntimeAttestationError("boot identity unavailable")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeAttestationError("boot identity unavailable") from exc
    if not value:
        raise RuntimeAttestationError("boot identity unavailable")
    return value


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ("git", "-C", str(repo), *args), stderr=subprocess.PIPE,
        text=True).strip()


def _require_pure_engine(repo: Path) -> None:
    """Refuse a compiled, non-strict, or bytecode-writing engine process."""
    if ({name: os.environ.get(name)
         for name in REQUIRED_ENGINE_ENVIRONMENT}
            != REQUIRED_ENGINE_ENVIRONMENT
            or not sys.dont_write_bytecode):
        raise RuntimeAttestationError(
            "collector requires pure engine, strict voids, and -B")
    fast_module = sys.modules.get("shengji.engine.fast")
    if fast_module is not None and bool(getattr(fast_module, "_saved", {})):
        raise RuntimeAttestationError("compiled engine is active")
    package_root = repo / "server" / "shengji"
    shadows = sorted(
        path.relative_to(repo).as_posix()
        for path in package_root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.suffix.lower() in LOADABLE_SHADOW_SUFFIXES)
    if shadows:
        raise RuntimeAttestationError("loadable source shadow is present")


def source_identity(codex_binary: Path) -> dict[str, object]:
    """Stamp the complete runtime a run binds to; never launch a game."""
    binary = Path(codex_binary).resolve()
    repo = Path(__file__).resolve().parents[3]
    try:
        status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        execution_git = _git(repo, "rev-parse", "HEAD")
        git_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeAttestationError("Git identity unavailable") from exc
    if len(execution_git) != 40 or len(git_tree) != 40:
        raise RuntimeAttestationError("Git identity drift")
    _require_pure_engine(repo)
    try:
        codex = attest_codex_runtime(binary)
    except CodexTurnTransportError as exc:
        raise RuntimeAttestationError("Codex runtime refused") from exc
    sources = _source_hashes()
    return {"schema": RUNTIME_SCHEMA,
            "python_executable": str(Path(sys.executable).resolve()),
            "python_sha256": _sha_bytes(Path(sys.executable).read_bytes()),
            "python_version": sys.version,
            "platform": platform.platform(),
            "engine_mode": "pure-python", "strict_voids": True,
            "python_dont_write_bytecode": True,
            "required_environment": dict(REQUIRED_ENGINE_ENVIRONMENT),
            "native_extension": None,
            "execution_git": execution_git, "git_tree": git_tree,
            "git_dirty": bool(status),
            "boot_identity_sha256": _sha_bytes(_boot_identity_bytes()),
            "codex_binary": str(binary),
            "codex_binary_sha256": codex["binary_sha256"],
            "codex_version": codex["version"],
            "codex_tool_catalog": codex,
            "model": MODEL, "reasoning_effort": REASONING_EFFORT,
            "sources": sources, "source_set_sha256": _sha(sources)}


__all__ = ["FAILURE_KINDS", "FAILURE_STAGES", "NO_FAILURE_MESSAGE_SHA256",
           "REQUIRED_ENGINE_ENVIRONMENT", "RPCConcurrency", "RUNTIME_SCHEMA",
           "RuntimeAttestationError", "SOURCE_PATHS", "source_identity"]
