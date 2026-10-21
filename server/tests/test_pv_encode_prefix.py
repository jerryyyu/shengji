"""The prefix-cached encoding latency switch (``SHENGJI_PV_ENCODE_PREFIX_CACHE``,
`train.pv_encode_prefix`): the served value pass's leaves and the prior's root
rows are encoded on the decision root's shared history prefix, with one batched
validation, and every tensor is the reference encoder's byte for byte.

Torch-free and package-free (a NumPy evaluator on a seeded random head stands in
for the package).  Witnesses: (a) full tensor bytes against the reference
encoder on leaves of pair and tractor follows, void-creating follows, partial
tricks, a second finished trick, the banker's own kitty and a defender's, the
opening lead, in forward and reversed batch order; (b) the fast path is taken on
those leaves and refused (reference rows, the same bytes) on a leaf that does not
extend the prefix; (c) refusals are the reference's; (d) the prior's root rows;
(e) a served bot with the switch on decides, records and counts exactly as off
over seeded rounds, and the switch enters no name or payload.
"""
import copy
import random
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
from shengji.ai.cwv_policy import afterstate
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.combos import decompose
from shengji.harvest.legal import enumerate_legal
from shengji.rl.value_afterstate import OUTCOME_CLASSES, category_signed_level
from shengji.rl.value_afterstate_v2 import public_dim
from shengji.train import pv_encode_prefix as prefix_module
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_prior_admission import root_clone
from shengji.train.policy_prior import flat_input, input_dim, root_tensors
from shengji.train.pv_encode_prefix import HistoryPrefix, encode_leaves, prior_rows, score_leaves
from test_pv_doomed_throw_reselect_exact_guard import R46_ENV
from test_pv_leaf_greedy_finish import R46_RULES
from test_pv_small_joker_lead import _fresh_round

FLAG = "SHENGJI_PV_ENCODE_PREFIX_CACHE"
SEEDS = tuple(range(707300, 707340))


class StubHead:
    """A seeded random linear head over the static inputs: any input byte that
    moves moves the outcome distribution."""

    def __init__(self, version):
        self.config = SimpleNamespace(architecture="mlp", enc_version=version,
                                      public_dim=public_dim(version))
        rng = np.random.default_rng(1000 + version)
        self.weight = rng.standard_normal((public_dim(version) + 5 * 54 + 2, OUTCOME_CLASSES))

    def probabilities(self, public, world, perspective):
        x = np.concatenate((public, world.reshape(len(public), -1), perspective),
                           axis=1).astype(np.float64)
        z = x @ self.weight
        z -= z.max(axis=1, keepdims=True)
        p = np.exp(z)
        return p / p.sum(axis=1, keepdims=True)


def stub_evaluator(version=7):
    """A `NumpyCompleteWorldEvaluator` on `StubHead` (the served class and its
    static ``mlp-static`` route, no package)."""
    ev = NumpyCompleteWorldEvaluator.__new__(NumpyCompleteWorldEvaluator)
    ev.model = StubHead(version)
    ev.metadata, ev.value_head = {}, "outcome"
    ev.checkpoint_path = ev.checkpoint_sha256 = None
    ev.encoding, ev.device, ev.threads, ev.max_batch = "mlp-static", "cpu", None, 4096
    ev.support = np.asarray([category_signed_level(i) for i in range(OUTCOME_CLASSES)],
                            dtype=np.float64)
    ev.positions = ev.model_rows = ev.terminal_rows = ev.forward_calls = ev.calls = 0
    ev.wall_secs = ev.cpu_secs = 0.0
    return ev


def counters(ev):
    return (ev.calls, ev.positions, ev.model_rows, ev.terminal_rows, ev.forward_calls)


def worlds_for(rnd, seat, n, seed):
    """The true deal, then ``n - 1`` deals of the hidden cards at the true hand
    lengths; the banker's own kitty stays fixed when the root seat is the banker."""
    rng = random.Random(seed)
    own_kitty = seat == rnd.banker
    hidden = [c for s in range(4) if s != seat for c in rnd.hands[s]]
    if not own_kitty:
        hidden += list(rnd.buried)
    out = [([list(h) for h in rnd.hands], list(rnd.buried))]
    for _ in range(n - 1):
        cards = hidden[:]
        rng.shuffle(cards)
        hands, i = [], 0
        for s in range(4):
            if s == seat:
                hands.append(list(rnd.hands[s]))
                continue
            k = len(rnd.hands[s])
            hands.append(sorted(cards[i:i + k]))
            i += k
        out.append((hands, list(rnd.buried) if own_kitty else sorted(cards[i:])))
    return out


