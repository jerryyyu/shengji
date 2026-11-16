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
    assert "scores" not in vars(after) and after.policy_name == before.policy_name
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
