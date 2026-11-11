#!/usr/bin/env python3
"""Fixtures that hold the TypeScript offline engine to the Python engine.

The TypeScript engine under ``web/src/offline/engine/`` is a port of
``shengji/engine``; its vitest suite replays these fixtures and asserts every
recorded verdict and outcome.  Two files are written to ``--out``:

``rounds.jsonl.gz``
    A header line, then one line per round.  Games are played with SmartBot or
    HeuristicBot at every seat through the same deal/declare/bury/play loop as
    ``shengji.ai.env.play_round``.  A round records its deck (the TS side never
    replicates Python's ``random``), every declaration with the deal position
    it followed, declare options and probes, the final trump and banker, the
    bury, the hands after the bury, every play (attempted cards and, for a
    failed throw, the forced cards and message), trick winners and points,
    the kitty bonus and the game's round result.  At every decision a few
    probe plays are validated against the live state and their outcome is
    recorded (accepted, accepted-with-forced-component, or the exact
    ``IllegalPlay`` message).  At a few sampled decisions every candidate play
    is enumerated in a canonical order and one verdict character per candidate
    is recorded.

``primitives.json.gz``
    The randomized and edge-case inputs of ``tests/test_fast_parity.py``
    (decompose, tractor runs, beats, decompose_matching, validate_follow,
    validate_lead and helpers) with the pure engine's outputs.

Everything is a deterministic function of ``--rounds`` and ``--seed``: probe
choices draw from their own ``random.Random`` and validate on their own
``Ordering``, so probing never feeds back into the game.

Usage::

    python scripts/gen_offline_engine_fixtures.py --rounds 300 \\
        --out ../web/src/offline/fixtures
    python scripts/gen_offline_engine_fixtures.py --rounds 10000 --out /tmp/x
"""

from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from shengji.engine import combos, legal  # noqa: E402
from shengji.engine.cards import TRUMP, Ordering, make_deck  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.engine.legal import IllegalPlay  # noqa: E402

FORMAT = 1
SUIT_ORDER = ("S", "H", "C", "D", TRUMP)
ENUM_CAP = 3000          # candidates per enumerated decision
ENUM_PER_ROUND = 5       # decisions per round sampled for full enumeration
NO_DECLARE_SHARE = 0.1  # rounds whose bots never declare
MAX_ROUNDS_PER_GAME = 40  # a games_to_win=None table never ends by itself
GAME_CONFIGS = [  # (bot, start_level, games_to_win), cycled per game
    ("smart", "2", 1),
    ("smart", "10", None),
    ("heuristic", "Q", 2),
    ("smart", "A", 1),
    ("heuristic", "2", 1),
    ("smart", "K", None),
]

# One character per candidate verdict.  Every enumerated candidate is drawn
# from the hand, so "You don't hold those cards." never occurs there.
FOLLOW_CODES = {
    None: ".",
    "You must follow suit.": "s",
    "You must play pairs from the led suit.": "p",
    "You must play all your cards of the led suit.": "a",
}


def _follow_code(msg):
    if msg in FOLLOW_CODES:
        return FOLLOW_CODES[msg]
    if msg.startswith("Must play exactly"):
        return "c"
    if msg.startswith("You must follow with a tractor"):
        return "t"
    raise RuntimeError(f"unexpected follow verdict: {msg!r}")


# ------------------------------------------------------------- enumeration
# The TypeScript engine enumerates candidates in exactly this order
# (``web/src/offline/engine/legal.ts``): distinct codes in string order, and
# for each code the number of copies taken ascending, depth first.

def _distinct(cards):
    cnt = Counter(cards)
    codes = sorted(cnt)
    return codes, [cnt[c] for c in codes]


def count_submultisets(cards, n):
    codes, counts = _distinct(cards)
    ways = [1] + [0] * n
    for k in counts:
        nxt = [0] * (n + 1)
        for total in range(n + 1):
            if ways[total]:
                for t in range(min(k, n - total) + 1):
                    nxt[total + t] += ways[total]
        ways = nxt
    return ways[n]


def submultisets(cards, n):
    codes, counts = _distinct(cards)
    out = []
    cur = []

    def rec(i, left):
        if left == 0:
            out.append(list(cur))
            return
        if i == len(codes):
            return
        for t in range(min(counts[i], left) + 1):
            cur.extend([codes[i]] * t)
            rec(i + 1, left - t)
            if t:
                del cur[-t:]

    rec(0, n)
    return out


