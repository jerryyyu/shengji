"""Torch-free tests for the counterfactual value diagnostic (#663 step 3)."""
from __future__ import annotations

import math
import random

import numpy as np
import pytest

from shengji.train import cf_value_diagnostic as cf
from shengji.train import pv_search_policy as pv
from shengji.train.pv_search_policy import PVSearchBot, PVSearchConfig
from test_policy_world_search import state


# ------------------------------------------------------------------ helpers

def _row(key, phase, bucket):
    return {"key": key, "phase": phase, "bucket": bucket, "seat": 0}


class StubEvaluator:
    """One finite score per leaf, a deterministic function of the leaf's hand."""
    backend = "numpy"

    def __init__(self):
        self.calls = 0

    def score(self, leaves, seat):
        self.calls += 1
        return [((hash(tuple(r.hands[seat])) % 1000) / 1000.0) - 0.5 for r in leaves]


def _stub_bot(worlds=2, candidates=3):
    predict = lambda x: np.tile(np.arange(54, dtype=float), (len(x), 1))  # noqa: E731
    config = PVSearchConfig(checkpoint_sha256="0" * 64, worlds=worlds, candidates=candidates,
                            cap=4000, batch_size=128, serving_budget_seconds=None)
    return PVSearchBot(predict, evaluator=StubEvaluator(), version=2, config=config, checkpoint="stub")


# ------------------------------------------------------------------ sampler

