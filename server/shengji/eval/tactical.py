"""Tactical regression fixtures for the served search (#677 strategy 4, #676).

A fixture is one position where a concrete bad decision was observed, stored
with ONLY the information the acting seat had at the time: the public setup
(trump, banker, declarations), the public play history (engine cards, plus
the attempted cards of a refused throw -- the refusal notice is public), and
the acting seat's own hand (plus its own burial when it is the banker).  No
hidden hand is stored.  ``public_round`` rebuilds an engine ``Round`` at the
decision with PLACEHOLDER hidden hands (a deterministic fill of the unseen
pool); the served bot samples its own worlds from the public state, so the
placeholder never reaches a value or a prior (``test_tactical_fixtures``
proves the decision is invariant to the fill).

Each fixture names a predicate for an acceptable action.  Predicates judge
with information available at the time as well: the bot's OWN sampled worlds
(for "doomed throw"), the public refusal history, or the engine's trick
arithmetic in last position (where the trick outcome is exact).  The set is
diagnostic, not a gate: the production bot is expected to fail some of it,
and a screen of an admission or tie-break change reads which fixtures moved.
"""

from __future__ import annotations

import copy
import json
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..engine.cards import Ordering, make_deck, total_points
from ..engine.combos import decompose
from ..engine.legal import IllegalPlay, beats, uniform_suit, validate_follow, validate_lead
from ..engine.round import HAND_SIZE, KITTY_SIZE, Round, TrickPlay
from ..harvest.legal import enumerate_legal
from ..harvest.rebuild import RebuildError, round_from_setup, synthetic_deck

SCHEMA = "tactical-fixture-v1"
FIXTURES_PATH = Path(__file__).resolve().parents[2] / "tests" / "tactical" / "fixtures.jsonl"

CATEGORIES = ("doomed-throw", "point-donation", "missed-point-win", "shortlist-miss",
              "repeated-failed-throw")
OBSERVATION_CATEGORY = "observation"

# The production play recipe (fly.toml, release 36).  A caller that pins only the
# package gets exactly the served name; every knob can still be overridden.
PRODUCTION_PLAY_ENV = {
    "SHENGJI_PV_WORLDS": "64", "SHENGJI_PV_CANDIDATES": "8", "SHENGJI_PV_CAP": "4000",
    "SHENGJI_PV_BATCH_SIZE": "128", "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3",
    "SHENGJI_PV_BURY_ARM": "hybrid", "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2",
}
PRODUCTION_BOT = "pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25"
OBSERVATION_COMPARISON_SEEDS = (0, 1, 2)
OBSERVATION_COMPARISON_FILL_SEED = 0
OBSERVATION_COMPARISON_SHA256 = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
OBSERVATION_COMPARISON_FLAGS = (
    "SHENGJI_PV_ADMISSION_DIVERSITY", "SHENGJI_PV_REFUSAL_CONSTRAINTS",
    "SHENGJI_PV_TIEBREAK_POINTS", "SHENGJI_PV_LEAD_ANCHOR",
)


class TacticalError(ValueError):
    pass


# ------------------------------------------------------------------ fixtures

@dataclass
class Fixture:
    id: str
    category: str
    source: dict
    seat: int
    setup: dict                 # trump_rank, trump_suit, trump_is_nt, banker, declarations, buried|None
    plays: list[dict]           # public history: {"seat", "cards"[, "attempted"]}, engine cards
    hand: list[str]             # the acting seat's hand at the decision
    observed: dict              # what the bot did: action, engine_play, admitted, value_means
    predicate: str
    args: dict
    why: str
    current_bot: str | None = None   # "pass" | "fail" recorded for PRODUCTION_BOT (xfail marker)
    notes: str = ""

    @property
    def trick(self) -> int:
        return len(self.plays) // 4

    @property
    def position(self) -> int:
        return len(self.plays) % 4

    def to_json(self) -> dict:
        return {"schema": SCHEMA, "id": self.id, "category": self.category,
                "source": self.source, "seat": self.seat, "trick": self.trick,
                "position": self.position, "setup": self.setup, "plays": self.plays,
                "hand": self.hand, "observed": self.observed,
                "predicate": {"name": self.predicate, "args": self.args},
                "why": self.why, "current_bot": self.current_bot, "notes": self.notes}


