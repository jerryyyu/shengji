"""train v0 (train_spec.md): loader/encoder round trip with the canonical
deal key, the STRUCTURAL (every-row) privacy witness, the three-way split
by deal key across stores + the Luna overlap refusal + receipt labels +
the persisted fit/selection populations (standalone evaluation, foreign
stores), stratified prior, prior masking + CE, training smoke with seed
determinism, preference derivation / skip, parallel cache build byte
identity, auxiliary search-mean head, sweep driver, bounded residency
with a peak-RSS memory witness (unfiltered and ``keep``-filtered), packed
features (lossless round trip + identical losses, packed-size residency
accounting, old-format caches rebuilt).

Pure engine + torch on CPU.  Three shard stores are generated here at
reduced work (N=2 selection worlds, R=30 report worlds):

* ``store_dir`` (A): 6 rounds = 3 deals (two mirrors each), seed0 SEED0;
* ``twin_dir`` (B): 2 rounds at the SAME seed0 with other knobs: the same
  deal as A's cluster 0 under a different run_id (the cross-store witness);
* ``other_dir`` (C): 2 rounds at another seed0: one deal disjoint from A,
  the source of the Luna-like private rows.
"""
import dataclasses
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.harvest import rebuild, trajectory  # noqa: E402
from shengji.harvest.common import action_key, write_jsonl  # noqa: E402
from shengji.harvest.schema import finalize_record, split_record  # noqa: E402
from shengji.rl import encode, value_afterstate  # noqa: E402
from shengji.train import baselines, data, sweep  # noqa: E402
from shengji.train import model as model_mod  # noqa: E402
from shengji.train import train_v0  # noqa: E402

