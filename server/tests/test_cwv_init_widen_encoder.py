"""A v7 run may warm-start from a v2 checkpoint (``--init-widen-encoder``).

v7 is v2's 560 columns plus 4 appended before the public tensor's terminal flag.  The widened
net gives those 4 inputs zero weight, so at step 0 it computes the source's function exactly
on every v7 row (whatever the new columns hold), for the plain, residual and grid trunks.  Any
other encoder difference is still refused, and so is a widening nobody asked for.
"""
from __future__ import annotations

import copy
import random

import numpy as np
import pytest
import torch

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.value_afterstate_v2 import public_dim, tensors_from_round
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import train_cwv
from shengji.train.train_cwv import _widen_first_layer, apply_init, load_cwv_checkpoint
from tests.test_cwv_train import THIRDS, records, store_dir  # noqa: F401  (shared corpus fixtures)

TRUNKS = {"plain": dict(trunk_block="plain", trunk_layers=2),
          "residual": dict(trunk_block="residual", trunk_layers=2),
          "grid": dict(trunk_block="grid", trunk_layers=2, grid_channels=8)}


def _rows(version):
    game = Game(random.Random(3))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    bot = SmartBot()
    for s in range(4):
        cards = bot.decide_declare(rnd, s, final=True)
        if cards:
            rnd.declare(s, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    states = []
    while rnd.phase == "play" and len(states) < 40:
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
        if rnd.phase == "play":
            states.append(copy.deepcopy(rnd))
    rows = [tensors_from_round(s, s.turn, version=version) for s in states]
    return torch.from_numpy(np.stack([np.concatenate([r.public, r.world.ravel(), r.perspective])
                                      for r in rows]))


@pytest.mark.parametrize("trunk", sorted(TRUNKS))
def test_the_widened_net_is_the_source_function_on_v7_rows(trunk):
    torch.manual_seed(1)
    cfg = dict(architecture="mlp", width=32, feedforward_width=64, attention_heads=1,
               search_head=True, policy_head=True, **TRUNKS[trunk])
    source = ValueNetwork(ValueModelConfig(public_dim=public_dim(2), enc_version=2, **cfg)).eval()
    target = ValueNetwork(ValueModelConfig(public_dim=public_dim(7), enc_version=7, **cfg)).eval()
    state, info = _widen_first_layer(source.state_dict(), target.state_dict(), target.config, 2)
    target.load_state_dict(state)
    assert info["from"] == 2 and info["to"] == 7 and info["zero_columns"] == 4
    assert info["parameter"] == ("trunk.stem.weight" if trunk == "grid" else "trunk.0.weight")
    x2, x7 = _rows(2), _rows(7)
    assert x7.shape[1] == x2.shape[1] + 4
    assert torch.equal(x7[:, :560], x2[:, :560]) and torch.equal(x7[:, 564:], x2[:, 560:])
    assert x7[:, 560:564].sum() == x7.shape[0], "the next-actor block is live on these rows"
    with torch.no_grad():
        f2, f7 = source.features_flat(x2), target.features_flat(x7)
        torch.testing.assert_close(f7, f2, rtol=0, atol=1e-5)
        for head in ("head", "search_head", "policy_head"):
            torch.testing.assert_close(getattr(target, head)(f7), getattr(source, head)(f2),
                                       rtol=0, atol=1e-5)
    # the new inputs are trainable from zero
    weight = target.state_dict()[info["parameter"]]
    at = info["inserted_at"]
    assert not weight[:, at:at + 4].any()
    target.train()
    optim = torch.optim.SGD(target.parameters(), lr=0.1)
    target.head(target.features_flat(x7)).sum().backward()
    optim.step()
    assert target.state_dict()[info["parameter"]][:, at:at + 4].any()


@pytest.fixture(scope="module")
def base_v2(store_dir, tmp_path_factory):  # noqa: F811
    out = tmp_path_factory.mktemp("widen") / "v2"
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=10, hidden=32, trunk_layers=2, trunk_block="residual", log=None,
              cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50, **THIRDS)
    train_cwv.train(out=out, encoder_version=2, **kw)
    return out / "best.pt", kw


def test_the_trainer_widens_only_when_asked_and_records_it(base_v2, tmp_path):
    path, kw = base_v2
    with pytest.raises(train_cwv.TrainError, match="model configuration differs"):
        train_cwv.train(out=tmp_path / "unasked", encoder_version=7, init=str(path),
                        init_exclude_exposed=True, **kw)
    with pytest.raises(train_cwv.TrainError, match="needs --init"):
        train_cwv.train(out=tmp_path / "noinit", encoder_version=7, init_widen_encoder=True, **kw)
    run = train_cwv.train(out=tmp_path / "v7", encoder_version=7, init=str(path),
                          init_exclude_exposed=True, init_widen_encoder=True, **kw)
    assert run["init"]["encoder_widened"] == {"from": 2, "to": 7, "parameter": "trunk.0.weight",
                                              "zero_columns": 4, "inserted_at": 560}
    assert run["config"]["init_widen_encoder"] is True and run["config"]["encoder_version"] == 7
    model, meta, _ = load_cwv_checkpoint(str(tmp_path / "v7" / "best.pt"), "cpu")
    assert model.config.enc_version == 7 and meta["encoder"]["enc_version"] == 7


@pytest.mark.parametrize("ours", [6, 1])
def test_a_layout_that_does_not_append_to_the_source_is_refused(base_v2, ours):
    path, _kw = base_v2
    _source, meta, _aux = load_cwv_checkpoint(str(path), "cpu")
    mc = {**meta["model_config"], "enc_version": ours, "public_dim": public_dim(ours)}
    if ours == 1:
        mc = {k: v for k, v in mc.items() if k not in ("enc_version", "public_dim")}
    config = {"arch": meta["arch"], "model_config": mc}
    model = ValueNetwork(ValueModelConfig.from_payload(dict(mc)))
    # v6 rewrites v1 columns and v1 is narrower: neither is v2 with columns appended
    with pytest.raises(train_cwv.TrainError):
        apply_init(model, None, str(path), config, torch.device("cpu"), widen_encoder=True)