def fixture_from_json(row: Mapping[str, Any]) -> Fixture:
    if row.get("schema") != SCHEMA:
        raise TacticalError(f"fixture schema {row.get('schema')!r} != {SCHEMA}")
    pred = row["predicate"]
    fx = Fixture(id=str(row["id"]), category=str(row["category"]), source=dict(row["source"]),
                 seat=int(row["seat"]), setup=dict(row["setup"]),
                 plays=[dict(p) for p in row["plays"]], hand=list(row["hand"]),
                 observed=dict(row.get("observed") or {}), predicate=str(pred["name"]),
                 args=dict(pred.get("args") or {}), why=str(row.get("why", "")),
                 current_bot=row.get("current_bot"), notes=str(row.get("notes", "")))
    validate_fixture(fx)
    return fx


def validate_fixture(fx: Fixture) -> None:
    if fx.category not in CATEGORIES and fx.category != OBSERVATION_CATEGORY:
        raise TacticalError(f"{fx.id}: unknown category {fx.category!r}")
    if fx.predicate not in PREDICATES:
        raise TacticalError(f"{fx.id}: unknown predicate {fx.predicate!r}")
    if fx.category == OBSERVATION_CATEGORY:
        if fx.predicate != "observe_follow":
            raise TacticalError(f"{fx.id}: observation fixtures must use observe_follow")
        if fx.current_bot is not None:
            raise TacticalError(f"{fx.id}: observation fixtures must not record current_bot")
    elif fx.predicate == "observe_follow":
        raise TacticalError(f"{fx.id}: observe_follow requires the observation category")
    if fx.seat not in range(4):
        raise TacticalError(f"{fx.id}: seat {fx.seat}")
    if fx.current_bot not in (None, "pass", "fail"):
        raise TacticalError(f"{fx.id}: current_bot must be pass/fail/null")
    own = Counter(fx.hand) + Counter(c for p in fx.plays if p["seat"] == fx.seat for c in p["cards"])
    if sum(own.values()) != HAND_SIZE:
        raise TacticalError(f"{fx.id}: hand + own plays is {sum(own.values())} cards, not {HAND_SIZE}")
    buried = fx.setup.get("buried")
    if fx.seat == fx.setup["banker"]:
        if not buried or len(buried) != KITTY_SIZE:
            raise TacticalError(f"{fx.id}: the banker's fixture must carry its own burial")
    elif buried:
        raise TacticalError(f"{fx.id}: a non-banker fixture must not store the burial (hidden)")
    for p in fx.plays:
        if p["seat"] not in range(4) or not p["cards"]:
            raise TacticalError(f"{fx.id}: malformed play {p}")
    deck = Counter(make_deck())
    seen = own + Counter(c for p in fx.plays if p["seat"] != fx.seat for c in p["cards"]) \
        + Counter(buried or [])
    if seen - deck:
        raise TacticalError(f"{fx.id}: cards beyond the deck: {dict(seen - deck)}")


def load_fixtures(path: Path | str = FIXTURES_PATH) -> list[Fixture]:
    out: list[Fixture] = []
    ids: set[str] = set()
    with Path(path).open() as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                fx = fixture_from_json(json.loads(line))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise TacticalError(f"{path}:{n}: {exc}") from exc
            if fx.id in ids:
                raise TacticalError(f"{path}:{n}: duplicate id {fx.id}")
            ids.add(fx.id)
            out.append(fx)
    return out


# --------------------------------------------------------- public rebuild

def _played_by(plays: Sequence[Mapping[str, Any]]) -> dict[int, Counter]:
    by = {s: Counter() for s in range(4)}
    for p in plays:
        by[int(p["seat"])].update(p["cards"])
    return by


def placeholder_hands(fx: Fixture, fill_seed: int = 0) -> tuple[list[list[str]], list[str]]:
    """Start-of-play hands and burial with the hidden cards filled from the
    unseen pool.  The acting seat's hand (and its burial as banker) is real;
    every other card is a placeholder, pinned only where public information
    fixes it (shown declaration cards stay with their declarer)."""
    banker = int(fx.setup["banker"])
    by = _played_by(fx.plays)
    pool = Counter(make_deck()) - Counter(fx.hand) - Counter(fx.setup.get("buried") or [])
    for s in range(4):
        pool -= by[s]
    if any(n < 0 for n in pool.values()):
        raise TacticalError(f"{fx.id}: public cards exceed the deck")
    hands: list[list[str]] = [[] for _ in range(4)]
    hands[fx.seat] = sorted((Counter(fx.hand) + by[fx.seat]).elements())
    pins: dict[int, Counter] = {s: Counter() for s in range(4)}
    for d in fx.setup.get("declarations") or []:
        s = int(d["seat"])
        if s != fx.seat:
            pins[s] += Counter(d["cards"]) - by[s]
    for s in range(4):
        if s == fx.seat:
            continue
        if pins[s] - pool:
            raise TacticalError(f"{fx.id}: declared cards of seat {s} are not in the unseen pool")
        pool -= pins[s]
    free = sorted(pool.elements())
    random.Random(fill_seed).shuffle(free)
    for s in range(4):
        if s == fx.seat:
            continue
        need = HAND_SIZE - sum(by[s].values()) - sum(pins[s].values())
        if need < 0 or need > len(free):
            raise TacticalError(f"{fx.id}: cannot fill seat {s} ({need} cards needed)")
        take, free = free[:need], free[need:]
        hands[s] = sorted(by[s].elements()) + sorted(pins[s].elements()) + take
        hands[s].sort()
    if fx.seat == banker:
        buried = sorted(fx.setup["buried"])
    else:
        buried = sorted(free[:KITTY_SIZE])
        free = free[KITTY_SIZE:]
    if free:
        raise TacticalError(f"{fx.id}: {len(free)} unseen cards left over after the fill")
    return hands, buried


