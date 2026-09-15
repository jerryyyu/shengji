"""#425: the joint net — a policy head on the value trunk, mixed root/value batches,
warm start from a headless incumbent, matched twin, and consumer loading."""
from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import policy_prior as pp
from shengji.train import train_cwv
from tests.test_cwv_train import THIRDS, store_dir, records  # noqa: F401


def test_policy_head_config_is_optional_in_the_payload_and_builds_the_module():
    plain = ValueModelConfig(architecture="mlp", width=16, history_layers=1, attention_heads=1,
                             feedforward_width=32, public_dim=561, enc_version=2)
    assert "policy_head" not in plain.payload()
    joint = ValueModelConfig(**{**plain.__dict__, "policy_head": True})
    assert joint.payload()["policy_head"] is True
    assert ValueModelConfig.from_payload(joint.payload()) == joint
    net = ValueNetwork(joint)
    assert net.policy_head.out_features == 54
    with pytest.raises(Exception):
        ValueNetwork(plain).policy_logits(torch.zeros(1, 16))
    x = torch.zeros(2, 833)
    assert net.policy_logits(net.features_flat(x)).shape == (2, 54)
    with pytest.raises(Exception):
        ValueModelConfig(**{**plain.__dict__, "architecture": "transformer", "policy_head": True}).validate()


@pytest.fixture(scope="module")
def policy_rows(store_dir, tmp_path_factory):  # noqa: F811
    out = tmp_path_factory.mktemp("rows") / "rows"
    summary = pp.extract(out, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    assert summary["rows"] > 20 and summary["deals"] >= 1
    return str(out)


def test_joint_net_trains_from_a_headless_incumbent_and_the_twin_matches_steps(
        store_dir, policy_rows, tmp_path):  # noqa: F811
    from shengji.ai.cwv_policy import load_cwv_checkpoint as consumer_load
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=10, hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32,
              val_rank_records=50, encoder_version=2, aux_points=True, **THIRDS)
    base = train_cwv.train(out=tmp_path / "base", **kw)
    assert "policy_head" not in base["model"]["config"] and base["policy_head"] is None
    with pytest.raises(train_cwv.TrainError, match="needs --policy-rows"):
        train_cwv.train(out=tmp_path / "bad", policy_head=True, **kw)
    with pytest.raises(train_cwv.TrainError, match="need --policy-head"):
        train_cwv.train(out=tmp_path / "bad2", policy_rows=policy_rows, **kw)

    joint = train_cwv.train(out=tmp_path / "joint", policy_head=True, policy_rows=policy_rows,
                            policy_eval=policy_rows, policy_weight=1.0, policy_listwise_weight=1.0,
                            policy_batch_fraction=0.5, init=str(tmp_path / "base" / "best.pt"),
                            init_exclude_exposed=True, **kw)
    assert joint["model"]["config"]["policy_head"] is True
    assert joint["init"]["policy_head_fresh"] is True and joint["init"]["aux_points_head_loaded"] is True
    block = joint["policy_head"]
    assert block["twin"] is False and block["root_batch"] == 32 and block["rows"]["rows_used"] > 20
    assert block["rows"]["deals"] >= 1 and block["eval"]["rows"] == block["rows"]["rows_available"]
    tr = joint["epochs"][0]["train"]
    assert tr["policy_rows"] > 0 and tr["policy_bce"] > 0 and tr["policy_listwise"] >= 0
    val = joint["epochs"][0]["val"]["policy"]
    assert val["top64"] and all(0.0 <= v <= 1.0 for v in val["top64"].values()) and val["deals"]
    assert "policy_head" in joint["consumer"]["heads"]
    # the checkpoint carries the head and the consumer's loader rebuilds it
    model, meta, _ = consumer_load(tmp_path / "joint" / "best.pt")
    assert model.config.policy_head and "policy_head.weight" in model.state_dict()
    assert meta["policy_head"]["rows"]["npz_sha256"] == block["rows"]["npz_sha256"]
    lo = model.policy_logits(model.features_flat(torch.zeros(1, 833)))
    assert lo.shape == (1, 54) and torch.isfinite(lo).all()
    # a headless run cannot warm-start from a policy-head net (layout differs)
    with pytest.raises(train_cwv.TrainError):
        train_cwv.train(out=tmp_path / "back", init=str(tmp_path / "joint" / "best.pt"),
                        init_exclude_exposed=True, **kw)

    # the matched twin: same batches and steps, weight 0 -> the head never moves
    twin = train_cwv.train(out=tmp_path / "twin", policy_head=True, policy_rows=policy_rows,
                           policy_eval=policy_rows, policy_weight=0.0, policy_batch_fraction=0.5,
                           init=str(tmp_path / "base" / "best.pt"), init_exclude_exposed=True, **kw)
    assert twin["policy_head"]["twin"] is True
    assert twin["epochs"][0]["train"]["policy_rows"] == tr["policy_rows"]
    assert twin["epochs"][0]["train"]["rows"] == tr["rows"] and twin["epochs"][0]["train"]["batches"] == tr["batches"]
    tw, _, _ = consumer_load(tmp_path / "twin" / "best.pt")
    # weight 0: the trunk received no policy gradient, so the two nets diverge only through it
    assert not torch.allclose(tw.state_dict()["head.weight"], model.state_dict()["head.weight"])
    assert twin["epochs"][0]["train"]["policy_bce"] is not None      # forwarded and measured, not trained
