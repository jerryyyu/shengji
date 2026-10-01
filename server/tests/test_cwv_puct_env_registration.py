"""The PUCT environment registration hook (#436 step 1b).

The screen harness builds its arms with ``make_bot(name)`` inside SPAWNED
worker processes, whose registry is populated only by the import-time
``_register_*_from_env`` hooks.  ``_register_cwv_puct_from_env`` mirrors the
pv-search hook: inert without ``SHENGJI_CWV_PUCT_CKPT``, refuses an unpinned
or mis-pinned package, and registers exactly the names
``cwv_puct_registry_entries`` produces, so a worker and its parent agree.

Torch-free: the package is the synthetic joint ``.npz`` of
``test_cwv_puct_package_prior``.  The fresh-interpreter witness runs for
real: a child ``python -c`` imports the registry under the env and builds
the bot.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from shengji.ai import registry
from shengji.ai.cwv_policy import CWVError
from shengji.ai.cwv_puct import cwv_puct_registry_entries, puct_env_recipe
from shengji.ai.registry import REGISTRY, make_bot

from test_cwv_puct_package_prior import _write_joint_package

ROOT = Path(__file__).parents[1]
PREFIX = "SHENGJI_CWV_PUCT_"


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    path = tmp_path_factory.mktemp("puctenv") / "tiny-joint.npz"
    return str(path), _write_joint_package(path, 3)


@pytest.fixture(scope="module")
def other_package(tmp_path_factory):
    path = tmp_path_factory.mktemp("puctenv2") / "other-joint.npz"
    return str(path), _write_joint_package(path, 23)


def _env(path, sha, **extra):
    env = {PREFIX + "CKPT": path, PREFIX + "SHA256": sha, PREFIX + "SIMULATIONS": "16"}
    env.update({PREFIX + k.upper(): v for k, v in extra.items()})
    return env


def _clear(monkeypatch):
    for key in [k for k in os.environ if k.startswith(PREFIX)]:
        monkeypatch.delenv(key)
    for name in [n for n in REGISTRY if n.startswith("mc-cwvpuct-")]:
        del REGISTRY[name]


# ------------------------------------------------------------- (a) inert

def test_the_hook_is_inert_without_the_env(monkeypatch):
    _clear(monkeypatch)
    before = dict(REGISTRY)
    registry._register_cwv_puct_from_env()
    assert REGISTRY == before
    assert not any(n.startswith("mc-cwvpuct-") for n in REGISTRY)
    with pytest.raises(CWVError, match="SHENGJI_CWV_PUCT_CKPT"):
        puct_env_recipe({})


# ------------------------------ (b) a fresh interpreter builds the bot

def test_a_fresh_interpreter_registers_the_same_names_and_builds_the_bot(package, monkeypatch):
    path, sha = package
    _clear(monkeypatch)
    env = _env(path, sha, prior="package", leaf_finish_trick="1", prior_temperature="0.5",
               world_pool="2", batch="4")
    # the parent's view of the names
    recipe = puct_env_recipe(env)
    expected = sorted(cwv_puct_registry_entries(
        recipe.pop("checkpoint"), recipe.pop("simulations"), **recipe))
    arm = [n for n in expected if not n.startswith("mc-cwvpuct-prior-")][0]
    assert arm == f"mc-cwvpuct-{sha[:8]}-s16-pprior-T0.5-ftl"
    # a spawned worker: a fresh interpreter whose registry sees ONLY the env
    code = (
        "import json, sys\n"
        "from shengji.ai.registry import REGISTRY, make_bot\n"
        "names = sorted(n for n in REGISTRY if n.startswith('mc-cwvpuct-'))\n"
        f"bot = make_bot({arm!r}, seed=3)\n"
        "print(json.dumps({'names': names, 'cls': type(bot).__name__,\n"
        "                  'prior': bot.CWV_PRIOR, 'ftl': bot.CWV_LEAF_FINISH_TRICK,\n"
        "                  'T': bot.CWV_PRIOR_TEMPERATURE, 'S': bot.CWV_SIMULATIONS,\n"
        "                  'W': bot.CWV_WORLD_POOL, 'K': bot.CWV_BATCH,\n"
        "                  'prior_sha': bot.prior_head.package_sha256,\n"
        "                  'value_sha': bot.cwv_checkpoint_sha256}))\n")
    child_env = {k: v for k, v in os.environ.items() if not k.startswith(PREFIX)}
    child_env.update(env)
    child_env["PYTHONPATH"] = str(ROOT)
    run = subprocess.run([sys.executable, "-P", "-B", "-c", code], cwd=ROOT, env=child_env,
                         capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    import json
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert out["names"] == expected
    assert out["prior"] == "package" and out["ftl"] is True and out["T"] == 0.5
    assert out["S"] == 16 and out["W"] == 2 and out["K"] == 4
    assert out["prior_sha"] == sha == out["value_sha"]
    assert out["cls"].startswith("CWVPuct_s16_w2_k4")
    # the same hook in THIS process registers the same names
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    registry._register_cwv_puct_from_env()
    assert sorted(n for n in REGISTRY if n.startswith("mc-cwvpuct-")) == expected
    bot = make_bot(arm, seed=3)
    assert bot.CWV_PRIOR == "package" and bot.prior_head.package_sha256 == sha
    _clear(monkeypatch)


# ------------------------------------------------- (c) refusals

def test_an_unpinned_or_mispinned_package_refuses(package, other_package, monkeypatch):
    path, sha = package
    other, other_sha = other_package
    _clear(monkeypatch)
    flipped = ("0" if sha[0] != "0" else "1") + sha[1:]
    for bad, match in (
            ({PREFIX + "CKPT": path, PREFIX + "SIMULATIONS": "16"}, "SHA256"),
            (_env(path, sha[:8]), "full sha256"),
            (_env(path, flipped), "does not hash"),
            (_env(other, sha), "does not hash"),
            ({PREFIX + "CKPT": path, PREFIX + "SHA256": sha}, "SIMULATIONS"),
            (_env(path, sha, simulations="0"), "positive"),
            (_env(path, sha, prior="bogus"), "PRIOR"),
            (_env(path, sha, prior="head"), "PRIOR_CKPT"),
            (_env(path, sha, prior_ckpt=other), "go together"),
            (_env(path, sha, prior_ckpt=other, prior_sha256=sha), "PRIOR_CKPT does not hash"),
            (_env(path, sha, prior_temperature="0"), "TEMPERATURE"),
            (_env(path, sha, leaf_finish_trick="yes"), "0 or 1")):
        with pytest.raises(CWVError, match=match):
            puct_env_recipe(bad)
    # the import hook raises the same refusal (it does not register half a recipe)
    for key, value in _env(path, flipped).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(CWVError, match="does not hash"):
        registry._register_cwv_puct_from_env()
    assert not any(n.startswith("mc-cwvpuct-") for n in REGISTRY)
    # a separate, correctly pinned prior package names itself
    recipe = puct_env_recipe(_env(path, sha, prior_ckpt=other, prior_sha256=other_sha))
    names = cwv_puct_registry_entries(recipe.pop("checkpoint"), recipe.pop("simulations"), **recipe)
    assert f"mc-cwvpuct-{sha[:8]}-prior-{other_sha[:8]}-s16-pprior" in names
    # uniform needs no prior package at all
    recipe = puct_env_recipe(_env(path, sha, prior="uniform"))
    assert "prior_checkpoint" not in recipe and recipe["prior"] == "uniform"
    _clear(monkeypatch)


# ------------------------------- (d) the served registration is untouched

def test_the_pv_search_registration_and_names_are_untouched(package, monkeypatch):
    from shengji.train import pv_search_policy as pv
    path, sha = package
    _clear(monkeypatch)
    for key in [k for k in os.environ if k.startswith("SHENGJI_PV_")]:
        monkeypatch.delenv(key)
    for name in [n for n in REGISTRY if n.startswith("pv-search-")]:
        del REGISTRY[name]
    # the PUCT env alone registers no pv-search name, and vice versa
    for key, value in _env(path, sha).items():
        monkeypatch.setenv(key, value)
    registry._register_cwv_puct_from_env()
    registry._register_pv_search_from_env()
    assert not any(n.startswith("pv-search-") for n in REGISTRY)
    monkeypatch.setenv("SHENGJI_PV_CKPT", path)
    monkeypatch.setenv("SHENGJI_PV_SHA256", sha)
    recipe = pv.pv_env_recipe()
    assert set(recipe) == {"checkpoint", "sha256"}            # no PUCT key leaks in
    names = registry.register_pv_search_policies(recipe.pop("checkpoint"), **recipe)
    assert names == [pv.pv_policy_name(sha[:8], pv.PVSearchConfig(checkpoint_sha256=sha))]
    assert names[0].startswith(f"pv-search-{sha[:8]}-w64-k8-r")
    for name in names:
        del REGISTRY[name]
    _clear(monkeypatch)


# ------------------- (e) the pins are enforced at CONSTRUCTION, not registration

def _replace_bytes(path: str, seed: int) -> str:
    """Overwrite the package in place with other weights; returns the new sha."""
    return _write_joint_package(Path(path), seed)


@pytest.mark.parametrize("prior", ["package", "uniform", "value", "head"])
def test_a_value_package_replaced_after_registration_refuses_at_make_bot(
        tmp_path, other_package, monkeypatch, prior):
    """Codex HOLD on #692: the value pin must reach the factory.  Register a
    pinned package, swap the file's bytes, and every registered name -- the
    arm under each prior mode and the control -- must refuse, naming the pin."""
    from shengji.ai.cwv_puct import make_cwv_puct_bot
    _clear(monkeypatch)
    path = str(tmp_path / f"value-{prior}.npz")
    sha = _write_joint_package(Path(path), 3)
    env = _env(path, sha, prior=prior, world_pool="2", batch="4")
    if prior == "head":
        other, other_sha = other_package
        env.update({PREFIX + "PRIOR_CKPT": other, PREFIX + "PRIOR_SHA256": other_sha})
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    registry._register_cwv_puct_from_env()
    names = sorted(n for n in REGISTRY if n.startswith("mc-cwvpuct-"))
    assert len(names) == 2 and all(sha[:8] in n for n in names)
    arm = [n for n in names if not n.startswith("mc-cwvpuct-prior-")][0]
    if prior != "head":            # a .pt public head is not built here (torch); the refusal is
        bot = make_bot(arm, seed=1)   # what matters and it fires before the head is loaded
        assert bot.cwv_checkpoint_sha256 == sha
    replaced = _replace_bytes(path, 99)
    assert replaced != sha
    for name in names:
        with pytest.raises(CWVError, match=f"value checkpoint .*pinned {sha[:8]}"):
            make_bot(name, seed=1)
    # the direct constructor enforces the same pin, with and without a prior package
    with pytest.raises(CWVError, match="value checkpoint"):
        make_cwv_puct_bot(path, simulations=1, checkpoint_sha256=sha)
    with pytest.raises(CWVError, match="value checkpoint"):
        make_cwv_puct_bot(path, simulations=1, control=True, checkpoint_sha256=sha)
    # MUTANT (the held behaviour): an UNPINNED factory builds on the replacement
    unpinned = make_cwv_puct_bot(path, simulations=1)
    assert unpinned.cwv_checkpoint_sha256 == replaced
    _clear(monkeypatch)


def test_a_prior_package_replaced_after_registration_refuses_at_make_bot(tmp_path, monkeypatch):
    _clear(monkeypatch)
    value = str(tmp_path / "value.npz")
    value_sha = _write_joint_package(Path(value), 3)
    prior = str(tmp_path / "prior.npz")
    prior_sha = _write_joint_package(Path(prior), 23)
    env = _env(value, value_sha, prior="package", prior_ckpt=prior, prior_sha256=prior_sha,
               world_pool="2", batch="4")
    for key, value_ in env.items():
        monkeypatch.setenv(key, value_)
    registry._register_cwv_puct_from_env()
    arm = f"mc-cwvpuct-{value_sha[:8]}-prior-{prior_sha[:8]}-s16-pprior"
    assert arm in REGISTRY
    bot = make_bot(arm, seed=1)
    assert bot.prior_head.package_sha256 == prior_sha and bot.cwv_checkpoint_sha256 == value_sha
    replaced = _replace_bytes(prior, 77)
    assert replaced != prior_sha
    # the value file is intact, so only the prior pin fires -- naming it
    with pytest.raises(CWVError, match=f"prior checkpoint .*pinned {prior_sha[:8]}"):
        make_bot(arm, seed=1)
    # the control carries no prior id and no prior package in its name
    assert f"mc-cwvpuct-prior-{value_sha[:8]}-s16" in REGISTRY
    _clear(monkeypatch)
