"""Trunk depth for the mlp value net (the architecture grid).

Every model trained before this option existed has a two-layer plain trunk.
That shape must stay byte-identical, its archived payloads must still load,
and the new shapes must refuse nonsense, train, and seal a receipt."""
import pytest
import torch

from shengji.rl.value_afterstate import OUTCOME_CLASSES
from shengji.rl.value_model import (ValueModelConfig, ValueModelError, ValueNetwork,
                                    _LEGACY_TRUNK, mlp_input_dim)
from shengji.train import train_cwv
# the trainer fixture family is module-local to test_cwv_train; importing registers it
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401
from tests.test_cwv_train import THIRDS, train_v0


def _mlp(hidden, layers=2, block="plain"):
    return train_cwv.model_config("mlp", hidden=hidden, trunk_layers=layers, trunk_block=block,
                                  encoder_version=2)


def test_legacy_shape_is_the_default_and_its_payload_carries_no_trunk_fields():
    cfg = _mlp(64)
    assert (cfg.trunk_layers, cfg.trunk_block) == (2, "plain") == tuple(_LEGACY_TRUNK.values())
    payload = cfg.payload()
    assert "trunk_layers" not in payload and "trunk_block" not in payload
    assert ValueModelConfig.from_payload(payload) == cfg
    # a payload written before the fields existed (no width fields either) still loads
    legacy = {k: v for k, v in payload.items() if k not in ("public_dim", "enc_version")}
    assert ValueModelConfig.from_payload(legacy).trunk_layers == 2


def test_non_legacy_shape_is_recorded_and_round_trips():
    cfg = _mlp(64, layers=4, block="residual")
    payload = cfg.payload()
    assert payload["trunk_layers"] == 4 and payload["trunk_block"] == "residual"
    assert ValueModelConfig.from_payload(payload) == cfg


@pytest.mark.parametrize("layers,block", [(1, "plain"), (128, "residual"), (4, "resnet"), (3.0, "plain")])
def test_nonsense_trunks_are_refused(layers, block):
    with pytest.raises((ValueModelError, TypeError)):
        cfg = _mlp(64)
        object.__setattr__(cfg, "trunk_layers", layers)
        object.__setattr__(cfg, "trunk_block", block)
        cfg.validate()


def test_unknown_payload_keys_are_still_schema_drift():
    payload = _mlp(64).payload()
    payload["trunk_depth"] = 4
    with pytest.raises(ValueModelError, match="schema drift"):
        ValueModelConfig.from_payload(payload)


def test_legacy_trunk_module_order_is_unchanged():
    net = ValueNetwork(_mlp(64))
    kinds = [type(m).__name__ for m in net.trunk]
    assert kinds == ["Linear", "GELU", "Dropout", "Linear", "GELU", "Dropout"]
    assert net.trunk[0].in_features == mlp_input_dim(net.config.public_dim)


def test_state_dict_of_a_legacy_net_is_unchanged_by_the_option():
    """The exact parameter names and shapes every archived checkpoint carries."""
    torch.manual_seed(0)
    net = ValueNetwork(_mlp(64))
    keys = list(net.state_dict())
    assert keys == ["trunk.0.weight", "trunk.0.bias", "trunk.3.weight", "trunk.3.bias",
                    "head.weight", "head.bias"]


def test_residual_and_plain_depth_build_the_intended_trunks():
    res = ValueNetwork(_mlp(64, layers=3, block="residual"))
    kinds = [type(m).__name__ for m in res.trunk]
    assert kinds == ["Linear", "ResidualTrunkBlock", "ResidualTrunkBlock", "ResidualTrunkBlock",
                     "LayerNorm", "ReLU"]
    assert all(type(m.norm).__name__ == "LayerNorm" for m in res.trunk[1:4])
    plain = ValueNetwork(_mlp(64, layers=4, block="plain"))
    assert [type(m).__name__ for m in plain.trunk].count("Linear") == 4


def _params(cfg):
    return sum(p.numel() for p in ValueNetwork(cfg).parameters())