def test_sampler_is_deterministic_and_stratified():
    rows = [_row(f"k{i}", cf.PHASES[i % 4], cf.TRICK_BUCKETS[(i // 4) % 5]) for i in range(200)]
    a = cf.sample_audit_set(rows, n=40, seed=7)
    b = cf.sample_audit_set(list(reversed(rows)), n=40, seed=7)
    assert [r["key"] for r in a] == [r["key"] for r in b]
    assert [r["index"] for r in a] == list(range(40))
    c = cf.sample_audit_set(rows, n=40, seed=8)
    assert [r["key"] for r in c] != [r["key"] for r in a]
    strata = {}
    for r in a:
        strata[(r["phase"], r["bucket"])] = strata.get((r["phase"], r["bucket"]), 0) + 1
    assert len(strata) == 20 and set(strata.values()) == {2}   # 40 over 20 strata, balanced


def test_sampler_fills_from_other_strata_and_drops_duplicates():
    rows = [_row("dup", "lead-single", "t00-04"), _row("dup", "lead-single", "t00-04")]
    rows += [_row(f"f{i}", "follow-multi", "t20+") for i in range(10)]
    chosen = cf.sample_audit_set(rows, n=6, seed=1)
    keys = [r["key"] for r in chosen]
    assert keys.count("dup") == 1 and len(keys) == 6 and len(set(keys)) == 6
    with pytest.raises(cf.AuditError):
        cf.sample_audit_set(rows, n=0, seed=1)


def test_audit_row_filters_and_phases():
    base = {"decision_kind": "play", "deck": ["x"], "action": ["S2", "S2"], "legal_actions_count": 5,
            "ply": 5, "trick": 1, "source_ref": "r:1", "seat": 1, "setup": {}, "plays_prefix": []}
    row = cf.audit_row(base, source="s")
    assert row["phase"] == "follow-multi" and row["bucket"] == "t00-04" and row["key"] == "r:1"
    assert cf.audit_row({**base, "decision_kind": "bury"}, source="s") is None
    assert cf.audit_row({**base, "legal_actions_count": 1}, source="s") is None
    assert cf.audit_row({**base, "deck": None}, source="s") is None
    assert cf.phase_of(8, ["S2"]) == "lead-single"
    assert cf.trick_bucket(23) == "t20+"


# ------------------------------------------------------------ shared worlds

def test_shared_worlds_are_a_pure_function_of_the_seed():
    rnd = state(); seat = rnd.turn
    w1, _ = cf.shared_worlds(rnd, seat, 3, seed=cf.world_seed(5, 2))
    w2, _ = cf.shared_worlds(rnd, seat, 3, seed=cf.world_seed(5, 2))
    assert cf.worlds_digest(w1) == cf.worlds_digest(w2) and len(w1) == 3
    w3, _ = cf.shared_worlds(rnd, seat, 3, seed=cf.world_seed(5, 3))
    assert cf.worlds_digest(w3) != cf.worlds_digest(w1)
    assert cf.world_seed(1, 0) != cf.world_seed(0, 1)


def test_short_sampling_refuses(monkeypatch):
    rnd = state(); seat = rnd.turn
    monkeypatch.setattr(cf, "sample_worlds", lambda *a, **k: ([], 0))
    with pytest.raises(cf.AuditError, match="short"):
        cf.shared_worlds(rnd, seat, 2, seed=1)


# -------------------------------------------------------------------- union

def test_union_order_dedup_played_and_extras():
    admitted = {"current": [("S3", "S2"), ("S4",)], "previous": [("S2", "S3"), ("S5",)]}
    legal = [("S2", "S3"), ("S4",), ("S5",), ("S6",), ("S7",), ("S8",), ("S9",)]
    union = cf.build_union(admitted, ("S9",), legal, extras=2, rng=random.Random(3))
    assert union[:4] == [("S2", "S3"), ("S4",), ("S5",), ("S9",)]
    assert len(union) == 6 and len(set(union)) == 6
    assert set(union[4:]) <= {("S6",), ("S7",), ("S8",)}
    again = cf.build_union(admitted, ("S9",), legal, extras=2, rng=random.Random(3))
    assert again == union
    assert len(cf.build_union(admitted, ("S9",), legal, extras=50, rng=random.Random(0))) == 7


# ------------------------------------------------------------------ metrics

def _table():
    union = [("A",), ("B",), ("C",), ("D",), ("E",)]
    return {
        "union": union, "played": ("C",),
        "heads": {"current": {"admitted": [("A",), ("B",), ("C",)], "decision": ("B",)},
                  "previous": {"admitted": [("A",), ("D",)], "decision": ("D",)}},
        # current:  B best overall (0.5), then D (0.4), A 0.1, C 0.0, E -1
        # previous: D best overall (0.9), then B (0.3), A 0.2, C 0.1, E 0.0
        "values": {"current": [0.1, 0.5, 0.0, 0.4, -1.0], "previous": [0.2, 0.3, 0.1, 0.9, 0.0]},
    }


def test_metric_arithmetic_on_hand_built_table():
    m = cf.position_metrics(_table(), tie_eps=0.02)
    assert m["admission.jaccard"] == pytest.approx(1 / 4)          # {A} over {A,B,C,D}
    assert m["admission.same_set"] is False
    assert m["admission.played_in_current"] is True and m["admission.played_in_previous"] is False
    assert m["admission.current_decision_in_previous"] is False
    assert m["admission.previous_decision_in_current"] is False
    assert m["admission.loss_current"] == pytest.approx(0.0)       # B admitted and best
    assert m["admission.loss_previous"] == pytest.approx(0.0)      # D admitted and best
    assert m["admission.union_argmax_admitted_current"] is True
    assert m["ranking.top1_agree"] is False                         # B vs D
    assert m["ranking.regret_current_under_previous"] == pytest.approx(0.9 - 0.3)
    assert m["ranking.regret_previous_under_current"] == pytest.approx(0.5 - 0.4)
    # swap: current value head, argmax over {A,B,C} = B (0.5), over {A,D} = D (0.4) -> flip, gap +0.1
    assert m["swap.flip_current"] is True and m["swap.gap_current"] == pytest.approx(0.1)
    # previous value head: over {A,B,C} = B (0.3), over {A,D} = D (0.9) -> flip, gap -0.6
    assert m["swap.flip_previous"] is True and m["swap.gap_previous"] == pytest.approx(-0.6)
    assert m["neartie.current_admitted"] is False                   # 0.5 - 0.1
    assert m["neartie.previous_admitted"] is False                  # 0.9 - 0.2
    assert m["outcome.agree"] is False and m["outcome.cause"] == "admission"
    assert m["outcome.current_matches_record"] is False
    assert m["outcome.current_is_union_argmax"] is True and m["outcome.previous_is_union_argmax"] is True
    rho = m["ranking.spearman"]
    assert -1 < rho < 1


def test_ranking_cause_and_near_tie():
    t = _table()
    t["heads"]["previous"]["admitted"] = [("A",), ("B",), ("C",)]
    t["heads"]["previous"]["decision"] = ("A",)
    t["values"]["previous"] = [0.30, 0.31, 0.1, 0.9, 0.0]
    m = cf.position_metrics(t)
    assert m["outcome.cause"] == "ranking"
    assert m["neartie.previous_admitted"] is True                   # 0.31 - 0.30 < 0.02
    assert m["admission.loss_previous"] == pytest.approx(0.9 - 0.31)
    assert m["admission.union_argmax_admitted_previous"] is False
    assert m["swap.flip_previous"] is False


def test_metrics_refuse_incomplete_tables():
    t = _table(); t["played"] = ("Z",)
    with pytest.raises(cf.AuditError, match="played"):
        cf.position_metrics(t)
    t = _table(); t["values"]["current"] = [0.0]
    with pytest.raises(cf.AuditError, match="cover"):
        cf.position_metrics(t)


def test_spearman_and_aggregate():
    assert cf.spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert cf.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert math.isnan(cf.spearman([1, 1, 1], [1, 2, 3]))
    agg = cf.aggregate([{"b": True, "f": 1.0, "s": "x"}, {"b": False, "f": float("nan"), "s": "x"},
                        {"b": True, "f": 3.0, "s": "y"}])
    assert agg["n"] == 3
    assert agg["b"] == {"n": 3, "count": 2, "frac": pytest.approx(2 / 3)}
    assert agg["f"]["n"] == 2 and agg["f"]["nan"] == 1 and agg["f"]["mean"] == pytest.approx(2.0)
    assert agg["s"]["counts"] == {"x": 2, "y": 1}
    strat = cf.stratified([{"phase": "lead-single", "bucket": "t00-04"}], [{"b": True}])
    assert set(strat) == {"overall", "phase:lead-single", "bucket:t00-04"}


# ---------------------------------------------------------------- admission

def test_admission_runs_the_served_search_and_admit_on_the_shared_worlds(monkeypatch):
    rnd = state(); seat = rnd.turn
    bot = _stub_bot(worlds=2, candidates=3)
    worlds, _ = cf.shared_worlds(rnd, seat, 2, seed=11)
    spy = {}
    real_admit = PVSearchBot._admit
    real_scores = PVSearchBot.scores

    def admit(self, rnd_, seat_, actions, preferences, anchor_index):
        chosen = real_admit(self, rnd_, seat_, actions, preferences, anchor_index)
        spy["chosen"] = [actions[i] for i in chosen]
        spy["anchor_index"] = anchor_index
        return chosen

    def own_worlds(self, *a, **k):
        raise AssertionError("the bot must not draw its own worlds")

    def scores(self, rnd_, seat_, actions, worlds_seen):
        spy["worlds"] = cf.worlds_digest(worlds_seen)
        return real_scores(self, rnd_, seat_, actions, worlds_seen)

    monkeypatch.setattr(pv.PVSearchBot, "_admit", admit)
    monkeypatch.setattr(pv.PVSearchBot, "_worlds", own_worlds)
    monkeypatch.setattr(pv.PVSearchBot, "scores", scores)
    out = cf.admission_under(bot, rnd, seat, worlds)
    assert spy["worlds"] == cf.worlds_digest(worlds)
    assert out["admitted"] == [cf.action_key(a) for a in spy["chosen"]]
    assert len(out["admitted"]) == 3 and out["admitted"][0] == cf.action_key(out["anchor"])
    assert spy["anchor_index"] == 0 or spy["chosen"][0] == tuple(out["anchor"]) or \
        cf.action_key(spy["chosen"][0]) == cf.action_key(out["anchor"])
    assert out["decision"] in out["admitted"]
    assert len(out["search_means"]) == 3 and len(out["policy_log_odds"]) == 3
    assert "_worlds" not in bot.__dict__          # the substitution did not leak
    assert bot.last_decision_record["worlds"] == 2


def test_value_table_uses_the_served_reducer():
    rnd = state(); seat = rnd.turn
    bot = _stub_bot(worlds=3)
    worlds, _ = cf.shared_worlds(rnd, seat, 3, seed=2)
    hand = rnd.hands[seat]
    union = sorted({(c,) for c in hand})[:2]
    table = cf.value_table(bot, rnd, seat, union, worlds)
    matrix, sums, _ = bot.value_matrix(rnd, seat, [list(k) for k in union], worlds)
    assert table["means"] == pytest.approx(list(sums / 3))
    assert len(table["se"]) == 2 and all(math.isfinite(v) for v in table["se"])


def test_run_position_builds_a_complete_table():
    rnd = state(); seat = rnd.turn
    bots = {"current": _stub_bot(worlds=2, candidates=3), "previous": _stub_bot(worlds=2, candidates=2)}
    played = [rnd.hands[seat][0]]
    row = {"key": "k", "index": 4, "seat": seat, "played": played, "phase": "lead-single",
           "bucket": "t00-04", "trick": 0, "legal_count": 9}
    from shengji.harvest.legal import enumerate_legal
    legal_fn = lambda r, s, p: list(enumerate_legal(r, s, cap=4000, must_include=[list(p)]).actions)  # noqa: E731
    table = cf.run_position(row, bots, worlds_n=2, extras=2, seed=9, rebuild=lambda r: rnd, legal_fn=legal_fn)
    assert table["schema"] == cf.SCHEMA_TABLE and table["worlds"] == 2
    union = [tuple(k) for k in table["union"]]
    assert tuple(sorted(played)) in union
    for head, info in table["heads"].items():
        assert all(tuple(k) in union for k in info["admitted"])
        assert tuple(info["decision"]) in union
        assert len(table["values"][head]) == len(union)
    assert len(union) <= 3 + 2 + 1 + 2
    metrics = cf.position_metrics(table)
    assert set(metrics) >= {"admission.jaccard", "ranking.spearman", "swap.flip_current", "outcome.cause"}
    again = cf.run_position(row, bots, worlds_n=2, extras=2, seed=9, rebuild=lambda r: rnd, legal_fn=legal_fn)
    assert again["worlds_sha256"] == table["worlds_sha256"] and again["union"] == table["union"]


def test_markdown_summary_renders():
    result = {"config": {"audit": "a.jsonl", "audit_sha256": "ab" * 32, "worlds": 2, "extras": 1, "seed": 0,
                         "tie_eps": 0.02, "heads": {"current": {"sha256": "1" * 64}, "previous": {"sha256": "2" * 64}}},
              "stratified": cf.stratified([{"phase": "lead-single", "bucket": "t00-04"}],
                                          [cf.position_metrics(_table())])}
    text = cf.markdown_summary(result)
    assert "| n | 1 | 1 | 1 |" in text and "admission" in text and "Disagreement cause" in text
