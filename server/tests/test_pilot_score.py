"""Scoring invariants. Regret measured the wrong way is worse than no number.

Each test corresponds to a way the pilot could produce a clean-looking result
that means nothing.
"""
from __future__ import annotations

import random

import pytest

from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.pilot_arms import ARMS, propose
from shengji.pilot_folds import draw_folds
from shengji.pilot_score import (Scored, oracle_reference, report_regret,
                                 score_action, union_ballot)


def _lead_state(seed=779100):
    for k in range(40):
        game = Game(random.Random(seed + k))
        bots = [make_bot("smart") for _ in range(4)]
        rnd = game.start_round()
        while rnd.phase == "deal":
            s, _, _ = rnd.deal_next()
            cs = bots[s].decide_declare(rnd, s)
            if cs:
                rnd.declare(s, cs)
        rnd.finalize_declare()
        rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
        while rnd.phase == "play":
            s = rnd.turn
            if s is None:
                break
            if not rnd.trick.plays and len(rnd.history) >= 2:
                return rnd, s
            rnd.play(s, bots[s].decide_play(rnd, s))
    raise AssertionError("no lead state found")


def test_returns_are_per_world_not_a_mean():
    """Means cannot express that two arms saw the same worlds. The pilot's
    comparison is paired, so the vector has to survive."""
    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    mem = Memory(rnd, seat)
    fw = draw_folds(bot, rnd, seat, mem, {"proposal": 4, "oracle": 4, "report": 8},
                    salt="t", state_key="s")
    action = propose("current", bot, rnd, seat, budget=14, seed=1,
                     state_key="s")[0]
    s = score_action(bot, rnd, seat, fw.worlds["report"], action)
    assert len(s.returns) == 8, "one return per world, in fold order"
    assert s.mean == pytest.approx(sum(s.returns) / 8)


def test_paired_diff_refuses_unrelated_equal_length_vectors():
    """Equal length is not the same fold. Codex paired two unrelated vectors
    through the old check and got a plausible difference back."""
    a = Scored(action=("S3",), returns=[1.0, 2.0], state_key="k",
               fold="report", world_keys=("w1", "w2"))
    b = Scored(action=("S4",), returns=[3.0, 4.0], state_key="k",
               fold="report", world_keys=("w3", "w4"))
    with pytest.raises(ValueError, match="different worlds"):
        a.paired_diff(b)
    c = Scored(action=("S4",), returns=[3.0, 4.0], state_key="OTHER",
               fold="report", world_keys=("w1", "w2"))
    with pytest.raises(ValueError, match="cannot pair across"):
        a.paired_diff(c)


def test_empty_fold_fails_closed():
    """An empty fold used to mean 0.0 — so an empty oracle fold selected its
    first action and an empty report fold reported zero regret."""
    with pytest.raises(ValueError, match="empty fold"):
        Scored(action=("S3",), state_key="k", fold="report").mean


def test_union_ballot_covers_every_arm():
    """A reference drawn from one arm's ballot hands that arm zero regret."""
    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    ballots = {a: propose(a, bot, rnd, seat, budget=14, seed=1, state_key="s")
               for a in ARMS}
    u = {tuple(sorted(x)) for x in union_ballot(ballots)}
    for arm, b in ballots.items():
        assert {tuple(sorted(x)) for x in b} <= u, f"{arm} missing from union"


def test_oracle_is_chosen_on_the_oracle_fold_only():
    """The reference must not be re-chosen on report worlds.

    An argmax is biased upward by the noise it selected on. Choosing the
    reference on the same worlds that score the arms would make every arm's
    regret inherit that bias — the select-and-test defect, one level up.
    """
    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    mem = Memory(rnd, seat)
    fw = draw_folds(bot, rnd, seat, mem, {"proposal": 4, "oracle": 6, "report": 6},
                    salt="t", state_key="s")
    ballots = {a: propose(a, bot, rnd, seat, budget=14, seed=1, state_key="s")
               for a in ARMS}
    ref = oracle_reference(bot, rnd, seat, fw.worlds["oracle"],
                           union_ballot(ballots), state_key="s", expect=6)
    assert len(ref.returns) == 6, "the oracle scored on the ORACLE fold"

    # re-scoring the frozen action on report worlds must be a fresh estimate
    out = report_regret(bot, rnd, seat, fw.worlds["report"],
                        ballots["current"][0], list(ref.action),
                        state_key="s", expect=6)
    assert out["n_worlds"] == 6
    assert out["reference_mean"] != ref.mean or len(set(ref.returns)) == 1, \
        "the reference's ORACLE-fold mean was reused instead of re-scored"


