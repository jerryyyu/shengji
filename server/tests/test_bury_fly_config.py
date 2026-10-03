"""The shipping configuration must resolve the reviewed bury-only recipe."""
import hashlib
import json
from pathlib import Path
import tomllib

from shengji.train.cwv_bury_policy import bury_env_recipe
from shengji.train.cwv_shortlist import resolved_recipe, shortlist_policy_name

# The shipping package (#425/#435, Jerry's go 2026-09-15 23:4x ET): the from-scratch joint
# net JS-M1 a5248cc5 as ONE NumPy package (0d17fd03…) that is both the value net and, via
# its policy head, the prior. Full SHAs are the identity; the eight-char prefixes are
# what the name shows.
M1_PACKAGE_SHA = "0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747"
PRIOR_PACKAGE_SHA = M1_PACKAGE_SHA
# The served pv-search package (release 36, unchanged in release 38): smv3out-491ee4bf.
SERVED_PV_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
RELEASE36 = "pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25"
RELEASE38 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457"


def test_fly_bury_name_matches_recipe_and_preserves_play(monkeypatch):
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
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv
    pv_recipe = {k: v for k, v in env.items() if k.startswith("SHENGJI_PV_")}
    assert pv_recipe["SHENGJI_PV_CKPT"] == "/data/models/smv3out-491ee4bf.npz"
    assert pv_recipe["SHENGJI_PV_SHA256"] == SERVED_PV_SHA
    # Release 38 (Jerry 2026-10-03): release 36's package, search, bury and budgets with the
    # four search rules on (combo = div + rc + tb, #676; lead anchor, #694).
    for flag in ("ADMISSION_DIVERSITY", "REFUSAL_CONSTRAINTS", "TIEBREAK_POINTS", "LEAD_ANCHOR"):
        assert pv_recipe["SHENGJI_PV_" + flag] == "1"
    # The served name is the one the server derives from this env (pv_env_recipe ->
    # pv_registry_entries); the package is not in the repo, so only its on-disk hash
    # lookup is stood in by the pinned sha.
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: SERVED_PV_SHA[:8])
    names = list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))
    assert names == [env["SHENGJI_BOT"]] == [RELEASE38]
    # Rollback: the same env without the four rule lines registers release 36's name.
    rollback = {k: v for k, v in env.items() if k not in (
        "SHENGJI_PV_ADMISSION_DIVERSITY", "SHENGJI_PV_REFUSAL_CONSTRAINTS",
        "SHENGJI_PV_TIEBREAK_POINTS", "SHENGJI_PV_LEAD_ANCHOR")}
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(rollback))) == [RELEASE36]
    assert pv_recipe["SHENGJI_PV_BURY_ARM"] == "hybrid"
    assert env["SHENGJI_CWV_SHORTLIST_CKPT"] == env["SHENGJI_CWV_PRIOR_CKPT"] == "/data/models/js-m1-0d17fd03.npz"
    assert env["SHENGJI_CWV_PRIOR_SHA256"] == PRIOR_PACKAGE_SHA
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == env["OMP_NUM_THREADS"] == "1"
