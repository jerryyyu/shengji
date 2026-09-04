"""train v0 (train_spec.md): loader/encoder round trip, PRIVACY witness,
split-by-cluster witness, stratified prior, prior masking + CE, training
smoke with seed determinism, preference derivation / skip, parallel cache
build byte identity, auxiliary search-mean head, sweep driver.

Pure engine + torch on CPU.  The shard store is generated here at reduced
work (4 rounds = 2 deal clusters, N=2 selection worlds, R=30 report worlds)
and the Luna-like private rows are built from those records.
"""
import json
import math
import random
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.harvest import rebuild, trajectory  # noqa: E402
from shengji.harvest.common import action_key, write_jsonl  # noqa: E402
from shengji.harvest.schema import finalize_record, split_record  # noqa: E402
from shengji.rl import encode  # noqa: E402
from shengji.train import baselines, data, sweep  # noqa: E402
from shengji.train import model as model_mod  # noqa: E402
from shengji.train import train_v0  # noqa: E402

SEED0 = 4_100_000
ROUNDS = 4
WORK = {"select_worlds": 2, "report_worlds": 30}
EXPLORE = {"explore_rate": 0.5, "explore_k": 2}
N_LUNA = 4


@pytest.fixture(scope="module")
def store_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("traj") / "run"
    trajectory.generate(rounds=ROUNDS, seed0=SEED0, out_dir=out, workers=1, merge=False,
                        **WORK, **EXPLORE)
    return out


@pytest.fixture(scope="module")
def records(store_dir):
    manifest = json.loads((store_dir / "manifest.json").read_text())
    recs = []
    for shard in manifest["shards"]:
        recs += [json.loads(line)
                 for line in (store_dir / shard["path"]).read_text().splitlines()]
    assert len(recs) == manifest["counts"]["records"] > 150
    return recs


def _luna_rows(records, n=N_LUNA):
    """Luna-like private rows: hidden hands + deck, a wide ballot, no search
    evidence and no ``preference`` (only the played action is known)."""
    rng = random.Random(3)
    picks = rng.sample([r for r in records if len(r["ballot"]) >= 2], n)
    rows = []
    for r in picks:
        rnd = rebuild.state_for_record(r)
        _, cluster, mirror, _, ply = r["source_ref"].split(":")
        fields = {k: v for k, v in r.items()
                  if k not in ("record_sha256", "preference", "allocation",
                               "action_values", "exploration", "production_ballot")}
        fields.update(
            source="luna-rpc", policy="gpt-5.6-luna", round_seed=None,
            source_ref=(f"pt-luna-test/attempts/{cluster}-mirror-{mirror}/"
                        f"trajectory.json#event-{ply}"),
            allocation=None, action_values=None, authority=None,
            hidden_hands=rebuild.hands_snapshot(rnd))
        _public, private = split_record(finalize_record(fields))
        rows.append(private)
    return rows


@pytest.fixture(scope="module")
def luna(tmp_path_factory, records):
    rows = _luna_rows(records)
    path = tmp_path_factory.mktemp("luna") / "luna-test.private.jsonl"
    write_jsonl(path, rows, private=True)
    return path, rows


def _blocks(store_dir, cache_dir):
    store = data.discover_store(store_dir)
    entries, blocks = [], []
    for shard in store.shards:
        block, _ = data.ensure_cache(shard, cache_dir, witness_seed=1)
        entries.append((shard, str(data.cache_path(cache_dir, shard.sha256))))
        blocks.append(block)
    bs = data.BlockStore(entries)
    bs.preload(blocks)
    return store, bs


# 1 ------------------------------------------------- loader / encoder round trip

