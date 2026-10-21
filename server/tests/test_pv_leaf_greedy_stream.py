"""The ``lgf`` memory switch (``SHENGJI_PV_LEAF_GREEDY_STREAM=1``, a latency
switch: no name, payload or digest) and the prefix-encoded reply valuations
(``SHENGJI_PV_ENCODE_PREFIX_CACHE=1`` with ``lgf``).

The greedy finish's reply listings are held as int8 card indices for one ply
(`pv_tree_search.CompactReplies`) and each scoring matrix is rebuilt at its
product (`LazyScoring`).  Witnesses: (a) the compact listing reads as
`legal_replies`' listing, its matrix is the same bytes and its products the
same floats, on a capped 4000-follow listing, other follows and leads; the ply
keeps one materialized matrix; (b) package-free paired bots over seeded rounds
with release 46's rules plus ``lgf``: the switched bot is the plain one
decision for decision (cards, record, sampler state, the finish's counters);
(c) the switch's plumbing: off by default, ``0``/``1`` only, instance state of
an ON bot only, no name change; (d) on the hash-pinned production and belief
packages, the served bot with ``dtrx``, ``lgf`` and ``lgfx`` decides exactly as
without the switch, alone or with the prefix encoding (cards, record, sampler
state and the value evaluator's counters), at every card count of two seeded
rounds.  Package tests fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1``.
"""
import copy
from itertools import islice

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.train import pv_search_policy as pv
from shengji.train import pv_tree_search as tree
from shengji.train.policy_value_search import PolicyValueBot
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_pv_admission_rules import names, predict, production_package  # noqa: F401
from test_pv_doomed_throw_reselect import HashNoiseEvaluator, throw_loving_scores
from test_pv_leaf_greedy_finish import LEAF_KEYS, LGF_ENV, R46_RULES, leaf_bot
from test_pv_search_serving import _play_state
from test_pv_small_joker_lead import _fresh_round
from test_release46_fly_config import PACKAGE_SHA, fly_env, pinned_belief_package  # noqa: F401

STREAM = "SHENGJI_PV_LEAF_GREEDY_STREAM"
PREFIX = "SHENGJI_PV_ENCODE_PREFIX_CACHE"
#: a heuristic-played round whose first trick has a capped (4000) follow listing
CAPPED_SEED = 707_014


class _Cap:
    cap = 4000


def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds") and not k.endswith("_ms")}


def _listing_states(seed):
    """Every (state, seat to act) of a heuristic-played round."""
    rnd = _fresh_round(seed)
    helper = HeuristicBot()
    while rnd.phase == "play":
        yield copy.deepcopy(rnd), rnd.turn
        rnd.play(rnd.turn, helper.decide_play(rnd, rnd.turn))


# --------------------------------------------- (a) the compact listing

def test_the_compact_listing_is_legal_replies_byte_for_byte():
    rng = np.random.default_rng(7)
    sizes, leads = [], 0
    for seed in (CAPPED_SEED, 707_001):
        for rnd, seat in _listing_states(seed):
            legal, dense = tree.legal_replies(_Cap, rnd, seat, None)
            slot = tree._DenseSlot()
            cache = {}
            compact, lazy = tree.legal_replies_compact(_Cap, rnd, seat, cache, slot)
            assert tree.legal_replies_compact(_Cap, rnd, seat, cache, slot)[0] is compact
            if dense is None:
                assert lazy is None and compact == legal and len(legal) == 1
                continue
            assert len(compact) == len(legal)
            assert [compact[i] for i in range(len(compact))] == legal
            rebuilt = compact.multiplicity()
            assert rebuilt.dtype == dense.dtype and rebuilt.tobytes() == dense.tobytes()
            row = rng.normal(size=dense.shape[1])
            assert (lazy @ row).tobytes() == (dense @ row).tobytes()
            sizes.append(len(legal))
            leads += not rnd.trick.plays
    assert max(sizes) == 4000 and leads > 0


