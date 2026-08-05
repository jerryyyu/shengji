"""Correctness invariants + regression tests from the 2026-08-02 A/A audit.

Three layers:
1. Regression tests for the audit's confirmed bugs (cache-key/order
   mismatch in the combos memos, throw-penalty cache aliasing).
2. Property tests over full seeded rounds: card conservation at every
   step, points conservation, kitty accounting, bot-output legality,
   beats() antisymmetry, cache integrity after real games.
3. Blind-spot coverage: throw penalties firing, defend-at-A endgame,
   trump-rank edge cases, shard round-trip, cross-process determinism of
   RL action enumeration.
"""

import os
import random
import subprocess
import sys
import types
from collections import Counter

import pytest

sys.path.insert(0, ".")
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine import combos  # noqa: E402
from shengji.engine.cards import Ordering, make_deck, total_points  # noqa: E402
from shengji.engine.game import A_INDEX, Game  # noqa: E402
from shengji.engine.legal import beats, uniform_suit, validate_follow, validate_lead  # noqa: E402

DECK_POINTS = 200  # 8x5 + 8x10 + 8xK per two decks


# ---------------------------------------------------------------------------
# 1. Regressions: memo caches must equal the reference FOR THE CALLER'S INPUT
# ---------------------------------------------------------------------------

def test_decompose_cache_exact_order_contract():
    """S7/D7 share a level under H-trump rank 7: the greedy decomposition is
    input-order dependent, so a sorted cache key let the first caller's order
    poison later calls (cached != reference). Fails before the exact-order
    key fix."""
    o = Ordering("H", "7")
    c1 = ["S7", "S7", "D7", "D7"]
    c2 = ["D7", "D7", "S7", "S7"]
    combos.decompose(c2, o)  # prime the cache with the other order
    assert combos.decompose(c1, o) == combos._decompose_uncached(c1, o)
    assert combos.decompose(c2, o) == combos._decompose_uncached(c2, o)


def test_find_tractor_runs_cache_exact_order_contract():
    o = Ordering("H", "7")
    t1 = ["HA", "HA", "S7", "S7", "D7", "D7"]
    t2 = ["HA", "HA", "D7", "D7", "S7", "S7"]
    combos.find_tractor_runs(t2, o, 2)  # prime with the other order
    assert (combos.find_tractor_runs(t1, o, 2)
            == combos._find_tractor_runs_uncached(t1, o, 2))
    assert (tuple(t1), 2) in o._trcache
    assert (tuple(t2), 2) in o._trcache


def test_throw_penalty_fires_and_returns_fresh_list():
    """A beatable throw is forced down to the beaten component — and the
    returned play must be a COPY, not an alias into the decompose cache
    (mutating it must not change later identical calls)."""
    o = Ordering("S", "2")
    hand = ["H3", "H5", "H5", "S3", "S4"]
    play = ["H3", "H5", "H5"]
    others = [["H6", "H6", "D3"], ["C4"], ["C5"]]
    forced, msg = validate_lead(play, hand, others, o)
    assert sorted(forced) == ["H3"]  # rule 2026-08-03: LOWEST beatable part (both were beatable; single < pair)
    assert msg and "Throw failed" in msg
    forced[0] = "XX"  # caller mutates its play in place
    forced2, _ = validate_lead(play, hand, others, o)
    assert sorted(forced2) == ["H3"], "penalty list aliased the cache"
    # an unbeatable throw stands
    ok, msg2 = validate_lead(["HA", "HK", "HK"], ["HA", "HK", "HK", "S3"],
                             [["H6", "H7"], ["C4"], ["C5"]], o)
    assert sorted(ok) == ["HA", "HK", "HK"] and msg2 is None


def test_ordering_tables_deterministic_order():
    """Per-card tables must be built in sorted order so no future iteration
    over them can be hash-randomized (Memory.unseen bug class)."""
    o = Ordering("H", "7")
    codes = sorted(set(make_deck()))
    assert list(o._eff) == codes
    assert list(o._lvl) == codes
    assert list(o._key) == codes


# ---------------------------------------------------------------------------
# 2. Full-round properties
# ---------------------------------------------------------------------------