def _replay_public(rnd: Round, plays: Sequence[Mapping[str, Any]], seat: int) -> None:
    """`Round.play` minus the validators that read other hands.  The acting
    seat's own follows are still validated against its (real) hand; nothing
    else is, because the other hands are placeholders.  Trick resolution,
    turn order, notices and point accounting are the engine's own."""
    for p in plays:
        s, cards = int(p["seat"]), list(p["cards"])
        rnd._require(s, "play")
        assert rnd.trick is not None and rnd.ordering is not None
        rnd.message = None
        if rnd.trick.plays and s == seat:
            validate_follow(cards, rnd.hands[s], rnd.trick.plays[0].cards, rnd.ordering)
        elif not rnd.trick.plays and uniform_suit(cards, rnd.ordering) is None:
            raise IllegalPlay("A lead must be a single suit (throws included).")
        rnd._remove(s, cards)
        rnd._age_notice()
        attempted = p.get("attempted")
        if attempted and sorted(attempted) != sorted(cards):
            rnd._set_notice(s, list(attempted), list(cards))
        rnd.trick.plays.append(TrickPlay(s, cards))
        if len(rnd.trick.plays) == 4:
            rnd._resolve_trick()
        else:
            rnd.turn = (s + 1) % 4


def public_round(fx: Fixture, fill_seed: int = 0) -> Round:
    """The decision root: real public state + the acting seat's hand, placeholder
    hidden hands.  Raises if the public history does not replay to the seat's turn
    with the stored hand."""
    setup = fx.setup
    if not setup.get("declarations"):
        raise TacticalError(f"{fx.id}: a kitty-flipped trump is not supported by the public rebuild")
    hands, buried = placeholder_hands(fx, fill_seed)
    final = setup["declarations"][-1]
    declaration = {"seat": int(final["seat"]), "cards": list(final["cards"])}
    try:
        deck = synthetic_deck(hands, buried, banker=int(setup["banker"]), declaration=declaration,
                              trump_suit=setup.get("trump_suit"),
                              trump_is_nt=bool(setup.get("trump_is_nt")))
        rnd = round_from_setup(deck, {
            "trump_rank": setup["trump_rank"], "banker": int(setup["banker"]),
            "declarations": [{"seat": int(d["seat"]), "cards": list(d["cards"])}
                             for d in setup["declarations"]],
            "trump_suit": setup.get("trump_suit"), "trump_is_nt": bool(setup.get("trump_is_nt")),
            "buried": buried})
    except (RebuildError, IllegalPlay) as exc:
        raise TacticalError(f"{fx.id}: public rebuild failed: {exc}") from exc
    _replay_public(rnd, fx.plays, fx.seat)
    if rnd.phase != "play" or rnd.turn != fx.seat:
        raise TacticalError(f"{fx.id}: history ends with seat {rnd.turn} to act, not {fx.seat}")
    if sorted(rnd.hands[fx.seat]) != sorted(fx.hand):
        raise TacticalError(f"{fx.id}: replayed hand differs from the stored hand")
    return rnd


