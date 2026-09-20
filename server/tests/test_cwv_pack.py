"""The decoded pack (#531) is the cache, byte for byte, and trains identically.

Built from real caches of a tiny trajectory store: every block's arrays equal the cache
block's; the batch sequence under a byte-bounded residency equals the cache store's for the
same rng; two epochs of real training from the pack produce bitwise-identical checkpoint
tensors; and the pack refuses a cache it was not built from.
"""
from pathlib import Path

import numpy as np
import pytest
import torch

from shengji.train import cwv_data, cwv_pack
from shengji.train.data import Residency, SplitSelector, split_deals
from tests.test_cwv_train import (store_dir, other_dir, records, other_records, luna, blocks,  # noqa: F401
                                  THIRDS)
from tests.test_cwv_train_policy_head import policy_rows  # noqa: F401

_BUDGET = 2 * 10 ** 6   # small enough that windows are byte-bounded on the tiny store


@pytest.fixture(scope="module")
def prepared(store_dir, tmp_path_factory):
    cache = tmp_path_factory.mktemp("pack-cache")
    prep = cwv_data.prepare_stores([str(store_dir)], Path(cache), limit_clusters=None, history=False,
                                   witness_seed=1, cache_workers=1, residency=Residency(_BUDGET))
    return prep, cache


@pytest.fixture(scope="module")
def pack(prepared, tmp_path_factory):
    prep, _cache = prepared
    out = tmp_path_factory.mktemp("pack") / "v"
    manifest = cwv_pack.build_pack(prep.block_store.entries, out, classify_shards=3)
    return out, manifest


def _pack_store(prep, out, **kw):
    return cwv_pack.CwvPackStore(prep.block_store.entries, out, residency=Residency(_BUDGET), **kw)


def test_every_block_is_the_cache_block_byte_for_byte(prepared, pack):
    prep, _ = prepared; out, manifest = pack
    assert manifest["schema"] == cwv_pack.PACK_SCHEMA and manifest["rows"] == sum(prep.block_store.rows())
    assert len(manifest["half_cols"]) + len(manifest["f32_cols"]) == manifest["public_dim"]
    ps = _pack_store(prep, out)
    assert ps.rows() == prep.block_store.rows() and ps.keys() == prep.block_store.keys()
    for i in range(len(prep.block_store)):
        a, b = prep.block_store.block(i), ps.block(i)
        assert a.n == b.n and a.optional == b.optional
        for name in cwv_data.CwvBlock.ARRAYS:
            x, y = getattr(a, name), getattr(b, name)
            assert x.dtype == y.dtype, (name, x.dtype, y.dtype)
            assert np.array_equal(x, y), name
        assert ps.keys_of(i) == prep.block_store.keys_of(i)


def test_batch_sequence_is_identical_under_a_byte_bounded_residency(prepared, pack):
    prep, _ = prepared; out, _ = pack
    # a budget that splits the tiny store into several byte-bounded windows on BOTH stores
    budget = sum(prep.block_store.sizes) // 2 + 1
    cs = cwv_data.CwvBlockStore(prep.block_store.entries, residency=Residency(budget))
    ps = cwv_pack.CwvPackStore(prep.block_store.entries, out, residency=Residency(budget))
    assignment = split_deals(cs.keys(), seed=1, val_fraction=0.25, test_fraction=0.25)
    sel = SplitSelector(assignment, "train")
    assert len(cs.windows(np.arange(len(cs)), 64)) > 1, "test needs >1 window"
    assert cs.windows(np.arange(len(cs)), 64) == ps.windows(np.arange(len(ps)), 64)
    a = list(cs.iter_batches(sel, 8, rng=np.random.default_rng(5), window=64))
    b = list(ps.iter_batches(sel, 8, rng=np.random.default_rng(5), window=64))
    assert len(a) == len(b) > 0
    for x, y in zip(a, b):
        assert x.keys() == y.keys()
        for k in x:
            assert np.array_equal(x[k], y[k]), k


@pytest.mark.parametrize("joint", [False, True])
def test_two_epochs_from_the_pack_give_bitwise_identical_weights(
        store_dir, luna, pack, policy_rows, tmp_path, joint):
    from shengji.train import train_cwv, train_v0
    out, _ = pack
    luna_path, _rows = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1, seed=7,
                   batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu", epochs=2,
              seed=7, batch_size=64, n_boot=10, hidden=32, log=None, cache_workers=1, eval_workers=1,
              bench_batch=32, public_head=str(tmp_path / "public" / "best.pt"),
              resident_bytes=_BUDGET, **THIRDS)
    if joint:
        kw.update(policy_head=True, policy_rows=policy_rows, policy_eval=policy_rows,
                  policy_weight=0.2, policy_batch_fraction=0.25, aux_points=True)
    cache = tmp_path / "cache"
    a = train_cwv.train(out=tmp_path / "cache-run", cache_dir=cache, **kw)
    manifest = cwv_pack.build_pack([(s, p) for s, p in _entries(store_dir, cache)], tmp_path / "pack2",
                                   classify_shards=3)
    b = train_cwv.train(out=tmp_path / "pack-run", cache_dir=cache, pack_dir=tmp_path / "pack2", **kw)
    assert a["best_epoch"] == b["best_epoch"] and b["pack_dir"] is not None and a["pack_dir"] is None
    ma, _meta_a, aux_a = train_cwv.load_cwv_checkpoint(tmp_path / "cache-run" / "best.pt")
    mb, _meta_b, aux_b = train_cwv.load_cwv_checkpoint(tmp_path / "pack-run" / "best.pt")
    wa, wb = ma.state_dict(), mb.state_dict()
    assert wa.keys() == wb.keys()
    for k in wa:
        assert torch.equal(wa[k], wb[k]), k
    assert (aux_a is None) == (aux_b is None)
    if aux_a is not None:
        for k, t in aux_a.state_dict().items():
            assert torch.equal(t, aux_b.state_dict()[k]), k
    ea = [(e["train"]["loss"], e["val"]["loss"]) for e in a["epochs"]]
    eb = [(e["train"]["loss"], e["val"]["loss"]) for e in b["epochs"]]
    assert ea == eb
    if joint:
        assert ma.policy_head is not None and mb.policy_head is not None
        for epoch_a, epoch_b in zip(a["epochs"], b["epochs"]):
            assert epoch_a["train"]["policy_rows"] > 0
            assert epoch_a["train"]["policy_bce"] > 0
            for metric in ("policy_rows", "policy_bce", "policy_listwise"):
                assert epoch_a["train"][metric] == epoch_b["train"][metric]


