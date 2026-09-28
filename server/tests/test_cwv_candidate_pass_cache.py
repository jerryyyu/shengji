"""Issue #542 lever 4b: the test candidate pass memoises the workers' output per shard.

Measured 2026-09-28 on arms C, D and F (496k corpus, 49,600 test shards): every run
re-decoded and re-encoded the SAME test set, 2,887-2,957 s each (~49 min), while the
scorers on top of it take a fraction of that.  The workers' output depends only on the
encoder, the flavour, the per-shard cap, the shard's bytes and the selected deals, so it
is cached under that identity; the scorers (which change per run) run on top of it.

The acceptance is the real entry point twice: ``candidate_pass`` on real shards, the second
time with the worker forbidden, must return the same rows, values and agreement.
"""
import json

import numpy as np
import pytest

from shengji.train import cwv_eval
from shengji.train.data import discover_store

# the fixture family is module-local to test_cwv_train; importing registers it here
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401


def _shard_keys(store_dir):
    store = discover_store(store_dir)
    return [(shard, None) for shard in store.shards]


def _score(entry):
    # a scorer with a per-candidate signature, so the agreement rows depend on the tensors
    return entry["public"].astype(np.float64).sum(axis=1) + entry["perspective"].astype(np.float64)


def _run(shard_keys, cache_dir, *, history=False, rank_limit=None, workers=1):
    lines = []
    out = cwv_eval.candidate_pass(shard_keys, score_fn=_score, score_many_fn=None,
                                  public_head=None, prior=None, device="cpu",
                                  workers=workers, rank_limit=rank_limit, history=history,
                                  progress=lines.append, cache_dir=cache_dir)
    return out, lines


def _same(a, b):
    assert a["rows"] == b["rows"] > 0
    assert a["search_records"] == b["search_records"] > 0
    assert a["candidates"] == b["candidates"] > 0
    assert a["decision_keys"] == b["decision_keys"]
    assert a["decision_values"] == b["decision_values"]
    assert a["clusters"] == b["clusters"]
    assert a["agreement"].keys() == b["agreement"].keys()
    for name in a["agreement"]:
        assert a["agreement"][name] == b["agreement"][name], name


def _forbid_worker(monkeypatch):
    def refuse(task):
        raise AssertionError("the worker ran on a shard whose result is cached")
    monkeypatch.setattr(cwv_eval, "_candidate_task", refuse)


@pytest.mark.parametrize("history", [False, True])
def test_second_pass_is_served_from_disk_and_equals_the_first(store_dir, tmp_path, monkeypatch,
                                                              history):
    shard_keys = _shard_keys(store_dir)
    first, lines_first = _run(shard_keys, tmp_path / "cache", history=history)
    assert first["cached_shards"] == 0
    assert lines_first[-1].endswith(f"cached=0 ({first['secs']}s)") or "cached=0" in lines_first[-1]
    files = sorted((tmp_path / "cache" / "candidate-pass").glob("*.npz"))
    assert len(files) == len(shard_keys)
    for path in files:
        with np.load(path, allow_pickle=False) as npz:
            meta = json.loads(str(npz["meta"]))
        assert meta["schema"] == cwv_eval.CANDIDATE_PASS_SCHEMA
        assert meta["history"] is history
        assert path.name == f"{meta['digest'][:24]}.npz"

    _forbid_worker(monkeypatch)
    second, lines_second = _run(shard_keys, tmp_path / "cache", history=history)
    assert second["cached_shards"] == len(shard_keys)
    assert "cached=%d" % len(shard_keys) in lines_second[-1]
    _same(first, second)


def test_the_cache_keys_on_everything_the_worker_reads(store_dir, tmp_path, monkeypatch):
    """Selected deals, the per-shard cap, want_search, history and the encoder
    version each change the digest; the same task twice does not."""
    shard = discover_store(store_dir).shards[0]
    base = (shard, None, True, 1 << 30, False, cwv_eval.ENC_VERSION)
    digest = cwv_eval.candidate_task_digest(base)
    assert digest == cwv_eval.candidate_task_digest(
        (shard, None, True, 1 << 30, False, cwv_eval.ENC_VERSION))
    variants = [
        (shard, ["deal-a"], True, 1 << 30, False, cwv_eval.ENC_VERSION),
        (shard, None, False, 1 << 30, False, cwv_eval.ENC_VERSION),
        (shard, None, True, 1, False, cwv_eval.ENC_VERSION),
        (shard, None, True, 1 << 30, True, cwv_eval.ENC_VERSION),
    ]
    other_version = 1 if cwv_eval.ENC_VERSION != 1 else 2
    variants.append((shard, None, True, 1 << 30, False, other_version))
    digests = {cwv_eval.candidate_task_digest(v) for v in variants}
    assert digest not in digests and len(digests) == len(variants)
    # selection order does not matter, membership does
    assert (cwv_eval.candidate_task_digest((shard, ["b", "a"], True, 1 << 30, False, cwv_eval.ENC_VERSION))
            == cwv_eval.candidate_task_digest((shard, ["a", "b"], True, 1 << 30, False, cwv_eval.ENC_VERSION)))

    # and the pass respects it: a different per-shard cap is a miss, rebuilt by the worker
    shard_keys = _shard_keys(store_dir)
    full, _ = _run(shard_keys, tmp_path / "cache")
    capped, _ = _run(shard_keys, tmp_path / "cache", rank_limit=len(shard_keys))
    assert capped["cached_shards"] == 0
    assert capped["search_records"] < full["search_records"]
    _forbid_worker(monkeypatch)
    again, _ = _run(shard_keys, tmp_path / "cache", rank_limit=len(shard_keys))
    assert again["cached_shards"] == len(shard_keys)
    _same(capped, again)