def public_fixture(rnd_before: Round, seat: int, plays: Sequence[Mapping[str, Any]],
                   declarations: Sequence[Mapping[str, Any]], *,
                   id: str, category: str, source: Mapping[str, Any], observed: Mapping[str, Any],
                   predicate: str, args: Mapping[str, Any] | None = None, why: str = "",
                   notes: str = "") -> Fixture:
    """Strip a FULL rebuilt round (deck known) down to the acting seat's view.
    ``rnd_before`` is the state at the decision; ``plays`` the public history
    that produced it (engine cards, ``attempted`` where a throw was refused);
    ``declarations`` the public declaration sequence."""
    if rnd_before.turn != seat or rnd_before.phase != "play":
        raise TacticalError("rnd_before must be the acting seat's decision state")
    decls = [{"seat": int(d["seat"]), "cards": list(d["cards"])} for d in declarations]
    setup = {"trump_rank": rnd_before.trump_rank, "trump_suit": rnd_before.trump_suit,
             "trump_is_nt": bool(rnd_before.trump_is_nt), "banker": int(rnd_before.banker),
             "declarations": decls,
             "buried": sorted(rnd_before.buried) if seat == rnd_before.banker else None}
    fx = Fixture(id=id, category=category, source=dict(source), seat=seat, setup=setup,
                 plays=[dict(p) for p in plays], hand=sorted(rnd_before.hands[seat]),
                 observed=dict(observed), predicate=predicate, args=dict(args or {}), why=why,
                 notes=notes)
    validate_fixture(fx)
    # the stored view must rebuild to the same public state the full round has
    twin = public_round(fx)
    if [p.cards for p in twin.trick.plays] != [p.cards for p in rnd_before.trick.plays] \
            or len(twin.history) != len(rnd_before.history):
        raise TacticalError(f"{id}: public rebuild does not reproduce the trick state")
    return fx


# ------------------------------------------------------------- predicates

@dataclass
class Context:
    rnd: Round                   # the decision root (placeholder hidden hands)
    seat: int
    action: list[str]
    record: dict | None          # the bot's last_decision_record
    worlds: list                 # the bot's own sampled worlds [(hands, buried)]
    fixture: Fixture


Verdict = tuple[bool | None, str]


def _key(cards: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(cards))


def _trick_winner(plays: Sequence[tuple[int, Sequence[str]]], o: Ordering) -> int:
    """`Round._resolve_trick`'s arithmetic over (seat, cards) plays."""
    lead = list(plays[0][1])
    suit = uniform_suit(lead, o)
    top = decompose(lead, o).top_level()
    winner = plays[0][0]
    for seat, cards in plays[1:]:
        won, new_top = beats(list(cards), lead, suit, top, o)
        if won:
            winner, top, suit = seat, new_top, o.eff_suit(cards[0])
    return winner


def _same_team(a: int, b: int) -> bool:
    return a % 2 == b % 2


def _legal_actions(ctx: Context, cap: int | None = 4000) -> list[list[str]]:
    legal = enumerate_legal(ctx.rnd, ctx.seat, cap=cap, must_include=[ctx.action])
    return [list(a) for a in legal.actions]


def not_a_doomed_throw(ctx: Context, max_fail_fraction: float = 0.5) -> Verdict:
    """The action is not a multi-component lead that the bot's OWN sampled
    worlds refuse (engine `validate_lead`) in more than ``max_fail_fraction``
    of them.  Single-component leads and follows pass trivially."""
    rnd = ctx.rnd
    if rnd.trick is None or rnd.trick.plays:
        return True, "follow: not a throw"
    o = rnd.ordering
    if uniform_suit(ctx.action, o) is None or len(decompose(ctx.action, o).components) == 1:
        return True, f"{'+'.join(ctx.action)} is a single component"
    if not ctx.worlds:
        return False, "no sampled worlds captured (fallback decision?)"
    failed = 0
    for hands, _buried in ctx.worlds:
        others = [hands[s] for s in range(4) if s != ctx.seat]
        cards, _msg = validate_lead(list(ctx.action), rnd.hands[ctx.seat], others, o)
        if _key(cards) != _key(ctx.action):
            failed += 1
    frac = failed / len(ctx.worlds)
    ok = frac <= max_fail_fraction
    return ok, (f"throw {'+'.join(ctx.action)} refused in {failed}/{len(ctx.worlds)} of the bot's "
                f"own worlds ({frac:.0%}; limit {max_fail_fraction:.0%})")


