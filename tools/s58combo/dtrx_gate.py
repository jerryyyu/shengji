"""Fail-closed validation of doomed-throw (dtr/dtrx) decision receipts.

The producer emits the ordinary re-select receipt on every successful search.
The exact-floor receipt is treatment-specific: it is present on every
candidate search decision and absent from the comparator and fallbacks.
"""

DTR_FIELDS = (
    "doomed_throw_reselect_applied",
    "doomed_throw_reselect_from",
    "doomed_throw_reselect_to",
    "doomed_throw_reselect_doomed_candidates",
    "doomed_throw_reselect_forced_excluded",
    "doomed_throw_reselect_fallback_forced",
)
DTRX_FIELDS = (
    "doomed_throw_reselect_exact_guarded",
    "doomed_throw_reselect_exact_floor_excluded",
)
_SCHEMAS = {"pv-search-decision-v1", "pv-search-fallback-v1"}


def _nonnegative(value):
    return type(value) is int and value >= 0


def _validate_dtr(rec):
    """Validate the common re-select receipt, returning its schema class."""
    if not isinstance(rec, dict) or rec.get("schema") not in _SCHEMAS:
        raise ValueError("unknown decision receipt schema")
    missing = [key for key in DTR_FIELDS if key not in rec]
    if missing:
        raise ValueError("dtr fields missing: " + ", ".join(missing))
    if type(rec[DTR_FIELDS[0]]) is not bool or type(rec[DTR_FIELDS[5]]) is not bool:
        raise ValueError("dtr boolean field malformed")
    if (not isinstance(rec[DTR_FIELDS[1]], str) or not rec[DTR_FIELDS[1]]
            or not isinstance(rec[DTR_FIELDS[2]], str) or not rec[DTR_FIELDS[2]]
            or not _nonnegative(rec[DTR_FIELDS[3]])
            or not _nonnegative(rec[DTR_FIELDS[4]])):
        raise ValueError("dtr receipt field malformed")
    if ("doomed_throw_reselect_abandoned" in rec
            and rec["doomed_throw_reselect_abandoned"] != "budget"):
        raise ValueError("dtr abandoned marker malformed")
    return rec["schema"]


def validate_record(rec, *, exact_guard=False, require_search=None):
    """Validate one arm-side decision and return ``search`` or ``fallback``.

    ``require_search`` is useful to callers that separately classify records;
    when omitted the schema determines the class.  dtrx is only legal on a
    candidate search record, and an unguarded receipt must report zero floor
    exclusions.
    """
    if not isinstance(rec, dict) or type(rec.get("schema")) is not str:
        raise ValueError("malformed receipt")
    schema = rec.get("schema")
    if schema == "pv-search-fallback-v1":
        if require_search is True:
            raise ValueError("decision schema population mismatch")
        if any(key in rec for key in (*DTR_FIELDS, *DTRX_FIELDS,
                                      "doomed_throw_reselect_abandoned")):
            raise ValueError("rule fields on fallback receipt")
        return "fallback"
    schema = _validate_dtr(rec)
    search = schema == "pv-search-decision-v1"
    if require_search is not None and search is not require_search:
        raise ValueError("decision schema population mismatch")
    present = [key for key in DTRX_FIELDS if key in rec]
    if exact_guard and search:
        if present != list(DTRX_FIELDS):
            raise ValueError("dtrx fields missing from candidate search receipt")
        if (type(rec[DTRX_FIELDS[0]]) is not bool
                or not _nonnegative(rec[DTRX_FIELDS[1]])
                or (not rec[DTRX_FIELDS[0]] and rec[DTRX_FIELDS[1]] != 0)):
            raise ValueError("dtrx receipt field malformed")
    elif present:
        raise ValueError("dtrx fields on comparator or fallback receipt")
    return "search" if search else "fallback"


def check_dtrx(plan, shards):
    """Check dtr/dtrx activation and receipt populations before estimation."""
    counts = {
        side: {"search": 0, "fallback": 0, "guarded": 0, "dtrx": 0,
               "dtr_applied": 0}
        for side in ("candidate", "comparator")
    }
    reasons = []
    for side in counts:
        config = plan["arms"][side]["identity"]["config"]
        common = config.get("doomed_throw_reselect")
        enabled = config.get("doomed_throw_reselect_exact_guard")
        if common is not True:
            reasons.append(f"{side}: common dtr recipe is not enabled")
        if type(enabled) is not bool or enabled != (side == "candidate"):
            reasons.append(f"{side}: exact dtrx recipe mismatch")
    for window in plan["windows"]:
        side = window["side"]
        exact_guard = side == "candidate"
        for shard in shards[window["output"]]:
            for trace in shard.get("decision_traces", []):
                if trace.get("side") != "arm":
                    continue
                for rec in trace.get("decisions", []):
                    try:
                        population = validate_record(rec, exact_guard=exact_guard)
                    except ValueError as exc:
                        reasons.append(f"{side}: {exc}")
                        continue
                    counts[side][population] += 1
                    if exact_guard and population == "search":
                        counts[side]["dtrx"] += 1
                        counts[side]["guarded"] += int(rec[DTRX_FIELDS[0]])
                    if population == "search":
                        counts[side]["dtr_applied"] += int(rec["doomed_throw_reselect_applied"])
    for side, value in counts.items():
        if not value["search"]:
            reasons.append(f"{side}: no search receipts")
        if side == "candidate" and not value["guarded"]:
            reasons.append("candidate: exact dtrx floor was never applied")
        if side == "candidate" and value["dtrx"] != value["search"]:
            reasons.append("candidate: dtrx population does not cover every search receipt")
    return {"verdict": "SCREEN_INVALID" if reasons else "VALID",
            "counts": counts, "reasons": reasons[:20]}
