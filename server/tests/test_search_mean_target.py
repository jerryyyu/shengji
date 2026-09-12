"""Issue #340: the search's mean as the level-head target, soft two-class form."""
import glob
import json
import os

import numpy as np
import pytest
import torch

from shengji.rl.value_afterstate import signed_level_category
from shengji.train import search_mean_sidecar as sc
from shengji.train.search_mean_target import soft_targets
# the trainer fixture family is module-local to test_cwv_train; importing registers it
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401
from tests.test_cwv_train import THIRDS, train_v0, train_cwv


def _mean_for(utility: float, points: float, attacker: bool) -> float:
    """The search scale: sign * (40 U + 0.2 p)."""
    return (1.0 if attacker else -1.0) * (40.0 * utility + 0.2 * points)


def test_exact_half_integer_utility_is_a_one_hot_on_that_class():
    for attacker in (True, False):
        # 120 attacker points sit in the 1.5 level bracket (attacker_level_utility)
        mean = torch.tensor([_mean_for(1.5, 120.0, attacker)])
        probs, used = soft_targets(mean, torch.tensor([120.0]), torch.tensor([attacker]),
                                   torch.tensor([7]))
        assert used.tolist() == [True]
        want = signed_level_category(120, attacker)
        assert probs[0].argmax().item() == want and probs[0, want].item() == pytest.approx(1.0)


def test_fractional_utility_splits_between_the_neighbouring_classes():
    mean = torch.tensor([_mean_for(1.75, 120.0, True)])
    probs, used = soft_targets(mean, torch.tensor([120.0]), torch.tensor([True]), torch.tensor([7]))
    lo, hi = signed_level_category(120, True), signed_level_category(120, True) + 1
    assert used.tolist() == [True]
    # 1.75 is a quarter above 1.5: three quarters of the mass stays on the lower class
    assert probs[0, lo].item() == pytest.approx(0.75) and probs[0, hi].item() == pytest.approx(0.25)
    assert probs[0].sum().item() == pytest.approx(1.0)


def test_missing_or_out_of_support_means_keep_the_realised_one_hot():
    means = torch.tensor([float("nan"), 1e9, -1e9])
    realised = torch.tensor([3, 150, 200])
    probs, used = soft_targets(means, torch.tensor([50.0, 50.0, 50.0]),
                               torch.tensor([True, True, False]), realised)
    assert used.tolist() == [False, False, False]
    for i, cat in enumerate(realised.tolist()):
        assert probs[i, cat].item() == 1.0 and probs[i].sum().item() == 1.0


def test_sidecar_round_trip_aligns_by_record_hash(tmp_path):
    shard = tmp_path / "cluster-00000.jsonl"
    rows = [{"action": ["S2"], "record_sha256": "a" * 64,
             "preference": {"means": [-1.0, 2.5], "played_index": 1}},
            {"action": ["S3"], "record_sha256": "b" * 64, "preference": {"means": [], "played_index": 0}},
            {"note": "not a decision"}]
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    counts = sc.build_sidecar(shard, tmp_path / "side")
    assert counts["records"] == 2 and counts["with_mean"] == 1
    arrays = {"record_sha256": np.asarray([b"b" * 64, b"a" * 64], dtype="S64")}
    sc.attach_search_means(arrays, counts["shard_sha256"], tmp_path / "side")
    got = arrays["search_mean_played"]
    assert np.isnan(got[0]) and got[1] == pytest.approx(2.5)


def test_trainer_uses_the_search_mean_target_only_where_a_mean_exists(store_dir, luna, tmp_path,
                                                                        monkeypatch):
    luna_path, _rows = luna
    side = tmp_path / "sidecar"
    built = [sc.build_sidecar(p, side) for p in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True))]
    assert built and sum(c["with_mean"] for c in built) > 0
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=1, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    realised = train_cwv.train(out=tmp_path / "realised", **kw)
    searched = train_cwv.train(out=tmp_path / "searched", target="search-mean",
                               search_mean_sidecar=str(side), **kw)
    assert realised["target"] == {"kind": "realised"}
    assert searched["target"]["kind"] == "search-mean"
    assert searched["target"]["sidecar_manifest_sha256"] == sc.manifest_sha256(side)
    ep = searched["epochs"][0]["train"]
    assert 0 < ep["search_mean_rows"] <= ep["rows"]
    # a different target trains different weights; the comparable numbers stay realised
    assert searched["epochs"][0]["train"]["cross_entropy"] != realised["epochs"][0]["train"]["cross_entropy"]
    assert searched["selection"]["criterion"] == realised["selection"]["criterion"]
    with pytest.raises(train_cwv.TrainError, match="search-mean-sidecar"):
        train_cwv.train(out=tmp_path / "bad", target="search-mean", **kw)
