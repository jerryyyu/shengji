"""The exact lead's full-trick variant (``exact_lead_full_minimax``, ``elm``), OFF BY DEFAULT.

With ``SHENGJI_PV_EXACT_LEAD_FULL_MINIMAX=1`` (which needs the deeper exact
rule and the tie rule ``elt``) each candidate's exact leaf is the world right
after the lead, so the exact solve also plays the lead's own trick, instead of
the heuristic finishing it.  Off, release 50's name and decisions are main's
(`test_r50_flag_off_parity`).  On, the name gains ``-elm`` after ``-elt``, the
recipe carries the leaf's identity, and at SDUS round 2 trick 14 (a production
position where the heuristic-finished first trick misprices the lead) the
served bot leads the card that is better on the true deal.

Correctness and identity witnesses only, not a strength or latency claim.
"""
import json

import pytest

import r50_flag_positions as P
from shengji.ai.cwv_policy import afterstate
from shengji.ai.endgame import _clone_for_play
from shengji.ai.endgame_compact import CompactWorldSession
from shengji.engine import legal
from shengji.rl.value_afterstate import category_signed_level, signed_level_category
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_prior_admission import root_clone
from shengji.train.pv_exact_deep import exact_root_means
from test_release50_fly_config import fly_env  # release 50's env, lcc32 on
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA,  # noqa: F401
                                       PRIOR_VOLUME_PATH, RELEASE50, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages, served_bot)

FLAG = "SHENGJI_PV_EXACT_LEAD_FULL_MINIMAX"
TIE = "SHENGJI_PV_EXACT_LEAD_TIE_BASELINE"
#: release 50 with the tie rule and this variant on
ELM50 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-elt-elm-la-dtr-dtrx-vd-"
         "vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-rb1000f9b-bury-hybrid-bwv-bbw-"
         "e31b3dc5cf72-sc8")
#: release 50 with the tie rule alone (the variant's own control)
ELT50 = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-whl-whd-bw-tb-ele-elt-la-dtr-dtrx-vd-"
         "vdef-lgf-lgfx-lgfd2000-ed7-xf7-xfcompactlevel-lcc32-r379b379c-bury-hybrid-bwv-bbw-"
         "ab298d84c9fc-sc8")
#: the production lead where the heuristic-finished first trick misprices the lead
MISPRICED = ("SDUS2", 14, 0)
#: main's pick there (`test_r50_flag_off_parity`)
PINNED_PICK = json.loads(P.PINNED.read_text())["decisions"][P.label(*MISPRICED)]["cards"]


def names(monkeypatch, extra):
    """The name the registry derives from release 50's env plus ``extra``
    (package hashes stood in for the files)."""
    from shengji.ai import cwv_policy

    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    return list(pv.singleton_registry_entries(**pv.pv_env_recipe({**fly_env(), **extra})))


def attacker_points(rnd, seat, action) -> int:
    """True-deal perfect-information attacker points after ``action``."""
    child = _clone_for_play(rnd)
    child.play(seat, list(action))
    if child.phase == "round_end":
        return child.attacker_points
    return CompactWorldSession(rnd, max_hand_cards=7, max_nodes=50_000_000,
                               alpha_beta=True).solve(child).attacker_points


def test_recipe_carries_the_variant_only_when_on_and_refuses_it_alone():
    base = dict(checkpoint_sha256="f" * 64, exact_lead_endgame=True, exact_deep_cards=7,
                exact_lead_tie_baseline=True)
    off = pv.recipe_payload(pv.PVSearchConfig(**base))
    assert not {"exact_lead_full_minimax", "exact_lead_first_trick"} & set(off)
    on = pv.recipe_payload(pv.PVSearchConfig(**base, exact_lead_full_minimax=True))
    assert on == {**off, "exact_lead_full_minimax": True,
                  "exact_lead_first_trick": pv.EXACT_LEAD_FIRST_TRICK_MINIMAX}
    for change in ({"exact_deep_cards": 0}, {"exact_lead_tie_baseline": False},
                   {"exact_lead_policy_first": True}):
        config = pv.PVSearchConfig(**{**base, **change, "exact_lead_full_minimax": True})
        with pytest.raises(pv.PVSearchPolicyError, match="exact_lead_full_minimax requires"):
            pv.recipe_payload(config)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(**base, exact_lead_full_minimax=1))
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("elm") == tokens.index("elp") + 1
    assert pv.PVSearchBot.exact_lead_full_minimax is False