def test_loader_encoder_round_trip(store_dir, records, luna, tmp_path):
    cache = tmp_path / "cache"
    store = data.discover_store(store_dir)
    assert store.layout == "shard-store" and len(store.shards) == 2
    assert store.manifests and store.manifests[0]["schema"] == trajectory.MANIFEST_SCHEMA
    by_sha = {r["record_sha256"]: r for r in records}
    total = 0
    for shard in store.shards:
        block, rebuilt = data.ensure_cache(shard, cache, witness_seed=1)
        assert rebuilt
        path = data.cache_path(cache, shard.sha256)
        assert path.name == f"{shard.sha256}.{encode.ENCODER_IMPLEMENTATION_SHA256[:12]}.npz"
        meta = block.meta
        assert meta["schema"] == data.CACHE_SCHEMA
        assert meta["encoder"]["implementation_sha256"] == encode.ENCODER_IMPLEMENTATION_SHA256
        assert meta["encoder"]["enc_version"] == encode.ENC_VERSION
        assert meta["encoder"]["obs_schema"] == encode.OBS_SCHEMA
        assert meta["shard"]["sha256"] == shard.sha256 and block.n == shard.records
        assert meta["counts"]["privacy_witness"]["records"] > 0
        assert meta["counts"]["preference"]["stored"] == block.n
        again, rebuilt2 = data.ensure_cache(shard, cache, witness_seed=1)
        assert not rebuilt2 and np.array_equal(again.obs, block.obs)
        assert np.array_equal(again.cand_feats, block.cand_feats)
        for i in range(block.n):
            r = by_sha[block.record_sha256[i].decode()]
            rnd = rebuild.state_for_record(r)
            assert np.array_equal(block.obs[i], np.asarray(encode.encode_obs(rnd, r["seat"]),
                                                           np.float32))
            lo, hi = block.cand_offsets[i], block.cand_offsets[i + 1]
            assert hi - lo == len(r["ballot"])
            expected = np.asarray([encode.encode_action(c, rnd) for c in r["ballot"]],
                                  np.float32)
            assert np.array_equal(block.cand_feats[lo:hi], expected)
            assert block.utility[i] == r["outcome"]["signed_level_utility"]
            assert block.attacker_points[i] == r["outcome"]["attacker_points"]
            assert block.points_so_far[i] == rnd.attacker_points
            assert block.ply[i] == r["ply"] and block.seat[i] == r["seat"]
            assert block.role_attacker[i] == (r["role"] == "attacker-team")
            run_id, cluster, _m, _s, _p = r["source_ref"].split(":")
            assert block.cluster[i] == f"{run_id}:{cluster}"
            assert block.has_softmax[i]
            assert np.allclose(block.cand_softmax[lo:hi], r["preference"]["softmax"])
            assert block.played[i] == r["preference"]["played_index"]
            total += 1
    assert total == len(records)
    # a batch keeps every candidate of every record, masked to its ballot
    batch = data.collate(block, np.arange(min(8, block.n)))
    assert batch["mask"].sum() == block.widths[:8].sum()
    assert batch["cand"].shape[2] == encode.ACT_DIM and batch["obs"].shape[1] == encode.OBS_DIM
    assert np.all(batch["target"][~batch["mask"]] == 0)
    # Luna private rows: deck + hidden hands, no search evidence: value target
    # and the played-action target only, cache kept private
    luna_path, rows = luna
    lstore = data.discover_store(luna_path)
    assert lstore.layout == "jsonl" and lstore.private
    lblock, _ = data.ensure_cache(lstore.shards[0], cache, witness_seed=1, private=True)
    assert lblock.n == N_LUNA
    assert (data.cache_path(cache, lstore.shards[0].sha256).stat().st_mode & 0o077) == 0
    pref = lblock.meta["counts"]["preference"]
    assert pref["missing"] == N_LUNA and pref["final_from_action"] == N_LUNA
    assert pref["stored"] == pref["derived"] == 0
    assert not lblock.has_softmax.any() and (lblock.played >= 0).all()
    for i, r in enumerate(rows):
        rnd = rebuild.state_for_record(r)
        assert np.array_equal(lblock.obs[i], np.asarray(encode.encode_obs(rnd, r["seat"]),
                                                        np.float32))
        keys = [action_key(c) for c in r["ballot"]]
        assert lblock.played[i] == keys.index(action_key(r["action"]))
        assert lblock.cluster[i] == r["source_ref"].split("#")[0].replace(
            f"-mirror-{r['source_ref'].split('-mirror-')[1][0]}", "")
        assert lblock.utility[i] == r["outcome"]["signed_level_utility"]


# 2 ----------------------------------------------------------- PRIVACY witness

def test_privacy_witness_refuses_an_encoder_that_reads_other_hands(
        store_dir, records, tmp_path, monkeypatch):
    rng = random.Random(0)
    checked = 0
    for r in records:
        rnd = rebuild.state_for_record(r)
        before = [list(h) for h in rnd.hands]
        checked += data.privacy_witness(rnd, r["seat"], r["ballot"], rng)
        assert [list(h) for h in rnd.hands] == before          # state restored
    assert checked == data.PRIVACY_TRIALS * len(records)
    # an encoder that peeks at the partner's hand
    real = encode.encode_obs

    def leaky(rnd, seat):
        obs = real(rnd, seat)
        partner = rnd.hands[(seat + 2) % 4]
        obs[0] += 1e-3 * sum(encode.CARD_INDEX[c] for c in partner)
        return obs

    monkeypatch.setattr(data, "encode_obs", leaky)
    r = next(r for r in records if 10 <= r["ply"] <= 60 and len(r["ballot"]) >= 2)
    with pytest.raises(data.PrivacyError, match="cannot see"):
        data.privacy_witness(rebuild.state_for_record(r), r["seat"], r["ballot"],
                             random.Random(0))
    # the loader refuses to cache (and hence to train) with such an encoder
    store = data.discover_store(store_dir)
    with pytest.raises(data.PrivacyError):
        data.build_cache(store.shards[0], tmp_path / "cache", witness_seed=1,
                         witness_every=1)
    assert not data.cache_path(tmp_path / "cache", store.shards[0].sha256).exists()


# 3 ------------------------------------------------------ split by deal cluster

