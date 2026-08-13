"""Strict read-only plumbing shared by terminal result reviewers."""
from __future__ import annotations

import hashlib
import importlib
import importlib.machinery
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


sys.dont_write_bytecode = True


class ReviewRefused(RuntimeError):
    pass


def _identity(
        info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_regular(path: Path, label: str, *, retain: bool) -> tuple[bytes, str]:
    """Read and hash one inode, refusing links or pathname replacement."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReviewRefused(f"{label} is not a regular unlinked file") from exc
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1):
            raise ReviewRefused(f"{label} is not a regular unlinked file")
        while block := os.read(descriptor, 1 << 20):
            digest.update(block)
            if retain:
                chunks.append(block)
        after = os.fstat(descriptor)
        try:
            pathname = path.lstat()
        except OSError as exc:
            raise ReviewRefused(f"{label} pathname changed while reading") \
                from exc
        if (_identity(before) != _identity(after)
                or _identity(pathname) != _identity(after)):
            raise ReviewRefused(f"{label} changed while reading")
    finally:
        os.close(descriptor)
    value = b"".join(chunks)
    if retain and len(value) != after.st_size:
        raise ReviewRefused(f"{label} changed while reading")
    return value, digest.hexdigest()


def read_regular_bytes(path: os.PathLike[str] | str, label: str) -> bytes:
    return _read_regular(Path(path), label, retain=True)[0]


def sha256(path: os.PathLike[str] | str) -> str:
    return _read_regular(Path(path), str(path), retain=False)[1]


def require_sha256(path: os.PathLike[str] | str, expected: str,
                   label: str) -> None:
    if sha256(path) != expected:
        raise ReviewRefused(f"{label} changed during review")


def regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_nlink == 1)


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReviewRefused(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path, label: str) -> dict:
    return load_json_with_sha256(path, label)[0]


def load_json_with_sha256(path: Path, label: str) -> tuple[dict, str]:
    raw, digest = _read_regular(path, label, retain=True)
    try:
        value = json.loads(
            raw, object_pairs_hook=_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReviewRefused(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ReviewRefused(f"{label} is not an object")
    return value, digest


def exact_source(repo: Path, git: str, modules: dict[str, str]) -> None:
    repo = repo.resolve()
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            text=True, capture_output=True).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=repo, check=True, text=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReviewRefused("source repository cannot be authenticated") from exc
    if head != git or dirty:
        raise ReviewRefused("source Git/tracked-tree drift")
    for logical, expected in modules.items():
        path = repo / logical
        if not regular_unlinked(path) or sha256(path) != expected:
            raise ReviewRefused(f"source module drift: {logical}")


def _tracked_module_paths(repo: Path, git: str) -> dict[str, str]:
    try:
        raw = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "--name-only", git, "--",
             "server/scripts", "server/shengji"], cwd=repo, check=True,
            capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReviewRefused("source module graph cannot be authenticated") \
            from exc
    modules: dict[str, str] = {}
    for encoded in raw.split(b"\0"):
        if not encoded:
            continue
        logical = encoded.decode()
        path = Path(logical)
        if path.suffix != ".py":
            continue
        if path.parts[:2] == ("server", "scripts") and len(path.parts) == 3:
            module_name = path.stem
        elif path.parts[:2] == ("server", "shengji"):
            parts = list(path.with_suffix("").parts[1:])
            if parts[-1] == "__init__":
                parts.pop()
            module_name = ".".join(parts)
        else:
            continue
        previous = modules.setdefault(module_name, logical)
        if previous != logical:
            raise ReviewRefused(f"ambiguous source module: {module_name}")
    return modules


def _git_blob_sha256(repo: Path, git: str, logical: str) -> str:
    try:
        value = subprocess.run(
            ["git", "cat-file", "blob", f"{git}:{logical}"], cwd=repo,
            check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReviewRefused(f"source module is not tracked: {logical}") \
            from exc
    return hashlib.sha256(value).hexdigest()


def import_script(repo: Path, name: str, logical: str,
                  dependencies: dict[str, str] | None = None, *,
                  git: str | None = None):
    expected_modules = {name: logical, **(dependencies or {})}
    tracked = _tracked_module_paths(repo, git) if git is not None else {}
    protected = set(expected_modules) | set(tracked)
    preloaded = sorted(
        module for module in sys.modules
        if module in protected or module == "shengji"
        or module.startswith("shengji."))
    if preloaded:
        raise ReviewRefused(
            "refusing preloaded source module(s): " + ", ".join(preloaded))
    scripts = str((repo / "server" / "scripts").resolve())
    server = str((repo / "server").resolve())
    sys.path[:0] = [scripts, server]
    importlib.invalidate_caches()
    module = importlib.import_module(name)
    if module is not sys.modules.get(name):
        raise ReviewRefused(f"import identity drift: {name}")
    for imported_name, imported_logical in expected_modules.items():
        imported = sys.modules.get(imported_name)
        imported_path = getattr(imported, "__file__", None)
        if (not isinstance(imported_path, str)
                or Path(imported_path).resolve()
                != (repo / imported_logical).resolve()):
            raise ReviewRefused(f"import path drift: {imported_name}")
    if git is not None:
        shengji_root = (repo / "server" / "shengji").resolve()
        for imported_name, imported in sorted(sys.modules.items()):
            if imported is None:
                continue
            imported_logical = tracked.get(imported_name)
            if imported_logical is not None:
                imported_path = Path(str(getattr(imported, "__file__", "")))
                expected_path = (repo / imported_logical).resolve()
                if (imported_path.resolve() != expected_path
                        or not regular_unlinked(expected_path)
                        or sha256(expected_path)
                        != _git_blob_sha256(repo, git, imported_logical)):
                    raise ReviewRefused(
                        f"import source drift: {imported_name}")
            elif imported_name == "shengji" \
                    or imported_name.startswith("shengji."):
                imported_path = Path(str(getattr(imported, "__file__", "")))
                try:
                    imported_path.resolve().relative_to(shengji_root)
                except (OSError, ValueError) as exc:
                    raise ReviewRefused(
                        f"import path drift: {imported_name}") from exc
                if not regular_unlinked(imported_path):
                    raise ReviewRefused(
                        f"import source drift: {imported_name}")
                if not any(str(imported_path).endswith(suffix)
                           for suffix in importlib.machinery.EXTENSION_SUFFIXES):
                    raise ReviewRefused(
                        f"untracked import source: {imported_name}")
    return module


def marker(prefix: str, claim: dict) -> str:
    return prefix + json.dumps(claim, sort_keys=True, separators=(",", ":"))


def reviewer_sources(*paths: Path) -> dict[str, str]:
    return {path.name: sha256(path) for path in paths}