def not_a_throw_refuted_by_public_refusal(ctx: Context, suit: str, pair_len: int, top: str,
                                          refusal_index: int) -> Verdict:
    """After a PUBLIC refusal (a throw of this seat was forced down to component
    ``top`` of ``pair_len`` in effective ``suit`` at play ``refusal_index``), the
    table knows some other hand beats that component.  Unless a beating structure
    has since been played, a new throw whose components include one of the same
    suit, same pair length and no higher top is refuted by public information."""
    rnd = ctx.rnd
    o = rnd.ordering
    if rnd.trick is None or rnd.trick.plays:
        return True, "follow: not a throw"
    if uniform_suit(ctx.action, o) is None:
        return False, "mixed-suit lead"
    dec = decompose(ctx.action, o)
    if len(dec.components) == 1:
        return True, f"{'+'.join(ctx.action)} is a single component"
    level = o.level(top)
    # beating cards played by other seats since the refusal weaken the inference
    since = Counter(c for p in ctx.fixture.plays[refusal_index + 1:]
                    if p["seat"] != ctx.seat for c in p["cards"]
                    if o.eff_suit(c) == suit and o.level(c) > level)
    if (pair_len == 0 and sum(since.values()) > 0) or \
            (pair_len >= 1 and any(n >= 2 for n in since.values())):
        return True, "a beating structure was played after the refusal; inference void"
    for comp in dec.components:
        if o.eff_suit(comp.cards[0]) == suit and comp.pair_len == pair_len and comp.top <= level:
            return False, (f"throw {'+'.join(ctx.action)} repeats a {suit} component "
                           f"({'+'.join(comp.cards)}) no higher than the one refused ({top})")
    return True, f"throw {'+'.join(ctx.action)} carries no component the refusal refuted"


def no_point_donation_when_zero_point_alternative_exists(ctx: Context) -> Verdict:
    """Last to play, opponents winning the trick whatever we do with this action:
    do not play points when a zero-point legal action exists."""
    rnd = ctx.rnd
    if rnd.trick is None or len(rnd.trick.plays) != 3:
        return False, "predicate applies to the last position only"
    o = rnd.ordering
    table = [(p.seat, p.cards) for p in rnd.trick.plays]
    if _same_team(_trick_winner(table + [(ctx.seat, ctx.action)], o), ctx.seat):
        return True, "our team wins the trick"
    pts = total_points(ctx.action)
    if pts == 0:
        return True, "no points played"
    zero = [a for a in _legal_actions(ctx) if total_points(a) == 0]
    if not zero:
        return True, "every legal action carries points"
    return False, (f"donated {pts} points with {'+'.join(ctx.action)}; {len(zero)} zero-point "
                   f"legal alternatives (e.g. {'+'.join(zero[0])})")


def wins_point_trick_when_available(ctx: Context, min_points: int = 10) -> Verdict:
    """Last to play with at least ``min_points`` on the table: if some legal
    action wins the trick for our team, the action wins it."""
    rnd = ctx.rnd
    if rnd.trick is None or len(rnd.trick.plays) != 3:
        return False, "predicate applies to the last position only"
    o = rnd.ordering
    table = [(p.seat, p.cards) for p in rnd.trick.plays]
    on_table = sum(total_points(c) for _, c in table)
    if on_table < min_points:
        return True, f"only {on_table} points on the table"
    if _same_team(_trick_winner(table + [(ctx.seat, ctx.action)], o), ctx.seat):
        return True, f"our team takes the {on_table} points"
    winners = [a for a in _legal_actions(ctx)
               if _same_team(_trick_winner(table + [(ctx.seat, a)], o), ctx.seat)]
    if not winners:
        return True, "no legal action wins the trick"
    return False, (f"{on_table} points lost with {'+'.join(ctx.action)}; {len(winners)} winning "
                   f"alternatives (e.g. {'+'.join(winners[0])})")


def structured_lead_admitted(ctx: Context, actions: Sequence[Sequence[str]]) -> Verdict:
    """The admitted ballot contains at least one of ``actions`` (a structured
    lead the shortlist missed; the value head preferred it when it was drawn)."""
    if not ctx.record or ctx.record.get("work_complete") is not True:
        return False, "no complete search record (fallback decision?)"
    admitted = {_key(a) for a in ctx.record.get("admitted") or []}
    hits = [a for a in actions if _key(a) in admitted]
    if hits:
        return True, f"admitted {'+'.join(hits[0])}"
    return False, (f"none of {[ '+'.join(a) for a in actions]} admitted; ballot "
                   f"{['+'.join(a) for a in ctx.record.get('admitted') or []]}")


