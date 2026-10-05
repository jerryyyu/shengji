"""Pure descriptive counters for the served doomed-throw mechanism.

The functions consume already-loaded shard dictionaries.  They do not read
files, call models, inspect outcomes, or impute missing play traces.
"""

from collections.abc import Iterable, Mapping


SCHEMA = "pv-doomed-throw-census-v1"
_SWAP_PREFIX = "doomed_throw_swap_"
_SWAP_FIELDS = (
    "doomed_throw_swap_applied",
    "doomed_throw_swap_from",
    "doomed_throw_swap_to",
    "doomed_throw_swap_worlds",
    "doomed_throw_swap_refused_worlds",
    "doomed_throw_swap_forced_variants",
    "doomed_throw_swap_abandoned",
    "doomed_throw_swap_abandon_error",
)


def empty_doomed_throw_census() -> dict:
    """Return an empty mutable census for one arm/window population."""
    return {
        "schema": SCHEMA,
        "candidate": None,
        "decisions": 0,
        "swap_field_records": 0,
        "swap_applied_field_records": 0,
        "swap_applied": 0,
        "budget_abandoned": 0,
        "multi_card_lead_records": 0,
        "abandoned_multi_card_lead_records": 0,
        "ratio_invalid_records": 0,
        "refused_world_ratio_distribution": {},
        "field_presence": {field: 0 for field in _SWAP_FIELDS},
        "unknown_swap_fields": {},
        "comparator_contamination_records": 0,
        "comparator_contamination_fields": {},
        "aligned_rounds": 0,
        "unaligned_rounds": 0,
        "aligned_arm_plays": 0,
        "failed_throws": 0,
        "failed_throw_rounds": 0,
    }


def _is_nonnegative_int(value) -> bool:
    return type(value) is int and value >= 0


def _arm_decisions(shard):
    traces = shard.get("decision_traces") if isinstance(shard, Mapping) else None
    if not isinstance(traces, list):
        return
    for trace in traces:
        if not isinstance(trace, Mapping) or trace.get("side") != "arm":
            continue
        decisions = trace.get("decisions")
        if not isinstance(decisions, list):
            continue
        yield from decisions


def _record_swap_fields(census: dict, record, *, candidate: bool) -> None:
    if not isinstance(record, Mapping):
        return
    fields = [field for field in record if isinstance(field, str) and field.startswith(_SWAP_PREFIX)]
    if not fields:
        return
    census["swap_field_records"] += 1
    presence = census["field_presence"]
    for field in fields:
        if field in presence:
            presence[field] += 1
        else:
            unknown = census["unknown_swap_fields"]
            unknown[field] = unknown.get(field, 0) + 1
    if not candidate:
        census["comparator_contamination_records"] += 1
        contamination = census["comparator_contamination_fields"]
        for field in fields:
            contamination[field] = contamination.get(field, 0) + 1
        return
    if "doomed_throw_swap_applied" in record:
        census["swap_applied_field_records"] += 1
    if record.get("doomed_throw_swap_applied") is True:
        census["swap_applied"] += 1
    if record.get("doomed_throw_swap_abandoned") == "budget":
        census["budget_abandoned"] += 1


def _record_lead_ratio(census: dict, record) -> None:
    """Observe only a validated, chronologically aligned lead decision."""
    selected = record.get("doomed_throw_swap_from")
    if not isinstance(selected, str) or len(selected.split()) < 2:
        return
    census["multi_card_lead_records"] += 1
    if "doomed_throw_swap_abandoned" in record:
        census["abandoned_multi_card_lead_records"] += 1
        return
    worlds = record.get("doomed_throw_swap_worlds")
    refused = record.get("doomed_throw_swap_refused_worlds")
    if (not _is_nonnegative_int(worlds) or worlds == 0
            or not _is_nonnegative_int(refused) or refused > worlds):
        census["ratio_invalid_records"] += 1
        return
    key = f"{refused}/{worlds}"
    distribution = census["refused_world_ratio_distribution"]
    distribution[key] = distribution.get(key, 0) + 1


