"""The served policy prior as part of the shortlist identity (#435 item 5).

Three things are guarded, each against its own mutant:

* a prior-less recipe resolves to exactly the name on file (the deployed
  ``...-r55d379a3``), so binding the prior changed nothing for anyone who did
  not opt in;
* a bound prior reaches the name, the digest, the built bot and its bury
  composition, and a prior knob without a prior is refused rather than dropped;
* the registry re-hashes the prior file on every build, so a file swapped after
  registration cannot serve under the old name.
"""
import hashlib
import os

import pytest

from shengji.ai import registry
from shengji.ai.cwv_policy import file_sha256
from shengji.train import cwv_shortlist as cs
from shengji.train.cwv_bury_policy import CWVBuryConfig
from shengji.train.cwv_prior_admission import (
    CWVPriorAdmissionBot, CWVPriorAdmissionConfig, CWVPriorBuryBot,
)

from test_cwv_shortlist_registry import checkpoint  # noqa: F401
from test_cwv_prior_admission import prior_ckpt  # noqa: F401

DEPLOYED = "mc-shortlist-fd6bb411-w32-r55d379a3"
PLAY = dict(alternatives=1, selection_worlds=1, report_worlds=30)


@pytest.fixture
def clean_registry():
    before = dict(registry.REGISTRY)
    try:
        yield
    finally:
        for name in set(registry.REGISTRY) - set(before):
            registry.REGISTRY.pop(name, None)


# ------------------------------------------------------- identity, by name

def test_a_prior_less_recipe_still_resolves_to_the_deployed_name():
    resolved = cs.resolved_recipe()
    assert "prior_sha256" not in resolved
    assert cs.shortlist_policy_name("fd6bb411", 32, recipe=resolved) == DEPLOYED
    # Mutant: the same recipe with the prior bound is a different bot and
    # must not collide with the deployed name by digest OR by eye.
    bound = cs.shortlist_policy_name("fd6bb411", 32, recipe=dict(prior_sha256="a" * 64))
    assert bound != DEPLOYED and bound.endswith("-prior-aaaaaaaa")
    assert not bound.startswith(DEPLOYED)


@pytest.mark.parametrize("field,value", [("prior_threshold", 1_000), ("prior_top", 64)])
def test_every_prior_field_changes_the_name(field, value):
    base = dict(prior_sha256="b" * 64)
    assert (cs.shortlist_policy_name("c", 32, recipe=base)
            != cs.shortlist_policy_name("c", 32, recipe={**base, field: value}))


def test_a_prior_knob_without_a_prior_is_refused_not_dropped():
    with pytest.raises(ValueError, match="need prior_sha256"):
        cs.resolved_recipe(prior_threshold=1_000)
    with pytest.raises(ValueError, match="full lowercase SHA256"):
        cs.resolved_recipe(prior_sha256="deadbeef")
    with pytest.raises(ValueError, match="positive integer"):
        cs.resolved_recipe(prior_sha256="c" * 64, prior_top=0)
    with pytest.raises(ValueError, match="not in RECIPE_FIELDS"):
        cs.resolved_recipe(prior_checkpoint="x.pt")   # the path is never identity


# ------------------------------------------------------------ env binding

def test_env_without_a_prior_is_byte_for_byte_the_old_recipe():
    _, _, recipe = cs.shortlist_env_recipe({"SHENGJI_CWV_SHORTLIST_CKPT": "ckpt.pt"})
    assert set(recipe) == set(cs.RECIPE_FIELDS)


def test_env_prior_group_is_parsed_and_a_stray_knob_is_refused():
    _, _, recipe = cs.shortlist_env_recipe({
        "SHENGJI_CWV_SHORTLIST_CKPT": "ckpt.pt", "SHENGJI_CWV_PRIOR_CKPT": "prior.npz",
        "SHENGJI_CWV_PRIOR_SHA256": "d" * 64, "SHENGJI_CWV_PRIOR_THRESHOLD": "1000"})
    assert recipe["prior_checkpoint"] == "prior.npz"
    assert recipe["prior_sha256"] == "d" * 64
    assert (recipe["prior_threshold"], recipe["prior_top"]) == (1000, 256)
    with pytest.raises(cs.ShortlistPolicyError, match="without SHENGJI_CWV_PRIOR_CKPT"):
        cs.shortlist_env_recipe({"SHENGJI_CWV_SHORTLIST_CKPT": "ckpt.pt",
                                 "SHENGJI_CWV_PRIOR_TOP": "64"})


# ------------------------------------------------------- the built bot