def test_the_s_row_of_the_grid_is_parameter_matched_within_one_percent():
    """S budget: depth-2 plain h512 (every existing 0.61M model) versus the
    three residual cells the grid trains at that budget."""
    base = _params(_mlp(512))
    for hidden, layers in ((436, 2), (330, 4), (244, 8)):
        cell = _params(_mlp(hidden, layers=layers, block="residual"))
        assert abs(cell - base) / base < 0.01, (hidden, layers, cell, base)
    plain4 = _params(_mlp(340, layers=4, block="plain"))
    assert abs(plain4 - base) / base < 0.01


def test_depth_8_residual_learns_a_toy_target():
    torch.manual_seed(1)
    din = mlp_input_dim(_mlp(64).public_dim)
    x = torch.randn(512, din)
    y = torch.randint(0, OUTCOME_CLASSES, (512,))

    def fit(block):
        torch.manual_seed(2)
        net = ValueNetwork(_mlp(64, layers=8, block=block))
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        net.train()
        first = last = None
        for step in range(200):
            opt.zero_grad()
            loss = torch.nn.functional.cross_entropy(net.head(net.trunk(x)), y)
            loss.backward()
            opt.step()
            first = loss.item() if first is None else first
            last = loss.item()
        return first, last

    r0, r1 = fit("residual")
    assert r1 < 0.25 * r0, (r0, r1)  # memorises 512 random labels: 5.40 -> well under 1.4


def test_end_to_end_training_with_a_residual_trunk_seals_a_receipt_that_reloads(store_dir, luna, tmp_path):
    luna_path, _ = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    result = train_cwv.train(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp",
                             device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32,
                             trunk_layers=4, trunk_block="residual", log=None, cache_workers=1,
                             eval_workers=1, bench_batch=32,
                             public_head=str(tmp_path / "public" / "best.pt"),
                             out=tmp_path / "depth", **THIRDS)
    mc = result["model"]["config"]
    assert mc["trunk_layers"] == 4 and mc["trunk_block"] == "residual"
    model, meta, _aux = train_cwv.load_cwv_checkpoint(tmp_path / "depth" / "best.pt")
    assert model.config.trunk_layers == 4 and model.config.trunk_block == "residual"
    assert result["model"]["parameters"] == sum(p.numel() for p in model.parameters())
    # the default recipe still writes a payload without the fields
    plain = train_cwv.train(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp",
                            device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32,
                            log=None, cache_workers=1, eval_workers=1, bench_batch=32,
                            public_head=str(tmp_path / "public" / "best.pt"),
                            out=tmp_path / "plain", **THIRDS)
    assert "trunk_layers" not in plain["model"]["config"]


def test_cli_parses_the_trunk_flags():
    args = train_cwv.build_parser().parse_args(
        ["train", "--data", "x", "--out", "y", "--trunk-layers", "8", "--trunk-block", "residual"])
    assert args.trunk_layers == 8 and args.trunk_block == "residual"
    with pytest.raises(SystemExit):
        train_cwv.build_parser().parse_args(["train", "--data", "x", "--out", "y", "--trunk-block", "resnet"])


def test_residual_trunk_trains_on_a_single_row_batch():
    """BatchNorm refuses B=1 in training mode; the block store yields such
    tails, so the residual trunk must accept one."""
    net = ValueNetwork(_mlp(64, layers=4, block="residual"))
    net.train()
    din = mlp_input_dim(net.config.public_dim)
    out = net.head(net.trunk(torch.randn(1, din)))
    assert out.shape == (1, OUTCOME_CLASSES)
    out.sum().backward()


def test_real_training_loop_with_a_singleton_tail_batch_completes(store_dir, luna, tmp_path):
    """Codex's witness: a window remainder of exactly one row reaches the model
    in training mode through the real loop, not a direct layer call."""
    luna_path, _ = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=1, seed=7, n_boot=10, hidden=32, trunk_layers=4, trunk_block="residual",
              log=None, cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    probe = train_cwv.train(out=tmp_path / "probe", batch_size=64, **kw)
    rows = probe["epochs"][0]["train"]["rows"]
    assert rows > 2
    # rows - 1 per batch leaves a trailing batch of exactly one row
    tail = train_cwv.train(out=tmp_path / "tail", batch_size=rows - 1, **kw)
    ep = tail["epochs"][0]["train"]
    assert ep["rows"] == rows and ep["batches"] == 2
    assert (tmp_path / "tail" / "best.pt").exists()