def leaves_for(rnd, seat, worlds, cap=10):
    """Per world and candidate: the served leaf (trick finished), the partial
    trick (the candidate alone) and a leaf one more trick deep."""
    actions = enumerate_legal(rnd, seat, cap=4000).actions[:cap]
    h = HeuristicBot()
    out = []
    for hands, buried in worlds:
        for action in actions:
            out.append(afterstate(rnd, seat, hands, buried, action, finish_trick=True))
            out.append(afterstate(rnd, seat, hands, buried, action, finish_trick=False))
            deep = afterstate(rnd, seat, hands, buried, action, finish_trick=True)
            target = len(deep.history) + 1
            while deep.phase == "play" and len(deep.history) < target:
                deep.play(deep.turn, h.decide_play(deep, deep.turn))
            out.append(deep)
    return out


def _lead(rnd):
    return rnd.trick.plays[0].cards if rnd.trick and rnd.trick.plays else None


def _multi_lead_before(rnd):
    """The prefix already holds a multi-card lead and an inferred void."""
    return (any(len(t.plays[0].cards) >= 2 for t in rnd.history)
            and any(HistoryPrefix.of(rnd).voids))


def _pair(rnd, seat):
    lead = _lead(rnd)
    return lead is not None and len(lead) == 2 and lead[0] == lead[1] \
        and _multi_lead_before(rnd)


def _tractor(rnd, seat):
    lead = _lead(rnd)
    if lead is None or len(lead) < 4:
        return False
    components = decompose(list(lead), rnd.ordering).components
    return len(components) == 1 and components[0].pair_len >= 2 and bool(rnd.history)


def _void(rnd, seat):
    lead = _lead(rnd)
    if lead is None:
        return False
    suit = rnd.ordering.eff_suit(lead[0])
    return not any(rnd.ordering.eff_suit(c) == suit for c in rnd.hands[seat]) \
        and _multi_lead_before(rnd)


def _banker_lead(rnd, seat):
    return _lead(rnd) is None and seat == rnd.banker and len(rnd.history) >= 4


def _defender_lead(rnd, seat):
    return _lead(rnd) is None and not rnd.is_attacker(seat) and seat != rnd.banker \
        and len(rnd.history) >= 4


def _late_follow(rnd, seat):
    return _lead(rnd) is not None and len(rnd.hands[seat]) <= 4


def _opening(rnd, seat):
    return not rnd.history and _lead(rnd) is None


SCENARIOS = {"pair_follow": _pair, "tractor_follow": _tractor, "void_follow": _void,
             "banker_lead": _banker_lead, "defender_lead": _defender_lead,
             "late_follow": _late_follow, "opening_lead": _opening}


def find_root(pred):
    h = HeuristicBot()
    for seed in SEEDS:
        rnd = _fresh_round(seed)
        while rnd.phase == "play":
            seat = rnd.turn
            if pred(rnd, seat):
                return rnd, seat
            rnd.play(seat, h.decide_play(rnd, seat))
    raise AssertionError("no root of this kind in the seeded rounds")


def assert_same_rows(fast, reference):
    assert len(fast) == len(reference)
    for a, b in zip(fast, reference):
        assert type(a) is type(b)
        for field in ("public", "history", "world", "perspective"):
            x, y = getattr(a, field), getattr(b, field)
            assert x.dtype == y.dtype and x.shape == y.shape
            assert x.tobytes() == y.tobytes(), field


# ------------------------------------------------- (a) tensor bytes against the reference

@pytest.mark.parametrize("version", [7, 2, 1])
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_leaf_tensors_are_the_reference_bytes(scenario, version):
    rnd, seat = find_root(SCENARIOS[scenario])
    ev = stub_evaluator(version)
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 3, seed=len(rnd.history)))
    reference = [ev.encoder(leaf, seat) for leaf in leaves if leaf.phase != "round_end"]
    for order in (leaves, leaves[::-1]):
        encoded = encode_leaves(ev, order, seat, HistoryPrefix.of(rnd))
        assert encoded is not None
        _, rows, pending, fast = encoded
        expected = [ev.encoder(order[i], seat) for i in pending]
        assert_same_rows(rows, expected)
        assert fast == len(rows) == len(reference)        # every row took the prefix
    assert_same_rows(encode_leaves(ev, leaves[::-1], seat, HistoryPrefix.of(rnd))[1],
                     reference[::-1])


