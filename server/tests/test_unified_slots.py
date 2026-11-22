"""The unified model in the served search's root prior slot (`train.unified_slots`): own-information
scores under the served ``scores`` contract, installed on one bot instance only."""
from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import unified_numpy as un
from shengji.harvest.legal import enumerate_legal, is_legal
from shengji.rl.encode import CARD_INDEX
from shengji.train import pv_search_policy as pv
from shengji.train import unified_slots as us
from tests.test_pv_search_serving import SMALL as PV_SMALL
from tests.test_pv_search_serving import _play_state, package  # noqa: F401  (shared setup and fixture)

TRUNK = {"d": 16, "heads": 4, "enc_layers": 1, "xattn_layers": 1, "x_hidden": 16, "card_self_attn": True}
CONFIG = {"trunk": TRUNK, "heads": {"q_hidden": 8, "policy_hidden": 8}}


def _weights(shapes, rng):
    return {k: (0.3 * rng.standard_normal(s)).astype(np.float32) for k, s in shapes.items()}


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    rng = np.random.default_rng(5)
    path = tmp_path_factory.mktemp("uslot") / "u.npz"
    un.save_package(path, CONFIG, _weights(bn.expected_shapes(TRUNK, **bn.DIMS), rng),
                    _weights(un.head_shapes(CONFIG), rng), {"note": "test"})
    return un.load_unified_numpy(path)


def _bot(package, seed=3):
    return pv.make_pv_search_bot(package[0], sha256=package[1], seed=seed, **PV_SMALL, serving_budget_seconds=30.0)


def _reshuffled(rnd, seat, rng):
    other = copy.deepcopy(rnd)
    seats = [s for s in range(4) if s != seat]
    pool = [c for s in seats for c in other.hands[s]]
    rng.shuffle(pool)
    for s in seats:
        n = len(other.hands[s])
        other.hands[s][:] = pool[:n]
        del pool[:n]
    return other


def test_preferences_are_the_mean_card_log_odds_and_read_no_hidden_card(model):
    rnd = _play_state()
    seat = rnd.turn
    actions = [list(a) for a in enumerate_legal(rnd, seat, cap=200).actions]
    got = us.root_prior_preferences(model, rnd, seat, actions)
    logits = model.policy_logits(bn.decision_inputs(rnd, seat, ()))
    want = [np.mean([logits[CARD_INDEX[c]] for c in a]) for a in actions]
    assert np.allclose(got, want, atol=1e-6) and len({len(a) for a in actions}) > 1
    again = us.root_prior_preferences(model, _reshuffled(rnd, seat, random.Random(9)), seat, actions)
    assert np.array_equal(got, again)


def test_installed_scores_keep_the_served_contract_and_the_search_completes(package, model):
    rnd = _play_state()
    seat = rnd.turn
    bot = us.install_root_prior(_bot(package), model)
    assert bot.policy_name.endswith(f"-{us.TOKEN}{model.package_sha256[:8]}")
    actions = [list(a) for a in enumerate_legal(rnd, seat, cap=50).actions]
    worlds, _ = bot._worlds(rnd, seat)
    scores = bot.scores(rnd, seat, actions, worlds)
    assert scores.shape == (len(worlds), len(actions)) and np.isfinite(scores).all()
    assert (scores == scores[0]).all()
    assert np.array_equal(scores[0], us.root_prior_preferences(model, rnd, seat, actions))
    calls = bot.unified_prior_calls
    played = bot.decide_play(rnd, seat)
    assert is_legal(rnd, seat, played)
    assert bot.last_decision_record["schema"] == pv.RECORD_SCHEMA and bot.unified_prior_calls == calls + 1