def lead_groups(hand, o):
    groups = []
    for eff in SUIT_ORDER:
        g = [c for c in hand if o.eff_suit(c) == eff]
        if g:
            groups.append(g)
    return groups


def count_lead_candidates(hand, o):
    return sum(count_submultisets(g, n) for g in lead_groups(hand, o)
               for n in range(1, len(g) + 1))


def lead_candidates(hand, o):
    out = []
    for g in lead_groups(hand, o):
        for n in range(1, len(g) + 1):
            out.extend(submultisets(g, n))
    return out


# ------------------------------------------------------------------ probes

def _outcome_lead(play, hand, others, o):
    try:
        actual, msg = legal.validate_lead(list(play), list(hand),
                                          [list(h) for h in others], o)
    except IllegalPlay as e:
        return {"err": str(e)}
    if msg is not None:
        return {"forced": list(actual), "msg": msg}
    return {}


def _outcome_follow(play, hand, lead, o):
    try:
        legal.validate_follow(list(play), list(hand), list(lead), o)
    except IllegalPlay as e:
        return {"err": str(e)}
    return {}


def _not_held(rng, hand):
    held = Counter(hand)
    pool = [c for c in sorted(set(make_deck())) if held[c] < 2]
    return rng.choice(pool)


def lead_probes(rng, hand, o):
    probes = []
    groups = lead_groups(hand, o)
    g = rng.choice(groups)
    probes.append(rng.sample(g, rng.randint(1, len(g))))
    if len(g) > 1:
        probes.append(list(g))
    if len(groups) > 1:
        a, b = rng.sample(groups, 2)
        probes.append([rng.choice(a), rng.choice(b)])
    r = rng.random()
    if r < 0.1:
        probes.append([])
    elif r < 0.25:
        probes.append([_not_held(rng, hand)])
    return probes


def follow_probes(rng, hand, lead, o):
    n = len(lead)
    eff = o.eff_suit(lead[0])
    probes = []
    if len(hand) >= n:
        probes.append(rng.sample(hand, n))
    in_suit = [c for c in hand if o.eff_suit(c) == eff]
    if len(in_suit) >= n:
        probes.append(rng.sample(in_suit, n))
    if n > 1 and len(in_suit) >= n - 1:
        off = [c for c in hand if o.eff_suit(c) != eff]
        if off:
            probes.append(rng.sample(in_suit, n - 1) + [rng.choice(off)])
    m = n + rng.choice((-1, 1))
    if 1 <= m <= len(hand):
        probes.append(rng.sample(hand, m))
    if rng.random() < 0.15:
        probes.append(rng.sample(hand, n - 1) + [_not_held(rng, hand)]
                      if n <= len(hand) else [_not_held(rng, hand)])
    return probes


# ------------------------------------------------------------------- rounds

def _make_bots(kind):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.ai.smart import SmartBot
    cls = SmartBot if kind == "smart" else HeuristicBot
    return [cls() for _ in range(4)]


class Stats(Counter):
    pass


