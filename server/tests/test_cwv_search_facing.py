"""Search-facing validation of the complete-world value net
(``cwv_eval.search_facing_metrics`` / ``train_cwv --select-metric`` /
``--init``): witnesses, each with the mutation that turns it RED.

1. Rank regret on a hand-built candidate set: a scorer whose argmax is the
   search's best has regret 0 and top-1 1; an inverted ranking has the
   maximal regret (the set's mean spread); the level scale is the search's
   (RED: a flipped sign in the regret -> the perfect scorer is no longer 0
   / the inverted one no longer maximal).
2. Points head metrics: MAE, bias (pred - real) and the below-banked
   fraction on hand-built rows (RED: bias computed real - pred).
3. Selection on synthetic per-epoch metrics: ``val_ce`` and
   ``val_rank_regret`` pick DIFFERENT epochs and stop at different times;
   an unknown metric or a block without the key is refused.
4. Warm start: ``--init`` loads trunk + heads (the init validation equals
   the source checkpoint's own val CE within 1e-4 and a zero-lr epoch keeps
   it); a hidden-width mismatch is refused (RED mutation: change --hidden).
5. The same function feeds the per-epoch validation, the final val/test
   pass and ``evaluate`` (``evaluate`` reproduces the receipt's test block)
   and the receipt carries the ``consumer`` block.
6. Cumulative exposure (Codex HOLD on PR #242): a checkpoint trained on
   population P1 warm-started on P2 > P1 with the same seed puts a P1-fit
   deal into P2's val/test -> refused naming the counts; with
   ``init_exclude_exposed`` it runs and the receipt's excluded counts equal
   the migrated deals (never added to train); a disjoint warm start works
   unchanged; the exposure is the union and ``evaluate --split novel``
   consults it (RED: disabling ``exposure_conflict``).
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.rl.value_afterstate import (  # noqa: E402
    N_CARDS,
    PUBLIC_DIM,
    WORLD_RECEIVERS,
    category_signed_level,
    signed_level_category,
)
from shengji.train import cwv_eval, train_cwv, train_v0  # noqa: E402

from test_cwv_train import (  # noqa: E402, F401  (module fixtures)
    EXPLORE,
    SEED0,
    THIRDS,
    WORK,
    _records,
    other_dir,
    other_records,
    records,
    store_dir,
)
from shengji.harvest import trajectory  # noqa: E402
from shengji.train.data import split_deals  # noqa: E402
from shengji.train.cwv_data import deal_key  # noqa: E402


# 1 ---------------------------------------------------------- rank regret

def _entry(means, role_attacker, terminal=None):
    k = len(means)
    return {
        "public": np.zeros((k, PUBLIC_DIM), np.float32),
        "world": np.zeros((k, WORLD_RECEIVERS, N_CARDS), np.uint8),
        "perspective": np.full(k, 1 if role_attacker else 0, np.uint8),
        "terminal": np.zeros(k, bool) if terminal is None else np.asarray(terminal, bool),
        "terminal_level": np.zeros(k, np.float64),
        "means": np.asarray(means, np.float64),
        "deal_key": "deck:x", "source_ref": f"r{role_attacker}:{k}",
        "role_attacker": bool(role_attacker),
    }


def _level(points, attacker):
    return category_signed_level(signed_level_category(int(points), attacker))


def test_rank_regret_perfect_zero_inverted_maximal():
    # an attacker's decision: means in attacker points; a defender's: negated
    entries = [_entry([100.0, 30.0, 150.0], True), _entry([-10.0, -90.0, -50.0, -130.0], False)]
    cands = cwv_eval.CandidateSet.concatenate(entries, {"schema": cwv_eval.CANDIDATE_SET_SCHEMA},
                                              history=False)
    assert cands.records == 2 and cands.candidates == 7
    # the level scale is the search's: category_signed_level of the mean's bracket
    ml = cands.means_level()
    assert ml[:3].tolist() == [_level(100, True), _level(30, True), _level(150, True)]
    assert ml[3:].tolist() == [_level(10, False), _level(90, False), _level(50, False),
                               _level(130, False)]
    assert ml[0] == 0.5 and ml[2] == 1.5 and ml[3] == 2.5 and ml[4] == -0.5
    # a fake model whose ranking IS the search's: regret 0, top-1 1
    perfect = cwv_eval.rank_metrics(ml.copy(), cands)
    assert perfect["rank_regret"] == 0.0 and perfect["rank_regret_points"] == 0.0
    assert perfect["rank_top1"] == 1.0 and perfect["rank_records"] == 2
    # a deliberately inverted ranking: the maximal regret (best minus worst)
    inverted = cwv_eval.rank_metrics(-ml, cands)
    spread = np.mean([ml[:3].max() - ml[:3].min(), ml[3:].max() - ml[3:].min()])
    assert inverted["rank_regret"] == pytest.approx(spread)
    assert inverted["rank_regret"] == pytest.approx(inverted["rank_regret_max"])
    assert inverted["rank_regret_points"] == pytest.approx(np.mean([150 - 30, -10 + 130]))
    assert inverted["rank_top1"] == 0.0
    assert 0.0 < perfect["rank_regret_max"] == inverted["rank_regret_max"]
    # a tie among the scorer's maxima is a uniform draw
    tied = cwv_eval.rank_metrics(np.zeros(7), cands)
    assert tied["rank_top1"] == pytest.approx(np.mean([1 / 3, 1 / 4]))
    assert tied["rank_regret"] == pytest.approx(np.mean([ml[:3].max() - ml[:3].mean(),
                                                         ml[3:].max() - ml[3:].mean()]))
    # RED: the sign flipped inside the regret (search best minus pick ->
    # pick minus search best) makes the perfect scorer's regret negative
    # and the inverted one's the negated spread -- both refused here
    flipped = -(perfect["rank_regret"]) if perfect["rank_regret"] else 0.0
    assert flipped == 0.0 and -inverted["rank_regret"] < 0 < inverted["rank_regret"]
    with pytest.raises(cwv_eval.EvalError, match="misaligned"):
        cwv_eval.rank_metrics(np.zeros(6), cands)
    # terminal candidates carry their exact level through candidate_levels
    term = _entry([100.0, 30.0], True, terminal=[True, False])
    term["terminal_level"][0] = 1.5
    cset = cwv_eval.CandidateSet.concatenate([term], {"schema": cwv_eval.CANDIDATE_SET_SCHEMA},
                                             history=False)
    logits = torch.zeros(2, 204)
    levels = cwv_eval.candidate_levels(lambda t: logits[: t["public"].shape[0]], cset, "cpu")
    assert levels[0] == 1.5 and levels[1] == pytest.approx(0.0, abs=1e-9)
    # save / load round trip keeps every array
    path = None
    try:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.npz"
            cands.save(path)
            back = cwv_eval.CandidateSet.load(path)
            assert back.records == 2 and np.array_equal(back.means, cands.means)
            assert np.array_equal(back.offsets, cands.offsets)
    finally:
        pass


# 1b ------------------------------------------------- top-k ranking metrics

def test_rank_at_k_identity_widening_and_ties():
    """WITNESS (b): a fake model whose TOP-1 is bad but whose TOP-4 contains
    the search's argmax -- rank_regret is large, rank_regret_at_4 is 0 and
    rank_recall_at_4 is 1.  RED (mutation): scoring k = 4 with the top-1 set
    (i.e. reading rank_regret where rank_regret_at_4 belongs) reports the
    large regret and recall 1/1 -> the two asserts below both fail."""
    # 8 candidates; the search's best is index 7, the net ranks it FOURTH
    means = [10.0, 20.0, 30.0, 40.0, 0.0, 5.0, 15.0, 400.0]
    cands = cwv_eval.CandidateSet.concatenate(
        [_entry(means, True)], {"schema": cwv_eval.CANDIDATE_SET_SCHEMA}, history=False)
    ml = cands.means_level()
    # net levels: 7 is ranked 4th (top-4 contains it, top-2 does not)
    net = np.asarray([9.0, 8.0, 7.0, 3.0, 2.0, 1.0, 0.0, 6.0])
    m = cwv_eval.rank_metrics(net, cands)
    # k = 1 IS rank_regret / rank_top1, bit for bit
    assert m["rank_regret_at_1"] == m["rank_regret"] and m["rank_regret"] > 0.0
    assert m["rank_recall_at_1"] == m["rank_top1"] == 0.0
    # the net's top-1 is candidate 0 -> the full regret to the best mean level
    assert m["rank_regret"] == pytest.approx(ml.max() - ml[0])
    # the top-4 set is {0, 1, 2, 7} and contains the search's argmax
    assert m["rank_regret_at_4"] == 0.0 and m["rank_recall_at_4"] == 1.0
    assert m["rank_regret_at_8"] == 0.0 and m["rank_recall_at_8"] == 1.0
    # ... but the top-2 set does not: still the full regret
    assert m["rank_regret_at_2"] == pytest.approx(ml.max() - max(ml[0], ml[1]))
    assert m["rank_recall_at_2"] == 0.0
    # RED: the mutation that reads the TOP-1 quantity for k = 4
    assert m["rank_regret"] != pytest.approx(m["rank_regret_at_4"])
    assert m["rank_top1"] != pytest.approx(m["rank_recall_at_4"])
    # monotone in k on this record
    ks = cwv_eval.DEFAULT_RANK_KS
    assert [m[f"rank_regret_at_{k}"] for k in ks] == sorted(
        [m[f"rank_regret_at_{k}"] for k in ks], reverse=True)
    assert [m[f"rank_recall_at_{k}"] for k in ks] == sorted(
        [m[f"rank_recall_at_{k}"] for k in ks])
    # the nested dicts and the flat aliases agree, and the definition is carried
    assert m["rank_ks"] == list(ks)
    assert all(m["rank_regret_at_k"][str(k)] == m[f"rank_regret_at_{k}"] for k in ks)
    assert all(m["rank_recall_at_k"][str(k)] == m[f"rank_recall_at_{k}"] for k in ks)
    assert "shortlist" not in m["rank_at_k_definition"]      # the caveat, not the consumer
    assert "MC-ranking proxy" in m["rank_at_k_definition"]
    assert "NOT E[U]" in m["rank_at_k_definition"]
    # a configurable k, and the refusals
    three = cwv_eval.rank_metrics(net, cands, ks=(3,))
    assert three["rank_ks"] == [3] and three["rank_regret_at_3"] == pytest.approx(
        ml.max() - max(ml[0], ml[1], ml[2]))
    with pytest.raises(cwv_eval.EvalError, match="positive integer"):
        cwv_eval.rank_metrics(net, cands, ks=(0,))
    with pytest.raises(cwv_eval.EvalError, match="at least one k"):
        cwv_eval.rank_metrics(net, cands, ks=())
    # k beyond the candidate count is the whole set: regret 0, recall 1
    assert cwv_eval.rank_metrics(net, cands, ks=(99,))["rank_regret_at_99"] == 0.0
    assert cwv_eval.rank_metrics(net, cands, ks=(99,))["rank_recall_at_99"] == 1.0


def test_rank_at_k_tie_rule_is_the_uniform_draw_of_rank_regret():
    """The tie rule STATED: the net's top-k is the first k of the candidates
    ordered by net level with ties broken UNIFORMLY at random, and the metric
    is the expectation over that draw -- exactly the rule rank_regret already
    uses at k = 1.  A fully tied scorer therefore has, at every k, the
    expected best level of a uniform k-subset."""
    entries = [_entry([100.0, 30.0, 150.0], True), _entry([-10.0, -90.0, -50.0, -130.0], False)]
    cands = cwv_eval.CandidateSet.concatenate(entries, {"schema": cwv_eval.CANDIDATE_SET_SCHEMA},
                                              history=False)
    ml = cands.means_level()
    tied = cwv_eval.rank_metrics(np.zeros(7), cands, ks=(1, 2, 3, 4))
    # k = 1: the uniform draw -- identical to rank_regret
    assert tied["rank_regret_at_1"] == tied["rank_regret"]
    assert tied["rank_recall_at_1"] == tied["rank_top1"] == pytest.approx(np.mean([1 / 3, 1 / 4]))
    # k = 2 over 3 (resp. 4) tied candidates: E[max of a uniform 2-subset]
    def e_max(values, k):
        from itertools import combinations
        subsets = list(combinations(range(len(values)), k))
        return float(np.mean([max(values[i] for i in sub) for sub in subsets]))

    def p_hit(values, k):
        from itertools import combinations
        best = max(values)
        subsets = list(combinations(range(len(values)), k))
        return float(np.mean([any(values[i] == best for i in sub) for sub in subsets]))

    a, b = ml[:3], ml[3:]
    for k in (1, 2, 3, 4):
        assert tied[f"rank_regret_at_{k}"] == pytest.approx(
            np.mean([a.max() - e_max(a, min(k, 3)), b.max() - e_max(b, min(k, 4))]))
        assert tied[f"rank_recall_at_{k}"] == pytest.approx(
            np.mean([p_hit(a, min(k, 3)), p_hit(b, min(k, 4))]))
    # a PARTIAL tie at the k-th boundary is the same expectation: two
    # candidates share the second-best net level, one of the two slots is
    # theirs, so k = 2 is (certain best) plus a uniform draw of the pair
    part = _entry([10.0, 200.0, 20.0, 400.0], True)
    cs = cwv_eval.CandidateSet.concatenate([part], {"schema": cwv_eval.CANDIDATE_SET_SCHEMA},
                                           history=False)
    lv = cs.means_level()
    got = cwv_eval.rank_metrics(np.asarray([5.0, 1.0, 1.0, 1.0]), cs, ks=(2,))
    assert got["rank_regret_at_2"] == pytest.approx(
        lv.max() - np.mean([max(lv[0], lv[1]), max(lv[0], lv[2]), max(lv[0], lv[3])]))
    assert got["rank_recall_at_2"] == pytest.approx(1 / 3)     # only index 3 is the argmax


def test_rank_at_k_missing_when_no_records():
    empty = cwv_eval.CandidateSet.empty({"schema": cwv_eval.CANDIDATE_SET_SCHEMA})
    block = cwv_eval.search_facing_metrics({}, levels=None, cands=None)
    for k in cwv_eval.DEFAULT_RANK_KS:
        assert block[f"rank_regret_at_{k}"] is None and block[f"rank_recall_at_{k}"] is None
    assert cwv_eval.rank_metrics(np.zeros(0), empty)["rank_regret_at_4"] is None



# 2 --------------------------------------------------------- points head

def test_points_metrics_bias_and_below_banked():
    pred = np.asarray([100.0, 60.0, np.nan, 20.0])
    real = np.asarray([90.0, 80.0, 50.0, 40.0])
    banked = np.asarray([50.0, 70.0, 0.0, 10.0])
    m = cwv_eval.points_metrics(pred, real, banked)
    assert m["points_n"] == 3
    assert m["points_mae"] == pytest.approx(np.mean([10, 20, 20]))
    assert m["points_bias"] == pytest.approx(np.mean([10, -20, -20]))      # pred - real
    assert m["points_below_banked"] == pytest.approx(1 / 3)                 # 60 < 70
    # RED: real - pred flips the bias
    assert m["points_bias"] != pytest.approx(np.mean([-10, 20, 20]))
    assert cwv_eval.points_metrics(np.full(2, np.nan), real[:2], banked[:2])["points_mae"] is None


# 3 ------------------------------------------------------------ selection

def test_selector_picks_different_epochs_per_metric():
    # WITNESS (d): the top-k selector must be able to pick a DIFFERENT epoch
    # than val_ce and than val_rank_regret -- epoch 5 is the only one whose
    # top-4 set contains the search's best, so only val_rank_regret_at_4
    # (and _at_8) select it.
    at_k = [
        {"rank_regret_at_1": 0.20, "rank_regret_at_2": 0.18, "rank_regret_at_4": 0.09,
         "rank_regret_at_8": 0.09},
        {"rank_regret_at_1": 0.12, "rank_regret_at_2": 0.11, "rank_regret_at_4": 0.07,
         "rank_regret_at_8": 0.07},
        {"rank_regret_at_1": 0.15, "rank_regret_at_2": 0.13, "rank_regret_at_4": 0.06,
         "rank_regret_at_8": 0.06},
        {"rank_regret_at_1": 0.16, "rank_regret_at_2": 0.14, "rank_regret_at_4": 0.05,
         "rank_regret_at_8": 0.05},
        {"rank_regret_at_1": 0.17, "rank_regret_at_2": 0.16, "rank_regret_at_4": 0.02,
         "rank_regret_at_8": 0.02},     # best top-4: a different epoch than CE / top-1
    ]
    epochs = [
        {"loss": 0.80, "rank_regret": 0.20, "points_mae": 30.0, **at_k[0]},
        {"loss": 0.70, "rank_regret": 0.12, "points_mae": 28.0, **at_k[1]},   # best regret
        {"loss": 0.65, "rank_regret": 0.15, "points_mae": 25.0, **at_k[2]},   # best CE
        {"loss": 0.66, "rank_regret": 0.16, "points_mae": 24.0, **at_k[3]},   # best points
        {"loss": 0.67, "rank_regret": 0.17, "points_mae": 26.0, **at_k[4]},
    ]
    # the synthetic at_1 column IS the rank_regret column (the k = 1 identity)
    assert [b["rank_regret_at_1"] for b in epochs] == [b["rank_regret"] for b in epochs]
    picks = {}
    stops = {}
    for metric in train_cwv.SELECT_METRICS:
        sel = train_cwv.Selector(metric, patience=2)
        for i, block in enumerate(epochs, start=1):
            improved, stop = sel.observe(i, block)
            assert improved == (sel.best_epoch == i)
            if stop:
                stops[metric] = i
                break
        picks[metric] = sel.best_epoch
        assert sel.payload()["metric"] == metric and sel.payload()["best_epoch"] == sel.best_epoch
    assert picks == {"val_ce": 3, "val_rank_regret": 2, "val_points_mae": 4,
                     "val_rank_regret_at_1": 2, "val_rank_regret_at_2": 2,
                     "val_rank_regret_at_4": 5, "val_rank_regret_at_8": 5}
    # the top-4 metric picks an epoch NEITHER val_ce NOR val_rank_regret picks
    assert picks["val_rank_regret_at_4"] not in (picks["val_ce"], picks["val_rank_regret"])
    assert stops == {"val_ce": 5, "val_rank_regret": 4,                 # patience 2 after best
                     "val_rank_regret_at_1": 4, "val_rank_regret_at_2": 4}
    # the top-k selector reads the top-k key, and refuses a block without it
    assert train_cwv.SELECT_METRICS["val_rank_regret_at_4"][0] == "rank_regret_at_4"
    assert "shortlist" in train_cwv.SELECT_METRICS["val_rank_regret_at_4"][1].lower()
    with pytest.raises(train_v0.TrainError, match="no finite 'rank_regret_at_4'"):
        train_cwv.Selector("val_rank_regret_at_4", patience=1).observe(
            1, {"loss": 0.5, "rank_regret": 0.1})
    with pytest.raises(train_v0.TrainError, match="val-rank-records"):
        train_cwv.build_config(data=["x"], select_metric="val_rank_regret_at_4",
                               val_rank_records=0)
    with pytest.raises(train_v0.TrainError, match="select-metric"):
        train_cwv.Selector("val_spearman", patience=1)
    with pytest.raises(train_v0.TrainError, match="no finite 'rank_regret'"):
        train_cwv.Selector("val_rank_regret", patience=1).observe(1, {"loss": 0.5,
                                                                      "rank_regret": None})
    with pytest.raises(train_v0.TrainError, match="needs --aux-points"):
        train_cwv.build_config(data=["x"], select_metric="val_points_mae")
    with pytest.raises(train_v0.TrainError, match="val-rank-records"):
        train_cwv.build_config(data=["x"], select_metric="val_rank_regret", val_rank_records=0)


# 4 + 5 ------------------------------------------ warm start, one function

@pytest.fixture(scope="module")
def trained(store_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("cwv-sf") / "a"
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=2, seed=7,
              batch_size=64, n_boot=10, hidden=32, log=None, cache_workers=1,
              eval_workers=1, bench_batch=16, aux_points=True, aux_weight=1.0,
              val_rank_records=50, **THIRDS)
    receipt = train_cwv.train(out=out, **kw)
    return out, kw, receipt


def test_search_facing_in_receipt_and_evaluate(trained, tmp_path):
    out, kw, receipt = trained
    for key in train_cwv.REQUIRED_RECEIPT_FIELDS:
        assert key in receipt, key
    # every epoch carries the search-facing block from the ONE function
    for row in receipt["epochs"]:
        val = row["val"]
        assert val["rank_records"] > 0 and val["rank_regret"] >= 0 and 0 <= val["rank_top1"] <= 1
        assert val["points_mae"] >= 0 and val["points_n"] == val["n"]
        assert val["rank_scale"] == cwv_eval.RANK_SCALE
    sf_val = receipt["final"]["val"]["search_facing"]
    sf_test = receipt["final"]["test"]["search_facing"]
    assert sf_test["rank_records"] > 0 and sf_test["candidate_set"]["per_shard_limit"] == 50
    # the final val block IS the best epoch's validation block (same code, same rows)
    best = next(r for r in receipt["epochs"] if r["epoch"] == receipt["best_epoch"])["val"]
    for key in ("rank_regret", "rank_top1", "points_mae", "points_bias", "cross_entropy"):
        assert sf_val[key] == pytest.approx(best[key], abs=1e-6), key
    assert receipt["selection"]["metric"] == "val_ce" and receipt["init"] is None
    consumer = receipt["consumer"]
    assert consumer["select_metric"] == "val_ce"
    assert set(consumer["heads"]) == {"level_head", "points_head"}
    assert "vleaf" in consumer["heads"]["points_head"]["consumed_by"][0]
    assert consumer["heads"]["level_head"]["recommended_select_metric"] == "val_rank_regret"
    # the consumer block names WHO reads the top-k shape and who the top-1 one
    level = consumer["heads"]["level_head"]
    assert level["recommended_select_metric_topk"] == "val_rank_regret_at_4"
    assert level["rank_ks"] == list(cwv_eval.DEFAULT_RANK_KS)
    assert any("shortlist" in c for c in level["top_k_consumers"])
    assert any("one-ply" in c for c in level["top_1_consumers"])
    assert any("PUCT" in c for c in level["top_1_consumers"])
    assert not any("one-ply" in c for c in level["top_k_consumers"])
    assert any("rank_regret_at_k" in m for m in level["metrics"])
    # WITNESSES (a) + (c) on REAL data, through the shared function: k = 1 is
    # rank_regret / rank_top1 exactly, and the top-k metrics are monotone.
    # RED: computing at_k off a different (e.g. top-1) candidate set breaks
    # the exact equality at k = 1 or the monotone order.
    for block in [sf_val, sf_test] + [row["val"] for row in receipt["epochs"]]:
        assert block["rank_regret_at_1"] == block["rank_regret"]
        assert block["rank_recall_at_1"] == block["rank_top1"]
        regrets = [block[f"rank_regret_at_{k}"] for k in cwv_eval.DEFAULT_RANK_KS]
        recalls = [block[f"rank_recall_at_{k}"] for k in cwv_eval.DEFAULT_RANK_KS]
        assert regrets == sorted(regrets, reverse=True), regrets
        assert recalls == sorted(recalls), recalls
        assert regrets[-1] >= 0.0 and recalls[-1] <= 1.0
    # the widening has teeth on real data: some k moves the metric
    assert sf_test["rank_regret_at_8"] < sf_test["rank_regret_at_1"]
    assert sf_test["rank_recall_at_8"] > sf_test["rank_recall_at_1"]
    # evaluate reproduces the test block through the same function
    ev = train_cwv.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "e",
                            data=kw["data"], device="cpu", n_boot=10,
                            cache_dir=str(out / "cache"), cache_workers=1, eval_workers=1,
                            bench_batch=8, log=None)
    got = ev["final"]["test"]["search_facing"]
    for key in ("rank_regret", "rank_regret_points", "rank_top1", "rank_records",
                "rank_regret_at_1", "rank_regret_at_2", "rank_regret_at_4",
                "rank_regret_at_8", "rank_recall_at_4",
                "points_mae", "points_bias", "points_below_banked", "cross_entropy"):
        assert got[key] == pytest.approx(sf_test[key], abs=1e-6), key
    assert ev["consumer"]["select_metric"] == "val_ce"


def test_warm_start_loads_weights_and_refuses_mismatch(trained, tmp_path):
    out, kw, receipt = trained
    src_val = receipt["selection"]["val"] if "val" in receipt["selection"] else None
    best_val = next(r for r in receipt["epochs"] if r["epoch"] == receipt["best_epoch"])["val"]
    # zero learning rate: the init validation and the epoch-1 validation
    # both equal the source checkpoint's own val CE on the same split
    warm = train_cwv.train(out=tmp_path / "w", **{**kw, "epochs": 1, "lr": 0.0,
                                                    "init": str(out / "best.pt")})
    init_val = warm["init"]["val"]
    assert warm["init"]["sha256"] and warm["init"]["path"].endswith("best.pt")
    assert warm["init"]["aux_points_head_loaded"] is True
    assert init_val["loss"] == pytest.approx(best_val["loss"], abs=1e-4)
    assert init_val["rank_regret"] == pytest.approx(best_val["rank_regret"], abs=1e-6)
    assert init_val["points_mae"] == pytest.approx(best_val["points_mae"], abs=1e-3)
    assert warm["epochs"][0]["val"]["loss"] == pytest.approx(best_val["loss"], abs=1e-4)
    assert warm["config"]["init"] == str((out / "best.pt").resolve())
    assert warm["selection"]["lr_effective"] == 0.0
    # a fresh model (no init) does NOT start there: the witness has teeth
    cold = train_cwv.train(out=tmp_path / "c", **{**kw, "epochs": 1, "lr": 0.0})
    assert cold["init"] is None
    assert abs(cold["epochs"][0]["val"]["loss"] - best_val["loss"]) > 1e-3
    # --init-lr-scale scales the effective learning rate and lands in the receipt
    scaled = train_cwv.build_config(data=kw["data"], init=str(out / "best.pt"),
                                    init_lr_scale=0.25)
    assert scaled["init_lr_scale"] == 0.25
    assert train_cwv.build_config(data=kw["data"])["init_lr_scale"] == 1.0
    # RED (mutation): a different hidden width is refused with a clear error
    with pytest.raises(train_v0.TrainError, match="model configuration differs"):
        train_cwv.train(out=tmp_path / "bad", **{**kw, "epochs": 1, "hidden": 16,
                                                   "init": str(out / "best.pt")})
    with pytest.raises(train_v0.TrainError, match="arch"):
        train_cwv.train(out=tmp_path / "bad2", **{**kw, "epochs": 1, "arch": "seq",
                                                    "aux_points": False,
                                                    "init": str(out / "best.pt")})
    del src_val


# 6 ----------------------------------------------------- cumulative exposure

@pytest.fixture(scope="module")
def third_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("cwv-third") / "run"
    trajectory.generate(rounds=6, seed0=SEED0 + 55_555, out_dir=out, workers=1, merge=False,
                        **WORK, **EXPLORE)
    return out


def _migrating_seed(keys1, keys2):
    """A seed whose split over P2 puts a P1 fit/selection deal into P2's
    val or test while leaving every P2 part non-empty after exclusion."""
    for seed in range(1, 400):
        a1 = split_deals(sorted(keys1), seed=seed, **THIRDS)
        fit = {k for k, v in a1.items() if v == "train"}
        exposed = {k for k, v in a1.items() if v in ("train", "val")}
        a2 = split_deals(sorted(keys2), seed=seed, **THIRDS)
        migrated = {"val": sorted(k for k, v in a2.items() if v == "val" and k in fit),
                    "test": sorted(k for k, v in a2.items() if v == "test" and k in exposed)}
        if not any(migrated.values()):
            continue
        dropped = set(migrated["val"]) | set(migrated["test"])
        remaining = {part: [k for k, v in a2.items() if v == part and k not in dropped]
                     for part in ("train", "val", "test")}
        if all(remaining.values()) and all(a1.values()):
            return seed, migrated
    raise AssertionError("no migrating seed")


def test_warm_start_refuses_or_excludes_ancestral_exposure(store_dir, other_dir, third_dir,
                                                           records, other_records, tmp_path):
    keys1 = {deal_key(r["deck"]) for r in records}
    keys3 = {deal_key(r["deck"]) for r in _records(third_dir)}
    keys2 = keys1 | {deal_key(r["deck"]) for r in other_records} | keys3
    assert len(keys1) == 3 and len(keys3) == 3 and len(keys2) == 7 and not keys1 & keys3
    seed, migrated = _migrating_seed(keys1, keys2)
    n_migrated = {part: len(v) for part, v in migrated.items()}
    kw = dict(arch="mlp", device="cpu", epochs=1, seed=seed, batch_size=64, n_boot=10,
              hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=8,
              val_rank_records=20, **THIRDS)
    p1 = train_cwv.train(data=[str(store_dir)], out=tmp_path / "p1", **kw)
    exposure = p1["exposure"]
    assert exposure["schema"] == train_cwv.EXPOSURE_SCHEMA and exposure["ancestors"] == []
    assert set(exposure["fit"]) == set(p1["population"]["train"])
    assert set(exposure["selection"]) == set(p1["population"]["val"])
    # the checkpoint payload carries it too
    _m, meta, _a = train_cwv.load_cwv_checkpoint(tmp_path / "p1" / "best.pt")
    assert meta["exposure"]["digest"] == exposure["digest"]
    # P2 > P1, same seed: a P1 fit/selection deal lands in P2's val/test -> refused
    p2 = dict(data=[str(store_dir), str(other_dir), str(third_dir)],
              init=str(tmp_path / "p1" / "best.pt"))
    with pytest.raises(train_v0.TrainError, match=(
            rf"{n_migrated['val']} deal\(s\) .* fit on land in this run's val and "
            rf"{n_migrated['test']} fit-or-selected deal\(s\) in its test")):
        train_cwv.train(out=tmp_path / "p2-refused", **p2, **kw)
    assert not (tmp_path / "p2-refused" / "best.pt").exists()
    # --init-exclude-exposed: runs; the excluded counts ARE the migrated deals,
    # which are in no part of the new run (never added to train)
    r = train_cwv.train(out=tmp_path / "p2", init_exclude_exposed=True, **p2, **kw)
    assert {k: r["init"]["excluded"][k] for k in ("val", "test")} == n_migrated
    assert r["config"]["init_exclude_exposed"] is True
    pop = r["population"]
    for part in ("train", "val", "test"):
        assert not set(pop[part]) & (set(migrated["val"]) | set(migrated["test"]))
    exposed1 = set(exposure["fit"]) | set(exposure["selection"])
    assert not set(pop["val"]) & set(exposure["fit"]) and not set(pop["test"]) & exposed1
    assert r["final"]["test"]["population"]["exposure"]["exposed"] == 0
    assert r["final"]["val"]["population"]["exposure"]["in_fit"] == 0
    # the exposure is cumulative: the union, with the ancestor named
    assert set(r["exposure"]["fit"]) == set(exposure["fit"]) | set(pop["train"])
    assert set(r["exposure"]["selection"]) == set(exposure["selection"]) | set(pop["val"])
    assert [a["digest"] for a in r["exposure"]["ancestors"]] == [exposure["digest"]]
    assert r["init"]["exposure"]["counts"] == exposure["counts"]
    # a second warm start cannot erase it: evaluate --split novel on P2's
    # stores finds no novel deal (every deal is in the population or exposed)
    with pytest.raises(train_v0.TrainError, match="no deal of the checkpoint's 'novel'"):
        train_cwv.evaluate(checkpoint=str(tmp_path / "p2" / "best.pt"), out=tmp_path / "e",
                           data=p2["data"], split="novel", device="cpu",
                           n_boot=10, cache_dir=str(tmp_path / "p2" / "cache"),
                           cache_workers=1, eval_workers=1, bench_batch=8, log=None)
    # the evaluated test block reports the exposure check against the cumulative digest
    ev = train_cwv.evaluate(checkpoint=str(tmp_path / "p2" / "best.pt"), out=tmp_path / "e2",
                            data=p2["data"], split="test", device="cpu",
                            n_boot=10, cache_dir=str(tmp_path / "p2" / "cache"),
                            cache_workers=1, eval_workers=1, bench_batch=8, log=None)
    assert ev["final"]["test"]["population"]["exposure"] == {
        **ev["final"]["test"]["population"]["exposure"], "exposed": 0,
        "checked_against": r["exposure"]["digest"]}
    # ... and the store-level check counts the CUMULATIVE exposure (P1's and P2's)
    assert ev["split"]["population_match"]["exposure"]["exposed"] == \
        r["exposure"]["counts"]["exposed"] > len(exposed1)
    # a compatible warm start (disjoint populations) works unchanged
    c = train_cwv.train(data=[str(third_dir)], out=tmp_path / "p3",
                        init=str(tmp_path / "p1" / "best.pt"), **kw)
    assert c["init"]["excluded"] == {**c["init"]["excluded"], "val": 0, "test": 0}
    assert c["exposure"]["counts"]["fit"] == len(exposure["fit"]) + len(c["population"]["train"])
    # exclusion without --init is refused up front
    with pytest.raises(train_v0.TrainError, match="needs --init"):
        train_cwv.build_config(data=["x"], init_exclude_exposed=True)