SEED0 = 4_100_000
ROUNDS = 6
WORK = {"select_worlds": 2, "report_worlds": 30}
EXPLORE = {"explore_rate": 0.5, "explore_k": 2}
N_LUNA = 4
THIRDS = dict(val_fraction=1 / 3, test_fraction=1 / 3)     # 3 deals -> 1 / 1 / 1
SERVER = Path(data.__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def store_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("traj") / "run"
    trajectory.generate(rounds=ROUNDS, seed0=SEED0, out_dir=out, workers=1, merge=False,
                        **WORK, **EXPLORE)
    return out


@pytest.fixture(scope="module")
def twin_dir(tmp_path_factory):
    """The same seed0 (hence the same deal for cluster 0) with another
    exploration setting: a different run_id over the same deck."""
    out = tmp_path_factory.mktemp("twin") / "run"
    trajectory.generate(rounds=2, seed0=SEED0, out_dir=out, workers=1, merge=False,
                        **WORK, explore_rate=0.0, explore_k=2)
    return out


@pytest.fixture(scope="module")
def other_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("other") / "run"
    trajectory.generate(rounds=2, seed0=SEED0 + 7_777, out_dir=out, workers=1, merge=False,
                        **WORK, **EXPLORE)
    return out


def _records(store_dir):
    manifest = json.loads((store_dir / "manifest.json").read_text())
    recs = []
    for shard in manifest["shards"]:
        recs += [json.loads(line)
                 for line in (store_dir / shard["path"]).read_text().splitlines()]
    assert len(recs) == manifest["counts"]["records"]
    return recs


@pytest.fixture(scope="module")
def records(store_dir):
    recs = _records(store_dir)
    assert len(recs) > 200
    return recs


@pytest.fixture(scope="module")
def other_records(other_dir):
    return _records(other_dir)


def _luna_rows(records, n=N_LUNA, *, picks=None):
    """Luna-like private rows: hidden hands + deck, a wide ballot, no search
    evidence and no ``preference`` (only the played action is known)."""
    if picks is None:
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
def luna(tmp_path_factory, other_records):
    """Luna rows over the deal of store C: disjoint from the training store."""
    rows = _luna_rows(other_records)
    path = tmp_path_factory.mktemp("luna") / "luna-test.private.jsonl"
    write_jsonl(path, rows, private=True)
    return path, rows


@pytest.fixture(scope="module")
def luna_overlap(tmp_path_factory, records):
    """Luna rows over deals of the TRAINING store: must be refused."""
    path = tmp_path_factory.mktemp("luna-overlap") / "luna-overlap.private.jsonl"
    write_jsonl(path, _luna_rows(records), private=True)
    return path


@pytest.fixture(scope="module")
def luna_overlap_all(tmp_path_factory, records):
    """One Luna row per deal of the training store (every part of any
    split): contaminated for ANY checkpoint trained on it."""
    picks = {}
    for r in records:
        cluster = r["source_ref"].split(":")[1]
        if cluster not in picks and len(r["ballot"]) >= 2 and 10 <= r["ply"] <= 60:
            picks[cluster] = r
    assert len(picks) == 3
    path = tmp_path_factory.mktemp("luna-overlap-all") / "luna-overlap-all.private.jsonl"
    write_jsonl(path, _luna_rows(records, picks=list(picks.values())), private=True)
    return path


def _entries(store_dir, cache_dir):
    store = data.discover_store(store_dir)
    entries = []
    for shard in store.shards:
        data.ensure_cache(shard, cache_dir, witness_seed=1)
        entries.append((shard, str(data.cache_path(cache_dir, shard.sha256))))
    return store, entries


def _blocks(store_dir, cache_dir, **kw):
    store, entries = _entries(store_dir, cache_dir)
    return store, data.BlockStore(entries, **kw)


def _deal_key_recipe(deck):
    h = hashlib.sha256(value_afterstate.DEAL_KEY_SCHEMA.encode("ascii"))
    for card in deck:
        h.update(len(card).to_bytes(2, "big"))
        h.update(card.encode("ascii"))
    return f"deck:{h.hexdigest()}"


# 1 ------------------------------------------------- loader / encoder round trip

def test_loader_encoder_round_trip(store_dir, records, luna, tmp_path):
    cache = tmp_path / "cache"
    store = data.discover_store(store_dir)
    assert store.layout == "shard-store" and len(store.shards) == 3
    assert store.manifests and store.manifests[0]["schema"] == trajectory.MANIFEST_SCHEMA
    by_sha = {r["record_sha256"]: r for r in records}
    total = 0
    keys_by_cluster: dict[str, set] = {}
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
        # the privacy witness ran on EVERY cached row (the production default)
        assert meta["witness_every"] == 1 and meta["witness_sampled"] is False
        assert meta["counts"]["privacy_witness"] == {
            "records": block.n, "permutations": data.PRIVACY_TRIALS * block.n, "every": 1}
        assert meta["nbytes"] == block.nbytes > 0
        assert meta["deal_key_schema"] == value_afterstate.DEAL_KEY_SCHEMA == data.DEAL_KEY_SCHEMA
        assert meta["deals"] == 1 and meta["counts"]["preference"]["stored"] == block.n
        again, rebuilt2 = data.ensure_cache(shard, cache, witness_seed=1)
        assert not rebuilt2 and np.array_equal(again.obs, block.obs)
        assert np.array_equal(again.cand_feats, block.cand_feats)
        obs, cand_feats = block.obs, block.cand_feats        # unpacked once (test only)
        for i in range(block.n):
            r = by_sha[block.record_sha256[i].decode()]
            rnd = rebuild.state_for_record(r)
            assert np.array_equal(obs[i], np.asarray(encode.encode_obs(rnd, r["seat"]),
                                                     np.float32))
            lo, hi = block.cand_offsets[i], block.cand_offsets[i + 1]
            assert hi - lo == len(r["ballot"])
            expected = np.asarray([encode.encode_action(c, rnd) for c in r["ballot"]],
                                  np.float32)
            assert np.array_equal(cand_feats[lo:hi], expected)
            assert block.utility[i] == r["outcome"]["signed_level_utility"]
            assert block.attacker_points[i] == r["outcome"]["attacker_points"]
            assert block.points_so_far[i] == rnd.attacker_points
            assert block.ply[i] == r["ply"] and block.seat[i] == r["seat"]
            assert block.role_attacker[i] == (r["role"] == "attacker-team")
            run_id, cluster, _m, _s, _p = r["source_ref"].split(":")
            assert block.cluster[i] == f"{run_id}:{cluster}"
            # the canonical deal key: the digest of the dealt deck, exactly
            # the recipe of rl.value_afterstate._deal_key
            assert (str(block.deal_key[i]) == data.deal_key(r["deck"])
                    == value_afterstate._deal_key(rnd) == _deal_key_recipe(r["deck"]))
            keys_by_cluster.setdefault(str(block.cluster[i]), set()).add(str(block.deal_key[i]))
            assert block.has_softmax[i]
            assert np.allclose(block.cand_softmax[lo:hi], r["preference"]["softmax"])
            assert block.played[i] == r["preference"]["played_index"]
            total += 1
    assert total == len(records)
    # both mirrors of a cluster are ONE deal; different clusters are different deals
    assert all(len(keys) == 1 for keys in keys_by_cluster.values())
    assert len(set().union(*keys_by_cluster.values())) == len(keys_by_cluster) == 3
    with pytest.raises(data.TrainDataError):
        data.deal_key(records[0]["deck"][:-1])
    # a batch keeps every candidate of every record, masked to its ballot
    batch = data.collate(block, np.arange(min(8, block.n)))
    assert batch["mask"].sum() == block.widths[:8].sum()
    assert batch["cand"].shape[2] == encode.ACT_DIM and batch["obs"].shape[1] == encode.OBS_DIM
    assert np.all(batch["target"][~batch["mask"]] == 0)
    # Luna private rows: deck + hidden hands, no search evidence: value target
    # and the played-action target only, cache kept private, deal keys bound
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
    lobs = lblock.obs
    for i, r in enumerate(rows):
        rnd = rebuild.state_for_record(r)
        assert np.array_equal(lobs[i], np.asarray(encode.encode_obs(rnd, r["seat"]),
                                                  np.float32))
        keys = [action_key(c) for c in r["ballot"]]
        assert lblock.played[i] == keys.index(action_key(r["action"]))
        assert lblock.cluster[i] == r["source_ref"].split("#")[0].replace(
            f"-mirror-{r['source_ref'].split('-mirror-')[1][0]}", "")
        assert lblock.utility[i] == r["outcome"]["signed_level_utility"]
        assert str(lblock.deal_key[i]) == data.deal_key(r["deck"])
    assert not set(map(str, lblock.deal_key)) & set().union(*keys_by_cluster.values())


# 2 ---------------------------------------------- PRIVACY witness: every row

def test_privacy_boundary_is_structural_every_row(store_dir, records, tmp_path, monkeypatch):
    rng = random.Random(0)
    checked = 0
    for r in records:
        rnd = rebuild.state_for_record(r)
        before = [list(h) for h in rnd.hands]
        checked += data.privacy_witness(rnd, r["seat"], r["ballot"], rng)
        assert [list(h) for h in rnd.hands] == before          # state restored
    assert checked == data.PRIVACY_TRIALS * len(records)
    store = data.discover_store(store_dir)
    shard = store.shards[0]
    # a STATE-CONDITIONAL leak: the encoder reads one card of the partner's
    # hand, but only once the round has a play on the table -- the first
    # record of the shard (no plays yet) encodes honestly
    real = encode.encode_obs

    def leaky(rnd, seat):
        obs = real(rnd, seat)
        played = bool(rnd.history) or (rnd.trick is not None and bool(rnd.trick.plays))
        if played:
            partner = rnd.hands[(seat + 2) % 4]
            if partner:
                # into a float32 column (the attacker points): a card plane
                # would refuse the non-dyadic value at packing time
                obs[508] += 1e-3 * encode.CARD_INDEX[partner[0]]
        return obs

    monkeypatch.setattr(data, "encode_obs", leaky)
    r = next(r for r in records if 10 <= r["ply"] <= 60 and len(r["ballot"]) >= 2)
    with pytest.raises(data.PrivacyError, match="cannot see"):
        data.privacy_witness(rebuild.state_for_record(r), r["seat"], r["ballot"],
                             random.Random(0))
    # PRODUCTION DEFAULT (no witness settings passed): the shard build refuses
    # and leaves no cache file; the same through ensure_cache / ensure_caches
    with pytest.raises(data.PrivacyError, match="cannot see"):
        data.build_cache(shard, tmp_path / "prod", witness_seed=1)
    assert not data.cache_path(tmp_path / "prod", shard.sha256).exists()
    with pytest.raises(data.PrivacyError):
        data.ensure_cache(shard, tmp_path / "prod", witness_seed=1)
    with pytest.raises(data.PrivacyError):
        data.ensure_caches([(shard, False)], tmp_path / "prod", witness_seed=1, workers=1)
    assert not list((tmp_path / "prod").glob("*.npz")) if (tmp_path / "prod").exists() else True
    # RED: a SAMPLED witness (the pre-repair production setting) misses the
    # leak -- only the honest first record is checked, the shard is cached
    # and would have been trained on.  Sampling is therefore refused unless
    # explicitly allowed, and the cache records that it was sampled.
    with pytest.raises(data.TrainDataError, match="allow-sampled-privacy-witness"):
        data.build_cache(shard, tmp_path / "sampled", witness_seed=1, witness_every=2)
    path, counts = data.build_cache(shard, tmp_path / "sampled", witness_seed=1,
                                    witness_every=10 ** 9, allow_sampled_witness=True)
    assert path.is_file() and counts["privacy_witness"] == {
        "records": 1, "permutations": data.PRIVACY_TRIALS, "every": 10 ** 9}
    meta = data.read_meta(path)
    assert meta["witness_sampled"] is True and meta["witness_every"] == 10 ** 9
    # a production run never reuses a sampled cache: loading it under the
    # every-row requirement refuses, ensure_caches rebuilds it (and, with
    # the leaky encoder still in place, refuses the rebuild)
    with pytest.raises(data.PrivacyError, match="refusing to reuse"):
        data.load_block(path, shard_sha256=shard.sha256, witness_every=1)
    assert data.load_block(path, shard_sha256=shard.sha256, witness_every=10 ** 9).n > 0
    with pytest.raises(data.PrivacyError, match="cannot see"):
        data.ensure_caches([(shard, False)], tmp_path / "sampled", witness_seed=1, workers=1)
    # the honest encoder: a sampled cache is REBUILT every-row by production
    monkeypatch.setattr(data, "encode_obs", real)
    (meta_rebuilt, rebuilt), = data.ensure_caches([(shard, False)], tmp_path / "sampled",
                                                  witness_seed=1, workers=1)
    assert rebuilt and meta_rebuilt["witness_every"] == 1
    assert meta_rebuilt["counts"]["privacy_witness"]["records"] == meta_rebuilt["counts"]["encoded"]
    # the training entry points: N > 1 is refused without the flag; with it,
    # the receipt records the sampled witness
    kw = dict(data=[str(store_dir)], device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=20, log=None, cache_dir=str(tmp_path / "train-cache"), **THIRDS)
    with pytest.raises(train_v0.TrainError, match="allow-sampled-privacy-witness"):
        train_v0.train(out=tmp_path / "t1", privacy_witness_every=4, **kw)
    assert not (tmp_path / "train-cache").exists()
    receipt = train_v0.train(out=tmp_path / "t2", privacy_witness_every=4,
                             allow_sampled_privacy_witness=True, **kw)
    assert receipt["privacy_witness"] == {"every": 4, "sampled": True, "allowed_sampled": True,
                                          "trials_per_row": data.PRIVACY_TRIALS}
    assert all(c["witness_every"] == 4 for c in receipt["data"][0]["cache"])
    assert "privacy_witness_every" not in receipt["config"]      # execution detail
    receipt2 = train_v0.train(out=tmp_path / "t3", **kw)
    assert receipt2["privacy_witness"]["every"] == 1 and not receipt2["privacy_witness"]["sampled"]
    assert receipt2["counts"]["cache_rebuilt"] == 3               # the sampled caches were replaced
    assert all(c["witness_every"] == 1 for c in receipt2["data"][0]["cache"])


# 3 ------------------------------------ split by DEAL KEY, across stores, 3-way

def test_split_is_by_deal_key_across_stores_and_three_way(store_dir, twin_dir, other_dir,
                                                          records, luna, luna_overlap,
                                                          luna_overlap_all, tmp_path):
    keys = [f"deck:{i:064x}" for i in range(200)]
    for seed in (1, 2):
        a = data.split_deals(keys, seed=seed, val_fraction=0.1, test_fraction=0.1)
        assert data.split_counts(a) == {"train": 160, "val": 20, "test": 20} and len(a) == 200
        assert a == data.split_deals(list(reversed(keys)), seed=seed, val_fraction=0.1,
                                     test_fraction=0.1)
    assert data.split_deals(keys, seed=1) != data.split_deals(keys, seed=2)
    assert data.split_counts(data.split_deals(keys, seed=1)) == {"train": 160, "val": 20, "test": 20}
    assert set(data.split_deals(["only"], seed=1).values()) == {"train"}
    assert data.split_counts(data.split_deals(["a", "b"], seed=1)) == {"train": 1, "val": 0, "test": 1}
    assert data.split_counts(data.split_deals(["a", "b", "c"], seed=1, **THIRDS)) == {
        "train": 1, "val": 1, "test": 1}
    with pytest.raises(data.TrainDataError):
        data.split_deals(keys, seed=1, val_fraction=0.5, test_fraction=0.5)
    # the same deal in two stores: A's cluster 0 and B (same seed0, other
    # knobs) share the deck under DIFFERENT run_ids
    cache = tmp_path / "cache"
    store_a, entries_a = _entries(store_dir, cache)
    store_b, entries_b = _entries(twin_dir, cache)
    bs = data.BlockStore(entries_a + entries_b)
    run_a = records[0]["source_ref"].split(":")[0]
    run_b = json.loads((twin_dir / "manifest.json").read_text())["run_id"]
    assert run_a != run_b and run_a.split("-")[1] == run_b.split("-")[1] == f"s{SEED0}"
    keys_by_cluster: dict[str, set] = {}
    for block in bs.iter_blocks():
        for c, k in zip(block.cluster, block.deal_key):
            keys_by_cluster.setdefault(str(c), set()).add(str(k))
    assert keys_by_cluster[f"{run_b}:0"] == keys_by_cluster[f"{run_a}:0"]
    shared = next(iter(keys_by_cluster[f"{run_b}:0"]))
    assert len(bs.keys()) == 3 and shared in bs.keys()

    def parts_of(shared_key, assignment, column):
        parts = set()
        for block in bs.iter_blocks():
            rows = np.flatnonzero(block.deal_key == shared_key)
            for part in data.SPLIT_PARTS:
                chosen = np.asarray([assignment[str(c)] == part for c in column(block)])
                if chosen[rows].any():
                    parts.add(part)
        return parts

    # keyed by deal: every row of the shared deal (both stores, both mirrors)
    # lands on ONE side, for every seed
    for seed in range(1, 41):
        assignment = data.split_deals(bs.keys(), seed=seed, **THIRDS)
        assert len(parts_of(shared, assignment, lambda b: b.deal_key)) == 1
        masks = {p: [data.split_mask(b, assignment, p) for b in bs.iter_blocks()]
                 for p in data.SPLIT_PARTS}
        for i in range(len(bs)):
            stacked = np.stack([masks[p][i] for p in data.SPLIT_PARTS])
            assert (stacked.sum(axis=0) == 1).all()               # exactly one part per row
        assert all(any(m.any() for m in masks[p]) for p in data.SPLIT_PARTS)
    # RED under the pre-repair key (<run_id>:<cluster>): the shared deal
    # has two keys and some seed puts its two copies on different sides
    split_by_cluster = [
        parts_of(shared, data.split_deals(sorted(keys_by_cluster), seed=seed, **THIRDS),
                 lambda b: b.cluster)
        for seed in range(1, 41)]
    assert any(len(parts) > 1 for parts in split_by_cluster), "run_id:cluster keying leaks"
    # the batch iterators see exactly the rows of their part
    assignment = data.split_deals(bs.keys(), seed=1, **THIRDS)
    n = {p: sum(int(data.split_mask(b, assignment, p).sum()) for b in bs.iter_blocks())
         for p in data.SPLIT_PARTS}
    assert sum(n.values()) == sum(b.n for b in bs.iter_blocks())
    for part in data.SPLIT_PARTS:
        seen = set()
        rows = 0
        for batch in bs.iter_batches(lambda b, p=part: data.split_mask(b, assignment, p), 32,
                                     rng=np.random.default_rng(0), window=2):
            rows += len(batch["idx"])
            seen.update(zip(batch["block"].tolist(), batch["row"].tolist()))
            for j, row in zip(batch["block"], batch["row"]):
                assert assignment[str(bs.block(int(j)).deal_key[row])] == part
        assert rows == n[part] == len(seen)
    # the Luna set is refused when it shares a deal with the data stores
    kw = dict(data=[str(store_dir)], device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=20, log=None, cache_dir=str(cache), **THIRDS)
    with pytest.raises(train_v0.TrainError, match=r"shares [123] deal\(s\) with the data stores"):
        train_v0.train(out=tmp_path / "overlap", eval_luna=str(luna_overlap), **kw)
    assert not (tmp_path / "overlap" / "receipt.json").exists()
    receipt = train_v0.train(out=tmp_path / "ok", eval_luna=str(luna[0]), **kw)
    assert receipt["luna"]["shared_deals_with_training"] == 0
    assert receipt["luna"]["checked_against"] == receipt["population"]["digest"]
    # the persisted populations: the deal keys of every part, disjoint, in
    # the receipt and in every checkpoint
    population = receipt["population"]
    assert population["schema"] == train_v0.POPULATION_SCHEMA
    assert population["counts"] == {"train": 1, "val": 1, "test": 1}
    sets = train_v0.population_sets(population)
    assert sets["train"] | sets["val"] | sets["test"] == set(bs.keys()) - {shared} | {shared}
    for name in ("best.pt", "checkpoints/epoch-01.pt"):
        payload = torch.load(tmp_path / "ok" / name, map_location="cpu", weights_only=False)
        assert payload["population"] == population
    ckpt = str(tmp_path / "ok" / "best.pt")
    ev_kw = dict(checkpoint=ckpt, device="cpu", n_boot=20, log=None, cache_dir=str(cache))
    # STANDALONE evaluate (no --data) on contaminated Luna sets: refused
    # against the checkpoint's own fit/selection deals
    with pytest.raises(train_v0.TrainError, match="fit/selection population"):
        train_v0.evaluate(out=tmp_path / "ev-bad", eval_luna=str(luna_overlap_all), **ev_kw)
    with pytest.raises(train_v0.TrainError, match="fit/selection population"):
        train_v0.evaluate(out=tmp_path / "ev-bad2", eval_luna=str(luna_overlap), **ev_kw)
    with pytest.raises(train_v0.TrainError, match="fit/selection population"):
        train_v0.evaluate(out=tmp_path / "ev-bad3", data=[str(store_dir)],
                          eval_luna=str(luna_overlap_all), **ev_kw)
    assert not (tmp_path / "ev-bad" / "receipt.json").exists()
    # a clean Luna set without --data: checked against the checkpoint,
    # labelled held out with an explicit zero
    ev = train_v0.evaluate(out=tmp_path / "ev-luna", eval_luna=str(luna[0]), **ev_kw)
    assert ev["headline"] == "luna" and ev["final"]["luna"]["held_out"] is True
    assert ev["luna"]["shared_deals_with_training"] == 0 and ev["luna"]["shared_with_test"] == 0
    assert ev["luna"]["checked_against"] == population["digest"]
    assert ev["final"]["luna"]["population"] == {
        "deals": 1, "in_train": 0, "in_val": 0, "in_test": 0, "novel": 1,
        "shared_with_fit": 0, "shared_with_selection": 0, "same_population": False,
        "checked_against": population["digest"]}
    assert ev["population"] == population
    # FOREIGN-DATA substitution: store C is not the checkpoint's population;
    # its deals are novel -> reported, held out only as --split novel, and
    # the checkpoint's test part has no rows there (refused, not relabelled)
    with pytest.raises(train_v0.TrainError, match="no deal of the checkpoint's 'test'"):
        train_v0.evaluate(out=tmp_path / "ev-c-test", data=[str(other_dir)], **ev_kw)
    ev = train_v0.evaluate(out=tmp_path / "ev-c-novel", data=[str(other_dir)], split="novel",
                           **ev_kw)
    assert ev["headline"] == "novel" and ev["final"]["novel"]["held_out"] is True
    assert ev["split"]["population_match"] == {
        "deals": 1, "in_train": 0, "in_val": 0, "in_test": 0, "novel": 1,
        "shared_with_fit": 0, "shared_with_selection": 0, "same_population": False,
        "checked_against": population["digest"]}
    assert ev["final"]["novel"]["population"]["novel"] == 1 and ev["split"]["deals"] == 1
    assert ev["final"]["novel"]["value"]["n"] == sum(b.n for b in _blocks(other_dir, cache)[1].iter_blocks())
    # store B replays a deal the checkpoint HAS seen (A's deal 0) under
    # another run_id: not novel; evaluating it as the part it belongs to
    # reports the substitution, and it is held out only if that part is test
    part = next(p for p in ("train", "val", "test") if shared in sets[p])
    with pytest.raises(train_v0.TrainError, match="no deal of the checkpoint's 'novel'"):
        train_v0.evaluate(out=tmp_path / "ev-b-novel", data=[str(twin_dir)], split="novel",
                          **ev_kw)
    ev = train_v0.evaluate(out=tmp_path / "ev-b", data=[str(twin_dir)], split=part, **ev_kw)
    match = ev["split"]["population_match"]
    assert match["same_population"] is False and match["deals"] == 1 and match["novel"] == 0
    assert match[f"in_{part}"] == 1
    assert ev["final"][part]["held_out"] is (part == "test")
    assert ev["headline"] == ("test" if part == "test" else None)
    for other in ("train", "val", "test"):
        if other != part:
            with pytest.raises(train_v0.TrainError, match="no deal of the checkpoint"):
                train_v0.evaluate(out=tmp_path / f"ev-b-{other}", data=[str(twin_dir)],
                                  split=other, **ev_kw)
    # the receipt refuses to label validation metrics as held out, a
    # headline that is not held out, a calibration fitted on a held-out
    # split, an UNCHECKED held-out population, and a Luna overlap of None
    assert train_v0.check_receipt(receipt) is receipt
    bad = json.loads(json.dumps(receipt))
    bad["final"]["val"]["held_out"] = True
    with pytest.raises(train_v0.TrainError, match="NOT held out"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    bad["headline"] = "val"
    with pytest.raises(train_v0.TrainError, match="headline"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    bad["calibration"]["fitted_on"] = "test"
    with pytest.raises(train_v0.TrainError, match="calibration"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    bad["final"]["test"]["held_out"] = False
    with pytest.raises(train_v0.TrainError, match="held out"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    bad["luna"]["shared_deals_with_training"] = 2
    with pytest.raises(train_v0.TrainError, match="Luna"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    bad["luna"]["shared_deals_with_training"] = None
    with pytest.raises(train_v0.TrainError, match="unknown or non-zero"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    bad["final"]["luna"]["population"]["shared_with_fit"] = None
    with pytest.raises(train_v0.TrainError, match="not checked"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    del bad["final"]["test"]["population"]
    with pytest.raises(train_v0.TrainError, match="not checked"):
        train_v0.check_receipt(bad)
    bad = json.loads(json.dumps(receipt))
    bad["population"]["val"] = bad["population"]["test"]
    with pytest.raises(train_v0.TrainError, match="not a split"):
        train_v0.check_receipt(bad)
    # a checkpoint without persisted populations cannot be evaluated
    payload = torch.load(ckpt, map_location="cpu", weights_only=False)
    del payload["population"]
    torch.save(payload, tmp_path / "no-population.pt")
    with pytest.raises(train_v0.TrainError, match="no persisted"):
        train_v0.evaluate(out=tmp_path / "ev-nopop", eval_luna=str(luna[0]),
                          **{**ev_kw, "checkpoint": str(tmp_path / "no-population.pt")})


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
              seed=7, batch_size=64, n_boot=50, log=None, **THIRDS)
    r1 = train_v0.train(out=tmp_path / "a", **kw)
    r2 = train_v0.train(out=tmp_path / "b", **kw)
    for key in train_v0.REQUIRED_RECEIPT_FIELDS:
        assert key in r1, key
    assert r1["schema"] == train_v0.RECEIPT_SCHEMA and r1["command"] == "train"
    assert r1["encoder"]["implementation_sha256"] == encode.ENCODER_IMPLEMENTATION_SHA256
    assert r1["encoder"]["enc_version"] == encode.ENC_VERSION
    assert len(r1["git"]["sha"]) == 40
    assert r1["data"][0]["layout"] == "shard-store" and len(r1["data"][0]["shards"]) == 3
    assert all(len(s["sha256"]) == 64 for s in r1["data"][0]["shards"])
    assert r1["data"][0]["manifests"][0]["schema"] == trajectory.MANIFEST_SCHEMA
    assert len(r1["config_sha256"]) == 64 and r1["seeds"]["torch"] == 7
    assert r1["config"]["test_fraction"] == pytest.approx(1 / 3)
    # the three-way split by deal: one deal each; every record in exactly one part
    split = r1["split"]
    assert (split["train_deals"], split["val_deals"], split["test_deals"]) == (1, 1, 1)
    assert (split["train_records"] + split["val_records"] + split["test_records"]
            == r1["counts"]["records_total"]) and r1["counts"]["deals_total"] == 3
    assert split["roles"]["val"] == train_v0.SPLIT_ROLES["val"]["role"]
    # the persisted populations name the deals of every part (disjoint)
    population = r1["population"]
    assert population["counts"] == {"train": 1, "val": 1, "test": 1}
    assert population["data"][0]["shards"] == [{"label": s["label"], "sha256": s["sha256"]}
                                               for s in r1["data"][0]["shards"]]
    sets = train_v0.population_sets(population)
    assert all(k.startswith("deck:") for part in sets.values() for k in part)
    assert r1["final"]["test"]["population"]["in_test"] == 1
    assert r1["final"]["val"]["population"]["shared_with_selection"] == 1
    # per-epoch telemetry is VALIDATION (tuning); nothing of the test split
    assert len(r1["epochs"]) == 2
    for row in r1["epochs"]:
        assert {"epoch", "train", "val", "val_role", "secs"} <= set(row) and "test" not in row
        assert row["train"]["loss"] > 0 and row["val"]["loss"] > 0
    assert r1["selection"]["split"] == "val" and r1["selection"]["best_epoch"] == r1["best_epoch"]
    # the headline is the TEST split: held out, calibration applied out of sample
    assert r1["headline"] == "test"
    test = r1["final"]["test"]
    assert test["held_out"] is True and test["split"] == "test"
    assert test["value"]["n"] == split["test_records"] and test["deals"] == 1
    for who in ("model", "stratified_prior"):
        assert test["value"][who]["mae"] >= 0 and test["value"][who]["mse"] >= 0
    diff = test["value"]["paired_diff_model_minus_prior"]["abs_error"]
    assert len(diff["ci95"]) == 2       # one deal: a degenerate CI at the mean (to rounding)
    assert diff["ci95"][0] - 1e-9 <= diff["mean"] <= diff["ci95"][1] + 1e-9
    assert diff["clusters"] == 1 and diff["n_boot"] == 50
    prior = test["prior"]["softmax"]
    assert prior["n"] > 0 and prior["uniform_ce"] > 0 and prior["incumbent_ce"] > 0
    assert 0 <= prior["top1_agreement"] <= 1
    assert test["calibration"]["in_sample"] is False and test["calibration"]["fitted_on"] == "val"
    # the validation block is tuning telemetry, labelled so; its calibration is in-sample
    val = r1["final"]["val"]
    assert val["held_out"] is False and "NOT held out" in val["role"]
    assert val["value"]["n"] == split["val_records"]
    assert val["calibration"]["in_sample"] is True
    assert val["calibration"]["mae_after"] <= val["calibration"]["mae_before"] + 1e-9
    assert r1["calibration"]["fitted_on"] == "val"
    assert r1["baselines"]["stratified_prior"]["n"] == split["train_records"]
    assert r1["baselines"]["fitted_on"] == "train"
    assert r1["baselines"]["incumbent"]["softmax"]["eps"] in baselines.INCUMBENT_EPS_GRID
    luna_m = r1["final"]["luna"]
    assert luna_m["held_out"] is True and luna_m["value"]["n"] == N_LUNA
    assert luna_m["prior"]["final"]["n"] == N_LUNA
    assert luna_m["prior"]["softmax"]["n"] == 0            # no search evidence on Luna
    assert "mae_after" in luna_m["calibration"] and luna_m["calibration"]["in_sample"] is False
    assert r1["luna"]["shared_deals_with_training"] == 0 and r1["luna"]["shared_with_test"] == 0
    assert luna_m["population"]["novel"] == 1
    # residency and privacy are on the receipt
    res = r1["residency"]
    assert res["budget_bytes"] == data.default_resident_bytes() > 0
    assert res["decoded_bytes_data"] == r1["counts"]["decoded_bytes"] > 0
    assert res["all_resident_bytes"] == res["decoded_bytes_data"] + res["decoded_bytes_luna"]
    assert res["peak_resident_bytes"] <= res["all_resident_bytes"]
    assert r1["privacy_witness"]["every"] == 1
    out = tmp_path / "a"
    assert (out / "receipt.json").is_file() and (out / "metrics.json").is_file()
    assert (out / "best.pt").is_file()
    assert sorted(p.name for p in (out / "checkpoints").iterdir()) == ["epoch-01.pt", "epoch-02.pt"]
    assert json.loads((out / "receipt.json").read_text())["final"] == r1["final"]
    # a fixed seed reproduces every metric exactly
    assert _strip_secs(r1["epochs"]) == _strip_secs(r2["epochs"])
    assert r1["final"] == r2["final"] and r1["config_sha256"] == r2["config_sha256"]
    assert r1["population"] == r2["population"]
    # a different seed changes them (the seed is applied)
    r3 = train_v0.train(out=tmp_path / "c", **{**kw, "seed": 8})
    assert _strip_secs(r3["epochs"]) != _strip_secs(r1["epochs"])
    # evaluate reproduces the checkpoint's TEST metrics (its default split,
    # the persisted test population of the same store) and Luna
    ev = train_v0.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "e",
                           data=[str(store_dir)], eval_luna=str(luna_path), device="cpu",
                           n_boot=50, log=None)
    assert ev["command"] == "evaluate" and ev["headline"] == "test"
    assert ev["final"]["test"]["value"]["model"] == test["value"]["model"]
    assert ev["final"]["test"]["held_out"] is True
    assert ev["final"]["test"]["population"] == test["population"]
    assert ev["final"]["luna"]["value"]["model"] == luna_m["value"]["model"]
    assert ev["split"]["records"] == split["test_records"]
    assert ev["split"]["population_match"]["same_population"] is True
    assert ev["split"]["population_match"]["novel"] == 0
    assert ev["population"] == population
    ev_val = train_v0.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "ev",
                               data=[str(store_dir)], device="cpu", split="val", n_boot=50,
                               log=None)
    assert ev_val["final"]["val"]["value"]["model"] == val["value"]["model"]
    assert ev_val["final"]["val"]["held_out"] is False and ev_val["headline"] is None
    ev_all = train_v0.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "ev-all",
                               data=[str(store_dir)], device="cpu", split="all", n_boot=20,
                               log=None)
    assert ev_all["final"]["all"]["held_out"] is False and ev_all["headline"] is None
    assert ev_all["final"]["all"]["value"]["n"] == r1["counts"]["records_total"]
    # a run needs all three parts: two deals cannot be split three ways
    with pytest.raises(train_v0.TrainError, match="need all three"):
        train_v0.train(out=tmp_path / "two", limit_clusters=2, **kw)
    with pytest.raises(train_v0.TrainError):
        train_v0.build_config(data=[str(store_dir)], val_fraction=0.5, test_fraction=0.5)
    with pytest.raises(train_v0.TrainError):
        train_v0.build_config(data=[str(store_dir)], test_fraction=0.0)


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
    assert len(jobs) == 4 and 1 <= data.default_cache_workers() <= data.CACHE_WORKERS_CAP
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
        block = data.load_block(b, shard_sha256=shard.sha256, witness_every=1)
        assert block.meta["shard"]["sha256"] == shard.sha256
        assert block.meta["schema"] == data.CACHE_SCHEMA and "built_secs" not in block.meta
        assert block.meta["witness_every"] == 1               # every row, in the pool too
        assert block.meta["counts"]["privacy_witness"]["records"] == block.n
    assert not list((tmp_path / "w3").glob("*.tmp"))
    # a worker builds, it never reorders: cache rows follow the shard's file order
    shard0 = store.shards[0]
    block = data.load_block(data.cache_path(tmp_path / "w3", shard0.sha256))
    assert [s.decode() for s in block.record_sha256] == [
        r["record_sha256"] for r in data.iter_records(shard0)]
    # ensure_caches keeps the input order and reuses what is valid (metas only)
    again = data.ensure_caches(jobs, tmp_path / "w3", witness_seed=1, workers=3)
    assert [rebuilt for _m, rebuilt in again] == [False] * 4
    assert [m["shard"]["sha256"] for m, _r in again] == [s.sha256 for s, _p in jobs]
    # a stale cache (another schema) is rebuilt, byte-identical
    stale = data.cache_path(tmp_path / "w3", shard0.sha256)
    with np.load(stale, allow_pickle=False) as npz:
        arrays = {k: npz[k] for k in npz.files if k != "meta"}
    meta = {**block.meta, "schema": "shengji-train-cache-v0"}
    np.savez_compressed(stale, meta=np.asarray(json.dumps(meta, sort_keys=True)), **arrays)
    rebuilt = data.ensure_caches(jobs, tmp_path / "w3", witness_seed=1, workers=3)
    assert [r for _b, r in rebuilt] == [True, False, False, False]
    assert stale.read_bytes() == data.cache_path(tmp_path / "w1", shard0.sha256).read_bytes()
    # a cache whose witness was sampled is rebuilt every-row, byte-identical
    data.build_cache(shard0, tmp_path / "w3", witness_seed=1, witness_every=5,
                     allow_sampled_witness=True)
    assert data.read_meta(stale)["witness_sampled"] is True
    rebuilt = data.ensure_caches(jobs, tmp_path / "w3", witness_seed=1, workers=3)
    assert [r for _b, r in rebuilt] == [True, False, False, False]
    assert stale.read_bytes() == data.cache_path(tmp_path / "w1", shard0.sha256).read_bytes()
    # the CLI flag reaches the pool and the receipt
    rc = train_v0.main(["train", "--data", str(store_dir), "--out", str(tmp_path / "cli"),
                        "--device", "cpu", "--epochs", "1", "--batch-size", "64",
                        "--n-boot", "20", "--val-fraction", "0.34", "--test-fraction", "0.33",
                        "--cache-workers", "2"])
    assert rc == 0
    receipt = json.loads((tmp_path / "cli" / "receipt.json").read_text())
    assert receipt["cache_workers"] == 2 and receipt["counts"]["cache_rebuilt"] == 3
    assert "cache_workers" not in receipt["config"]          # execution detail, not config
    assert receipt["privacy_witness"] == {"every": 1, "sampled": False, "allowed_sampled": False,
                                          "trials_per_row": data.PRIVACY_TRIALS}
    for shard in store.shards:
        assert (data.cache_path(tmp_path / "cli" / "cache", shard.sha256).read_bytes()
                == data.cache_path(tmp_path / "w1", shard.sha256).read_bytes())
    # sampling from the CLI needs the explicit flag
    rc = train_v0.main(["train", "--data", str(store_dir), "--out", str(tmp_path / "cli2"),
                        "--device", "cpu", "--epochs", "1", "--privacy-witness-every", "3"])
    assert rc == 2 and not (tmp_path / "cli2" / "receipt.json").exists()


# 9 ------------------------------------------------ auxiliary search-mean head

def test_aux_search_mean_head_trains_and_is_reported_separately(store_dir, records, luna,
                                                                tmp_path):
    luna_path, _rows = luna
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), device="cpu", epochs=6,
              seed=7, batch_size=32, patience=99, n_boot=20, log=None,
              cache_dir=str(tmp_path / "cache"), cache_workers=1, **THIRDS)
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
    # validation MAE (points) improves over epochs and the training term falls
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
    final_val = with_aux["final"]["val"]["aux_search_mean"]
    best = with_aux["best_epoch"]
    assert final_val["n"] == with_aux["epochs"][-1]["val"]["aux_search_rows"] > 0
    assert final_val["model"]["mae"] == pytest.approx(val[best - 1], abs=1e-4)
    final = with_aux["final"]["test"]["aux_search_mean"]
    assert final["n"] > 0 and final["model"]["mae"] > 0
    assert final["stratified_prior"]["mae"] > 0 and "units" in final
    assert final["paired_diff_model_minus_prior"]["abs_error"]["n"] == final["n"]
    # the target's stratified prior is fitted on the training rows that carry it
    assert with_aux["baselines"]["search_mean_prior"]["n"] == e["train"]["aux_search_rows"] > 0
    assert "aux_search_mean" not in with_aux["final"]["luna"]     # no target on Luna
    # without the head: no aux metrics, and the primary metrics have the same layout
    without = train_v0.train(out=tmp_path / "plain", **kw)
    assert without["config"]["aux_search_mean"] == 0.0
    assert without["config"]["arch"]["aux_search_mean"] is False
    assert "aux_search_mean" not in without["final"]["test"]
    assert all(ep["val"]["aux_search_mae"] is None for ep in without["epochs"])
    assert all("aux_search_huber" not in ep["train"] for ep in without["epochs"])
    for key in ("value", "prior", "calibration"):
        assert set(without["final"]["test"][key]) == set(with_aux["final"]["test"][key]), key
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

def test_sweep_reuses_one_cache_and_matches_standalone_runs(store_dir, luna, luna_overlap,
                                                            tmp_path):
    luna_path, _rows = luna
    base = {"epochs": 3, "seed": 7, "batch_size": 32, "n_boot": 50, "lr": 1e-3, **THIRDS}
    grid = [{}, {"prior_target": "final", "hidden": 64, "aux_search_mean": 1.0, "seed": 8}]
    summary = sweep.run_sweep(data=[str(store_dir)], grid=grid, out=tmp_path / "sweep",
                              eval_luna=str(luna_path), device="cpu", base=base,
                              cache_workers=2, log=None)
    rows = summary["rows"]
    assert summary["schema"] == sweep.SWEEP_SCHEMA and summary["status"] == {"ok": 2, "failed": 0}
    assert [r["index"] for r in rows] == [0, 1] and [r["overrides"] for r in rows] == grid
    assert summary["headline"] == "test" and summary["privacy_witness"]["every"] == 1
    # ONE shared cache, built up front in the pool; every run reused it
    assert summary["cache"]["built"] == 4 and summary["cache"]["shards"] == 4
    assert summary["cache"]["workers"] == 2 and summary["cache"]["deals"] == 3
    assert [r["cache"] for r in rows] == [{"rebuilt": 0, "reused": 4}] * 2
    assert len(list((tmp_path / "sweep" / "cache").glob("*.npz"))) == 4
    assert all(not (Path(r["run"]) / "cache").exists() for r in rows)
    # every row equals a standalone run with the same config; the row's
    # headline fields are the TEST split, val is labelled tuning
    s0 = train_v0.train(data=[str(store_dir)], out=tmp_path / "s0", eval_luna=str(luna_path),
                        device="cpu", log=None, **base)
    s1 = train_v0.train(data=[str(store_dir)], out=tmp_path / "s1", eval_luna=str(luna_path),
                        device="cpu", log=None, **{**base, **grid[1]})
    for row, ref in zip(rows, (s0, s1)):
        assert row["config_sha256"] == ref["config_sha256"]
        assert Path(row["run"]).name == f"{row['index']:02d}-{ref['config_sha256'][:12]}"
        receipt = json.loads((Path(row["run"]) / "receipt.json").read_text())
        assert receipt["config"] == ref["config"] and receipt["final"] == ref["final"]
        v = ref["final"]["test"]["value"]
        assert row["headline"] == "test" and row["test"]["held_out"] is True
        assert row["test"]["value_mae"] == v["model"]["mae"]
        assert row["test"]["value_mse"] == v["model"]["mse"]
        assert row["test"]["prior_mae"] == v["stratified_prior"]["mae"]
        diff = v["paired_diff_model_minus_prior"]["abs_error"]
        assert row["test"]["diff_abs_error"] == {"mean": diff["mean"], "ci95": diff["ci95"],
                                                 "clusters": diff["clusters"]}
        target = ref["config"]["prior_target"]
        p = ref["final"]["test"]["prior"][target]
        ce = row["test"]["prior_ce"]
        assert (ce["target"], ce["model"], ce["uniform"], ce["incumbent"]) == (
            target, p["model_ce"], p["uniform_ce"], p["incumbent_ce"])
        assert row["val"]["held_out"] is False and "NOT held out" in row["val"]["role"]
        assert row["val"]["value_mae"] == ref["final"]["val"]["value"]["model"]["mae"]
        assert row["val"]["calibration_in_sample"] is True
        assert row["test"]["calibration_in_sample"] is False
        assert row["luna"]["value_mae"] == ref["final"]["luna"]["value"]["model"]["mae"]
        assert row["epochs"] == len(ref["epochs"]) == 3
        assert row["best_epoch"] == ref["best_epoch"] and row["wall_secs"] > 0
        assert row["config"]["hidden"] == ref["config"]["hidden"]
        assert row["selection"]["split"] == "val"
        assert row["population"] == {"counts": ref["population"]["counts"],
                                     "digest": ref["population"]["digest"]}
    # the overrides were applied: the two rows are different runs
    assert rows[0]["config_sha256"] != rows[1]["config_sha256"]
    assert rows[0]["test"]["value_mae"] != rows[1]["test"]["value_mae"]
    assert rows[0]["test"]["aux_search_mae"] is None
    assert rows[1]["test"]["aux_search_mae"] == s1["final"]["test"]["aux_search_mean"]["model"]["mae"]
    assert (rows[1]["test"]["prior_ce"]["target"], rows[1]["config"]["hidden"],
            rows[1]["config"]["seed"]) == ("final", 64, 8)
    assert rows[0]["test"]["prior_ce"]["target"] == "softmax"
    # sweep.json is the summary; sweep.md has one table row per config in
    # grid order, TEST columns as the headline and the val column named tuning
    assert json.loads((tmp_path / "sweep" / "sweep.json").read_text()) == summary
    md = (tmp_path / "sweep" / "sweep.md").read_text()
    header = next(line for line in md.splitlines() if line.startswith("| # |"))
    assert "TEST MAE model / prior" in header and "(tuning)" in header
    assert "HEADLINE = the TEST split" in md
    table = [line for line in md.splitlines() if line.startswith("| 0 ") or line.startswith("| 1 ")]
    assert len(table) == 2 and table[0].startswith("| 0 | baseline |")
    assert rows[0]["config_sha256"][:12] in table[0] and 'prior_target="final"' in table[1]
    assert f"{rows[1]['test']['aux_search_mae']:.2f}" in table[1]
    assert f"{rows[0]['test']['value_mae']:.3f} / {rows[0]['test']['prior_mae']:.3f}" in table[0]
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
    assert ok["config_sha256"] == rows[0]["config_sha256"] and ok["test"] == rows[0]["test"]
    assert summary2["status"] == {"ok": 1, "failed": 1} and summary2["cache"]["built"] == 0
    assert "FAILED" in (tmp_path / "sweep2" / "sweep.md").read_text()
    # an unknown override key refuses the whole grid before anything runs
    with pytest.raises(sweep.SweepError, match="unknown override"):
        sweep.run_sweep(data=[str(store_dir)], grid=[{}, {"hiden": 64}], out=tmp_path / "sweep3",
                        device="cpu", base=base, log=None)
    assert not (tmp_path / "sweep3").exists()
    # a Luna set sharing a deal with the data refuses the whole sweep up front
    with pytest.raises(train_v0.TrainError, match="shares"):
        sweep.run_sweep(data=[str(store_dir)], grid=[{}], out=tmp_path / "sweep4",
                        eval_luna=str(luna_overlap), device="cpu", base=base,
                        cache_dir=str(tmp_path / "sweep" / "cache"), cache_workers=1, log=None)
    assert not (tmp_path / "sweep4" / "runs").exists()
    # the CLI: --set base overrides, a grid file, exit 0 when every config ran
    grid_path = tmp_path / "grid.json"
    grid_path.write_text(json.dumps([{"prior_weight": 0.5}]))
    rc = sweep.main(["--data", str(store_dir), "--grid", str(grid_path),
                     "--out", str(tmp_path / "cli"), "--device", "cpu",
                     "--cache-dir", str(tmp_path / "sweep" / "cache"), "--cache-workers", "1",
                     "--set", "epochs=1", "--set", "batch_size=64", "--set", "n_boot=20",
                     "--set", "val_fraction=0.34", "--set", "test_fraction=0.33"])
    assert rc == 0
    cli = json.loads((tmp_path / "cli" / "sweep.json").read_text())
    assert cli["base"] == {"epochs": 1, "batch_size": 64, "n_boot": 20, "val_fraction": 0.34,
                           "test_fraction": 0.33}
    assert cli["rows"][0]["config"]["prior_weight"] == 0.5 and cli["rows"][0]["epochs"] == 1


# 11 ------------------------------------------ bounded residency + memory witness

def _synthetic_features(rng, rows: int, layout: data.FeatureLayout) -> np.ndarray:
    """Random float32 vectors an encoder of ``layout`` could have produced
    (counts 0 / .5 / 1, multiples of 1/8, free scalars)."""
    x = np.zeros((rows, layout.dim), dtype=np.float32)
    x[:, layout.bits2] = rng.integers(0, 3, size=(rows, len(layout.bits2))) * np.float32(0.5)
    x[:, layout.u8] = rng.integers(0, 32, size=(rows, len(layout.u8))) * np.float32(0.125)
    x[:, layout.f32] = rng.random((rows, len(layout.f32)), dtype=np.float32)
    return x


def _synthetic_cache(cache_dir: Path, i: int, rows: int, *, kmax: int = 4):
    """A cache file of ``rows`` synthetic rows in the production layout
    (schema, encoder identity, packing, shard binding, witness settings,
    nbytes); every 50 consecutive rows are one deal."""
    rng = np.random.default_rng(i)
    widths = rng.integers(1, kmax + 1, size=rows)
    offsets = np.zeros(rows + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(widths)
    total = int(offsets[-1])
    deals = [_synthetic_deal(i, r // 50) for r in range(rows)]
    arrays = {
        **data.pack_features(_synthetic_features(rng, rows, data.OBS_LAYOUT),
                             _synthetic_features(rng, total, data.CAND_LAYOUT)),
        "cand_offsets": offsets,
        "cand_softmax": np.full(total, 0.5, dtype=np.float32),
        "has_softmax": np.ones(rows, dtype=bool),
        "played": np.zeros(rows, dtype=np.int32),
        "utility": rng.standard_normal(rows).astype(np.float32),
        "attacker_points": np.zeros(rows, dtype=np.float32),
        "points_so_far": np.zeros(rows, dtype=np.float32),
        "ply": rng.integers(0, 100, size=rows).astype(np.int32),
        "role_attacker": np.ones(rows, dtype=bool),
        "seat": np.zeros(rows, dtype=np.int8),
        "cluster": np.asarray([f"syn:{i}"] * rows, dtype=str),
        "record_sha256": np.asarray([b"0" * 64] * rows, dtype="S64"),
        "source_ref": np.asarray([f"syn:{i}:{r}" for r in range(rows)], dtype=str),
        "search_mean": np.zeros(rows, dtype=np.float32),
        "has_search_mean": np.zeros(rows, dtype=bool),
        "deal_key": np.asarray(deals, dtype=str),
    }
    sha = hashlib.sha256(f"synthetic-{i}-{rows}".encode("ascii")).hexdigest()
    meta = {
        "schema": data.CACHE_SCHEMA, "encoder": data.encoder_identity(),
        "packing": data.PACKING,
        "shard": {"label": f"synthetic-{i}", "sha256": sha, "records": rows, "cluster": i,
                  "store": "synthetic"},
        "counts": {"encoded": rows, "records": rows,
                   "preference": {k: 0 for k in data.PREFERENCE_KEYS},
                   "privacy_witness": {"records": rows, "permutations": 2 * rows, "every": 1}},
        "witness_seed": 0, "witness_every": 1, "witness_sampled": False,
        "deal_key_schema": data.DEAL_KEY_SCHEMA, "deals": len(set(deals)),
        "nbytes": int(sum(a.nbytes for a in arrays.values())),
        "features": {"packed_nbytes": int(sum(arrays[k].nbytes for k in data.Block.PACKED)),
                     "float32_nbytes": data.float32_nbytes(rows, total)},
    }
    path = data.cache_path(cache_dir, sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        np.savez(fh, meta=np.asarray(json.dumps(meta, sort_keys=True)), **arrays)
    shard = data.ShardRef(path=f"synthetic-{i}", label=f"synthetic-{i}", sha256=sha,
                          records=rows, cluster=i, store="synthetic")
    return shard, str(path)


def _synthetic_deal(block: int, deal: int) -> str:
    return f"deck:{block:04d}{deal:060d}"


MEMORY_PROBE = r"""
import json, resource, sys
import numpy as np
from shengji.train import data
entries = [(data.ShardRef(**s), p) for s, p in json.loads(sys.argv[1])]
budget = None if sys.argv[2] == "none" else int(sys.argv[2])
window = int(sys.argv[3])
mode = sys.argv[4]
keep = json.loads(sys.argv[5])
def peak():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(r) if sys.platform == "darwin" else int(r) * 1024
store = data.BlockStore(entries, resident_bytes=budget,
                        keep=None if keep is None else [None if k is None else set(k) for k in keep])
before = peak()
rng = np.random.default_rng(0)
rows = 0
digest = 0.0
if mode == "batches":
    for epoch in range(2):
        for batch in store.iter_batches(lambda b: np.ones(b.n, dtype=bool), 256, rng=rng,
                                        window=window):
            rows += int(batch["obs"].shape[0])
            digest += float(batch["obs"][:, 0].sum())
elif mode == "blocks":
    for i in range(len(store)):
        block = store.block(i)
        rows += block.n
        digest += float(block.obs_bits[:, 0].sum())      # the resident (packed) column
        del block
elif mode == "blocks_full_then_subset":
    # the pre-repair filtered load: reserve the subset, decode the WHOLE
    # block, then cut the kept rows out of it (the RED reference)
    for i in range(len(store)):
        shard, path = store.entries[i]
        store.residency.make_room(store.sizes[i], label=shard.label)
        full = data.load_block(path, shard_sha256=shard.sha256, witness_every=1)
        block = full.subset(store.keep_idx[i])
        del full
        store.residency.admit((store.id, i), block, label=shard.label)
        rows += block.n
        digest += float(block.obs_bits[:, 0].sum())
        del block
after = peak()
print(json.dumps({"before": before, "after": after, "rows": rows, "digest": digest,
                  **store.residency.describe()}))
"""


def _memory_probe(entries, budget, window, *, mode="batches", keep=None):
    payload = json.dumps([(dataclasses.asdict(s), p) for s, p in entries])
    env = {**os.environ, "PYTHONPATH": str(SERVER), "PYTHONDONTWRITEBYTECODE": "1"}
    keep_arg = json.dumps(None if keep is None else [None if k is None else sorted(k) for k in keep])
    proc = subprocess.run([sys.executable, "-P", "-B", "-c", MEMORY_PROBE, payload,
                           "none" if budget is None else str(budget), str(window), mode,
                           keep_arg],
                          capture_output=True, text=True, env=env, check=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_residency_is_bounded_and_batches_do_not_depend_on_the_budget(tmp_path):
    n_blocks, rows = 16, 15000                     # about 10 MB packed per block
    entries = [_synthetic_cache(tmp_path / "cache", i, rows) for i in range(n_blocks)]
    sizes = [data.read_meta(p)["nbytes"] for _s, p in entries]
    total = sum(sizes)
    biggest = max(sizes)
    assert 8 * 2 ** 20 < biggest < 12 * 2 ** 20 and total > 128 * 2 ** 20
    budget = 2 * biggest + 2 ** 20            # room for a two-block window
    # the LRU: at most ``budget`` bytes resident, blocks reloaded past it
    store = data.BlockStore(entries, resident_bytes=budget)
    assert store.nbytes == total and store.sizes == sizes and store.rows() == [rows] * n_blocks
    for i in range(n_blocks):
        block = store.block(i)
        assert block.n == rows and store.residency.bytes <= budget
        assert store.residency.peak_bytes <= budget
    assert store.residency.loads == n_blocks and store.residency.evictions == n_blocks - 2
    assert store.block(n_blocks - 1) is store.residency.get((store.id, n_blocks - 1))
    assert store.residency.loads == n_blocks                    # resident: no reload
    store.block(0)
    assert store.residency.loads == n_blocks + 1                # evicted: reloaded
    assert len(store.residency) == 2
    # a window is bounded by both --window and the budget; a block above it refuses
    order = list(range(n_blocks))
    assert [len(g) for g in store.windows(order, 64)] == [2] * (n_blocks // 2)
    assert [len(g) for g in store.windows(order, 1)] == [1] * n_blocks
    assert data.BlockStore(entries).windows(order, 5) == [order[i:i + 5]
                                                         for i in range(0, n_blocks, 5)]
    with pytest.raises(data.TrainDataError, match="above the residency budget"):
        list(data.BlockStore(entries, resident_bytes=biggest - 1).iter_batches(
            lambda b: np.ones(b.n, dtype=bool), 64))
    with pytest.raises(data.TrainDataError, match="above the residency budget"):
        data.BlockStore(entries, resident_bytes=biggest - 1).block(sizes.index(biggest))
    with pytest.raises(data.TrainDataError):
        data.Residency(0)
    # the batch sequence is a function of the seed alone, whatever the budget
    all_rows = lambda b: np.ones(b.n, dtype=bool)  # noqa: E731

    def sequence(budget, window=3):
        st = data.BlockStore(entries, resident_bytes=budget)
        out = []
        for batch in st.iter_batches(all_rows, 500, rng=np.random.default_rng(11), window=window):
            out.append((batch["obs"].tobytes(), batch["cand"].tobytes(), batch["mask"].tobytes(),
                        batch["utility"].tobytes(), batch["block"].tobytes(),
                        batch["row"].tobytes(), batch["idx"].tobytes()))
        return out, st.residency.describe()

    unbounded, r0 = sequence(None)
    tight, r1 = sequence(3 * biggest + 2 ** 20)
    assert unbounded == tight and len(unbounded) > 0
    assert sum(len(b[3]) // 4 for b in unbounded) == n_blocks * rows
    assert r0["evictions"] == 0 and r0["loads"] == n_blocks
    assert r1["evictions"] > 0 and r1["loads"] == n_blocks     # one epoch: each block once
    assert r1["peak_resident_bytes"] <= 3 * biggest + 2 ** 20
    shuffled, _ = sequence(None, window=5)
    assert shuffled != unbounded                                 # the window changes the order
    # MEMORY WITNESS (a fresh process: python + numpy + data.py, no torch):
    # peak RSS with the budget stays under budget + a fixed overhead over
    # the pre-iteration peak (measured: about 17-20 MB of zip / batch
    # buffers whatever the budget); RED with eviction disabled (unbounded:
    # the whole corpus becomes resident and the peak grows by its size)
    overhead = 32 * 2 ** 20
    bounded = _memory_probe(entries, budget, 2)
    resident_all = _memory_probe(entries, None, 2)
    assert bounded["rows"] == resident_all["rows"] == 2 * n_blocks * rows
    assert bounded["digest"] == resident_all["digest"]
    assert bounded["evictions"] > 0 and resident_all["evictions"] == 0
    assert bounded["peak_resident_bytes"] <= budget
    grew_bounded = bounded["after"] - bounded["before"]
    grew_all = resident_all["after"] - resident_all["before"]
    assert grew_bounded <= budget + overhead, (grew_bounded, budget, bounded)
    assert grew_all >= 0.8 * total, (grew_all, total, resident_all)
    assert grew_all > budget + overhead                          # RED without eviction


def test_filtered_loading_decodes_only_the_kept_rows_within_the_budget(tmp_path):
    n_blocks, rows = 6, 30000                      # about 19 MB decoded (packed) per block
    entries = [_synthetic_cache(tmp_path / "cache", i, rows) for i in range(n_blocks)]
    full_sizes = [data.read_meta(p)["nbytes"] for _s, p in entries]
    assert all(16 * 2 ** 20 < s < 24 * 2 ** 20 for s in full_sizes)
    # keep 12 of the 600 deals of every odd block, everything of the even ones
    keep = [None if i % 2 == 0 else {_synthetic_deal(i, d) for d in range(3, 15)}
            for i in range(n_blocks)]
    unbounded = data.BlockStore(entries, keep=keep)
    assert unbounded.rows() == [rows if i % 2 == 0 else 600 for i in range(n_blocks)]
    assert len(unbounded.keys()) == 3 * 600 + 3 * 12
    # a filtered entry decodes ONLY its kept rows: the block equals the full
    # block's subset, byte for byte, and its exact size was known up front
    for i in range(n_blocks):
        block = unbounded.block(i)
        assert block.nbytes == unbounded.sizes[i]
        full = data.load_block(entries[i][1], shard_sha256=entries[i][0].sha256)
        if keep[i] is None:
            assert unbounded.keep_idx[i] is None and block.nbytes == full_sizes[i]
            reference = full
        else:
            idx = np.flatnonzero(np.isin(full.deal_key, sorted(keep[i])))
            assert np.array_equal(unbounded.keep_idx[i], idx)
            reference = full.subset(idx)
            assert block.n == 600 and block.nbytes < full_sizes[i] // 8
        for name in data.Block.ARRAYS:
            assert np.array_equal(getattr(block, name), getattr(reference, name)), (i, name)
    # a window / the budget see the filtered sizes, so a store whose FULL
    # blocks are far above the budget trains when its kept rows fit
    subset = max(unbounded.sizes[i] for i in range(1, n_blocks, 2))
    budget = 2 * subset + 2 ** 16
    assert budget < min(full_sizes) // 3
    filtered_only = [(entries[i], keep[i]) for i in range(1, n_blocks, 2)]
    store = data.BlockStore([e for e, _k in filtered_only], resident_bytes=budget,
                            keep=[k for _e, k in filtered_only])
    assert [len(g) for g in store.windows(list(range(len(store))), 64)] == [2, 1]
    seen = 0
    for batch in store.iter_batches(lambda b: np.ones(b.n, dtype=bool), 128,
                                    rng=np.random.default_rng(0), window=2):
        seen += int(batch["obs"].shape[0])
    assert seen == 3 * 600 and store.residency.peak_bytes <= budget
    with pytest.raises(data.TrainDataError, match="above the residency budget"):
        data.BlockStore(entries, resident_bytes=budget, keep=keep).block(0)   # unfiltered: full
    # MEMORY WITNESS for the keep path (loads only, a fresh process): the
    # peak RSS stays within budget + a small overhead -- nothing of the
    # unkept rows is ever materialised; RED under the pre-repair load
    # (decode the whole block, then subset), which overshoots by a full block
    overhead = 8 * 2 ** 20
    probe_entries = [e for e, _k in filtered_only]
    probe_keep = [k for _e, k in filtered_only]
    streaming = _memory_probe(probe_entries, budget, 1, mode="blocks", keep=probe_keep)
    full_then_subset = _memory_probe(probe_entries, budget, 1, mode="blocks_full_then_subset",
                                     keep=probe_keep)
    assert streaming["rows"] == full_then_subset["rows"] == 3 * 600
    assert streaming["digest"] == full_then_subset["digest"]
    assert streaming["peak_resident_bytes"] <= budget and streaming["evictions"] == 1
    grew_streaming = streaming["after"] - streaming["before"]
    grew_full = full_then_subset["after"] - full_then_subset["before"]
    assert grew_streaming <= budget + overhead, (grew_streaming, budget, streaming)
    assert grew_full > budget + overhead, (grew_full, budget, full_then_subset)   # RED
    assert grew_full >= min(full_sizes)                          # a whole block went resident


# 12 --------------------------------- packed features: lossless, accounted, keyed

def _reference_batch(block: data.Block, records_by_sha: dict, idx: np.ndarray) -> dict:
    """The batch of rows ``idx`` built from the ENCODER's float32 vectors
    (never from the cache): the independent reference for ``collate``."""
    idx = np.asarray(idx, dtype=np.int64)
    widths = block.widths[idx]
    kmax = max(int(widths.max()), 1)
    obs = np.zeros((len(idx), encode.OBS_DIM), np.float32)
    cand = np.zeros((len(idx), kmax, encode.ACT_DIM), np.float32)
    for j, i in enumerate(idx.tolist()):
        r = records_by_sha[block.record_sha256[i].decode()]
        rnd = rebuild.state_for_record(r)
        obs[j] = np.asarray(encode.encode_obs(rnd, r["seat"]), np.float32)
        for k, c in enumerate(r["ballot"]):
            cand[j, k] = np.asarray(encode.encode_action(c, rnd), np.float32)
    return {"obs": obs, "cand": cand}


def _step_losses(batch: dict, seed: int = 0) -> dict:
    """The losses of one training step on ``batch`` with a freshly seeded
    model (the same seed: the same weights)."""
    torch.manual_seed(seed)
    net = model_mod.ValuePriorNet()
    t = train_v0.to_tensors(batch, torch.device("cpu"), "softmax")
    losses = model_mod.batch_losses(net, t, prior_weight=1.0)
    return {k: float(v.item()) for k, v in losses.items()}


def test_packed_features_are_lossless_and_train_identically(store_dir, records, tmp_path):
    by_sha = {r["record_sha256"]: r for r in records}
    _store, entries = _entries(store_dir, tmp_path / "cache")
    bs = data.BlockStore(entries)
    checked = 0
    for block in bs.iter_blocks():
        # the resident members ARE the packed ones (uint8 / a few float32 columns)
        assert block.obs_bits.dtype == np.uint8 and block.cand_bits.dtype == np.uint8
        assert block.obs_bits.shape == (block.n, data.OBS_LAYOUT.bits_width)
        assert block.obs_f32.shape == (block.n, 2) and block.cand_f32.shape[1] == 1
        assert block.cand_u8.shape == (int(block.cand_offsets[-1]), 4)
        obs, cand = block.obs, block.cand_feats
        for i in range(block.n):
            r = by_sha[block.record_sha256[i].decode()]
            rnd = rebuild.state_for_record(r)
            # unpack(pack(x)) == x, BYTE for byte, on every row and every candidate
            ref = np.asarray(encode.encode_obs(rnd, r["seat"]), np.float32)
            assert obs[i].tobytes() == ref.tobytes()
            lo, hi = block.cand_offsets[i], block.cand_offsets[i + 1]
            ref_c = np.asarray([encode.encode_action(c, rnd) for c in r["ballot"]], np.float32)
            assert cand[lo:hi].tobytes() == ref_c.tobytes()
            checked += 1
        # packing the encoder's vectors again gives exactly the cached members
        packed = data.pack_features(obs, cand)
        for name in data.Block.PACKED:
            assert np.array_equal(packed[name], getattr(block, name)), name
        assert data.OBS_LAYOUT.packed_bytes_per_row == 141
        assert data.CAND_LAYOUT.packed_bytes_per_row == 22
    assert checked == len(records)
    # a training step on the packed path (collate unpacks per batch) yields
    # exactly the losses of a step on the encoder's own float32 vectors
    block = max(bs.iter_blocks(), key=lambda b: int((b.points_so_far > 0).sum()))
    idx = np.flatnonzero(block.points_so_far > 0)[:96]      # rows whose scalar is not 0
    assert idx.size >= 16
    batch = data.collate(block, idx)
    reference = _reference_batch(block, by_sha, idx)
    assert batch["obs"].tobytes() == reference["obs"].tobytes()
    assert batch["cand"].tobytes() == reference["cand"].tobytes()
    packed_losses = _step_losses(batch)
    assert packed_losses == _step_losses({**batch, **reference})
    assert packed_losses["total"] > 0
    # RED: a scalar feature (attacker points / 200, column 508) quantised to
    # a uint8 at the packer's scale (round to 1/8) changes the observation
    # bytes AND the losses of the same step -- the comparison above detects
    # it -- and the packer refuses a layout that would store that column in
    # a byte
    col = 508
    assert data.OBS_SEGMENTS[4][0] == "attacker_points" and col in data.OBS_LAYOUT.f32
    lossy = reference["obs"].copy()
    lossy[:, col] = (np.round(lossy[:, col] * data.U8_SCALE) / data.U8_SCALE).astype(np.float32)
    assert (lossy[:, col] != reference["obs"][:, col]).sum() >= 16
    assert _step_losses({**batch, "obs": lossy}) != packed_losses
    quantised = [[name, width, "u8" if name == "attacker_points" else kind]
                 for name, width, kind in data.OBS_SEGMENTS]
    with pytest.raises(data.TrainDataError, match="cannot store exactly"):
        data.FeatureLayout("obs", quantised, encode.OBS_DIM).pack(reference["obs"])
    # every segment kind is exercised, and a wrong segment table refuses at import
    assert {kind for _n, _w, kind in data.OBS_SEGMENTS + data.CAND_SEGMENTS} == {"bits2", "u8", "f32"}
    with pytest.raises(ValueError, match="cover"):
        data.FeatureLayout("obs", data.OBS_SEGMENTS[:-1], encode.OBS_DIM)


def test_residency_accounts_for_the_packed_size(store_dir, tmp_path):
    _store, entries = _entries(store_dir, tmp_path / "cache")
    bs = data.BlockStore(entries)
    unpacked_total = 0
    for i, (shard, path) in enumerate(entries):
        meta = data.read_meta(path)
        block = bs.block(i)
        packed = int(sum(getattr(block, k).nbytes for k in data.Block.PACKED))
        f32 = data.float32_nbytes(block.n, int(block.cand_offsets[-1]))
        assert f32 == block.n * encode.OBS_DIM * 4 + int(block.cand_offsets[-1]) * encode.ACT_DIM * 4
        # the reported size is the PACKED size: the sum of the resident arrays
        assert (block.nbytes == meta["nbytes"] == bs.sizes[i]
                == sum(getattr(block, k).nbytes for k in data.Block.ARRAYS))
        assert meta["features"] == {"packed_nbytes": packed, "float32_nbytes": f32}
        assert f32 > 10 * packed                              # 13x measured on the corpus
        # RED under float32 accounting: the same rows unpacked would report far more
        unpacked = block.nbytes - packed + f32
        assert block.nbytes < unpacked / 3
        unpacked_total += unpacked
    assert bs.residency.bytes == bs.nbytes == sum(bs.sizes)
    receipt = train_v0.residency_receipt(bs.residency, decoded_bytes=bs.nbytes)
    assert receipt["decoded_bytes_data"] == receipt["resident_bytes"] == bs.nbytes
    assert "PACKED" in receipt["contract"]
    # a budget of exactly the packed corpus holds every block resident,
    # although the same rows unpacked would not fit it (they would stream)
    assert unpacked_total > bs.nbytes
    fits = data.BlockStore(entries, resident_bytes=bs.nbytes)
    rows = sum(int(b["obs"].shape[0]) for b in fits.iter_batches(
        lambda b: np.ones(b.n, dtype=bool), 64, rng=np.random.default_rng(0)))
    assert rows == sum(bs.rows()) and fits.residency.evictions == 0
    assert fits.residency.peak_bytes == bs.nbytes
    with pytest.raises(data.TrainDataError, match="above the residency budget"):
        data.BlockStore(entries, resident_bytes=min(bs.sizes) - 1).block(bs.sizes.index(min(bs.sizes)))


def _write_cache(path: Path, arrays: dict, meta: dict) -> None:
    with open(path, "wb") as fh:
        np.savez(fh, meta=np.asarray(json.dumps(meta, sort_keys=True)), **arrays)


def test_old_format_caches_are_rebuilt_not_misread(store_dir, tmp_path, monkeypatch):
    store = data.discover_store(store_dir)
    shard = store.shards[0]
    cache = tmp_path / "cache"
    path, _counts = data.build_cache(shard, cache, witness_seed=1)
    fresh = path.read_bytes()
    block = data.load_block(path)
    assert block.meta["schema"] == data.CACHE_SCHEMA and block.meta["packing"] == data.PACKING
    # the pre-packing (v3) layout of the SAME rows: float32 obs / cand_feats
    # members, schema v3, no packing key
    old_arrays = {"obs": block.obs, "cand_offsets": block.cand_offsets,
                  "cand_feats": block.cand_feats, "cand_softmax": block.cand_softmax}
    for name in data.Block.SCALARS:
        old_arrays[name] = getattr(block, name)
    old_meta = {k: v for k, v in block.meta.items() if k not in ("packing", "features")}
    old_meta["schema"] = "shengji-train-cache-v3"
    old_meta["nbytes"] = int(sum(a.nbytes for a in old_arrays.values()))
    assert old_meta["nbytes"] > 3 * block.nbytes
    _write_cache(path, old_arrays, old_meta)
    assert data.read_meta(path)["schema"] == "shengji-train-cache-v3"
    with pytest.raises(data.TrainDataError, match="cache schema"):
        data.load_block(path)
    (meta, rebuilt), = data.ensure_caches([(shard, False)], cache, witness_seed=1, workers=1)
    assert rebuilt and meta["schema"] == data.CACHE_SCHEMA and meta["packing"] == data.PACKING
    assert path.read_bytes() == fresh                     # rebuilt: the packed file again
    assert data.load_block(path).obs_bits.dtype == np.uint8
    # a current-schema file packed with ANOTHER layout is rebuilt as well
    other = dict(block.meta)
    other["packing"] = {**data.PACKING, "version": 0}
    packed_arrays = {name: getattr(block, name) for name in data.Block.ARRAYS}
    _write_cache(path, packed_arrays, other)
    with pytest.raises(data.TrainDataError, match="another feature layout"):
        data.load_block(path)
    (meta, rebuilt), = data.ensure_caches([(shard, False)], cache, witness_seed=1, workers=1)
    assert rebuilt and path.read_bytes() == fresh
    _blk, rebuilt2 = data.ensure_cache(shard, cache, witness_seed=1)
    assert not rebuilt2                                    # valid: reused
    # RED with the format key dropped (the v3 schema accepted as current and
    # no packing check): the stale float32 file passes as valid, ensure_caches
    # REUSES it and the loader misreads it (no packed member to decode)
    _write_cache(path, old_arrays, old_meta)
    monkeypatch.setattr(data, "CACHE_SCHEMA", "shengji-train-cache-v3")
    monkeypatch.setattr(data, "PACKING", None)
    (meta, rebuilt), = data.ensure_caches([(shard, False)], cache, witness_seed=1, workers=1)
    assert not rebuilt and meta["schema"] == "shengji-train-cache-v3"
    with pytest.raises(KeyError):
        data.load_block(path)