def play_recorded_round(game, bots, prng, stats):
    """One round driven like env.play_round, recorded for the TS replay."""
    rec = {
        "levels": list(game.levels),
        "banker": game.banker,
        "gamesWon": list(game.games_won),
    }
    rnd = game.start_round()
    rec["trumpRank"] = rnd.trump_rank
    rec["deck"] = list(rnd.deck)
    # One ordered event list: a declaration changes what later checks see.
    events = []
    # Some rounds nobody declares, so trump is flipped from the kitty.
    silent = prng.random() < NO_DECLARE_SHARE
    rec["silent"] = silent

    def check_options(seat):
        events.append([rnd._deal_pos, seat, "opts",
                       rnd.declare_options(seat)])
        stats["declare_checks"] += 1

    def probe_declare(seat):
        hand = rnd.hands[seat]
        cands = [[c] for c in hand] + [[c, c] for c in sorted(set(hand))]
        cands.append(["BJ", "BJ"])
        cards = sorted(prng.choice(cands))
        try:
            copy.deepcopy(rnd).declare(seat, list(cards))
            verdict = None
        except IllegalPlay as e:
            verdict = str(e)
        events.append([rnd._deal_pos, seat, "try", cards, verdict])
        stats["declare_checks"] += 1

    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        if prng.random() < 0.05:
            probe_declare(prng.randrange(4))
        cards = None if silent else bots[seat].decide_declare(rnd, seat)
        if cards:
            check_options(seat)
            rnd.declare(seat, cards)
            events.append([rnd._deal_pos, seat, "declare", list(cards)])
            stats["declares"] += 1
    for seat in range(4):
        check_options(seat)
    for seat in range(4):
        cards = None if silent else bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            check_options(seat)
            rnd.declare(seat, cards)
            events.append([rnd._deal_pos, seat, "declare", list(cards)])
            stats["declares"] += 1
    rec["declareEvents"] = events
    rnd.finalize_declare()
    rec["trump"] = {"suit": rnd.trump_suit, "nt": rnd.trump_is_nt,
                    "banker": rnd.banker}
    bury = list(bots[rnd.banker].decide_bury(rnd, rnd.banker))
    rnd.bury(rnd.banker, bury)
    rec["bury"] = bury
    rec["handsAfterBury"] = [list(h) for h in rnd.hands]

    probe_o = Ordering(rnd.trump_suit, rnd.trump_rank)
    enum_at = set(prng.sample(range(100), ENUM_PER_ROUND))
    plays, probes, enums, tricks = [], [], [], []
    idx = 0
    while rnd.phase == "play":
        seat = rnd.turn
        hand = list(rnd.hands[seat])
        leading = not rnd.trick.plays
        if leading:
            others = [list(rnd.hands[s]) for s in range(4) if s != seat]
            for p in lead_probes(prng, hand, probe_o):
                out = _outcome_lead(p, hand, others, probe_o)
                probes.append([idx, p, out])
                stats["legality_checks"] += 1
                stats["illegal_attempts"] += "err" in out
                stats["failed_throws"] += "forced" in out
            if idx in enum_at:
                n_c = count_lead_candidates(hand, probe_o)
                if n_c <= ENUM_CAP:
                    verdict, forced = [], []
                    for i, cand in enumerate(lead_candidates(hand, probe_o)):
                        out = _outcome_lead(cand, hand, others, probe_o)
                        if "err" in out:
                            raise RuntimeError(f"lead candidate raised: {cand} {out}")
                        if "forced" in out:
                            verdict.append("f")
                            forced.append([i, out["forced"]])
                        else:
                            verdict.append(".")
                    enums.append([idx, "lead", n_c, "".join(verdict), forced])
                    stats["enumerated_decisions"] += 1
                    stats["legality_checks"] += n_c
                    stats["failed_throws"] += len(forced)
                else:
                    enums.append([idx, "lead", n_c, None, None])
                    stats["enum_skipped"] += 1
        else:
            lead = list(rnd.trick.plays[0].cards)
            for p in follow_probes(prng, hand, lead, probe_o):
                out = _outcome_follow(p, hand, lead, probe_o)
                probes.append([idx, p, out])
                stats["legality_checks"] += 1
                stats["illegal_attempts"] += "err" in out
            if idx in enum_at:
                n = len(lead)
                n_c = count_submultisets(hand, n)
                if n_c <= ENUM_CAP:
                    verdict = []
                    for cand in submultisets(hand, n):
                        out = _outcome_follow(cand, hand, lead, probe_o)
                        verdict.append(_follow_code(out.get("err")))
                    v = "".join(verdict)
                    enums.append([idx, "follow", n_c, v, None])
                    stats["enumerated_decisions"] += 1
                    stats["legality_checks"] += n_c
                    stats["illegal_attempts"] += n_c - v.count(".")
                else:
                    enums.append([idx, "follow", n_c, None, None])
                    stats["enum_skipped"] += 1

        attempted = list(bots[seat].decide_play(rnd, seat))
        trick_before = rnd.trick
        rnd.play(seat, attempted)
        played = trick_before.plays[-1].cards
        entry = [seat, attempted]
        if played != attempted:
            entry += [list(played), rnd.message]
            stats["failed_throws"] += 1
            stats["bot_failed_throws"] += 1
        plays.append(entry)
        stats["plays"] += 1
        stats["legality_checks"] += 1
        if trick_before.winner is not None:
            tricks.append([trick_before.leader, trick_before.winner,
                           trick_before.points])
            stats["tricks"] += 1
        idx += 1

    rec["plays"] = plays
    rec["probes"] = probes
    rec["enums"] = enums
    rec["tricks"] = tricks
    rec["end"] = {"attackerPoints": rnd.attacker_points,
                  "kittyBonus": rnd.kitty_bonus,
                  "lastTrickWinner": rnd.last_trick_winner}
    res = game.finish_round()
    rec["result"] = {
        "attackerPoints": res.attacker_points,
        "kittyPoints": res.kitty_points,
        "kittyCards": list(res.kitty_cards),
        "winnerTeam": res.winner_team,
        "levelChange": res.level_change,
        "nextBanker": res.next_banker,
        "newLevels": list(res.new_levels),
        "gameOver": res.game_over,
        "gamesWon": list(res.games_won),
        "pointScored": res.point_scored,
    }
    stats["rounds"] += 1
    return rec


