"""The shipping configuration must resolve the reviewed bury-only recipe."""
import hashlib
import json
from pathlib import Path
import tomllib

from shengji.train.cwv_bury_policy import CWVBuryConfig, bury_env_recipe
from shengji.train.cwv_shortlist import resolved_recipe, shortlist_policy_name

# The shipping package (#425/#435, Jerry's go 2026-09-15 23:4x ET): the from-scratch joint
# net JS-M1 a5248cc5 as ONE NumPy package (0d17fd03…) that is both the value net and, via
# its policy head, the prior. Full SHAs are the identity; the eight-char prefixes are
# what the name shows.
M1_PACKAGE_SHA = "0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747"
PRIOR_PACKAGE_SHA = M1_PACKAGE_SHA


def test_fly_bury_name_matches_recipe_and_preserves_play():
    config = tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())
    env = config["env"]
    parsed = bury_env_recipe(env)
    assert parsed is not None
    arm, bury, budget = parsed[-3:]
    assert arm == "hybrid" and budget == 2.0
    assert vars(bury) == dict(max_candidates=32, model_worlds=32,
                              selection_worlds=32, alternatives=4)
    play_recipe = parsed[2]
    # The prior group reaches the play recipe from the env and the SHA pin is the package's.
    assert play_recipe["prior_checkpoint"] == "/data/models/js-m1-0d17fd03.npz"
    assert play_recipe["prior_sha256"] == PRIOR_PACKAGE_SHA
    assert (play_recipe["prior_threshold"], play_recipe["prior_top"]) == (1_000, 256)
    play_fields = {k: v for k, v in play_recipe.items() if k not in ("prior_checkpoint",)}
    play_policy = shortlist_policy_name(M1_PACKAGE_SHA[:8], 32, recipe=resolved_recipe(**play_fields))
    assert play_policy == "mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03"
    identity = dict(schema="cwv-bury-recipe-v1",
        play_policy=play_policy,
        checkpoint_sha256=M1_PACKAGE_SHA,
        arm=arm, config=vars(bury), fallback="heuristic-on-error-or-budget",
        serving_budget_seconds=budget)
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()[:12]
    # Release 29 serves the policy/value search (pv-search, #585) with the hybrid bury; the
    # release-28 name below stays registered by the retained keys as the one-line rollback.
    release28 = identity["play_policy"] + "-bury-hybrid-" + digest
    assert release28 == "mc-shortlist-0d17fd03-w32-r0d610b62-prior-0d17fd03-bury-hybrid-003c2abe49ff"
    assert env["SHENGJI_BOT"] != release28
    from shengji.train import pv_search_policy as pv
    pv_recipe = {k: v for k, v in env.items() if k.startswith("SHENGJI_PV_")}
    assert pv_recipe["SHENGJI_PV_CKPT"] == "/data/models/soft-8ecd4fea.npz"
    assert len(pv_recipe["SHENGJI_PV_SHA256"]) == 64
    play = pv.pv_policy_name(pv_recipe["SHENGJI_PV_SHA256"][:8], pv.PVSearchConfig(
        checkpoint_sha256=pv_recipe["SHENGJI_PV_SHA256"], worlds=int(pv_recipe["SHENGJI_PV_WORLDS"]),
        candidates=int(pv_recipe["SHENGJI_PV_CANDIDATES"]), cap=int(pv_recipe["SHENGJI_PV_CAP"]),
        batch_size=int(pv_recipe["SHENGJI_PV_BATCH_SIZE"]),
        serving_budget_seconds=float(pv_recipe["SHENGJI_PV_SERVING_BUDGET_SECONDS"])))
    pv_identity = dict(schema="cwv-bury-recipe-v1", play_policy=play,
                       checkpoint_sha256=pv_recipe["SHENGJI_PV_SHA256"], arm="hybrid",
                       config=vars(CWVBuryConfig()), fallback="heuristic-on-error-or-budget",
                       serving_budget_seconds=float(pv_recipe["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"]))
    pv_digest = hashlib.sha256(json.dumps(pv_identity, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()[:12]
    assert env["SHENGJI_BOT"] == play + "-bury-hybrid-" + pv_digest
    assert pv_recipe["SHENGJI_PV_BURY_ARM"] == "hybrid"
    assert env["SHENGJI_CWV_SHORTLIST_CKPT"] == env["SHENGJI_CWV_PRIOR_CKPT"] == "/data/models/js-m1-0d17fd03.npz"
    assert env["SHENGJI_CWV_PRIOR_SHA256"] == PRIOR_PACKAGE_SHA
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == env["OMP_NUM_THREADS"] == "1"
