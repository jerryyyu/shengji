"""The compiled hot paths of the served search (`pv_native`, `_pv_fast`).

Torch-free and package-free.  Witnesses for ``SHENGJI_PV_ENCODE_NATIVE=1``:
(e) `fused_many_native` is `fused_many_batched` byte for byte (every field,
the None pattern) at encoder v1, v2 and v7 on value leaves and open reply
clones over seeded rounds and the named leaf scenarios, with the kernel
building (not declining) the batches; (f) it declines to the batched builder
what that builder skips or refuses; (g) paired ``lgf`` bots decide
identically with the switch off and on; (h) the switch is off by default and
enters no name.  Witnesses for ``SHENGJI_PV_LEAF_CLONE_FAST=1`` and
``SHENGJI_PV_LEAF_TRICK_CACHE=1``: (i) `afterstate_fast` / `child_position_fast`
build the clones `afterstate` / `child_position` build, attribute for
attribute, and `shallow_round` falls back to ``copy.copy`` off the default
protocol; (j) a seeded follow-root clone holds the caches the trusted rollout
builds playing the same trick from its lead, and finishes its trick as the
unseeded clone does; (k) paired ``lgf`` bots with every native switch on
decide as the plain bot.  Witnesses for ``SHENGJI_PV_WORLD_FAST=1``: (l)
`belief_sample_worlds` is `belief_seq.sample_worlds` (the worlds, the
generator's state after, the refusals at the same state) on the proposal
inputs of seeded decisions with random marginals, and declines arrays it does
not take before touching the generator; (m) `world_completion` is
``_complete_determinized_hands`` (the hands, each refusal and its message).
The served bot with every native switch on is `test_pv_native_release48`.
Witnesses for ``SHENGJI_PV_LEGAL_NATIVE=1``:
(a) `pv_native.follow_listing` is ``islice(iter_follow_actions(...), cap)``
action for action -- every follow case (in-suit with its validator, short,
void), single, pair, tractor and throw leads, caps from 1 to unbounded -- over
seeded deals; (b) `legal_replies_compact` with ``native`` returns the same
listing, scoring products and single-action shape as without it; (c) paired
``lgf`` bots decide identically with the switch off and on (cards, record,
sampler state, the finish's counters, the evaluator's counters); (d) the
switch is off by default, read from the environment like the other latency
switches, and enters no name or payload; without the compiled module the
listing declines and the Python reference runs.
"""
import copy
import random
from itertools import islice

import numpy as np
import pytest

from shengji.engine.game import Game
from shengji.harvest import legal as harvest_legal
from shengji.harvest.legal import iter_follow_actions, iter_lead_actions
from shengji.train import pv_native
from shengji.train import pv_search_policy as pv
from shengji.train import pv_tree_search as pts
from native_switches import NATIVE_OFF
from test_pv_encode_batch_fast import lgf_bot
from test_pv_encode_prefix import counters
from test_pv_doomed_throw_reselect_exact_guard import R46_ENV
from test_pv_leaf_greedy_finish import LEAF_KEYS
from test_pv_lgf_reply_prefix import CAPPED_SEED
from test_pv_small_joker_lead import _fresh_round

FLAG = "SHENGJI_PV_LEGAL_NATIVE"

needs_native = pytest.mark.skipif(not pv_native.HAVE_NATIVE,
                                  reason="train/_pv_fast is not built")


def _decoded(listing):
    cards, offsets = listing
    names = pv_native._tables()[2]
    return [tuple(names[c] for c in cards[offsets[i]:offsets[i + 1]].tolist())
            for i in range(len(offsets) - 1)]


def _deals(seeds):
    """``(hands, ordering)`` of seeded deals after the declaration."""
    for seed in seeds:
        rnd = _fresh_round(seed)
        yield [list(hand) for hand in rnd.hands], rnd.ordering


