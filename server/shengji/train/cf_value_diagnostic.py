"""Counterfactual candidate-value diagnostic on a FIXED audit set (#663 step 3, #677).

Separates, on the same positions and the same sampled worlds, three things the
served pv-search bundles into one decision:

* ADMISSION -- which K actions a head's policy prior lets the value head price
  (the served rule: heuristic anchor + the prior's top K-1; ``PVSearchBot._admit``
  reached through ``PVSearchBot._search``, never re-implemented here);
* RANKING -- how a head's VALUE head orders a wider set: the union of both
  heads' admitted sets, the action the record played, and E extra random legal
  actions, every one priced in every shared world (``PVSearchBot.value_matrix``,
  reduced with serving's own accumulator ``sums / W``);
* OUTCOME -- the action each head actually chooses on the shared worlds, and,
  when the two heads choose differently, whether admission or ranking is the
  proximate cause.

What this is NOT: #663 step 1 (Codex) measures the ACTUAL K=8 admission under
production, world draws and all.  This tool fixes the worlds and asks the
counterfactual value question -- with the admitted set swapped and the value
head held fixed, does the argmax move?  The two are complements, not
duplicates.  Every number here is a point estimate on an audit set; nothing is
a strength claim.

Units: value means are the package's ``expected-signed-level-half-integer``
from the acting team's perspective, as in the decision records.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import random
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from ..ai.heuristic import HeuristicBot
from ..ai.mcbot import MCBot
from ..ai.memory import Memory
from ..ai.cwv_policy import sample_worlds

SCHEMA_AUDIT = "cf-value-audit-set-v1"
SCHEMA_TABLE = "cf-value-position-table-v1"
PHASES = ("lead-single", "lead-multi", "follow-single", "follow-multi")
TRICK_BUCKETS = ("t00-04", "t05-09", "t10-14", "t15-19", "t20+")
HEADS = ("current", "previous")
DEFAULT_TIE_EPS = 0.02

ActionKey = tuple[str, ...]


class AuditError(ValueError):
    """The audit set or a position cannot be used as asked."""


# ------------------------------------------------------------------ audit set

def action_key(cards: Sequence[str]) -> ActionKey:
    return tuple(sorted(cards))


def phase_of(ply: int, action: Sequence[str]) -> str:
    return ("lead" if int(ply) % 4 == 0 else "follow") + ("-multi" if len(action) > 1 else "-single")


def trick_bucket(trick: int) -> str:
    return TRICK_BUCKETS[min(int(trick) // 5, len(TRICK_BUCKETS) - 1)]


def audit_row(record: Mapping[str, Any], *, source: str) -> dict[str, Any] | None:
    """The self-contained audit row for one decision record, or None when the
    record cannot be rebuilt or has nothing to choose (one legal action)."""
    if record.get("decision_kind") != "play":
        return None
    if record.get("deck") is None and record.get("round_seed") is None:
        return None
    action = record.get("action")
    if not action:
        return None
    legal_count = int(record.get("legal_actions_count") or 0)
    if legal_count < 2:
        return None
    ply = int(record["ply"])
    trick = int(record.get("trick", ply // 4))
    return {
        "key": str(record["source_ref"]),
        "source": source,
        "record_sha256": record.get("record_sha256"),
        "policy": record.get("policy"),
        "seat": int(record["seat"]),
        "role": record.get("role"),
        "ply": ply,
        "trick": trick,
        "phase": phase_of(ply, action),
        "bucket": trick_bucket(trick),
        "legal_count": legal_count,
        "legal_complete": bool(record.get("legal_actions_complete", True)),
        "played": list(action),
        "engine_play": record.get("engine_play"),
        # rebuild fields (harvest.rebuild.state_for_record)
        "decision_kind": "play",
        "deck": record.get("deck"),
        "round_seed": record.get("round_seed"),
        "setup": record["setup"],
        "plays_prefix": record.get("plays_prefix") or [],
    }


def sample_audit_set(rows: Iterable[Mapping[str, Any]], *, n: int, seed: int) -> list[dict[str, Any]]:
    """Deterministic stratified draw: strata = phase x trick bucket, each
    shuffled by ONE ``random.Random(seed)`` in sorted stratum order, then
    round-robin one row per stratum until ``n`` rows or every stratum is empty.
    Balanced where the store allows it; a small stratum contributes all it has
    and the remainder comes from the others.  Duplicate keys are dropped (first
    occurrence wins) so the draw is a set of distinct positions."""
    if type(n) is not int or n < 1:
        raise AuditError("n must be a positive integer")
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for row in rows:
        if row["key"] in seen:
            continue
        seen.add(row["key"])
        strata[(row["phase"], row["bucket"])].append(dict(row))
    rng = random.Random(seed)
    queues = []
    for name in sorted(strata):
        bucket = sorted(strata[name], key=lambda r: r["key"])
        rng.shuffle(bucket)
        queues.append(bucket)
    chosen: list[dict[str, Any]] = []
    while len(chosen) < n and any(queues):
        for queue in queues:
            if queue and len(chosen) < n:
                chosen.append(queue.pop())
    for index, row in enumerate(chosen):
        row["index"] = index
    return chosen


def audit_set_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps([r["key"] for r in rows], separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


# -------------------------------------------------------------- shared worlds

def world_seed(base_seed: int, index: int) -> int:
    """One sampler stream per position, a pure function of (base seed, index)."""
    return int(base_seed) * 1_000_003 + int(index)


def shared_worlds(rnd, seat: int, n: int, *, seed: int):
    """``n`` worlds through PRODUCTION's sampler (``cwv_policy.sample_worlds`` on
    an ``MCBot(seed)``, the same pipeline ``PVSearchBot._worlds`` runs), drawn
    ONCE per position and reused for every head.  Short sampling refuses."""
    bot = MCBot(seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    worlds, attempts = sample_worlds(bot, rnd, seat, n, mem=mem)
    if len(worlds) != n:
        raise AuditError(f"shared world sampling short: {len(worlds)}/{n}")
    if any(rnd.ordering.eff_suit(c) in mem.voids[s]
           for hands, _ in worlds for s in range(4) if s != seat for c in hands[s]):
        raise AuditError("shared world sampling violates public voids")
    return worlds, attempts


def worlds_digest(worlds) -> str:
    payload = json.dumps([[hands, buried] for hands, buried in worlds], separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


# ------------------------------------------------------------------ admission

def admission_under(bot, rnd, seat: int, worlds) -> dict[str, Any]:
    """The head's served decision on the SHARED worlds.

    Runs ``PVSearchBot._search`` -- heuristic anchor, capped legal listing,
    policy-prior scores, ``_admit`` (anchor + top K-1), value means on the
    admitted set, ``_select`` -- with only ``_worlds`` substituted so the bot
    prices the shared draw instead of drawing its own.  Nothing about the
    admission rule lives in this module."""
    patched = lambda rnd_, seat_, check_budget=None: (list(worlds), len(worlds))  # noqa: E731
    bot.__dict__["_worlds"] = patched
    try:
        anchor = HeuristicBot.decide_play(bot, rnd, seat)
        decision = bot._search(rnd, seat, anchor, time.perf_counter())
    finally:
        del bot.__dict__["_worlds"]
    record = bot.last_decision_record
    if record is None or record.get("work_complete") is not True:
        raise AuditError("served search did not publish a complete record")
    return {
        "anchor": list(anchor),
        "admitted": [action_key(a) for a in record["admitted"]],
        "decision": action_key(decision),
        "search_means": [float(v) for v in record["value_means"]],
        "policy_log_odds": [float(v) for v in record["policy_log_odds_admitted"]],
        "legal_count": int(record["legal_count"]),
        "legal_complete": bool(record["legal_complete"]),
        "listing": int(record["actions"]),
    }


# -------------------------------------------------------------------- union

def build_union(admitted: Mapping[str, Sequence[ActionKey]], played: ActionKey,
                legal: Sequence[ActionKey], *, extras: int, rng: random.Random) -> list[ActionKey]:
    """Admitted sets in head order (deduplicated, order kept), then the played
    action, then ``extras`` random legal actions not already present (drawn
    from the SORTED remainder with ``rng``; fewer if the pool is smaller)."""
    union: list[ActionKey] = []
    present: set[ActionKey] = set()

    def add(key: ActionKey) -> None:
        if key not in present:
            present.add(key)
            union.append(key)

    for head in sorted(admitted):
        for key in admitted[head]:
            add(action_key(key))
    add(action_key(played))
    pool = sorted({action_key(k) for k in legal} - present)
    for key in rng.sample(pool, min(int(extras), len(pool))):
        add(key)
    return union


def value_table(bot, rnd, seat: int, union: Sequence[ActionKey], worlds) -> dict[str, list[float]]:
    """The head's value means over ``union`` on the shared worlds: serving's own
    reducer (``sums / W`` from ``value_matrix``), plus the per-action SE over
    worlds for the near-tie reading."""
    matrix, sums, _batches = bot.value_matrix(rnd, seat, [list(k) for k in union], worlds)
    w = len(worlds)
    means = sums / w
    se = matrix.std(axis=0, ddof=1) / math.sqrt(w) if w >= 2 else np.full(len(union), float("nan"))
    return {"means": [float(v) for v in means], "se": [float(v) for v in se]}


# ------------------------------------------------------------------- metrics

def _argmax(values: Sequence[float], indices: Iterable[int]) -> int:
    best = None
    for i in indices:
        if best is None or values[i] > values[best]:
            best = i
    if best is None:
        raise AuditError("argmax over an empty set")
    return best


def _spread(values: Sequence[float], indices: Iterable[int]) -> float:
    ordered = sorted((values[i] for i in indices), reverse=True)
    return float("nan") if len(ordered) < 2 else ordered[0] - ordered[1]


def _rank(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rho with average ranks; NaN when either side is constant."""
    if len(a) != len(b) or len(a) < 2:
        return float("nan")
    ra, rb = np.asarray(_rank(a)), np.asarray(_rank(b))
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def position_metrics(table: Mapping[str, Any], *, tie_eps: float = DEFAULT_TIE_EPS,
                     heads: Sequence[str] = HEADS) -> dict[str, Any]:
    """Every metric for one position, computed from the per-position table.

    ``table``: ``union`` (action keys), ``played`` (key), ``heads[H]`` with
    ``admitted`` (keys) and ``decision`` (key), ``values[H]`` (means over the
    union, aligned by index).  Keys are compared as sorted card tuples.
    """
    union = [action_key(k) for k in table["union"]]
    index = {key: i for i, key in enumerate(union)}
    played = action_key(table["played"])
    if played not in index:
        raise AuditError("played action missing from the union")
    adm: dict[str, list[int]] = {}
    decision: dict[str, int] = {}
    values: dict[str, list[float]] = {}
    for head in heads:
        info = table["heads"][head]
        adm[head] = [index[action_key(k)] for k in info["admitted"]]
        decision[head] = index[action_key(info["decision"])]
        values[head] = [float(v) for v in table["values"][head]]
        if len(values[head]) != len(union):
            raise AuditError(f"{head}: value table does not cover the union")
    a, b = heads[0], heads[1]
    out: dict[str, Any] = {}
    # -- admission
    sa, sb = set(adm[a]), set(adm[b])
    out["admission.jaccard"] = len(sa & sb) / len(sa | sb)
    out["admission.same_set"] = sa == sb
    for head, own, other in ((a, sa, sb), (b, sb, sa)):
        out[f"admission.played_in_{head}"] = index[played] in own
    for head, other_name, other in ((a, b, sb), (b, a, sa)):
        out[f"admission.{head}_decision_in_{other_name}"] = decision[head] in other
    for head in (a, b):
        v = values[head]
        best_union = _argmax(v, range(len(union)))
        best_own = _argmax(v, adm[head])
        out[f"admission.loss_{head}"] = v[best_union] - v[best_own]
        out[f"admission.union_argmax_admitted_{head}"] = best_union in set(adm[head])
    # -- ranking on the union
    out["ranking.spearman"] = spearman(values[a], values[b])
    top = {h: _argmax(values[h], range(len(union))) for h in (a, b)}
    out["ranking.top1_agree"] = top[a] == top[b]
    for head, other in ((a, b), (b, a)):
        vo = values[other]
        out[f"ranking.regret_{head}_under_{other}"] = vo[top[other]] - vo[top[head]]
    # -- swap: admitted set swapped, value head fixed (#663 step 3)
    for v_head in (a, b):
        v = values[v_head]
        under_a = _argmax(v, adm[a])
        under_b = _argmax(v, adm[b])
        out[f"swap.flip_{v_head}"] = under_a != under_b
        out[f"swap.gap_{v_head}"] = v[under_a] - v[under_b]
    # -- near ties
    for head in (a, b):
        v = values[head]
        out[f"neartie.{head}_admitted"] = _spread(v, adm[head]) < tie_eps
        out[f"neartie.{head}_union"] = _spread(v, range(len(union))) < tie_eps
    # -- outcome
    out["outcome.agree"] = decision[a] == decision[b]
    if decision[a] == decision[b]:
        cause = "same"
    elif decision[a] not in sb or decision[b] not in sa:
        cause = "admission"
    else:
        cause = "ranking"
    out["outcome.cause"] = cause
    for head in (a, b):
        out[f"outcome.{head}_matches_record"] = decision[head] == index[played]
        out[f"outcome.{head}_is_union_argmax"] = decision[head] == top[head]
    return out


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per metric: bools -> ``{n, count, frac}``; floats -> ``{n, mean, median}``
    over finite values; strings -> counts."""
    columns: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        for key, value in row.items():
            columns[key].append(value)
    out: dict[str, Any] = {"n": len(rows)}
    for key in sorted(columns):
        values = columns[key]
        if all(isinstance(v, bool) for v in values):
            count = sum(values)
            out[key] = {"n": len(values), "count": count, "frac": count / len(values) if values else float("nan")}
        elif all(isinstance(v, (int, float)) for v in values):
            finite = [float(v) for v in values if math.isfinite(float(v))]
            out[key] = {"n": len(finite), "nan": len(values) - len(finite),
                        "mean": float(np.mean(finite)) if finite else float("nan"),
                        "median": float(np.median(finite)) if finite else float("nan")}
        else:
            counts: dict[str, int] = defaultdict(int)
            for v in values:
                counts[str(v)] += 1
            out[key] = {"n": len(values), "counts": dict(sorted(counts.items()))}
    return out


def stratified(positions: Sequence[Mapping[str, Any]], metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``overall`` plus one aggregate per phase and per trick bucket."""
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for pos, row in zip(positions, metrics, strict=True):
        groups["overall"].append(row)
        groups[f"phase:{pos['phase']}"].append(row)
        groups[f"bucket:{pos['bucket']}"].append(row)
    return {name: aggregate(rows) for name, rows in groups.items()}


