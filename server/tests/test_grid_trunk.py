"""The ``grid`` trunk block (issue #411): the card planes read as a suit x
level table in front of the residual blocks.

The layout must agree with the engine's ordering for every trump, the block
must be parameter-matched to M1's residual twin at the G1 cell, archived
payloads must be untouched, and the trainer must build and seal it."""
import numpy as np
import pytest
import torch

import random

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import RANKS, SUITS, TRUMP, Ordering
from shengji.engine.game import Game
from shengji.rl.card_grid import (GRID_COLS, GRID_ROWS, PAD, TRUMP_CHOICES, grid_slots,
                                  grid_table)
from shengji.rl.encode import CARD_INDEX, N_CARDS
from shengji.rl.value_inference import tensors_for_model
from shengji.rl.value_model import ValueModelConfig, ValueModelError, ValueNetwork
from shengji.train import train_cwv
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401
from tests.test_cwv_train import THIRDS, train_v0

CODES = {index: code for code, index in CARD_INDEX.items()}


def _cfg(block="grid", channels=44, layers=3, hidden=330, search_head=True):
    return train_cwv.model_config("mlp", hidden=hidden, trunk_layers=layers, trunk_block=block,
                                  grid_channels=channels, search_head=search_head,
                                  encoder_version=2)


@pytest.mark.parametrize("suit", TRUMP_CHOICES)
@pytest.mark.parametrize("rank", RANKS)
def test_every_card_lands_once_in_its_effective_suit_row_with_levels_left_to_right(suit, rank):
    o = Ordering(suit, rank)
    slots = grid_slots(suit, rank)
    filled = slots[slots != PAD]
    assert sorted(filled.tolist()) == sorted(CARD_INDEX.values())   # each card exactly once
    rows = list(SUITS) + [TRUMP]
    for r in range(GRID_ROWS):
        levels = []
        for c in range(GRID_COLS):
            if slots[r, c] == PAD:
                continue
            code = CODES[int(slots[r, c])]
            assert o.eff_suit(code) == rows[r]
            levels.append(o.level(code))
        assert levels == sorted(levels)            # a column is a level, left to right
    # the trump row holds the whole trump group, incl. both jokers at the top
    assert CODES[int(slots[4, 17])] == "BJ" and CODES[int(slots[4, 16])] == "LJ"


def test_table_is_indexed_by_the_encoder_one_hots():
    table = grid_table()
    assert table.shape == (len(TRUMP_CHOICES) * len(RANKS), GRID_ROWS * GRID_COLS)
    for si, suit in enumerate(TRUMP_CHOICES):
        for ri, rank in enumerate(RANKS):
            assert np.array_equal(table[si * 13 + ri], grid_slots(suit, rank).reshape(-1))


def test_grid_of_a_real_round_matches_the_hand_by_effective_suit():
    g = Game(random.Random(7))
    rnd = g.start_round()
    hb = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        elif rnd.phase == "bury":
            rnd.bury(rnd.banker, hb.decide_bury(rnd, rnd.banker))
    for _ in range(6):                               # a trick and a half: the history is non-empty
        rnd.play(rnd.turn, hb.decide_play(rnd, rnd.turn))
    model = ValueNetwork(_cfg())
    t = tensors_for_model(model, rnd, 1)
    x = torch.cat((torch.from_numpy(t.public), torch.from_numpy(t.world).flatten(),
                   torch.from_numpy(t.perspective))).unsqueeze(0)
    g = model.trunk.grid(x)                          # (1, planes, rows, cols)
    o = rnd.ordering
    rows = list(SUITS) + [TRUMP]
    for r, eff in enumerate(rows):
        held = sum(1 for card in rnd.hands[1] if o.eff_suit(card) == eff)
        assert float(g[0, 0, r].sum()) == pytest.approx(held * 0.5)   # own-hand plane (count / 2)
        assert float(g[0, 9, r].sum()) == pytest.approx(held * 0.5)   # world receiver 0 (count / 2)
    assert float(g.sum()) == pytest.approx(float(x[0, :9 * N_CARDS].sum() + t.world.sum()))


def test_g1_cell_is_parameter_matched_to_m1s_residual_twin_and_has_both_heads():
    def n(cfg):
        return sum(p.numel() for p in ValueNetwork(cfg).parameters())
    m1 = train_cwv.model_config("mlp", hidden=330, trunk_layers=4, trunk_block="residual",
                                search_head=True, encoder_version=2)
    assert n(m1) == 644_568                          # M1 (A-d4-2h-176k, ckpt 3cb9cd62)
    g1 = n(_cfg())
    assert abs(g1 - 644_568) / 644_568 < 0.005 and g1 == 644_423   # lean block, 44 channels
    net = ValueNetwork(_cfg())
    x = torch.randn(5, 561 + 270 + 2)
    x[:, 486:491] = 0; x[:, 488] = 1; x[:, 491:504] = 0; x[:, 495] = 1
    f = net.features(x[:, :561], x[:, 561:831].reshape(5, 5, 54), x[:, 831:])
    assert f.shape == (5, 165)
    assert net.head_logits(f, "outcome").shape == (5, 204)
    assert net.head_logits(f, "search-mean").shape == (5, 204)
    net.head_logits(f, "outcome").sum().backward()
    assert all(p.grad is not None for name, p in net.named_parameters() if "search_head" not in name)


