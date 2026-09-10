"""The shipping configuration must resolve the reviewed bury-only recipe."""
import hashlib
import json
from pathlib import Path
import tomllib

from shengji.train.cwv_bury_policy import bury_env_recipe


def test_fly_bury_name_matches_recipe_and_preserves_play():
    config = tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())
    env = config["env"]
    parsed = bury_env_recipe(env)
    assert parsed is not None
    arm, bury, budget = parsed[-3:]
    assert arm == "hybrid" and budget == 2.0
    assert vars(bury) == dict(max_candidates=32, model_worlds=32,
                              selection_worlds=32, alternatives=4)
    identity = dict(schema="cwv-bury-recipe-v1",
        play_policy="mc-shortlist-fd6bb411-w32-r55d379a3",
        checkpoint_sha256="fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9",
        arm=arm, config=vars(bury), fallback="heuristic-on-error-or-budget",
        serving_budget_seconds=budget)
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()[:12]
    assert env["SHENGJI_BOT"] == identity["play_policy"] + "-bury-hybrid-" + digest
    assert env["SHENGJI_CWV_SHORTLIST_CKPT"] == "/data/models/w32-fd6bb411.npz"
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == env["OMP_NUM_THREADS"] == "1"