def test_served_name_gains_elm_only_when_on(monkeypatch):
    for off in ({}, {FLAG: "0"}, {FLAG: ""}):
        assert names(monkeypatch, off) == [RELEASE50]
    assert names(monkeypatch, {TIE: "1"}) == [ELT50]
    assert names(monkeypatch, {TIE: "1", FLAG: "1"}) == [ELM50]
    with pytest.raises(pv.PVSearchPolicyError, match="exact_lead_full_minimax requires"):
        names(monkeypatch, {FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        names(monkeypatch, {TIE: "1", FLAG: "yes"})


def test_lead_only_leaf_plays_the_lead_through_the_engine():
    # ADKY round 3 trick 11: seat 2's throw D7 D7 DA stood on the true deal
    rnd = P.replay("ADKY3", 11, 0)
    seat, throw = rnd.turn, ["D7", "D7", "DA"]
    true_hands = [list(h) for h in rnd.hands]
    world = [list(h) for h in true_hands]
    # the world that gives seat 0 the DJ pair, which beats the D7 pair
    world[0][world[0].index("S5")], world[3][world[3].index("DJ")] = "DJ", "S5"
    for hands, expected in ((true_hands, throw), (world, ["D7", "D7"])):
        root = root_clone(rnd, hands, list(rnd.buried))
        actual, _ = legal.validate_lead(throw, hands[seat], [hands[s] for s in range(4) if s != seat],
                                        rnd.ordering)
        assert sorted(actual) == sorted(expected)
        leaf = pv._lead_only_leaf(root, seat, hands, list(rnd.buried), throw, 0)
        assert [(p.seat, sorted(p.cards)) for p in leaf.trick.plays] == [(seat, sorted(expected))]
        assert leaf.turn == (seat + 1) % 4 and leaf.history == rnd.history
        # the root it was cloned from is untouched
        assert root.trick.plays == [] and sorted(root.hands[seat]) == sorted(rnd.hands[seat])


def test_lead_only_means_are_the_true_minimax_where_the_heuristic_finish_misprices():
    rnd = P.replay(*MISPRICED)
    seat = rnd.turn
    actions = [["D3"], ["D5"], ["HQ"]]
    world = [([list(h) for h in rnd.hands], list(rnd.buried))]

    def means(leaf):
        out, stats = exact_root_means(rnd, seat, actions, world, leaf, None, max_hand_cards=7,
                                      max_nodes=50_000_000)
        assert stats["worlds_completed"] == 1
        return list(out)

    truth = [category_signed_level(signed_level_category(attacker_points(rnd, seat, a),
                                                         rnd.is_attacker(seat)))
             for a in actions]
    assert means(pv._lead_only_leaf) == truth
    heuristic = means(lambda r, s, h, b, a, i: afterstate(r, s, h, b, a, finish_trick=True))
    assert heuristic != truth
    # the heuristic finish rates D3 at least as high as HQ; the true minimax does not
    assert heuristic[0] >= heuristic[2] and truth[2] > truth[0]


def test_served_bot_leads_the_truly_better_card_only_with_the_variant(release50_packages,
                                                                      monkeypatch):
    rnd = P.replay(*MISPRICED)
    seat = rnd.turn
    env = fly_env()
    picks = {}
    for label, extra, expected_name in (("off", {}, RELEASE50), ("elt", {TIE: "1"}, ELT50),
                                        ("elm", {TIE: "1", FLAG: "1"}, ELM50)):
        name, bot = served_bot(release50_packages, monkeypatch,
                               env={**env, **extra, "SHENGJI_BOT": expected_name}, seed=P.SEED)
        assert name == bot.policy_name == expected_name
        assert bot.exact_lead_full_minimax is (label == "elm")
        assert ("exact_lead_full_minimax" in vars(bot)) is (label == "elm")
        picks[label] = sorted(P.lift(bot).decide_play(rnd, seat))
        record = bot.last_decision_record
        assert record["exact_lead_status"] == "complete"
        assert (record.get("exact_lead_first_trick") == "minimax") is (label == "elm")
    # off and the tie rule alone keep the head's D3 (main's pinned pick); the
    # variant leads HQ, which the true deal prices 25 points better for the
    # defending seat
    assert picks["off"] == PINNED_PICK == picks["elt"] == ["D3"]
    assert picks["elm"] == ["HQ"]
    assert not rnd.is_attacker(seat)
    assert attacker_points(rnd, seat, ["HQ"]) == 100 < 125 == attacker_points(rnd, seat, ["D3"])



@pytest.mark.parametrize('cap', [1.8, 2.0, 2.25])
def test_lower_cap_reaches_minimax_and_keeps_baseline_on_expiry(
        release50_packages, monkeypatch, cap):
    import copy
    import numpy as np
    from shengji.train import pv_exact_deep
    from test_release50_fly_config import local_env

    env = {**local_env(release50_packages), TIE: '1', FLAG: '1',
           'SHENGJI_PV_EXACT_LEAD_MAX_SECONDS': str(cap)}
    recipe = pv.pv_env_recipe(env)
    entries = pv.singleton_registry_entries(**recipe)
    name, = entries
    if cap == 2.25:
        assert name == ELM50
    else:
        assert f'-els{round(cap * 1000)}-' in name and name != ELM50
    policy = entries[name](seed=7)
    assert policy.exact_lead_max_seconds == cap
    assert policy.exact_lead_full_minimax and policy.exact_lead_tie_baseline

    rnd = P.replay(*MISPRICED)
    actions = [['D3'], ['D5'], ['HQ']]
    worlds = [([list(h) for h in rnd.hands], list(rnd.buried))]
    base = (np.zeros(3), 1, 0, actions[0], 2)
    policy._tiebreak = {'baseline': True}
    before = copy.deepcopy(policy._tiebreak)
    clock = [0.0]
    monkeypatch.setattr(pv.time, 'perf_counter', lambda: clock[0])
    original = pv_exact_deep.exact_root_means
    entered = []

    def elapsed(*args, **kwargs):
        assert args[4] is pv._lead_only_leaf
        entered.append(True)
        policy._tiebreak = {'partial': True}
        # Exercise the real leaf/scorer guard with elapsed time below the default cap.
        clock[0] = 2.01
        return original(*args, **kwargs)

    monkeypatch.setattr(pv_exact_deep, 'exact_root_means', elapsed)
    result = policy._exact_lead_decision(rnd, rnd.turn, actions, worlds, 0.0,
                                         None, [0.0] * 3, base)
    state = policy._exact_lead
    assert entered == [True] and state['exact_lead_first_trick'] == 'minimax'
    assert state['exact_lead_seconds'] == 2.01
    if cap < 2.01:
        assert result is base
        assert state['exact_lead_status'] == 'abandoned'
        assert state['exact_lead_abandon_reason'] == 'soft_budget'
        assert state['exact_lead_worlds_completed'] is None
        assert policy._tiebreak == before
    else:
        assert state['exact_lead_status'] == 'complete'
        assert state['exact_lead_worlds_completed'] == 1


#: the five combo51 lines: the candidate arm adds them, the control arm is the env without
#: them (release 51), whichever of the two the served fly.toml carries
COMBO51 = {TIE: "1", FLAG: "1", "SHENGJI_PV_EXACT_LEAD_MAX_SECONDS": "1.6",
           "SHENGJI_PV_WORLD_HISTORY_THROWS": "1", "SHENGJI_PV_REFUSAL_EVENT_COMPLETE": "1"}


@pytest.mark.parametrize("candidate, expire, expected", [
    (False, False, ["D3"]), (True, False, ["HQ"]), (True, True, ["D3"]),
])
def test_combo_lead_keeps_serving_budgets_through_server_commit(
        release50_packages, tmp_path, monkeypatch, candidate, expire, expected):
    """The candidate corrects the replayed lead through a budgeted server turn."""
    import asyncio
    import random
    import time
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from test_release46_fly_config import fly_env as production_env
    from test_release50_fly_config import local_env
    from shengji.eval.served_config import registry_name

    control = {k: v for k, v in production_env().items() if k not in COMBO51}
    env = {**control, **COMBO51} if candidate else control
    assert candidate or not set(COMBO51) & set(env)
    env["SHENGJI_BOT"] = registry_name(local_env(release50_packages, env))
    name, bot = served_bot(release50_packages, monkeypatch, env=env, seed=P.SEED)
    assert bot.serving_budget_seconds == 3.0
    if candidate:
        assert bot.exact_lead_max_seconds == 1.6
    assert bot.leaf_greedy_deadline_ms == 2000
    if expire:
        from shengji.train import pv_exact_deep
        original = pv_exact_deep.exact_root_means
        real_clock = time.perf_counter

        def expired(*args, **kwargs):
            # Expire inside the real solver, after the server has admitted the turn.
            with monkeypatch.context() as clock_patch:
                clock_patch.setattr(time, "perf_counter", lambda: real_clock() + 1.61)
                return original(*args, **kwargs)

        monkeypatch.setattr(pv_exact_deep, "exact_root_means", expired)
    rnd = P.replay(*MISPRICED)
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="COMBO", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        start = time.monotonic()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        elapsed = time.monotonic() - start
        assert prepared is not None
        searched = prepared.decision.snapshot.bot_copy
        record = searched.last_decision_record
        cards = list(prepared.decision.cards)
        print({"candidate": candidate, "expire": expire, "elapsed": elapsed, "cards": cards,
               "exact_seconds": record.get("exact_lead_seconds"),
               "worlds": record.get("exact_lead_worlds_completed")})
        assert searched.policy_name == name
        assert searched.serving_budget_seconds == 3.0
        if candidate:
            assert searched.exact_lead_max_seconds == 1.6
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(cards)
        assert cards == expected
        if expire:
            assert record["exact_lead_status"] == "abandoned"
            assert record["exact_lead_abandon_reason"] == "soft_budget"
            assert record["exact_lead_worlds_completed"] is None
        else:
            assert record["exact_lead_status"] == "complete"
            assert record["exact_lead_worlds_completed"] == 64
        if candidate and not expire:
            assert record["exact_lead_first_trick"] == "minimax"
            assert record["exact_lead_base_played"] == ["D3"]
            assert record["exact_lead_changed"]
        elif not candidate:
            assert "exact_lead_first_trick" not in record
        assert record["belief_fallback"] == 0

    asyncio.run(scenario())