def _entries(store_dir, cache):
    from shengji.train import train_cwv
    store = cwv_data.discover_store(str(store_dir), limit_clusters=None)
    version = train_cwv.DEFAULTS["encoder_version"]
    return [(s, str(cwv_data.cache_path(cache, s.sha256, history=False, version=version)))
            for s in store.shards]


def test_pack_refuses_a_foreign_cache_and_a_double_build(prepared, pack, tmp_path):
    prep, _ = prepared; out, manifest = pack
    with pytest.raises(cwv_pack.PackError, match="already here"):
        cwv_pack.build_pack(prep.block_store.entries, out)
    # a shard the pack never saw
    shard, path = prep.block_store.entries[0]
    foreign = cwv_data.ShardRef(path=shard.path, label="foreign", sha256="0" * 64, records=shard.records,
                                cluster=shard.cluster, store=shard.store)
    with pytest.raises(cwv_pack.PackError, match="not in the pack"):
        cwv_pack.CwvPackStore([(foreign, path)], out)
    # the sidecar contract is part of the pack
    with pytest.raises(cwv_pack.PackError, match="sidecar"):
        cwv_pack.CwvPackStore(prep.block_store.entries, out, sidecar_dir=str(tmp_path))


def test_half_multiple_columns_round_trip_exactly():
    rng = np.random.default_rng(0)
    pub = np.concatenate([rng.integers(0, 3, (50, 5)).astype(np.float32) * 0.5,
                          rng.random((50, 2)).astype(np.float32)], axis=1)
    ok = cwv_pack.classify_public(pub)
    assert ok.tolist() == [True] * 5 + [False] * 2
    doubled = (pub[:, :5] * 2).astype(np.uint8)
    assert np.array_equal(doubled.astype(np.float32) * np.float32(0.5), pub[:, :5])


def test_pack_dir_reaches_train_only_and_evaluate_still_parses(monkeypatch):
    """Codex, #532: pack_dir had landed in the exec kwargs shared with evaluate(), which
    does not take it, so the default evaluate CLI raised TypeError."""
    from shengji.train import train_cwv
    seen = {}
    monkeypatch.setattr(train_cwv, "evaluate", lambda **kw: seen.setdefault("evaluate", kw))
    monkeypatch.setattr(train_cwv, "train", lambda **kw: seen.setdefault("train", kw))
    train_cwv.main(["evaluate", "--checkpoint", "c.pt", "--out", "o", "--data", "d"])
    assert "evaluate" in seen and "pack_dir" not in seen["evaluate"]
    train_cwv.main(["train", "--data", "d", "--out", "o", "--pack-dir", "p"])
    assert seen["train"]["pack_dir"] == "p"


def test_packed_search_labels_are_bound_to_the_sidecar_file_by_digest(prepared, tmp_path):
    prep, _ = prepared
    empty = tmp_path / "sidecar-empty"; empty.mkdir()
    out = tmp_path / "pack-sc"
    manifest = cwv_pack.build_pack(prep.block_store.entries, out, sidecar_dir=str(empty), classify_shards=3)
    assert manifest["sidecar"] and all(s["sidecar_sha256"] is None for s in manifest["shards"])
    # same (empty) sidecar: accepted; a sidecar that now HAS a file for a shard: refused
    cwv_pack.CwvPackStore(prep.block_store.entries, out, sidecar_dir=str(empty))
    changed = tmp_path / "sidecar-changed"; changed.mkdir()
    shard = prep.block_store.entries[0][0]
    np.savez(cwv_pack.sidecar_path(changed, shard.sha256), x=np.zeros(1))
    with pytest.raises(cwv_pack.PackError, match="sidecar file for"):
        cwv_pack.CwvPackStore(prep.block_store.entries, out, sidecar_dir=str(changed))


def test_zero_column_groups_are_not_memory_mapped(prepared, tmp_path):
    prep, _ = prepared
    width = prep.block_store.block(0).public.shape[1]
    out = tmp_path / "pack-allf32"
    manifest = cwv_pack.build_pack(prep.block_store.entries, out, classify_shards=3,
                                   force_float32=range(width))
    assert manifest["half_cols"] == [] and len(manifest["f32_cols"]) == width
    ps = cwv_pack.CwvPackStore(prep.block_store.entries, out)
    for i in range(len(prep.block_store)):
        assert np.array_equal(ps.block(i).public, prep.block_store.block(i).public)
