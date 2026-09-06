"""Fresh, matched production decision panels for teacher relabelling.

This module is deliberately an observation boundary.  It makes no model
requests or teacher-quality judgments: a registered production bot plays the
round, while a wider deterministic ballot decides which pre-play states are
retained for a future teacher. Full trajectories include the terminal engine
state; it is never used to select positions or filter deals.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import game
from .atomic_io import publish_exclusive_bytes
from .canonical import canonical_json_bytes
from ..ai.registry import REGISTRY
from ..engine.round import actual_play_after


SCHEMA = "luna-quality-panel-v1"
PRODUCTION_POLICY = "mc-s0-report-lcb"
PRODUCTION_SOURCE_TAG = f"production:{PRODUCTION_POLICY}"
BALLOT_SOURCE_TAG = "production:wide-heuristic-ballot"
REQUESTED_ORDINALS = (0, 12, 24, 36)
MAX_WORKERS = 16
SPLITS = {0: "fit", 1: "validation"}


class QualityPanelError(ValueError):
    """A panel input, shard, or immutable publication is malformed."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _bot_seed(secret: bytes, coordinate: Sequence[object], seat: int,
              label: str) -> int:
    return int.from_bytes(hashlib.sha256(
        secret + canonical_json_bytes([SCHEMA, label, list(coordinate), seat])
    ).digest()[:8], "big") & ((1 << 63) - 1)


def validate_secret(secret: object) -> bytes:
    if type(secret) is not bytes or len(secret) != 32:
        raise QualityPanelError("seed secret must be exactly 32 bytes")
    return secret


def coordinate_tasks(design: game.LunaDesign | None = None) \
        -> tuple[tuple[str, int, int], ...]:
    """Return exactly the fresh design's fixed root coordinates."""
    return tuple((design or game.LunaDesign()).root_coordinates)


def deal_split(coordinate: Sequence[object]) -> str:
    """Assign a complete deal to one split; descendants are never mixed."""
    coord = game.LunaCoordinate(*coordinate)
    return SPLITS[coord.replicate]


def select_stage(decision_ordinal: object, ballot: object) -> bool:
    """Select solely by contested ordinal and ballot width, before play.

    In particular this function does not inspect an engine result or any
    terminal state.  Forced (one-candidate) actions are not ordinal slots.
    """
    if isinstance(decision_ordinal, bool) or not isinstance(decision_ordinal, int):
        return False
    if not isinstance(ballot, Sequence) or isinstance(ballot, (str, bytes)):
        return False
    return len(ballot) >= 2 and decision_ordinal in REQUESTED_ORDINALS


def shard_path(out: Path, coordinate: Sequence[object]) -> Path:
    rank, banker, replicate = game.LunaCoordinate(*coordinate).payload()
    return Path(out) / f"coordinate-{rank}-b{banker}-r{replicate}.json"


