"""Pure alignment of two benchmark endpoints with explicit failure semantics."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .benchmark_failure_protocol import (
    FAIL_STOP,
    PRESERVE_ILLEGAL,
    attempt_disposition,
)


def _protocol(protocol: str) -> str:
    if protocol not in (FAIL_STOP, PRESERVE_ILLEGAL):
        raise ValueError("unknown benchmark failure protocol")
    # Legacy rows are fail-stop even when they contain a failure receipt. The
    # amended protocol is the sole opt-in to treating a typed illegality as a
    # model forfeit.
    return PRESERVE_ILLEGAL if protocol == PRESERVE_ILLEGAL else FAIL_STOP


def _finite_score(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def _side(rows: Sequence[Mapping[str, object]], information: str,
          protocol: str) -> tuple[dict[int, dict[int, tuple[str, float | None]]],
                                  int, int]:
    by_seed: dict[int, dict[int, tuple[str, float | None]]] = {}
    seen: set[tuple[int, int]] = set()
    unattempted = 0
    unclassified = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("benchmark row must be an object")
        if raw.get("information") != information:
            continue
        seed, flip = raw.get("seed"), raw.get("flip")
        if (type(seed) is not int or type(flip) is not int
                or flip not in (0, 1)):
            raise ValueError("invalid benchmark row identity")
        identity = (seed, flip)
        if identity in seen:
            raise ValueError("duplicate benchmark row identity")
        seen.add(identity)
        row = dict(raw)
        disposition = attempt_disposition(row, protocol=protocol)
        if disposition == "complete":
            score = row.get("signed_levels")
            if not _finite_score(score):
                raise ValueError("finite signed-level score required")
            value: float | None = -float(score)
        elif disposition == "retained-model-failure":
            value = 1.0
        elif disposition == "unattempted":
            value = None
            unattempted += 1
        else:
            value = None
            unclassified += 1
        by_seed.setdefault(seed, {})[flip] = (disposition, value)
    for pair in by_seed.values():
        if set(pair) != {0, 1}:
            raise ValueError("each benchmark seed must contain both flips")
    return by_seed, unattempted, unclassified


def aligned_forfeit_values(
    left: Sequence[Mapping[str, object]],
    right: Sequence[Mapping[str, object]],
    information: str,
    *,
    left_protocol: str,
    right_protocol: str,
) -> dict[str, object]:
    """Align policy-perspective paired values without imputation.

    Complete mirrors contribute ``-signed_levels``; a typed amended failure
    contributes the policy-perspective forfeit ``+1``; pending mirrors have no
    value. Any unclassified failure blocks the endpoint instead of dropping
    that pair selectively.
    """
    if information not in ("actor-only", "perfect"):
        raise ValueError("information must be actor-only or perfect")
    left_protocol = _protocol(left_protocol)
    right_protocol = _protocol(right_protocol)
    left_pairs, left_unattempted, left_unclassified = _side(
        left, information, left_protocol)
    right_pairs, right_unattempted, right_unclassified = _side(
        right, information, right_protocol)

    common_seeds = sorted(set(left_pairs) & set(right_pairs))
    matched_seeds: list[int] = []
    values: list[float] = []
    for seed in common_seeds:
        left_pair, right_pair = left_pairs[seed], right_pairs[seed]
        if (any(disposition == "stop" for disposition, _ in left_pair.values())
                or any(disposition == "stop" for disposition, _ in right_pair.values())):
            continue
        left_scores = [left_pair[flip][1] for flip in (0, 1)]
        right_scores = [right_pair[flip][1] for flip in (0, 1)]
        if any(score is None for score in (*left_scores, *right_scores)):
            continue
        matched_seeds.append(seed)
        values.append((sum(left_scores) / 2.0) - (sum(right_scores) / 2.0))

    blocked = bool(left_unclassified or right_unclassified)
    partial = (not left_pairs or not right_pairs
               or set(left_pairs) != set(right_pairs)
               or left_unattempted > 0 or right_unattempted > 0)
    return {
        "status": "blocked" if blocked else ("partial" if partial else "complete"),
        "matched_seeds": matched_seeds,
        "values": None if blocked else values,
        "left_unattempted_mirrors": left_unattempted,
        "right_unattempted_mirrors": right_unattempted,
        "left_unclassified_failures": left_unclassified,
        "right_unclassified_failures": right_unclassified,
    }


__all__ = ["aligned_forfeit_values"]