def test_regret_is_zero_when_the_arm_plays_the_reference():
    """Sanity: same action, same worlds, no regret and no interval."""
    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    mem = Memory(rnd, seat)
    fw = draw_folds(bot, rnd, seat, mem, {"proposal": 2, "oracle": 2, "report": 6},
                    salt="t", state_key="s")
    action = propose("current", bot, rnd, seat, budget=14, seed=1,
                     state_key="s")[0]
    out = report_regret(bot, rnd, seat, fw.worlds["report"], action, action,
                        state_key="s", expect=6)
    assert out["regret"] == pytest.approx(0.0)
    assert all(d == 0 for d in
               [r - a for r, a in zip(out["reference_returns"],
                                      out["arm_returns"])])


def test_empty_union_is_refused():
    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    with pytest.raises(ValueError, match="empty union"):
        oracle_reference(bot, rnd, seat, [], [])


def test_scoring_is_deterministic_for_a_fixed_fold():
    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    mem = Memory(rnd, seat)
    fw = draw_folds(bot, rnd, seat, mem, {"proposal": 2, "oracle": 2, "report": 5},
                    salt="t", state_key="s")
    action = propose("current", bot, rnd, seat, budget=14, seed=1,
                     state_key="s")[0]
    a = score_action(bot, rnd, seat, fw.worlds["report"], action)
    b = score_action(bot, rnd, seat, fw.worlds["report"], action)
    assert a.returns == b.returns, "rollout scoring is not reproducible"


def test_choice_reproduces_deployed_margin_and_point_shy():
    """The arm must play what its POLICY would play, not the raw argmax.

    A pilot that compares ballots while ignoring selection compares something
    nobody would ship (Codex).
    """
    from shengji.pilot_score import choose_action

    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    mem = Memory(rnd, seat)
    fw = draw_folds(bot, rnd, seat, mem, {"proposal": 6, "oracle": 4, "report": 4},
                    salt="t", state_key="s")
    ballot = propose("current", bot, rnd, seat, budget=14, seed=1, state_key="s")
    got = choose_action(bot, rnd, seat, fw.worlds["proposal"], ballot,
                        state_key="s", expect=6)
    means = got["proposal_means"]
    if not got["kept_heuristic"]:
        assert means[got["index"]] - means[0] >= bot.MARGIN, \
            "overrode SmartBot without clearing the confidence margin"
    assert got["action"] in ballot


def test_choice_prefers_the_protected_action_on_a_tie():
    """MARGIN exists because rollouts are noisiest early; a tie must not
    override the heuristic prior."""
    from shengji.pilot_score import choose_action

    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    mem = Memory(rnd, seat)
    fw = draw_folds(bot, rnd, seat, mem, {"proposal": 4, "oracle": 2, "report": 2},
                    salt="t", state_key="s")
    ballot = propose("current", bot, rnd, seat, budget=14, seed=1, state_key="s")
    got = choose_action(bot, rnd, seat, fw.worlds["proposal"], ballot,
                        state_key="s", expect=4)
    m = got["proposal_means"]
    beat_margin = [i for i in range(len(m)) if i and m[i] - m[0] >= bot.MARGIN]
    if not beat_margin:
        assert got["kept_heuristic"], "nothing cleared the margin, yet it overrode"


def test_raw_points_and_brackets_are_preserved():
    """A scalar-policy change must be auditable without rerunning."""
    from shengji.pilot_score import bracket

    rnd, seat = _lead_state()
    bot = make_bot("mc", seed=4)
    mem = Memory(rnd, seat)
    fw = draw_folds(bot, rnd, seat, mem, {"proposal": 2, "oracle": 2, "report": 5},
                    salt="t", state_key="s")
    action = propose("current", bot, rnd, seat, budget=14, seed=1,
                     state_key="s")[0]
    s = score_action(bot, rnd, seat, fw.worlds["report"], action,
                     state_key="s", fold="report", expect=5)
    assert len(s.raw_points) == 5 and len(s.brackets) == 5
    assert all(b == bracket(p) for b, p in zip(s.brackets, s.raw_points))
    assert bracket(0) == -3 and bracket(80) == 0 and bracket(120) == 1