# ------------------------------------------------------------------ pipeline

def run_position(row: Mapping[str, Any], bots: Mapping[str, Any], *, worlds_n: int,
                 extras: int, seed: int, rebuild: Callable[[Mapping[str, Any]], Any],
                 legal_fn: Callable[[Any, int, Sequence[str]], Sequence[Sequence[str]]]) -> dict[str, Any]:
    """One audit row -> the per-position table (admission, union, values)."""
    rnd = rebuild(row)
    seat = int(row["seat"])
    if rnd.turn != seat:
        raise AuditError(f"{row['key']}: rebuilt state is not {seat}'s turn")
    worlds, attempts = shared_worlds(rnd, seat, worlds_n, seed=world_seed(seed, int(row["index"])))
    heads = {name: admission_under(bot, rnd, seat, worlds) for name, bot in bots.items()}
    played = action_key(row["played"])
    legal = [action_key(a) for a in legal_fn(rnd, seat, row["played"])]
    rng = random.Random(world_seed(seed, int(row["index"])) ^ 0x5F5E1)
    union = build_union({h: info["admitted"] for h, info in heads.items()}, played, legal,
                        extras=extras, rng=rng)
    values, se = {}, {}
    for name, bot in bots.items():
        table = value_table(bot, rnd, seat, union, worlds)
        values[name], se[name] = table["means"], table["se"]
    return {
        "schema": SCHEMA_TABLE, "key": row["key"], "index": int(row["index"]),
        "seat": seat, "phase": row["phase"], "bucket": row["bucket"], "trick": row["trick"],
        "legal_count": row["legal_count"], "played": list(played),
        "worlds": worlds_n, "sample_attempts": attempts, "worlds_sha256": worlds_digest(worlds),
        "union": [list(k) for k in union],
        "heads": {h: {**info, "admitted": [list(k) for k in info["admitted"]],
                      "decision": list(info["decision"])} for h, info in heads.items()},
        "values": values, "se": se,
    }


