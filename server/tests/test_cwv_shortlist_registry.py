"""Witnesses for the W32 shortlist as a registry policy.

Every test carries its mutation: the assertion that would go RED if the
guarded behaviour were dropped is exercised against an explicit mutant, so a
GREEN here means the check discriminates rather than merely passes.

The guarded behaviour is one thing above all: ``mc-shortlist-<ckpt8>-w32``
must build `CWVShortlistBot`.  `registry.register_cwv_policies` looks like
the way to register a W32 complete-world-value arm and is NOT: it registers
``CWVOnePly_w32``, a different design that loses on the scorecard, and a
generator wired to it would produce hours of data worse than production with
every counter healthy.
"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest

from shengji.ai import cwv_policy
from shengji.ai.cwv_policy import CWVOnePlyBot, make_cwv_bot
from shengji.ai.mcbot import MCBot
from shengji.ai.registry import (
    REGISTRY,
    make_bot,
    register_cwv_policies,
    register_cwv_shortlist_policies,
)
from shengji.harvest import trajectory
from shengji.train import cwv_shortlist
from shengji.train.cwv_shortlist import (
    CWVShortlistBot,
    ShortlistPolicyError,
    shortlist_env_recipe,
    shortlist_policy_name,
    shortlist_registry_entries,
)


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory) -> str:
    """A tiny MLP checkpoint, so ``mlp-static`` is the effective encoding."""
    out = tmp_path_factory.mktemp("shortlist") / "tiny.pt"
    _load_script("cwv_dev_checkpoint").build_dev_checkpoint(
        str(out), rounds=2, architecture="mlp", width=16, max_epochs=2,
        quiet=True)
    return str(out)


@pytest.fixture
def registered(checkpoint):
    names = register_cwv_shortlist_policies(checkpoint, [32])
    try:
        yield names
    finally:
        for name in names:
            REGISTRY.pop(name, None)


# ------------------------------------------------- A: it IS the shortlist bot

def test_registered_name_builds_the_shortlist_bot_with_the_screened_recipe(
        checkpoint, registered):
    ckpt8 = cwv_policy.checkpoint_id(checkpoint)
    assert registered == [f"mc-shortlist-{ckpt8}-w32"]
    assert shortlist_policy_name(ckpt8) == f"mc-shortlist-{ckpt8}-w32"
    # never confusable with the one-ply entry of register_cwv_policies
    assert cwv_policy.policy_name(ckpt8, 32) not in registered

    bot = make_bot(registered[0], seed=11)
    assert type(bot) is CWVShortlistBot           # NOT a subclass, NOT one-ply
    assert isinstance(bot, MCBot)
    assert bot.policy_name == registered[0]
    assert bot.seed == 11                          # make_bot forwarded it
    # the screened recipe
    assert bot.shortlist_config.worlds == 32
    assert bot.shortlist_config.alternatives == 4
    assert bot.shortlist_config.selection_worlds == 30
    assert bot.N_DETERMINIZATIONS == 30
    assert bot.REPORT_FOLD_WORLDS == 300
    assert bot.reuse_successors is True
    assert bot.shortlist_config.uniform is False
    # the checkpoint's own encoder identity, not the requested one
    assert bot.cwv_ckpt8 == ckpt8
    assert bot.cwv_enc_version == bot.evaluator.enc_version
    assert bot.cwv_encoding == bot.evaluator.effective_encoding == "mlp-static"


def test_one_ply_bot_under_a_shortlist_name_is_refused(checkpoint, registered,
                                                       monkeypatch):
    """MUTANT: point the registered name at the one-ply class."""
    trap = make_cwv_bot(checkpoint, worlds=32, seed=11)
    assert type(trap).__name__ == "CWVOnePly_w32"
    assert not isinstance(trap, CWVShortlistBot)

    monkeypatch.setattr(cwv_shortlist, "_build_shortlist",
                        lambda evaluator, **kw: trap)
    with pytest.raises(ShortlistPolicyError, match="not CWVShortlistBot"):
        make_bot(registered[0], seed=11)


def test_a_foreign_factory_under_a_shortlist_name_is_refused(checkpoint,
                                                             monkeypatch):
    """MUTANT: register the shortlist NAME with register_cwv_policies' bot.

    The registry boundary, not the builder, is what refuses here.
    """
    ckpt8 = cwv_policy.checkpoint_id(checkpoint)
    one_ply = {shortlist_policy_name(ckpt8): (
        lambda **kw: make_cwv_bot(checkpoint, worlds=32, seed=kw.get("seed")))}
    monkeypatch.setattr(cwv_shortlist, "shortlist_registry_entries",
                        lambda *a, **k: one_ply)
    names = register_cwv_shortlist_policies(checkpoint, [32])
    try:
        with pytest.raises(ShortlistPolicyError, match="CWVOnePly_w32"):
            make_bot(names[0], seed=11)
    finally:
        for name in names:
            REGISTRY.pop(name, None)


def test_registering_the_one_ply_arm_gives_a_different_name_and_class(checkpoint):
    """The trap this whole entry point exists to make unreachable."""
    ckpt8 = cwv_policy.checkpoint_id(checkpoint)
    names = register_cwv_policies(checkpoint, [32])
    try:
        assert shortlist_policy_name(ckpt8) not in names
        bot = make_bot(f"mc-cwv-{ckpt8}-w32", seed=11)
        assert isinstance(bot, CWVOnePlyBot)
        assert not isinstance(bot, CWVShortlistBot)
    finally:
        for name in names:
            REGISTRY.pop(name, None)


# ------------------------------------------------------ env-driven registration

def test_env_recipe_defaults_and_overrides():
    assert shortlist_env_recipe({}) is None
    ckpt, worlds, recipe = shortlist_env_recipe(
        {"SHENGJI_CWV_SHORTLIST_CKPT": "ckpt.pt"})
    assert (ckpt, worlds) == ("ckpt.pt", [32])
    assert recipe == {"alternatives": 4, "selection_worlds": 30,
                      "report_worlds": 300, "batch_size": 128,
                      "encoding": "mlp-static", "reuse_successors": True}
    _, worlds, recipe = shortlist_env_recipe({
        "SHENGJI_CWV_SHORTLIST_CKPT": "ckpt.pt",
        "SHENGJI_CWV_SHORTLIST_WORLDS": "8,32",
        "SHENGJI_CWV_SHORTLIST_REPORT_WORLDS": "60",
        "SHENGJI_CWV_SHORTLIST_REUSE_SUCCESSORS": "0"})
    assert worlds == [8, 32]
    assert recipe["report_worlds"] == 60 and recipe["reuse_successors"] is False


def test_entries_refuse_a_non_positive_world_count(checkpoint):
    with pytest.raises(ValueError, match="worlds must be positive"):
        shortlist_registry_entries(checkpoint, [0])


# -------------------------------------- the harvest stamps production's ballot

def test_trajectory_probes_production_for_the_shortlist_policy(registered):
    config = trajectory.build_config(policy=registered[0], seed0=1,
                                     explore_rate=0.0, explore_k=0)
    assert config["policy_class"] == "CWVShortlistBot"
    bot = trajectory.make_trajectory_bot(config, seed=3,
                                         explore_rng=random.Random(0))
    assert isinstance(bot, CWVShortlistBot)
    probe = bot.production_probe
    assert probe is not None and not isinstance(probe, CWVShortlistBot)
    assert probe.policy_name == "mc-s0-report-lcb"
    # MUTANT: drop the marker and production's ballot is never recorded
    assert CWVShortlistBot.PRODUCTION_BALLOT_POLICY == "mc-s0-report-lcb"


def test_the_default_policy_keeps_no_production_probe():
    config = trajectory.build_config(policy="mc-s0-report-lcb", seed0=1,
                                     explore_rate=0.0, explore_k=0)
    bot = trajectory.make_trajectory_bot(config, seed=3,
                                         explore_rng=random.Random(0))
    assert bot.production_probe is None
