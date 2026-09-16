"""#411 / #425: a grid-trunk net (G1's suit x level table) served as a v2 NumPy package.

Witnesses: the package reproduces the Torch value softmax and the joint policy head over
the grid trunk without Torch, on inputs whose trump one-hots select different index tables;
the exported grid table is card_grid's; a tampered table, a grid package that hides its
channel count, and a non-grid package that claims one are refused; deep copies share the
immutable weights.
"""
import copy
import json

import numpy as np
import pytest

from shengji.ai.cwv_numpy import (CWVNumpyConfig, CWVNumpyError, GRID_COLS, GRID_ROWS,
                                  PACKAGE_SCHEMA_V2, load_cwv_numpy)


def _inputs(rng, n):
    """Random public rows whose trump one-hots are valid (one suit choice, one rank)."""
    public = rng.standard_normal((n, 561)).astype(np.float32)
    public[:, :486] = rng.integers(0, 3, (n, 486)).astype(np.float32)   # card-count planes
    public[:, 486:491] = 0.0
    public[np.arange(n), 486 + rng.integers(0, 5, n)] = 1.0            # S H D C NT
    public[:, 491:504] = 0.0
    public[np.arange(n), 491 + rng.integers(0, 13, n)] = 1.0           # trump rank
    world = (rng.integers(0, 3, (n, 5, 54)) * 0.5).astype(np.float32)
    persp = np.eye(2, dtype=np.float32)[rng.integers(0, 2, n)]
    return public, world, persp


@pytest.fixture(scope="module")
def grid(tmp_path_factory):
    torch = pytest.importorskip("torch")
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp("grid")
    torch.manual_seed(411)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64, public_dim=561,
                                        enc_version=2, attention_heads=1, trunk_block="grid",
                                        trunk_layers=2, grid_channels=6, search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "grid.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2), "sees_hidden_hands": True})
    pkg = d / "grid.npz"
    export_cwv_numpy(ckpt, pkg)
    return net, str(ckpt), str(pkg)


def test_grid_package_reproduces_the_torch_trunk_value_softmax_and_policy_head(grid):
    torch = pytest.importorskip("torch")
    from shengji.rl.card_grid import grid_table
    net, _, pkg = grid
    model = load_cwv_numpy(pkg)
    assert model.trunk_block == "grid" and model.config.grid_channels == 6 and model.policy_head is True
    meta = json.loads(str(np.load(pkg)["metadata"].item()))
    assert meta["schema"] == PACKAGE_SCHEMA_V2
    assert meta["config"]["trunk_block"] == "grid" and meta["config"]["grid_channels"] == 6
    np.testing.assert_array_equal(np.load(pkg)["grid_table"], grid_table().astype(np.float32))
    rng = np.random.default_rng(411)
    public, world, persp = _inputs(rng, 24)
    assert len(set(map(tuple, np.argmax(public[:, 486:491], 1)[:, None] * 13 + np.argmax(public[:, 491:504], 1)[:, None]))) > 4, \
        "the witness must select several different index tables"
    flat = np.concatenate((public, world.reshape(24, -1), persp), axis=1)
    with torch.no_grad():
        want_p = torch.softmax(net.head_logits(net.features(torch.from_numpy(public), torch.from_numpy(world),
                                                            torch.from_numpy(persp)), "outcome"), 1).numpy()
        want_logits = net.policy_logits(net.features_flat(torch.from_numpy(flat))).numpy()
    np.testing.assert_allclose(model.probabilities(public, world, persp), want_p, rtol=2e-5, atol=2e-6)
    np.testing.assert_allclose(model.policy_log_odds(flat), want_logits, rtol=2e-5, atol=2e-6)
    # the gather is trump-dependent: moving the trump suit one-hot changes the features
    moved = public.copy()
    moved[:, 486:491] = np.roll(moved[:, 486:491], 1, axis=1)
    assert not np.allclose(model.probabilities(moved, world, persp), want_p)


def test_both_torch_window_implementations_match_the_package(grid):
    """GridTrunk reads the windows either as per-tap GEMMs or conv1d (host-dependent);
    the package must agree with both."""
    torch = pytest.importorskip("torch")
    net, _, pkg = grid
    model = load_cwv_numpy(pkg)
    rng = np.random.default_rng(7)
    public, world, persp = _inputs(rng, 6)
    got = model.probabilities(public, world, persp)
    for use_conv1d in (False, True):
        net.trunk.use_conv1d = use_conv1d
        try:
            with torch.no_grad():
                want = torch.softmax(net.head_logits(net.features(torch.from_numpy(public), torch.from_numpy(world),
                                                                  torch.from_numpy(persp)), "outcome"), 1).numpy()
        finally:
            net.trunk.use_conv1d = None
        np.testing.assert_allclose(got, want, rtol=2e-5, atol=2e-6)


def test_a_tampered_grid_table_is_refused(grid, tmp_path):
    _, _, pkg = grid
    z = dict(np.load(pkg))
    bad = dict(z)
    bad["grid_table"] = z["grid_table"].copy()
    bad["grid_table"][0, 0] = 55.0                      # past the appended pad column
    np.savez_compressed(tmp_path / "bad.npz", **bad)
    with pytest.raises(CWVNumpyError, match="grid_table"):
        load_cwv_numpy(tmp_path / "bad.npz")
    frac = dict(z)
    frac["grid_table"] = z["grid_table"].copy()
    frac["grid_table"][0, 0] = 0.5                      # not an index
    np.savez_compressed(tmp_path / "frac.npz", **frac)
    with pytest.raises(CWVNumpyError, match="grid_table"):
        load_cwv_numpy(tmp_path / "frac.npz")


def test_grid_metadata_must_name_its_channels_and_only_a_grid_may(grid, tmp_path):
    _, _, pkg = grid
    z = dict(np.load(pkg))
    meta = json.loads(str(z["metadata"].item()))
    hidden = dict(z)
    cfg = dict(meta["config"]); del cfg["grid_channels"]
    hidden["metadata"] = np.asarray(json.dumps({**meta, "config": cfg}, sort_keys=True))
    np.savez_compressed(tmp_path / "hidden.npz", **hidden)
    with pytest.raises(CWVNumpyError):
        load_cwv_numpy(tmp_path / "hidden.npz")
    with pytest.raises(CWVNumpyError, match="grid_channels"):
        CWVNumpyConfig(architecture="mlp", width=32, feedforward_width=64, public_dim=561, enc_version=2,
                       trunk_block="residual", trunk_layers=2, grid_channels=6).validate()
    with pytest.raises(CWVNumpyError, match="grid_channels"):
        CWVNumpyConfig(architecture="mlp", width=32, feedforward_width=64, public_dim=561, enc_version=2,
                       trunk_block="grid", trunk_layers=2).validate()


def test_grid_package_deep_copies_share_weights_and_the_table(grid):
    _, _, pkg = grid
    model = load_cwv_numpy(pkg)
    clone = copy.deepcopy(model)
    assert clone._weights is model._weights and clone._grid_slots is model._grid_slots
    assert clone._grid_slots.shape == (65, GRID_ROWS * GRID_COLS)
    assert not clone._grid_slots.flags.writeable, "the shared table must be immutable"
    with pytest.raises(ValueError):
        clone._grid_slots[0, 0] = 0
    assert clone.package_sha256 == model.package_sha256