def iter_rounds(n_rounds, seed, stats):
    produced = 0
    g = 0
    while produced < n_rounds:
        bot_kind, start, to_win = GAME_CONFIGS[g % len(GAME_CONFIGS)]
        game = Game(random.Random(seed * 1_000_003 + g), start_level=start,
                    games_to_win=to_win)
        bots = _make_bots(bot_kind)
        prng = random.Random(f"probe:{seed}:{g}")
        r = 0
        while not game.game_over and r < MAX_ROUNDS_PER_GAME and produced < n_rounds:
            rec = play_recorded_round(game, bots, prng, stats)
            head = {"game": g, "round": r}
            if r == 0:
                head["config"] = {"bot": bot_kind, "startLevel": start,
                                  "gamesToWin": to_win}
                stats["games"] += 1
            yield {**head, **rec}
            produced += 1
            r += 1
        g += 1


def _dumps(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _gzip_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9,
                       filename="") as f:
        f.write(text.encode("utf-8"))
    return buf.getvalue()


def rounds_text(n_rounds, seed, stats=None):
    stats = Stats() if stats is None else stats
    lines = [_dumps(r) for r in iter_rounds(n_rounds, seed, stats)]
    header = {"format": FORMAT, "rounds": n_rounds, "seed": seed,
              "enumCap": ENUM_CAP, "stats": dict(sorted(stats.items()))}
    return "\n".join([_dumps(header)] + lines) + "\n"


# --------------------------------------------------------------- primitives
# Inputs reproduce tests/test_fast_parity.py's generators (same seeds and
# draws); outputs are the pure reference functions.

CONFIGS = [("H", "7"), ("S", "2"), ("D", "A"), (None, "7"), (None, "A"),
           ("C", "10")]


def _comp(c):
    return [c.kind, list(c.cards), c.top, c.pair_len]


def _dec(d):
    return None if d is None else [_comp(c) for c in d.components]


def _suit_groups(cards, o):
    groups = {}
    for c in cards:
        groups.setdefault(o.eff_suit(c), []).append(c)
    return groups


def _random_lead(rng, group):
    r = rng.random()
    if r < 0.45:
        o = Ordering("H", "7")
        comps = combos.decompose(list(group), o).components
        return list(rng.choice(comps).cards)
    if r < 0.8:
        n = rng.randint(1, len(group))
        return rng.sample(group, n)
    return list(group)


def _vf(play, hand, lead, o):
    try:
        legal.validate_follow(list(play), list(hand), list(lead), o)
        return None
    except IllegalPlay as e:
        return str(e)
    except AssertionError:
        return "AssertionError"


def _cih(hand, play):
    try:
        legal.check_in_hand(list(hand), list(play))
        return None
    except IllegalPlay as e:
        return str(e)