def markdown_summary(result: Mapping[str, Any]) -> str:
    """A short markdown read of the stratified aggregates."""
    strat = result["stratified"]
    cfg = result["config"]
    lines = [
        "# Counterfactual value diagnostic (#663 step 3)",
        "",
        f"audit set `{cfg['audit']}` (sha256 {cfg['audit_sha256'][:12]}), N={strat['overall']['n']}, "
        f"W={cfg['worlds']} shared worlds, E={cfg['extras']} extras, seed {cfg['seed']}, tie eps {cfg['tie_eps']}",
        "",
        f"current = `{cfg['heads']['current']['sha256'][:8]}`, previous = `{cfg['heads']['previous']['sha256'][:8]}`; "
        "values in expected-signed-level half-integers (acting team).",
        "",
        "Point estimates on an audit set; not a strength claim.",
        "",
    ]
    rows = [
        ("admitted-set Jaccard (mean)", "admission.jaccard", "mean"),
        ("identical admitted sets", "admission.same_set", "frac"),
        ("played action admitted by current", "admission.played_in_current", "frac"),
        ("played action admitted by previous", "admission.played_in_previous", "frac"),
        ("current's decision inside previous's set", "admission.current_decision_in_previous", "frac"),
        ("previous's decision inside current's set", "admission.previous_decision_in_current", "frac"),
        ("admission loss under current (mean)", "admission.loss_current", "mean"),
        ("admission loss under previous (mean)", "admission.loss_previous", "mean"),
        ("union argmax admitted, current", "admission.union_argmax_admitted_current", "frac"),
        ("union argmax admitted, previous", "admission.union_argmax_admitted_previous", "frac"),
        ("Spearman on union (mean)", "ranking.spearman", "mean"),
        ("top-1 agreement on union", "ranking.top1_agree", "frac"),
        ("regret of current's argmax under previous (mean)", "ranking.regret_current_under_previous", "mean"),
        ("regret of previous's argmax under current (mean)", "ranking.regret_previous_under_current", "mean"),
        ("argmax flips when sets swapped, current value head", "swap.flip_current", "frac"),
        ("argmax flips when sets swapped, previous value head", "swap.flip_previous", "frac"),
        ("gap current-set minus previous-set, current value head (mean)", "swap.gap_current", "mean"),
        ("gap current-set minus previous-set, previous value head (mean)", "swap.gap_previous", "mean"),
        ("near-tie on admitted set, current", "neartie.current_admitted", "frac"),
        ("near-tie on admitted set, previous", "neartie.previous_admitted", "frac"),
        ("decisions agree", "outcome.agree", "frac"),
        ("current decision = recorded play", "outcome.current_matches_record", "frac"),
        ("previous decision = recorded play", "outcome.previous_matches_record", "frac"),
    ]
    groups = ["overall"] + [g for g in sorted(strat) if g.startswith("phase:")] \
        + [g for g in sorted(strat) if g.startswith("bucket:")]
    header = "| metric | " + " | ".join(g.replace("phase:", "").replace("bucket:", "") for g in groups) + " |"
    lines += [header, "|" + "---|" * (len(groups) + 1)]
    lines.append("| n | " + " | ".join(str(strat[g]["n"]) for g in groups) + " |")
    for label, key, field in rows:
        cells = []
        for g in groups:
            cell = strat[g].get(key)
            cells.append("-" if cell is None else f"{cell[field]:.4f}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    cause = strat["overall"].get("outcome.cause", {}).get("counts", {})
    lines += ["", "Disagreement cause (overall): " + ", ".join(f"{k} {v}" for k, v in sorted(cause.items())), ""]
    return "\n".join(lines)
