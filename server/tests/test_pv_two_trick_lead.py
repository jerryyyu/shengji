"""The two-trick value leaf at a lead (``two_trick_lead``, ``tt2``), OFF BY DEFAULT.

With ``SHENGJI_PV_TT2=1`` every value pass of a lead decision prices the served
first-trick leaves' copies after the policy head has played the next trick
(`pv_two_trick`).  Off, release 50's name and decisions are main's on the ten
fixed production positions (`r50_flag_positions`).  On, the value consumer sees
end-of-trick-2 positions; the points tie-break, the exact stages and the
greedy finish's cache keep the first-trick leaves; a pass that reaches the
rule's deadline returns its first-trick sums exactly; a leaf whose round ended
in the first trick is priced as it stands; and copies never touch the leaves
they were made from.

Correctness and identity witnesses only, not a strength or latency claim.
"""
import json
import time

import numpy as np
import pytest

import r50_flag_positions as P
from shengji.train import pv_encode_prefix
from shengji.train import pv_search_policy as pv
from shengji.train import pv_two_trick as tt2
from test_r50_flag_off_parity import assert_decision
from test_release50_fly_config import fly_env  # release 50's env, lcc32 on
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA,  # noqa: F401
                                       PRIOR_VOLUME_PATH, RELEASE50, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages, served_bot)

PINS = json.loads(P.PINNED.read_text())
FLAG = "SHENGJI_PV_TT2"
CAP = "SHENGJI_PV_TT2_MAX_SECONDS"
#: release 50 with the rule on at its default cap
TT250 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-"
         "vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-tt2-r550ed7f3-bury-hybrid-bwv-"
         "bbw-cc736d06ab08-sc8")
#: a mid-game lead the exact stages do not reach (ten cards in hand)
MIDGAME_LEAD = ("SDUS2", 8, 0)
#: a lead the exact lead stage decides
EXACT_LEAD = ("ADKY3", 12, 0)
#: the last trick's lead: every leaf's round ends in its first trick
LAST_LEAD = ("WJLB2", 19, 0)
#: the positions where the acting seat follows
FOLLOWS = tuple(p for p in P.POSITIONS if p[2] > 0)


def names(monkeypatch, extra):
    from shengji.ai import cwv_policy

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    return list(pv.singleton_registry_entries(**pv.pv_env_recipe({**fly_env(), **extra})))


def on_bot(packages, monkeypatch, extra=None):
    name, bot = served_bot(packages, monkeypatch,
                           env={**fly_env(), FLAG: "1", "SHENGJI_BOT": TT250, **(extra or {})},
                           seed=P.SEED)
    assert name == bot.policy_name == TT250 and bot.two_trick_lead is True
    return P.lift(bot)


def setup_pass(bot, position, k=4, w=6):
    """A lead root, ``k`` of its legal actions, ``w`` of its sampled worlds, and
    the rule's state armed for a decision that started now."""
    rnd = P.replay(*position)
    seat = rnd.turn
    actions = [list(a) for a in bot._legal(rnd, seat, []).actions][:k]
    worlds, _ = bot._worlds(rnd, seat)
    worlds = list(worlds[:w])
    # the served value pass finishes every leaf first (the greedy finish's own
    # value calls happen here, outside the spied pass)
    bot._greedy_prefill(rnd, seat, actions, worlds)
    bot._two_trick = bot._two_trick_state(rnd, time.perf_counter())
    assert bot._two_trick["active"] and bot._two_trick["lead"]
    return rnd, seat, actions, worlds


class ValueSpy:
    """Every batch of positions the value head scores, with the scores it
    returned, on the prefix path and the plain path alike."""

    def __init__(self, bot, monkeypatch):
        self.calls = []
        original_prefix = pv_encode_prefix.score_leaves
        original_plain = bot.evaluator.score

        def prefix(evaluator, positions, seat, pre, *args, **kwargs):
            out = original_prefix(evaluator, positions, seat, pre, *args, **kwargs)
            self.calls.append((list(positions), np.asarray(out, dtype=np.float64).copy()))
            return out

        def plain(positions, seat):
            out = original_plain(positions, seat)
            self.calls.append((list(positions), np.asarray(out, dtype=np.float64).copy()))
            return out

        monkeypatch.setattr(pv_encode_prefix, "score_leaves", prefix)
        monkeypatch.setattr(bot.evaluator, "score", plain)

    def positions(self):
        return [p for batch, _ in self.calls for p in batch]

    def scores(self):
        return np.concatenate([s for _, s in self.calls]) if self.calls else np.zeros(0)


