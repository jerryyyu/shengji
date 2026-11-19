"""The greedy finish's compiled reply children (`pv_tree_search.reply_children_fast`,
`train/_reply_fast`).

Torch-free and package-free.  (a) Over seeded rounds, every follow clone the
served finish builds (`afterstate_fast`, with and without the seeded trick
caches) gives, for its candidate list, the children
``child_position_fast`` + ``finish_current_trick`` give: every attribute in
the same order, the trick and its caches, the history, the objects shared with
the parent; the compiled builder ran.  (b) Without the compiled module the
reference runs and gives the same children.  (c) The compiled builder is
declined when a reference it stands for is replaced, when `Round` takes a
``__setattr__`` or a data descriptor, and per clone when the clone copies off
the default protocol or holds its own ``play``.  (d) `greedy_finish_current_trick`
passes the builder only with ``fast_clone`` and intact references.  (e) Paired
``lgf`` bots with every native switch on decide identically with the module
present and absent (cards, record, sampler state, the finish's counters, the
evaluator's counters), the builder taking every reply ply.
"""
import copy

import pytest

from shengji.ai.cwv_policy import finish_current_trick
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.round import Round
from shengji.harvest.legal import enumerate_legal
from shengji.train import pv_tree_search as pts
from native_switches import NATIVE_OFF
from test_pv_encode_batch_fast import _comparable, lgf_bot
from test_pv_encode_prefix import counters
from test_pv_lgf_reply_prefix import CAPPED_SEED
from test_pv_small_joker_lead import _fresh_round

needs_module = pytest.mark.skipif(pts._reply_fast is None,
                                  reason="train/_reply_fast is not built")


def _trick(trick):
    if trick is None:
        return None
    return (type(trick), list(vars(trick)), trick.leader,
            [(type(p), p.seat, list(p.cards)) for p in trick.plays], trick.winner, trick.points,
            trick.incumbent, trick.running_points)


def _state(rnd):
    """Every attribute in order; tricks (the open one, the history, the last)
    with their caches spelled out."""
    out = []
    for key, value in vars(rnd).items():
        if key == "trick" or key == "last_trick":
            value = _trick(value)
        elif key == "history":
            value = [_trick(t) for t in value]
        out.append((key, value))
    return type(rnd), out


def _sharing(child, parent):
    return sorted(k for k in vars(child) if vars(child)[k] is vars(parent).get(k))


def _reference(clone, seat, candidates):
    out = []
    for candidate in candidates:
        child = pts.child_position_fast(clone, seat, candidate)
        finish_current_trick(child)
        out.append(child)
    return out


def _follow_clones(seeds, seeded):
    """``(clone, seat, candidates)``: trusted clones of seeded heuristic rounds
    (the served finish's `afterstate_fast`), each with an open trick, and up
    to six of the acting seat's legal plays plus the heuristic's."""
    helper = HeuristicBot()
    for seed in seeds:
        rnd = _fresh_round(seed)
        while rnd.phase == "play":
            seat = rnd.turn
            hands, buried = [list(h) for h in rnd.hands], list(rnd.buried)
            for action in enumerate_legal(rnd, seat, cap=3).actions[:3]:
                clone = pts.afterstate_fast(rnd, seat, hands, buried, list(action))
                if clone.phase != "play" or not clone.trick.plays:
                    continue
                if seeded:
                    pts.seed_trick_caches(clone)
                turn = clone.turn
                candidates = [list(a) for a in enumerate_legal(clone, turn, cap=6).actions[:6]]
                follow = sorted(helper.decide_play(clone, turn))
                if follow not in candidates:
                    candidates.append(follow)
                yield clone, turn, candidates
            rnd.play(seat, helper.decide_play(rnd, seat))


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = pts._reply_fast

    class Spy:
        @staticmethod
        def reply_children(*args):
            calls.append(len(args[2]))
            return real.reply_children(*args)
    monkeypatch.setattr(pts, "_reply_fast", Spy())
    return calls


# ------------------------------------------------- (a) the same children

@needs_module
@pytest.mark.parametrize("seeded", [False, True])
def test_the_compiled_children_are_the_reference_children(spy, seeded):
    assert pts.reply_children_intact()
    checked = 0
    for clone, seat, candidates in _follow_clones((707_001, 707_002, 707_003), seeded):
        before = _state(clone)
        want = _reference(clone, seat, candidates)
        got = pts.reply_children_fast(clone, seat, candidates)
        assert _state(clone) == before
        assert len(got) == len(want) == len(candidates)
        for a, b in zip(want, got):
            assert _state(a) == _state(b)
            assert _sharing(a, clone) == _sharing(b, clone)
        assert len({id(c) for c in got}) == len(got)
        assert len({id(c.hands) for c in got}) == len(got)
        checked += len(got)
    assert checked > 2000 and sum(spy) == checked


# ------------------------------------------------- (b) without the module

