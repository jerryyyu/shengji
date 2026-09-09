"""Witness the full-legal candidate wiring, not just a ranking helper."""
import copy
import random

import numpy as np
import pytest

from shengji.ai.cwv_policy import afterstate, sample_worlds
from shengji.ai.mcbot import MCBot
from shengji.ai.registry import REGISTRY
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import play_state, round_signature


class Values:
    def __init__(self):
        self.calls = []

    def score(self, states, seat):
        self.calls.append((list(states), seat))
        return np.asarray([r.attacker_points for r in states], dtype=float)


def test_real_enumerator_every_action_world_is_scored_in_bounded_batches():
    rnd = play_state()
    original = round_signature(rnd)
    evaluator = Values()
    bot = CWVShortlistBot(evaluator, seed=13, config=CWVShortlistConfig(worlds=2, batch_size=17))
    before_rng = bot.rng.getstate()
    legal = enumerate_legal(rnd, rnd.turn, cap=None)
    production = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, rnd.turn)
    assert len(legal.actions) > len(production) * 10
    selected = bot._candidates(rnd, rnd.turn)
    assert selected[0] == sorted(production[0])
    assert len(selected) == 5 and len({tuple(a) for a in selected}) == 5
    assert sum(len(rows) for rows, _ in evaluator.calls) == len(legal.actions) * 2
    assert max(len(rows) for rows, _ in evaluator.calls) <= 17
    assert bot.shortlist_counts["cheap_evaluations"] == len(legal.actions) * 2
    assert bot.last_shortlist["legal_count"] == len(legal.actions)
    assert "full_legal_scores" not in bot.last_shortlist
    assert bot.rng.getstate() == before_rng
    assert round_signature(rnd) == original


def test_full_legal_capture_retains_every_aligned_score_without_changing_search(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = play_state()
    config = CWVShortlistConfig(worlds=2, selection_worlds=2, batch_size=17)
    bots = [CWVShortlistBot(Values(), seed=13, config=config,
                           capture_full_legal_scores=enabled)
            for enabled in (False, True)]
    rollout_calls = [[], []]
    for index, bot in enumerate(bots):
        bot.REPORT_FOLD_WORLDS = 30

        def rollout(r, s, hands, buried, action, _index=index, **kwargs):
            rollout_calls[_index].append((tuple(action),
                tuple((s, tuple(cards)) for s, cards in sorted(hands.items())), tuple(buried)))
            return float(len(action))

        monkeypatch.setattr(bot, "_rollout", rollout)
    played = [bot.decide_play(copy.deepcopy(rnd), rnd.turn) for bot in bots]
    assert played[0] == played[1]
    assert rollout_calls[0] and rollout_calls[0] == rollout_calls[1]
    assert bots[0].rng.getstate() == bots[1].rng.getstate()
    assert bots[0].shortlist_counts == bots[1].shortlist_counts
    assert [len(states) for states, _ in bots[0].evaluator.calls] == [
        len(states) for states, _ in bots[1].evaluator.calls]
    detail = bots[1].last_decision_record["cwv_shortlist"]
    capture = detail["full_legal_scores"]
    actions = enumerate_legal(rnd, rnd.turn, cap=None).actions
    assert capture["schema"] == "cwv-full-legal-scores-v1"
    assert capture["actions"] == [sorted(a) for a in actions]
    assert len(actions) > len(detail["shortlist"])
    # Independently recover world-major evaluator output, including rejected
    # actions. A selected-only vector or an index permutation fails here.
    raw = [float(r.attacker_points) for states, _ in bots[1].evaluator.calls for r in states]
    expected = np.asarray(raw).reshape(2, len(actions)).mean(axis=0).tolist()
    assert capture["means"] == expected
    assert [capture["means"][i] for i in detail["shortlist_indices"]] == detail["shortlist_means"]
    assert capture["worlds"] == 2 and capture["unscored_reason"] is None
    assert capture["world_seed"] == detail["world_seed"]
    assert capture["seat"] == rnd.turn
    assert capture["kind"] == "model-world-mean"
    assert capture["perspective"] == "acting-team"
    assert "full_legal_scores" not in bots[0].last_shortlist


def test_uniform_capture_does_not_fabricate_model_labels():
    rnd = play_state()
    bot = CWVShortlistBot(None, config=CWVShortlistConfig(uniform=True),
                         capture_full_legal_scores=True)
    bot._candidates(rnd, rnd.turn)
    capture = bot.last_shortlist["full_legal_scores"]
    assert capture["means"] is None
    assert capture["unscored_reason"] == "uniform"
    assert capture["worlds"] == 0
    assert len(capture["actions"]) == bot.last_shortlist["legal_count"]


def test_k8_keeps_incumbent_and_exhaustively_scores_all_legal_actions():
    rnd = play_state()
    original = round_signature(rnd)
    evaluator = Values()
    bot = CWVShortlistBot(
        evaluator, seed=13,
        config=CWVShortlistConfig(worlds=1, selection_worlds=30,
                                   alternatives=8, batch_size=17))
    before_rng = bot.rng.getstate()
    legal = enumerate_legal(rnd, rnd.turn, cap=None)
    assert len(legal.actions) >= 9

    production = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, rnd.turn)
    selected = bot._candidates(rnd, rnd.turn)

    assert selected[0] == sorted(production[0])
    assert len(selected) == 9
    assert len({tuple(action) for action in selected}) == 9
    assert bot.shortlist_config.alternatives == 8
    assert bot.N_DETERMINIZATIONS == 30
    assert bot.REPORT_FOLD_WORLDS == 300
    assert sum(len(rows) for rows, _ in evaluator.calls) == len(legal.actions)
    assert bot.shortlist_counts["cheap_evaluations"] == len(legal.actions)
    assert bot.rng.getstate() == before_rng
    assert round_signature(rnd) == original