def _drive_round(seed, bot_factory, level_idx=None, banker=None):
    """Play one full round, asserting conservation invariants at every step
    and validating every bot follow against the engine before applying it."""
    game = Game(random.Random(seed))
    if level_idx is not None:
        game.level_idx = list(level_idx)
        game.banker = banker
    rnd = game.start_round()
    deck_cnt = Counter(rnd.deck)
    bots = [bot_factory(i) for i in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        c = bots[seat].decide_declare(rnd, seat)
        if c:
            rnd.declare(seat, c)
    for s in range(4):
        c = bots[s].decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))

    def seen():
        cnt = Counter()
        for h in rnd.hands:
            cnt.update(h)
        cnt.update(rnd.buried)
        for t in rnd.history:
            for p in t.plays:
                cnt.update(p.cards)
        if rnd.trick:
            for p in rnd.trick.plays:
                cnt.update(p.cards)
        return cnt

    assert seen() == deck_cnt, "cards not conserved after bury"
    while rnd.phase == "play":
        seat = rnd.turn
        play = bots[seat].decide_play(rnd, seat)
        if rnd.trick.plays:  # bot follows must already be engine-legal
            validate_follow(play, rnd.hands[seat],
                            rnd.trick.plays[0].cards, rnd.ordering)
        rnd.play(seat, play)
        assert seen() == deck_cnt, "cards not conserved mid-play"

    # Points conservation: every deck point lands in a trick or the kitty.
    assert sum(t.points for t in rnd.history) + total_points(rnd.buried) \
        == DECK_POINTS
    att_trick_pts = sum(t.points for t in rnd.history
                        if rnd.is_attacker(t.winner))
    assert rnd.attacker_points == att_trick_pts + rnd.kitty_bonus
    final = rnd.history[-1]
    if rnd.is_attacker(final.winner):  # chaodi-free kitty accounting
        assert rnd.kitty_bonus == \
            total_points(rnd.buried) * 2 * len(final.plays[0].cards)
    else:
        assert rnd.kitty_bonus == 0
    game.finish_round()
    return rnd


class _FastMC(MCBot):
    N_DETERMINIZATIONS = 3


def test_conservation_and_legality_heuristic_smart():
    for seed in range(6):
        _drive_round(seed, lambda i: HeuristicBot())
        _drive_round(seed + 100, lambda i: SmartBot())


def test_conservation_and_legality_mc_wide_ballots():
    # MCBot head defaults have the wide ballots ON — this drives them.
    assert MCBot.WIDE_LEAD_BALLOT and MCBot.WIDE_FOLLOW_BALLOT
    for seed in (7, 8):
        _drive_round(seed, lambda i: _FastMC(seed=i))


def test_trump_rank_edge_suits():
    # rank A (top rank trump) and rank 10 (point card as trump rank)
    _drive_round(21, lambda i: SmartBot(), level_idx=[A_INDEX, A_INDEX], banker=0)
    _drive_round(22, lambda i: SmartBot(), level_idx=[8, 8], banker=1)
    _drive_round(23, lambda i: _FastMC(seed=i), level_idx=[A_INDEX, 3], banker=0)


def test_decompose_caches_stay_clean_after_full_round():
    """Standing anti-poison guard: after a real MC round (rollouts share the
    Ordering's caches), every cache entry must still equal a fresh reference
    computation on the same key."""
    rnd = _drive_round(31, lambda i: _FastMC(seed=i))
    o = rnd.ordering
    dcache = getattr(o, "_dcache", {})
    assert dcache, "expected the decompose memo to be exercised"
    for key, val in dcache.items():
        assert val == combos._decompose_uncached(list(key), o)
    for (key, k), val in getattr(o, "_trcache", {}).items():
        assert val == combos._find_tractor_runs_uncached(list(key), o, k)


def test_beats_antisymmetry_and_irreflexivity():
    rng = random.Random(0)
    deck = make_deck()
    for o in (Ordering("S", "2"), Ordering("H", "7"), Ordering(None, "A")):
        plays = []
        for _ in range(40):
            hand = rng.sample(deck, rng.randint(4, 12))
            suits = {}
            for c in hand:
                suits.setdefault(o.eff_suit(c), []).append(c)
            for cards in suits.values():
                for comp in combos.decompose(cards, o).components:
                    plays.append(list(comp.cards))
        checked = 0
        for a in plays:
            suit_a = o.eff_suit(a[0])
            top_a = combos.decompose(a, o).top_level()
            assert not beats(a, a, suit_a, top_a, o)[0]  # ties lose
            for b in plays:
                if combos.decompose(b, o).shape() != combos.decompose(a, o).shape():
                    continue
                won_b, top_b = beats(b, a, suit_a, top_a, o)
                if won_b:
                    suit_b = o.eff_suit(b[0])
                    assert not beats(a, b, suit_b, top_b, o)[0], (a, b)
                    checked += 1
        assert checked > 20


