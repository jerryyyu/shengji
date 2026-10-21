"""The shipping configuration must resolve the reviewed bury-only recipe."""
import hashlib
import json
from pathlib import Path
import tomllib

from shengji.train.cwv_bury_policy import bury_env_recipe
from shengji.train.cwv_shortlist import resolved_recipe, shortlist_policy_name
from test_release46_fly_config import RELEASE46, V92_CANDIDATE_ENV, release46_env, without_combo
from test_release47_fly_config import RELEASE47, V98_CANDIDATE_CHANGES

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
RELEASE42 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-r0f40c8b5-bury-hybrid-273fed4cd40d"
RELEASE43 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-r91979586-bury-hybrid-28570365d86b"
RELEASE44 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-6c1fb26b80e6"
RELEASE45 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8"
WIDE_BURY = ("SHENGJI_PV_BURY_WIDE_VALUE", "SHENGJI_PV_BURY_WIDE_K")


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
    # Release 42 (Jerry 2026-10-06): release 38 plus the doomed-throw swap (#830, v57dts).
    # Release 43 (Jerry 2026-10-09): the doomed-throw re-select (#946) replaces the swap.
    # Release 44 (Jerry 2026-10-11): release 43 plus the value-guided declaration (#952, #959).
    # Release 45 (Jerry 2026-10-13): release 44 plus the wide value-only bury at K=64 (#974).
    # Release 46: release 45 plus the combo (history-legal belief-proposed worlds, the exact
    # endgame search at 7 cards, the every-first-round value declaration), the twelve lines of
    # V92_CANDIDATE_ENV; the name is the one v92combo45 screened.
    # Release 47: release 46 with the S46 r3 belief pair and the re-select's exact-stage
    # guard (dtrx, #1120), V98_CANDIDATE_CHANGES; the name is the one v98combo screened.
    for flag in ("ADMISSION_DIVERSITY", "REFUSAL_CONSTRAINTS", "TIEBREAK_POINTS", "LEAD_ANCHOR",
                 "DOOMED_THROW_RESELECT", "VALUE_DECLARE"):
        assert pv_recipe["SHENGJI_PV_" + flag] == "1"
    assert {k: pv_recipe[k] for k in V98_CANDIDATE_CHANGES} == V98_CANDIDATE_CHANGES
    assert {k: release46_env(env)[k] for k in V92_CANDIDATE_ENV} == V92_CANDIDATE_ENV
    # The served name is the one the server derives from this env (pv_env_recipe ->
    # pv_registry_entries); the packages are not in the repo, so only their on-disk hash
    # lookups are stood in by the pinned shas (the belief package's registration check
    # reads the file named by SHENGJI_PV_BELIEF_CKPT).
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: SERVED_PV_SHA[:8])
    belief_volume = {pair["SHENGJI_PV_BELIEF_CKPT"]: pair["SHENGJI_PV_BELIEF_SHA256"]
                     for pair in (V92_CANDIDATE_ENV, V98_CANDIDATE_CHANGES)}
    monkeypatch.setattr(pv, "file_sha256", lambda path: belief_volume[str(path)])
    names = list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))
    assert names == [env["SHENGJI_BOT"]] == [RELEASE47]
    # Rollback to release 46: the dtrx line removed and the S17 belief pair restored. Only
    # the play digest's belief and guard identity moves; the bury recipe is unchanged.
    release46 = release46_env(env)
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(release46))) == [RELEASE46]
    assert RELEASE47.endswith("-bury-hybrid-bwv-7cdf6f0d4232")
    assert (pv_recipe["SHENGJI_PV_BURY_WIDE_VALUE"], pv_recipe["SHENGJI_PV_BURY_WIDE_K"]) == ("1", "64")
    # Rollback to release 45: release 46's env without the twelve combo lines. The play digest
    # moves (the world, exact and declaration rules are in it) and the bury suffix digests
    # the play identity, so the bury recipe is unchanged although its suffix differs.
    release45 = without_combo(release46)
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(release45))) == [RELEASE45]
    assert RELEASE46.endswith("-bury-hybrid-bwv-cf77a93949b0") and RELEASE45.endswith("-bury-hybrid-bwv-7a73e8fbf1a8")
    # Rollback to release 44: release 45 without the two wide-bury lines; the play digest
    # is untouched, only the bury digest moves.
    release44 = {k: v for k, v in release45.items() if k not in WIDE_BURY}
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(release44))) == [RELEASE44]
    assert RELEASE45[:RELEASE45.index("-bury-")] == RELEASE44[:RELEASE44.index("-bury-")]
    # Rollback to release 43: release 44 without the value-declare line.
    release43 = {k: v for k, v in release44.items() if k != "SHENGJI_PV_VALUE_DECLARE"}
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(release43))) == [RELEASE43]
    # Rollback to release 38: the same env without the swap line registers release 38's name.
    # Rollback to release 42: the re-select line swapped back for the swap line.
    assert "SHENGJI_PV_DOOMED_THROW_SWAP" not in env
    release42 = {k: v for k, v in release43.items() if k != "SHENGJI_PV_DOOMED_THROW_RESELECT"}
    release42["SHENGJI_PV_DOOMED_THROW_SWAP"] = "1"
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(release42))) == [RELEASE42]
    release38 = {k: v for k, v in release43.items() if k != "SHENGJI_PV_DOOMED_THROW_RESELECT"}
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(release38))) == [RELEASE38]
    # Deeper rollback: without the five rule lines it registers release 36's name.
    rollback = {k: v for k, v in release44.items() if k not in ("SHENGJI_PV_VALUE_DECLARE", "SHENGJI_PV_DOOMED_THROW_RESELECT",
        "SHENGJI_PV_ADMISSION_DIVERSITY", "SHENGJI_PV_REFUSAL_CONSTRAINTS",
        "SHENGJI_PV_TIEBREAK_POINTS", "SHENGJI_PV_LEAD_ANCHOR")}
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe(rollback))) == [RELEASE36]
    assert pv_recipe["SHENGJI_PV_BURY_ARM"] == "hybrid"
    assert env["SHENGJI_CWV_SHORTLIST_CKPT"] == env["SHENGJI_CWV_PRIOR_CKPT"] == "/data/models/js-m1-0d17fd03.npz"
    assert env["SHENGJI_CWV_PRIOR_SHA256"] == PRIOR_PACKAGE_SHA
    assert env["SHENGJI_MODEL_SEARCH_CONCURRENCY"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == env["OMP_NUM_THREADS"] == "1"
