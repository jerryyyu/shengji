"""Read-only construction of the Value-Afterstate V2 execution freeze.

The builder is deliberately boring: it authenticates one clean checkout,
reopens six already-published inputs, and returns the typed freeze object.  It
does not create an evidence namespace or grant any execution authority.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_capacity import choose_capacity_tier_v2
from .world_afterstate_v2_capacity_runner import reopen_capacity_receipt_v2_bytes
from .world_afterstate_v2_execution import (
    ExecutionFreezeV2, MAX_DEADLINE_SECONDS, SourceBindingV2,
    FREEZE_SCHEMA, live_runtime_profile, source_manifest_sha256,
    validate_execution_freeze,
)


class WorldAfterstateV2FreezeBuilderError(ValueError):
    """A source checkout or freeze input was refused."""


FreezeBuilderError = WorldAfterstateV2FreezeBuilderError

_LOADABLE = {".py", ".pyc", ".pyo", ".so", ".dylib", ".pyd"}
_ARTIFACT_LABELS = (
    "protocol", "capacity", "population", "config", "seed",
    "continuation-policy",
)
def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object_sha(value: Mapping[str, Any]) -> str:
    return _sha(canonical_json_bytes(dict(value)))


def _fail(message: str, exc: BaseException | None = None):
    if exc is None:
        raise WorldAfterstateV2FreezeBuilderError(message)
    raise WorldAfterstateV2FreezeBuilderError(message) from exc


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(("git", *args), cwd=repo, check=True,
                                capture_output=True, text=not binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        _fail("source Git authentication failed", exc)
    return result.stdout if binary else result.stdout.strip()


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        _fail(f"{label} bytes drift")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(
                               ValueError(value)))
    except WorldAfterstateV2FreezeBuilderError:
        raise
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not canonical JSON", exc)
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        _fail(f"{label} is not canonical JSON")
    return value


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            _fail("duplicate JSON key")
        result[key] = value
    return result


def _path(value: Path | str, label: str, *, absolute: bool = True) -> Path:
    path = Path(value)
    if absolute and not path.is_absolute():
        _fail(f"{label} must be absolute")
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} path drift")
    try:
        st = path.stat()
    except OSError as exc:
        _fail(f"{label} path drift", exc)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        _fail(f"{label} path drift")
    return path


def _read(path: Path, label: str) -> bytes:
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        _fail(f"{label} cannot be read", exc)
    if (before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) != (after.st_ino, after.st_size,
                                     after.st_mtime_ns, after.st_ctime_ns):
        _fail(f"{label} changed during read")
    return raw


def _head(repo: Path, expected: str) -> str:
    if (type(expected) is not str or len(expected) != 40
            or any(c not in "0123456789abcdef" for c in expected)):
        _fail("expected source Git identity drift")
    actual = _git(repo, "rev-parse", "HEAD")
    if actual != expected:
        _fail("source HEAD differs from expected")
    return actual


def _clean_source_tree(repo: Path) -> None:
    try:
        status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all",
                      "--ignored=matching")
    except WorldAfterstateV2FreezeBuilderError:
        raise
    if status:
        for row in status.splitlines():
            # Ordinary tracked/untracked changes are never admissible.  An
            # ignored virtualenv/log directory is harmless, but ignored
            # loadable source (including a cache directory) is not.
            ignored = row.startswith("!! ")
            name = row[3:] if ignored else row[3:]
            if not ignored:
                _fail("source checkout is not clean")
            normalized = name.rstrip("/")
            if (Path(normalized).suffix.lower() in _LOADABLE
                    or normalized.startswith(("server/shengji/", "server/scripts/"))):
                _fail("ignored loadable source state present")
    # Git status intentionally does not report every ignored shadow in all
    # configurations.  Scan the loadable source roots independently.
    for root_name in ("server/shengji", "server/scripts"):
        root = repo / root_name
        if not root.is_dir() or root.is_symlink():
            _fail("Value V2 source root drift")
        for current, dirs, files in os.walk(root, topdown=True,
                                            followlinks=False):
            if Path(current).is_symlink():
                _fail("source symlink present")
            if "__pycache__" in dirs:
                _fail("source bytecode cache present")
            dirs[:] = [name for name in dirs if name != ".git"]
            for name in files:
                path = Path(current) / name
                if path.is_symlink():
                    _fail("source symlink present")
                if path.suffix.lower() in _LOADABLE:
                    # Any loadable file under these roots is source state;
                    # ignored or untracked shadows are not admissible.
                    if path.suffix.lower() in {".pyc", ".pyo"}:
                        _fail("source bytecode artifact present")


def _module_path(repo: Path, name: str) -> Path | None:
    if not name or name.startswith((".", "__")):
        return None
    # The package is installed from ``server`` in production.
    parts = name.split(".")
    candidate = repo / "server" / Path(*parts)
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    init = candidate / "__init__.py"
    return init if init.is_file() else None


def _resolve_import(repo: Path, path: Path, module: str, level: int) -> Path | None:
    try:
        relative = path.relative_to(repo / "server").with_suffix("")
    except ValueError:
        return None
    package = list(relative.parts[:-1])
    if path.name == "__init__.py":
        package = list(relative.parts[:-1])
    if level:
        if level - 1 > len(package):
            return None
        package = package[:len(package) - level + 1]
        name = ".".join((*package, module)) if module else ".".join(package)
    else:
        name = module
    return _module_path(repo, name)


def _imports(repo: Path, path: Path) -> tuple[Path, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        _fail("source import graph parse refused", exc)
    result: list[Path] = []
    for node in ast.walk(tree):
        candidate = None
        if isinstance(node, ast.Import):
            for alias in node.names:
                candidate = _module_path(repo, alias.name)
                if candidate is not None:
                    result.append(candidate)
        elif isinstance(node, ast.ImportFrom):
            candidate = _resolve_import(repo, path, node.module or "", node.level)
            if candidate is not None:
                result.append(candidate)
            for alias in node.names:
                if alias.name == "*":
                    continue
                base = (node.module + "." + alias.name
                        if node.module else alias.name)
                candidate = _resolve_import(repo, path, base, node.level)
                if candidate is not None:
                    result.append(candidate)
    return tuple(result)


def _source_closure(repo: Path) -> tuple[Path, ...]:
    tracked = set(_git(repo, "ls-files", "-z", binary=True).decode().split("\0"))
    roots = {
        path for path in tracked
        if (path.startswith("server/shengji/rl/world_afterstate_v2_")
            and path.endswith(".py"))
        or (path.startswith("server/scripts/world_afterstate_v2")
            and path.endswith(".py"))
        or path == "server/scripts/build_world_afterstate_v2_freeze.py"
    }
    discovered = {repo / name for name in roots}
    # Importing a package executes its initializer as well.  Bind those
    # tracked initializers so the closure describes the actual import surface.
    for current in tuple(discovered):
        try:
            relative = current.relative_to(repo / "server")
        except ValueError:
            continue
        for count in range(1, len(relative.parts)):
            package = repo / "server" / Path(*relative.parts[:-count]) / "__init__.py"
            if package.is_file() and package.relative_to(repo).as_posix() in tracked:
                discovered.add(package)
    queue = list(discovered)
    while queue:
        current = queue.pop()
        for candidate in _imports(repo, current):
            try:
                relative = candidate.relative_to(repo).as_posix()
            except ValueError:
                continue
            if relative not in tracked or candidate in discovered:
                continue
            discovered.add(candidate)
            queue.append(candidate)
    result = tuple(sorted(discovered, key=lambda path: path.relative_to(repo).as_posix()))
    if not result:
        _fail("Value V2 source closure is empty")
    return result


def _bindings(repo: Path, source_git: str) -> tuple[SourceBindingV2, ...]:
    rows = []
    for path in _source_closure(repo):
        relative = path.relative_to(repo).as_posix()
        if path.is_symlink() or not path.is_file():
            _fail("source binding path drift")
        raw = _read(path, f"source {relative}")
        try:
            committed = _git(repo, "show", f"{source_git}:{relative}", binary=True)
        except WorldAfterstateV2FreezeBuilderError:
            raise
        if raw != committed:
            _fail("source byte differs from Git blob")
        rows.append(SourceBindingV2(relative, len(raw), _sha(raw)))
    rows.sort(key=lambda row: row.path)
    return tuple(rows)


def _repo_relative(repo: Path, value: Path | str, label: str) -> tuple[Path, str]:
    path = _path(value, label)
    try:
        relative = path.resolve(strict=True).relative_to(repo.resolve(strict=True))
    except (OSError, ValueError) as exc:
        _fail(f"{label} must be inside repository", exc)
    text = relative.as_posix()
    if (not text or text.startswith("../") or text == ".."
            or "\\" in text or any(part in ("", ".", "..")
                                    for part in Path(text).parts)):
        _fail(f"{label} path drift")
    # Resolve every component explicitly; artifact symlinks are forbidden.
    cursor = repo
    for part in Path(text).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail(f"{label} symlink path drift")
    return path, text


def _validate_protocol(raw: bytes) -> None:
    value = _strict_json(raw, "protocol artifact")
    try:
        from .world_afterstate_v2_protocol import protocol_payload
        expected = protocol_payload()
    except Exception as exc:
        _fail("protocol authoritative reopener unavailable", exc)
    if value != expected:
        _fail("protocol artifact reopen drift")


@dataclass(frozen=True)
class _ConfigBinding:
    artifact_bindings: tuple[tuple[str, str, str], ...]
    evidence_root: str
    deadline_seconds: int
    population_tier: str = "D256"


def _validate_inputs(repo: Path, paths: tuple[tuple[str, Path | str], ...],
                     *, evidence_root: Path, deadline_seconds: int
                     ) -> tuple[tuple[tuple[str, str, str], ...], str]:
    if len(paths) != len(_ARTIFACT_LABELS):
        _fail("freeze artifact input population drift")
    rows: list[tuple[str, str, str]] = []
    raws: dict[str, bytes] = {}
    for label, supplied in paths:
        if label not in _ARTIFACT_LABELS:
            _fail("freeze artifact label drift")
        path, relative = _repo_relative(repo, supplied, f"{label} artifact")
        raw = _read(path, f"{label} artifact")
        raws[label] = raw
        rows.append((label, relative, _sha(raw)))
    if tuple(row[0] for row in rows) != _ARTIFACT_LABELS:
        _fail("freeze artifact order drift")
    _validate_protocol(raws["protocol"])
    try:
        capacity = reopen_capacity_receipt_v2_bytes(raws["capacity"])
        if any(tier.outcomes_opened for tier in capacity.tiers):
            _fail("capacity receipt contains opened outcomes")
        selected = choose_capacity_tier_v2(capacity)
        if selected.name != "D256" or not any(
                tier.tier == selected.name and tier.exact_source_supply
                for tier in capacity.tiers):
            _fail("capacity exact-source tier unavailable")
    except WorldAfterstateV2FreezeBuilderError:
        raise
    except Exception as exc:
        _fail("capacity receipt reopen refused", exc)
    # The population input and early-stage config have authoritative adapter
    # readers.  Build a provisional identity solely to exercise those readers.
    try:
        from .world_afterstate_v2_stage_adapters import _read_input, _read_stage_config
        supplied = dict(paths)
        digest_by_label = {row[0]: row[2] for row in rows}
        _read_input(Path(supplied["population"]),
                    expected_digest=digest_by_label["population"],
                    freeze_deadline=deadline_seconds)
        config_binding = tuple(row for row in rows if row[0] == "config")
        provisional = _ConfigBinding(
            artifact_bindings=config_binding,
            evidence_root=str(evidence_root), deadline_seconds=deadline_seconds)
        _read_stage_config(repo, provisional, "world-afterstate-v2-early-stage-adapters-input-v1")
    except WorldAfterstateV2FreezeBuilderError:
        raise
    except Exception as exc:
        _fail("Value V2 input authoritative reopen refused", exc)
    # No typed reopener exists for the seed registry or continuation-policy
    # input in this source head.  Their strict canonical envelope is the
    # strongest honest check available; do not invent a weaker reinterpretation.
    _strict_json(raws["seed"], "seed registry input")
    _strict_json(raws["continuation-policy"], "continuation-policy input")
    return tuple(rows), selected.name


def build_execution_freeze(
        repo: Path | str, expected_head: str | None = None,
        protocol_path: Path | str | None = None, capacity_path: Path | str | None = None,
        population_path: Path | str | None = None, config_path: Path | str | None = None,
        seed_path: Path | str | None = None,
        continuation_policy_path: Path | str | None = None,
        evidence_root: Path | str | None = None,
        deadline_seconds: int = MAX_DEADLINE_SECONDS,
        heartbeat_seconds: int = 60, *, expected_git: str | None = None,
        source_git: str | None = None,
        population_input_path: Path | str | None = None,
        early_stage_config_path: Path | str | None = None,
        seed_input_path: Path | str | None = None,
        continuation_policy_input_path: Path | str | None = None,
        ) -> ExecutionFreezeV2:
    """Build and round-trip one canonical, inert :class:`ExecutionFreezeV2`."""
    expected_head = expected_head or expected_git or source_git
    population_path = population_path or population_input_path
    config_path = config_path or early_stage_config_path
    seed_path = seed_path or seed_input_path
    continuation_policy_path = (continuation_policy_path
                                or continuation_policy_input_path)
    if any(value is None for value in (expected_head, protocol_path,
                                       capacity_path, population_path,
                                       config_path, seed_path,
                                       continuation_policy_path, evidence_root)):
        _fail("freeze input is missing")
    repo = Path(repo)
    if not repo.is_absolute() or repo.is_symlink() or not repo.is_dir():
        _fail("repository path drift")
    evidence = Path(evidence_root)
    if not evidence.is_absolute() or evidence.exists() or evidence.is_symlink():
        _fail("evidence root must be absolute and unused")
    if (type(deadline_seconds) is not int or isinstance(deadline_seconds, bool)
            or not 1 <= deadline_seconds <= MAX_DEADLINE_SECONDS):
        _fail("freeze deadline drift")
    if (type(heartbeat_seconds) is not int or isinstance(heartbeat_seconds, bool)
            or not 1 <= heartbeat_seconds <= 60):
        _fail("freeze heartbeat drift")
    source_git = _head(repo, expected_head)
    _clean_source_tree(repo)
    artifacts, tier = _validate_inputs(
        repo, (("protocol", protocol_path), ("capacity", capacity_path),
               ("population", population_path), ("config", config_path),
               ("seed", seed_path),
               ("continuation-policy", continuation_policy_path)),
        evidence_root=evidence, deadline_seconds=deadline_seconds)
    bindings = _bindings(repo, source_git)
    try:
        runtime = live_runtime_profile()
    except Exception as exc:
        _fail("live runtime profile unavailable", exc)
    if type(runtime) is not dict or not runtime.get("boot_identity"):
        _fail("live runtime profile drift")
    runtime_sha = _object_sha(runtime)
    source_manifest = source_manifest_sha256(source_git, bindings)
    values = {
        "source_git": source_git,
        "source_manifest_sha256": source_manifest,
        "runtime_sha256": runtime_sha,
        "protocol_sha256": artifacts[0][2], "capacity_sha256": artifacts[1][2],
        "population_sha256": artifacts[2][2], "config_sha256": artifacts[3][2],
        "seed_sha256": artifacts[4][2],
        "continuation_policy_sha256": artifacts[5][2],
    }
    freeze = ExecutionFreezeV2(
        **values, evidence_root=str(evidence), boot_identity=runtime["boot_identity"],
        source_bindings=bindings, runtime_profile=runtime,
        artifact_bindings=artifacts, population_tier=tier,
        deadline_seconds=deadline_seconds, heartbeat_seconds=heartbeat_seconds,
        schema=FREEZE_SCHEMA)
    try:
        validate_execution_freeze(freeze)
        raw = freeze.canonical_bytes()
        reopened = __import__(
            "shengji.rl.world_afterstate_v2_execution",
            fromlist=["execution_freeze_from_bytes"]).execution_freeze_from_bytes(raw)
    except Exception as exc:
        _fail("execution freeze validation/roundtrip refused", exc)
    if reopened != freeze:
        _fail("execution freeze roundtrip drift")
    # Do not allow importing/telemetry to have dirtied the checkout.
    _clean_source_tree(repo)
    return freeze


def build_freeze(repo: Path | str, source_git: str | None = None, **kwargs: Any
                 ) -> ExecutionFreezeV2:
    """Keyword-friendly alias used by small operator wrappers."""
    expected = kwargs.pop("expected_head", None) or kwargs.pop("expected_git", None)
    expected = expected or source_git
    if expected is None:
        _fail("expected source Git identity is missing")
    names = {
        "protocol": "protocol_path", "capacity": "capacity_path",
        "population": "population_path", "population_input": "population_path",
        "config": "config_path", "early_stage_config": "config_path",
        "seed": "seed_path", "seed_input": "seed_path",
        "continuation_policy": "continuation_policy_path",
        "continuation_policy_input": "continuation_policy_path",
    }
    for old, new in names.items():
        if old in kwargs and new not in kwargs:
            kwargs[new] = kwargs.pop(old)
    return build_execution_freeze(repo, expected, **kwargs)


build_world_afterstate_v2_freeze = build_freeze


def publish_freeze(path: Path | str, freeze: ExecutionFreezeV2) -> None:
    """Publish only a requested freeze path, exclusively and durably."""
    target = Path(path)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        _fail("freeze output path occupied or not absolute")
    partial = target.with_name(f".{target.name}.partial")
    if partial.exists() or partial.is_symlink():
        _fail("freeze output partial path occupied")
    cursor = target.parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            _fail("freeze output parent symlink")
        cursor = cursor.parent
    try:
        validate_execution_freeze(freeze)
    except Exception as exc:
        _fail("freeze output value refused", exc)
    created_partial = False
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Publish through a same-directory immutable partial.  A crash cannot
        # leave a truncated path masquerading as the reviewed freeze, and the
        # hard-link step retains exclusive no-overwrite semantics.
        with partial.open("xb") as handle:
            created_partial = True
            handle.write(freeze.canonical_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(partial, 0o400)
        os.link(partial, target, follow_symlinks=False)
        partial.unlink()
        descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        if created_partial and partial.exists() and not partial.is_symlink():
            try:
                partial.unlink()
            except OSError:
                pass
        _fail("freeze output publication refused", exc)


__all__ = [
    "FreezeBuilderError", "WorldAfterstateV2FreezeBuilderError",
    "build_execution_freeze", "build_freeze",
    "build_world_afterstate_v2_freeze", "publish_freeze",
]
