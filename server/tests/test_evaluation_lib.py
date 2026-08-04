"""Guards on the one evaluator, now that six runners collapsed into it.

The consolidation is only a win if the invariants that were scattered across
those runners survive in one place. Each test below corresponds to a way a
real claim was lost.
"""
from __future__ import annotations

import json
import random

import pytest

from shengji.evaluation import (ProtocolFailure, arm_ballots, clustered_win_rate,
                                counters, paired_by_seed, parse_bar, run_arm)


def _rec(seed, flip, util, label="arm"):
    return {"run": "t", "label": label, "policy": "p", "seed": seed,
            "flip": flip, "won": int(util > 0), "level_utility": util,
            "arm": counters([]), "opp": counters([])}


def test_paired_stats_cluster_by_seed_not_by_round():
    """The error that killed six claims: treating correlated flips as n=2.

    Two flips of one seed share a deal. Clustering keeps them as ONE unit; not
    clustering doubles the apparent sample and shrinks the interval by ~sqrt2.
    """
    a = [_rec(1, 0, 2), _rec(1, 1, 2), _rec(2, 0, -2), _rec(2, 1, -2)]
    b = [_rec(1, 0, 0), _rec(1, 1, 0), _rec(2, 0, 0), _rec(2, 1, 0)]
    m, ci, n = paired_by_seed(a, b)
    assert n == 2, "four rounds over two deals is TWO clusters, not four"
    assert m == pytest.approx(0.0)


def test_paired_difference_is_per_seed_sum():
    a = [_rec(5, 0, 3), _rec(5, 1, 1)]
    b = [_rec(5, 0, 1), _rec(5, 1, 1)]
    m, ci, n = paired_by_seed(a, b)
    assert n == 1 and m == pytest.approx(2.0)
    assert ci == float("inf"), \
        "one cluster has a known centre and an unknown spread; it must not " \
        "report a finite interval, and must not zero out the mean"


def test_win_rate_is_also_clustered():
    recs = [_rec(1, 0, 1), _rec(1, 1, 1), _rec(2, 0, -1), _rec(2, 1, -1)]
    value, half = clustered_win_rate(recs)
    assert value == pytest.approx(0.5)
    assert half > 0, "a two-cluster estimate must carry a real interval"


def test_a_bar_must_be_machine_checkable():
    """A bar recorded but not applied is theatre; free text cannot gate."""
    for bad in ("should be better", "paired_utility improves", "> 0", ""):
        with pytest.raises(ProtocolFailure):
            parse_bar(bad)
    assert parse_bar("paired_utility > 0") == ("paired_utility", 0.0)
    assert parse_bar(" win_rate > 0.55 ") == ("win_rate", 0.55)


def test_bar_is_parsed_before_compute_is_spent():
    """parse_bar is called first in evaluate(), so a typo fails in a second."""
    import inspect

    from shengji import evaluation
    src = inspect.getsource(evaluation.evaluate)
    assert src.index("parse_bar") < src.index("run_arm"), \
        "an unenforceable bar must be caught before a multi-hour run starts"


def test_run_arm_gives_every_seat_a_distinct_seed(tmp_path, monkeypatch):
    """The seed-dropping lambda lived in five runners at once.

    If a factory ignores the seed kwarg, all four seats share an RNG state and
    the mirrored pair stops being a fair comparison. Guarded here now that the
    runners that carried the bug are gone.
    """
    made = []

    def fake_make_bot(name, seed=None):
        made.append((name, seed))
        return type("B", (), {"rng": random.Random(seed)})()

    class FakeLog:
        winner_team = 0
        level_change = 1

    monkeypatch.setattr("shengji.evaluation.make_bot", fake_make_bot)
    monkeypatch.setattr("shengji.evaluation.play_round",
                        lambda *a, **k: FakeLog())
    path = tmp_path / "recs.jsonl"
    with open(path, "w") as fh:
        run_arm("arm", "p", "q", clusters=2, seed0=100, fh=fh, run_id="r",
                progress=False)

    seeds_per_call = [s for _, s in made]
    assert None not in seeds_per_call, "a factory dropped the seed kwarg"
    # four distinct bots per round, and the two flips of a seed reuse the deal
    per_round = [seeds_per_call[i:i + 4] for i in range(0, len(seeds_per_call), 4)]
    for quad in per_round:
        assert len(set(quad)) == 4, f"seats share a seed: {quad}"


def test_run_arm_pairs_both_flips_on_the_same_deal(tmp_path, monkeypatch):
    """Mirroring is worthless if the two flips are dealt differently."""
    dealt = []

    monkeypatch.setattr("shengji.evaluation.make_bot",
                        lambda name, seed=None: object())

    class FakeLog:
        winner_team = 0
        level_change = 1

    def fake_play_round(game, pol):
        dealt.append(game)
        return FakeLog()

    monkeypatch.setattr("shengji.evaluation.play_round", fake_play_round)
    monkeypatch.setattr("shengji.evaluation.Game", lambda rng: rng.random())
    with open(tmp_path / "r.jsonl", "w") as fh:
        run_arm("arm", "p", "q", clusters=3, seed0=7, fh=fh, run_id="r",
                progress=False)
    # flips 0 and 1 of each cluster must have been dealt from the same seed
    for i in range(0, 6, 2):
        assert dealt[i] == dealt[i + 1], "the two flips used different deals"


def test_records_are_json_serialisable(tmp_path, monkeypatch):
    monkeypatch.setattr("shengji.evaluation.make_bot",
                        lambda name, seed=None: object())

    class FakeLog:
        winner_team = 1
        level_change = 2

    monkeypatch.setattr("shengji.evaluation.play_round",
                        lambda *a, **k: FakeLog())
    p = tmp_path / "r.jsonl"
    with open(p, "w") as fh:
        recs = run_arm("arm", "p", "q", 1, 0, fh, "r", progress=False)
    on_disk = [json.loads(x) for x in open(p)]
    assert on_disk == recs
    assert recs[0]["level_utility"] == -2, "loser's utility is negative and scaled"


def test_unknown_policy_is_a_protocol_failure_not_a_guess():
    with pytest.raises(ProtocolFailure, match="cannot determine the ballot"):
        arm_ballots(["mc", "no-such-policy-xyz"])


def test_ballots_distinguish_policies_that_search_from_ones_that_do_not():
    b = arm_ballots(["mc", "smart"])
    assert b["mc"] != b["smart"]
    assert b["smart"].startswith("none@")


def test_null_control_differs_from_mc_only_in_its_random_draws():
    """`mc-null` is the control the N=30 confirmation depends on.

    If it ever drifts into being a different POLICY, it stops being a null and
    the confirmation silently loses its attribution. The first dose rerun was
    voided for the mirror-image mistake: passing `mc-strong`, a stronger
    treatment, where the evaluator expects an arm that should not work.
    """
    from shengji.ai.registry import make_bot
    from shengji.engine.ballot import ballot_for_policy

    null, base = make_bot("mc-null", seed=7), make_bot("mc", seed=7)
    assert ballot_for_policy("mc-null").digest == ballot_for_policy("mc").digest
    differing = [a for a in dir(base)
                 if a.isupper() and getattr(null, a, None) != getattr(base, a, None)]
    assert not differing, f"mc-null is not a null: it differs in {differing}"
    assert null.rng.getstate() != base.rng.getstate(), \
        "mc-null must draw differently, or it measures nothing"