def test_without_the_compiled_module_the_reference_builds_them(monkeypatch):
    monkeypatch.setattr(pts, "_reply_fast", None)
    assert not pts.reply_children_intact()
    checked = 0
    for clone, seat, candidates in _follow_clones((707_004,), True):
        want = _reference(clone, seat, candidates)
        got = pts.reply_children_fast(clone, seat, candidates)
        assert [_state(c) for c in got] == [_state(c) for c in want]
        checked += len(got)
    assert checked > 500


# ------------------------------------------------- (c) declines

def _one_clone():
    return next(_follow_clones((707_001,), True))


@needs_module
def test_a_replaced_reference_declines_the_compiled_builder(monkeypatch):
    assert pts.reply_children_intact()
    for name in ("finish_current_trick", "child_position_fast", "shallow_round",
                 "default_finisher"):
        with monkeypatch.context() as m:
            real = getattr(pts, name)
            m.setattr(pts, name, lambda *a, _real=real: _real(*a))
            assert not pts.reply_children_intact(), name
    assert pts.reply_children_intact()


@needs_module
def test_a_round_setattr_or_data_descriptor_declines_the_compiled_builder(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(Round, "__setattr__", lambda self, k, v: object.__setattr__(self, k, v),
                  raising=False)
        assert not pts.reply_children_intact()
    with monkeypatch.context() as m:
        m.setattr(Round, "message", property(lambda self: None, lambda self, v: None),
                  raising=False)
        assert not pts.reply_children_intact()
    assert pts.reply_children_intact()


@needs_module
def test_a_clone_off_the_default_protocol_or_with_its_own_play_takes_the_reference(spy):
    clone, seat, candidates = _one_clone()

    class Called(Exception):
        pass

    def own_play(*args):
        raise Called
    own = copy.copy(clone)
    own.play = own_play
    with pytest.raises(Called):        # the reference: the child plays through its own ``play``
        pts.reply_children_fast(own, seat, candidates)
    assert spy == []

    class Other(Round):
        pass
    other = Other.__new__(Other)
    other.__dict__.update(vars(clone))
    got = pts.reply_children_fast(other, seat, candidates)
    assert spy == [] and all(type(c) is Other for c in got)
    assert pts.reply_children_fast(clone, seat, candidates) and spy == [len(candidates)]


# ------------------------------------------------- (d) selection

@needs_module
@pytest.mark.parametrize("fast_clone", [False, True])
def test_the_finish_passes_the_builder_only_with_fast_clones(monkeypatch, fast_clone):
    seen = []
    real = pts.greedy_reply_ply

    def ply(*args, **kw):
        seen.append(kw.get("children_fn"))
        return real(*args, **kw)
    monkeypatch.setattr(pts, "greedy_reply_ply", ply)
    bot = lgf_bot(7, True, 5)
    clone, _, _ = _one_clone()
    pts.greedy_finish_current_trick(bot, [clone], len(clone.history) + 1, None, 2, 7,
                                    compact=True, fast_clone=fast_clone)
    assert seen and all(fn is (pts.reply_children_fast if fast_clone else None) for fn in seen)
    seen.clear()
    monkeypatch.setattr(pts, "_reply_fast", None)
    clone, _, _ = _one_clone()
    pts.greedy_finish_current_trick(bot, [clone], len(clone.history) + 1, None, 2, 7,
                                    compact=True, fast_clone=fast_clone)
    assert seen and all(fn is None for fn in seen)


# ------------------------------------------------- (e) paired bots

@needs_module
@pytest.mark.parametrize("version", [2, 7])
def test_lgf_bots_decide_alike_with_and_without_the_compiled_children(monkeypatch, version):
    real = pts._reply_fast
    built = []

    class Spy:
        @staticmethod
        def reply_children(*args):
            built.append(1)
            return real.reply_children(*args)
    decisions = applied = 0
    for seed in (CAPPED_SEED, 707_004):
        rnd = _fresh_round(seed)
        plain = [lgf_bot(version, True, 300 + s) for s in range(4)]
        fast = [lgf_bot(version, True, 300 + s) for s in range(4)]
        for bot in plain + fast:
            for attr in NATIVE_OFF:
                setattr(bot, attr, True)
        while rnd.phase == "play":
            seat = rnd.turn
            monkeypatch.setattr(pts, "_reply_fast", None)
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            monkeypatch.setattr(pts, "_reply_fast", Spy())
            b = fast[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain[seat].last_decision_record, fast[seat].last_decision_record
            assert a == b and _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
            assert plain[seat].sampler.rng.getstate() == fast[seat].sampler.rng.getstate()
            assert plain[seat]._leaf_greedy["stats"] == fast[seat]._leaf_greedy["stats"]
            assert counters(plain[seat].evaluator) == counters(fast[seat].evaluator)
            decisions += 1
            applied += bool(ra["leaf_greedy_finish_applied"])
            rnd.play(seat, a)
    assert decisions >= 80 and applied > 20 and len(built) > 100