def test_registered_name_builds_the_admission_bot_and_binds_the_prior_sha(
        checkpoint, prior_ckpt, clean_registry):
    path, sha = prior_ckpt
    name, = registry.register_cwv_shortlist_policies(
        checkpoint, [1], prior_checkpoint=path, **PLAY)
    assert name.endswith(f"-prior-{sha[:8]}")
    bot = registry.make_bot(name, seed=3)
    assert type(bot) is CWVPriorAdmissionBot
    assert bot.policy_name == name
    assert bot.cwv_prior_sha256 == sha and bot.cwv_prior_checkpoint == path
    assert bot.prior_config == CWVPriorAdmissionConfig(
        checkpoint=path, checkpoint_sha256=sha, threshold=10_000, top=256)
    # The direct builder derives the same name from the same arguments.
    direct = cs.make_shortlist_bot(checkpoint, seed=3, worlds=1,
                                   prior_checkpoint=path, **PLAY)
    assert direct.policy_name == name
    # Mutant: the prior-less registration is a different name and a plain bot.
    plain, = registry.register_cwv_shortlist_policies(checkpoint, [1], **PLAY)
    assert plain != name and "prior" not in plain
    assert type(registry.make_bot(plain, seed=3)) is cs.CWVShortlistBot


def test_a_pinned_sha_that_does_not_match_the_file_is_refused(checkpoint, prior_ckpt):
    path, sha = prior_ckpt
    with pytest.raises(cs.ShortlistPolicyError, match="not the pinned"):
        cs.shortlist_registry_entries(checkpoint, [1], prior_checkpoint=path,
                                      prior_sha256="e" * 64, **PLAY)
    with pytest.raises(cs.ShortlistPolicyError, match="not the bound"):
        cs.make_shortlist_bot(checkpoint, worlds=1, prior_checkpoint=path,
                              prior_sha256="e" * 64, **PLAY)
    with pytest.raises(cs.ShortlistPolicyError, match="binds nothing"):
        cs.make_shortlist_bot(checkpoint, worlds=1, prior_sha256=sha, **PLAY)


def test_a_prior_swapped_after_registration_cannot_serve_under_the_name(
        checkpoint, prior_ckpt, tmp_path, clean_registry):
    path, _sha = prior_ckpt
    copy = tmp_path / "prior.pt"
    copy.write_bytes(open(path, "rb").read())
    name, = registry.register_cwv_shortlist_policies(
        checkpoint, [1], prior_checkpoint=str(copy), **PLAY)
    registry.make_bot(name, seed=1)          # the registered file builds
    copy.write_bytes(copy.read_bytes() + b"\0")
    with pytest.raises(cs.ShortlistPolicyError, match="not the bound"):
        registry.make_bot(name, seed=1)


# ---------------------------------------------------------- bury composition

def test_bury_wrapper_keeps_the_prior_admission_stage(checkpoint, prior_ckpt, clean_registry):
    path, sha = prior_ckpt
    bury = CWVBuryConfig(max_candidates=6, model_worlds=1, selection_worlds=2, alternatives=2)
    name, = registry.register_cwv_bury_policies(
        checkpoint, [1], arm="hybrid", bury_config=bury, prior_checkpoint=path, **PLAY)
    bot = registry.make_bot(name, seed=5)
    assert type(bot) is CWVPriorBuryBot
    assert bot.bury_arm == "hybrid" and bot.bury_config == bury
    assert bot.prior_config.checkpoint_sha256 == sha
    assert bot.cwv_prior_sha256 == sha
    assert bot._candidates.__func__ is CWVPriorAdmissionBot._candidates
    identity = bot.bury_recipe_identity
    assert identity["play_policy"].endswith(f"-prior-{sha[:8]}")
    assert name.startswith(identity["play_policy"] + "-bury-hybrid-")
    # Mutant: the same play recipe without the prior is a plain bury bot under
    # a name that shares no prefix past the checkpoint and width.
    plain, = registry.register_cwv_bury_policies(
        checkpoint, [1], arm="hybrid", bury_config=bury, **PLAY)
    assert plain != name and not hasattr(registry.make_bot(plain, seed=5), "prior_config")


# ----------------------------------------------------------------- health

def test_healthz_reports_the_prior_file_sha_or_null(prior_ckpt, monkeypatch):
    from shengji.api import server
    path, sha = prior_ckpt
    monkeypatch.delenv("SHENGJI_CWV_PRIOR_CKPT", raising=False)
    assert server._prior_health() is None
    monkeypatch.setenv("SHENGJI_CWV_PRIOR_CKPT", path)
    monkeypatch.setenv("SHENGJI_CWV_PRIOR_THRESHOLD", "1000")
    health = server._prior_health()
    assert health == {"sha256": sha, "threshold": 1000, "top": 256}
    assert health["sha256"] == hashlib.sha256(open(path, "rb").read()).hexdigest()
    monkeypatch.setenv("SHENGJI_CWV_PRIOR_CKPT", path + ".missing")
    assert "error" in server._prior_health()
