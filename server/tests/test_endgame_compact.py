"""The compact exact solver is the reference solver, bit for bit.

``CompactWorldSession`` (pure-Python and compiled backends) must return what
``ExactWorldSession`` returns for every root of a shared session: the value,
the chosen action, the node and cache-hit counts, and -- when the node cap
binds -- the same refusal with the same consumed work.  Positions come from
fixed seeds: random bounded deals biased towards pairs, tractors and throws
(every trump context, no-trump included, mid-trick roots included), and
heuristic self-play endgames scored through ``exact_lead_means`` exactly as
S18 serves it.  CI runs this module under both engines.
"""

from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai.endgame import (ExactEndgameBudgetExceeded, ExactEndgameRefusal,
                                ExactWorldSession, _clone_for_play,
                                exhaustive_legal_actions)
from shengji.ai.endgame_compact import HAVE_FAST, CompactWorldSession, default_backend
from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import RANKS, SUITS, Ordering, make_deck
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay
from shengji.train import pv_exact_endgame
from shengji.train.cwv_prior_admission import root_clone

BACKENDS = ["python"] + (["compiled"] if HAVE_FAST else [])


def _outcomes(make, roots, check_budget=None):
    """Solve ``roots`` in one session; every observable, in order."""
    session = make(roots[0])
    out = []
    for root in roots:
        try:
            got = session.solve(root)
        except ExactEndgameBudgetExceeded as exc:
            out.append(("cap", str(exc), exc.nodes, exc.cache_hits))
            break
        out.append(("ok", got.attacker_points, got.action, got.nodes, got.cache_hits))
    out.append(("session", session.nodes, session.cache_hits))
    return out


def _session(backend, **kw):
    if backend == "reference":
        return lambda rnd: ExactWorldSession(rnd, **kw)
    return lambda rnd: CompactWorldSession(rnd, backend=backend, **kw)


