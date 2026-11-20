"""The banker side-suit void head and the void-first world draw (`ai.void_head`), off unless installed."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai import void_head as vh
from shengji.ai.memory import Memory
from shengji.rl.encode import CARD_INDEX
from shengji.train import unified_slots as us
from tests.test_pv_search_serving import package  # noqa: F401  (shared setup and fixture)
from tests.test_unified_slots import _belief_bot, _states, belief_package, model  # noqa: F401

CODES = sorted(CARD_INDEX, key=CARD_INDEX.get)
D, DG = 16, 16          # the test trunk's card-state and row-context widths
F = D + DG + vh.N_SCALARS


def _head(tmp_path, bias, belief_sha, name="h.npz"):
    """A head whose output is the constant ``sigmoid(bias)`` (zero weights)."""
    w = {"l0.weight": np.zeros((8, F)), "l0.bias": np.zeros(8), "l1.weight": np.zeros((4, 8)), "l1.bias": np.zeros(4),
         "l2.weight": np.zeros((1, 4)), "l2.bias": np.array([float(bias)])}
    path = tmp_path / name
    sha = vh.save_package(path, {"in_dim": F, "hidden": [8, 4]}, w, {"belief_package_sha256": belief_sha})
    return str(path), sha


def _non_banker_states(n=14):
    return [r for r in _states(n) if r.turn != r.banker]


def _suit_of(rnd):
    o = rnd.ordering
    return np.array(["SHDC".index(o.eff_suit(c)) if o.eff_suit(c) in "SHDC" else 4 for c in CODES])


def test_card_states_compose_to_the_served_logits_and_marginals(belief_package):
    served = bn.load_belief_numpy(*belief_package)
    for rnd in _states(10):
        inp = bn.decision_inputs(rnd, rnd.turn, ())
        q, g = served.card_states(inp)
        assert served.head_logits(q, g).tobytes() == served.logits(inp).tobytes()
        assert served.marginals_of(served.logits(inp), inp["M"]).tobytes() == served.marginals(inp).tobytes()


def test_the_shared_trunk_belief_gives_the_same_states_and_keeps_its_slot(belief_package, model):
    served = bn.load_belief_numpy(*belief_package)
    shared = us.shared_trunk_belief(served, model)
    for rnd in _states(6):
        inp = bn.decision_inputs(rnd, rnd.turn, ())
        q, g = shared.card_states(inp)
        assert shared.head_logits(q, g).tobytes() == shared.logits(inp).tobytes()
        assert shared.shared["q"] is not None and shared.shared["seat"] == rnd.turn
        q2, g2 = served.card_states(inp)
        np.testing.assert_allclose(shared.output_states(q), served.output_states(q2), atol=1e-5)


def test_candidates_and_features_follow_the_definition(belief_package):
    served = bn.load_belief_numpy(*belief_package)
    seen = 0
    for rnd in _non_banker_states():
        seat = rnd.turn
        inp = bn.decision_inputs(rnd, seat, ())
        r = (rnd.banker - seat) % 4 - 1
        q, g = served.card_states(inp)
        h = served.output_states(q)
        P = served.marginals(inp)
        x, cand = vh.features(h[None], g[None], P[None], inp["M"][None], inp["n_c"][None], inp["sizes"][None],
                              inp["K"][None], inp["card_feat"][None], np.array([r]))
        assert x.shape == (1, 4, F) and np.isfinite(x).all()
        suit = _suit_of(rnd)
        for f in range(4):
            on = suit == f
            w = inp["n_c"] * (inp["M"][:, r] & (inp["n_c"] > 0)) * on
            want = w.sum() > 0 and inp["K"][on, r].sum() == 0
            assert cand[0, f] == want
            if want:
                np.testing.assert_allclose(x[0, f, :D], (w[:, None] * h).sum(0) / w.sum(), rtol=1e-5, atol=1e-6)
                seen += 1
        np.testing.assert_allclose(x[0, :, D:D + DG], np.broadcast_to(g, (4, DG)), rtol=1e-6)
        assert (x[0, :, -3:] == np.eye(3)[r]).all()
    assert seen > 5


def test_package_round_trip_and_refusals(tmp_path):
    path, sha = _head(tmp_path, 0.0, "x" * 64)
    head = vh.load_void_head(path, sha)
    assert head.package_sha256 == sha
    np.testing.assert_allclose(head.probs(np.zeros((3, 4, F), np.float32)), 0.5)
    with pytest.raises(vh.VoidHeadError):
        vh.load_void_head(path, "0" * 64)
    with pytest.raises(vh.VoidHeadError):
        vh.VoidHead({"in_dim": F, "hidden": [8]}, dict(head.w), {})


def _proposals(served, rnd, seat, head, seed=3, batch=64):
    constraints = HL.draw_constraints(rnd, seat)
    off = bn.BeliefProposal(served, rnd, seat, (), seed=seed, batch=batch, forbidden=constraints)
    on = bn.BeliefProposal(served, rnd, seat, (), seed=seed, batch=batch, forbidden=constraints, void_head=head)
    return off, on


def test_a_sure_void_is_drawn_in_every_world_when_feasible_and_worlds_stay_legal(belief_package, tmp_path):
    served = bn.load_belief_numpy(*belief_package)
    head = vh.load_void_head(*_head(tmp_path, 30.0, served.package_sha256))
    forced = 0
    for rnd in _non_banker_states():
        seat = rnd.turn
        _, on = _proposals(served, rnd, seat, head)
        assert on.void is not None
        b, suit = rnd.banker, _suit_of(rnd)
        mem = Memory(rnd, seat, own_kitty=True)
        for _ in range(64):
            hands, buried = on(rnd, seat, mem)
            full = [hands.get(s, rnd.hands[s]) for s in range(4)]
            for s in range(4):
                assert len(full[s]) == len(rnd.hands[s])
                if s != seat:
                    assert not any(rnd.ordering.eff_suit(c) in mem.voids[s] for c in full[s])
            kept, _, _ = on.void.plan(tuple(on.void.suits))
            for f in kept:
                assert not any(suit[CARD_INDEX[c]] == f for c in full[b])
        forced += on.void_forced
        assert all(on.void.force[f] == pytest.approx(1.0) or on.void.q[f] >= 1.0 for f in on.void.suits)
    assert forced > 0


def test_a_zero_head_never_forces_and_the_banker_and_off_draws_are_unchanged(belief_package, tmp_path):
    served = bn.load_belief_numpy(*belief_package)
    head = vh.load_void_head(*_head(tmp_path, -40.0, served.package_sha256))
    for rnd in _states(10):
        seat = rnd.turn
        off, on = _proposals(served, rnd, seat, head)
        mem = Memory(rnd, seat, own_kitty=True)
        a = [off(rnd, seat, mem) for _ in range(16)]
        b = [on(rnd, seat, mem) for _ in range(16)]
        if seat == rnd.banker:
            assert on.void is None and a == b        # no plan, no extra generator draw
        else:
            assert on.void is not None and on.void_forced == 0
            assert all(v == 0.0 for v in on.void.force.values())


def test_an_infeasible_pattern_drops_suits_lowest_force_first():
    M = np.zeros((54, 4), bool)
    n_c = np.zeros(54)
    eff = np.zeros((54, 4), bool)
    # receiver 0 (the banker) must take 2 cards; only suits 0 and 1 can go there
    for c, f in ((0, 0), (1, 0), (2, 1), (3, 1)):
        M[c, [0, 1]] = True
        n_c[c] = 1
        eff[c, f] = True
    sizes = np.array([2, 2, 0, 0])
    P = np.where(M, 0.5, 0.0)
    vf = vh.VoidFirst(P, P, M, n_c, sizes, eff, 0, np.array([0.9, 0.6, 0.0, 0.0]), np.array([True, True, False, False]))
    kept, Mz, _ = vf.plan((0, 1))
    assert kept == (0,) and not Mz[[0, 1], 0].any() and Mz[[2, 3], 0].all()
    assert vh.hall_feasible(Mz, n_c, sizes)
    mix = vf.mixture()
    np.testing.assert_allclose(mix.sum(-1)[n_c > 0], 1.0)


def test_the_installed_bot_draws_history_legal_seeded_worlds_and_records_the_plan(package, belief_package, tmp_path):
    served_sha = belief_package[1]
    path, sha = _head(tmp_path, 1.0, served_sha)
    bot = _belief_bot(package, belief_package)
    name = getattr(bot, "policy_name", None) or type(bot).__name__
    vh.install_void_head(bot, path, sha)
    assert bot.policy_name == f"{name}-{vh.NAME_TOKEN}{sha[:8]}"
    with pytest.raises(vh.VoidHeadError):
        vh.install_void_head(bot, path, sha)
    rnd = _non_banker_states()[0]
    seat = rnd.turn
    worlds, _ = bot._worlds(copy.deepcopy(rnd), seat)
    stats = bot._last_sampling
    assert stats["belief_fallback"] == 0 and stats["void_first_suits"] >= 1
    for hands, _ in worlds:
        assert HL.history_legal(rnd, seat, hands)
    again = _belief_bot(package, belief_package)
    vh.install_void_head(again, path, sha)
    assert again._worlds(copy.deepcopy(rnd), seat)[0] == worlds
    plain = _belief_bot(package, belief_package)
    plain._worlds(copy.deepcopy(rnd), seat)
    assert "void_first_suits" not in plain._last_sampling
    snap = copy.deepcopy(bot)
    assert snap.void_head is bot.void_head


def test_install_refuses_a_head_trained_on_another_belief_package(package, belief_package, tmp_path):
    path, sha = _head(tmp_path, 0.0, "f" * 64)
    with pytest.raises(vh.VoidHeadError):
        vh.install_void_head(_belief_bot(package, belief_package), path, sha)
