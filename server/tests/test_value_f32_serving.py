"""``SHENGJI_PV_VALUE_F32``: the float32 forward of the complete-world value and prior packages.

Off (unset or ``0``) the registry gains nothing and every model forwards exactly as before: the
float64 forward is checked bit for bit against the reference arithmetic below.  On, each pv-search
name gains a ``-vf32`` twin whose bot holds float32 views of its value and prior packages; the
views share the immutable weights, survive deep copies and pickles, and stay within float32
rounding of the float64 forward.  The package tests build release 55 as the server does on the
hash-pinned packages and fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1``.
"""
import copy
import pickle

import numpy as np
import pytest

from shengji.ai import cwv_numpy as cn
from shengji.ai.cwv_numpy import CWVNumpyConfig, CWVNumpyError, CWVNumpyMLP
from shengji.train import value_f32_serving as vf
from shengji.train.pv_search_policy import PVSearchPolicyError


def _model(trunk_block="residual", policy_tower_layers=0, seed=3):
    config = CWVNumpyConfig(architecture="mlp", width=24, feedforward_width=48, public_dim=565,
                            enc_version=7, trunk_block=trunk_block, trunk_layers=2 if trunk_block == "plain" else 3,
                            policy_head=True, policy_tower_layers=policy_tower_layers,
                            policy_tower_width=32 if policy_tower_layers else 0)
    rng = np.random.default_rng(seed)
    weights = {k: (rng.normal(size=shape) * 0.2).astype(np.float32)
               for k, shape in cn.expected_arrays(config).items()}
    for k in weights:
        if k.endswith("norm_weight"):
            weights[k] = (1.0 + weights[k]).astype(np.float32)
    return CWVNumpyMLP(config, weights)


def _batch(model, n=33, seed=5):
    rng = np.random.default_rng(seed)
    public = (rng.random((n, model.public_dim)) < 0.2).astype(np.float32)
    world = (rng.random((n, cn.WORLD_RECEIVERS, cn.N_CARDS)) < 0.25).astype(np.float32)
    perspective = rng.random((n, cn.PERSPECTIVE_DIM)).astype(np.float32)
    flat = np.concatenate((public, world.reshape(n, -1), perspective), axis=1)
    return public, world, perspective, flat


def _reference(model, x, head):
    """The float64 residual forward on float64 copies of the package arrays, as written before the
    float32 view existed."""
    w = {k: np.asarray(v, dtype=np.float64) for k, v in model._weights.items()}
    x = np.asarray(x).astype(np.float64)
    with np.errstate(all="ignore"):
        h = x @ w["stem_weight"].T + w["stem_bias"]
        for i in range(model.config.trunk_layers):
            n = cn._layer_norm(h, w[f"block{i}_norm_weight"], w[f"block{i}_norm_bias"])
            n = np.maximum(n @ w[f"block{i}_up_weight"].T + w[f"block{i}_up_bias"], 0.0)
            h = h + (n @ w[f"block{i}_down_weight"].T + w[f"block{i}_down_bias"])
        h = np.maximum(cn._layer_norm(h, w["final_norm_weight"], w["final_norm_bias"]), 0.0)
        if head == "policy":
            for i in range(model.config.policy_tower_layers):
                n = cn._layer_norm(h, w[f"policy_tower{i}_norm_weight"], w[f"policy_tower{i}_norm_bias"])
                n = np.maximum(n @ w[f"policy_tower{i}_up_weight"].T + w[f"policy_tower{i}_up_bias"], 0.0)
                h = h + (n @ w[f"policy_tower{i}_down_weight"].T + w[f"policy_tower{i}_down_bias"])
            return h @ w["policy_weight"].T + w["policy_bias"]
        logits = h @ w["head_weight"].T + w["head_bias"]
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    probs = np.exp(shifted)
    return probs / np.sum(probs, axis=1, keepdims=True)


@pytest.mark.parametrize("tower", [0, 2])
def test_the_float64_forward_is_the_reference_bit_for_bit(tower):
    model = _model(policy_tower_layers=tower)
    public, world, perspective, flat = _batch(model)
    assert model.compute_f32 is False
    probs = model.probabilities(public, world, perspective)
    assert probs.dtype == np.float64
    assert np.array_equal(probs, _reference(model, flat, "value"))
    logits = model.policy_log_odds(flat)
    assert logits.dtype == np.float64
    assert np.array_equal(logits, _reference(model, flat, "policy"))