def test_split_is_by_deal_cluster_never_by_record(store_dir, tmp_path):
    keys = [f"run:{i}" for i in range(200)]
    for seed in (1, 2):
        a = data.split_clusters(keys, seed=seed, val_fraction=0.1)
        assert sum(v == "val" for v in a.values()) == 20 and len(a) == 200
        assert a == data.split_clusters(list(reversed(keys)), seed=seed, val_fraction=0.1)
    assert data.split_clusters(keys, seed=1) != data.split_clusters(keys, seed=2)
    assert set(data.split_clusters(["only"], seed=1).values()) == {"train"}
    _store, bs = _blocks(store_dir, tmp_path / "cache")
    assignment = data.split_clusters(bs.cluster_keys(), seed=1, val_fraction=0.5)
    assert sorted(assignment.values()) == ["train", "val"]
    train_clusters, val_clusters = set(), set()
    for block in bs.iter_blocks():
        tm = data.split_mask(block, assignment, "train")
        vm = data.split_mask(block, assignment, "val")
        assert not (tm & vm).any() and (tm | vm).all()
        train_clusters |= set(map(str, block.cluster[tm]))
        val_clusters |= set(map(str, block.cluster[vm]))
        for i in range(block.n):                       # both mirrors share a key
            run_id, cluster, *_ = str(block.source_ref[i]).split(":")
            assert str(block.cluster[i]) == f"{run_id}:{cluster}"
    assert train_clusters and val_clusters
    assert not (train_clusters & val_clusters), "a deal cluster is in both splits"
    # the batch iterators see disjoint records
    seen_train = {int(i) for b in bs.iter_batches(
        lambda b: data.split_mask(b, assignment, "train"), 32) for i in b["idx"]}
    n_val = sum(int(data.split_mask(b, assignment, "val").sum()) for b in bs.iter_blocks())
    n_train = sum(int(data.split_mask(b, assignment, "train").sum()) for b in bs.iter_blocks())
    assert n_train + n_val == sum(b.n for b in bs.iter_blocks())
    assert len(seen_train) == n_train
    rows = 0
    for batch in bs.iter_batches(lambda b: data.split_mask(b, assignment, "val"), 32,
                                 rng=np.random.default_rng(0)):
        rows += len(batch["idx"])
    assert rows == n_val


# 4 ---------------------------------------------------------- stratified prior

def test_stratified_prior_baseline_on_a_hand_built_table():
    prior = baselines.StratifiedPrior()
    prior.add([0, 10, 33], [True, True, True], [0, 20, 39], [1, 1, -1])   # early/attacker/0-39
    prior.add([70, 99], [False, False], [80, 200], [3, 3])                # late/banker/80+
    prior.add([34, 66], [False, True], [40, 79], [-2, 2])                 # middle cells
    assert prior.predict([5], [True], [10]) == pytest.approx([1 / 3])
    assert prior.predict([67], [False], [95]) == pytest.approx([3.0])
    assert prior.predict([50], [False], [50]) == pytest.approx([-2.0])
    assert prior.predict([40], [True], [45]) == pytest.approx([2.0])
    assert prior.predict([50], [True], [0]) == pytest.approx([1.0])       # empty: global mean
    assert prior.predict([-1], [True], [0]) == pytest.approx([1 / 3])     # bury = early
    assert baselines.phase_index([0, 33, 34, 66, 67, 99, -1]).tolist() == [0, 0, 1, 1, 2, 2, 0]
    assert baselines.points_bin([0, 39, 40, 79, 80, 200]).tolist() == [0, 0, 1, 1, 2, 2]
    d = prior.to_dict()
    assert d["n"] == 7 and d["empty_cells"] == baselines.N_STRATA - 4
    assert d["global_mean"] == pytest.approx(1.0)
    cells = {c["stratum"]: c for c in d["cells"]}
    assert cells["early|attacker-team|0-39"]["n"] == 3
    assert cells["late|banker-team|80+"]["mean"] == pytest.approx(3.0)
    again = baselines.StratifiedPrior.from_dict(d)
    assert np.array_equal(again.means(), prior.means())
    # the prior baselines: uniform CE is log K; the smoothed incumbent at eps=1 is uniform
    assert baselines.uniform_ce([2, 4]).tolist() == pytest.approx([math.log(2), math.log(4)])
    assert baselines.incumbent_ce([1.0, 0.0], [2, 2], 1.0).tolist() == pytest.approx([math.log(2)] * 2)
    first, widths = np.array([1.0, 1.0, 0.9, 0.2]), np.array([3, 4, 2, 5])
    fit = baselines.fit_incumbent_eps(first, widths)
    assert fit["eps"] in baselines.INCUMBENT_EPS_GRID
    assert fit["train_ce"] == min(row["ce"] for row in fit["grid"])
    assert fit["train_ce"] == pytest.approx(
        baselines.incumbent_ce(first, widths, fit["eps"]).mean())
    assert fit["train_ce"] < baselines.uniform_ce(widths).mean()   # eps = 1 is uniform
    # paired difference with a cluster bootstrap CI
    ci = baselines.cluster_bootstrap(np.array([1.0, 1.0, -1.0, -1.0]),
                                     np.array(["a", "a", "b", "b"]), n_boot=200, seed=0)
    assert ci["mean"] == 0.0 and ci["clusters"] == 2 and ci["ci95"][0] <= 0 <= ci["ci95"][1]


# 5 ------------------------------------------------- prior masking + cross-entropy

