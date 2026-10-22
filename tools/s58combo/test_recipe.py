"""Explicit package-backed admission tests, not a strength or latency run."""
import asyncio
import copy
import os
import random
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recipe import FLAGS, arm_envs, build_pair

ROOT = Path(__file__).resolve().parents[2]


def base():
    return tomllib.loads((ROOT / "fly.toml").read_text())["env"]


@pytest.mark.parametrize("key,value", [
    ("SHENGJI_PV_SERVING_BUDGET_SECONDS", "48"),
    ("SHENGJI_PV_EXACT_DEEP_CARDS", "8"),
    ("SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS", "8"),
    ("SHENGJI_PV_LEAF_GREEDY_FINISH", "1"),
])
def test_refuses_a_different_comparator(key, value):
    with pytest.raises(ValueError):
        arm_envs({**base(), key: value}, "play", "old", "new")


def test_env_delta_is_only_the_requested_combo():
    original = base()
    candidate, comparator = arm_envs(original, "play", "old", "new")
    assert original == base()
    assert {k for k in candidate if candidate[k] != comparator.get(k)} == {
        *FLAGS, "SHENGJI_PV_BELIEF_CKPT", "SHENGJI_PV_BELIEF_SHA256"}


def package_envs():
    return arm_envs(base(), os.environ["COMBO_PLAY_PACKAGE"],
                    os.environ["COMBO_OLD_BELIEF"], os.environ["COMBO_NEW_BELIEF"])


def test_wrong_belief_bytes_are_refused():
    from shengji.train.pv_search_policy import PVSearchPolicyError

    envs = package_envs()
    envs[0]["SHENGJI_PV_BELIEF_CKPT"] = os.environ["COMBO_OLD_BELIEF"]
    with pytest.raises(PVSearchPolicyError, match="sha256|SHA256|hash"):
        build_pair(envs)


def test_shared_policy_drift_is_not_hidden_by_matching_deltas():
    envs = package_envs()
    for env in envs:
        env["SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST"] = "0"
    with pytest.raises(ValueError, match="comparator is not release 46"):
        build_pair(envs)


@pytest.mark.parametrize("exact_tail", [False, True])
def test_real_combo_reaches_server_commit_and_trace(tmp_path, monkeypatch, exact_tail):
    from shengji.ai import belief_numpy as bn
    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv
    from shengji.engine.game import Game

    for key in list(os.environ):
        if key.startswith("SHENGJI_PV_"):
            monkeypatch.delenv(key)
    envs = package_envs()
    (name, bot), (control_name, control) = build_pair(envs)
    assert "-lgf-lgfx-" in name and "-dtrx-" in name
    assert control_name == base()["SHENGJI_BOT"]
    assert not control.leaf_greedy_finish
    # Correctness only: timing cannot substitute a fallback for the tested path.
    bot.serving_budget_seconds = 600
    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    rnd = prepare_round(Game(random.Random(17)), [HeuristicBot() for _ in range(4)])
    if exact_tail:
        helper = HeuristicBot()
        while max(map(len, rnd.hands)) > 3:
            rnd.play(rnd.turn, helper.decide_play(rnd, rnd.turn))
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="COMBO", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        count = len(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = copy.deepcopy(prepared.decision.snapshot.bot_copy.last_decision_record)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == count - len(prepared.decision.cards)
        return record

    record = asyncio.run(scenario())
    assert record["work_complete"] and record["worlds"] == 64
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    assert record["leaf_greedy_finish_exact_skipped"] == exact_tail
    if not exact_tail:
        assert record["leaf_greedy_finish_applied"]
        assert record["leaf_greedy_reply_plays"] > 0
    else:
        assert not record["leaf_greedy_finish_applied"]
        assert record["leaf_greedy_reply_plays"] == 0
    print(f"\n{name}: real S58 proposal -> greedy leaf -> server commit PASS")