def test_the_ply_keeps_one_materialized_matrix():
    rnd, seat = next((r, s) for r, s in _listing_states(CAPPED_SEED) if r.trick.plays
                     and len(tree.legal_replies(_Cap, r, s, None)[0]) == 4000)
    other, other_seat = next((r, s) for r, s in _listing_states(707_001) if r.trick.plays
                             and len(tree.legal_replies(_Cap, r, s, None)[0]) > 1)
    slot = tree._DenseSlot()
    _, big = tree.legal_replies_compact(_Cap, rnd, seat, {}, slot)
    _, small = tree.legal_replies_compact(_Cap, other, other_seat, {}, slot)
    row = np.ones(54)
    big @ row
    held = slot.dense
    assert slot.owner is big and held.shape == (4000, 54)
    big @ row
    assert slot.dense is held                       # the same key reuses it
    small @ row
    assert slot.owner is small and slot.dense.shape[0] < 4000
    # the compact form is a small fraction of the listing it replaces
    compact, _ = tree.legal_replies_compact(_Cap, rnd, seat, {}, tree._DenseSlot())
    assert compact.cards.nbytes + compact.offsets.nbytes < held.nbytes // 20


# ---------------------------------- (b) package-free paired seeded rounds

def _stream(bot):
    bot.leaf_greedy_stream = True
    return bot


