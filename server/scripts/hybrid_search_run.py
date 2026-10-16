"""Sequential JSONL runner for bounded hybrid-search diagnostics.

This runner is cooperative: the supplied wall budget is checked at stage
boundaries and through the consumers' gate, but it is not a process timeout.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from shengji.train.lead_root_capture import restore_with_ledger
from scripts.hybrid_search_probe import run_hybrid_search_probe, score_true_deal_regret


MAX_LINE_BYTES = 2 * 1024 * 1024


def ranking_attribution(probe, regret):
    """Separate selection-rule removal from changed values on one ballot.

    Positive deltas mean better true-deal value. This is an algebraic
    decomposition, not a causal strength estimate or an extra search arm.
    """
    means = probe["baseline"]["means"]
    truth = regret["values"]
    if not means or len(means) != len(truth) or any(
            not math.isfinite(float(v)) for v in (*means, *truth)):
        raise ValueError("attribution requires finite aligned ballot values")
    served = probe["baseline"]["pv_winner"]
    hybrid = probe["hybrid_value_argmax_index"]
    flat = max(range(len(means)), key=means.__getitem__)
    return {"baseline_value_argmax_index": flat,
            "baseline_value_argmax_regret": max(truth) - truth[flat],
            "selection_rule_removal_delta": truth[flat] - truth[served],
            "lookahead_value_delta": truth[hybrid] - truth[flat],
            "total_delta": truth[hybrid] - truth[served]}


def _validate_caps(completed_tricks, exact_max_cards, oracle_max_cards,
                   max_nodes, max_roots, wall_seconds, seed):
    if type(completed_tricks) is not int or not 1 <= completed_tricks <= 3:
        raise ValueError("completed_tricks must be an integer in [1, 3]")
    if type(exact_max_cards) is not int or not 0 <= exact_max_cards <= 7:
        raise ValueError("exact_max_cards must be an integer in [0, 7]")
    if type(oracle_max_cards) is not int or not 1 <= oracle_max_cards <= 8:
        raise ValueError("oracle_max_cards must be an integer in [1, 8]")
    for name, value in (("max_nodes", max_nodes), ("max_roots", max_roots)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if isinstance(wall_seconds, bool) or not isinstance(wall_seconds, (int, float)) \
            or not math.isfinite(float(wall_seconds)) or wall_seconds <= 0:
        raise ValueError("wall_seconds must be positive")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")


def run_probe_file(input_path, output_path, bot_factory, *, completed_tricks,
                   exact_max_cards, oracle_max_cards, max_nodes, max_roots,
                   wall_seconds, seed):
    """Consume up to ``max_roots`` packet rows into a new compact JSONL file."""
    if not callable(bot_factory):
        raise TypeError("bot_factory must be callable")
    _validate_caps(completed_tricks, exact_max_cards, oracle_max_cards,
                   max_nodes, max_roots, wall_seconds, seed)
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    started = time.monotonic()
    deadline = started + float(wall_seconds)
    attempted = completed = 0

    def expired():
        if time.monotonic() >= deadline:
            raise TimeoutError("cooperative wall budget expired")

    def emit(dest, row):
        dest.write(json.dumps(row, separators=(",", ":")) + "\n")
        dest.flush()

    with input_path.open("rb") as source, output_path.open("x", encoding="utf-8") as dest:
        emit(dest, {"type": "header", "schema": "hybrid-search-run-v1",
                    "config": {"completed_tricks": completed_tricks,
                               "exact_max_cards": exact_max_cards,
                               "oracle_max_cards": oracle_max_cards,
                               "max_nodes": max_nodes, "max_roots": max_roots,
                               "node_limit_scope": "per exact leaf or oracle candidate",
                               "wall_seconds": float(wall_seconds), "seed": seed}})
        while completed < max_roots:
            try:
                expired()
                raw = source.readline(MAX_LINE_BYTES + 1)
                if not raw:
                    emit(dest, {"type": "terminal", "status": "COMPLETE",
                                "reason": "eof", "attempted": attempted,
                                "completed": completed})
                    return {"status": "COMPLETE", "reason": "eof",
                            "attempted": attempted, "completed": completed}
                attempted += 1
                if len(raw) > MAX_LINE_BYTES:
                    raise ValueError("input line exceeds 2MiB limit")
                if not raw.strip():
                    raise ValueError("blank input line")
                row = json.loads(raw.decode("utf-8"))
                if not isinstance(row, dict):
                    raise ValueError("input row must be an object")
                packet_keys = [key for key in ("packet", "replay") if key in row]
                if len(packet_keys) != 1 or not isinstance(row[packet_keys[0]], dict):
                    raise ValueError("input row requires exactly one packet or replay object")
                packet = row[packet_keys[0]]
                root_index = row.get("root_index", attempted - 1)
                if type(root_index) is not int or root_index < 0:
                    raise ValueError("root_index must be a non-negative integer")
                rnd, ledger = restore_with_ledger(packet)
                seat = rnd.turn
                root_max_hand = max((len(hand) for hand in rnd.hands), default=0)
                if not isinstance(seat, int) or not 0 <= seat < len(rnd.hands):
                    raise ValueError("restored root has no valid seat")
                if root_max_hand > oracle_max_cards:
                    raise ValueError("restored root exceeds oracle_max_cards")
                expired()
                bot = bot_factory(seed + attempted - 1)
                bot._refusals = ledger
                expired()

                def gate():
                    expired()

                probe = run_hybrid_search_probe(
                    bot, rnd, seat, completed_tricks=completed_tricks,
                    exact_max_cards=exact_max_cards, gate=gate,
                    exact_max_nodes=max_nodes)
                expired()
                regret = score_true_deal_regret(
                    rnd, seat, probe, max_hand_cards=oracle_max_cards,
                    max_nodes=max_nodes, gate=gate)
                expired()
                pv_index = probe["baseline"]["pv_winner"]
                emit(dest, {"type": "root", "line": attempted,
                            "root_index": root_index,
                            "seat": probe["seat"],
                            "lead": not bool(rnd.trick.plays),
                            "max_hand": root_max_hand,
                            "admitted": probe["admitted"],
                            "baseline": {"index": pv_index,
                                         "action": probe["admitted"][pv_index],
                                         "means": probe["baseline"]["means"]},
                            "proposal": {"index": probe["hybrid_value_argmax_index"],
                                          "action": probe["admitted"][probe["hybrid_value_argmax_index"]],
                                          "matrix_means": probe["matrix_means"],
                                          "changed": probe["changed"]},
                            "timing": {"probe_seconds": probe["seconds"],
                                       "baseline_seconds": probe["baseline"]["seconds"],
                                       "oracle_seconds": regret["seconds"]},
                            "leafstats": probe["leafstats"],
                            "ranking_attribution": ranking_attribution(probe, regret),
                            "regret": {key: regret[key] for key in (
                                "label", "scope", "actions", "values",
                                "best_admitted_value", "baseline_regret",
                                "hybrid_regret", "regret_reduction", "zero_baseline")}})
                completed += 1
            except Exception as exc:
                reason = "budget" if isinstance(exc, TimeoutError) else "error"
                emit(dest, {"type": "terminal",
                            "status": "PARTIAL" if reason == "budget" else "FAILED",
                            "reason": reason,
                            "error": type(exc).__name__, "message": str(exc),
                            "attempted": attempted, "completed": completed})
                return {"status": "PARTIAL" if reason == "budget" else "FAILED",
                        "reason": reason,
                        "attempted": attempted, "completed": completed}
        emit(dest, {"type": "terminal", "status": "COMPLETE",
                    "reason": "root_limit", "attempted": attempted,
                    "completed": completed})
        return {"status": "COMPLETE", "reason": "root_limit",
                "attempted": attempted, "completed": completed}
