#!/usr/bin/env python3
"""Pre-import launcher for the score-redacted Air O0-v2 preflight."""
from __future__ import annotations

import os
import sys
from pathlib import Path


REQUIRED_ENVIRONMENT = {
    "SHENGJI_FAST": "1",
    "SHENGJI_REQUIRE_VOIDS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}
REFUSED_ENVIRONMENT_KEYS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)


def preimport_environment_problems(environment) -> list[str]:
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


def require_preimport_environment(environment=os.environ) -> None:
    problems = preimport_environment_problems(environment)
    if problems:
        raise SystemExit(
            "Suphx O0-v2 preflight refused before import: "
            + "; ".join(problems))


def main(argv: list[str] | None = None) -> int:
    require_preimport_environment()
    server = Path(__file__).resolve().parents[1]
    if str(server) not in sys.path:
        sys.path.insert(0, str(server))
    from shengji.rl.suphx_o0_v2_preflight import cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