def admitted_ballot_not_crowded(ctx: Context, max_same_suit_throws: int = 4) -> Verdict:
    """At most ``max_same_suit_throws`` of the admitted candidates are
    multi-component leads (throws) in one effective suit: a ballot of
    near-duplicate throw variants has spent its slots on one plan (#677)."""
    if not ctx.record or ctx.record.get("work_complete") is not True:
        return False, "no complete search record (fallback decision?)"
    rnd = ctx.rnd
    if rnd.trick is None or rnd.trick.plays:
        return True, "follow: no lead ballot"
    o = rnd.ordering
    per_suit: Counter = Counter()
    for a in ctx.record.get("admitted") or []:
        suit = uniform_suit(list(a), o)
        if suit is not None and len(decompose(list(a), o).components) > 1:
            per_suit[suit] += 1
    if not per_suit:
        return True, "no throws admitted"
    suit, n = per_suit.most_common(1)[0]
    total = len(ctx.record.get("admitted") or [])
    ok = n <= max_same_suit_throws
    return ok, f"{n}/{total} admitted candidates are {suit}-suit throws (limit {max_same_suit_throws})"


def observe_follow(ctx: Context) -> Verdict:
    """Marker predicate for a bounded, non-scored follow observation.

    The runner performs the engine legality check and emits local trick
    consequences.  There is deliberately no claim that the chosen follow or
    any admitted alternative is better.
    """
    return None, "observed follow; no best-action verdict"


PREDICATES: dict[str, Callable[..., Verdict]] = {
    "not_a_doomed_throw": not_a_doomed_throw,
    "not_a_throw_refuted_by_public_refusal": not_a_throw_refuted_by_public_refusal,
    "no_point_donation_when_zero_point_alternative_exists":
        no_point_donation_when_zero_point_alternative_exists,
    "wins_point_trick_when_available": wins_point_trick_when_available,
    "structured_lead_admitted": structured_lead_admitted,
    "admitted_ballot_not_crowded": admitted_ballot_not_crowded,
    "observe_follow": observe_follow,
}


def refusal_args(fx_plays: Sequence[Mapping[str, Any]], seat: int, ordering: Ordering) -> dict:
    """Arguments for `not_a_throw_refuted_by_public_refusal` from the LAST public
    refusal of ``seat`` in the history: the forced component's suit, pair length,
    top card and the play's index."""
    for index in range(len(fx_plays) - 1, -1, -1):
        p = fx_plays[index]
        if int(p["seat"]) == seat and p.get("attempted") \
                and sorted(p["attempted"]) != sorted(p["cards"]):
            comp = decompose(list(p["cards"]), ordering).components[0]
            top = max(comp.cards, key=ordering.level)
            return {"suit": ordering.eff_suit(comp.cards[0]), "pair_len": comp.pair_len,
                    "top": top, "refusal_index": index}
    raise TacticalError(f"seat {seat} has no public refusal in the history")


# ---------------------------------------------------------------- running

@dataclass
class Result:
    fixture: Fixture
    action: list[str] | None
    passed: bool | None
    detail: str
    record: dict | None = None
    seconds: float = 0.0
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        if self.passed is None:
            return "observed"
        return "pass" if self.passed else "FAIL"


def _observation_consequence(rnd: Round, seat: int, action: Sequence[str]) -> dict:
    """Validate a follow and report only facts local to the current trick."""
    if rnd.trick is None or not rnd.trick.plays:
        raise IllegalPlay("observation follow requires a non-empty lead")
    if not action:
        raise IllegalPlay("observation follow cannot be empty")
    assert rnd.ordering is not None
    lead = rnd.trick.plays[0].cards
    validate_follow(list(action), list(rnd.hands[seat]), lead, rnd.ordering)
    table = [(p.seat, p.cards) for p in rnd.trick.plays]
    table.append((seat, list(action)))
    residual = Counter(rnd.hands[seat]) - Counter(action)
    return {
        "action": list(action),
        "current_winner": _trick_winner(table, rnd.ordering),
        "current_points": total_points(c for _s, cards in table for c in cards),
        "trick_complete": len(table) == 4,
        "residual_hand": sorted(residual.elements()),
    }


def _observation_result(rnd: Round, fx: Fixture, action: list[str],
                        record: dict | None, seconds: float) -> Result:
    """Validate and summarize an observation without judging its preference."""
    try:
        chosen = _observation_consequence(rnd, fx.seat, action)
        observation = {k: chosen[k] for k in
                       ("current_winner", "current_points", "trick_complete", "residual_hand")}
        if record and record.get("work_complete") is True:
            observation["admitted"] = [
                _observation_consequence(rnd, fx.seat, list(candidate))
                for candidate in record.get("admitted") or []
            ]
        return Result(fx, action, None, "observed follow; no best-action verdict",
                      record=record, seconds=seconds, extra={"observation": observation})
    except Exception as exc:
        return Result(fx, action, None, f"{type(exc).__name__}: {exc}", record=record,
                      seconds=seconds, error="observation")