def test_prior_masking_and_cross_entropy_match_manual():
    torch.manual_seed(0)
    net = model_mod.ValuePriorNet().eval()
    obs = torch.randn(3, encode.OBS_DIM)
    cand = torch.randn(3, 5, encode.ACT_DIM)
    mask = torch.tensor([[1, 1, 1, 0, 0], [1, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=torch.bool)
    target = torch.tensor([[0.2, 0.5, 0.3, 0, 0], [1, 0, 0, 0, 0], [0.1, 0.2, 0.3, 0.2, 0.2]])
    value, aux, logits, search = net(obs, cand, mask)
    assert value.shape == (3,) and aux is None and search is None
    probs = model_mod.prior_distribution(logits, mask)
    assert torch.all(probs[~mask] == 0)                   # exactly zero outside the ballot
    assert torch.allclose(probs.sum(dim=1), torch.ones(3), atol=1e-6)
    ce = model_mod.prior_cross_entropy(logits, mask, target)
    for i in range(3):
        k = int(mask[i].sum())
        l = logits[i, :k].double()
        manual = -sum(float(target[i, j]) * (l[j] - torch.logsumexp(l, 0)) for j in range(k))
        assert ce[i].item() == pytest.approx(manual.item(), abs=1e-5)
    assert ce[1].item() == pytest.approx(0.0, abs=1e-6)   # one candidate: certain
    # candidates outside the ballot never influence the distribution
    cand2 = cand.clone()
    cand2[~mask] = 100.0
    logits2 = net(obs, cand2, mask).logits
    assert torch.allclose(model_mod.prior_distribution(logits2, mask), probs)
    uniform = torch.where(mask, 1.0 / mask.sum(1, keepdim=True), torch.zeros_like(target))
    ce_u = model_mod.prior_cross_entropy(logits, mask, uniform)
    p = probs.detach()
    for i in range(3):
        k = int(mask[i].sum())          # uniform target: -(1/k) sum_j log p_j
        assert ce_u[i].item() == pytest.approx(-float(torch.log(p[i, :k]).sum()) / k, abs=1e-5)
    # the loss only counts rows that carry a target
    batch = {"obs": obs, "cand": cand, "mask": mask, "target": target,
             "has_softmax": torch.tensor([True, False, True]),
             "utility": torch.tensor([1.0, -1.0, 2.0]), "attacker_points": torch.zeros(3)}
    losses = model_mod.batch_losses(net, batch, prior_weight=1.0)
    assert losses["prior"].item() == pytest.approx((ce[0].item() + ce[2].item()) / 2, abs=1e-5)
    assert losses["n_prior"].item() == 2
    assert losses["total"].item() == pytest.approx(losses["value"].item() + losses["prior"].item(),
                                                   abs=1e-5)


# 6 ---------------------------------------------------------- training smoke

def _strip_secs(epochs):
    return [{k: v for k, v in e.items() if k != "secs"} for e in epochs]


def test_training_smoke_receipt_and_seed_determinism(store_dir, luna, tmp_path):
    luna_path, _rows = luna
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), device="cpu", epochs=2,
              seed=7, batch_size=64, n_boot=50, val_fraction=0.5, log=None)
    r1 = train_v0.train(out=tmp_path / "a", **kw)
    r2 = train_v0.train(out=tmp_path / "b", **kw)
    for key in train_v0.REQUIRED_RECEIPT_FIELDS:
        assert key in r1, key
    assert r1["schema"] == train_v0.RECEIPT_SCHEMA and r1["command"] == "train"
    assert r1["encoder"]["implementation_sha256"] == encode.ENCODER_IMPLEMENTATION_SHA256
    assert r1["encoder"]["enc_version"] == encode.ENC_VERSION
    assert len(r1["git"]["sha"]) == 40
    assert r1["data"][0]["layout"] == "shard-store" and len(r1["data"][0]["shards"]) == 2
    assert all(len(s["sha256"]) == 64 for s in r1["data"][0]["shards"])
    assert r1["data"][0]["manifests"][0]["schema"] == trajectory.MANIFEST_SCHEMA
    assert len(r1["config_sha256"]) == 64 and r1["seeds"]["torch"] == 7
    assert r1["split"] == {**r1["split"], "train_clusters": 1, "val_clusters": 1}
    assert r1["split"]["train_records"] + r1["split"]["val_records"] == r1["counts"]["records_total"]
    assert len(r1["epochs"]) == 2
    for row in r1["epochs"]:
        assert {"epoch", "train", "val", "secs"} <= set(row)
        assert row["train"]["loss"] > 0 and row["val"]["loss"] > 0
    val = r1["final"]["val"]
    assert val["value"]["n"] == r1["split"]["val_records"]
    for who in ("model", "stratified_prior"):
        assert val["value"][who]["mae"] >= 0 and val["value"][who]["mse"] >= 0
    diff = val["value"]["paired_diff_model_minus_prior"]["abs_error"]
    assert len(diff["ci95"]) == 2 and diff["ci95"][0] <= diff["mean"] <= diff["ci95"][1]
    assert diff["clusters"] == 1 and diff["n_boot"] == 50
    prior = val["prior"]["softmax"]
    assert prior["n"] > 0 and prior["uniform_ce"] > 0 and prior["incumbent_ce"] > 0
    assert 0 <= prior["top1_agreement"] <= 1
    assert r1["baselines"]["stratified_prior"]["n"] == r1["split"]["train_records"]
    assert r1["baselines"]["incumbent"]["softmax"]["eps"] in baselines.INCUMBENT_EPS_GRID
    cal = r1["calibration"]
    assert {"scale", "shift"} <= set(cal) and len(val["calibration"]["reliability"]) >= 1
    assert val["calibration"]["mae_after"] <= val["calibration"]["mae_before"] + 1e-9
    luna_m = r1["final"]["luna"]
    assert luna_m["value"]["n"] == N_LUNA and luna_m["prior"]["final"]["n"] == N_LUNA
    assert luna_m["prior"]["softmax"]["n"] == 0            # no search evidence on Luna
    assert "mae_after" in luna_m["calibration"]
    out = tmp_path / "a"
    assert (out / "receipt.json").is_file() and (out / "metrics.json").is_file()
    assert (out / "best.pt").is_file()
    assert sorted(p.name for p in (out / "checkpoints").iterdir()) == ["epoch-01.pt", "epoch-02.pt"]
    assert json.loads((out / "receipt.json").read_text())["final"] == r1["final"]
    # a fixed seed reproduces every metric exactly
    assert _strip_secs(r1["epochs"]) == _strip_secs(r2["epochs"])
    assert r1["final"] == r2["final"] and r1["config_sha256"] == r2["config_sha256"]
    # a different seed changes them (the seed is applied)
    r3 = train_v0.train(out=tmp_path / "c", **{**kw, "seed": 8})
    assert _strip_secs(r3["epochs"]) != _strip_secs(r1["epochs"])
    # evaluate reproduces the checkpoint's held-out value metrics
    ev = train_v0.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "e",
                           data=[str(store_dir)], eval_luna=str(luna_path), device="cpu",
                           n_boot=50, log=None)
    assert ev["command"] == "evaluate" and ev["final"]["val"]["value"]["model"] == val["value"]["model"]
    assert ev["final"]["luna"]["value"]["model"] == luna_m["value"]["model"]


