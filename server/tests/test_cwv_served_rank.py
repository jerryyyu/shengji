"""Served-leaf ranking (``train.served_rank``), the opt-in trainer options for
LR decay and weight averaging, and the standalone re-scorer.  Each witness
names the mutation that turns it RED.

1. Records are chosen per deal and trick bucket by the seeded hash, not file
   order (RED: taking the first eligible record of a bucket).
2. A candidate is scored at the served leaf: played in the canonical true
   world with the current trick finished by the heuristic, exactly
   ``cwv_policy.afterstate(finish_trick=True)`` (RED: the immediate afterstate
   of ``cwv_eval.score_candidates``).  The truth is the heuristic playout to
   round end, reproduced here on an independent deep copy, and the root
   round is never mutated.
3. The metric: a perfect scorer has regret 0, an inverted one the mean
   spread; the headline weighs buckets equally (RED: the record mean); the
   search-means regret is ``cwv_eval.rank_metrics``' regret on the same pick.
4. LR schedule and weight average arithmetic; ``swapped`` restores the raw
   weights exactly.
5. Training with the options on: per-epoch served and averaged blocks, the
   averaged checkpoint selected into ``best.pt`` (RED: copying the raw one);
   with every option off the config is the historical one.
6. The re-scorer reproduces the trainer's CE, rank regret and served block
   for a checkpoint and refuses a deal the model was fit on.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.ai.cwv_policy import afterstate, default_finisher  # noqa: E402
from shengji.ai.cwv_static_encoding import tensors_from_round_static  # noqa: E402
from shengji.harvest import rebuild  # noqa: E402
from shengji.rl.value_afterstate import (  # noqa: E402
    N_CARDS, PUBLIC_DIM, WORLD_RECEIVERS, category_signed_level, signed_level_category)
from shengji.rl.value_afterstate_v2 import public_dim  # noqa: E402
from shengji.train import cwv_data, cwv_eval, served_rank, served_rescore, train_cwv  # noqa: E402
from shengji.train.data import discover_store  # noqa: E402

from test_cwv_train import (  # noqa: E402, F401  (module fixtures)
    EXPLORE, SEED0, THIRDS, WORK, _records, records, store_dir)


def _level(points, attacker):
    return category_signed_level(signed_level_category(int(points), attacker))


# 1 --------------------------------------------------------- record choice

def test_trick_buckets_and_hash_orders():
    assert [served_rank.trick_bucket(t) for t in (0, 4, 5, 9, 10, 24)] == \
        ["early", "early", "mid", "mid", "late", "late"]
    with pytest.raises(cwv_eval.EvalError):
        served_rank.trick_bucket(-1)
    assert served_rank.record_rank(1, "a") == served_rank.record_rank(1, "a")
    assert served_rank.record_rank(1, "a") != served_rank.record_rank(2, "a")
    keys = [f"deck:{i}" for i in range(50)]
    chosen = served_rank.served_deals(keys, 10, seed=3)
    assert len(chosen) == 10 and set(chosen) <= set(keys)
    assert chosen == served_rank.served_deals(list(reversed(keys)), 10, seed=3)
    assert chosen != served_rank.served_deals(keys, 10, seed=4)
    assert served_rank.served_deals(keys, 0, seed=3) == []
    assert sorted(served_rank.served_deals(keys, 99, seed=3)) == sorted(keys)


@pytest.fixture(scope="module")
def shards(store_dir):
    return [(s, None) for s in discover_store(store_dir).shards]


@pytest.fixture(scope="module")
def served(shards):
    return served_rank.build_served_set(shards, per_bucket=1, seed=5, workers=1)


def _eligible(records):
    out = {}
    for r in records:
        if r["decision_kind"] != "play" or r.get("outcome") is None:
            continue
        if cwv_data.search_means(r) is None:
            continue
        key = cwv_data.deal_key(list(r["deck"]))
        out.setdefault((key, served_rank.trick_bucket(r["trick"])), []).append(r)
    return out


def test_records_are_the_min_hash_record_of_each_deal_bucket(served, records):
    pools = _eligible(records)
    assert served.records == len(pools)                 # one per (deal, bucket) at per_bucket 1
    got = dict(zip(zip(served.cands.deal_key.tolist(), served.buckets().tolist()),
                   served.cands.source_ref.tolist()))
    for (key, bucket), pool in pools.items():
        want = min(pool, key=lambda r: served_rank.record_rank(5, r["source_ref"]))
        assert got[(key, bucket)] == want["source_ref"]
    # the buckets are all populated, and the records are spread over the round
    assert set(served.buckets().tolist()) == set(served_rank.BUCKET_NAMES)
    # RED: file order.  The trainer's set at one record per deal reads trick 0.
    first = {}
    for r in records:
        if r["decision_kind"] == "play" and r.get("outcome") is not None \
                and cwv_data.search_means(r) is not None:
            first.setdefault(cwv_data.deal_key(list(r["deck"])), r)
    assert {r["trick"] for r in first.values()} == {0}
    assert max(served.trick) >= 10


def test_served_set_is_a_function_of_its_digest(shards, served, tmp_path):
    again = served_rank.ensure_served_set(shards, tmp_path, per_bucket=1, seed=5, workers=1)
    assert again.meta["digest"] == served.meta["digest"]
    for name in cwv_eval.CandidateSet.ARRAYS:
        assert np.array_equal(getattr(again.cands, name), getattr(served.cands, name)), name
    loaded = served_rank.ensure_served_set(shards, tmp_path, per_bucket=1, seed=5, workers=1)
    assert loaded.meta.get("loaded_from")
    assert np.array_equal(loaded.rollout_level, served.rollout_level)
    assert np.array_equal(loaded.trick, served.trick)
    other = served_rank.build_served_set(shards, per_bucket=1, seed=6, workers=1)
    assert other.meta["digest"] != served.meta["digest"]
    assert other.cands.source_ref.tolist() != served.cands.source_ref.tolist()
    two = served_rank.build_served_set(shards, per_bucket=2, seed=5, workers=1)
    assert served.records < two.records <= 2 * served.records


# 2 ------------------------------------------------------------ the leaf

def _mid_trick_record(records):
    for r in records:
        if r["decision_kind"] == "play" and cwv_data.search_means(r) is not None \
                and len(r["plays_prefix"]) % 4 in (0, 1) and r["trick"] >= 2:
            rnd = rebuild.state_for_record(r)
            if rnd.trick is not None and len(rnd.trick.plays) < 3:
                return r, rnd
    raise AssertionError("no mid-trick search record in the fixture")


def _fingerprint(rnd):
    return (json.dumps(rnd.hands), json.dumps(sorted(rnd.buried)), rnd.attacker_points,
            len(rnd.history), [(p.seat, list(p.cards)) for p in rnd.trick.plays], rnd.turn,
            rnd.phase)


@pytest.mark.parametrize("version", [2, 7])
def test_candidates_are_scored_at_the_served_leaf_and_rolled_out(records, version):
    record, rnd = _mid_trick_record(records)
    seat = int(record["seat"])
    indices, _means = cwv_data.search_means(record)
    cands = [record["ballot"][i] for i in indices]
    before = _fingerprint(rnd)
    scored = served_rank.score_served_candidates(rnd, seat, cands, version=version)
    assert _fingerprint(rnd) == before                       # the root is never mutated
    assert scored["public"].shape[1] == public_dim(version)
    hands, buried = served_rank.true_world(rnd)
    assert hands == [sorted(h) for h in rnd.hands] and buried == sorted(rnd.buried)
    old = cwv_eval.score_candidates(rnd, seat, cands, version=version)
    differs = False
    for i, cand in enumerate(cands):
        leaf = afterstate(rnd, seat, hands, buried, cand, finish_trick=True)
        assert leaf.phase == "round_end" or not leaf.trick.plays   # a trick boundary
        if leaf.phase == "round_end":
            assert scored["terminal"][i]
        else:
            want = tensors_from_round_static(leaf, seat, version=version)
            assert np.array_equal(scored["public"][i], want.public)
            assert np.array_equal(scored["world"][i], np.rint(want.world * 2).astype(np.uint8))
            differs |= not np.array_equal(scored["public"][i], old["public"][i])
        # the truth: the same heuristic to round end on an independent deep copy
        clone = copy.deepcopy(rnd)
        clone.hands = [sorted(h) for h in clone.hands]
        clone.buried = sorted(clone.buried)
        clone._trusted_rollout = True
        clone._determinized_world = True
        clone.play(seat, list(cand))
        policy = default_finisher()
        while clone.phase == "play":
            s = clone.turn
            clone.play(s, policy.decide_play(clone, s))
        assert int(scored["rollout_points"][i]) == clone.attacker_points
        assert scored["rollout_level"][i] == _level(clone.attacker_points,
                                                    bool(rnd.is_attacker(seat)))
    # RED: the immediate afterstate (cwv_eval.score_candidates) is not the leaf
    assert differs


# 3 ---------------------------------------------------------- the metric

def _sset(groups):
    """``groups``: (trick, role_attacker, rollout points per candidate, means)."""
    entries = []
    for i, (trick, attacker, points, means) in enumerate(groups):
        k = len(points)
        entries.append({
            "public": np.zeros((k, PUBLIC_DIM), np.float32),
            "world": np.zeros((k, WORLD_RECEIVERS, N_CARDS), np.uint8),
            "perspective": np.full(k, int(attacker), np.uint8),
            "terminal": np.zeros(k, bool), "terminal_level": np.zeros(k),
            "means": np.asarray(means, np.float64), "units_code": 0,
            "deal_key": f"deck:{i // 2}", "source_ref": f"r{i}", "role_attacker": attacker,
            "trick": trick, "rollout_points": np.asarray(points, np.int16),
            "rollout_level": np.asarray([_level(p, attacker) for p in points])})
    return served_rank.ServedCandidateSet.concatenate(entries, {"schema": "test"})


def test_served_metric_perfect_inverted_and_bucket_balanced():
    sset = _sset([(0, True, [30, 90, 130], [30.0, 90.0, 130.0]),
                  (1, True, [60, 140], [60.0, 140.0]),
                  (2, False, [20, 100], [-20.0, -100.0]),
                  (6, False, [70, 75, 40], [-70.0, -75.0, -40.0]),
                  (12, True, [120, 125], [120.0, 125.0])])
    perfect = sset.rollout_level.copy()
    m = served_rank.served_rank_metrics(perfect, sset)
    assert m["served_rank_regret"] == 0.0 and m["served_rank_top1"] == 1.0
    assert m["served_rank_records"] == 5
    inverted = served_rank.served_rank_metrics(-perfect, sset)
    rows = served_rank.served_rank_rows(-perfect, sset)
    assert np.allclose(rows["regret"], rows["spread"])         # the worst pick everywhere
    by = inverted["served_by_trick"]
    assert by["early"]["records"] == 3 and by["mid"]["records"] == 1 and by["late"]["records"] == 1
    balanced = np.mean([by[b]["regret"] for b in served_rank.BUCKET_NAMES])
    assert inverted["served_rank_regret"] == pytest.approx(balanced)
    # RED: the record mean weighs the early bucket three times
    assert inverted["served_rank_regret"] != pytest.approx(rows["regret"].mean())
    assert inverted["served_rank_regret_records_mean"] == pytest.approx(rows["regret"].mean())
    assert inverted["served_rank_regret_late"] == by["late"]["regret"]
    # points: the acting team's, so a defender's best is the fewest attacker points
    assert rows["regret_points"][2] == pytest.approx(100 - 20)
    # the search regret is cwv_eval's rank regret on the same argmax
    for levels in (perfect, -perfect, np.zeros_like(perfect)):
        mine = served_rank.served_rank_rows(levels, sset)["search_regret"].mean()
        assert mine == pytest.approx(cwv_eval.rank_metrics(levels, sset.cands)["rank_regret"])
    with pytest.raises(cwv_eval.EvalError, match="misaligned"):
        served_rank.served_rank_metrics(np.zeros(3), sset)
    assert served_rank.served_rank_metrics(np.zeros(0), None)["served_rank_regret"] is None


def test_clustered_standard_errors():
    values = np.asarray([1.0, 1.0, 0.0, 0.0])
    # two deals, each constant: the SE is the deal-level one
    assert served_rank.clustered_se(values, np.asarray(["a", "a", "b", "b"])) == \
        pytest.approx(np.sqrt(2 * (2 * 0.5) ** 2) / 4)
    mean, se = served_rank.balanced_with_se(values, np.asarray(["early", "early", "mid", "mid"]),
                                            np.asarray(["a", "b", "a", "b"]))
    assert mean == pytest.approx(0.5) and se == pytest.approx(0.0)


# 4 ------------------------------------------------- LR and weight average

def test_lr_factor_shapes():
    f = train_cwv.lr_factor
    assert [f("constant", s, 10, 0.0) for s in (0, 5, 99)] == [1.0, 1.0, 1.0]
    assert f("cosine", 0, 10, 0.1) == pytest.approx(1.0)
    assert f("cosine", 5, 10, 0.1) == pytest.approx(0.1 + 0.9 * 0.5)
    assert f("cosine", 10, 10, 0.1) == pytest.approx(0.1)
    assert f("cosine", 50, 10, 0.1) == pytest.approx(0.1)
    assert f("linear", 2, 10, 0.0) == pytest.approx(0.8)
    with pytest.raises(train_cwv.TrainError):
        f("step", 1, 10, 0.0)


def test_weight_average_ema_swa_and_swap():
    p = torch.nn.Parameter(torch.tensor([1.0, 2.0]))
    ema = train_cwv.WeightAverage([p], "ema", decay=0.5, start_epoch=1)
    with torch.no_grad():
        p.copy_(torch.tensor([3.0, 4.0]))
    ema.update(1)
    assert torch.allclose(ema.shadow[0], torch.tensor([2.0, 3.0]))
    with ema.swapped():
        assert torch.equal(p.detach(), torch.tensor([2.0, 3.0]))
    assert torch.equal(p.detach(), torch.tensor([3.0, 4.0]))   # raw weights restored
    q = torch.nn.Parameter(torch.tensor([0.0]))
    swa = train_cwv.WeightAverage([q], "swa", decay=0.5, start_epoch=2)
    for epoch, value in ((1, 10.0), (2, 1.0), (2, 2.0), (3, 6.0)):
        with torch.no_grad():
            q.fill_(value)
        swa.update(epoch)
    assert swa.updates == 3 and torch.allclose(swa.shadow[0], torch.tensor([3.0]))
    assert not train_cwv.WeightAverage([q], "swa", decay=0.5, start_epoch=9).ready


def test_build_config_refusals_and_defaults():
    base = train_cwv.build_config(data=["x"])
    for key in ("served_rank", "lr_schedule", "weight_average"):
        assert key not in base
    with pytest.raises(train_cwv.TrainError, match="served-rank-deals"):
        train_cwv.build_config(data=["x"], select_metric="val_served_rank_regret")
    with pytest.raises(train_cwv.TrainError, match="lr-final-scale"):
        train_cwv.build_config(data=["x"], lr_final_scale=0.1)
    with pytest.raises(train_cwv.TrainError, match="select-averaged"):
        train_cwv.build_config(data=["x"], select_averaged=True)
    with pytest.raises(train_cwv.TrainError, match="seq"):
        train_cwv.build_config(data=["x"], arch="seq", served_rank_deals=3)
    with pytest.raises(train_cwv.TrainError, match="swa-start-epoch"):
        train_cwv.build_config(data=["x"], epochs=2, weight_average="swa", swa_start_epoch=3)
    on = train_cwv.build_config(data=["x"], served_rank_deals=4, lr_schedule="linear",
                                lr_final_scale=0.2, weight_average="swa", swa_start_epoch=1)
    assert on["served_rank"] == {"deals": 4, "per_bucket": 1, "seed": 1}
    assert on["lr_schedule"] == {"kind": "linear", "final_scale": 0.2}
    assert on["weight_average"] == {"kind": "swa", "select": False, "start_epoch": 1}


# 5 ------------------------------------------------------------- training

@pytest.fixture(scope="module")
def trained(store_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("cwv-served") / "a"
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=2, seed=7,
              batch_size=64, n_boot=10, hidden=32, log=None, cache_workers=1,
              eval_workers=1, bench_batch=16, aux_points=True, aux_weight=1.0,
              val_rank_records=50, served_rank_deals=5, served_rank_per_bucket=2,
              select_metric="val_served_rank_regret", lr_schedule="cosine",
              lr_final_scale=0.1, weight_average="ema", ema_decay=0.9, select_averaged=True,
              **THIRDS)
    receipt = train_cwv.train(out=out, **kw)
    return out, kw, receipt


def test_training_reports_served_and_averaged_blocks(trained):
    out, kw, receipt = trained
    assert receipt["config"]["served_rank"]["deals"] == 5
    assert receipt["selection"]["metric"] == "val_served_rank_regret"
    assert receipt["selection"]["weights"] == "averaged"
    lrs = [row["train"]["lr_end"] for row in receipt["epochs"]]
    assert lrs[0] > lrs[-1] >= 0.1 * 3e-4 - 1e-12              # decayed towards the floor
    for row in receipt["epochs"]:
        val = row["val"]
        assert val["served_rank_records"] > 0 and val["served_rank_regret"] >= 0
        assert set(val["served_by_trick"]) == set(served_rank.BUCKET_NAMES)
        assert val["averaged"]["served_rank_regret"] is not None
        assert (out / "checkpoints" / f"epoch-{row['epoch']:02d}.avg.pt").is_file()
    best = receipt["best_epoch"]
    picked = next(r for r in receipt["epochs"] if r["epoch"] == best)["val"]["averaged"]
    assert receipt["selection"]["best_value"] == pytest.approx(picked["served_rank_regret"])
    # best.pt holds the AVERAGED weights of the best epoch (RED: the raw copy)
    model, meta, _aux = train_cwv.load_cwv_checkpoint(out / "best.pt", "cpu")
    avg, _m, _a = train_cwv.load_cwv_checkpoint(
        out / "checkpoints" / f"epoch-{best:02d}.avg.pt", "cpu")
    raw, _m, _a = train_cwv.load_cwv_checkpoint(
        out / "checkpoints" / f"epoch-{best:02d}.pt", "cpu")
    sd, sa, sr = model.state_dict(), avg.state_dict(), raw.state_dict()
    assert all(torch.equal(sd[k], sa[k]) for k in sd)
    assert not all(torch.equal(sd[k], sr[k]) for k in sd)
    assert meta["weights"] == "averaged"
    # the final served blocks come from the same function on the selected weights
    sf = receipt["final"]["val"]["served_facing"]
    assert sf["served_rank_regret"] == pytest.approx(picked["served_rank_regret"], abs=1e-9)
    assert receipt["final"]["test"]["served_facing"]["served_rank_records"] > 0
    assert "served_leaf_metric" in receipt["consumer"]["heads"]["level_head"]


# 6 ------------------------------------------------------------- rescoring

def test_rescore_reproduces_the_trainer_and_refuses_fit_deals(trained, tmp_path):
    out, kw, receipt = trained
    ckpt = out / "checkpoints" / "epoch-01.pt"
    model, meta, aux = train_cwv.load_cwv_checkpoint(ckpt, "cpu")
    test_keys = sorted(meta["population"]["test"])
    deals = tmp_path / "deals.json"
    deals.write_text(json.dumps({"deal_keys": test_keys}))
    report = served_rescore.rescore([("e01", str(ckpt))], kw["data"], tmp_path / "r",
                                    cache_dir=out / "cache", deals_file=str(deals),
                                    per_bucket=2, seed=7, workers=1, log=None)
    got = report["models"]["e01"]
    assert report["deals"] == len(test_keys) and got["exposure"]["fit"] == 0
    # the trainer's arithmetic on the same deals
    version = int(model.config.enc_version)
    prepared = cwv_data.prepare_stores(kw["data"], out / "cache", limit_clusters=None,
                                       history=False, witness_seed=1, cache_workers=1,
                                       version=version)
    store = prepared.block_store
    sel = np.asarray(test_keys)
    ev = train_cwv.run_eval(model, store, lambda b: np.isin(b.deal_key, sel), torch.device("cpu"),
                            batch_size=64, aux_head=aux)
    assert got["val_ce"] == pytest.approx(float(ev["ce"].mean()), abs=1e-9)
    old = cwv_eval.build_candidate_set(train_cwv.shard_keys_of(store, set(test_keys)),
                                       per_shard_limit=1, history=False, workers=1,
                                       version=version)
    levels = train_cwv.rank_levels(model, old, torch.device("cpu"), batch_size=64)
    assert got["rank_regret"] == pytest.approx(cwv_eval.rank_metrics(levels, old)["rank_regret"])
    sset = served_rank.build_served_set(train_cwv.shard_keys_of(store, set(test_keys)),
                                        per_bucket=2, seed=7, version=version)
    block = train_cwv.served_facing(model, sset, torch.device("cpu"), batch_size=64)
    assert got["served_rank_regret"] == pytest.approx(block["served_rank_regret"])
    assert got["served"]["served_by_trick"] == block["served_by_trick"]
    with np.load(tmp_path / "r" / "records.npz") as npz:
        assert npz["e01__served_regret"].size == sset.records
        assert npz["e01__ce_deal_sum"].sum() / npz["ce_deal_rows"].sum() == \
            pytest.approx(got["val_ce"])
    # resumable per model: a rerun scores only the model without a saved result
    lines = []
    ckpt2 = out / "checkpoints" / "epoch-02.pt"
    again = served_rescore.rescore([("e01", str(ckpt)), ("e02", str(ckpt2))], kw["data"],
                                   tmp_path / "r", cache_dir=out / "cache",
                                   deals_file=str(deals), per_bucket=2, seed=7, workers=1,
                                   log=lines.append)
    assert any(line.startswith("resuming: ['e01']") for line in lines)
    assert not any(line.startswith("e01:") for line in lines)
    assert any(line.startswith("e02:") for line in lines)
    assert json.dumps(again["models"]["e01"], sort_keys=True) == json.dumps(got, sort_keys=True)
    with np.load(tmp_path / "r" / "records.npz") as npz:
        assert {"e01__served_regret", "e02__served_regret"} <= set(npz.files)
    # a deal the model was fit on is refused
    fit = tmp_path / "fit.json"
    fit.write_text(json.dumps({"deal_keys": sorted(meta["population"]["train"])}))
    with pytest.raises(train_cwv.TrainError, match="fit exposure"):
        served_rescore.rescore([("e01", str(ckpt))], kw["data"], tmp_path / "f",
                               cache_dir=out / "cache", deals_file=str(fit), log=None)