@pytest.mark.parametrize("tower", [0, 2])
def test_the_float32_view_shares_the_weights_and_stays_within_float32_rounding(tower):
    model = _model(policy_tower_layers=tower)
    public, world, perspective, flat = _batch(model)
    before = model.probabilities(public, world, perspective)
    view = model.as_float32()
    assert view is not model and view.compute_f32 is True and model.compute_f32 is False
    assert view._weights is model._weights and view.config is model.config
    assert view._trunk(flat.astype(np.float32)).dtype == np.float32
    probs = view.probabilities(public, world, perspective)
    logits = view.policy_log_odds(flat)
    assert probs.dtype == np.float64 and logits.dtype == np.float64
    assert np.allclose(probs.sum(axis=1), 1.0)
    assert np.max(np.abs(probs - before)) < 1e-5
    assert np.max(np.abs(logits - model.policy_log_odds(flat))) < 1e-4
    assert not np.array_equal(probs, before)          # the view does forward in float32
    assert np.array_equal(model.probabilities(public, world, perspective), before)
    for clone in (copy.deepcopy(view), pickle.loads(pickle.dumps(view))):
        assert clone.compute_f32 is True
        assert np.array_equal(clone.probabilities(public, world, perspective), probs)
    for clone in (copy.deepcopy(model), pickle.loads(pickle.dumps(model))):
        assert clone.compute_f32 is False
    assert view.as_float32().compute_f32 is True


def test_only_the_residual_trunk_has_a_float32_view():
    with pytest.raises(CWVNumpyError, match="residual trunk only"):
        _model("plain").as_float32()


def test_the_flag_is_off_unless_one_and_refuses_anything_else():
    assert vf.value_f32({}) is False
    assert vf.value_f32({vf.FLAG_KEY: ""}) is False
    assert vf.value_f32({vf.FLAG_KEY: "0"}) is False
    assert vf.value_f32({vf.FLAG_KEY: "1"}) is True
    with pytest.raises(PVSearchPolicyError, match="must be 0 or 1"):
        vf.value_f32({vf.FLAG_KEY: "true"})


class _Predict:
    def __init__(self, net):
        self._prior_net = net


class _Evaluator:
    def __init__(self, model):
        self.model = model


class _Bot:
    def __init__(self, name):
        self.policy_name = name
        self.evaluator = _Evaluator(_model(seed=11))
        self.predict = _Predict(_model(seed=12))


def test_flag_off_registers_nothing_and_on_registers_a_twin_per_pv_search_name():
    entries = {"pv-search-abc": lambda **kw: _Bot("pv-search-abc"), "heuristic": lambda **kw: None}
    assert vf.value_f32_registry_entries(entries, {}) == {}
    assert vf.value_f32_registry_entries(entries, {vf.FLAG_KEY: "0"}) == {}
    twins = vf.value_f32_registry_entries(entries, {vf.FLAG_KEY: "1"})
    assert set(twins) == {"pv-search-abc-vf32"}
    bot = twins["pv-search-abc-vf32"]()
    assert bot.policy_name == "pv-search-abc-vf32" and bot.value_f32 is True
    assert bot.evaluator.model.compute_f32 and bot.predict._prior_net.compute_f32
    wrong = {"pv-search-abc": lambda **kw: _Bot("pv-search-other")}
    with pytest.raises(PVSearchPolicyError, match="expected"):
        vf.value_f32_registry_entries(wrong, {vf.FLAG_KEY: "1"})["pv-search-abc-vf32"]()


def test_install_leaves_the_shared_models_unchanged():
    bot = _Bot("pv-search-x")
    value, prior = bot.evaluator.model, bot.predict._prior_net
    vf.install(bot)
    assert bot.evaluator.model is not value and bot.predict._prior_net is not prior
    assert value.compute_f32 is False and prior.compute_f32 is False
    assert bot.evaluator.model._weights is value._weights
    bot.evaluator.model = object()
    with pytest.raises(PVSearchPolicyError, match="not a complete-world NumPy package"):
        vf.install(bot)


# The served bot on the hash-pinned packages.