# 7 ------------------------------------------- preference derived or skipped

def test_rows_without_preference_are_derived_or_skipped(records, tmp_path):
    counts = {k: 0 for k in data.PREFERENCE_KEYS}
    searched = [r for r in records if r["allocation"]["searched"]]
    single = [r for r in records if not r["allocation"]["searched"]]
    assert searched and single
    for r in searched:
        stripped = {k: v for k, v in r.items() if k != "preference"}
        soft, played = data.prior_targets(stripped, counts)
        assert soft == pytest.approx(r["preference"]["softmax"], abs=1e-9)
        assert played == r["preference"]["played_index"]
    assert counts["derived"] == len(searched) and counts["stored"] == 0
    for r in single:
        soft, played = data.prior_targets({k: v for k, v in r.items() if k != "preference"},
                                          counts)
        assert soft == [1.0] and played == 0
    assert counts["point_mass"] == len(single) and counts["missing"] == 0
    # a contested ballot with no evidence at all: counted, never guessed
    r = searched[0]
    bare = {k: v for k, v in r.items()
            if k not in ("preference", "allocation", "action_values")}
    c2 = {k: 0 for k in data.PREFERENCE_KEYS}
    soft, played = data.prior_targets(bare, c2)
    assert soft is None and played == [action_key(c) for c in r["ballot"]].index(
        action_key(r["action"]))
    assert c2["missing"] == 1 and c2["final_from_action"] == 1
    # a stored preference is used verbatim, even where derivation would differ
    c3 = {k: 0 for k in data.PREFERENCE_KEYS}
    k = len(r["ballot"])
    fake = {**r, "preference": {**r["preference"], "softmax": [1.0 / k] * k}}
    assert data.prior_targets(fake, c3)[0] == [1.0 / k] * k and c3["stored"] == 1
    # through the loader: preferences stripped everywhere, evidence removed on
    # five contested rows -> derived / point mass / missing, and the missing
    # rows carry no prior target in the cache
    stripped_rows = []
    removed = 0
    for rec in records:
        fields = {key: v for key, v in rec.items() if key not in ("preference", "record_sha256")}
        if rec["allocation"]["searched"] and removed < 5:
            fields["allocation"] = None
            fields["action_values"] = None
            removed += 1
        stripped_rows.append(finalize_record(fields))
    path = tmp_path / "stripped.jsonl"
    write_jsonl(path, stripped_rows)
    store = data.discover_store(path)
    block, _ = data.ensure_cache(store.shards[0], tmp_path / "cache", witness_seed=1)
    pref = block.meta["counts"]["preference"]
    assert block.n == len(records)
    assert pref["stored"] == 0 and pref["derived"] == len(searched) - 5
    assert pref["point_mass"] == len(single) and pref["missing"] == 5
    assert int(block.has_softmax.sum()) == len(records) - 5
    assert (block.played >= 0).all()
    by_sha = {r["record_sha256"]: r for r in stripped_rows}
    for i in range(block.n):
        rec = by_sha[block.record_sha256[i].decode()]
        lo, hi = block.cand_offsets[i], block.cand_offsets[i + 1]
        if rec["allocation"] is None:
            assert not block.has_softmax[i] and np.all(block.cand_softmax[lo:hi] == 0)
        else:
            assert block.has_softmax[i] and abs(block.cand_softmax[lo:hi].sum() - 1) < 1e-5


# 8 ------------------------------------------ parallel cache build: byte identity