def _cases(seeds, rng):
    """``(hand, lead, ordering)``: every seat's hand and random sub-hands
    against leads drawn from another seat's full lead listing (singles,
    pairs, tractors and throws)."""
    for hands, ordering in _deals(seeds):
        for leader in range(4):
            leads = list(islice(iter_lead_actions(hands[leader], ordering), 3000))
            picks = rng.sample(leads, min(len(leads), 25))
            # the multi-card leads are where listings grow
            picks += [lead for lead in leads if len(lead) >= 3][:: max(1, len(leads) // 40)]
            for lead in picks:
                for seat in range(4):
                    if seat == leader:
                        continue
                    hand = hands[seat]
                    yield list(hand), list(lead), ordering
                    sub = rng.sample(hand, rng.randint(len(lead), len(hand)))
                    yield sub, list(lead), ordering


# ------------------------------------------------- (a) the same listing

@needs_native
def test_the_native_follow_listing_is_the_python_enumeration_over_seeded_deals():
    rng = random.Random(1026)
    kinds = {"in-suit": 0, "short": 0, "void": 0}
    capped = rows = 0
    for hand, lead, ordering in _cases(range(707001, 707007), rng):
        case = harvest_legal._follow_case(hand, lead, ordering)[0]
        for cap in (None, 1, 3, 4000, 37):
            reference = list(islice(iter_follow_actions(list(hand), lead, ordering), cap))
            got = _decoded(pv_native.follow_listing(list(hand), lead, ordering, cap))
            assert got == reference, (hand, lead, cap)
            capped += cap is not None and len(reference) == cap
            rows += len(reference)
        kinds[case] += 1
    assert min(kinds.values()) > 200, kinds
    assert capped > 500 and rows > 100_000


@needs_native
def test_the_native_listing_reaches_the_cap_on_a_capped_follow():
    """The capped (4000) first-trick follow of `CAPPED_SEED` (a void hand
    facing a long throw)."""
    rnd = _fresh_round(CAPPED_SEED)
    from shengji.ai.heuristic import HeuristicBot
    helper = HeuristicBot()
    seen = 0
    while rnd.phase == "play" and seen < 400:
        seat = rnd.turn
        if rnd.trick.plays:
            hand, lead = list(rnd.hands[seat]), rnd.trick.plays[0].cards
            reference = list(islice(iter_follow_actions(list(hand), lead, rnd.ordering), 4000))
            got = _decoded(pv_native.follow_listing(hand, lead, rnd.ordering, 4000))
            assert got == reference
        rnd.play(seat, helper.decide_play(rnd, seat))
        seen += 1


@needs_native
def test_the_native_listing_raises_what_the_reference_raises():
    hands, ordering = next(_deals([707001]))
    # a lead of mixed suits has no follow case: the reference's assertion
    mixed = [hands[0][0], next(c for c in hands[0] if ordering.eff_suit(c)
                               != ordering.eff_suit(hands[0][0]))]
    with pytest.raises(AssertionError):
        list(iter_follow_actions(list(hands[1]), mixed, ordering))
    with pytest.raises(AssertionError):
        pv_native.follow_listing(list(hands[1]), mixed, ordering, 4000)
    # an unknown card in the hand: the reference's validator refuses it
    # (in-suit) or the card numbering does (short and void)
    for hand in ([*hands[1], "ZZ"],):
        for lead in ([hands[0][0]], [hands[0][0]] * 2):
            try:
                reference = list(islice(iter_follow_actions(list(hand), lead, ordering), 4000))
            except Exception as exc:     # noqa: BLE001 -- the class is what is compared
                with pytest.raises(type(exc)):
                    pv_native.follow_listing(list(hand), lead, ordering, 4000)
            else:
                try:
                    got = _decoded(pv_native.follow_listing(list(hand), lead, ordering, 4000))
                except KeyError:
                    # the listing numbers every card; CompactReplies would raise the same
                    with pytest.raises(KeyError):
                        pts.CompactReplies([list(a) for a in reference], leads=False)
                else:
                    assert got == reference


# ------------------------------------------------- (b) legal_replies_compact

class _Cap:
    def __init__(self, cap):
        self.cap = cap


@needs_native
def test_compact_replies_with_native_are_the_reference_listing_and_scores():
    from shengji.ai.heuristic import HeuristicBot
    helper = HeuristicBot()
    rng = np.random.default_rng(5)
    checked = singles = 0
    for seed in (CAPPED_SEED, 707_001, 707_002):
        rnd = _fresh_round(seed)
        while rnd.phase == "play":
            seat = rnd.turn
            if rnd.trick.plays:
                for cap in (4000, 2):
                    bot = _Cap(cap)
                    a = pts.legal_replies_compact(bot, rnd, seat, {}, pts._DenseSlot())
                    b = pts.legal_replies_compact(bot, rnd, seat, {}, pts._DenseSlot(), True)
                    assert len(a[0]) == len(b[0])
                    assert [a[0][i] for i in range(len(a[0]))] == \
                        [b[0][i] for i in range(len(b[0]))]
                    if a[1] is None:
                        assert b[1] is None and type(a[0]) is type(b[0]) is list
                        singles += 1
                    else:
                        row = rng.normal(size=54)
                        assert (a[1] @ row).tobytes() == (b[1] @ row).tobytes()
                    checked += 1
            rnd.play(seat, helper.decide_play(rnd, seat))
    assert checked > 300 and singles > 20


# ------------------------------------------------- (c) paired lgf bots

def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds") and not k.endswith("_ms")}


@needs_native
@pytest.mark.parametrize("version", [2, 7])
def test_the_native_listing_lgf_bot_decides_exactly_as_the_python_one(version, monkeypatch):
    calls = []
    real = pv_native.follow_listing
    monkeypatch.setattr(pv_native, "follow_listing", lambda *a: calls.append(1) or real(*a))
    decisions = applied = 0
    for seed in (CAPPED_SEED, 707_001):
        rnd = _fresh_round(seed)
        plain = [lgf_bot(version, True, 100 + s) for s in range(4)]
        fast = [lgf_bot(version, True, 100 + s) for s in range(4)]
        for bot in fast:
            bot.legal_native = True
        while rnd.phase == "play":
            seat = rnd.turn
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            b = fast[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain[seat].last_decision_record, fast[seat].last_decision_record
            assert a == b and _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
            assert LEAF_KEYS <= set(rb)
            assert plain[seat].sampler.rng.getstate() == fast[seat].sampler.rng.getstate()
            assert plain[seat]._leaf_greedy["stats"] == fast[seat]._leaf_greedy["stats"]
            assert counters(plain[seat].evaluator) == counters(fast[seat].evaluator)
            decisions += 1
            applied += bool(ra["leaf_greedy_finish_applied"])
            rnd.play(seat, a)
    assert decisions >= 80 and applied > 20 and calls


# ------------------------------------------------- (d) env, default, name, fallback

def test_the_legal_switch_is_off_by_default_and_enters_no_name():
    assert pv.PVSearchBot.legal_native is False
    assert pv.LATENCY_SWITCH_ENV["legal_native"] == FLAG
    assert pv.latency_switches({})["legal_native"] is False
    assert pv.latency_switches({FLAG: "1"})["legal_native"] is True
    with pytest.raises(pv.PVSearchPolicyError, match=FLAG):
        pv.latency_switches({FLAG: "yes"})
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    assert pv.pv_env_recipe({**env, FLAG: "1"}) == pv.pv_env_recipe(env)
    assert "legal_native" not in vars(lgf_bot(2, True, 1))


def test_without_the_compiled_module_the_listing_declines(monkeypatch):
    monkeypatch.setattr(pv_native, "_pv_fast", None)
    hands, ordering = next(_deals([707001]))
    assert pv_native.follow_listing(list(hands[1]), [hands[0][0]], ordering, 4000) is None
    rnd = _fresh_round(707001)
    from shengji.ai.heuristic import HeuristicBot
    rnd.play(rnd.turn, HeuristicBot().decide_play(rnd, rnd.turn))
    seat = rnd.turn
    a = pts.legal_replies_compact(_Cap(4000), rnd, seat, {}, pts._DenseSlot())
    b = pts.legal_replies_compact(_Cap(4000), rnd, seat, {}, pts._DenseSlot(), True)
    assert [a[0][i] for i in range(len(a[0]))] == [b[0][i] for i in range(len(b[0]))]


# ------------------------------------------------- (e)-(h) the native encoder

from shengji.train import pv_encode_prefix as pe  # noqa: E402
from test_pv_encode_batch_fast import _same_row  # noqa: E402
from test_pv_encode_prefix import SCENARIOS, find_root, leaves_for, worlds_for  # noqa: E402
from test_pv_lgf_reply_prefix import _roots  # noqa: E402

ENCODE_FLAG = "SHENGJI_PV_ENCODE_NATIVE"


def _native_prefix(rnd):
    prefix = pe.HistoryPrefix.of(rnd, batched=True, native=True)
    assert prefix.native is not None
    return prefix


def _kernel_counter(monkeypatch):
    built = []
    real = pv_native._pv_fast.encode_static_batch

    def spy(*args):
        out = real(*args)
        built.append(out is not None)
        return out
    monkeypatch.setattr(pv_native._pv_fast, "encode_static_batch", spy)
    return built


def _assert_native_same(prefix, positions, seats, version):
    reference = pe.fused_many_batched(prefix, positions, seats, version)
    got = pe.fused_many_native(prefix, positions, seats, version)
    assert len(got) == len(reference)
    for index, (a, b) in enumerate(zip(got, reference)):
        assert _same_row(a, b), (version, index)
    return sum(row is not None for row in reference)


@needs_native
@pytest.mark.parametrize("version", [1, 2, 7])
def test_native_rows_are_the_batched_rows_byte_for_byte_over_seeded_rounds(version, monkeypatch):
    built = _kernel_counter(monkeypatch)
    rows = 0
    for rnd, seat, leaves, opened in _roots((CAPPED_SEED, 707_001, 707_002, 707_003)):
        prefix = _native_prefix(rnd)
        for positions, seats in ((leaves, [seat] * len(leaves)),
                                 (opened, [c.turn for c in opened])):
            for order in (slice(None), slice(None, None, -1)):
                rows += _assert_native_same(prefix, positions[order], seats[order], version)
    assert rows > 3000
    assert sum(built) > 0.95 * len(built), (sum(built), len(built))


@needs_native
@pytest.mark.parametrize("version", [1, 2, 7])
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_native_rows_are_the_batched_rows_on_the_named_leaves(scenario, version):
    rnd, seat = find_root(SCENARIOS[scenario])
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 3, seed=len(rnd.history)))
    live = [leaf for leaf in leaves if leaf.phase == "play"]
    _assert_native_same(_native_prefix(rnd), live, [seat] * len(live), version)


@needs_native
def test_native_rows_decline_what_the_batched_builder_declines(monkeypatch):
    built = _kernel_counter(monkeypatch)
    rnd, seat, leaves, opened = next(_roots((707_001,)))
    later = None
    for later in _roots((707_001,)):
        if len(later[0].history) >= 3:
            break
    prefix = _native_prefix(later[0])
    # another root's leaves (a shorter history), an unknown card, a malformed
    # hand, a no-trump flag clash, a foreign seat type
    bad_card = copy.deepcopy(later[2][0]); bad_card.hands[1] = [*bad_card.hands[1][:-1], "ZZ"]
    bad_hand = copy.deepcopy(later[2][0]); bad_hand.hands[2] = tuple(bad_hand.hands[2])
    no_suit = copy.deepcopy(later[2][0]); no_suit.trump_is_nt = False; no_suit.trump_suit = None
    for positions in (leaves, [bad_card, *later[2]], [*later[2], bad_hand],
                      [no_suit, *later[2]]):
        for version in (1, 2, 7):
            _assert_native_same(prefix, positions, [later[1]] * len(positions), version)
    assert pe.fused_many_native(prefix, later[2], [later[1]] * len(later[2]), 3) == \
        [None] * len(later[2])
    # the shorter-history leaves and the three malformed batches, at three versions
    assert built.count(False) >= 12


@needs_native
@pytest.mark.parametrize("version", [1, 2, 7])
def test_encode_leaves_and_reply_rows_on_a_native_prefix_are_the_batched_rows(version):
    """On the served evaluator class the native leaves are held stacked
    (`StackedRows`): the arrays ``np.stack`` gives over the batched rows'
    fields; the reply rows are the batched ones byte for byte."""
    from test_pv_encode_prefix import stub_evaluator
    stacked = replies = 0
    for rnd, seat, leaves, opened in _roots((707_002, 707_004)):
        batched = pe.HistoryPrefix.of(rnd, batched=True)
        native = _native_prefix(rnd)
        if leaves:
            ev = stub_evaluator(version)
            a = pe.encode_leaves(ev, leaves, seat, batched)
            b = pe.encode_leaves(ev, leaves, seat, native)
            assert a is not None and b is not None and a[2] == b[2] and a[3] == b[3]
            assert a[0][[i for i, leaf in enumerate(leaves) if leaf.phase == "round_end"]] \
                .tobytes() == b[0][[i for i, leaf in enumerate(leaves)
                                    if leaf.phase == "round_end"]].tobytes()
            assert type(b[1]) is pe.StackedRows and len(b[1]) == len(a[1])
            for field, array in zip(("public", "world", "perspective"), b[1].arrays):
                reference = np.stack([getattr(row, field) for row in a[1]])
                assert array.dtype == reference.dtype and array.tobytes() == reference.tobytes()
            stacked += 1
        if opened:
            turn = opened[0].turn
            a = pe.reply_rows(opened, turn, version, batched)
            b = pe.reply_rows(opened, turn, version, native)
            assert len(a) == len(b)
            assert all(x.dtype == y.dtype and x.shape == y.shape and x.tobytes() == y.tobytes()
                       for x, y in zip(a, b))
            replies += 1
    assert stacked > 50 and replies > 20


@needs_native
@pytest.mark.parametrize("version", [2, 7])
def test_score_leaves_on_a_native_prefix_is_the_batched_score(version):
    """The stacked forward (`probabilities_stacked`): the same values byte for
    byte and the same evaluator counters as the rows' forward."""
    from test_pv_encode_prefix import stub_evaluator
    checked = 0
    for rnd, seat, leaves, _ in _roots((707_005,)):
        if not leaves:
            continue
        a_ev, b_ev = stub_evaluator(version), stub_evaluator(version)
        a = pe.score_leaves(a_ev, leaves, seat, pe.HistoryPrefix.of(rnd, batched=True))
        b = pe.score_leaves(b_ev, leaves, seat, _native_prefix(rnd))
        assert a.tobytes() == b.tobytes()
        assert counters(a_ev) == counters(b_ev)
        checked += 1
    assert checked > 30


@needs_native
def test_the_stacked_forward_is_the_rows_forward_across_chunks():
    from test_pv_encode_prefix import stub_evaluator
    rnd, seat, leaves, _ = next(r for r in _roots((707_006,)) if len(r[2]) >= 7)
    rows = pe.fused_many_batched(pe.HistoryPrefix.of(rnd, batched=True), leaves,
                                 [seat] * len(leaves), 7)
    rows = [row for row in rows if row is not None]
    for chunk in (1, 3, len(rows), 4096):
        a, b = stub_evaluator(7), stub_evaluator(7)
        a.max_batch = b.max_batch = chunk
        x = a.probabilities(rows)
        y = b.probabilities_stacked(*(np.stack([getattr(r, f) for r in rows])
                                      for f in ("public", "world", "perspective")))
        assert x.tobytes() == y.tobytes() and a.forward_calls == b.forward_calls


@needs_native
@pytest.mark.parametrize("version", [2, 7])
def test_the_native_encoder_lgf_bot_decides_exactly_as_the_batched_one(version, monkeypatch):
    built = _kernel_counter(monkeypatch)
    decisions = applied = 0
    for seed in (CAPPED_SEED, 707_003):
        rnd = _fresh_round(seed)
        plain = [lgf_bot(version, True, 200 + s) for s in range(4)]
        fast = [lgf_bot(version, True, 200 + s) for s in range(4)]
        for bot in fast:
            bot.encode_native = True
            bot.legal_native = True
        while rnd.phase == "play":
            seat = rnd.turn
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            b = fast[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain[seat].last_decision_record, fast[seat].last_decision_record
            assert a == b and _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
            assert plain[seat].sampler.rng.getstate() == fast[seat].sampler.rng.getstate()
            assert plain[seat]._leaf_greedy["stats"] == fast[seat]._leaf_greedy["stats"]
            assert counters(plain[seat].evaluator) == counters(fast[seat].evaluator)
            decisions += 1
            applied += bool(ra["leaf_greedy_finish_applied"])
            rnd.play(seat, a)
    assert decisions >= 80 and applied > 20 and sum(built) > 100


def test_the_encode_switch_is_off_by_default_and_enters_no_name():
    assert pv.PVSearchBot.encode_native is False
    assert pv.LATENCY_SWITCH_ENV["encode_native"] == ENCODE_FLAG
    assert pv.latency_switches({})["encode_native"] is False
    assert pv.latency_switches({ENCODE_FLAG: "1"})["encode_native"] is True
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    assert pv.pv_env_recipe({**env, ENCODE_FLAG: "1"}) == pv.pv_env_recipe(env)
    assert "encode_native" not in vars(lgf_bot(2, True, 1))
    rnd = _fresh_round(707_001)
    assert pe.HistoryPrefix.of(rnd).native is None
    assert pe.HistoryPrefix.of(rnd, native=True).native is None      # needs ``batched``


def test_without_the_compiled_module_the_native_prefix_is_off(monkeypatch):
    monkeypatch.setattr(pv_native, "_pv_fast", None)
    rnd = _fresh_round(707_001)
    prefix = pe.HistoryPrefix.of(rnd, batched=True, native=True)
    assert prefix.native is None and pe._builder(prefix) is pe.fused_many_batched


# ------------------------------------------------- (i)-(k) clones and trick caches

from shengji.ai.cwv_policy import afterstate, child_position, finish_current_trick  # noqa: E402
from shengji.engine.round import Round  # noqa: E402

ALL_SWITCHES = tuple(NATIVE_OFF)


def _state(rnd):
    """Every attribute, the trick's caches and plays spelled out."""
    out = dict(vars(rnd))
    trick = out.pop("trick")
    out["trick"] = None if trick is None else (
        trick.leader, [(p.seat, list(p.cards)) for p in trick.plays], trick.winner, trick.points,
        trick.incumbent, trick.running_points)
    return out


def _sharing(a, b):
    """Which attributes of two clones of one parent are the parent's own objects."""
    return sorted(k for k in vars(a) if vars(a)[k] is vars(b).get(k))


def _clone_states(seeds):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.harvest.legal import enumerate_legal
    helper = HeuristicBot()
    for seed in seeds:
        rnd = _fresh_round(seed)
        while rnd.phase == "play":
            seat = rnd.turn
            actions = [list(a) for a in enumerate_legal(rnd, seat, cap=6).actions[:6]]
            yield rnd, seat, actions
            rnd.play(seat, helper.decide_play(rnd, seat))


def test_the_fast_clones_are_the_reference_clones_attribute_for_attribute():
    checked = 0
    for rnd, seat, actions in _clone_states((707_001, 707_002)):
        hands, buried = [list(h) for h in rnd.hands], list(rnd.buried)
        for action in actions:
            a = afterstate(rnd, seat, hands, buried, action, finish_trick=False)
            b = pts.afterstate_fast(rnd, seat, hands, buried, action)
            assert type(a) is type(b) is Round and _state(a) == _state(b)
            assert list(vars(a)) == list(vars(b))
            assert _sharing(a, rnd) == _sharing(b, rnd)
            if a.phase == "play" and a.trick.plays:
                reply = HeuristicBot().decide_play(a, a.turn)
                c = child_position(a, a.turn, reply)
                d = pts.child_position_fast(b, b.turn, reply)
                assert _state(c) == _state(d) and list(vars(c)) == list(vars(d))
                assert _sharing(c, a) == _sharing(d, b)
            checked += 1
    assert checked > 400


def test_the_shallow_copy_falls_back_off_the_default_protocol(monkeypatch):
    calls = []

    class Other(Round):
        def __copy__(self):
            calls.append(1)
            return "copied"
    rnd = _fresh_round(707_001)
    other = Other.__new__(Other)
    other.__dict__.update(vars(rnd))
    assert pts.shallow_round(other) == "copied" and calls
    clone = pts.shallow_round(rnd)
    assert clone is not rnd and type(clone) is Round and vars(clone) == vars(rnd)
    monkeypatch.setattr(pts, "_ROUND_DEFAULT_COPY", False)
    assert vars(pts.shallow_round(rnd)) == vars(rnd)


from shengji.ai.heuristic import HeuristicBot  # noqa: E402


def _trusted_replay(rnd, seat, hands, buried, action):
    """The trick of ``afterstate(...)`` played again from its lead inside a
    trusted clone, so `Round.play` builds the caches itself."""
    clone = afterstate(rnd, seat, hands, buried, action, finish_trick=False)
    if clone.phase != "play" or not clone.trick.plays:
        return clone, None
    replay = copy.copy(clone)
    from shengji.engine.round import Trick
    plays = clone.trick.plays
    replay.hands = [list(h) for h in clone.hands]
    for play in plays:
        replay.hands[play.seat].extend(play.cards)
    replay.trick = Trick(leader=plays[0].seat)
    replay.turn = plays[0].seat
    replay.history = list(clone.history)
    for play in plays:
        replay.play(play.seat, list(play.cards))
    return clone, replay


def test_seeded_caches_are_the_trusted_rollout_caches_and_finish_alike():
    seeded = 0
    for rnd, seat, actions in _clone_states((707_001, 707_002, 707_003)):
        if not rnd.trick.plays:
            continue
        hands, buried = [list(h) for h in rnd.hands], list(rnd.buried)
        for action in actions:
            clone, replay = _trusted_replay(rnd, seat, hands, buried, action)
            if replay is None:
                continue
            assert clone.trick.incumbent is None and clone.trick.running_points is None
            plain = copy.deepcopy(clone)
            pts.seed_trick_caches(clone)
            assert (clone.trick.incumbent, clone.trick.running_points) == \
                (replay.trick.incumbent, replay.trick.running_points)
            assert clone.trick.running_points is not None
            finish_current_trick(clone)
            finish_current_trick(plain)
            assert _state(clone)["history"] == _state(plain)["history"]
            last_a, last_b = clone.history[-1], plain.history[-1]
            assert [(p.seat, p.cards) for p in last_a.plays] == \
                [(p.seat, p.cards) for p in last_b.plays]
            assert (last_a.winner, last_a.points, clone.attacker_points, clone.turn) == \
                (last_b.winner, last_b.points, plain.attacker_points, plain.turn)
            seeded += 1
    assert seeded > 300


def test_seeding_leaves_lead_and_cached_tricks_alone():
    rnd = _fresh_round(707_001)
    hands, buried = [list(h) for h in rnd.hands], list(rnd.buried)
    action = HeuristicBot().decide_play(rnd, rnd.turn)
    clone = afterstate(rnd, rnd.turn, hands, buried, action, finish_trick=False)
    before = (clone.trick.incumbent, clone.trick.running_points)
    assert before[1] is not None                      # the lead built them
    pts.seed_trick_caches(clone)
    assert (clone.trick.incumbent, clone.trick.running_points) == before
    untrusted = copy.deepcopy(rnd)
    untrusted.play(untrusted.turn, list(action))
    pts.seed_trick_caches(untrusted)                  # not a trusted clone
    assert untrusted.trick.incumbent is None and untrusted.trick.running_points is None


@needs_native
@pytest.mark.parametrize("version", [2, 7])
def test_every_native_switch_lgf_bot_decides_exactly_as_the_plain_one(version):
    decisions = applied = 0
    for seed in (CAPPED_SEED, 707_004):
        rnd = _fresh_round(seed)
        plain = [lgf_bot(version, True, 300 + s) for s in range(4)]
        fast = [lgf_bot(version, True, 300 + s) for s in range(4)]
        for bot in fast:
            for attr in ALL_SWITCHES:
                setattr(bot, attr, True)
        while rnd.phase == "play":
            seat = rnd.turn
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            b = fast[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain[seat].last_decision_record, fast[seat].last_decision_record
            assert a == b and _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
            assert plain[seat].sampler.rng.getstate() == fast[seat].sampler.rng.getstate()
            assert plain[seat]._leaf_greedy["stats"] == fast[seat]._leaf_greedy["stats"]
            assert counters(plain[seat].evaluator) == counters(fast[seat].evaluator)
            assert fast[seat]._leaf_greedy["cache"] == {}
            decisions += 1
            applied += bool(ra["leaf_greedy_finish_applied"])
            rnd.play(seat, a)
    assert decisions >= 80 and applied > 20


def test_the_clone_and_cache_switches_are_off_by_default_and_enter_no_name():
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    for attr, flag in (("leaf_cache_release", "SHENGJI_PV_LEAF_CACHE_RELEASE"),
                       ("leaf_clone_fast", "SHENGJI_PV_LEAF_CLONE_FAST"),
                       ("leaf_trick_cache", "SHENGJI_PV_LEAF_TRICK_CACHE")):
        assert getattr(pv.PVSearchBot, attr) is False
        assert pv.LATENCY_SWITCH_ENV[attr] == flag
        assert pv.latency_switches({flag: "1"})[attr] is True
        assert pv.pv_env_recipe({**env, flag: "1"}) == pv.pv_env_recipe(env)
        assert attr not in vars(lgf_bot(2, True, 1))


# ------------------------------------------------- (l)-(m) the world draw

from shengji.ai.belief_numpy import decision_inputs  # noqa: E402
from shengji.train import belief_seq  # noqa: E402


def _proposal_inputs(seeds, rng):
    """``(Q, n_c, M, sizes)`` of seeded heuristic decisions, the marginals a
    random positive table projected to the receiver sizes as the proposal does."""
    for rnd, seat, _ in _clone_states(seeds):
        inp = decision_inputs(rnd, seat)
        M = np.asarray(inp["M"], bool)
        P = np.where(M, rng.gamma(0.7, size=M.shape), 0.0)
        yield belief_seq.project_sizes(P, inp["n_c"], inp["sizes"], M), inp["n_c"], M, \
            inp["sizes"]


@needs_native
def test_the_native_belief_draw_is_the_reference_draw_and_stream():
    rng = np.random.default_rng(11)
    checked = 0
    for Q, n_c, M, sizes in _proposal_inputs((707_001, 707_002), rng):
        for W in (1, 7, 64):
            seed = int(rng.integers(1 << 62))
            a_rng, b_rng = np.random.default_rng(seed), np.random.default_rng(seed)
            a = belief_seq.sample_worlds(Q, n_c, M, sizes, W, a_rng)
            b = pv_native.belief_sample_worlds(Q, n_c, M, sizes, W, b_rng)
            assert a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()
            assert a_rng.bit_generator.state == b_rng.bit_generator.state
            checked += 1
    assert checked > 300


@needs_native
def test_the_native_belief_draw_refuses_where_the_reference_refuses():
    rng = np.random.default_rng(12)
    Q, n_c, M, sizes = next(_proposal_inputs((707_003,), rng))
    # one receiver short of its copies: no completable receiver at some copy
    short = sizes.copy()
    short[int(np.argmax(short))] -= 1
    for bad_sizes in (short,):
        a_rng, b_rng = np.random.default_rng(5), np.random.default_rng(5)
        with pytest.raises(belief_seq.BeliefSeqError) as a:
            belief_seq.sample_worlds(Q, n_c, M, bad_sizes, 16, a_rng)
        with pytest.raises(belief_seq.BeliefSeqError) as b:
            pv_native.belief_sample_worlds(Q, n_c, M, bad_sizes, 16, b_rng)
        assert str(a.value) == str(b.value)
        assert a_rng.bit_generator.state == b_rng.bit_generator.state
    with pytest.raises(belief_seq.BeliefSeqError):
        pv_native.belief_sample_worlds(np.full_like(Q, np.nan), n_c, M, sizes, 4,
                                       np.random.default_rng(1))
    untouched = np.random.default_rng(3)
    state = untouched.bit_generator.state
    assert pv_native.belief_sample_worlds(Q.astype(np.float32), n_c, M, sizes, 4, untouched) is None
    assert pv_native.belief_sample_worlds(Q, n_c, M.astype(np.int8), sizes, 4, untouched) is None
    assert untouched.bit_generator.state == state


def test_the_world_completion_is_the_reference_completion():
    from shengji.ai.mcbot import DeterminizationContractError, MCBot
    bot = MCBot(seed=1)
    checked = 0
    for rnd, seat, _ in _clone_states((707_001, 707_004)):
        complete = pv_native.world_completion(bot, rnd, seat)
        others = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
        buried = list(rnd.buried)
        cases = [others, {**others, (seat + 1) % 4: others[(seat + 1) % 4][:-1]},
                 {s: h for s, h in others.items() if s != (seat + 2) % 4}]
        if others[(seat + 1) % 4]:
            swapped = dict(others)
            swapped[(seat + 1) % 4] = [*others[(seat + 1) % 4][1:], "SA"]
            cases.append(swapped)
        for sampled in cases:
            for bury in (buried, buried[:-1] + ["HA"]):
                try:
                    reference = bot._complete_determinized_hands(rnd, seat, sampled, buried=bury)
                except DeterminizationContractError as exc:
                    with pytest.raises(DeterminizationContractError) as got:
                        complete(rnd, seat, sampled, buried=bury)
                    assert str(got.value) == str(exc)
                else:
                    assert complete(rnd, seat, sampled, buried=bury) == reference
                checked += 1
    assert checked > 1000

    class Override(MCBot):
        def _complete_determinized_hands(self, *a, **k):
            return None
    rnd = _fresh_round(707_001)
    assert pv_native.world_completion(Override(seed=1), rnd, rnd.turn) is None


def test_the_world_switch_is_off_by_default_and_enters_no_name():
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    assert pv.PVSearchBot.world_fast is False
    assert pv.LATENCY_SWITCH_ENV["world_fast"] == "SHENGJI_PV_WORLD_FAST"
    assert pv.latency_switches({"SHENGJI_PV_WORLD_FAST": "1"})["world_fast"] is True
    assert pv.pv_env_recipe({**env, "SHENGJI_PV_WORLD_FAST": "1"}) == pv.pv_env_recipe(env)