def run_fixture(bot, fx: Fixture, *, fill_seed: int = 0) -> Result:
    """Run ``bot.decide_play`` on the fixture's public root and judge the action.

    The bot's own sampled worlds are captured by shadowing ``_worlds`` on the
    instance for the duration of the call -- purely observing, the sampler's
    stream and the decision are what they would be without the capture."""
    try:
        rnd = public_round(fx, fill_seed)
    except TacticalError as exc:
        return Result(fx, None, False, str(exc), error="rebuild")
    captured: dict[str, Any] = {}
    original = getattr(type(bot), "_worlds", None)
    # Observation fixtures must not retain or inspect sampled opponent worlds.
    capture_worlds = fx.category != OBSERVATION_CATEGORY
    if original is not None and capture_worlds:
        def _worlds(rnd_, seat_, check_budget=None):
            worlds, attempts = original(bot, rnd_, seat_, check_budget)
            captured["worlds"] = worlds
            return worlds, attempts
        bot._worlds = _worlds
    started = time.perf_counter()
    try:
        action = list(bot.decide_play(copy.deepcopy(rnd), fx.seat))
    except Exception as exc:  # the report must list the failure, not abort the set
        return Result(fx, None, False, f"{type(exc).__name__}: {exc}", error="decide_play",
                      seconds=time.perf_counter() - started)
    finally:
        if original is not None and capture_worlds:
            try:
                del bot._worlds
            except AttributeError:
                pass
    seconds = time.perf_counter() - started
    record = getattr(bot, "last_decision_record", None)
    if fx.category == OBSERVATION_CATEGORY:
        return _observation_result(rnd, fx, action, record, seconds)
    ctx = Context(rnd=rnd, seat=fx.seat, action=action, record=record,
                  worlds=list(captured.get("worlds") or []), fixture=fx)
    try:
        ok, detail = PREDICATES[fx.predicate](ctx, **fx.args)
    except Exception as exc:
        return Result(fx, action, False, f"{type(exc).__name__}: {exc}", record=record,
                      seconds=seconds, error="predicate")
    extra = {}
    if record and record.get("work_complete") is True:
        means = record.get("value_means") or []
        extra["value_spread"] = (max(means) - min(means)) if means else None
    elif record:
        extra["fallback"] = record.get("reason")
    return Result(fx, action, ok, detail, record=record, seconds=seconds, extra=extra)


def run_set(make_bot: Callable[[], Any], fixtures: Sequence[Fixture], *, fill_seed: int = 0,
            progress: Callable[[Result], None] | None = None) -> list[Result]:
    """One FRESH bot per fixture (``make_bot()``), so every verdict is a function
    of the fixture and the bot's seed alone, never of the order of the set."""
    out = []
    for fx in fixtures:
        res = run_fixture(make_bot(), fx, fill_seed=fill_seed)
        out.append(res)
        if progress is not None:
            progress(res)
    return out


def observation_comparison_environs(checkpoint: str, sha256: str) -> dict[str, dict[str, str]]:
    """Return frozen r36-SMV3 control and the four-flag DEV treatment."""
    control = production_environ(checkpoint, sha256)
    treatment = dict(control)
    treatment.update({flag: "1" for flag in OBSERVATION_COMPARISON_FLAGS})
    differing = {key for key in set(control) | set(treatment)
                 if control.get(key) != treatment.get(key)}
    if differing != set(OBSERVATION_COMPARISON_FLAGS):
        raise TacticalError(f"comparison changes unexpected keys: {sorted(differing)}")
    return {"r36-smv3": control, "div+rc+tb+la": treatment}