def test_full_decision_can_nominate_an_offballot_action_without_changing_search(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd = play_state()
    seat = rnd.turn
    bot = CWVShortlistBot(Values(), seed=13, config=CWVShortlistConfig(selection_worlds=2))
    production = REGISTRY["mc-s0-report-lcb"](seed=13)._candidates(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=None).actions
    target = next(a for a in legal if tuple(a) not in {tuple(sorted(b)) for b in production})
    # If the wiring regresses to production's ballot this target is absent.
    monkeypatch.setattr(bot, "_means", lambda r, s, actions, worlds:
                        np.asarray([100.0 if a == target else 0.0 for a in actions]))
    rollouts = []

    def rollout(r, s, hands, buried, action, **kwargs):
        rollouts.append(tuple(action))
        value = 100.0 if action == target else 0.0
        return value if rnd.is_attacker(seat) else -value

    monkeypatch.setattr(bot, "_rollout", rollout)
    bot.REPORT_FOLD_WORLDS = 30
    assert bot._decide_adaptive.__func__ is MCBot._decide_adaptive
    assert bot._report_fold_gap.__func__ is MCBot._report_fold_gap
    assert bot._report_rollout.__func__ is MCBot._report_rollout
    assert bot._pick_index.__func__ is MCBot._pick_index
    played = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert played == target
    assert rec["report_fold"]["worlds"] == 30
    assert rec["report_fold"]["complete"] is True
    assert rec["work"]["report_rollouts"] == 60
    assert tuple(target) in rollouts
    assert rec["cwv_shortlist"]["offballot_played"] is True
    assert rec["cwv_shortlist"]["shortlist"] == rec["candidates"]
    cheap = rec["cwv_shortlist"]["cheap_sampler_delta"]
    full = rec["cwv_shortlist"]["production_sampler_delta"]
    total = rec["sampler_counters"]["delta"]
    assert cheap["accepted_worlds"] == 1
    assert full["accepted_worlds"] == rec["alloc"]["worlds"] + rec["report_fold"]["worlds"]
    assert all(total[k] == cheap[k] + full[k] for k in total)


def test_uniform_has_same_size_incumbent_and_no_network_or_extra_parent_rng():
    rnd = play_state()
    learned = CWVShortlistBot(Values(), seed=7)
    control = CWVShortlistBot(None, seed=7, config=CWVShortlistConfig(uniform=True))
    state = control.rng.getstate()
    expected_size = len(learned._candidates(rnd, rnd.turn))
    selected = control._candidates(rnd, rnd.turn)
    assert len(selected) == expected_size == 5
    assert selected[0] == learned.last_shortlist["incumbent"]
    assert control.shortlist_counts["cheap_evaluations"] == 0
    assert control.rng.getstate() == state
    again = CWVShortlistBot(None, seed=7, config=CWVShortlistConfig(uniform=True))
    assert again._candidates(rnd, rnd.turn) == selected


def test_hidden_twin_score_inputs_replace_hidden_hands_and_unknown_kitty():
    rnd = play_state()
    policy = REGISTRY["mc-s0-report-lcb"](seed=9)
    # Advance away from banker so the burial is genuinely hidden to the actor.
    rnd.play(rnd.turn, policy.canonical_lead(rnd, rnd.turn))
    seat = rnd.turn
    assert seat != rnd.banker
    worlds, _ = sample_worlds(policy, rnd, seat, 1)
    twin = copy.deepcopy(rnd)
    hidden = next(s for s in range(4) if s != seat and twin.hands[s])
    twin.hands[hidden][0], twin.buried[0] = twin.buried[0], twin.hands[hidden][0]
    action = enumerate_legal(rnd, seat, cap=None).actions[0]
    a = afterstate(rnd, seat, *worlds[0], action, finish_trick=True)
    b = afterstate(twin, seat, *worlds[0], action, finish_trick=True)
    assert round_signature(a) == round_signature(b)
    evaluator = Values()
    bot = CWVShortlistBot(evaluator)
    assert np.array_equal(bot._means(rnd, seat, [action], worlds),
                          bot._means(twin, seat, [action], worlds))


def test_underfill_refuses_and_restores_rng_without_fallback_ballot(monkeypatch):
    rnd = play_state()
    bot = CWVShortlistBot(Values())
    before = bot.rng.getstate()
    monkeypatch.setattr(bot, "_sample_hands", lambda *args: None)
    with pytest.raises(ValueError, match="^CWV shortlist cheap world population underfilled$"):
        bot.decide_play(rnd, rnd.turn)
    assert bot.rng.getstate() == before
    assert bot.last_decision_record is None


@pytest.mark.parametrize("bad", [[], [float("nan")]])
def test_bad_values_refuse(bad):
    rnd = play_state()
    bot = CWVShortlistBot(Values())
    bot.evaluator.score = lambda *args: np.asarray(bad)
    world = ([list(h) for h in rnd.hands], list(rnd.buried))
    action = enumerate_legal(rnd, rnd.turn, cap=None).actions[0]
    with pytest.raises(ValueError, match="^CWV shortlist requires one finite root-team value per afterstate$"):
        bot._means(rnd, rnd.turn, [action], [world])


def test_tractor_lock_cannot_bypass_exhaustive_candidate_stage(monkeypatch):
    # A production-locked lead still reaches the new candidate stage.
    from shengji.engine.combos import decompose
    rnd = next(r for r in (play_state(i) for i in range(100))
               if any(c.pair_len >= 2 for c in decompose(
                   REGISTRY["mc-s0-report-lcb"]().canonical_lead(r, r.turn), r.ordering).components))
    bot = CWVShortlistBot(None, config=CWVShortlistConfig(uniform=True))
    marker = ["sentinel"]
    calls = []
    monkeypatch.setattr(bot, "_candidates", lambda *args: calls.append(True) or [marker])
    assert bot.decide_play(rnd, rnd.turn) == marker
    assert calls == [True]