def _committed_by_seat(record):
    history = record.get("committed_history") if isinstance(record, Mapping) else None
    if not isinstance(history, list):
        return None
    by_seat = {}
    for position, row in enumerate(history):
        if (not isinstance(row, list) or len(row) != 2
                or type(row[0]) is not int or not isinstance(row[1], list)
                or not row[1]):
            return None
        by_seat.setdefault(row[0], []).append((position, row[1]))
    return by_seat


def _attempted_length(decision):
    """Read canonical ``played``; an optional length witness must agree."""
    if not isinstance(decision, Mapping):
        return None
    length = decision.get("played__len")
    played = decision.get("played")
    if not isinstance(played, list) or not played:
        return None
    if "played__len" in decision and (
            not _is_nonnegative_int(length) or len(played) != length):
        return None
    return len(played)


def _aligned_round(record, traces):
    """Return plays, failures and lead records, or None if unaligned."""
    if (not isinstance(record, Mapping) or type(record.get("mirror")) is not int
            or record.get("mirror") not in (0, 1)):
        return None
    seats = record.get("arm_seats")
    if (not isinstance(seats, list) or len(seats) != 2
            or any(type(seat) is not int for seat in seats)
            or len(set(seats)) != 2):
        return None
    by_seat = _committed_by_seat(record)
    if by_seat is None or any(seat not in by_seat for seat in seats):
        return None
    if not isinstance(traces, list) or len(traces) != 2:
        return None
    plays = failed = 0
    leads = []
    for trace, seat in zip(traces, seats):
        if (not isinstance(trace, Mapping) or trace.get("side") != "arm"
                or trace.get("mirror") != record.get("mirror")):
            return None
        decisions = trace.get("decisions")
        committed = by_seat[seat]
        if not isinstance(decisions, list) or len(decisions) != len(committed):
            return None
        for decision, (position, cards) in zip(decisions, committed):
            attempted = _attempted_length(decision)
            if (not isinstance(decision, Mapping) or decision.get("seat") != seat
                    or attempted is None or attempted < len(cards)):
                return None
            plays += 1
            if position % 4 == 0:
                leads.append(decision)
            if attempted > len(cards):
                failed += 1
    return plays, failed, leads


def _observe_alignment(census: dict, shard) -> None:
    records = shard.get("records") if isinstance(shard, Mapping) else None
    if not isinstance(records, list):
        return
    traces = shard.get("decision_traces") if isinstance(shard, Mapping) else None
    for record in records:
        mirror = record.get("mirror") if isinstance(record, Mapping) else None
        selected = []
        if isinstance(traces, list) and type(mirror) is int:
            selected = [trace for trace in traces
                        if isinstance(trace, Mapping)
                        and trace.get("side") == "arm"
                        and trace.get("mirror") == mirror]
        aligned = _aligned_round(record, selected)
        if aligned is None:
            census["unaligned_rounds"] += 1
            continue
        plays, failed, leads = aligned
        census["aligned_rounds"] += 1
        census["aligned_arm_plays"] += plays
        census["failed_throws"] += failed
        census["failed_throw_rounds"] += int(failed > 0)
        if census["candidate"]:
            for decision in leads:
                _record_lead_ratio(census, decision)


def observe_doomed_throw(census: dict, shard, *, candidate: bool) -> None:
    """Add one already-loaded shard to a candidate or comparator census.

    The arm's traces are counted independently of alignment for mechanism
    field telemetry. Failed-throw rates and lead ratios use only complete
    per-mirror alignments; abandoned leads never enter the ratio distribution.
    """
    if (not isinstance(census, dict) or census.get("schema") != SCHEMA
            or type(candidate) is not bool):
        raise ValueError("invalid doomed-throw census or arm")
    if census["candidate"] is None:
        census["candidate"] = candidate
    elif census["candidate"] is not candidate:
        raise ValueError("mixed candidate/comparator census")
    decisions = list(_arm_decisions(shard))
    census["decisions"] += len(decisions)
    for record in decisions:
        _record_swap_fields(census, record, candidate=candidate)
    _observe_alignment(census, shard)


