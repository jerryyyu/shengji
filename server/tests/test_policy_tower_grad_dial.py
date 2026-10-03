"""Policy tower with a trunk gradient dial (off by default).

``--policy-tower-layers N`` adds N policy-ONLY residual blocks between the shared trunk
and the 54 card logits; ``--policy-trunk-grad-scale A`` multiplies the policy loss's
gradient where it enters the trunk.  Witnesses, in the order of the PR's claims:

* defaults are the net, the loss, the training step and the package of before the option;
* the dial: A=0 leaves the trunk with no policy gradient, A=0.25 gives exactly a quarter
  of the A=1 gradient, the tower and policy head always get the full gradient, and the
  value gradient into the trunk does not depend on A;
* the value / search-mean heads never see the tower;
* export + NumPy inference: a tower package is its own schema (v3), reproduces the Torch
  policy scores, leaves the value probabilities untouched, and a pre-tower runtime refuses it;
* warm start: a towerless checkpoint loads into a tower net whose policy path starts as the
  source's function exactly; the run's config and receipt record the options.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
import torch

from shengji.ai import cwv_numpy
from shengji.ai.cwv_numpy import (CWVNumpyError, PACKAGE_SCHEMA_V2, PACKAGE_SCHEMA_V3,
                                  load_cwv_numpy)
from shengji.rl.value_model import (ValueModelConfig, ValueModelError, ValueNetwork,
                                    model_state_sha256)
from shengji.train import policy_prior as pp
from shengji.train import train_cwv
from shengji.train.policy_rows import policy_losses, scale_trunk_gradient
from shengji.train.train_cwv import apply_init, load_cwv_checkpoint
from tests.test_cwv_train import THIRDS, store_dir, records  # noqa: F401

WIDTH, FFW, DIN = 32, 64, 833
BASE = dict(architecture="mlp", width=WIDTH, history_layers=1, attention_heads=1,
            feedforward_width=FFW, public_dim=561, enc_version=2, trunk_block="residual",
            trunk_layers=2, search_head=True, policy_head=True)
TOWER = dict(policy_tower_layers=2, policy_tower_width=FFW)
PARITY = dict(rtol=2e-5, atol=2e-6)          # the tolerance of tests/test_cwv_numpy_joint.py


def _net(seed=11, **extra):
    torch.manual_seed(seed)
    return ValueNetwork(ValueModelConfig(**{**BASE, **extra}))


def _wake(net, seed=3):
    """Give the (identity-initialised) tower a real function, as training would."""
    gen = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        for block in net.policy_tower:
            block.down.weight.copy_(torch.randn(block.down.weight.shape, generator=gen) * 0.05)
            block.down.bias.copy_(torch.randn(block.down.bias.shape, generator=gen) * 0.05)
    return net


def _roots(n=24, seed=5, ballot=6, cards=3):
    rng = np.random.default_rng(seed)
    ball = rng.integers(0, 54, (n, ballot, cards)).astype(np.int64)
    ball[:, :, -1][rng.random((n, ballot)) < 0.4] = -1          # ragged actions
    mask = np.ones((n, ballot), bool)
    mask[:, -1] = rng.random(n) < 0.5                           # ragged ballots
    tgt = rng.integers(0, ballot - 1, n)
    tgt[:3] = -1                                                # rows with no ballot target
    return {"x": torch.from_numpy(rng.standard_normal((n, DIN)).astype(np.float32)),
            "y": torch.from_numpy((rng.random((n, 54)) < 0.06).astype(np.float32)),
            "ball": torch.from_numpy(ball), "mask": torch.from_numpy(mask),
            "tgt": torch.from_numpy(tgt)}


def _values(n=16, seed=9):
    rng = np.random.default_rng(seed)
    return (torch.from_numpy(rng.standard_normal((n, DIN)).astype(np.float32)),
            torch.from_numpy(rng.integers(0, 204, n)))


def _policy_grads(net, t, scale):
    net.zero_grad(set_to_none=True)
    bce, lw, _ = policy_losses(net, t, listwise_weight=1.0, trunk_grad_scale=scale)
    (bce + lw).backward()
    return {k: (None if p.grad is None else p.grad.clone()) for k, p in net.named_parameters()}


# ------------------------------------------------------------------ defaults

def test_defaults_build_the_net_and_payload_of_before_the_option():
    plain = ValueModelConfig(**BASE)
    assert not {"policy_tower_layers", "policy_tower_width"} & set(plain.payload())
    assert ValueModelConfig.from_payload(plain.payload()) == plain
    net = _net()
    assert not hasattr(net, "policy_tower")
    assert not any(k.startswith("policy_tower") for k in net.state_dict())
    # the legacy forward, written out: the head reads the trunk features directly
    x = _roots()["x"]
    assert torch.equal(net.policy_logits(net.features_flat(x)), net.policy_head(net.trunk(x)))

    tower_cfg = ValueModelConfig(**{**BASE, **TOWER})
    assert tower_cfg.payload()["policy_tower_layers"] == 2
    assert ValueModelConfig.from_payload(tower_cfg.payload()) == tower_cfg
    for bad in (dict(policy_tower_layers=1, policy_tower_width=FFW, policy_head=False),
                dict(policy_tower_layers=0, policy_tower_width=FFW),
                dict(policy_tower_layers=1, policy_tower_width=WIDTH - 1),
                dict(policy_tower_layers=-1, policy_tower_width=0)):
        with pytest.raises(ValueModelError):
            ValueModelConfig(**{**BASE, **bad}).validate()


def test_the_tower_is_built_last_so_every_other_weight_draws_the_same_init():
    """Initialisation order / RNG consumption: the tower net's trunk, value heads and policy
    head are the towerless net's tensors for the same seed, and the tower itself starts as an
    exact identity on the policy path."""
    plain, tower = _net(seed=4), _net(seed=4, **TOWER)
    a, b = plain.state_dict(), tower.state_dict()
    assert set(b) - set(a) == {f"policy_tower.{i}.{part}.{kind}" for i in range(2)
                               for part in ("norm", "up", "down") for kind in ("weight", "bias")}
    assert set(a) <= set(b) and all(torch.equal(a[k], b[k]) for k in a)
    assert all(not b[f"policy_tower.{i}.down.{kind}"].any() for i in range(2) for kind in ("weight", "bias"))
    assert b["policy_tower.0.up.weight"].any()
    x = _roots()["x"]
    plain.eval(); tower.eval()
    with torch.no_grad():
        assert torch.equal(plain.policy_logits(plain.features_flat(x)),
                           tower.policy_logits(tower.features_flat(x)))


def test_default_training_steps_are_the_legacy_steps_to_the_bit():
    """Three AdamW steps of value CE + policy loss: the trainer's ``policy_losses`` at the
    defaults against the pre-option computation written out by hand (head on the trunk
    features, BCE + listwise CE).  Same seed, same batches -> identical parameters."""
    t = _roots()
    vx, vy = _values()

    def run(legacy: bool):
        net = _net(seed=21)
        net.train()
        optim = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-2)
        losses = []
        for _ in range(3):
            ce = torch.nn.functional.cross_entropy(net.head_logits(net.features_flat(vx), "outcome"), vy)
            if legacy:
                logits = net.policy_head(net.trunk(t["x"]))
                bce = torch.nn.functional.binary_cross_entropy_with_logits(logits, t["y"])
                lw = pp.listwise_loss(logits, t["ball"], t["mask"], t["tgt"])
            else:
                bce, lw, _ = policy_losses(net, t, listwise_weight=1.0)
            total = ce + 1.0 * (bce + 1.0 * lw)
            optim.zero_grad(set_to_none=True)
            total.backward()
            optim.step()
            losses.append(total.detach().clone())
        return net, losses

    (new, new_losses), (old, old_losses) = run(False), run(True)
    assert all(torch.equal(a, b) for a, b in zip(new_losses, old_losses))
    assert model_state_sha256(new) == model_state_sha256(old)
    # and the explicit default is the same code path
    net = _net(seed=21)
    a = policy_losses(net, t, listwise_weight=1.0)
    b = policy_losses(net, t, listwise_weight=1.0, trunk_grad_scale=1.0)
    assert all(torch.equal(u, v) for u, v in zip(a, b))


def test_default_config_records_nothing_new(tmp_path):
    kw = dict(data=[str(tmp_path)], arch="mlp", hidden=32, encoder_version=2)
    base = train_cwv.build_config(policy_head=True, policy_rows=str(tmp_path / "rows"), **kw)
    assert not [k for k in base if "tower" in k or "grad_scale" in k]
    assert not [k for k in base["model_config"] if "tower" in k]
    on = train_cwv.build_config(policy_head=True, policy_rows=str(tmp_path / "rows"),
                                policy_tower_layers=2, policy_trunk_grad_scale=0.25, **kw)
    assert on["policy_tower_layers"] == 2 and on["policy_trunk_grad_scale"] == 0.25
    # the default tower width is the trunk blocks' inner width (--hidden)
    assert on["policy_tower_width"] == 32 and on["model_config"]["policy_tower_width"] == 32
    assert on["model_config"]["policy_tower_layers"] == 2
    # everything else in the config is what the default run records
    assert {k: v for k, v in on.items() if k in base and k != "model_config"} \
        == {k: v for k, v in base.items() if k != "model_config"}
    assert train_cwv.config_sha256(on) != train_cwv.config_sha256(base)
    wide = train_cwv.build_config(policy_head=True, policy_rows=str(tmp_path / "rows"),
                                  policy_tower_layers=1, policy_tower_width=48, **kw)
    assert wide["model_config"]["policy_tower_width"] == 48 and "policy_trunk_grad_scale" not in wide
    for bad, match in ((dict(policy_tower_layers=1), "need --policy-head"),
                       (dict(policy_trunk_grad_scale=0.5), "need --policy-head"),
                       (dict(policy_head=True, policy_rows="r", policy_tower_width=48), "needs --policy-tower-layers"),
                       (dict(policy_head=True, policy_rows="r", policy_trunk_grad_scale=1.5), r"in \[0, 1\]"),
                       (dict(policy_head=True, policy_rows="r", policy_trunk_grad_scale=-0.1), r"in \[0, 1\]"),
                       (dict(policy_head=True, policy_rows="r", policy_detach=True,
                             policy_trunk_grad_scale=0.25), "give one of them")):
        with pytest.raises(train_cwv.TrainError, match=match):
            train_cwv.build_config(**bad, **kw)


# ---------------------------------------------------------------------- dial

def test_the_dial_keeps_the_forward_values_bit_for_bit():
    f = torch.randn(7, WIDTH, requires_grad=True)
    assert scale_trunk_gradient(f, 1.0) is f
    for a in (0.0, 0.25, 0.3, 0.999):
        assert torch.equal(scale_trunk_gradient(f, a), f)
    (g,) = torch.autograd.grad(scale_trunk_gradient(f, 0.25).sum(), f)
    assert torch.equal(g, torch.full_like(f, 0.25))
    assert not scale_trunk_gradient(f, 0.0).requires_grad
    with pytest.raises(ValueError):
        scale_trunk_gradient(f, 1.01)


@pytest.mark.parametrize("tower", [True, False])
def test_policy_gradient_into_the_trunk_is_scaled_and_the_policy_path_is_not(tower):
    net = _wake(_net(**TOWER)) if tower else _net()
    net.train()
    t = _roots()
    full, quarter, zero = (_policy_grads(net, t, a) for a in (1.0, 0.25, 0.0))
    trunk = [k for k in full if k.startswith("trunk.")]
    policy = [k for k in full if k.startswith(("policy_tower.", "policy_head."))]
    assert trunk and policy and (not tower or any(k.startswith("policy_tower.") for k in policy))
    # A = 0: the trunk gets nothing from the policy loss; the policy path trains
    assert all(zero[k] is None or not zero[k].any() for k in trunk)
    assert all(zero[k] is not None and zero[k].any() for k in policy)
    # A = 0.25: exactly a quarter of the A = 1 trunk gradient (same weights, same batch)
    assert all(full[k].any() for k in trunk)
    for k in trunk:
        np.testing.assert_allclose(quarter[k].numpy(), 0.25 * full[k].numpy(), rtol=1e-6, atol=0)
    # the tower and the policy output get the FULL gradient at every A
    for k in policy:
        assert torch.equal(quarter[k], full[k]) and torch.equal(zero[k], full[k]), k
    # the policy loss never reaches the value heads
    assert all(g[k] is None for g in (full, quarter, zero) for k in g if k.startswith(("head.", "search_head.")))
    # and the loss itself does not depend on A
    losses = [policy_losses(net, t, listwise_weight=1.0, trunk_grad_scale=a)[:2] for a in (1.0, 0.25, 0.0)]
    assert all(torch.equal(l[0], losses[0][0]) and torch.equal(l[1], losses[0][1]) for l in losses)
    # --policy-detach is A = 0
    net.zero_grad(set_to_none=True)
    bce, lw, _ = policy_losses(net, t, listwise_weight=1.0, detach=True)
    (bce + lw).backward()
    assert all(p.grad is None for k, p in net.named_parameters() if k.startswith("trunk."))


def test_value_gradients_into_the_trunk_do_not_depend_on_the_dial():
    net = _wake(_net(**TOWER))
    net.train()
    t = _roots()
    vx, vy = _values()

    def value_loss():
        feats = net.features_flat(vx)
        return (torch.nn.functional.cross_entropy(net.head_logits(feats, "outcome"), vy)
                + torch.nn.functional.cross_entropy(net.head_logits(feats, "search-mean"), vy))

    net.zero_grad(set_to_none=True)
    value_loss().backward()
    value_only = {k: (None if p.grad is None else p.grad.clone()) for k, p in net.named_parameters()}
    # the value losses never touch the tower or the policy head
    assert all(value_only[k] is None for k in value_only if k.startswith(("policy_tower.", "policy_head.")))
    trunk = [k for k in value_only if k.startswith("trunk.")]
    policy_full = _policy_grads(net, t, 1.0)
    for a in (0.0, 0.25, 1.0):
        net.zero_grad(set_to_none=True)
        bce, lw, _ = policy_losses(net, t, listwise_weight=1.0, trunk_grad_scale=a)
        (value_loss() + bce + lw).backward()
        for k in trunk:
            got = net.get_parameter(k).grad.numpy()
            want = value_only[k].numpy() + a * policy_full[k].numpy()
            np.testing.assert_allclose(got, want, rtol=2e-5, atol=1e-7, err_msg=k)
            if a == 0.0:        # the stop-gradient run's trunk gradient IS the value gradient
                assert torch.equal(net.get_parameter(k).grad, value_only[k]), k
        for k in ("head.weight", "search_head.weight"):
            assert torch.equal(net.get_parameter(k).grad, value_only[k]), k


def test_the_value_heads_never_see_the_tower():
    tower = _wake(_net(seed=4, **TOWER))
    plain = _net(seed=4)
    plain.load_state_dict({k: v for k, v in tower.state_dict().items() if not k.startswith("policy_tower.")})
    tower.eval(); plain.eval()
    rng = np.random.default_rng(2)
    public = torch.from_numpy(rng.standard_normal((6, 561)).astype(np.float32))
    world = torch.from_numpy((rng.integers(0, 3, (6, 5, 54)) * 0.5).astype(np.float32))
    persp = torch.from_numpy(np.eye(2, dtype=np.float32)[rng.integers(0, 2, 6)])
    with torch.no_grad():
        feats_t, feats_p = tower.features(public, world, persp), plain.features(public, world, persp)
        assert torch.equal(feats_t, feats_p)
        for head in ("outcome", "search-mean"):
            assert torch.equal(tower.head_logits(feats_t, head), plain.head_logits(feats_p, head))
        # while the policy path does read it
        assert not torch.equal(tower.policy_logits(feats_t), plain.policy_logits(feats_p))


# -------------------------------------------------------- export + inference

@pytest.fixture(scope="module")
def packages(tmp_path_factory):
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    d = tmp_path_factory.mktemp("tower")
    tower = _wake(_net(seed=4, **TOWER))
    plain = _net(seed=4)
    plain.load_state_dict({k: v for k, v in tower.state_dict().items() if not k.startswith("policy_tower.")})
    out = {}
    for name, net in (("tower", tower), ("plain", plain)):
        net.eval()
        ckpt, pkg = d / f"{name}.pt", d / f"{name}.npz"
        save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2), "sees_hidden_hands": True})
        export_cwv_numpy(ckpt, pkg)
        out[name] = (net, str(ckpt), str(pkg))
    return out


def _flat(n=9, seed=5):
    rng = np.random.default_rng(seed)
    public = rng.standard_normal((n, 561)).astype(np.float32)
    world = (rng.integers(0, 3, (n, 5, 54)) * 0.5).astype(np.float32)
    persp = np.eye(2, dtype=np.float32)[rng.integers(0, 2, n)]
    return public, world, persp, np.concatenate((public, world.reshape(n, -1), persp), axis=1)


def test_a_towerless_export_is_the_package_of_before_the_option(packages):
    """Array-level identity (an .npz's bytes carry zip timestamps): the key set, every array,
    the schema and the config keys of a towerless joint package, enumerated here by hand."""
    net, _ckpt, pkg = packages["plain"]
    z = np.load(pkg)
    legacy = {"head_weight": "search_head.weight", "head_bias": "search_head.bias",
              "stem_weight": "trunk.0.weight", "stem_bias": "trunk.0.bias",
              "final_norm_weight": "trunk.3.weight", "final_norm_bias": "trunk.3.bias",
              "policy_weight": "policy_head.weight", "policy_bias": "policy_head.bias"}
    for i in range(2):
        for part in ("norm", "up", "down"):
            for kind in ("weight", "bias"):
                legacy[f"block{i}_{part}_{kind}"] = f"trunk.{i + 1}.{part}.{kind}"
    meta = json.loads(str(z["metadata"].item()))
    head = meta["metadata"]["exported_value_head"]
    if head == "outcome":
        legacy.update(head_weight="head.weight", head_bias="head.bias")
    assert set(z.files) == set(legacy) | {"metadata"}
    state = net.state_dict()
    for dst, src in legacy.items():
        assert z[dst].dtype == np.float32 and np.array_equal(z[dst], state[src].numpy()), dst
    assert meta["schema"] == PACKAGE_SCHEMA_V2
    assert set(meta["config"]) == {"architecture", "width", "feedforward_width", "public_dim", "enc_version",
                                   "trunk_block", "trunk_layers", "policy_head"}
    assert set(meta) == {"schema", "config", "metadata", "original_checkpoint_sha256"}


def test_a_tower_package_reproduces_the_torch_policy_scores_and_leaves_the_value_alone(packages):
    net, _ckpt, pkg = packages["tower"]
    _plain_net, _pckpt, plain_pkg = packages["plain"]
    model, plain = load_cwv_numpy(pkg), load_cwv_numpy(plain_pkg)
    meta = json.loads(str(np.load(pkg)["metadata"].item()))
    assert meta["schema"] == PACKAGE_SCHEMA_V3
    assert meta["config"]["policy_tower_layers"] == 2 and meta["config"]["policy_tower_width"] == FFW
    assert model.config.policy_tower_layers == 2 and plain.config.policy_tower_layers == 0
    assert {k for k in np.load(pkg).files if k.startswith("policy_tower")} \
        == {f"policy_tower{i}_{part}_{kind}" for i in range(2) for part in ("norm", "up", "down")
            for kind in ("weight", "bias")}
    public, world, persp, flat = _flat()
    with torch.no_grad():
        want = net.policy_logits(net.features_flat(torch.from_numpy(flat))).numpy()
    np.testing.assert_allclose(model.policy_log_odds(flat), want, **PARITY)
    # the tower matters: the towerless package (same trunk, same head) scores differently
    assert np.abs(plain.policy_log_odds(flat) - want).max() > 1e-3
    # the value path is the towerless package's, exactly
    assert np.array_equal(model.probabilities(public, world, persp), plain.probabilities(public, world, persp))
    # the admission's action scores (card log-odds summed per action) agree as well
    from shengji.train.cwv_prior_admission import action_scores
    cards = list(pp.CARD_INDEX)
    actions = [[cards[0]], [cards[3], cards[3]], [cards[7], cards[8], cards[20]]]
    np.testing.assert_allclose(action_scores(model.policy_log_odds(flat), actions),
                               action_scores(want, actions), rtol=2e-5, atol=2e-5)
    # the package survives the IPC / snapshot paths
    import copy
    import pickle
    for clone in (copy.deepcopy(model), pickle.loads(pickle.dumps(model))):
        assert np.array_equal(clone.policy_log_odds(flat), model.policy_log_odds(flat))


def test_a_runtime_from_before_the_tower_refuses_the_package(packages, tmp_path, monkeypatch):
    _net_, _ckpt, pkg = packages["tower"]
    # the runtime of before this change knew two schemas
    monkeypatch.setattr(cwv_numpy, "PACKAGE_SCHEMAS", (cwv_numpy.PACKAGE_SCHEMA, PACKAGE_SCHEMA_V2))
    with pytest.raises(CWVNumpyError, match="invalid package metadata schema"):
        load_cwv_numpy(pkg)
    monkeypatch.undo()
    load_cwv_numpy(pkg)

    def rewrite(name, edit_meta=None, drop=()):
        z = dict(np.load(pkg))
        meta = json.loads(str(z["metadata"].item()))
        if edit_meta:
            edit_meta(meta)
        z["metadata"] = np.asarray(json.dumps(meta, sort_keys=True))
        np.savez_compressed(tmp_path / name, **{k: v for k, v in z.items() if k not in drop})
        return tmp_path / name

    # relabelled as v2 (what a pre-tower runtime accepts): refused, never served headless-of-tower
    with pytest.raises(CWVNumpyError, match="v3 package feature"):
        load_cwv_numpy(rewrite("v2.npz", lambda m: m.update(schema=PACKAGE_SCHEMA_V2)))
    # a v2 package with the tower keys stripped from the config: the arrays give it away
    def strip(m):
        m["schema"] = PACKAGE_SCHEMA_V2
        for k in ("policy_tower_layers", "policy_tower_width"):
            del m["config"][k]
    with pytest.raises(CWVNumpyError, match="schema drift"):
        load_cwv_numpy(rewrite("stripped.npz", strip))
    # a tower package missing a tower array
    with pytest.raises(CWVNumpyError, match="schema drift"):
        load_cwv_numpy(rewrite("short.npz", drop=("policy_tower1_down_bias",)))
    # v3 names a tower and nothing else
    _p, _c, plain_pkg = packages["plain"]
    z = dict(np.load(plain_pkg))
    meta = json.loads(str(z["metadata"].item())); meta["schema"] = PACKAGE_SCHEMA_V3
    z["metadata"] = np.asarray(json.dumps(meta, sort_keys=True))
    np.savez_compressed(tmp_path / "v3plain.npz", **z)
    with pytest.raises(CWVNumpyError, match="v3 package feature"):
        load_cwv_numpy(tmp_path / "v3plain.npz")
    # a tower without its policy head is not a configuration
    with pytest.raises(CWVNumpyError):
        cwv_numpy.CWVNumpyConfig(architecture="mlp", width=WIDTH, feedforward_width=FFW, public_dim=561,
                                 enc_version=2, trunk_block="residual", trunk_layers=2,
                                 policy_tower_layers=1, policy_tower_width=FFW).validate()


def _prior_log_odds(path):
    """The served prior path, as `pv_search_policy.NumpyPriorPredict` drives it."""
    from types import SimpleNamespace

    from shengji.train.cwv_prior_admission import (CWVPriorAdmissionBot, load_prior_checked,
                                                   prior_encoder_version)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    kind, model, payload = load_prior_checked(str(path), sha)
    assert prior_encoder_version(kind, model, payload) == 2
    holder = SimpleNamespace(_prior_kind=kind, _prior_net=model, _prior_payload=payload)
    return kind, CWVPriorAdmissionBot._prior_log_odds(holder, _flat()[3])


def test_the_prior_admission_reads_the_tower_from_the_served_package(packages):
    """`load_prior_checked` / `prior_encoder_version` / `_prior_log_odds` need no change:
    the served kind (``joint-numpy``) scores through the tower."""
    net, _ckpt, pkg = packages["tower"]
    kind, got = _prior_log_odds(pkg)
    assert kind == "joint-numpy"
    with torch.no_grad():
        want = net.policy_logits(net.features_flat(torch.from_numpy(_flat()[3]))).numpy()
    np.testing.assert_allclose(got, want, **PARITY)


# ---------------------------------------------------------------- warm start

@pytest.fixture(scope="module")
def trained(store_dir, tmp_path_factory):  # noqa: F811
    d = tmp_path_factory.mktemp("towerwarm")
    rows = d / "rows"
    summary = pp.extract(rows, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    assert summary["rows"] > 20
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10,
              hidden=32, trunk_layers=2, trunk_block="residual", log=None, cache_workers=1, eval_workers=1,
              bench_batch=32, val_rank_records=50, encoder_version=2, policy_head=True,
              policy_rows=str(rows), policy_batch_fraction=1.0, **THIRDS)
    base = train_cwv.train(out=d / "base", **kw)
    return d, kw, base


def test_a_towerless_checkpoint_warm_starts_a_tower_whose_policy_path_is_the_sources(trained):
    d, _kw, base = trained
    assert "tower" not in base["policy_head"] and "policy_trunk_grad_scale" not in base["config"]
    path = str(d / "base" / "best.pt")
    source, meta, _aux = load_cwv_checkpoint(path, "cpu")
    assert "policy_tower_layers" not in meta["model_config"]
    mc = {**meta["model_config"], "policy_tower_layers": 2, "policy_tower_width": 48}
    config = {"arch": meta["arch"], "model_config": mc}
    torch.manual_seed(99)
    model = ValueNetwork(ValueModelConfig.from_payload(dict(mc)))
    info = apply_init(model, None, path, config, torch.device("cpu"))
    assert info["policy_tower_fresh"] is True and info["policy_tower_identity_init"] is True
    assert info["policy_head_fresh"] is False and info["trunk_blocks_added"] == 0
    src, dst = source.state_dict(), model.state_dict()
    assert all(torch.equal(src[k], dst[k]) for k in src)                 # the policy head included
    source.eval(); model.eval()
    x = torch.randn(16, DIN)
    with torch.no_grad():
        assert torch.equal(source.policy_logits(source.features_flat(x)), model.policy_logits(model.features_flat(x)))
        assert torch.equal(source.head_logits(source.features_flat(x)), model.head_logits(model.features_flat(x)))
    # the tower trains from the identity: one policy step moves its output projection,
    # the next one (now that the projection is non-zero) reaches the rest of the block
    optim = torch.optim.SGD(model.parameters(), lr=0.1)
    model.train()
    before_up = model.state_dict()["policy_tower.0.up.weight"].clone()
    for _ in range(2):
        optim.zero_grad(set_to_none=True)
        model.policy_logits(model.features_flat(x)).square().mean().backward()
        optim.step()
    assert model.state_dict()["policy_tower.0.down.weight"].any()
    assert not torch.equal(model.state_dict()["policy_tower.0.up.weight"], before_up)

    # a towerless net cannot take a tower checkpoint, and two different towers do not mix
    plain = ValueNetwork(ValueModelConfig.from_payload(dict(meta["model_config"])))
    tower_meta = {**meta, "model_config": mc}
    with pytest.raises(train_cwv.TrainError):
        apply_init(plain, None, path, {"arch": meta["arch"], "model_config": meta["model_config"]},
                   torch.device("cpu"), loaded=(model, tower_meta, None))
    other = {**mc, "policy_tower_layers": 1}
    with pytest.raises(train_cwv.TrainError):
        apply_init(ValueNetwork(ValueModelConfig.from_payload(dict(other))), None, path,
                   {"arch": meta["arch"], "model_config": other}, torch.device("cpu"),
                   loaded=(model, tower_meta, None))


def test_the_trainer_runs_the_tower_with_the_dial_and_records_both(trained, tmp_path):
    from scripts.export_cwv_numpy import export_cwv_numpy
    d, kw, base = trained
    run = train_cwv.train(out=tmp_path / "tower", init=str(d / "base" / "best.pt"), init_exclude_exposed=True,
                          policy_tower_layers=2, policy_trunk_grad_scale=0.25, **kw)
    assert run["config"]["policy_tower_layers"] == 2 and run["config"]["policy_tower_width"] == 32
    assert run["config"]["policy_trunk_grad_scale"] == 0.25
    assert run["model"]["config"]["policy_tower_layers"] == 2
    assert run["init"]["policy_tower_fresh"] is True
    block = run["policy_head"]["tower"]
    assert block["layers"] == 2 and block["width"] == 32 and block["trunk_grad_scale"] == 0.25
    assert run["config_sha256"] != base["config_sha256"]
    assert run["epochs"][0]["train"]["policy_rows"] > 0
    model, meta, _ = load_cwv_checkpoint(str(tmp_path / "tower" / "best.pt"), "cpu")
    assert meta["config"]["policy_trunk_grad_scale"] == 0.25 and meta["policy_head"]["tower"]["layers"] == 2
    assert model.state_dict()["policy_tower.0.down.weight"].any()        # the tower trained
    # the trained checkpoint exports and serves its tower
    pkg = tmp_path / "tower.npz"
    export_cwv_numpy(tmp_path / "tower" / "best.pt", pkg)
    served = load_cwv_numpy(pkg)
    assert served.config.policy_tower_layers == 2
    _public, _world, _persp, flat = _flat()
    with torch.no_grad():
        want = model.policy_logits(model.features_flat(torch.from_numpy(flat))).numpy()
    np.testing.assert_allclose(served.policy_log_odds(flat), want, **PARITY)
    # both prior kinds (the Torch checkpoint and the served package) score through the tower
    kind_t, torch_scores = _prior_log_odds(tmp_path / "tower" / "best.pt")
    kind_n, numpy_scores = _prior_log_odds(pkg)
    assert (kind_t, kind_n) == ("joint", "joint-numpy")
    np.testing.assert_allclose(torch_scores, want, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(numpy_scores, want, **PARITY)
    # a tower run continues from a tower checkpoint of the same shape (strict load)
    again = train_cwv.train(out=tmp_path / "again", init=str(tmp_path / "tower" / "best.pt"),
                            init_exclude_exposed=True, policy_tower_layers=2, policy_trunk_grad_scale=0.0, **kw)
    assert "policy_tower_fresh" not in again["init"] and again["config"]["policy_trunk_grad_scale"] == 0.0