def test_parallel_cache_build_is_byte_identical_to_sequential(store_dir, luna, tmp_path):
    luna_path, _rows = luna
    store = data.discover_store(store_dir)
    lstore = data.discover_store(luna_path)
    jobs = [(s, store.private) for s in store.shards] + [(s, True) for s in lstore.shards]
    assert len(jobs) == 3 and 1 <= data.default_cache_workers() <= data.CACHE_WORKERS_CAP
    one = data.build_caches(jobs, tmp_path / "w1", witness_seed=1, workers=1)
    log = []
    three = data.build_caches(jobs, tmp_path / "w3", witness_seed=1, workers=3,
                              progress=log.append)
    assert any("with 3 workers" in line for line in log)
    assert (sorted(b["sha256"] for b in one) == sorted(b["sha256"] for b in three)
            == sorted(s.sha256 for s, _ in jobs))
    assert {b["sha256"]: b["encoded"] for b in one} == {b["sha256"]: b["encoded"] for b in three}
    for shard, private in jobs:
        a = data.cache_path(tmp_path / "w1", shard.sha256)
        b = data.cache_path(tmp_path / "w3", shard.sha256)
        # the cache key (file name) and the shard-hash binding are unchanged
        assert a.name == b.name == f"{shard.sha256}.{encode.ENCODER_IMPLEMENTATION_SHA256[:12]}.npz"
        assert a.read_bytes() == b.read_bytes(), shard.label
        assert ((b.stat().st_mode & 0o077) == 0) == private
        block = data.load_block(b, shard_sha256=shard.sha256)
        assert block.meta["shard"]["sha256"] == shard.sha256
        assert block.meta["schema"] == data.CACHE_SCHEMA and "built_secs" not in block.meta
    assert not list((tmp_path / "w3").glob("*.tmp"))
    # a worker builds, it never reorders: cache rows follow the shard's file order
    shard0 = store.shards[0]
    block = data.load_block(data.cache_path(tmp_path / "w3", shard0.sha256))
    assert [s.decode() for s in block.record_sha256] == [
        r["record_sha256"] for r in data.iter_records(shard0)]
    # ensure_caches keeps the input order and reuses what is valid
    again = data.ensure_caches(jobs, tmp_path / "w3", witness_seed=1, workers=3)
    assert [rebuilt for _b, rebuilt in again] == [False] * 3
    assert [b.meta["shard"]["sha256"] for b, _r in again] == [s.sha256 for s, _p in jobs]
    # a stale cache (another schema) is rebuilt, byte-identical
    stale = data.cache_path(tmp_path / "w3", shard0.sha256)
    with np.load(stale, allow_pickle=False) as npz:
        arrays = {k: npz[k] for k in npz.files if k != "meta"}
    meta = {**block.meta, "schema": "shengji-train-cache-v0"}
    np.savez_compressed(stale, meta=np.asarray(json.dumps(meta, sort_keys=True)), **arrays)
    rebuilt = data.ensure_caches(jobs, tmp_path / "w3", witness_seed=1, workers=3)
    assert [r for _b, r in rebuilt] == [True, False, False]
    assert stale.read_bytes() == data.cache_path(tmp_path / "w1", shard0.sha256).read_bytes()
    # the CLI flag reaches the pool and the receipt
    rc = train_v0.main(["train", "--data", str(store_dir), "--out", str(tmp_path / "cli"),
                        "--device", "cpu", "--epochs", "1", "--batch-size", "64",
                        "--n-boot", "20", "--val-fraction", "0.5", "--cache-workers", "2"])
    assert rc == 0
    receipt = json.loads((tmp_path / "cli" / "receipt.json").read_text())
    assert receipt["cache_workers"] == 2 and receipt["counts"]["cache_rebuilt"] == 2
    assert "cache_workers" not in receipt["config"]          # execution detail, not config
    for shard in store.shards:
        assert (data.cache_path(tmp_path / "cli" / "cache", shard.sha256).read_bytes()
                == data.cache_path(tmp_path / "w1", shard.sha256).read_bytes())


# 9 ------------------------------------------------ auxiliary search-mean head

