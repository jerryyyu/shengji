"""Synthetic DEEP8 capacity witness; selected by both CWV CI engine modes."""
import torch

from shengji.rl.value_model import ValueNetwork, mlp_input_dim
from shengji.train import train_cwv


def test_fixed_width_four_to_eight_preserves_all_existing_heads(tmp_path):
    torch.manual_seed(7)
    common = dict(hidden=330, trunk_block="residual", policy_head=True,
                  search_head=True, encoder_version=2)
    source_cfg = train_cwv.model_config("mlp", trunk_layers=4, **common)
    target_cfg = train_cwv.model_config("mlp", trunk_layers=8, **common)
    source, target = ValueNetwork(source_cfg), ValueNetwork(target_cfg)
    source_aux = train_cwv.AuxPointsHead(source_cfg.width)
    target_aux = train_cwv.AuxPointsHead(target_cfg.width)
    # apply_init's preloaded path avoids a real checkpoint. This sentinel only
    # supplies the receipt's file hash, not model weights or serialized metadata.
    sentinel = tmp_path / "synthetic-init.txt"
    sentinel.write_text("synthetic preloaded weights\n")
    metadata = dict(arch="mlp", model_config=source_cfg.payload(),
                    exposure=train_cwv.exposure_block([], []))
    info = train_cwv.apply_init(
        target, target_aux, str(sentinel),
        dict(arch="mlp", model_config=target_cfg.payload()), torch.device("cpu"),
        loaded=(source, metadata, source_aux))
    assert source_cfg.width == target_cfg.width == 165
    assert info["trunk_blocks_added"] == 4
    assert info["trunk_blocks_added_identity_init"]
    assert info["aux_points_head_loaded"] and not info["policy_head_fresh"]
    for i in range(5, 9):
        assert not target.trunk[i].down.weight.any()
        assert not target.trunk[i].down.bias.any()
    assert torch.equal(source.trunk[5].weight, target.trunk[9].weight)
    source.eval(); target.eval()
    x = torch.randn(64, mlp_input_dim(source_cfg.public_dim))
    with torch.no_grad():
        before, after = source.features_flat(x), target.features_flat(x)
        assert torch.equal(before, after)
        for name in ("head", "policy_head", "search_head"):
            assert torch.equal(getattr(source, name)(before), getattr(target, name)(after))
        assert torch.equal(source_aux(before), target_aux(after))