def test_the_two_window_implementations_agree_and_the_forward_is_identical():
    """The conv1d path (oneDNN CPUs) and the flat per-tap GEMM path compute the same
    read; a whole forward through either gives the same features."""
    net = ValueNetwork(_cfg(channels=16, hidden=64)).eval()
    tr = net.trunk
    h = torch.randn(3, tr.rows, tr.cols, tr.win2_w.shape[1])
    tr.use_conv1d = True; a = tr._window(h, tr.win2_w, tr.win2_b)
    tr.use_conv1d = False; b = tr._window(h, tr.win2_w, tr.win2_b)
    assert torch.allclose(a, b, atol=1e-5)
    x = torch.rand(7, 561 + 270 + 2); x[:, 486:491] = 0; x[:, 488] = 1; x[:, 491:504] = 0; x[:, 495] = 1
    with torch.no_grad():
        tr.use_conv1d = True; fa = net.features(x[:, :561], x[:, 561:831].reshape(7, 5, 54), x[:, 831:])
        tr.use_conv1d = False; fb = net.features(x[:, :561], x[:, 561:831].reshape(7, 5, 54), x[:, 831:])
    assert torch.allclose(fa, fb, atol=1e-5)
    tr.use_conv1d = None


def test_window_read_equals_a_kernel_3_convolution_along_the_row():
    """The flat per-tap GEMM is a width-3 convolution along the column axis with
    zero padding, weights shared across rows -- checked against F.conv2d."""
    net = ValueNetwork(_cfg(channels=16, hidden=64))
    tr = net.trunk
    h = torch.randn(3, tr.rows, tr.cols, tr.win2_w.shape[1])
    out = tr._window(h, tr.win2_w, tr.win2_b)
    weight = tr.win2_w.permute(2, 1, 0).unsqueeze(2)               # (O, C, 1, 3)
    ref = torch.nn.functional.conv2d(h.permute(0, 3, 1, 2), weight, tr.win2_b, padding=(0, 1))
    assert torch.allclose(out, ref.permute(0, 2, 3, 1), atol=1e-5)


def test_grid_requires_its_channels_and_other_blocks_refuse_them():
    with pytest.raises(train_cwv.TrainError):
        _cfg(channels=0)
    with pytest.raises(train_cwv.TrainError):
        _cfg(block="residual", channels=40)
    with pytest.raises(train_cwv.TrainError):          # Codex #412 review: a negative count
        _cfg(block="residual", channels=-1)
    with pytest.raises(train_cwv.TrainError):          # Codex #412 review: seq silently ignored grid
        train_cwv.model_config("seq", trunk_block="grid", grid_channels=40, encoder_version=2)
    with pytest.raises(train_cwv.TrainError):
        train_cwv.model_config("seq", trunk_layers=4, trunk_block="residual", encoder_version=2)
    assert train_cwv.model_config("seq", encoder_version=2).architecture != "mlp"
    base = _cfg().payload()
    for change in ({"grid_channels": 0}, {"trunk_block": "residual"}, {"grid_channels": 2048}):
        with pytest.raises(ValueModelError):
            ValueModelConfig.from_payload({**base, **change})


def test_payloads_of_existing_shapes_carry_no_grid_field_and_grid_round_trips():
    for block, layers in (("plain", 2), ("residual", 4)):
        cfg = train_cwv.model_config("mlp", hidden=64, trunk_layers=layers, trunk_block=block,
                                     encoder_version=2)
        assert "grid_channels" not in cfg.payload()
        assert ValueModelConfig.from_payload(cfg.payload()) == cfg
    cfg = _cfg(channels=16, hidden=64)
    payload = cfg.payload()
    assert payload["grid_channels"] == 16 and payload["trunk_block"] == "grid"
    assert ValueModelConfig.from_payload(payload) == cfg
    bad = dict(payload); bad["grid_channels"] = 0
    with pytest.raises(ValueModelError):
        ValueModelConfig.from_payload(bad)


def test_trainer_builds_seals_and_reloads_a_grid_net(store_dir, luna, tmp_path):  # noqa: F811
    luna_path, _ = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    result = train_cwv.train(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp",
                             device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32,
                             trunk_layers=2, trunk_block="grid", grid_channels=8, search_head=False,
                             log=None, cache_workers=1, eval_workers=1, bench_batch=32,
                             public_head=str(tmp_path / "public" / "best.pt"),
                             out=tmp_path / "grid", **THIRDS)
    mc = result["model"]["config"]
    assert mc["trunk_block"] == "grid" and mc["grid_channels"] == 8
    model, meta, _aux = train_cwv.load_cwv_checkpoint(tmp_path / "grid" / "best.pt")
    assert model.config.trunk_block == "grid" and model.config.grid_channels == 8
    assert result["model"]["parameters"] == sum(p.numel() for p in model.parameters())