# ---------------------------------------------------------------------------
# 3. Blind spots
# ---------------------------------------------------------------------------

def _stub_round(banker, attacker_points):
    return types.SimpleNamespace(phase="round_end", banker=banker,
                                 attacker_points=attacker_points,
                                 kitty_bonus=0, buried=[])


def test_defend_at_A_endgame():
    # (a) banker team defends at A => game over, levels frozen
    g = Game()
    g.level_idx = [A_INDEX, 5]
    g.round = _stub_round(banker=0, attacker_points=79)
    res = g.finish_round()
    assert res.game_over and g.game_over
    assert g.level_idx == [A_INDEX, 5]
    # (b) attackers break the banker's A => NOT over, deal passes on
    g = Game()
    g.level_idx = [A_INDEX, 5]
    g.round = _stub_round(banker=0, attacker_points=120)
    res = g.finish_round()
    assert not res.game_over and res.winner_team == 1
    assert res.next_banker == 1 and g.level_idx[1] == 6
    # (c) attackers WIN at A => not over; they take the deal and must defend
    g = Game()
    g.level_idx = [5, A_INDEX]
    g.round = _stub_round(banker=0, attacker_points=120)
    res = g.finish_round()
    assert not res.game_over and res.winner_team == 1
    assert g.level_idx[1] == A_INDEX and res.next_banker == 1
    # (d) shutout defense at A still ends the game
    g = Game()
    g.level_idx = [7, A_INDEX]
    g.round = _stub_round(banker=1, attacker_points=0)
    res = g.finish_round()
    assert res.game_over and res.winner_team == 1


def test_shard_roundtrip():
    np = pytest.importorskip("numpy")
    from shengji.rl.dataset import Decision, TrajectoryWriter
    from shengji.rl.encode import ACT_DIM, OBS_DIM
    import tempfile

    rng = random.Random(5)

    def vec(n):
        return [round(rng.uniform(0, 1), 4) for _ in range(n)]

    decisions = []
    for i in range(7):
        n_act = rng.randint(1, 6)
        decisions.append(Decision(
            obs=vec(OBS_DIM),
            actions=[vec(ACT_DIM) for _ in range(n_act)],
            chosen=rng.randrange(n_act), seat=i % 4,
            ret=rng.uniform(-1, 1),
            action_values=(vec(n_act)[:n_act] if i % 2 == 0 else None)))
    with tempfile.TemporaryDirectory() as d:
        w = TrajectoryWriter(d)
        for dec in decisions:
            w.add(dec)
        w.flush()
        z = np.load(os.path.join(d, "shard_00000.npz"))
        off = z["offsets"]
        assert len(off) == len(decisions) + 1
        for i, dec in enumerate(decisions):
            assert np.allclose(z["obs"][i], np.float32(dec.obs))
            assert int(z["chosen"][i]) == dec.chosen
            assert abs(float(z["returns"][i]) - dec.ret) < 1e-6
            acts = z["actions"][off[i]:off[i + 1]]
            assert acts.shape == (len(dec.actions), ACT_DIM)
            assert np.allclose(acts, np.float32(dec.actions))
            assert bool(z["has_values"][i]) == (dec.action_values is not None)
            if dec.action_values is not None:
                assert np.allclose(z["action_values"][off[i]:off[i + 1]],
                                   np.float32(dec.action_values))


_ENUM_SCRIPT = """
import hashlib, random
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.rl.actions import enumerate_actions

game = Game(random.Random(7))
rnd = game.start_round()
while rnd.phase == "deal":
    rnd.deal_next()
bot = HeuristicBot()
for s in range(4):
    c = bot.decide_declare(rnd, s, final=True)
    if c:
        rnd.declare(s, c)
rnd.finalize_declare()
rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
h = hashlib.sha256()
while rnd.phase == "play":
    seat = rnd.turn
    h.update(repr(enumerate_actions(rnd, seat)).encode())
    h.update(repr(enumerate_actions(rnd, seat, include_throws=True)).encode())
    h.update(repr(enumerate_actions(rnd, seat,
                                    exhaustive_follows=True)).encode())
    rnd.play(seat, bot.decide_play(rnd, seat))
print(h.hexdigest())
"""


