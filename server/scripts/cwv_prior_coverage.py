#!/usr/bin/env python3
"""Offline W32 proposal coverage by a public prior head.

This is a proposal-agreement diagnostic.  It is not a search-quality,
strength, ground-truth, or confirmation screen.  The panel is caller-supplied
and must contain only already-opened ``fit`` snapshots; no games are played.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from shengji.ai.cwv_puct import PublicPriorHead
from shengji.ai.cwv_policy import file_sha256, shared_evaluator
from shengji.ai.mcbot import MCBot
from shengji.engine.combos import decompose
from shengji.luna.game import _round_from_snapshot, _state_snapshot
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig


SCHEMA = "cwv-prior-coverage-v1"
DEFAULT_SEED = 20260908
DEFAULT_LIMIT = 52
DEFAULT_DEADLINE_SECONDS = 300
DEFAULT_PREFIXES = (16, 32, 64, 128)


class PriorCoverageError(ValueError):
    """The diagnostic input or a model's proposal population is invalid."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def action_key(action: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(str(card) for card in action))


def action_id(action: Sequence[str]) -> str:
    """Opaque action identity; card strings are deliberately not published."""
    return hashlib.sha256(_json_bytes(list(action_key(action)))).hexdigest()


def rank_indices(scores: Sequence[float], actions: Sequence[Sequence[str]]) -> list[int]:
    """Deterministic descending rank, with action identity as the tie-break."""
    values = np.asarray(scores, dtype=np.float64)
    if values.ndim != 1 or len(values) != len(actions) or not np.isfinite(values).all():
        raise PriorCoverageError("ranking requires one finite score per action")
    keys = [action_key(action) for action in actions]
    if len(set(keys)) != len(keys):
        raise PriorCoverageError("ranking population contains duplicate actions")
    return sorted(range(len(actions)), key=lambda i: (-float(values[i]), keys[i]))


def _index_map(actions: Sequence[Sequence[str]]) -> dict[tuple[str, ...], int]:
    result: dict[tuple[str, ...], int] = {}
    for index, action in enumerate(actions):
        key = action_key(action)
        if key in result:
            raise PriorCoverageError("action population contains duplicate actions")
        result[key] = index
    return result


def prior_prefix_indices(actions: Sequence[Sequence[str]], scores: Sequence[float],
                         incumbent: Sequence[str], prefix: int) -> list[int]:
    """Return incumbent plus the top ``prefix`` *other* legal actions."""
    if isinstance(prefix, bool) or not isinstance(prefix, int) or prefix < 1:
        raise PriorCoverageError("prior prefix must be a positive integer")
    index = _index_map(actions)
    incumbent_key = action_key(incumbent)
    if incumbent_key not in index:
        raise PriorCoverageError("prior population omitted the incumbent")
    order = rank_indices(scores, actions)
    others = [i for i in order if i != index[incumbent_key]]
    return [index[incumbent_key], *others[:prefix]]


def hybrid_indices(actions: Sequence[Sequence[str]], value_scores: Sequence[float],
                   prior_scores: Sequence[float], incumbent: Sequence[str],
                   *, value_count: int = 2, prior_count: int = 2,
                   proposed_count: int = 4) -> list[int]:
    """Top-2 value + top-2 prior, deduplicated and value-filled to four."""
    if min(value_count, prior_count, proposed_count) < 1:
        raise PriorCoverageError("hybrid counts must be positive")
    index = _index_map(actions)
    inc_key = action_key(incumbent)
    if inc_key not in index:
        raise PriorCoverageError("hybrid population omitted the incumbent")
    inc = index[inc_key]
    value_order = [i for i in rank_indices(value_scores, actions) if i != inc]
    prior_order = [i for i in rank_indices(prior_scores, actions) if i != inc]
    chosen: list[int] = []
    for i in value_order[:value_count] + prior_order[:prior_count]:
        if i not in chosen:
            chosen.append(i)
    for i in value_order:
        if len(chosen) >= proposed_count:
            break
        if i not in chosen:
            chosen.append(i)
    return [inc, *chosen[:proposed_count]]


