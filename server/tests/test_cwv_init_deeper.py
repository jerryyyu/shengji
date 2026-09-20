"""A deeper residual trunk warm-starts from a shallower incumbent (Jerry 2026-09-20: 'start with
base model M1 and then train new layers on top with the new dataset').  The added blocks are
identity at step 0, so the deeper net IS the incumbent's function before training; the receipt
records how many blocks were added; every other configuration difference is still refused."""
from __future__ import annotations

import pytest
import torch

from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import train_cwv
from shengji.train.train_cwv import apply_init, load_cwv_checkpoint
from tests.test_cwv_train import THIRDS, store_dir, records  # noqa: F401


@pytest.fixture(scope="module")
def base(store_dir, tmp_path_factory):  # noqa: F811
    out = tmp_path_factory.mktemp("deeper") / "base"
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10,
              hidden=32, trunk_layers=2, trunk_block="residual", log=None, cache_workers=1, eval_workers=1,
              bench_batch=32, val_rank_records=50, **THIRDS)
    train_cwv.train(out=out, **kw)
    return out / "best.pt", kw


def _deeper_config(meta, depth):
    return {"arch": meta["arch"], "model_config": {**meta["model_config"], "trunk_layers": depth}}


def test_added_blocks_are_identity_and_the_incumbent_function_is_preserved(base):
    path, _ = base
    source, meta, _aux = load_cwv_checkpoint(str(path), "cpu")
    assert meta["model_config"]["trunk_layers"] == 2 and meta["model_config"]["trunk_block"] == "residual"
    config = _deeper_config(meta, 4)
    model = ValueNetwork(ValueModelConfig.from_payload(dict(config["model_config"])))
    info = apply_init(model, None, str(path), config, torch.device("cpu"))
    assert info["trunk_blocks_added"] == 2 and info["trunk_blocks_added_identity_init"] is True
    assert info["policy_head_fresh"] is False
    # the incumbent's blocks and final norm sit in their slots; the new blocks' output is zero
    src, dst = source.state_dict(), model.state_dict()
    for k in ("trunk.0.weight", "trunk.1.up.weight", "trunk.2.down.bias"):
        assert torch.equal(src[k], dst[k]), k
    assert torch.equal(src["trunk.3.weight"], dst["trunk.5.weight"])        # final LayerNorm remapped
    assert not dst["trunk.3.down.weight"].any() and not dst["trunk.4.down.weight"].any()
    assert dst["trunk.3.up.weight"].any()                                   # the rest is a real init
    source.eval(); model.eval()
    x = torch.randn(16, source.config.public_dim + 5 * 54 + 2)
    with torch.no_grad():
        assert torch.equal(source.features_flat(x), model.features_flat(x))
        assert torch.equal(source.head(source.features_flat(x)), model.head(model.features_flat(x)))
    # the new blocks are trainable: one step at lr>0 moves them off zero
    optim = torch.optim.SGD(model.parameters(), lr=0.1)
    model.train(); model.head(model.features_flat(x)).sum().backward(); optim.step()
    assert model.state_dict()["trunk.3.down.weight"].any()


@pytest.mark.parametrize("change", ["width", "plain", "dropout"])
def test_other_configuration_differences_are_still_refused(base, change):
    path, _ = base
    _source, meta, _aux = load_cwv_checkpoint(str(path), "cpu")
    mc = dict(meta["model_config"])
    if change == "width":
        mc.update(trunk_layers=4, width=48, feedforward_width=max(48, mc["feedforward_width"]))
    elif change == "plain":
        mc.update(trunk_layers=4, trunk_block="plain")
    elif change == "dropout":
        mc.update(trunk_layers=4, dropout=0.5)
    config = {"arch": meta["arch"], "model_config": mc}
    model = ValueNetwork(ValueModelConfig.from_payload(dict(mc)))
    with pytest.raises(train_cwv.TrainError):
        apply_init(model, None, str(path), config, torch.device("cpu"))


def test_the_trainer_warm_starts_deeper_and_records_it(base, tmp_path):
    path, kw = base
    run = train_cwv.train(out=tmp_path / "deeper", init=str(path), init_exclude_exposed=True,
                          **{**kw, "trunk_layers": 3})
    assert run["init"]["trunk_blocks_added"] == 1 and run["init"]["policy_head_fresh"] is False
    assert run["model"]["config"]["trunk_layers"] == 3
    model, meta, _ = load_cwv_checkpoint(str(tmp_path / "deeper" / "best.pt"), "cpu")
    assert meta["model_config"]["trunk_layers"] == 3 and len(model.trunk) == 3 + 3
    # the other direction is refused: a shallower net cannot warm-start from the deeper one
    with pytest.raises(train_cwv.TrainError):
        train_cwv.train(out=tmp_path / "back", init=str(tmp_path / "deeper" / "best.pt"),
                        init_exclude_exposed=True, **kw)
