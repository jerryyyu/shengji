#!/usr/bin/env python3
"""Run pytest against the checkout containing this script.

This entrypoint is deliberately independent of the package installation.  It
is useful when a shared virtualenv may still have an editable install from a
different checkout.
"""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys
from types import ModuleType


SERVER_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = SERVER_DIR / "shengji"


class CheckoutError(RuntimeError):
    """The requested checkout or engine mode cannot be authenticated."""


def _origin(module: ModuleType, label: str) -> Path:
    value = getattr(module, "__file__", None)
    if not value:
        raise CheckoutError(f"{label} has no filesystem origin")
    return Path(value).resolve()


def _inside_package(path: Path) -> bool:
    try:
        path.relative_to(PACKAGE_DIR)
    except ValueError:
        return False
    return True


def _prepare_imports(engine: str) -> tuple[ModuleType, ModuleType]:
    """Select the source tree and authenticate its important imports."""

    # Keep the target ahead of both the interpreter's script directory and any
    # inherited PYTHONPATH/editable-install entries.
    target = str(SERVER_DIR)
    sys.path[:] = [entry for entry in sys.path if entry != target]
    sys.path.insert(0, target)
    # Tests also launch Python CLIs, including with -P from foreign working
    # directories. sys.path changes alone are not inherited by those children.
    # Resolve existing relative entries before chdir so their meaning is kept.
    inherited = os.environ.get("PYTHONPATH")
    child_paths = [] if inherited is None else [
        str(Path(entry or ".").resolve()) for entry in inherited.split(os.pathsep)
    ]
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [target, *(entry for entry in child_paths if entry != target)]
    )
    os.chdir(SERVER_DIR)

    if engine == "pure":
        os.environ.pop("SHENGJI_FAST", None)
    else:
        os.environ["SHENGJI_FAST"] = "1"

    try:
        shengji = importlib.import_module("shengji")
    except Exception as exc:
        if engine == "compiled":
            raise CheckoutError(
                f"compiled engine unavailable; refusing fallback: {exc}"
            ) from exc
        raise CheckoutError(
            f"could not activate pure engine from {SERVER_DIR}: {exc}"
        ) from exc

    expected_origin = (PACKAGE_DIR / "__init__.py").resolve()
    actual_origin = _origin(shengji, "shengji")
    if actual_origin != expected_origin:
        raise CheckoutError(
            f"shengji resolved to {actual_origin}, expected {expected_origin}"
        )

    try:
        legal = importlib.import_module("shengji.engine.legal")
    except Exception as exc:
        raise CheckoutError(
            f"could not import legal validator from {SERVER_DIR}: {exc}"
        ) from exc
    legal_origin = _origin(legal, "shengji.engine.legal")
    if not _inside_package(legal_origin):
        raise CheckoutError(
            f"shengji.engine.legal resolved outside checkout: {legal_origin}"
        )
    follow = getattr(legal, "validate_follow", None)
    owner_name = getattr(follow, "__module__", None)
    if not callable(follow) or not owner_name:
        raise CheckoutError("shengji.engine.legal.validate_follow is unavailable")
    expected_owner = (
        "shengji.engine._fast" if engine == "compiled" else "shengji.engine.legal"
    )
    if owner_name != expected_owner:
        raise CheckoutError(
            f"validate_follow owner is {owner_name!r}, expected {expected_owner!r}"
        )
    try:
        owner = importlib.import_module(owner_name)
    except Exception as exc:
        raise CheckoutError(
            f"could not import validate_follow owner {owner_name}: {exc}"
        ) from exc
    owner_origin = _origin(owner, owner_name)
    if not _inside_package(owner_origin):
        raise CheckoutError(
            f"validate_follow resolved outside checkout: {owner_origin}"
        )

    if engine == "compiled":
        try:
            fast = importlib.import_module("shengji.engine.fast")
        except Exception as exc:
            raise CheckoutError(
                f"compiled engine unavailable; refusing fallback: {exc}"
            ) from exc
        if not getattr(fast, "HAVE_FAST", False) or getattr(fast, "_fast", None) is None:
            raise CheckoutError(
                "compiled engine unavailable; refusing pure-Python fallback"
            )

    return shengji, legal


def _arguments(argv: list[str] | None) -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(
        description="run pytest using this checkout's source tree",
        allow_abbrev=False,
    )
    parser.add_argument("--engine", choices=("pure", "compiled"), required=True)
    words = list(sys.argv[1:] if argv is None else argv)
    if "--" in words:
        boundary = words.index("--")
        prefix, pytest_args = words[:boundary], words[boundary + 1:]
    else:
        prefix, pytest_args = words, []
    parsed = parser.parse_args(prefix)
    return parsed.engine, pytest_args


def main(argv: list[str] | None = None) -> int:
    engine, pytest_args = _arguments(argv)
    print(f"checkout source: {SERVER_DIR}", flush=True)
    print(f"engine mode: {engine}", flush=True)
    try:
        _prepare_imports(engine)
    except CheckoutError as exc:
        print(f"test checkout refused: {exc}", file=sys.stderr, flush=True)
        return 2

    import pytest

    return int(pytest.main(pytest_args))


if __name__ == "__main__":
    raise SystemExit(main())