class W32ProposalBot(CWVShortlistBot):
    """CWV shortlist bot retaining full legal action scores for diagnostics."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.full_actions: list[list[str]] | None = None
        self.full_means: np.ndarray | None = None
        self.ranking_seconds = 0.0

    def _means(self, rnd, seat, actions, worlds):
        started = time.perf_counter()
        means = super()._means(rnd, seat, actions, worlds)
        self.ranking_seconds += time.perf_counter() - started
        self.full_actions = [list(action) for action in actions]
        self.full_means = np.asarray(means, dtype=np.float64).copy()
        return means


def production_tractor_lock(rnd, seat: int) -> bool:
    """Report the production lock condition without applying its early return."""
    if not MCBot.TRACTOR_LOCK or rnd.trick is None or rnd.trick.plays:
        return False
    pick = MCBot(seed=0).canonical_lead(rnd, seat)
    parts = decompose(pick, rnd.ordering).components
    return len(parts) == 1 and parts[0].pair_len >= 2


def _verify_legal_population(rnd, seat: int, actions: Sequence[Sequence[str]], incumbent):
    if seat != rnd.turn:
        raise PriorCoverageError("root actor does not match snapshot turn")
    legal = enumerate_legal(rnd, seat, cap=None, must_include=[list(incumbent)])
    keys = [action_key(action) for action in actions]
    legal_keys = [action_key(action) for action in legal.actions]
    if (len(keys) != len(legal_keys) or set(keys) != set(legal_keys)
            or len(set(keys)) != len(keys)):
        raise PriorCoverageError("W32 ranking did not receive the full legal population")
    if action_key(incumbent) not in set(keys):
        raise PriorCoverageError("W32 ranking population omitted incumbent")
    return len(legal_keys)


def _prior_scores(prior_head, rnd, seat: int, actions: Sequence[Sequence[str]], legal_count: int):
    if seat != rnd.turn:
        raise PriorCoverageError("prior root actor does not match snapshot turn")
    if len(actions) != legal_count:
        raise PriorCoverageError("prior received a truncated legal population")
    started = time.perf_counter()
    scores = np.asarray(prior_head.probabilities(rnd, seat, actions), dtype=np.float64)
    elapsed = time.perf_counter() - started
    if scores.shape != (legal_count,) or not np.isfinite(scores).all():
        raise PriorCoverageError("prior returned one finite score per legal action")
    if np.any(scores < 0) or not math.isclose(float(scores.sum()), 1.0, rel_tol=0, abs_tol=1e-5):
        raise PriorCoverageError("prior probabilities do not form a distribution")
    return scores, elapsed


def _metric(actions, selected, baseline, full_best, *, stage, prior_rank, value_rank,
            legal_count, ranking_seconds, prior_seconds):
    chosen = {action_key(actions[i]) for i in selected}
    base_keys = {action_key(actions[i]) for i in baseline}
    retained = len(chosen & base_keys)
    best_retained = action_key(actions[full_best]) in chosen
    return {
        "stage": stage,
        "number_proposed": max(0, len(selected) - 1),
        "selected_action_ids": [action_id(actions[i]) for i in selected],
        "proposed_action_ids": [action_id(actions[i]) for i in selected[1:]],
        "top4_baseline_retained": retained,
        "top4_baseline_total": len(baseline),
        "top4_baseline_retention": (retained / len(baseline) if baseline else None),
        "best_w32_alternative_retained": best_retained,
        "legal_count": legal_count,
        "ranking_cost": {"worlds": 32, "evaluations": legal_count * 32,
                          "seconds": ranking_seconds},
        "prior_cost": {"legal_rows": legal_count, "seconds": prior_seconds,
                        "forward_calls": 1},
        "selected_prior_ranks": [prior_rank[i] for i in selected if i in prior_rank],
        "selected_value_ranks": [value_rank[i] for i in selected if i in value_rank],
    }


def analyze_snapshot(snapshot: Mapping[str, Any], *, evaluator=None, prior_head=None,
                     value_checkpoint: str | None = None,
                     prior_checkpoint: str | None = None, seed: int = DEFAULT_SEED,
                     prefixes: Sequence[int] = DEFAULT_PREFIXES) -> dict:
    """Analyze one supplied root snapshot without exposing its private cards."""
    if type(snapshot) is not dict:
        raise PriorCoverageError("snapshot must be an object")
    rnd = _round_from_snapshot(snapshot)
    if rnd.phase != "play" or rnd.turn is None:
        raise PriorCoverageError("snapshot must be an active play state")
    seat = rnd.turn
    before_state = digest(_state_snapshot(rnd))
    tractor_lock = production_tractor_lock(rnd, seat)
    bot = None
    if evaluator is None:
        if not value_checkpoint:
            raise PriorCoverageError("value checkpoint is required")
        evaluator = shared_evaluator(value_checkpoint, threads=1, encoding="mlp-static")
    if prior_head is None:
        if not prior_checkpoint:
            raise PriorCoverageError("prior checkpoint is required")
        prior_head = PublicPriorHead(prior_checkpoint)
    bot = W32ProposalBot(
        evaluator, seed=seed,
        config=CWVShortlistConfig(worlds=32, alternatives=4, batch_size=128),
        reuse_successors=True)
    bot_rng = bot.rng.getstate()
    try:
        selected = bot._candidates(rnd, seat)
        detail = bot.last_shortlist or {}
        if int(detail.get("legal_count", len(selected))) <= 1:
            return {"status": "skipped", "skip_reason": "forced",
                    "state_hash": before_state, "seat": seat,
                    "legal_count": detail.get("legal_count", 1),
                    "production_tractor_lock": tractor_lock}
        actions = bot.full_actions
        means = bot.full_means
        if actions is None or means is None:
            raise PriorCoverageError("W32 did not retain full ranking population")
        incumbent = detail.get("incumbent")
        if not incumbent:
            raise PriorCoverageError("W32 did not retain incumbent")
        legal_count = _verify_legal_population(rnd, seat, actions, incumbent)
        prior, prior_seconds = _prior_scores(prior_head, rnd, seat, actions, legal_count)
        index = _index_map(actions)
        base = index[action_key(incumbent)]
        prior_order = [i for i in rank_indices(prior, actions) if i != base]
        value_order = [i for i in rank_indices(means, actions) if i != base]
        prior_rank = {i: rank + 1 for rank, i in enumerate(prior_order)}
        value_rank = {i: rank + 1 for rank, i in enumerate(value_order)}
        baseline = [index[action_key(action)] for action in detail["shortlist"][1:]]
        full_best = value_order[0] if value_order else base
        metrics = {"label": "W32-proposal agreement; NOT true best moves, strength, or confirmation"}
        for prefix in prefixes:
            chosen = prior_prefix_indices(actions, prior, incumbent, prefix)
            metrics[f"prior_prefix_{prefix}"] = _metric(
                actions, chosen, baseline, full_best, stage=f"prior_prefix_{prefix}",
                prior_rank=prior_rank, value_rank=value_rank,
                legal_count=legal_count, ranking_seconds=bot.ranking_seconds,
                prior_seconds=prior_seconds)
        hybrid = hybrid_indices(actions, means, prior, incumbent)
        metrics["hybrid_top2value_plus_top2prior"] = _metric(
            actions, hybrid, baseline, full_best, stage="hybrid_top2value_plus_top2prior",
            prior_rank=prior_rank, value_rank=value_rank,
            legal_count=legal_count, ranking_seconds=bot.ranking_seconds,
            prior_seconds=prior_seconds)
        row = {
            "status": "complete", "state_hash": before_state, "seat": seat,
            "legal_count": legal_count, "production_count": detail.get("production_count"),
            "w32_shortlist_count": len(selected),
            "production_tractor_lock": tractor_lock,
            "identity": {"value_checkpoint": value_checkpoint,
                          "prior_checkpoint": prior_checkpoint,
                          "value_evaluator": getattr(evaluator, "identity", lambda: None)(),
                          "prior_head": getattr(prior_head, "identity", lambda: None)()},
            "metrics": metrics,
            "rankings": {
                "prior": [{"action_id": action_id(actions[i]), "rank": rank + 1}
                           for rank, i in enumerate(prior_order)],
                "w32_value": [{"action_id": action_id(actions[i]), "rank": rank + 1}
                              for rank, i in enumerate(value_order)],
            },
            "actions": [{"action_id": action_id(action),
                         "prior_rank": prior_rank.get(i),
                         "w32_value_rank": value_rank.get(i),
                         "baseline_w32": i in baseline,
                         "incumbent": i == base,
                         "stage": ("incumbent" if i == base else
                                   "w32_baseline" if i in baseline else "legal")}
                        for i, action in enumerate(actions)],
        }
        return row
    finally:
        after_state = digest(_state_snapshot(rnd))
        if after_state != before_state:
            raise PriorCoverageError("diagnostic mutated input snapshot")
        if bot is not None and bot.rng.getstate() != bot_rng:
            raise PriorCoverageError("diagnostic advanced bot RNG")


def load_panel(path: str | Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PriorCoverageError("panel is not valid JSON") from exc
    if type(value) is not dict or type(value.get("entries")) is not list:
        raise PriorCoverageError("panel must be {entries: [...]}")
    entries = value["entries"]
    seen: set[str] = set()
    for entry in entries:
        if type(entry) is not dict or type(entry.get("id")) is not str:
            raise PriorCoverageError("panel entry needs a string id")
        if entry["id"] in seen:
            raise PriorCoverageError("panel contains duplicate ids")
        seen.add(entry["id"])
        provenance = entry.get("provenance")
        if type(provenance) is not dict or provenance.get("split") != "fit":
            raise PriorCoverageError("panel must contain already-opened FIT entries only")
        if type(entry.get("snapshot")) is not dict:
            raise PriorCoverageError("panel entry needs a snapshot")
    return entries


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(_json_bytes(value))
    temporary.replace(path)


def _parse_prefixes(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("prefixes must be comma-separated integers") from exc
    if not result or any(prefix < 1 for prefix in result) or len(set(result)) != len(result):
        raise argparse.ArgumentTypeError("prefixes must be distinct positive integers")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--value-checkpoint", required=True, type=Path)
    parser.add_argument("--prior-checkpoint", required=True, type=Path)
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--prefixes", type=_parse_prefixes,
                        default=DEFAULT_PREFIXES)
    parser.add_argument("--deadline-seconds", type=float, default=DEFAULT_DEADLINE_SECONDS)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.deadline_seconds <= 0:
        parser.error("limit and deadline-seconds must be positive")
    for name, path in (("value checkpoint", args.value_checkpoint),
                       ("prior checkpoint", args.prior_checkpoint),
                       ("panel", args.panel)):
        if not path.is_file():
            parser.error(f"{name} not found: {path}")
    entries = load_panel(args.panel)[:args.limit]
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    config = {
        "schema": SCHEMA, "scope": "W32-proposal agreement diagnostic",
        "label": "NOT true best moves, strength, or confirmation",
        "value_checkpoint_sha256": file_sha256(args.value_checkpoint),
        "prior_checkpoint_sha256": file_sha256(args.prior_checkpoint),
        "panel_sha256": file_sha256(args.panel), "root_count": len(entries),
        "limit": args.limit, "seed": args.seed, "prefixes": list(args.prefixes),
        "deadline_seconds": args.deadline_seconds,
        "panel_population": "caller-supplied already-opened FIT entries only",
    }
    _write_json(args.out / "config.json", config)
    rows: list[dict] = []
    progress = {"schema": SCHEMA, "root_count": len(entries), "completed_rows": 0,
                "progress": 0.0, "eta_seconds": None, "status": "running"}
    _write_json(args.out / "progress.json", progress)
    _write_json(args.out / "rows.json", [])
    try:
        evaluator = shared_evaluator(str(args.value_checkpoint), threads=1,
                                     encoding="mlp-static")
        prior_head = PublicPriorHead(str(args.prior_checkpoint))
        for index, entry in enumerate(entries):
            elapsed = time.monotonic() - started
            if elapsed >= args.deadline_seconds:
                progress["status"] = "deadline"
                break
            try:
                row = analyze_snapshot(entry["snapshot"], evaluator=evaluator,
                                       prior_head=prior_head,
                                       value_checkpoint=str(args.value_checkpoint),
                                       prior_checkpoint=str(args.prior_checkpoint),
                                       seed=args.seed + index,
                                       prefixes=args.prefixes)
                row["id"] = entry["id"]
                row["index"] = index
            except Exception as exc:
                row = {"status": "error", "id": entry["id"], "index": index,
                       "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            _write_json(args.out / "rows.json", rows)
            complete = len(rows)
            elapsed = time.monotonic() - started
            eta = (elapsed / complete * (len(entries) - complete)) if complete else None
            progress.update({"completed_rows": complete,
                             "progress": complete / len(entries) if entries else 1.0,
                             "eta_seconds": eta})
            _write_json(args.out / "progress.json", progress)
        else:
            progress["status"] = ("complete_with_errors" if any(
                row.get("status") == "error" for row in rows) else "complete")
    except BaseException as exc:
        progress.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        _write_json(args.out / "progress.json", progress)
        raise
    finally:
        progress["completed_rows"] = len(rows)
        progress["progress"] = len(rows) / len(entries) if entries else 1.0
        _write_json(args.out / "progress.json", progress)
    _write_json(args.out / "summary.json", {
        "schema": SCHEMA, "config": config, "root_count": len(entries),
        "completed_rows": len(rows), "status": progress["status"], "rows": rows,
        "status_counts": dict(Counter(row.get("status") for row in rows)),
        "skip_counts": dict(Counter(row.get("skip_reason") for row in rows
                                     if row.get("status") == "skipped")),
        "label": "W32-proposal agreement; NOT true best moves, strength, or confirmation",
    })
    return 0 if progress["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