_ADDITIVE_FIELDS = (
    "decisions", "swap_field_records", "swap_applied_field_records", "swap_applied",
    "budget_abandoned", "multi_card_lead_records", "ratio_invalid_records",
    "abandoned_multi_card_lead_records",
    "comparator_contamination_records",
    "aligned_rounds", "unaligned_rounds", "aligned_arm_plays", "failed_throws",
    "failed_throw_rounds",
)


def _validate_census(census: Mapping) -> None:
    if census.get("schema") != SCHEMA or census.get("candidate") is None:
        raise ValueError("incompatible doomed-throw census")
    if type(census["candidate"]) is not bool:
        raise ValueError("invalid census arm")
    for field in _ADDITIVE_FIELDS:
        if not _is_nonnegative_int(census.get(field)):
            raise ValueError("census counts must be nonnegative integers")
    presence = census.get("field_presence")
    if (not isinstance(presence, Mapping)
            or any(not _is_nonnegative_int(presence.get(field)) for field in _SWAP_FIELDS)):
        raise ValueError("invalid swap field presence")
    contamination = census.get("comparator_contamination_fields")
    if not isinstance(contamination, Mapping) or any(
            not isinstance(k, str) or not k.startswith(_SWAP_PREFIX)
            or not _is_nonnegative_int(v)
            for k, v in contamination.items()):
        raise ValueError("invalid comparator contamination")
    unknown = census.get("unknown_swap_fields")
    if (not isinstance(unknown, Mapping)
            or any(not isinstance(k, str) or not k.startswith(_SWAP_PREFIX)
                   or not _is_nonnegative_int(v) for k, v in unknown.items())):
        raise ValueError("invalid unknown swap field presence")
    distribution = census.get("refused_world_ratio_distribution")
    if (not isinstance(distribution, Mapping)
            or any(not isinstance(k, str) or not _is_nonnegative_int(v)
                   for k, v in distribution.items())):
        raise ValueError("invalid refused-world ratio distribution")


def summarize_doomed_throw(censuses: Iterable[Mapping]) -> dict:
    """Merge shard counters and calculate descriptive alignment/rate fields."""
    rows = list(censuses)
    for row in rows:
        _validate_census(row)
    if rows and len({row["candidate"] for row in rows}) != 1:
        raise ValueError("mixed candidate/comparator censuses")
    total = {field: 0 for field in _ADDITIVE_FIELDS}
    field_presence = {field: 0 for field in _SWAP_FIELDS}
    contamination = {}
    unknown = {}
    distribution = {}
    for row in rows:
        for field in _ADDITIVE_FIELDS:
            total[field] += row[field]
        for field in _SWAP_FIELDS:
            field_presence[field] += row["field_presence"][field]
        for field, count in row["comparator_contamination_fields"].items():
            contamination[field] = contamination.get(field, 0) + count
        for field, count in row["unknown_swap_fields"].items():
            unknown[field] = unknown.get(field, 0) + count
        for ratio, count in row["refused_world_ratio_distribution"].items():
            distribution[ratio] = distribution.get(ratio, 0) + count
    aligned = total["aligned_rounds"]
    unaligned = total["unaligned_rounds"]
    arm_plays = total["aligned_arm_plays"]
    return {
        "schema": SCHEMA,
        "candidate": rows[0]["candidate"] if rows else None,
        "counts": total,
        "field_presence": field_presence,
        "unknown_swap_fields": dict(sorted(unknown.items())),
        "refused_world_ratio_distribution": dict(sorted(distribution.items())),
        "comparator_contamination_fields": dict(sorted(contamination.items())),
        "lane_defect": bool(contamination),
        "alignment": {
            "aligned_rounds": aligned,
            "unaligned_rounds": unaligned,
            "total_rounds": aligned + unaligned,
            "coverage": aligned / (aligned + unaligned) if aligned + unaligned else None,
        },
        "failed_throw_rate_per_1000_aligned_arm_plays":
            1000 * total["failed_throws"] / arm_plays if arm_plays else None,
        "failed_throw_round_share":
            total["failed_throw_rounds"] / aligned if aligned else None,
        "invalid_ratio_records": total["ratio_invalid_records"],
        "status": "observed" if aligned or total["decisions"] else "no valid telemetry",
        "note": "Descriptive only; malformed or missing alignments are excluded, never imputed. ",
    }
