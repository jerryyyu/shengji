#!/usr/bin/env python3
"""Pre-import launcher for the frozen Direct-Q learning screen.

The behavioral modules read some experiment flags while they import.  Keep
this launcher stdlib-only and reject the environment before importing any
``shengji`` package code.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


REQUIRED_ENVIRONMENT = {
    "SHENGJI_FAST": "1",
    "SHENGJI_REQUIRE_VOIDS": "1",
}
REFUSED_ENVIRONMENT_KEYS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)


def preimport_environment_problems(
        environment: dict[str, str] | os._Environ[str]) -> list[str]:
    problems = []
    for name, expected in REQUIRED_ENVIRONMENT.items():
        if environment.get(name) != expected:
            problems.append(f"set {name}={expected} exactly")
    present = sorted(
        name for name in REFUSED_ENVIRONMENT_KEYS if name in environment)
    if present:
        problems.append(
            "experimental sampler/ballot keys must be absent: "
            f"{present}")
    return problems


def require_preimport_environment(
        environment: dict[str, str] | os._Environ[str] = os.environ) -> None:
    problems = preimport_environment_problems(environment)
    if problems:
        raise SystemExit("Direct-Q screen refused before import: "
                         + "; ".join(problems))


def main(argv: list[str] | None = None) -> int:
    require_preimport_environment()
    server = Path(__file__).resolve().parents[1]
    if str(server) not in sys.path:
        sys.path.insert(0, str(server))
    from shengji.rl.douzero_learning_screen import cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