def test_the_switched_bot_is_the_plain_lgf_bot_over_seeded_rounds():
    evaluator = HashNoiseEvaluator()
    decisions = applied = capped = 0
    for seed in (CAPPED_SEED, 707_001):
        rnd = _fresh_round(seed)
        plain = [leaf_bot(evaluator, worlds=8, seed=100 + s, **R46_RULES) for s in range(4)]
        switched = [_stream(leaf_bot(evaluator, worlds=8, seed=100 + s, **R46_RULES))
                    for s in range(4)]
        for bot in plain + switched:
            bot.scores = throw_loving_scores
        while rnd.phase == "play":
            seat = rnd.turn
            capped += bool(rnd.trick.plays) and sum(1 for _ in islice(tree.iter_follow_actions(
                list(rnd.hands[seat]), rnd.trick.plays[0].cards, rnd.ordering), 4000)) == 4000
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            b = switched[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain[seat].last_decision_record, switched[seat].last_decision_record
            assert a == b and _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
            assert LEAF_KEYS <= set(rb)
            assert plain[seat].sampler.rng.getstate() == switched[seat].sampler.rng.getstate()
            assert plain[seat]._leaf_greedy["stats"] == switched[seat]._leaf_greedy["stats"]
            decisions += 1
            applied += bool(ra["leaf_greedy_finish_applied"])
            rnd.play(seat, a)
    print(f"\nlgfs parity: decisions={decisions} applied={applied} capped_follows={capped}")
    assert decisions >= 80 and applied > 20 and capped > 0


def test_the_harness_bot_reads_the_switch_too():
    rnd = _fresh_round(CAPPED_SEED)
    seat = rnd.turn
    world = ([list(h) for h in rnd.hands], list(rnd.buried))
    actions = [sorted(HeuristicBot().decide_play(copy.deepcopy(rnd), seat))]
    out = []
    for stream in (False, True):
        bot = PolicyValueBot(predict, evaluator=HashNoiseEvaluator(), worlds=2, cap=4000,
                             seed=17, leaf_greedy_finish=True)
        if stream:
            bot.leaf_greedy_stream = True
        bot._greedy_prefill(rnd, seat, actions, [world])
        leaf = bot._leaf_greedy["cache"][(tuple(actions[0]), 0)]
        out.append(([[(p.seat, list(p.cards)) for p in t.plays] for t in leaf.history],
                    bot._leaf_greedy["stats"]))
    assert out[0] == out[1] and out[0][1]["tree_reply_plays"] > 0


# --------------------------------------------------- (c) the switch itself

def test_the_switch_is_off_by_default_and_enters_no_name(production_package):  # noqa: F811
    assert PolicyValueBot.leaf_greedy_stream is False
    assert pv.LATENCY_SWITCH_ENV["leaf_greedy_stream"] == STREAM
    assert pv.latency_switches({})["leaf_greedy_stream"] is False
    assert pv.latency_switches({STREAM: "1"})["leaf_greedy_stream"] is True
    assert pv.latency_switches({STREAM: ""})["leaf_greedy_stream"] is False
    for bad in ("2", "true", "on"):
        with pytest.raises(pv.PVSearchPolicyError, match=STREAM):
            pv.latency_switches({STREAM: bad})
    with pytest.raises(pv.PVSearchPolicyError, match=STREAM):
        pv.pv_env_recipe({**LGF_ENV, STREAM: "2"})        # refused before any bot is built
    lgf, = names(LGF_ENV)
    for raw in ("1", "0", ""):
        assert names({**LGF_ENV, STREAM: raw}) == [lgf]
    assert "leaf_greedy_stream" not in pv.pv_env_recipe({**LGF_ENV, STREAM: "1"})


# ------------------------------- (d) the served bot on the pinned packages

def _counters(ev):
    return (ev.calls, ev.positions, ev.model_rows, ev.terminal_rows, ev.forward_calls)


def _build(monkeypatch, factory, switches):
    for name in (STREAM, PREFIX):
        monkeypatch.delenv(name, raising=False)
    for name in switches:
        monkeypatch.setenv(name, "1")
    bot = factory(seed=17)
    for name in (STREAM, PREFIX):
        monkeypatch.delenv(name, raising=False)
    return bot


@pytest.mark.parametrize("switches", [(STREAM,), (STREAM, PREFIX)], ids=["stream", "stream+prefix"])
def test_the_switched_r47_lgf_bot_decides_exactly_as_the_plain_one(
        monkeypatch, pinned_production_package, pinned_belief_package, switches):  # noqa: F811
    """Release 46 + ``dtrx`` + ``lgf`` + ``lgfx`` from ``fly.toml`` (budget lifted
    so the host's speed cannot decide); every fourth play decision of two
    seeded heuristic-played rounds, and every decision of their first trick."""
    env = {**fly_env(), "SHENGJI_PV_CKPT": str(pinned_production_package),
           "SHENGJI_PV_SHA256": PACKAGE_SHA, "SHENGJI_PV_BELIEF_CKPT": str(pinned_belief_package),
           "SHENGJI_PV_SERVING_BUDGET_SECONDS": "600",
           "SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD": "1",
           "SHENGJI_PV_LEAF_GREEDY_FINISH": "1", "SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP": "1"}
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    (name, factory), = entries.items()
    assert "-dtrx-" in name and "-lgf-lgfx-" in name
    plain = _build(monkeypatch, factory, ())
    switched = _build(monkeypatch, factory, switches)
    assert vars(switched)["leaf_greedy_stream"] is True and "leaf_greedy_stream" not in vars(plain)
    assert switched.encode_prefix_cache == (PREFIX in switches)
    helper = HeuristicBot()
    decisions = applied = 0
    card_counts = set()
    for seed in (17, 23):
        rnd = _play_state(seed)
        step = 0
        while rnd.phase == "play":
            seat = rnd.turn
            if step % 4 == 0 or not rnd.history:
                card_counts.add(len(rnd.hands[seat]))
                before = _counters(plain.evaluator)
                a = plain.decide_play(copy.deepcopy(rnd), seat)
                delta_plain = [x - y for x, y in zip(_counters(plain.evaluator), before)]
                before = _counters(switched.evaluator)
                b = switched.decide_play(copy.deepcopy(rnd), seat)
                delta_switched = [x - y for x, y in zip(_counters(switched.evaluator), before)]
                ra, rb = plain.last_decision_record, switched.last_decision_record
                assert a == b, (seed, len(rnd.history))
                assert _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
                assert plain.sampler.rng.getstate() == switched.sampler.rng.getstate()
                assert delta_plain == delta_switched
                decisions += 1
                applied += bool(ra.get("leaf_greedy_finish_applied"))
            rnd.play(seat, helper.decide_play(rnd, seat))
            step += 1
    print(f"\nr47 lgf {'+'.join(switches)}: decisions={decisions} applied={applied} "
          f"cards={sorted(card_counts)}")
    assert decisions >= 40 and applied >= 10 and len(card_counts) >= 15