def test_the_scenarios_cover_what_they_name():
    """The prefixes hold multi-card leads and inferred voids, and the leaves end
    mid-trick, at a trick boundary and a trick deeper."""
    rnd, seat = find_root(_tractor)
    prefix = HistoryPrefix.of(rnd)
    assert prefix is not None and prefix.events == 4 * len(rnd.history) > 0
    rnd, seat = find_root(_pair)
    assert _multi_lead_before(rnd)
    rnd, seat = find_root(_void)
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 2, seed=3))
    depths = {len(leaf.history) - len(rnd.history) for leaf in leaves}
    assert depths == {0, 1, 2} or depths == {1, 2}
    assert any(leaf.trick is not None and leaf.trick.plays for leaf in leaves)
    rnd, seat = find_root(_pair)
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 2, seed=3))
    assert any(len(leaf.history) == len(rnd.history) + 1 and any(
        len(p.cards) == 2 for p in leaf.history[-1].plays) for leaf in leaves)


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_scores_and_counters_are_the_reference(scenario):
    rnd, seat = find_root(SCENARIOS[scenario])
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 2, seed=11), cap=6)
    ref, fast = stub_evaluator(), stub_evaluator()
    expected = ref.score(leaves, seat)
    got = score_leaves(fast, leaves, seat, HistoryPrefix.of(rnd))
    assert got.dtype == expected.dtype and got.tobytes() == expected.tobytes()
    assert counters(fast) == counters(ref)


# ------------------------------------------------- (b) where the prefix does not apply

def test_a_leaf_that_does_not_extend_the_prefix_takes_the_reference():
    rnd, seat = find_root(_pair)
    ev = stub_evaluator()
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 2, seed=5), cap=4)
    foreign = [copy.deepcopy(leaf) for leaf in leaves]     # same states, other trick objects
    _, rows, pending, fast = encode_leaves(ev, foreign, seat, HistoryPrefix.of(rnd))
    assert fast == 0
    assert_same_rows(rows, [ev.encoder(foreign[i], seat) for i in pending])
    other, other_seat = find_root(_void)
    assert HistoryPrefix.of(other).fused(leaves[0], seat) is None


def test_an_unsupported_evaluator_or_encoder_takes_the_reference(monkeypatch):
    rnd, seat = find_root(_pair)
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 1, seed=5), cap=2)
    ev = stub_evaluator()
    ev.encoding = "reference"                          # the reference builder
    assert encode_leaves(ev, leaves, seat, HistoryPrefix.of(rnd)) is None

    class Scored(NumpyCompleteWorldEvaluator):
        def score(self, positions, root_seat, *, tensor_cache=None):
            return np.full(len(positions), 7.0)
    other = stub_evaluator()
    other.__class__ = Scored
    assert encode_leaves(other, leaves, seat, HistoryPrefix.of(rnd)) is None
    assert score_leaves(other, leaves, seat, HistoryPrefix.of(rnd)).tolist() == [7.0] * len(leaves)
    assert encode_leaves(stub_evaluator(), leaves, seat, None) is None


def test_a_failed_batch_check_reencodes_the_whole_call(monkeypatch):
    rnd, seat = find_root(_void)
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 2, seed=5), cap=3)
    ref, fast = stub_evaluator(), stub_evaluator()
    monkeypatch.setattr(prefix_module, "_valid_batch", lambda rows, version: False)
    assert encode_leaves(fast, leaves, seat, HistoryPrefix.of(rnd)) is None
    got = score_leaves(fast, leaves, seat, HistoryPrefix.of(rnd))
    assert got.tobytes() == ref.score(leaves, seat).tobytes()
    assert counters(fast) == counters(ref)


def test_the_batch_check_implies_the_per_row_checks():
    rnd, seat = find_root(_pair)
    ev = stub_evaluator()
    leaf = leaves_for(rnd, seat, worlds_for(rnd, seat, 1, seed=5), cap=1)[0]
    row = ev.encoder(leaf, seat)
    assert prefix_module._valid_batch([row], 7)
    for bad in (dict(world=np.where(row.world == 0.5, 1.5, row.world).astype(np.float32)),
                dict(perspective=np.asarray([1.0, 1.0], dtype=np.float32)),
                dict(public=np.where(np.arange(row.public.shape[0]) == 3, np.nan,
                                     row.public).astype(np.float32)),
                dict(public=row.public[:-1])):
        broken = type(row)(**{**vars(row), **bad})
        assert not prefix_module._valid_batch([row, broken], 7)
        with pytest.raises(Exception):
            broken.validate()


# ------------------------------------------------- (c) refusals are the reference's