def test_a_file_carrying_another_digest_is_ignored_and_rebuilt(store_dir, tmp_path):
    shard_keys = _shard_keys(store_dir)
    first, _ = _run(shard_keys, tmp_path / "cache")
    path = sorted((tmp_path / "cache" / "candidate-pass").glob("*.npz"))[0]
    with np.load(path, allow_pickle=False) as npz:
        arrays = {name: npz[name] for name in npz.files if name != "meta"}
        meta = json.loads(str(npz["meta"]))
    meta["digest"] = "0" * 64
    np.savez_compressed(path, meta=np.asarray(json.dumps(meta)), **arrays)
    second, _ = _run(shard_keys, tmp_path / "cache")
    assert second["cached_shards"] == len(shard_keys) - 1
    _same(first, second)
    third, _ = _run(shard_keys, tmp_path / "cache")
    assert third["cached_shards"] == len(shard_keys)          # the rebuild overwrote it


def test_a_truncated_file_is_a_miss_not_a_crash(store_dir, tmp_path):
    shard_keys = _shard_keys(store_dir)
    first, _ = _run(shard_keys, tmp_path / "cache")
    path = sorted((tmp_path / "cache" / "candidate-pass").glob("*.npz"))[0]
    path.write_bytes(path.read_bytes()[:100])
    second, _ = _run(shard_keys, tmp_path / "cache")
    assert second["cached_shards"] == len(shard_keys) - 1
    _same(first, second)


def test_no_cache_dir_means_no_files_and_no_count(store_dir, tmp_path):
    shard_keys = _shard_keys(store_dir)
    out, lines = _run(shard_keys, None)
    assert out["cached_shards"] == 0
    assert not (tmp_path / "cache").exists()


def test_the_pool_path_pairs_each_result_with_its_own_file(store_dir, tmp_path, monkeypatch):
    """With several workers the pool completes in any order; every file must
    hold the shard its name says, and the rows must come out in task order,
    so a serial second pass reads them back equal."""
    shard_keys = _shard_keys(store_dir)
    assert len(shard_keys) > 1
    first, _ = _run(shard_keys, tmp_path / "cache", workers=2)
    assert first["cached_shards"] == 0
    _forbid_worker(monkeypatch)
    second, _ = _run(shard_keys, tmp_path / "cache", workers=1)
    assert second["cached_shards"] == len(shard_keys)
    _same(first, second)


def test_the_trainer_reports_the_hits_in_its_receipt(store_dir, luna, tmp_path, monkeypatch):
    """The real trainer twice with one cache dir: the second run's test pass is
    served from disk and metrics.json says so."""
    from tests.test_cwv_train import THIRDS, train_v0
    from shengji.train import train_cwv

    luna_path, _rows = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=1, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              cache_dir=str(tmp_path / "shared-cache"),
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    cold = train_cwv.train(out=tmp_path / "cold", **kw)
    warm = train_cwv.train(out=tmp_path / "warm", **kw)
    rc, rw = cold["final"]["test"]["ranking"], warm["final"]["test"]["ranking"]
    assert rc["shards_from_cache"] == 0
    assert rw["shards_from_cache"] > 0
    assert rc["records"] == rw["records"] > 0 and rc["candidates"] == rw["candidates"]
    on_disk = json.loads((tmp_path / "warm" / "metrics.json").read_text())
    assert on_disk["final"]["test"]["ranking"]["shards_from_cache"] == rw["shards_from_cache"]
    # same weights (same seed, same data), so the same candidate values and agreement
    assert rc["scorers"]["cwv"] == rw["scorers"]["cwv"]