def _load_canonical(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityPanelError(f"invalid shard {path.name}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise QualityPanelError(f"non-canonical shard {path.name}")
    return value


def _publish(path: Path, value: Mapping[str, object], *,
             existing_equal_ok: bool = False) -> None:
    publish_exclusive_bytes(path, canonical_json_bytes(dict(value)), mode=0o600,
                            existing_equal_ok=existing_equal_ok)


def _canonical_cards(cards: object) -> list[str]:
    if not isinstance(cards, Sequence) or isinstance(cards, (str, bytes)):
        raise QualityPanelError("production action drift")
    if not cards or any(type(card) is not str for card in cards):
        raise QualityPanelError("production action drift")
    return sorted(cards)


def capture_coordinate(seed_secret: bytes,
                       coordinate: Sequence[object], *,
                       producer_factory: Callable[..., object] | None = None,
                       ballot_factory: Callable[..., object] | None = None
                       ) -> dict[str, object]:
    """Play one fresh root and retain the four requested decision panels.

    Factories are test seams only.  Production defaults are resolved from the
    literal registry entry and ``WideHeuristicBallotBot`` at call time.
    """
    secret = validate_secret(seed_secret)
    coord = game.LunaCoordinate(*coordinate)
    coord_tuple = coord.cluster_key
    root = game.build_root(secret, coord_tuple)
    root_snapshot = game._state_snapshot(root)
    root_seed_value = game.root_seed(secret, coord_tuple)
    root_sha = game.root_identity(root)
    mode = game.root_trump_mode(root)
    production_type = producer_factory or REGISTRY[PRODUCTION_POLICY]
    ballot_type = ballot_factory or game.WideHeuristicBallotBot
    producers = [production_type(seed=_bot_seed(secret, coord_tuple, seat,
                                                  "production"))
                 for seat in range(4)]
    ballots = [ballot_type(seed=_bot_seed(secret, coord_tuple, seat, "ballot"))
               for seat in range(4)]
    stages: list[dict[str, object]] = []
    trajectory: list[dict[str, object]] = []
    contested_ordinal = 0
    action_ordinal = 0
    failed: str | None = None
    while root.phase == "play":
        seat = root.turn
        if seat is None:
            failed = "engine turn absent"
            break
        wide_ballot = [_canonical_cards(cards)
                       for cards in ballots[seat]._candidates(root, seat)]
        if not wide_ballot:
            failed = "empty wide ballot"
            break
        is_contested = len(wide_ballot) >= 2
        ordinal = contested_ordinal if is_contested else None
        before = game._state_snapshot(root)
        production_ballot = [_canonical_cards(cards)
                             for cards in producers[seat]._candidates(root, seat)]
        attempted: list[str] | None = None
        error: str | None = None
        try:
            attempted = _canonical_cards(producers[seat].decide_play(root, seat))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        production_index = (production_ballot.index(attempted)
                            if attempted is not None and attempted in production_ballot
                            else None)
        if select_stage(ordinal, wide_ballot):
            stages.append({
                "decision_ordinal": ordinal,
                "seat": seat,
                "snapshot": before,
                "candidate_ballot": wide_ballot,
                "production_ballot": production_ballot,
                "production_play_index": production_index,
                "attempted_action": attempted,
                "engine_accepted_action": None,
                "source_continuation_policy": PRODUCTION_POLICY,
                "source_tag": BALLOT_SOURCE_TAG,
                "failed_throw": False,
            })
        accepted: list[str] | None = None
        prior_last_trick = root.last_trick
        if error is None:
            try:
                root.play(seat, attempted)  # type: ignore[arg-type]
                # ``play`` can legally accept a failed multi-component throw
                # after coercing it to one component.  The helper reads the
                # engine's recorded cards, never the submitted attempt.
                accepted = actual_play_after(root, seat, prior_last_trick)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
        if stages and stages[-1].get("decision_ordinal") == ordinal:
            stages[-1]["engine_accepted_action"] = accepted
            stages[-1]["engine_error"] = error
            stages[-1]["failed_throw"] = (
                accepted is not None and attempted is not None
                and sorted(attempted) != sorted(accepted))
        trajectory.append({
            "action_ordinal": action_ordinal,
            "decision_ordinal": ordinal,
            "seat": seat,
            "state_before": before,
            "state_after": game._state_snapshot(root),
            "candidate_ballot": wide_ballot,
            "production_ballot": production_ballot,
            "production_play_index": production_index,
            "source_continuation_policy": PRODUCTION_POLICY,
            "attempted_action": attempted,
            "engine_accepted_action": accepted,
            "engine_accepted": accepted is not None,
            "failed_throw": (accepted is not None and attempted is not None
                             and sorted(attempted) != sorted(accepted)),
            "error": error,
        })
        action_ordinal += 1
        if error is not None:
            failed = error
            break
        if is_contested:
            contested_ordinal += 1
    status = "complete" if failed is None and root.phase == "round_end" else "incomplete"
    return {
        "schema": SCHEMA,
        "private": True,
        "coordinate": list(coord_tuple),
        "cluster_key": list(coord_tuple),
        "replicate": coord.replicate,
        "split": deal_split(coord_tuple),
        "source_tag": PRODUCTION_SOURCE_TAG,
        "source_tags": [BALLOT_SOURCE_TAG, PRODUCTION_SOURCE_TAG],
        "source_continuation_policy": PRODUCTION_POLICY,
        "production_policy": PRODUCTION_POLICY,
        "status": status,
        "error": failed,
        "root_seed": root_seed_value,
        "root_sha256": root_sha,
        "root_rank": coord.trump_rank,
        "root_suit": mode,
        "root_trump_mode": mode,
        "root_trump_suit": root.trump_suit,
        "root_snapshot": root_snapshot,
        "requested_ordinals": list(REQUESTED_ORDINALS),
        "missing_requested_ordinals": [ordinal for ordinal in REQUESTED_ORDINALS
                                       if ordinal not in {stage["decision_ordinal"]
                                                         for stage in stages}],
        "stages": stages,
        "trajectory": trajectory,
    }


def _config(secret: bytes, design: game.LunaDesign) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "namespace": design.namespace,
        "seed_commitment_sha256": hashlib.sha256(secret).hexdigest(),
        "coordinates": [list(row) for row in coordinate_tasks(design)],
        "requested_ordinals": list(REQUESTED_ORDINALS),
        "production_policy": PRODUCTION_POLICY,
    }


def summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    ordered = sorted((dict(row) for row in rows),
                     key=lambda row: tuple(row["coordinate"]))
    return {
        "schema": SCHEMA,
        "population": len(ordered),
        "complete": sum(row.get("status") == "complete" for row in ordered),
        "incomplete": sum(row.get("status") != "complete" for row in ordered),
        "stages": sum(len(row.get("stages", ())) for row in ordered),
        "coordinates": [row["coordinate"] for row in ordered],
        "splits": {split: sum(row.get("split") == split for row in ordered)
                   for split in ("fit", "validation")},
        "source_tags": sorted({tag for row in ordered
                                for tag in row.get("source_tags",
                                                   [row.get("source_tag")])}),
    }


def run_panel(seed_secret: bytes, out: Path, *, workers: int = 1,
              design: game.LunaDesign | None = None) -> dict[str, object]:
    """Prepare every fixed coordinate, reopening immutable shards on resume."""
    secret = validate_secret(seed_secret)
    if isinstance(workers, bool) or not isinstance(workers, int) \
            or not 1 <= workers <= MAX_WORKERS:
        raise QualityPanelError("workers must be between 1 and 16")
    design = design or game.LunaDesign()
    out = Path(out)
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    if out.stat().st_mode & 0o077:
        raise QualityPanelError("panel directory must be private (mode 700)")
    config = _config(secret, design)
    config_path = out / "config.json"
    if config_path.exists():
        if _load_canonical(config_path) != config:
            raise QualityPanelError("conflicting resume config")
    else:
        _publish(config_path, config)
    coords = coordinate_tasks(design)
    rows: dict[tuple[str, int, int], dict[str, object]] = {}
    pending: list[tuple[str, int, int]] = []
    for coordinate in coords:
        path = shard_path(out, coordinate)
        if path.exists():
            row = _load_canonical(path)
            if tuple(row.get("coordinate", ())) != coordinate:
                raise QualityPanelError("shard coordinate drift")
            rows[coordinate] = row
        else:
            pending.append(coordinate)

    def record(coordinate, row):
        _publish(shard_path(out, coordinate), row)
        rows[coordinate] = row
        print(json.dumps({"event": "coordinate-finished", "coordinate": coordinate,
                          "status": row["status"], "completed": len(rows),
                          "total": len(coords), "percent": 100 * len(rows) / len(coords)}),
              flush=True)

    if workers == 1:
        for coordinate in pending:
            try:
                row = capture_coordinate(secret, coordinate)
            except Exception as exc:
                row = capture_failure(secret, coordinate, exc)
            record(coordinate, row)
    else:
        with ProcessPoolExecutor(max_workers=workers,
                                 initializer=_limit_native_threads) as pool:
            futures = {pool.submit(_capture_coordinate_task,
                                   (secret, coordinate)): coordinate
                       for coordinate in pending}
            for future in as_completed(futures):
                coordinate = futures[future]
                try:
                    row = future.result()
                except Exception as exc:
                    # Preserve all already-published successes.  A failure is
                    # represented by a private immutable incomplete shard.
                    row = capture_failure(secret, coordinate, exc)
                record(coordinate, row)
    ordered = [rows[coordinate] for coordinate in coords]
    manifest = {"schema": SCHEMA, "private": True,
                "config": config, "summary": summarize(ordered),
                "shards": [{"coordinate": row["coordinate"],
                             "sha256": _sha(row),
                             "status": row["status"]}
                            for row in ordered]}
    _publish(out / "manifest.json", manifest, existing_equal_ok=True)
    return manifest


def _limit_native_threads() -> None:
    """Keep each production capture process at one numerical thread."""
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"


def _capture_coordinate_task(payload: tuple[bytes, tuple[str, int, int]]) \
        -> dict[str, object]:
    _limit_native_threads()
    secret, coordinate = payload
    return capture_coordinate(secret, coordinate)


def capture_failure(seed_secret: bytes, coordinate: Sequence[object],
                    error: BaseException) -> dict[str, object]:
    secret = validate_secret(seed_secret)
    coord = game.LunaCoordinate(*coordinate)
    return {"schema": SCHEMA, "private": True,
            "coordinate": list(coord.cluster_key), "cluster_key": list(coord.cluster_key),
            "replicate": coord.replicate, "split": deal_split(coord.cluster_key),
            "source_tag": PRODUCTION_SOURCE_TAG,
            "source_tags": [BALLOT_SOURCE_TAG, PRODUCTION_SOURCE_TAG],
            "source_continuation_policy": PRODUCTION_POLICY,
            "production_policy": PRODUCTION_POLICY, "status": "incomplete",
            "error": f"{type(error).__name__}: {error}", "root_seed": None,
            "root_sha256": None, "root_rank": coord.trump_rank, "root_suit": None,
            "root_snapshot": None, "requested_ordinals": list(REQUESTED_ORDINALS),
            "missing_requested_ordinals": list(REQUESTED_ORDINALS),
            "stages": [], "trajectory": []}


__all__ = ["BALLOT_SOURCE_TAG", "MAX_WORKERS", "PRODUCTION_POLICY",
           "PRODUCTION_SOURCE_TAG", "REQUESTED_ORDINALS",
           "SCHEMA", "QualityPanelError", "capture_coordinate",
           "capture_failure", "coordinate_tasks", "deal_split", "run_panel",
           "select_stage", "shard_path", "summarize", "validate_secret"]