def test_a_refused_state_raises_the_reference_refusal():
    rnd, seat = find_root(_pair)
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 1, seed=5), cap=3)
    broken = copy.copy(leaves[0])
    hands = [list(h) for h in broken.hands]
    other = (seat + 1) % 4
    hands[other][0] = hands[seat][0]                    # a third copy of one card
    broken.hands = hands
    batch = [leaves[1], broken, leaves[2]]
    with pytest.raises(Exception) as reference:
        stub_evaluator().score(batch, seat)
    with pytest.raises(type(reference.value)) as fast:
        score_leaves(stub_evaluator(), batch, seat, HistoryPrefix.of(rnd))
    assert str(fast.value) == str(reference.value)
    with pytest.raises(Exception) as empty:
        score_leaves(stub_evaluator(), [], seat, HistoryPrefix.of(rnd))
    assert "no positions" in str(empty.value)


# ------------------------------------------------- (d) the prior's root rows

def reference_prior(rnd, seat, worlds, version):
    return np.stack([flat_input(root_tensors(root_clone(rnd, hands, buried), seat, version), version)
                     for hands, buried in worlds]).astype(np.float32)


@pytest.mark.parametrize("version", [7, 2, 1])
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_prior_rows_are_the_reference_bytes(scenario, version):
    rnd, seat = find_root(SCENARIOS[scenario])
    worlds = worlds_for(rnd, seat, 6, seed=29)
    for order in (worlds, worlds[::-1]):
        got = prior_rows(rnd, seat, order, version)
        expected = reference_prior(rnd, seat, order, version)
        assert got.dtype == expected.dtype and got.shape == expected.shape == (6, input_dim(version))
        assert got.tobytes() == expected.tobytes()


def test_prior_rows_with_another_acting_hand_take_the_reference():
    """A world whose acting hand differs from the first world's cannot share its
    public block; the whole call is the reference's."""
    rnd, seat = find_root(_void)
    worlds = worlds_for(rnd, seat, 4, seed=29)
    hands, buried = worlds[2]
    swapped = [list(h) for h in hands]
    other = (seat + 1) % 4
    swapped[seat][0], swapped[other][0] = swapped[other][0], swapped[seat][0]
    odd = worlds[:2] + [(swapped, buried)] + worlds[3:]
    got = prior_rows(rnd, seat, odd, 7)
    expected = reference_prior(rnd, seat, odd, 7)
    assert got.tobytes() == expected.tobytes()
    assert expected[2].tobytes() != expected[1].tobytes()


# ------------------------------------------------- (e) a served bot, switch on and off

def stub_predict_for(version):
    weight = np.random.default_rng(7).standard_normal((input_dim(version), 54))

    def predict(X):
        return np.asarray(X, dtype=np.float64) @ weight
    return predict


def bot(version, on, worlds=6, seed=17):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=16, **R46_RULES)
    b = pv.PVSearchBot(stub_predict_for(version), evaluator=stub_evaluator(version),
                       version=version, config=config, checkpoint="/dev/null", seed=seed)
    if on:
        b.encode_prefix_cache = True
    return b


def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds") and not k.endswith("_ms")}


@pytest.mark.parametrize("version", [7, 2])
def test_a_served_bot_decides_and_counts_exactly_as_off_over_seeded_rounds(version):
    off, on = bot(version, False), bot(version, True)
    decisions = 0
    for seed in (17, 23):
        rnd = _fresh_round(seed)
        while rnd.phase == "play":
            seat = rnd.turn
            a = off.decide_play(copy.deepcopy(rnd), seat)
            b = on.decide_play(copy.deepcopy(rnd), seat)
            assert a == b
            assert _comparable(off.last_decision_record) == _comparable(on.last_decision_record)
            assert off.sampler.rng.getstate() == on.sampler.rng.getstate()
            assert counters(off.evaluator) == counters(on.evaluator)
            rnd.play(seat, a)
            decisions += 1
    assert decisions > 100
    assert on.evaluator.model_rows > 0


def test_the_switch_is_off_by_default_and_enters_no_name(monkeypatch):
    assert pv.PVSearchBot.encode_prefix_cache is False
    assert pv.latency_switches({}) == {"encode_prefix_cache": False, "single_candidate_fast": False}
    assert pv.latency_switches({FLAG: "1"})["encode_prefix_cache"] is True
    assert pv.latency_switches({FLAG: "0"})["encode_prefix_cache"] is False
    with pytest.raises(pv.PVSearchPolicyError, match=FLAG):
        pv.latency_switches({FLAG: "yes"})
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    assert pv.pv_env_recipe({**env, FLAG: "1"}) == pv.pv_env_recipe(env)
    with pytest.raises(pv.PVSearchPolicyError, match=FLAG):
        pv.pv_env_recipe({**env, FLAG: "2"})
    off = bot(7, False)
    assert "encode_prefix_cache" not in vars(off)
