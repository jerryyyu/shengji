"""Strict read-only plumbing shared by terminal result reviewers."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path


sys.dont_write_bytecode = True


class ReviewRefused(RuntimeError):
    pass


def sha256(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
    if not regular_unlinked(path):
        raise ReviewRefused(f"{label} is not a regular unlinked file")
    try:
        value = json.loads(
            path.read_text(), object_pairs_hook=_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReviewRefused(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ReviewRefused(f"{label} is not an object")
    return value


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


def import_script(repo: Path, name: str, logical: str,
                  dependencies: dict[str, str] | None = None):
    expected_modules = {name: logical, **(dependencies or {})}
    preloaded = sorted(module for module in expected_modules
                       if module in sys.modules)
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
    return module


def marker(prefix: str, claim: dict) -> str:
    return prefix + json.dumps(claim, sort_keys=True, separators=(",", ":"))


def reviewer_sources(*paths: Path) -> dict[str, str]:
    return {path.name: sha256(path) for path in paths}
