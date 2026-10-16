#!/usr/bin/env python3
"""Summarize rows appended by a production room-log refresh.

Policy attribution comes only from the appended events.  In particular, this
tool never consults ``fly.toml`` or the currently served bot: a late-arriving
round can have been played by an older deployment.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


class DeltaError(ValueError):
    pass


def _finite_numbers(values: Iterable[Any]) -> list[float]:
    out = []
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number):
                out.append(number)
    return out


def _median(values: Iterable[Any]) -> float | None:
    numbers = _finite_numbers(values)
    return statistics.median(numbers) if numbers else None


def appended_events(before: Path, after: Path) -> list[dict[str, Any]]:
    old = before.read_bytes()
    new = after.read_bytes()
    if not new.startswith(old):
        raise DeltaError("after log does not have before log as an exact prefix")
    suffix = new[len(old):]
    events = []
    for offset, raw in enumerate(suffix.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DeltaError(f"invalid appended JSON on suffix line {offset}") from exc
        if not isinstance(event, dict):
            raise DeltaError(f"appended JSON on suffix line {offset} is not an object")
        events.append(event)
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    plays = [event for event in events if event.get("e") == "play" and event.get("bot") is True]
    decisions = [event.get("decision") for event in plays
                 if isinstance(event.get("decision"), dict)]
    timings = [event for event in events
               if event.get("e") == "bot_timing" and event.get("phase") == "play"
               and event.get("acted") is not False]
    completed = [event for event in events
                 if event.get("e") == "model_search" and event.get("phase") == "play"
                 and event.get("event") == "completed"]

    event_policies = Counter()
    for event in plays + timings + completed:
        decision = event.get("decision")
        policy = decision.get("policy") if isinstance(decision, dict) else event.get("policy")
        if isinstance(policy, str) and policy:
            event_policies[policy] += 1

    decision_policies = Counter(
        decision["policy"] for decision in decisions
        if isinstance(decision.get("policy"), str) and decision["policy"]
    )
    unknown_policy_plays = sum(
        not isinstance(decision.get("policy"), str) or not decision.get("policy")
        for decision in decisions
    ) + len(plays) - len(decisions)

    timestamps = _finite_numbers(event.get("t") for event in events)
    search_fallbacks = sum(
        decision.get("schema") == "pv-search-fallback-v1"
        or decision.get("work_complete") is False
        for decision in decisions
    )
    refusal_fallback_worlds = sum(
        int(decision.get("refusal_fallback_worlds") or 0) for decision in decisions
    )
    declare_events = [event for event in events
                      if event.get("e") == "declare_decision" and event.get("bot") is True]
    declare_records = [event["record"] for event in declare_events
                       if isinstance(event.get("record"), dict)
                       and event["record"].get("schema") == "pv-value-declare-decision-v1"]
    declare_policies = Counter(record["policy"] for record in declare_records
                               if isinstance(record.get("policy"), str) and record["policy"])
    fallback_reasons = Counter(record["fallback_reason"] for record in declare_records
                               if isinstance(record.get("fallback_reason"), str)
                               and record["fallback_reason"])
    declare_searches = [event for event in events
                        if event.get("e") == "model_search" and event.get("phase") == "declare"
                        and event.get("event") == "completed"]
    return {
        "appended_events": len(events),
        "event_kinds": dict(sorted(Counter(str(event.get("e")) for event in events).items())),
        "rounds": sorted({int(event["round"]) for event in events
                          if isinstance(event.get("round"), int)}),
        "first_timestamp": min(timestamps) if timestamps else None,
        "last_timestamp": max(timestamps) if timestamps else None,
        "bot_plays": len(plays),
        "decision_records": len(decisions),
        "decision_policy_counts": dict(sorted(decision_policies.items())),
        "unknown_policy_plays": unknown_policy_plays,
        "observed_event_policy_counts": dict(sorted(event_policies.items())),
        "search_fallbacks": search_fallbacks,
        "refusal_fallback_worlds": refusal_fallback_worlds,
        "declaration": {
            # Records are committed gated decisions (including PASS). Worker
            # completions can be discarded by stale-state guards, so they are
            # deliberately a separate denominator, never inferred decisions.
            "committed_events": len(declare_events),
            "value_records": len(declare_records),
            "unknown_records": len(declare_events) - len(declare_records),
            "policy_counts": dict(sorted(declare_policies.items())),
            "unknown_policy_records": len(declare_records) - sum(declare_policies.values()),
            "evaluated": sum(r.get("evaluated") is True for r in declare_records),
            "not_evaluated": sum(r.get("evaluated") is False for r in declare_records),
            "changed": sum(r.get("changed") is True for r in declare_records),
            "fallback_reasons": dict(sorted(fallback_reasons.items())),
            "fallback_fraction": (sum(fallback_reasons.values()) / len(declare_records)
                                  if declare_records else None),
            "decision_seconds_p50": _median(r.get("seconds") for r in declare_records),
            "model_search_completed": len(declare_searches),
            "model_search_seconds_p50": _median(e.get("elapsed_seconds") for e in declare_searches),
        },
        "latency_seconds_p50": {
            "decision": _median(decision.get("seconds") for decision in decisions),
            "model_search_completed": _median(event.get("elapsed_seconds") for event in completed),
            "bot_compute": _median(event.get("compute_seconds") for event in timings),
            "turn": _median(event.get("turn_seconds") for event in timings),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact", action="store_true",
                        help="emit one-line JSON for a calling script")
    parser.add_argument("before", type=Path, help="pre-refresh room log")
    parser.add_argument("after", type=Path, help="post-refresh room log")
    args = parser.parse_args(argv)
    try:
        report = summarize(appended_events(args.before, args.after))
    except (DeltaError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