def content(leaf):
    """``leaf``'s position by value: its hands, kitty, tricks and turn."""
    return (tuple(tuple(h) for h in leaf.hands), tuple(leaf.buried), leaf.phase, leaf.turn,
            tuple((t.winner, t.points, tuple((p.seat, tuple(p.cards)) for p in t.plays))
                  for t in leaf.history),
            None if leaf.trick is None else tuple((p.seat, tuple(p.cards)) for p in leaf.trick.plays),
            leaf.attacker_points)


def snapshot(leaf):
    return (tuple(tuple(h) for h in leaf.hands), tuple(leaf.buried), len(leaf.history),
            tuple(id(t) for t in leaf.history), leaf.phase, leaf.turn,
            None if leaf.trick is None else tuple((p.seat, tuple(p.cards)) for p in leaf.trick.plays),
            leaf.attacker_points)


# -- recipe, name and env ------------------------------------------------------


def test_recipe_carries_the_rule_only_when_on():
    base = dict(checkpoint_sha256="f" * 64)
    off = pv.recipe_payload(pv.PVSearchConfig(**base))
    assert not {"two_trick_lead", "two_trick_max_seconds"} & set(off)
    on = pv.recipe_payload(pv.PVSearchConfig(**base, two_trick_lead=True))
    assert on == {**off, "two_trick_lead": {"rule": tt2.TT2_RULE_ID, "max_seconds": 5.0,
                                            "budget_fraction": tt2.TT2_BUDGET_FRACTION}}
    capped = pv.recipe_payload(pv.PVSearchConfig(**base, two_trick_lead=True,
                                                 two_trick_max_seconds=2.5))
    assert capped["two_trick_lead"]["max_seconds"] == 2.5
    assert pv.recipe_digest(pv.PVSearchConfig(**base)) != pv.recipe_digest(
        pv.PVSearchConfig(**base, two_trick_lead=True))
    with pytest.raises(pv.PVSearchPolicyError, match="needs two_trick_lead"):
        pv.recipe_payload(pv.PVSearchConfig(**base, two_trick_max_seconds=2.5))
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(**base, two_trick_lead=1))
    for bad in (0.0, -1.0, float("nan"), float("inf"), True, "5"):
        with pytest.raises(pv.PVSearchPolicyError, match="two_trick_max_seconds must be"):
            pv.recipe_payload(pv.PVSearchConfig(**base, two_trick_lead=True,
                                                two_trick_max_seconds=bad))
    from shengji.train.pv_tree_config import PVTreeConfig
    with pytest.raises(pv.PVSearchPolicyError, match="does not combine with the tree"):
        pv._check_two_trick(pv.PVSearchConfig(**base, two_trick_lead=True,
                                              tree=PVTreeConfig(sims=8)))
    assert "two_trick_lead" not in pv.RULE_FLAGS.values()
    assert pv.PVSearchBot.two_trick_lead is False and pv.PVSearchBot._two_trick is None


def test_served_name_gains_tt2_only_when_on(monkeypatch):
    for off in ({}, {FLAG: "0"}, {FLAG: ""}, {FLAG: "0", CAP: ""}):
        assert names(monkeypatch, off) == [RELEASE50]
    assert names(monkeypatch, {FLAG: "1"}) == [TT250]
    assert names(monkeypatch, {FLAG: "1", CAP: "5"}) == [TT250]
    capped, = names(monkeypatch, {FLAG: "1", CAP: "2.5"})
    assert "-lcc32-tt2-tt2s2500-r" in capped and capped != TT250
    with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_TT2=1"):
        names(monkeypatch, {CAP: "2.5"})
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        names(monkeypatch, {FLAG: "yes"})
    with pytest.raises(pv.PVSearchPolicyError, match="is not a number"):
        names(monkeypatch, {FLAG: "1", CAP: "soon"})
    with pytest.raises(pv.PVSearchPolicyError, match="two_trick_max_seconds must be"):
        names(monkeypatch, {FLAG: "1", CAP: "0"})


# -- flag off: main's decisions --------------------------------------------------


@pytest.mark.parametrize("key,trick,pos", P.POSITIONS, ids=[P.label(*p) for p in P.POSITIONS])
def test_flag_off_at_zero_decides_as_main(release50_packages, monkeypatch, key, trick, pos):
    name, bot = served_bot(release50_packages, monkeypatch, env={**fly_env(), FLAG: "0"},
                           seed=P.SEED)
    assert name == bot.policy_name == RELEASE50
    assert "two_trick_lead" not in vars(bot) and bot._two_trick is None
    got = P.decision(P.lift(bot), P.replay(key, trick, pos))
    assert_decision(got, PINS["decisions"][P.label(key, trick, pos)])
    assert not any(k.startswith("tt2_") for k in bot.last_decision_record)