def test_a_bot_it_was_not_installed_on_decides_as_before(package, model):
    rnd = _play_state()
    seat = rnd.turn
    before = _bot(package)
    played = before.decide_play(copy.deepcopy(rnd), seat)
    record = {k: v for k, v in before.last_decision_record.items() if "seconds" not in k}
    us.install_root_prior(_bot(package), model)
    after = _bot(package)
    assert "scores" not in vars(after) and "policy_name" not in vars(after)
    assert after.decide_play(copy.deepcopy(rnd), seat) == played
    assert {k: v for k, v in after.last_decision_record.items() if "seconds" not in k} == record


def test_a_model_error_is_the_searchs_own_fallback(package, model, monkeypatch):
    rnd = _play_state()
    bot = us.install_root_prior(_bot(package), model)
    monkeypatch.setattr(us, "root_prior_preferences", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    bot.decide_play(rnd, rnd.turn)
    assert bot.last_decision_record["schema"] == pv.FALLBACK_SCHEMA


def test_install_refuses_twice_an_unhashed_model_and_a_bot_without_the_slot(package, model):
    bot = us.install_root_prior(_bot(package), model)
    with pytest.raises(us.UnifiedSlotError):
        us.install_root_prior(bot, model)
    with pytest.raises(us.UnifiedSlotError):
        us.install_root_prior(object(), model)
    unhashed = copy.copy(model)
    unhashed.package_sha256 = None
    with pytest.raises(us.UnifiedSlotError):
        us.install_root_prior(_bot(package), unhashed)


# ---- one trunk forward for the belief slot and the root prior (`install_shared_forward`)

WHL = dict(world_history_legal=True, world_history_draw=True, belief_worlds=True)


@pytest.fixture(scope="module")
def belief_package(tmp_path_factory, model):
    """A served-shape belief package carrying the unified model's trunk (temperature not 1)."""
    path = tmp_path_factory.mktemp("uslot_b") / "belief.npz"
    sha = bn.save_package(path, TRUNK, dict(model.trunk.w), {"temperature": 1.3})
    return str(path), sha


def _belief_bot(package, belief_package, seed=3):
    return pv.make_pv_search_bot(package[0], sha256=package[1], seed=seed, **PV_SMALL, serving_budget_seconds=30.0, **WHL,
                                 belief_checkpoint=belief_package[0], belief_sha256=belief_package[1])


def _states(n=14):
    """Play states along one game (the heuristic plays), leads and follows."""
    from shengji.ai.heuristic import HeuristicBot
    rnd = _play_state()
    h = HeuristicBot()
    out = []
    while rnd.phase == "play" and len(out) < n:
        out.append(copy.deepcopy(rnd))
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    return out


def _record(bot):
    return {k: v for k, v in bot.last_decision_record.items() if "seconds" not in k and not k.endswith("_ms") and k != "policy"}


def test_shared_forward_belief_and_prior_are_the_two_forward_bytes(package, belief_package, model):
    served = bn.load_belief_numpy(*belief_package)
    shared = us.shared_trunk_belief(served, model)
    assert shared.temperature == served.temperature == 1.3 and shared.package_sha256 == served.package_sha256
    two = us.install_root_prior(_belief_bot(package, belief_package), model)
    one = us.install_shared_forward(_belief_bot(package, belief_package), model)
    assert one.policy_name.endswith(f"-{us.SHARED_TOKEN}{model.package_sha256[:8]}")
    states = _states()
    assert any(s.trick.plays for s in states) and any(not s.trick.plays for s in states)
    for n, rnd in enumerate(states, 1):
        seat = rnd.turn
        inp = bn.decision_inputs(rnd, seat, ())
        assert shared.logits(inp).tobytes() == served.logits(inp).tobytes()
        assert shared.marginals(inp).tobytes() == served.marginals(inp).tobytes()
        assert us.policy_from_states(model, shared.shared["q"]).tobytes() == model.policy_logits(inp).tobytes()
        actions = [list(a) for a in enumerate_legal(rnd, seat, cap=50).actions]
        w1, _ = one._worlds(rnd, seat)
        w2, _ = two._worlds(rnd, seat)
        assert w1 == w2 and one._last_sampling["belief_fallback"] == 0 == two._last_sampling["belief_fallback"]
        s1, s2 = one.scores(rnd, seat, actions, w1), two.scores(rnd, seat, actions, w2)
        assert s1.tobytes() == s2.tobytes() and s1.shape == (len(w1), len(actions))
        assert (one.unified_shared_hits, one.unified_shared_misses, one.unified_prior_calls) == (n, 0, n)


def test_shared_forward_decisions_and_records_equal_the_two_forward_bot(package, belief_package, model):
    for rnd in _states(8):
        seat = rnd.turn
        two = us.install_root_prior(_belief_bot(package, belief_package), model)
        one = us.install_shared_forward(_belief_bot(package, belief_package), model)
        assert one.decide_play(copy.deepcopy(rnd), seat) == two.decide_play(copy.deepcopy(rnd), seat)
        assert one.last_decision_record["schema"] == pv.RECORD_SCHEMA and _record(one) == _record(two)
        assert (one.unified_shared_hits, one.unified_shared_misses) == (1, 0)


def test_shared_forward_without_this_decisions_states_runs_the_trunk(package, belief_package, model):
    states = _states(3)
    one = us.install_shared_forward(_belief_bot(package, belief_package), model)
    rnd, other = states[0], states[2]
    actions = [list(a) for a in enumerate_legal(rnd, rnd.turn, cap=50).actions]
    want = np.tile(us.root_prior_preferences(model, rnd, rnd.turn, actions), (2, 1))
    assert one.scores(rnd, rnd.turn, actions, [None, None]).tobytes() == want.tobytes()       # no proposal ran
    one._worlds(other, other.turn)
    assert one.scores(rnd, rnd.turn, actions, [None, None]).tobytes() == want.tobytes()       # another state's
    one._worlds(rnd, rnd.turn)
    assert one.scores(copy.deepcopy(rnd), rnd.turn, actions, [None, None]).tobytes() == want.tobytes()  # another object
    assert (one.unified_shared_hits, one.unified_shared_misses) == (0, 3) and not one.belief_model.shared


def test_shared_forward_refuses_another_trunk_and_leaves_other_bots_alone(package, belief_package, model, tmp_path):
    rng = np.random.default_rng(8)
    path = tmp_path / "other.npz"
    sha = bn.save_package(path, TRUNK, _weights(bn.expected_shapes(TRUNK, **bn.DIMS), rng), {"temperature": 1.0})
    with pytest.raises(us.UnifiedSlotError):
        us.install_shared_forward(_belief_bot(package, (str(path), sha)), model)
    with pytest.raises(us.UnifiedSlotError):
        us.install_shared_forward(_bot(package), model)
    rnd = _play_state()
    before = _belief_bot(package, belief_package)
    played = before.decide_play(copy.deepcopy(rnd), rnd.turn)
    record = _record(before)
    us.install_shared_forward(_belief_bot(package, belief_package), model)
    after = _belief_bot(package, belief_package)
    assert not {"scores", "_belief_worlds", "policy_name"} & set(vars(after)) and type(after.belief_model) is bn.BeliefNumpy
    assert after.decide_play(copy.deepcopy(rnd), rnd.turn) == played and _record(after) == record


def test_shared_trunk_reuses_only_matching_immutable_buffers(belief_package, model, monkeypatch):
    served = bn.load_belief_numpy(*belief_package)
    first = us.shared_trunk_belief(served, model)
    key = next(iter(served.w))
    with pytest.raises(ValueError):
        served.w[key].setflags(write=True)
    with monkeypatch.context() as patch:
        def unexpected(*args):
            pytest.fail("identical verified buffers were compared again")
        patch.setattr(np, "array_equal", unexpected)
        second = us.shared_trunk_belief(served, model)
    assert first.shared is not second.shared
    served.w[key] = served.w[key].copy()
    us.shared_trunk_belief(served, model)
    served.w[key].flat[0] += 1
    with pytest.raises(us.UnifiedSlotError, match="trunk"):
        us.shared_trunk_belief(served, model)