def run_observation_comparison(make_control: Callable[[int], Any],
                               make_treatment: Callable[[int], Any],
                               fixtures: Sequence[Fixture], *,
                               seeds: Sequence[int] = OBSERVATION_COMPARISON_SEEDS,
                               fill_seed: int = OBSERVATION_COMPARISON_FILL_SEED) -> list[dict]:
    """Run four public observations paired at identical roots and seeds."""
    if len(fixtures) != 4 or any(fx.category != OBSERVATION_CATEGORY or fx.current_bot is not None
                                 for fx in fixtures):
        raise TacticalError("comparison requires exactly four unstamped observation fixtures")
    if len({fx.id for fx in fixtures}) != 4:
        raise TacticalError("comparison roots must be unique")
    rows = []
    for seed in seeds:
        for fx in fixtures:
            control = run_fixture(make_control(seed), fx, fill_seed=fill_seed)
            treatment = run_fixture(make_treatment(seed), fx, fill_seed=fill_seed)
            if control.status != "observed" or treatment.status != "observed":
                raise TacticalError(f"{fx.id}/seed {seed}: comparison is not observed-only")
            rows.append({"fixture": fx.id, "seed": seed, "fill_seed": fill_seed,
                         "control": control, "treatment": treatment})
    # Coverage is post-decision diagnostics, outside policy timing. Enumerate
    # once per public fixture, never using an opponent's actual hidden hand.
    from shengji.harvest.legal import enumerate_legal
    from shengji.train.ballot_opportunity import summarize_opportunities
    pools = {}
    for fx in fixtures:
        rnd = public_round(fx, fill_seed=fill_seed)
        pools[fx.id] = enumerate_legal(rnd, fx.seat, cap=None)
    for row in rows:
        legal = pools[row['fixture']]
        for arm in ('control', 'treatment'):
            result = row[arm]
            record = result.record
            if (not isinstance(record, dict) or record.get('work_complete') is not True
                    or 'admitted' not in record):
                raise TacticalError('complete admitted-action telemetry required for coverage')
            result.extra['ballot_opportunity'] = summarize_opportunities(
                result.fixture.hand, legal.actions, record['admitted'],
                legal_complete=legal.complete)
    return rows


def observation_decision_metadata(result: Result) -> dict:
    """Expose only decision telemetry safe for an observation comparison."""
    record = result.record or {}
    return {key: record[key] for key in ("work_complete", "admitted", "value_means")
            if key in record} | {"seconds": result.seconds}


def format_table(results: Sequence[Result], bot_name: str | None = None) -> str:
    rows = [("id", "category", "status", "known", "action", "observed", "secs", "detail")]
    for r in results:
        fx = r.fixture
        rows.append((fx.id, fx.category, r.status, fx.current_bot or "-",
                     "+".join(r.action) if r.action else "-",
                     "+".join(fx.observed.get("action") or []) or "-",
                     f"{r.seconds:.2f}", r.detail))
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]) - 1)]
    lines = []
    if bot_name:
        lines.append(f"bot: {bot_name}")
    for row in rows:
        lines.append("  ".join(str(v).ljust(w) for v, w in zip(row[:-1], widths)) + "  " + str(row[-1]))
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "FAIL")
    errors = sum(1 for r in results if r.status == "ERROR")
    observed = sum(1 for r in results if r.status == "observed")
    by_cat: dict[str, list[int]] = {}
    for r in results:
        if r.status == "observed":
            continue
        by_cat.setdefault(r.fixture.category, [0, 0])
        by_cat[r.fixture.category][1] += 1
        if r.status == "pass":
            by_cat[r.fixture.category][0] += 1
    scored = passed + failed + errors
    by_category = ", ".join(f"{k} {p}/{t}" for k, (p, t) in sorted(by_cat.items()))
    if observed:
        lines.append(f"total: {passed} pass, {failed} fail, {errors} error of {scored}; "
                     f"observations: {observed}; by category: {by_category}")
    else:
        lines.append(f"total: {passed} pass, {failed} fail, {errors} error of {scored}; by category: "
                     + by_category)
    moved = [r for r in results if r.fixture.current_bot and
             r.status in ("pass", "FAIL") and
             (r.status == "pass") != (r.fixture.current_bot == "pass")]
    if moved:
        lines.append("moved vs the recorded production verdict: "
                     + ", ".join(f"{r.fixture.id} ({r.fixture.current_bot}->{r.status})" for r in moved))
    return "\n".join(lines)


# ----------------------------------------------------------- the served bot

def production_environ(checkpoint: str, sha256: str, **overrides: str) -> dict[str, str]:
    """A fly.toml-shaped environment for the production play recipe on a local
    package path.  ``overrides`` replace individual ``SHENGJI_PV_*`` keys."""
    env = dict(PRODUCTION_PLAY_ENV)
    env.update({"SHENGJI_PV_CKPT": str(checkpoint), "SHENGJI_PV_SHA256": str(sha256)})
    env.update(overrides)
    return env


def bot_from_environ(environ: Mapping[str, str], *, seed: int = 0):
    """``(name, bot)`` built exactly as the server registers the env recipe
    (`pv_env_recipe` -> `pv_registry_entries` -> factory)."""
    from ..train import pv_search_policy as pv
    recipe = pv.pv_env_recipe(environ)
    entries = pv.pv_registry_entries(**recipe)
    (name, factory), = entries.items()
    return name, factory(seed=seed)