@pytest.mark.parametrize("key,trick,pos", FOLLOWS, ids=[P.label(*p) for p in FOLLOWS])
def test_flag_on_follow_plays_mains_cards_on_mains_worlds(release50_packages, monkeypatch,
                                                         key, trick, pos):
    bot = on_bot(release50_packages, monkeypatch)
    got = P.decision(bot, P.replay(key, trick, pos))
    pinned = PINS["decisions"][P.label(key, trick, pos)]
    assert (got["cards"], got["worlds"]) == (pinned["cards"], pinned["worlds"])
    record = bot.last_decision_record
    assert record["tt2_lead"] is False and record["tt2_passes"] == 0
    assert record["tt2_policy_rows"] == 0


# -- flag on: what the value head prices -------------------------------------------


def test_value_consumer_sees_end_of_trick_two(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    rnd, seat, actions, worlds = setup_pass(bot, MIDGAME_LEAD)
    root = len(rnd.history)
    spy = ValueSpy(bot, monkeypatch)
    capture = np.full((len(worlds), len(actions)), np.nan)
    sums, batches = bot._score_leaves(rnd, seat, actions, worlds, capture=capture)
    cells = len(worlds) * len(actions)
    seen = spy.positions()
    assert len(seen) == 2 * cells          # the first-trick pass, then the second
    first, second = seen[:cells], seen[cells:]
    assert {len(p.history) for p in first} == {root + 1}
    assert {len(p.history) for p in second} == {root + 2}
    assert all(p.phase == "play" and not p.trick.plays for p in second)
    assert not {id(p) for p in first} & {id(p) for p in second}
    # the sums and the captured cells are the second pass's scores, in its order
    scores = spy.scores()[cells:]
    assert capture.ravel().tolist() == scores.tolist()
    expected = np.zeros(len(actions))
    np.add.at(expected, [i for _ in worlds for i in range(len(actions))], scores)
    assert sums.tolist() == expected.tolist()
    # each copy is its served leaf followed by one trick the policy played
    for a, b in zip(first, second):
        assert b.history[:root + 1] == a.history[:root + 1]
        assert b.history[root].plays is a.history[root].plays
        played = sum(len(p.cards) for p in b.history[root + 1].plays)
        assert played == sum(map(len, a.hands)) - sum(map(len, b.hands)) > 0
        assert len(b.history[root + 1].plays) == 4
    state = bot._two_trick
    assert (state["passes"], state["fallbacks"], state["leaves"]) == (1, 0, cells)
    assert state["policy_rows"] > 0 and batches >= 2


def test_tiebreak_and_exact_consumers_keep_the_first_trick(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    rnd, seat, actions, worlds = setup_pass(bot, MIDGAME_LEAD)
    root = len(rnd.history)
    bot._greedy_prefill(rnd, seat, actions, worlds)
    cached = {key: (leaf, snapshot(leaf)) for key, leaf in bot._leaf_greedy["cache"].items()}
    bot._score_leaves(rnd, seat, actions, worlds)
    for (action, world_index), (leaf, before) in cached.items():
        assert bot._leaf_greedy["cache"][(action, world_index)] is leaf
        assert snapshot(leaf) == before and len(leaf.history) == root + 1
    for world_index, (hands, buried) in enumerate(worlds):
        for action in actions:
            leaf = bot._scored_leaf(rnd, seat, hands, buried, action, world_index)
            points = bot._trick_points(rnd, seat, hands, buried, action, world_index)
            trick = leaf.history[root]
            ours = rnd.is_attacker(trick.winner) == rnd.is_attacker(seat)
            assert points == (trick.points if ours else -trick.points)
            assert len(bot._leaf(rnd, seat, hands, buried, action, world_index).history) == root + 1


def test_rule_never_replaces_the_shared_leaf_builders(release50_packages, monkeypatch):
    """The failure this rule's design avoids: a second trick played inside
    `_leaf` / `_greedy_finish` / `_scored_leaf` reaches the tie-break and the
    exact stages.  While the second trick is being played, and after the whole
    decision, every shared builder still returns a first-trick leaf."""
    bot = on_bot(release50_packages, monkeypatch)
    rnd = P.replay(*EXACT_LEAD)
    seat, root = rnd.turn, len(rnd.history)
    hands, buried = [list(h) for h in rnd.hands], list(rnd.buried)
    probe = list(bot._legal(rnd, seat, []).actions[0])
    original_play = tt2.play_next_trick
    checked = []

    def play_and_check(*args, **kwargs):
        out = original_play(*args, **kwargs)
        for builder in (bot._leaf, bot._scored_leaf):
            assert len(builder(rnd, seat, hands, buried, probe, 0).history) == root + 1
        assert type(bot._trick_points(rnd, seat, hands, buried, probe, 0)) is int
        checked.append(True)
        return out

    monkeypatch.setattr(tt2, "play_next_trick", play_and_check)
    exact_leaves = []
    original_leaf = bot._leaf

    def leaf(*args):
        out = original_leaf(*args)
        exact_leaves.append(len(out.history))
        return out

    bot._leaf = leaf
    bot.decide_play(rnd, seat)
    del bot._leaf
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and record["exact_lead_status"] == "complete"
    assert record["tt2_lead"] and record["tt2_passes"] >= 1 and checked
    assert exact_leaves and set(exact_leaves) == {root + 1}
    for name in ("_leaf", "_greedy_finish", "_scored_leaf", "_score_leaves", "_trick_points"):
        assert name not in vars(bot)
    assert type(bot)._score_leaves is pv.PVSearchBot._score_leaves


def test_cap_fallback_returns_the_first_trick_sums_exactly(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    rnd, seat, actions, worlds = setup_pass(bot, MIDGAME_LEAD)
    plain_capture = np.full((len(worlds), len(actions)), np.nan)
    plain = bot._score_leaves(rnd, seat, actions, worlds, capture=plain_capture,
                              leaf=bot._scored_leaf)
    bot._two_trick["deadline"] = time.perf_counter() - 1.0
    capture = np.full((len(worlds), len(actions)), np.nan)
    sums, batches = bot._score_leaves(rnd, seat, actions, worlds, capture=capture)
    assert sums.tolist() == plain[0].tolist() and batches == plain[1]
    assert capture.tolist() == plain_capture.tolist()
    state = bot._two_trick
    assert state["expired"] and (state["passes"], state["fallbacks"]) == (0, 1)
    # every later pass of the decision is priced on the first trick as well
    again = bot._score_leaves(rnd, seat, actions, worlds)
    assert again[0].tolist() == plain[0].tolist() and state["fallbacks"] == 2
    assert tt2.record(state)["tt2_fallback"] is True


def test_cap_fallback_decision_is_the_flag_off_decision(release50_packages, monkeypatch):
    rnd = P.replay(*MIDGAME_LEAD)
    off_name, off = served_bot(release50_packages, monkeypatch, seed=P.SEED)
    off_cards = sorted(P.lift(off).decide_play(rnd, rnd.turn))
    off_record = off.last_decision_record
    bot = on_bot(release50_packages, monkeypatch)
    bot.two_trick_max_seconds = 1e-9
    on_cards = sorted(bot.decide_play(P.replay(*MIDGAME_LEAD), rnd.turn))
    record = bot.last_decision_record
    assert record["tt2_lead"] and record["tt2_fallback"] and record["tt2_passes"] == 0
    assert record["tt2_fallbacks"] >= 1 and on_cards == off_cards

    def same(r):
        r = P._canonical(r)
        return {k: v for k, v in r.items() if not k.startswith("tt2_") and k != "policy"}
    assert same(record) == same(off_record)


def test_round_end_leaves_pass_through_unchanged(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    rnd, seat, actions, worlds = setup_pass(bot, LAST_LEAD)
    assert all(len(h) == 1 for h in rnd.hands) and len(actions) == 1
    plain = bot._score_leaves(rnd, seat, actions, worlds, leaf=bot._scored_leaf)
    spy = ValueSpy(bot, monkeypatch)
    sums, _ = bot._score_leaves(rnd, seat, actions, worlds)
    seen = spy.positions()
    cells = len(worlds)
    assert all(p.phase == "round_end" for p in seen)
    assert [id(p) for p in seen[:cells]] == [id(p) for p in seen[cells:]]
    assert sums.tolist() == plain[0].tolist()
    state = bot._two_trick
    assert (state["round_end"], state["leaves"], state["policy_rows"]) == (cells, 0, 0)


def test_copies_never_mutate_shared_or_aliased_leaves(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    rnd, seat, actions, worlds = setup_pass(bot, MIDGAME_LEAD, k=3, w=3)
    root = len(rnd.history)
    served = {}

    def aliased(root_, actor, hands, buried, action, world_index):
        # every action of a world shares the first action's leaf object
        key = world_index
        if key not in served:
            leaf = pv.PVSearchBot._scored_leaf(bot, root_, actor, hands, buried, action,
                                               world_index)
            served[key] = (leaf, snapshot(leaf))
        return served[key][0]

    monkeypatch.setattr(bot, "_scored_leaf", aliased)
    spy = ValueSpy(bot, monkeypatch)
    capture = np.full((len(worlds), len(actions)), np.nan)
    bot._score_leaves(rnd, seat, actions, worlds, capture=capture)
    for leaf, before in served.values():
        assert snapshot(leaf) == before and len(leaf.history) == root + 1
    cells = len(worlds) * len(actions)
    second = spy.positions()[cells:]
    # one copy per distinct served leaf, shared by its aliases, priced alike
    assert len({id(p) for p in second}) == len(served) == len(worlds)
    assert not {id(p) for p in second} & {id(leaf) for leaf, _ in served.values()}
    for row in capture:
        # the same copy batched at different rows may differ in the last bit
        np.testing.assert_allclose(row, np.full(row.shape, row[0]), rtol=1e-12, atol=1e-12)
    assert bot._two_trick["leaves"] == len(served)


def test_leaf_copy_is_distinct_and_equal(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    rnd, seat, actions, worlds = setup_pass(bot, MIDGAME_LEAD, k=1, w=1)
    hands, buried = worlds[0]
    leaf = bot._scored_leaf(rnd, seat, hands, buried, actions[0], 0)
    before = snapshot(leaf)
    copy = tt2.leaf_copy(leaf)
    assert copy is not leaf and snapshot(copy) == before
    for attribute in ("hands", "buried", "trick", "history"):
        assert getattr(copy, attribute) is not getattr(leaf, attribute)
    assert all(a is not b for a, b in zip(copy.hands, leaf.hands))
    assert content(copy) == content(leaf)
    tt2.play_next_trick(bot, [copy], len(rnd.history) + 2)
    assert snapshot(leaf) == before and len(copy.history) == len(rnd.history) + 2


def test_prefix_rows_play_the_reference_rows_tricks(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    assert bot.encode_prefix_cache
    rnd, seat, actions, worlds = setup_pass(bot, MIDGAME_LEAD)
    leaves = [bot._scored_leaf(rnd, seat, hands, buried, action, wi)
              for wi, (hands, buried) in enumerate(worlds) for action in actions]
    prefix = pv_encode_prefix.HistoryPrefix.of(rnd, batched=bot.encode_batch_fast,
                                               native=bot.encode_native)
    target = len(rnd.history) + 2
    fast = [tt2.leaf_copy(leaf) for leaf in leaves]
    reference = [tt2.leaf_copy(leaf) for leaf in leaves]
    assert tt2.play_next_trick(bot, fast, target, prefix=prefix) == \
        tt2.play_next_trick(bot, reference, target)
    assert [content(a) for a in fast] == [content(b) for b in reference]
    assert all(len(a.history) == target for a in fast if a.phase == "play")


def test_state_is_inactive_outside_a_lead_search(release50_packages, monkeypatch):
    bot = on_bot(release50_packages, monkeypatch)
    rnd = P.replay(*MIDGAME_LEAD)
    bot.decide_play(rnd, rnd.turn)
    assert bot._two_trick is not None and bot._two_trick["active"] is False
    rnd, seat, actions, worlds = setup_pass(bot, MIDGAME_LEAD, k=2, w=2)
    bot._two_trick["active"] = False
    spy = ValueSpy(bot, monkeypatch)
    bot._score_leaves(rnd, seat, actions, worlds)
    assert len(spy.positions()) == 4 and {len(p.history) for p in spy.positions()} == \
        {len(rnd.history) + 1}
    # the allowance is the cap, clamped to the serving budget's share
    bot.serving_budget_seconds = 3.0
    state = bot._two_trick_state(rnd, 100.0)
    assert state["allowance"] == pytest.approx(2.4) and state["deadline"] == pytest.approx(102.4)
    bot.serving_budget_seconds = None
    assert bot._two_trick_state(rnd, 100.0)["allowance"] == 5.0
    follow = P.replay(*FOLLOWS[0])
    assert bot._two_trick_state(follow, 100.0)["active"] is False