from test_release50_fly_config import release50_packages  # noqa: E402,F401
from test_release53_fly_config import served_bot  # noqa: E402
from test_release55_fly_config import RELEASE55, release55_pair  # noqa: E402,F401
from test_release46_fly_config import fly_env  # noqa: E402
from test_unified_serving import served_functions  # noqa: E402,F401
import r50_flag_positions as fixed  # noqa: E402

PLAY_POSITIONS = fixed.POSITIONS[:4]


def _walk_models(bot):
    """Every CWVNumpyMLP reachable from ``bot``'s attributes."""
    import types
    seen, found = set(), []

    def walk(o, depth):
        if id(o) in seen or depth > 10:
            return
        seen.add(id(o))
        if isinstance(o, CWVNumpyMLP):
            found.append(o)
            return
        if isinstance(o, (str, bytes, int, float, bool, type(None), np.ndarray, types.ModuleType, type)):
            return
        if isinstance(o, (dict, types.MappingProxyType)):
            items = list(o.values())
        elif isinstance(o, (list, tuple, set, frozenset)):
            items = list(o)
        elif hasattr(o, "__dict__"):
            items = list(vars(o).values())
        else:
            return
        for v in items:
            walk(v, depth + 1)
    walk(bot, 0)
    return found


def test_flag_off_the_served_registry_and_bot_are_unchanged(
        release50_packages, release55_pair, monkeypatch, served_functions):
    from shengji.ai import registry
    env = fly_env()
    assert vf.FLAG_KEY not in env
    name, bot = served_bot(release50_packages, release55_pair, monkeypatch, env=env)
    assert name == bot.policy_name == RELEASE55
    assert not any(k.endswith(vf.SUFFIX) for k in registry.REGISTRY)
    assert not hasattr(bot, "value_f32")
    models = _walk_models(bot)
    assert len(models) == 2 and not any(m.compute_f32 for m in models)


def test_flag_on_the_twin_binds_float32_views_and_the_base_name_is_unchanged(
        release50_packages, release55_pair, monkeypatch, served_functions):
    env = {**fly_env(), vf.FLAG_KEY: "1"}
    base_name, base = served_bot(release50_packages, release55_pair, monkeypatch, env=env)
    assert base_name == RELEASE55 and not hasattr(base, "value_f32")
    assert not any(m.compute_f32 for m in _walk_models(base))
    env = {**env, "SHENGJI_BOT": RELEASE55 + vf.SUFFIX}
    name, twin = served_bot(release50_packages, release55_pair, monkeypatch, env=env)
    assert name == twin.policy_name == RELEASE55 + vf.SUFFIX and twin.value_f32 is True
    models = _walk_models(twin)
    assert len(models) == 2 and all(m.compute_f32 for m in models)
    assert {m.package_sha256 for m in models} == {m.package_sha256 for m in _walk_models(base)}
    assert all(m.compute_f32 for m in _walk_models(copy.deepcopy(twin)))
    assert not any(m.compute_f32 for m in _walk_models(base))


def test_flag_on_the_twin_plays_the_served_cards_at_fixed_positions(
        release50_packages, release55_pair, monkeypatch, served_functions):
    env = {**fly_env(), vf.FLAG_KEY: "1"}
    _, base = served_bot(release50_packages, release55_pair, monkeypatch, env=env, seed=fixed.SEED)
    fixed.lift(base)
    for key, trick, pos in PLAY_POSITIONS:
        f64 = copy.deepcopy(base)
        f32 = vf.install(copy.deepcopy(base))
        served = fixed.decision(f64, fixed.replay(key, trick, pos))
        switched = fixed.decision(f32, fixed.replay(key, trick, pos))
        assert switched["cards"] == served["cards"], fixed.label(key, trick, pos)
        assert switched["worlds"] == served["worlds"], fixed.label(key, trick, pos)


def test_the_served_packages_forward_within_float32_rounding(release50_packages):
    from shengji.ai.cwv_numpy import load_cwv_numpy
    for role in ("value", "prior"):
        model = load_cwv_numpy(release50_packages[role])
        view = model.as_float32()
        public, world, perspective, flat = _batch(model, n=256, seed=9)
        probs, ref = view.probabilities(public, world, perspective), model.probabilities(public, world, perspective)
        assert np.max(np.abs(probs - ref)) < 1e-5, role
        if model.policy_head:
            assert np.max(np.abs(view.policy_log_odds(flat) - model.policy_log_odds(flat))) < 1e-3, role
