"""Ballot-capture report (issue #205 step 1): which candidate-generator
VARIANTS would have offered the moves humans and the Luna teacher actually
played, and at what ballot size.

Capture rate is the cheap proxy that orders variants BEFORE any equal-work
strength screen.  Engine-only and read-only on the harvested decision
records; production candidate generation (``shengji.ai``) is not touched and
the structural variants below never subclass or modify ``MCBot``.

Inputs
------
``human.jsonl`` (human_v8 decisions; every row carries its deck) and
``luna-rpc.private.jsonl`` (Luna teacher decisions; only the private split
carries the synthetic deck and the burial, so only it can be rebuilt).  Each
play record is rebuilt with ``rebuild.state_for_record``; bury records are
skipped (no ballot).  "Contested" = the production ballot has more than one
candidate; every rate is over contested decisions.  The played action is the
record's submitted ``action``.  Hidden-hand data never reaches the output:
the report carries counts, rates and category histograms only.

Variants — candidate SETS at a rebuilt state.  Every candidate passes
``legal.is_legal`` and every variant is a superset of ``production``
(``check_invariants`` refuses otherwise; the report never silently drifts).
---------------------------------------------------------------------------
production   ``luna.game._production_ballot``: the exact production set,
             TRACTOR_LOCK short-circuit included (a tractor-locked lead is
             one candidate, hence uncontested).
wide         ``luna.game.WideHeuristicBallotBot(seed=0)._candidates`` — the
             list Luna chose from (RETAIN_ALL_LEAD_PAIRS, V3_LEAD_SINGLES,
             RISKY_THROWS, TRUMP_BALLOT on; TRACTOR_LOCK off; caps 64) —
             unioned with production.
all-trump    production + every trump single and trump pair held (leads only;
             follows unchanged).
top-X-suit   production + the X highest singles of every effective suit held
             (X in {2, 3}; distinct codes by descending level, code as the
             tie-break; leads only).
points       production + every point-card (5/10/K) single: any suit on
             leads, the led suit on single-card follows (a follow must match
             the lead's size, so only single-card leads admit a single).
union        wide + all-trump + top-3-suit + points.

Uncaptured leads are broken down by shape (single/pair/tractor/throw, via
the engine's ``decompose``) x suit class (trump/off-suit) and, for singles,
by the played card's position among the DISTINCT levels the seat holds in
that effective suit: highest / second / middle / lowest (a two-level suit's
lower card is "lowest"; a one-card suit is "highest").
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from ..engine.cards import TRUMP, points
from ..engine.combos import decompose
from ..engine.legal import suit_cards, uniform_suit
from ..engine.round import Round
from .common import InputRegistry, action_key
from .legal import SUIT_ORDER, is_legal
from .rebuild import state_for_record

SCHEMA = "shengji-ballot-capture-report-v1"
Key = tuple[str, ...]

VARIANTS = ("production", "wide", "all-trump", "top-2-suit", "top-3-suit",
            "points", "union")
UNION_OF = ("wide", "all-trump", "top-3-suit", "points")
#: (source name, file name inside a harvest output directory)
SOURCE_FILES = (("human", "human.jsonl"), ("luna", "luna-rpc.private.jsonl"))
PHASES = ("lead", "follow")
SHAPES = ("single", "pair", "tractor", "throw")
SUIT_CLASSES = ("off-suit", "trump")
POSITIONS = ("highest", "second", "middle", "lowest")

DESCRIPTIONS = {
    "production": "luna.game._production_ballot (MCBot._candidates of "
                  "mc-s0-report-lcb; tractor-locked leads collapse to the pick)",
    "wide": "WideHeuristicBallotBot(seed=0)._candidates (RETAIN_ALL_LEAD_PAIRS, "
            "V3_LEAD_SINGLES, RISKY_THROWS, TRUMP_BALLOT on; TRACTOR_LOCK off; "
            "caps 64) | production",
    "all-trump": "production | every trump single and trump pair held (leads only)",
    "top-2-suit": "production | the 2 highest singles of every effective suit "
                  "held (leads only)",
    "top-3-suit": "production | the 3 highest singles of every effective suit "
                  "held (leads only)",
    "points": "production | every point-card (5/10/K) single: any suit on leads, "
              "the led suit on single-card follows",
    "union": "wide | all-trump | top-3-suit | points",
}


class BallotCaptureError(ValueError):
    """A variant broke an invariant or a record could not be scored."""


# ---------------------------------------------------------------- variants

def production_set(rnd: Round, seat: int) -> set[Key]:
    """The exact production ballot (TRACTOR_LOCK short-circuit included)."""
    from ..luna.game import _production_ballot
    return set(_production_ballot(rnd, seat))


def _legal_keys(rnd: Round, seat: int, keys: Iterable[Key]) -> set[Key]:
    return {k for k in keys if is_legal(rnd, seat, list(k))}


def wide_candidates(rnd: Round, seat: int) -> set[Key]:
    """The wide ballot Luna chose from, as the existing bot generates it."""
    from ..luna.game import WideHeuristicBallotBot
    bot = WideHeuristicBallotBot(seed=0)
    return {action_key(a) for a in bot._candidates(rnd, seat)}


def trump_lead_candidates(rnd: Round, seat: int) -> set[Key]:
    """Every trump single and trump pair held (leads only)."""
    assert rnd.trick is not None and rnd.ordering is not None
    if rnd.trick.plays:
        return set()
    cnt = Counter(suit_cards(rnd.hands[seat], TRUMP, rnd.ordering))
    keys = {(c,) for c in cnt} | {(c, c) for c, k in cnt.items() if k >= 2}
    return _legal_keys(rnd, seat, keys)


def top_single_candidates(rnd: Round, seat: int, x: int) -> set[Key]:
    """The ``x`` highest singles of every effective suit held (leads only)."""
    assert rnd.trick is not None and rnd.ordering is not None
    if rnd.trick.plays:
        return set()
    o = rnd.ordering
    hand = rnd.hands[seat]
    keys: set[Key] = set()
    for suit in SUIT_ORDER:
        codes = sorted(set(suit_cards(hand, suit, o)),
                       key=lambda c: (-o.level(c), c))
        keys.update((c,) for c in codes[:x])
    return _legal_keys(rnd, seat, keys)


def point_single_candidates(rnd: Round, seat: int) -> set[Key]:
    """Every point-card single: any suit on leads, the led suit on
    single-card follows."""
    assert rnd.trick is not None and rnd.ordering is not None
    o = rnd.ordering
    hand = rnd.hands[seat]
    if not rnd.trick.plays:
        pool = list(hand)
    else:
        lead = rnd.trick.plays[0].cards
        if len(lead) != 1:
            return set()
        led = uniform_suit(list(lead), o)
        assert led is not None
        pool = suit_cards(hand, led, o)
    return _legal_keys(rnd, seat, {(c,) for c in set(pool) if points(c)})


EXTENSIONS: dict[str, Callable[[Round, int], set[Key]]] = {
    "wide": wide_candidates,
    "all-trump": trump_lead_candidates,
    "top-2-suit": lambda rnd, seat: top_single_candidates(rnd, seat, 2),
    "top-3-suit": lambda rnd, seat: top_single_candidates(rnd, seat, 3),
    "points": point_single_candidates,
}


def variant_sets(rnd: Round, seat: int,
                 variants: Sequence[str] = VARIANTS) -> dict[str, set[Key]]:
    """Every requested variant at one state.

    The production set and each extension are computed once and shared, so
    the result equals calling the variant functions one by one.  A request
    without ``production`` still returns it (it is the baseline of every
    other set).
    """
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        raise BallotCaptureError(f"unknown variants: {unknown}")
    prod = production_set(rnd, seat)
    cache: dict[str, set[Key]] = {}

    def extra(name: str) -> set[Key]:
        if name not in cache:
            cache[name] = EXTENSIONS[name](rnd, seat)
        return cache[name]

    out: dict[str, set[Key]] = {"production": set(prod)}
    for name in variants:
        if name == "production":
            continue
        if name == "union":
            added = set().union(*(extra(n) for n in UNION_OF))
        else:
            added = extra(name)
        out[name] = prod | added
    return out


def variant_set(name: str, rnd: Round, seat: int) -> set[Key]:
    return variant_sets(rnd, seat, (name,))[name]


def wide_set(rnd: Round, seat: int) -> set[Key]:
    return variant_set("wide", rnd, seat)


def all_trump_set(rnd: Round, seat: int) -> set[Key]:
    return variant_set("all-trump", rnd, seat)


def top_suit_set(rnd: Round, seat: int, x: int = 3) -> set[Key]:
    if x not in (2, 3):
        raise BallotCaptureError("top-X-suit is defined for X in {2, 3}")
    return variant_set(f"top-{x}-suit", rnd, seat)


def points_set(rnd: Round, seat: int) -> set[Key]:
    return variant_set("points", rnd, seat)


def union_set(rnd: Round, seat: int) -> set[Key]:
    return variant_set("union", rnd, seat)


def check_invariants(rnd: Round, seat: int, sets: dict[str, set[Key]]) -> None:
    """Refuse a variant that drops a production candidate or offers an
    illegal one (the report must never mis-state either)."""
    prod = sets["production"]
    for name, keys in sets.items():
        missing = prod - keys
        if missing:
            raise BallotCaptureError(
                f"variant {name!r} lacks {len(missing)} production candidate(s)")
        for key in sorted(keys - prod if name != "production" else keys):
            if not is_legal(rnd, seat, list(key)):
                raise BallotCaptureError(
                    f"variant {name!r} offers an illegal action")


# ---------------------------------------------------------- classification

def classify_lead(rnd: Round, seat: int,
                  action: Sequence[str]) -> tuple[str, str, str | None]:
    """``(shape, suit class, single position)`` of a lead the seat played.

    Shape follows the engine's ``decompose``; the position of a single is
    its index among the DISTINCT levels held in that effective suit (the
    played card included): highest / second / middle / lowest.
    """
    o = rnd.ordering
    assert o is not None
    cards = list(action)
    dec = decompose(cards, o)
    if len(dec.components) > 1:
        shape = "throw"
    else:
        pair_len = dec.components[0].pair_len
        shape = "single" if pair_len == 0 else ("pair" if pair_len == 1 else "tractor")
    suit = o.eff_suit(cards[0])
    suit_class = "trump" if suit == TRUMP else "off-suit"
    position = None
    if shape == "single":
        levels = sorted({o.level(c) for c in suit_cards(rnd.hands[seat], suit, o)},
                        reverse=True)
        i = levels.index(o.level(cards[0]))
        if i == 0:
            position = "highest"
        elif i == len(levels) - 1:
            position = "lowest"
        elif i == 1:
            position = "second"
        else:
            position = "middle"
    return shape, suit_class, position


# ------------------------------------------------------------- decisions

def iter_records(path: Path, registry: InputRegistry,
                 limit: int | None = None) -> Iterator[dict]:
    """The first ``limit`` rows of a decision-record JSONL file (all rows
    when ``limit`` is None)."""
    for i, record in enumerate(registry.read_jsonl(path)):
        if limit is not None and i >= limit:
            break
        yield record


def score_record(record: dict, variants: Sequence[str]) -> dict:
    """One rebuilt play decision scored against every requested variant."""
    rnd = state_for_record(record)
    seat = int(record["seat"])
    if rnd.phase != "play" or rnd.turn != seat or rnd.trick is None:
        raise BallotCaptureError(
            f"{record.get('source_ref')}: rebuilt state is not the seat's play turn")
    sets = variant_sets(rnd, seat, variants)
    check_invariants(rnd, seat, sets)
    key = action_key(record["action"])
    phase = "lead" if not rnd.trick.plays else "follow"
    return {
        "phase": phase,
        "contested": len(sets["production"]) > 1,
        "captured": {name: key in keys for name, keys in sets.items()},
        "sizes": {name: len(keys) for name, keys in sets.items()},
        "lead_category": (classify_lead(rnd, seat, record["action"])
                          if phase == "lead" else None),
    }


def source_decisions(path: Path, registry: InputRegistry, variants: Sequence[str],
                     limit: int | None = None) -> tuple[list[dict], dict]:
    """Score every play record of one source file.  Returns the decisions
    and per-source counts (rows read, bury rows skipped, failed throws)."""
    counts = {"rows": 0, "play_decisions": 0, "bury_rows_skipped": 0,
              "engine_play_differs": 0}
    out: list[dict] = []
    for record in iter_records(path, registry, limit):
        counts["rows"] += 1
        if record.get("decision_kind") != "play":
            counts["bury_rows_skipped"] += 1
            continue
        if record.get("engine_play") is not None:
            counts["engine_play_differs"] += 1
        out.append(score_record(record, variants))
        counts["play_decisions"] += 1
    return out, counts


# ------------------------------------------------------------ aggregation

def _cell() -> dict:
    return {"decisions": 0, "contested": 0, "captured": 0, "uncaptured": 0,
            "candidates_total": 0, "candidates_max": 0}


def _finish(cell: dict) -> dict:
    n = cell["contested"]
    total = cell.pop("candidates_total")
    cell["capture_rate"] = (cell["captured"] / n) if n else None
    cell["candidates_mean"] = (total / n) if n else None
    return cell


def aggregate(decisions: Iterable[dict], variants: Sequence[str]) -> dict:
    """Per variant: overall / lead / follow cells (rates over contested
    decisions; candidate counts over contested decisions) and the
    uncaptured-lead breakdown."""
    names = list(dict.fromkeys(("production", *variants)))
    cells = {v: {"overall": _cell(), "lead": _cell(), "follow": _cell()} for v in names}
    shape_suit = {v: Counter() for v in names}
    position = {v: Counter() for v in names}
    for d in decisions:
        for v in names:
            for scope in ("overall", d["phase"]):
                cell = cells[v][scope]
                cell["decisions"] += 1
                if not d["contested"]:
                    continue
                cell["contested"] += 1
                size = d["sizes"][v]
                cell["candidates_total"] += size
                cell["candidates_max"] = max(cell["candidates_max"], size)
                if d["captured"][v]:
                    cell["captured"] += 1
                else:
                    cell["uncaptured"] += 1
            if d["contested"] and not d["captured"][v] and d["phase"] == "lead":
                shape, suit_class, pos = d["lead_category"]
                shape_suit[v][f"{shape}/{suit_class}"] += 1
                if pos is not None:
                    position[v][pos] += 1
    report = {}
    for v in names:
        report[v] = {
            "overall": _finish(cells[v]["overall"]),
            "lead": _finish(cells[v]["lead"]),
            "follow": _finish(cells[v]["follow"]),
            "uncaptured_leads": {
                "by_shape_suit": {f"{s}/{c}": shape_suit[v][f"{s}/{c}"]
                                  for s in SHAPES for c in SUIT_CLASSES},
                "single_position": {p: position[v][p] for p in POSITIONS},
            },
        }
    return report


# ----------------------------------------------------------------- report

def build_report(*, human: Path | None, luna: Path | None,
                 variants: Sequence[str] = VARIANTS, limit: int | None = None,
                 registry: InputRegistry | None = None) -> dict:
    """Score both sources and assemble the report (no timestamps: the
    report is a pure function of the inputs and the code)."""
    registry = registry or InputRegistry()
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        raise BallotCaptureError(f"unknown variants: {unknown}")
    # canonical order, production first: the JSON is written with sorted
    # keys, so the order lives in ``variant_order``
    names = tuple(v for v in VARIANTS if v == "production" or v in variants)
    notes = [
        "rates are over CONTESTED decisions (production ballot > 1 candidate); "
        "candidate means/maxima are over the same decisions",
        "the played action is the record's submitted action (engine_play, when "
        "present, is the engine's forced substitute for a failed throw)",
        "bury records carry no ballot and are skipped",
        "all-trump and top-X-suit add nothing on follows; points adds led-suit "
        "point singles on single-card follows only",
        "top-X-suit ranks distinct codes by descending level (code breaks ties) "
        "inside each effective suit, trump included",
        "single position is the played card's index among the distinct levels "
        "held in its effective suit (a two-level suit's lower card is 'lowest')",
        "no hidden-hand data: the report holds counts and rates only",
        "the ballot-gap report counts luna-rpc rows as contested when the recorded "
        "WIDE ballot has > 1 candidate; here contested is production > 1 for both "
        "sources, so the luna denominators differ from that report",
    ]
    if limit is not None:
        notes.append(f"limit: only the first {limit} rows of each input file were read")
    report: dict = {
        "schema": SCHEMA,
        "contested": "production ballot has more than one candidate",
        "variant_order": list(names),
        "variants": {v: DESCRIPTIONS[v] for v in names},
        "sources": {},
    }
    for name, path in (("human", human), ("luna", luna)):
        if path is None or not Path(path).is_file():
            notes.append(f"{name}: input file missing, source skipped"
                         + ("" if path is None else f" ({path})"))
            continue
        decisions, counts = source_decisions(Path(path), registry, names, limit)
        contested = sum(1 for d in decisions if d["contested"])
        report["sources"][name] = {
            "path": str(path),
            "counts": {**counts, "contested": contested,
                       "contested_lead": sum(1 for d in decisions
                                             if d["contested"] and d["phase"] == "lead"),
                       "contested_follow": sum(1 for d in decisions
                                               if d["contested"] and d["phase"] == "follow")},
            "variants": aggregate(decisions, names),
        }
        if counts["engine_play_differs"]:
            notes.append(f"{name}: {counts['engine_play_differs']} record(s) carry "
                         "engine_play (failed throw); capture uses the submitted action")
    report["notes"] = notes
    report["inputs"] = registry.rows()
    return report


def write_report(out_dir: Path, report: dict) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ballot_capture.json"
    md_path = out_dir / "ballot_capture.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(report))
    return json_path, md_path


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{100 * rate:.1f}%"


def _num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def chain(report: dict, source: str, scope: str) -> str:
    """``production 83.9% -> wide 97.1% -> ...`` for one source and scope."""
    src = report["sources"][source]
    return " -> ".join(f"{v} {_pct(src['variants'][v][scope]['capture_rate'])}"
                       for v in report["variant_order"])


def headline(report: dict) -> list[str]:
    lines = []
    for name in sorted(report["sources"]):
        src = report["sources"][name]
        c = src["counts"]
        lines.append(f"{name}: {c['play_decisions']} play decisions, {c['contested']} "
                     f"contested (lead {c['contested_lead']} / follow {c['contested_follow']})")
        for scope in ("lead", "follow", "overall"):
            lines.append(f"  {scope}: {chain(report, name, scope)}")
    return lines


def render_markdown(report: dict) -> str:
    out = [f"# Ballot capture ({report['schema']})", "",
           "Contested = production ballot has more than one candidate; every rate "
           "is over contested decisions.  Captured = the played action is in the "
           "variant's candidate set.", ""]
    order = report["variant_order"]
    out.append("## Variants")
    out.append("")
    for v in order:
        out.append(f"- `{v}`: {report['variants'][v]}")
    out.append("")
    for name in sorted(report["sources"]):
        src = report["sources"][name]
        c = src["counts"]
        out.append(f"## {name}: {c['play_decisions']} play decisions, {c['contested']} "
                   f"contested (lead {c['contested_lead']} / follow {c['contested_follow']})")
        out.append("")
        for scope in ("lead", "follow", "overall"):
            out.append(f"- {scope}: {chain(report, name, scope)}")
        out.append("")
        out.append("| variant | overall | lead | follow | mean cands (lead / follow) "
                   "| max cands (lead / follow) |")
        out.append("|---|---|---|---|---|---|")
        for v in order:
            agg = src["variants"][v]
            o, ld, fw = agg["overall"], agg["lead"], agg["follow"]
            out.append(
                f"| {v} | {_pct(o['capture_rate'])} ({o['captured']}/{o['contested']}) "
                f"| {_pct(ld['capture_rate'])} ({ld['captured']}/{ld['contested']}) "
                f"| {_pct(fw['capture_rate'])} ({fw['captured']}/{fw['contested']}) "
                f"| {_num(ld['candidates_mean'])} / {_num(fw['candidates_mean'])} "
                f"| {ld['candidates_max']} / {fw['candidates_max']} |")
        out.append("")
        out.append("Uncaptured leads by shape x suit class:")
        out.append("")
        keys = [f"{s}/{cl}" for s in SHAPES for cl in SUIT_CLASSES]
        out.append("| variant | uncaptured leads | " + " | ".join(keys) + " |")
        out.append("|---|---|" + "---|" * len(keys))
        for v in order:
            agg = src["variants"][v]
            bs = agg["uncaptured_leads"]["by_shape_suit"]
            out.append(f"| {v} | {agg['lead']['uncaptured']} | "
                       + " | ".join(str(bs[k]) for k in keys) + " |")
        out.append("")
        out.append("Uncaptured lead singles by position within their suit:")
        out.append("")
        out.append("| variant | " + " | ".join(POSITIONS) + " |")
        out.append("|---|" + "---|" * len(POSITIONS))
        for v in order:
            agg = src["variants"][v]
            sp = agg["uncaptured_leads"]["single_position"]
            out.append(f"| {v} | " + " | ".join(str(sp[p]) for p in POSITIONS) + " |")
        out.append("")
    out.append("## Notes")
    out.append("")
    for note in report["notes"]:
        out.append(f"- {note}")
    out.append("")
    out.append("## Inputs")
    out.append("")
    for row in report["inputs"]:
        out.append(f"- `{row['path']}` sha256 `{row['sha256']}`")
    out.append("")
    return "\n".join(out)
