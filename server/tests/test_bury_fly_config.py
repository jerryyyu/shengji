"""The shipping configuration must resolve the reviewed bury-only recipe."""
import hashlib
import json
from pathlib import Path
import tomllib

from shengji.train.cwv_bury_policy import bury_env_recipe
from shengji.train.cwv_shortlist import resolved_recipe, shortlist_policy_name

# The shipping packages (#435, Jerry's go 2026-09-15): M1 3cb9cd62 as NumPy package
# 12ce4415 and policy prior v2 b6d928c5 as NumPy package b9ff76c9. Full SHAs are the
# identity; the eight-char prefixes are what the name shows.
M1_PACKAGE_SHA = "12ce4415a65c479b03d52a08574e14a5909b09435c1d8dddeab1726fbc1d4d4f"
PRIOR_PACKAGE_SHA = "b9ff76c9038630ae80bd396f4565574c549a55e385ffd729c2521905b76f0e6c"


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
    assert play_recipe["prior_checkpoint"] == "/data/models/prior-v2-b9ff76c9.npz"
    assert play_recipe["prior_sha256"] == PRIOR_PACKAGE_SHA
    assert (play_recipe["prior_threshold"], play_recipe["prior_top"]) == (10_000, 256)
    play_fields = {k: v for k, v in play_recipe.items() if k not in ("prior_checkpoint",)}
    play_policy = shortlist_policy_name(M1_PACKAGE_SHA[:8], 32, recipe=resolved_recipe(**play_fields))
    assert play_policy == "mc-shortlist-12ce4415-w32-r94c1cdbf-prior-b9ff76c9"
    identity = dict(schema="cwv-bury-recipe-v1",
        play_policy=play_policy,
        checkpoint_sha256=M1_PACKAGE_SHA,
        arm=arm, config=vars(bury), fallback="heuristic-on-error-or-budget",
        serving_budget_seconds=budget)
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()[:12]
    assert env["SHENGJI_BOT"] == identity["play_policy"] + "-bury-hybrid-" + digest
    assert env["SHENGJI_CWV_SHORTLIST_CKPT"] == "/data/models/m1-12ce4415.npz"
    assert env["SHENGJI_CWV_PRIOR_SHA256"] == PRIOR_PACKAGE_SHA
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == env["OMP_NUM_THREADS"] == "1"