def primitives():
    out = {"decompose": [], "beats": [], "matching": [], "follow": [],
           "lead": []}
    deck = make_deck()

    def group_case(cards, cfg):
        o = Ordering(*cfg)
        runs = [combos._find_tractor_runs_uncached(list(cards), o, k)
                for k in range(1, 7)]
        out["decompose"].append([list(cfg), list(cards),
                                 _dec(combos._decompose_uncached(list(cards), o)),
                                 runs])

    # test_random_hand_parity
    rng = random.Random(42)
    for i in range(2000):
        cfg = CONFIGS[i % len(CONFIGS)]
        o = Ordering(*cfg)
        hand = rng.sample(deck, rng.randint(1, 25))
        for cards in _suit_groups(hand, o).values():
            group_case(cards, cfg)
    # test_edge_cases (one permutation each is enough: the result is a
    # function of the multiset, which the TS side must also honour)
    import itertools
    edge = [
        ["BJ", "BJ"], ["LJ", "LJ", "BJ", "BJ"], ["H7", "H7", "LJ", "LJ"],
        ["S7", "S7", "D7", "D7", "C7", "C7"],
        ["S7", "D7", "S7", "D7", "H7", "H7"],
        ["HA", "HA", "S7", "S7", "H7", "H7", "LJ", "LJ"],
        ["H2", "H2", "H3", "H3", "H4", "H4", "H5", "H5", "H6", "H6", "H8", "H8"],
        ["S3", "S3", "S4", "S4", "S5", "S5"],
        ["S3", "S4", "S3", "S4", "S5", "S6", "S5"],
    ]
    for cards in edge:
        for perm in itertools.islice(itertools.permutations(cards), 6):
            group_case(list(perm), ("H", "7"))
    for cards in ([("%s7" % s) for s in "SHDC" for _ in (0, 1)],
                  ["S7", "S7", "H7", "H7", "LJ", "LJ", "BJ", "BJ"]):
        for perm in itertools.islice(itertools.permutations(cards), 6):
            group_case(list(perm), (None, "7"))

    # test_beats_and_decompose_matching_random_parity
    rng = random.Random(20260803)
    n_beats = n_match = 0
    while n_beats < 10_000 or n_match < 10_000:
        cfg = CONFIGS[rng.randrange(len(CONFIGS))]
        op = Ordering(*cfg)
        hand = rng.sample(deck, rng.randint(4, 25))
        groups = list(_suit_groups(hand, op).values())
        lead_group = rng.choice(groups)
        lead = _random_lead(rng, lead_group)
        shape = combos._decompose_uncached(lead, op).shape()
        inc_suit = legal.uniform_suit(lead, op)
        inc_top = (combos._decompose_uncached(lead, op).top_level()
                   if rng.random() < 0.7 else rng.randrange(16))
        challengers = [rng.sample(deck, len(lead))]
        other = rng.sample(deck, rng.randint(len(lead), 30))
        for g in _suit_groups(other, op).values():
            if len(g) >= len(lead):
                challengers.append(rng.sample(g, len(lead)))
        for ch in challengers:
            won, top = legal.beats(ch, lead, inc_suit, inc_top, op)
            out["beats"].append([list(cfg), ch, lead, inc_suit, inc_top,
                                 won, top])
            n_beats += 1
            out["matching"].append([list(cfg), ch, [list(shape[0]), shape[1]],
                                    _dec(combos.decompose_matching(ch, op, shape))])
            n_match += 1
        rand_shape = (tuple(sorted((rng.randint(1, 3)
                                    for _ in range(rng.randint(0, 2))),
                            reverse=True)), rng.randint(0, 4))
        out["matching"].append([list(cfg), list(lead_group),
                                [list(rand_shape[0]), rand_shape[1]],
                                _dec(combos.decompose_matching(lead_group, op,
                                                               rand_shape))])
        n_match += 1

    # test_beats_equal_level_trump_rank_edges
    pool_h7 = ["HA", "HA", "S7", "S7", "D7", "D7", "C7", "C7", "H7", "H7",
               "LJ", "LJ", "BJ", "BJ"]
    pool_nt = ["S7", "S7", "H7", "H7", "D7", "D7", "C7", "C7", "LJ", "LJ",
               "BJ", "BJ"]
    rng = random.Random(99)
    for cfg, pool in ((("H", "7"), pool_h7), ((None, "7"), pool_nt)):
        for _ in range(400):
            op = Ordering(*cfg)
            lead = rng.sample(pool, 2 * rng.randint(1, 4))
            ch = rng.sample(pool, len(lead))
            shape = combos._decompose_uncached(lead, op).shape()
            top = combos._decompose_uncached(lead, op).top_level()
            for inc in ("T", "H", "S"):
                won, t = legal.beats(ch, lead, inc, top, op)
                out["beats"].append([list(cfg), ch, lead, inc, top, won, t])
            out["matching"].append([list(cfg), ch, [list(shape[0]), shape[1]],
                                    _dec(combos.decompose_matching(ch, op, shape))])

    # test_single_follow_keeps_all_validation_failures
    single = [
        (["H8"], ["H8", "C3"], ["H7"]), (["C3"], ["H8", "C3"], ["H7"]),
        (["C3"], ["C3", "D4"], ["H7"]), (["BJ"], ["BJ", "S2"], ["SJ"]),
        (["H8"], ["C3"], ["H7"]), ([], ["H8"], ["H7"]),
        (["H8", "H8"], ["H8", "H8"], ["H7"]), (["H8"], ["H8", "H8"], ["H7", "H7"]),
    ]
    for cfg in CONFIGS:
        for play, hand, lead in single:
            o = Ordering(*cfg)
            out["follow"].append([list(cfg), play, hand, lead,
                                  _vf(play, hand, lead, o), _cih(hand, play),
                                  legal.uniform_suit(play, o) if play else None,
                                  combos.pair_count(play)])

    # test_validate_follow_and_helpers_random_parity
    rng = random.Random(777)
    for i in range(4000):
        cfg = CONFIGS[i % len(CONFIGS)]
        op = Ordering(*cfg)
        hand = rng.sample(deck, rng.randint(2, 20))
        lead_hand = rng.sample(deck, rng.randint(1, 12))
        lead_group = rng.choice(list(_suit_groups(lead_hand, op).values()))
        lead = _random_lead(rng, lead_group)
        if rng.random() < 0.1:
            lead = rng.sample(deck, rng.randint(2, 4))
        plays = []
        if len(hand) >= len(lead):
            plays.append(rng.sample(hand, len(lead)))
        in_suit = [c for c in hand if op.eff_suit(c) == op.eff_suit(lead[0])]
        if len(in_suit) >= len(lead):
            plays.append(rng.sample(in_suit, len(lead)))
        plays.append(rng.sample(hand, rng.randint(1, len(hand))))
        plays.append(rng.sample(deck, len(lead)))
        if rng.random() < 0.05:
            plays.append([])
        for play in plays:
            out["follow"].append([list(cfg), play, hand, lead,
                                  _vf(play, hand, lead, op), _cih(hand, play),
                                  legal.uniform_suit(play, op) if play else None,
                                  combos.pair_count(play)])

    # test_validate_lead_throw_penalty_parity
    rng = random.Random(24)
    deck2 = make_deck()

    def lead_case(play, hand, others, cfg):
        o = Ordering(*cfg)
        out["lead"].append([list(cfg), list(play), list(hand),
                            [list(h) for h in others],
                            _outcome_lead(play, hand, others, o)])

    for i in range(400):
        cfg = CONFIGS[i % len(CONFIGS)]
        o0 = Ordering(*cfg)
        eff = ("S", "H", "D", "C", TRUMP)[i % 5]
        pool = [c for c in deck2 if o0.eff_suit(c) == eff]
        codes = sorted(sorted(set(pool)), key=o0.level)  # set order is hash-randomized
        if len(codes) < 6:
            continue
        lo, hi = codes[:len(codes) // 2], codes[len(codes) // 2:]
        picks = rng.sample(lo, rng.randint(2, min(4, len(lo))))
        play = [c for c in picks for _ in (0, 1)]
        if rng.random() < 0.7:
            play.append(rng.choice(hi[:max(1, len(hi) - 1)]))
        rng.shuffle(play)
        off = [c for c in deck2 if o0.eff_suit(c) != eff]
        hand = list(play) + rng.sample(off, 5)
        beaters = rng.sample(hi, min(len(hi), rng.randint(1, 4)))
        others = [[c for c in beaters for _ in (0, 1)], rng.sample(off, 4),
                  rng.sample(pool, min(4, len(pool)))]
        lead_case(play, hand, others, cfg)
    for i in range(200):
        cfg = CONFIGS[i % len(CONFIGS)]
        o0 = Ordering(*cfg)
        rng.shuffle(deck2)
        hands = [deck2[s * 25:(s + 1) * 25] for s in range(4)]
        hand, others = hands[0], hands[1:]
        groups = {}
        for c in hand:
            groups.setdefault(o0.eff_suit(c), []).append(c)
        g = rng.choice(list(groups.values()))
        for play in (list(g), rng.sample(g, rng.randint(1, len(g)))):
            lead_case(play, hand, others, cfg)
    return out


def primitives_text():
    return _dumps({"format": FORMAT, **primitives()}) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rounds", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    if os.environ.get("SHENGJI_RULES_PROFILE"):
        ap.error("SHENGJI_RULES_PROFILE must be unset: fixtures are our rules")
    args.out.mkdir(parents=True, exist_ok=True)
    stats = Stats()
    text = rounds_text(args.rounds, args.seed, stats)
    (args.out / "rounds.jsonl.gz").write_bytes(_gzip_bytes(text))
    (args.out / "primitives.json.gz").write_bytes(_gzip_bytes(primitives_text()))
    print(_dumps({"out": str(args.out), **dict(sorted(stats.items()))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
