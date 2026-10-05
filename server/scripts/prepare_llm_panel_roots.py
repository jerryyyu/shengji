"""Prepare one private, provider-free common root source for the Sol panel.

This command performs only the engine's deal/declaration/bury setup with four
SmartBots.  It never enters play and emits the same canonical root snapshots
consumed by :mod:`w32_llm_benchmark`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
from typing import Sequence

from shengji.ai import env
from shengji.ai.smart import SmartBot
from shengji.engine.cards import RANKS
from shengji.engine.game import Game
from shengji.luna.atomic_io import publish_exclusive_bytes
from shengji.luna.canonical import canonical_json_bytes

from scripts.w32_llm_benchmark import (
    PANEL_POLICIES,
    ROOT_SOURCE_SCHEMA,
    _panel_setup_identity,
    _root_snapshot,
    _sha,
    parse_seeds,
)


class RootPreparationRefusal(ValueError):
    """The requested immutable root source cannot be created safely."""


def _publish(path: Path, value: object) -> None:
    publish_exclusive_bytes(path, canonical_json_bytes(value), mode=0o400)


def prepare_roots(*, output: str | Path,
                  seeds: Sequence[int | str]) -> dict[str, object]:
    """Prepare and seal roots in the caller's explicit seed order."""
    try:
        seed_order = parse_seeds([str(seed) for seed in seeds])
    except ValueError as exc:
        raise RootPreparationRefusal(str(exc)) from exc
    if not seed_order:
        raise RootPreparationRefusal("seeds cannot be empty")
    output_path = Path(output).expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        raise RootPreparationRefusal("output must be a fresh path")

    setup = _panel_setup_identity()
    roots: dict[int, dict[str, object]] = {}
    hashes: dict[str, str] = {}
    for index, seed in enumerate(seed_order):
        rank_index = index % len(RANKS)
        game = Game(random.Random(seed), start_level=RANKS[rank_index])
        # A preselected banker makes the source independent of declaration
        # choices while retaining the engine's normal setup path.
        game.banker = seed % 4
        env.prepare_round(game, [SmartBot() for _ in range(4)])
        root = _root_snapshot(game, seed, rank_index)
        roots[seed] = root
        hashes[str(seed)] = _sha(root)

    config = {
        "schema": ROOT_SOURCE_SCHEMA,
        "seeds": list(seed_order),
        "seed_order": list(seed_order),
        "policies": list(PANEL_POLICIES),
        "setup": setup,
        "claim": "common roots only; no gameplay, provider, or model calls",
    }
    result = {
        "schema": ROOT_SOURCE_SCHEMA,
        "mode": "roots-only",
        "root_schema": "w32-llm-benchmark-root-v1",
        "roots_only": True,
        "gameplay": False,
        "provider_calls": 0,
        "model_calls": 0,
        "policies": list(PANEL_POLICIES),
        "seeds": list(seed_order),
        "setup": setup,
        "config": config,
        "roots": hashes,
    }

    try:
        output_path.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise RootPreparationRefusal("output must be a fresh path") from exc
    try:
        for seed in seed_order:
            _publish(output_path / f"root-{seed}.json", roots[seed])
        _publish(output_path / "result.json", result)
    except Exception:
        # The directory is intentionally left immutable and inspectable if a
        # publication fails; no completed result.json then exists to import.
        raise
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = prepare_roots(output=args.output, seeds=args.seeds)
    except (OSError, RootPreparationRefusal, ValueError) as exc:
        build_parser().error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