def _play_round(trump_suit, trump_rank, banker, hands, buried, *, leader,
                attacker_points):
    rnd = Round(trump_rank, banker=banker, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering(trump_suit, trump_rank)
    rnd.trump_suit = trump_suit
    rnd.trump_is_nt = trump_suit is None
    rnd.hands = [list(h) for h in hands]
    rnd.buried = list(buried)
    rnd.attacker_points = attacker_points
    rnd.trick = Trick(leader=leader)
    rnd.turn = leader
    return rnd


def _random_position(rng: random.Random) -> Round:
    """A legal bounded position, dense in pairs, tractors and trump."""
    trump_rank = rng.choice(RANKS)
    trump_suit = rng.choice(list(SUITS) + [None])
    deck = make_deck()
    # a narrow card pool makes pairs, tractors and contested throws common
    suits = rng.sample(SUITS, rng.choice([1, 1, 2]))
    pool = [c for c in deck
            if c in ("LJ", "BJ") or c[0] in suits or c[1:] == trump_rank]
    if trump_suit is not None and rng.random() < 0.5:
        pool += [c for c in deck if c[0] == trump_suit and c not in pool]
    rng.shuffle(pool)
    size = rng.choice([1, 2, 3, 3, 4, 4, 4])
    if len(pool) < 4 * size:
        size = len(pool) // 4
    hands = [sorted(pool[i * size:(i + 1) * size]) for i in range(4)]
    for hand in hands:
        rng.shuffle(hand)            # engine list order is not sorted order
    rest = list(deck)
    for hand in hands:
        for card in hand:
            rest.remove(card)
    buried = rng.sample(rest, 8)
    leader = rng.randrange(4)
    rnd = _play_round(trump_suit, trump_rank, rng.randrange(4), hands, buried,
                      leader=leader, attacker_points=5 * rng.randrange(0, 21))
    # mid-trick roots, reached through the engine
    for _ in range(rng.choice([0, 0, 0, 1, 2, 3])):
        actions = exhaustive_legal_actions(rnd, rnd.turn)
        rnd.play(rnd.turn, list(rng.choice(actions)))
        if rnd.phase != "play" or not rnd.trick.plays:
            break
    return rnd


def _session_roots(rnd: Round) -> list[Round]:
    """The root and every child of its acting seat: candidate leaves that
    share one world session, as in S18."""
    roots = [rnd]
    for action in exhaustive_legal_actions(rnd, rnd.turn):
        child = _clone_for_play(rnd)
        child.play(rnd.turn, list(action))
        if child.phase == "play":
            roots.append(child)
    return roots


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("alpha_beta", [True, False])
def test_random_positions_match_reference(backend, alpha_beta):
    rng = random.Random(20261015 + alpha_beta)
    compared = capped = 0
    for _ in range(60):
        rnd = _random_position(rng)
        if rnd.phase != "play":
            continue
        roots = _session_roots(rnd)
        for max_nodes in (50_000, 40, 7):
            want = _outcomes(_session("reference", alpha_beta=alpha_beta,
                                      max_nodes=max_nodes), roots)
            got = _outcomes(_session(backend, alpha_beta=alpha_beta,
                                     max_nodes=max_nodes), roots)
            assert got == want
            compared += 1
            capped += any(row[0] == "cap" for row in want)
    assert compared >= 150 and capped >= 20   # the cap really binds in this set


def _endgame_lead(seed: int) -> Round | None:
    """Heuristic self-play to the first lead with every hand <= 4 cards."""
    game = Game(random.Random(seed))
    bots = [HeuristicBot() for _ in range(4)]
    rnd = prepare_round(game, bots)
    while rnd.phase == "play":
        if not rnd.trick.plays and max(map(len, rnd.hands)) <= 4:
            return rnd
        rnd.play(rnd.turn, bots[rnd.turn].decide_play(rnd, rnd.turn))
    return None


def _worlds(rnd: Round, seat: int, rng: random.Random, n: int):
    """Determinizations: the other hands (and, for a non-banker, the kitty)
    reshuffled at their real sizes; the acting seat's hand kept."""
    hidden = [c for s in range(4) if s != seat for c in rnd.hands[s]]
    if seat != rnd.banker:
        hidden += list(rnd.buried)
    worlds = []
    for _ in range(n):
        cards = list(hidden)
        rng.shuffle(cards)
        hands, at = [], 0
        for s in range(4):
            if s == seat:
                hands.append(list(rnd.hands[s]))
            else:
                k = len(rnd.hands[s])
                hands.append(cards[at:at + k])
                at += k
        buried = cards[at:] if seat != rnd.banker else list(rnd.buried)
        worlds.append((hands, buried))
    return worlds


def _heuristic_leaf(root, seat, hands, buried, action, world_index):
    """S18's shape of leaf: the candidate lead, then heuristic follows."""
    clone = root_clone(root, hands, buried)
    clone._trusted_rollout = False
    clone.play(seat, list(action))
    bot = HeuristicBot()
    while clone.phase == "play" and clone.trick.plays:
        clone.play(clone.turn, bot.decide_play(clone, clone.turn))
    return clone


def _lead_means(monkeypatch, session_factory, rnd, seat, actions, worlds, max_nodes):
    monkeypatch.setattr(pv_exact_endgame, "CompactWorldSession", session_factory)
    try:
        means, stats = pv_exact_endgame.exact_lead_means(
            rnd, seat, actions, worlds, _heuristic_leaf, None, max_nodes=max_nodes)
    except ExactEndgameBudgetExceeded as exc:
        return ("cap", str(exc), exc.nodes, exc.cache_hits)
    return ("ok", means.tolist(), stats, int(np.argmax(means)))


@pytest.mark.parametrize("backend", BACKENDS)
def test_selfplay_lead_stage_matches_reference(monkeypatch, backend):
    """``exact_lead_means`` -- per-candidate means, work counters, the argmax
    lead, and node-cap refusals -- is unchanged by the compact session."""
    assert pv_exact_endgame.CompactWorldSession is CompactWorldSession
    rng = random.Random(5300000)
    decisions = capped = 0
    for seed in range(5300000, 5300024):
        rnd = _endgame_lead(seed)
        if rnd is None:
            continue
        seat = rnd.turn
        actions = exhaustive_legal_actions(rnd, seat)[:8]
        worlds = _worlds(rnd, seat, rng, 8)
        for max_nodes in (10_000, 25):
            want = _lead_means(
                monkeypatch, lambda r, **kw: ExactWorldSession(r, **kw),
                rnd, seat, actions, worlds, max_nodes)
            got = _lead_means(
                monkeypatch,
                lambda r, **kw: CompactWorldSession(r, backend=backend, **kw),
                rnd, seat, actions, worlds, max_nodes)
            assert got == want
            decisions += 1
            capped += want[0] == "cap"
    assert decisions >= 40 and capped >= 5


@pytest.mark.parametrize("backend", BACKENDS)
def test_check_budget_cadence_and_cancellation(backend):
    rnd = None
    rng = random.Random(7)
    while rnd is None or rnd.phase != "play" or max(map(len, rnd.hands)) < 3:
        rnd = _random_position(rng)
    roots = _session_roots(rnd)
    calls = {"reference": 0, backend: 0}

    def counter(name):
        def check():
            calls[name] += 1
        return check
    want = _outcomes(lambda r: ExactWorldSession(
        r, alpha_beta=True, check_budget=counter("reference")), roots)
    got = _outcomes(lambda r: CompactWorldSession(
        r, alpha_beta=True, backend=backend,
        check_budget=counter(backend)), roots)
    assert got == want
    if backend == "python":
        assert calls[backend] == calls["reference"]
    else:
        # every root, plus one search call in every 256
        assert len(roots) <= calls[backend] <= calls["reference"]

    class Cancelled(Exception):
        pass

    def cancel():
        raise Cancelled

    with pytest.raises(Cancelled):
        CompactWorldSession(rnd, backend=backend, check_budget=cancel).solve(rnd)


@pytest.mark.parametrize("backend", BACKENDS)
def test_refusals_match_reference(backend):
    too_large = _play_round("H", "7", 0, [["C2"] * 5] * 4, [], leader=0,
                            attacker_points=0)
    with pytest.raises(ExactEndgameRefusal, match="completeness cap"):
        CompactWorldSession(too_large, backend=backend).solve(too_large)
    first = _play_round("H", "7", 0, [["C3"], ["C4"], ["C5"], ["CA"]], ["H5"],
                        leader=0, attacker_points=7)
    other_kitty = _play_round("H", "7", 0, [["C3"], ["C4"], ["C5"], ["CA"]], ["C2"],
                              leader=0, attacker_points=7)
    session = CompactWorldSession(first, backend=backend)
    assert session.solve(first).attacker_points == 22
    with pytest.raises(ExactEndgameRefusal, match="context differs"):
        session.solve(other_kitty)


@pytest.mark.parametrize("backend", BACKENDS)
def test_out_of_capacity_root_replays_onto_python_identically(backend):
    """Four copies of one code in a seat (impossible from a real deal) exceed
    the compiled masks: the session replays onto the Python backend and every
    observable still matches the reference."""
    hands = [["C3", "C4"], ["C5", "C6"], ["C8", "C9"], ["CA", "C10"]]
    normal = _play_round("H", "7", 0, hands, ["H5"], leader=0, attacker_points=0)
    odd = _play_round("H", "7", 0, [["C6"] * 4, ["C8"] * 4, ["C9"] * 4,
                                    ["C3", "C4", "D5", "D5"]], ["H5"],
                      leader=3, attacker_points=10)
    roots = _session_roots(normal) + [odd] + _session_roots(normal)
    want = _outcomes(_session("reference", alpha_beta=True), roots)
    got = _outcomes(_session(backend, alpha_beta=True), roots)
    assert got == want


def test_default_backend_follows_the_engine():
    from shengji.engine import fast
    expected = "compiled" if HAVE_FAST and fast._saved else "python"
    assert default_backend() == expected
    with pytest.raises(ValueError, match="unknown exact backend"):
        CompactWorldSession(_play_round("H", "7", 0, [["C3"]] * 4, [], leader=0,
                                        attacker_points=0), backend="other")


def test_root_round_is_not_mutated():
    rng = random.Random(11)
    rnd = _random_position(rng)
    while rnd.phase != "play":
        rnd = _random_position(rng)
    before = copy.deepcopy((rnd.hands, rnd.buried, rnd.attacker_points, rnd.turn,
                            [(p.seat, p.cards) for p in rnd.trick.plays]))
    for backend in BACKENDS:
        CompactWorldSession(rnd, backend=backend).solve(rnd)
    assert before == (rnd.hands, rnd.buried, rnd.attacker_points, rnd.turn,
                      [(p.seat, p.cards) for p in rnd.trick.plays])


def test_mid_trick_root_plays_are_kept_in_engine_order():
    """A root trick whose plays are TrickPlay lists (not tuples) solves."""
    rnd = _play_round(None, "2", 1, [["SA", "SK"], ["S3", "S4"], ["H5", "H6"],
                                     ["S10", "S9"]], ["H2"],
                      leader=0, attacker_points=0)
    rnd.play(0, ["SA"])
    for backend in BACKENDS:
        assert (CompactWorldSession(rnd, backend=backend).solve(rnd)
                == ExactWorldSession(rnd).solve(rnd))
    assert isinstance(rnd.trick.plays[0], TrickPlay)


@pytest.mark.skipif(not HAVE_FAST, reason="compiled exact solver not built")
@pytest.mark.parametrize("ending", ["complete", "cancelled", "node_cap"])
def test_compiled_tables_live_exactly_as_long_as_the_decision(ending):
    """The compiled rule tables are shared by every world of one decision (one
    ``Ordering``) and are freed with it -- on success, on cancellation and on a
    node-cap refusal.  A table that owned its weak key leaked every decision."""
    import gc
    import weakref

    from shengji.ai import _endgame_fast

    class Cancelled(Exception):
        pass

    gc.collect()
    baseline = len(_endgame_fast._TABLES)
    orderings, tables = [], []
    hands = [["C3", "C4", "D5", "D5"], ["C6", "C8", "D9", "DK"],
             ["C9", "CA", "D3", "D10"], ["C10", "CK", "DA", "D7"]]
    for decision in range(4):
        rnd = _play_round("H", "7", decision % 4, hands, ["H5", "D10"],
                          leader=decision % 4, attacker_points=0)
        roots = _session_roots(rnd)
        calls = [0]

        def check():
            calls[0] += 1
            if ending == "cancelled" and calls[0] > 3:
                raise Cancelled

        records = []
        for _world in range(2):     # two worlds of one decision share the root Ordering
            world = root_clone(rnd, rnd.hands, rnd.buried)
            assert world.ordering is rnd.ordering
            session = CompactWorldSession(
                world, alpha_beta=True, backend="compiled", check_budget=check,
                max_nodes=1 if ending == "node_cap" else 250_000)
            try:
                for root in roots:
                    session.solve(root)
            except (Cancelled, ExactEndgameBudgetExceeded):
                assert ending != "complete"
            else:
                assert ending == "complete"
            records.append(_endgame_fast._TABLES[rnd.ordering].records)
            del session, world
        table = _endgame_fast._TABLES[rnd.ordering]
        if ending == "complete":
            assert records[1] == records[0] > 0   # the second world rebuilt nothing
        orderings.append(weakref.ref(rnd.ordering))
        tables.append(weakref.ref(table))
        del rnd, roots, root, table, check
    gc.collect()
    assert [r() for r in orderings] == [None] * 4
    assert [t() for t in tables] == [None] * 4
    assert len(_endgame_fast._TABLES) == baseline