def test_aux_search_mean_head_trains_and_is_reported_separately(store_dir, records, luna,
                                                                tmp_path):
    luna_path, _rows = luna
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), device="cpu", epochs=6,
              seed=7, batch_size=32, patience=99, n_boot=20, val_fraction=0.5, log=None,
              cache_dir=str(tmp_path / "cache"), cache_workers=1)
    with_aux = train_v0.train(out=tmp_path / "aux", aux_search_mean=1.0, **kw)
    # the receipt records the weight, the head and the rows with / without a target
    assert with_aux["config"]["aux_search_mean"] == 1.0
    assert with_aux["config"]["arch"]["aux_search_mean"] is True
    counts = with_aux["counts"]["records"]["search_mean"]
    with_means = [r for r in records
                  if r["action_values"] and r["action_values"]["means"] is not None]
    assert counts == {"present": len(with_means), "absent": len(records) - len(with_means),
                      "unusable": 0}
    assert 0 < len(with_means) < len(records)
    assert with_aux["luna"]["counts"]["records"]["search_mean"] == {
        "present": 0, "absent": N_LUNA, "unusable": 0}
    # the cached target is exactly action_values.means[played_index] (the final target's index)
    shard = data.discover_store(store_dir).shards[0]
    block = data.load_block(data.cache_path(tmp_path / "cache", shard.sha256),
                            shard_sha256=shard.sha256)
    by_sha = {r["record_sha256"]: r for r in records}
    for i in range(block.n):
        r = by_sha[block.record_sha256[i].decode()]
        if r["action_values"] is None:
            assert not block.has_search_mean[i] and block.search_mean[i] == 0
        else:
            assert r["action_values"]["perspective"] == data.SEARCH_MEAN_PERSPECTIVE
            assert block.has_search_mean[i]
            assert block.played[i] == r["allocation"]["played_index"]
            assert block.search_mean[i] == pytest.approx(
                r["action_values"]["means"][block.played[i]], rel=1e-6)
    # held-out MAE (points) improves over epochs and the training term falls
    val = [e["val"]["aux_search_mae"] for e in with_aux["epochs"]]
    tr = [e["train"]["aux_search_huber"] for e in with_aux["epochs"]]
    assert len(val) == 6 and all(v is not None and v > 0 for v in val)
    assert val[-1] < 0.98 * val[0], val
    assert tr[-1] < 0.5 * tr[0], tr
    # the aux term is in the TRAINING loss only; the selection loss is value + prior
    e = with_aux["epochs"][0]
    assert e["train"]["prior_rows"] == e["train"]["rows"]
    assert e["train"]["loss"] > e["train"]["value_huber"] + e["train"]["prior_ce"] + 1e-6
    assert e["val"]["loss"] == pytest.approx(e["val"]["value_huber"] + e["val"]["prior_ce"])
    final = with_aux["final"]["val"]["aux_search_mean"]
    best = with_aux["best_epoch"]
    assert final["n"] == with_aux["epochs"][-1]["val"]["aux_search_rows"] > 0
    assert final["model"]["mae"] == pytest.approx(val[best - 1], abs=1e-4)
    assert final["stratified_prior"]["mae"] > 0 and "units" in final
    assert final["paired_diff_model_minus_prior"]["abs_error"]["n"] == final["n"]
    # the target's stratified prior is fitted on the training rows that carry it
    assert with_aux["baselines"]["search_mean_prior"]["n"] == e["train"]["aux_search_rows"] > 0
    assert "aux_search_mean" not in with_aux["final"]["luna"]     # no target on Luna
    # without the head: no aux metrics, and the primary metrics have the same layout
    without = train_v0.train(out=tmp_path / "plain", **kw)
    assert without["config"]["aux_search_mean"] == 0.0
    assert without["config"]["arch"]["aux_search_mean"] is False
    assert "aux_search_mean" not in without["final"]["val"]
    assert all(ep["val"]["aux_search_mae"] is None for ep in without["epochs"])
    assert all("aux_search_huber" not in ep["train"] for ep in without["epochs"])
    for key in ("value", "prior", "calibration"):
        assert set(without["final"]["val"][key]) == set(with_aux["final"]["val"][key]), key
    assert without["config_sha256"] != with_aux["config_sha256"]
    # the weight is refused when negative; the head is refused without the arch flag
    with pytest.raises(train_v0.TrainError):
        train_v0.build_config(data=[str(store_dir)], aux_search_mean=-1.0)
    net = model_mod.ValuePriorNet()
    batch = data.collate(block, np.arange(4))
    t = train_v0.to_tensors(batch, torch.device("cpu"), "softmax")
    with pytest.raises(ValueError, match="aux_search_mean"):
        model_mod.batch_losses(net, t, prior_weight=1.0, search_weight=1.0)
    losses = model_mod.batch_losses(model_mod.ValuePriorNet({"aux_search_mean": True}), t,
                                    prior_weight=1.0, search_weight=0.5)
    assert losses["n_search"].item() == int(block.has_search_mean[:4].sum())
    assert losses["total"].item() == pytest.approx(
        losses["value"].item() + losses["prior"].item() + 0.5 * losses["search"].item(), abs=1e-5)


# 10 --------------------------------------------------------------- sweep driver