def test_enumerate_actions_deterministic_across_processes():
    """RL ballots must be byte-identical regardless of the interpreter's
    hash seed (the Memory.unseen incident class: hash-ordered iteration
    feeding candidate construction)."""
    digests = []
    for hash_seed in ("0", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        out = subprocess.run([sys.executable, "-c", _ENUM_SCRIPT],
                             capture_output=True, text=True, env=env,
                             cwd=os.path.dirname(os.path.dirname(
                                 os.path.abspath(__file__))))
        assert out.returncode == 0, out.stderr
        digests.append(out.stdout.strip())
    assert digests[0] == digests[1], "ballots differ across hash seeds"


def test_failed_throw_bookkeeping_matches_engine():
    """A bot's FAILED throw must remove/log what the ENGINE played, not the
    attempt. Regression for the 2026-08-03 server desync (Codex audit):
    ordinary self-play almost never fires a throw penalty, so this must be
    constructed."""
    import random
    from shengji.engine.game import Game
    from shengji.engine.round import actual_play_after
    from shengji.engine.legal import validate_lead

    game = Game(random.Random(5))
    rnd = game.start_round()
    while rnd.phase != "play":
        from shengji.ai.heuristic import HeuristicBot
        bot = HeuristicBot()
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        elif rnd.phase == "bury":
            rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    o = rnd.ordering
    seat = rnd.turn
    hand = rnd.hands[seat]
    # find a beatable multi-component throw in this seat's hand
    from collections import Counter
    from shengji.engine.cards import TRUMP
    from shengji.engine.legal import suit_cards
    attempt = None
    for s in "SHDC":
        cs = suit_cards(hand, s, o)
        cnt = Counter(cs)
        pair = next((c for c, n in cnt.items() if n >= 2), None)
        single = next((c for c in cs if c != pair), None)
        if pair and single:
            cand = [pair, pair, single]
            others = [rnd.hands[x] for x in range(4) if x != seat]
            played, msg = validate_lead(cand, hand, others, o)
            if msg:  # penalty fired
                attempt = (cand, played)
                break
    if attempt is None:
        import pytest
        pytest.skip("no beatable throw available in this deal")
    cand, expected = attempt
    prev_last = rnd.last_trick
    rnd.play(seat, cand)
    actual = actual_play_after(rnd, seat, prev_last)
    assert sorted(actual) == sorted(expected), (
        "helper must report the engine's forced play, not the attempt")
    assert len(actual) < len(cand), "this deal should have forced a penalty"


def _room_at_play(seed: int):
    """A Room advanced to the play phase, with ids mirroring the dealt hands.

    Built directly rather than over a websocket because the regression needs a
    SPECIFIC failed throw, which ordinary play almost never produces.
    """
    import random
    from shengji.api.server import Room
    from shengji.engine.game import Game
    from shengji.ai.heuristic import HeuristicBot

    room = Room(code="TST")
    room.game = Game(random.Random(seed))
    rnd = room.game.start_round()
    helper = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        elif rnd.phase == "bury":
            rnd.bury(rnd.banker, helper.decide_bury(rnd, rnd.banker))
    # ids mirror hands exactly; the desync this guards against is precisely
    # these two drifting apart
    room.ids = [{i * 4 + s: c for i, c in enumerate(rnd.hands[s])}
                for s in range(4)]
    return room, rnd


def _find_failing_throw(rnd, seat):
    """A multi-component lead this seat can be BEATEN on, so the penalty fires."""
    from collections import Counter
    from shengji.engine.legal import suit_cards, validate_lead
    o = rnd.ordering
    hand = rnd.hands[seat]
    for s in "SHDC":
        cs = suit_cards(hand, s, o)
        cnt = Counter(cs)
        pair = next((c for c, n in cnt.items() if n >= 2), None)
        single = next((c for c in cs if c != pair), None)
        if pair and single:
            cand = [pair, pair, single]
            others = [rnd.hands[x] for x in range(4) if x != seat]
            played, msg = validate_lead(cand, hand, others, o)
            if msg and len(played) < len(cand):
                return cand, played
    return None, None


def test_failed_throw_does_not_desync_the_room_at_the_SERVER_boundary():
    """The 2026-08-03 desync lived in `bot_step`, not in the engine.

    `tests/test_invariants.py::test_failed_throw_bookkeeping_matches_engine`
    covers `validate_lead` directly, so it cannot see a server-layer regression:
    `bot_step` must remove and log what the ENGINE played, not what the bot
    attempted. This drives the same failure through the real seam and asserts
    the client-visible hand (`room.ids`) still matches the engine hand.
    """
    from shengji.api.server import bot_step
    for seed in range(40):
        room, rnd = _room_at_play(seed)
        seat = rnd.turn
        cand, played = _find_failing_throw(rnd, seat)
        if cand is None:
            continue
        room.bot.decide_play = lambda r, s, _c=cand: list(_c)
        assert bot_step(room, seat) is True
        assert len(played) < len(cand), "the penalty must actually fire"
        assert sorted(room.ids[seat].values()) == sorted(rnd.hands[seat]), (
            "room ids desynced from the engine hand after a failed throw")
        return
    import pytest
    pytest.fail("no beatable throw found in 40 deals — fixture is not "
                "exercising the regression")


def test_the_boundary_check_CATCHES_the_historical_desync():
    """Falsification: reintroduce the bug and require the check to fail.

    Without this, the test above would pass against a `bot_step` that removed
    the attempt instead of the played cards, and would prove nothing.
    """
    import shengji.api.server as server
    from shengji.api.server import bot_step
    for seed in range(40):
        room, rnd = _room_at_play(seed)
        seat = rnd.turn
        cand, played = _find_failing_throw(rnd, seat)
        if cand is None:
            continue
        room.bot.decide_play = lambda r, s, _c=cand: list(_c)
        original = server.actual_play_after
        # the historical bug: mirror the ATTEMPT rather than what was played
        server.actual_play_after = lambda r, s, prev, _c=cand: list(_c)
        try:
            try:
                bot_step(room, seat)
            except StopIteration:
                return  # removing cards the hand no longer holds — also caught
            assert sorted(room.ids[seat].values()) != sorted(rnd.hands[seat]), (
                "the injected desync was not detected; the boundary assertion "
                "is vacuous")
        finally:
            server.actual_play_after = original
        return
    import pytest
    pytest.fail("no beatable throw found in 40 deals")


# --- high-N raw-record round trip -------------------------------------------
# The v6 gate artifacts REPLAY from these corpora, so a record that stops
# rebuilding breaks a frozen artifact silently. Nothing in the suite covered
# the raw records until now (no test referenced `highn` at all).
#
# The round trip asserts REPLAYABILITY, deliberately not the stored labels:
# `candidates`/`mean`/`best` were captured under the old ballot and non-strict
# sampler, so requiring them to regenerate would fail for legitimate reasons
# and the test would be deleted rather than believed.

def _highn_rows(n):
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "rl_data", "highn_corpus_all.jsonl")
    if not os.path.exists(path):
        return None
    out = []
    with open(path) as fh:
        for line in fh:
            out.append(json.loads(line))
            if len(out) >= n:
                break
    return out