def test_sweep_reuses_one_cache_and_matches_standalone_runs(store_dir, luna, tmp_path):
    luna_path, _rows = luna
    base = {"epochs": 3, "seed": 7, "batch_size": 32, "n_boot": 50, "val_fraction": 0.5,
            "lr": 1e-3}
    grid = [{}, {"prior_target": "final", "hidden": 64, "aux_search_mean": 1.0, "seed": 8}]
    summary = sweep.run_sweep(data=[str(store_dir)], grid=grid, out=tmp_path / "sweep",
                              eval_luna=str(luna_path), device="cpu", base=base,
                              cache_workers=2, log=None)
    rows = summary["rows"]
    assert summary["schema"] == sweep.SWEEP_SCHEMA and summary["status"] == {"ok": 2, "failed": 0}
    assert [r["index"] for r in rows] == [0, 1] and [r["overrides"] for r in rows] == grid
    # ONE shared cache, built up front in the pool; every run reused it
    assert summary["cache"]["built"] == 3 and summary["cache"]["shards"] == 3
    assert summary["cache"]["workers"] == 2
    assert [r["cache"] for r in rows] == [{"rebuilt": 0, "reused": 3}] * 2
    assert len(list((tmp_path / "sweep" / "cache").glob("*.npz"))) == 3
    assert all(not (Path(r["run"]) / "cache").exists() for r in rows)
    # every row equals a standalone run with the same config
    s0 = train_v0.train(data=[str(store_dir)], out=tmp_path / "s0", eval_luna=str(luna_path),
                        device="cpu", log=None, **base)
    s1 = train_v0.train(data=[str(store_dir)], out=tmp_path / "s1", eval_luna=str(luna_path),
                        device="cpu", log=None, **{**base, **grid[1]})
    for row, ref in zip(rows, (s0, s1)):
        assert row["config_sha256"] == ref["config_sha256"]
        assert Path(row["run"]).name == f"{row['index']:02d}-{ref['config_sha256'][:12]}"
        receipt = json.loads((Path(row["run"]) / "receipt.json").read_text())
        assert receipt["config"] == ref["config"] and receipt["final"] == ref["final"]
        v = ref["final"]["val"]["value"]
        assert row["val"]["value_mae"] == v["model"]["mae"]
        assert row["val"]["value_mse"] == v["model"]["mse"]
        assert row["val"]["prior_mae"] == v["stratified_prior"]["mae"]
        diff = v["paired_diff_model_minus_prior"]["abs_error"]
        assert row["val"]["diff_abs_error"] == {"mean": diff["mean"], "ci95": diff["ci95"],
                                                "clusters": diff["clusters"]}
        target = ref["config"]["prior_target"]
        p = ref["final"]["val"]["prior"][target]
        ce = row["val"]["prior_ce"]
        assert (ce["target"], ce["model"], ce["uniform"], ce["incumbent"]) == (
            target, p["model_ce"], p["uniform_ce"], p["incumbent_ce"])
        assert row["luna"]["value_mae"] == ref["final"]["luna"]["value"]["model"]["mae"]
        assert row["epochs"] == len(ref["epochs"]) == 3
        assert row["best_epoch"] == ref["best_epoch"] and row["wall_secs"] > 0
        assert row["config"]["hidden"] == ref["config"]["hidden"]
    # the overrides were applied: the two rows are different runs
    assert rows[0]["config_sha256"] != rows[1]["config_sha256"]
    assert rows[0]["val"]["value_mae"] != rows[1]["val"]["value_mae"]
    assert rows[0]["val"]["aux_search_mae"] is None
    assert rows[1]["val"]["aux_search_mae"] == s1["final"]["val"]["aux_search_mean"]["model"]["mae"]
    assert (rows[1]["val"]["prior_ce"]["target"], rows[1]["config"]["hidden"],
            rows[1]["config"]["seed"]) == ("final", 64, 8)
    assert rows[0]["val"]["prior_ce"]["target"] == "softmax"
    # sweep.json is the summary; sweep.md has one table row per config in grid order
    assert json.loads((tmp_path / "sweep" / "sweep.json").read_text()) == summary
    md = (tmp_path / "sweep" / "sweep.md").read_text()
    table = [line for line in md.splitlines() if line.startswith("| 0 ") or line.startswith("| 1 ")]
    assert len(table) == 2 and table[0].startswith("| 0 | baseline |")
    assert rows[0]["config_sha256"][:12] in table[0] and 'prior_target="final"' in table[1]
    assert f"{rows[1]['val']['aux_search_mae']:.2f}" in table[1]
    # a failed config is recorded, not fatal; the order is the grid order; the
    # ok row reproduces the earlier baseline row exactly (shared cache reused)
    summary2 = sweep.run_sweep(data=[str(store_dir)], grid=[{"hidden": 1}, {}],
                               out=tmp_path / "sweep2", eval_luna=str(luna_path), device="cpu",
                               base=base, cache_dir=str(tmp_path / "sweep" / "cache"),
                               cache_workers=1, log=None)
    failed, ok = summary2["rows"]
    assert failed["status"] == "failed" and "hidden" in failed["error"]
    assert failed["config_sha256"] is None and failed["run"] is None
    assert ok["status"] == "ok" and ok["index"] == 1
    assert ok["config_sha256"] == rows[0]["config_sha256"] and ok["val"] == rows[0]["val"]
    assert summary2["status"] == {"ok": 1, "failed": 1} and summary2["cache"]["built"] == 0
    assert "FAILED" in (tmp_path / "sweep2" / "sweep.md").read_text()
    # an unknown override key refuses the whole grid before anything runs
    with pytest.raises(sweep.SweepError, match="unknown override"):
        sweep.run_sweep(data=[str(store_dir)], grid=[{}, {"hiden": 64}], out=tmp_path / "sweep3",
                        device="cpu", base=base, log=None)
    assert not (tmp_path / "sweep3").exists()
    # the CLI: --set base overrides, a grid file, exit 0 when every config ran
    grid_path = tmp_path / "grid.json"
    grid_path.write_text(json.dumps([{"prior_weight": 0.5}]))
    rc = sweep.main(["--data", str(store_dir), "--grid", str(grid_path),
                     "--out", str(tmp_path / "cli"), "--device", "cpu",
                     "--cache-dir", str(tmp_path / "sweep" / "cache"), "--cache-workers", "1",
                     "--set", "epochs=1", "--set", "batch_size=64", "--set", "n_boot=20",
                     "--set", "val_fraction=0.5"])
    assert rc == 0
    cli = json.loads((tmp_path / "cli" / "sweep.json").read_text())
    assert cli["base"] == {"epochs": 1, "batch_size": 64, "n_boot": 20, "val_fraction": 0.5}
    assert cli["rows"][0]["config"]["prior_weight"] == 0.5 and cli["rows"][0]["epochs"] == 1