def test_high_n_raw_records_round_trip_to_their_declared_state():
    import os
    import sys
    import pytest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "scripts"))
    rows = _highn_rows(40)
    if not rows:
        pytest.skip("high-N corpus absent (gitignored)")
    import pilot_states as PS
    from shengji.engine.cards import make_deck
    deck_size = len(make_deck())
    checked = 0
    for row in rows:
        rnd = PS.replay(row)
        assert rnd.turn == row["seat"], (
            f"seed {row['seed']} ply {row['ply']}: replayed to seat "
            f"{rnd.turn}, record declares {row['seat']}")
        # conservation: every card is in a hand, buried, or already played
        held = sum(len(h) for h in rnd.hands)
        played = sum(len(p["cards"]) for p in row["plays"])
        assert held + played + len(rnd.buried) == deck_size, (
            f"seed {row['seed']}: {held} held + {played} played + "
            f"{len(rnd.buried)} buried != {deck_size}")
        checked += 1
    assert checked == len(rows), "every sampled record must rebuild"


def test_a_corrupted_high_n_record_is_REJECTED():
    """Falsification: the round trip must fail on a tampered record.

    Without this, `replay` could silently accept a mismatched deck and the test
    above would pass against a corpus that no longer describes its states.
    """
    import os
    import sys
    import pytest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "scripts"))
    rows = _highn_rows(1)
    if not rows:
        pytest.skip("high-N corpus absent (gitignored)")
    import pilot_states as PS
    row = dict(rows[0])
    row["setup"] = dict(row["setup"])
    deck = list(row["setup"]["deck"])
    deck[0], deck[1] = deck[1], deck[0]      # swap two cards
    row["setup"]["deck"] = deck
    with pytest.raises(ValueError, match="deck mismatch"):
        PS.replay(row)
