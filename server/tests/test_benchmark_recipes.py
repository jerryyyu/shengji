"""Synthetic source qualification; never load a checkpoint or call a provider."""
import hashlib
import json

import pytest

from shengji.luna import benchmark_recipes as recipes


@pytest.mark.parametrize("policy", ["mc-lcb", "mc-strong", "mc", "smart"])
def test_static_recipe_factory_seed_and_identity(monkeypatch, policy):
    from shengji.ai.registry import REGISTRY
    name = "mc-s0-report-lcb" if policy == "mc-lcb" else policy
    calls = []
    sentinel = object()
    def factory(**kwargs):
        calls.append(kwargs)
        return sentinel
    monkeypatch.setitem(REGISTRY, name, factory)
    prepared = recipes.prepare_recipe(policy, {})
    assert not calls
    assert prepared.identity["benchmark_id"] == policy
    assert prepared.identity["play_only"] is True
    assert prepared.factory(seed=17) is sentinel
    assert calls == ([{}] if policy == "smart" else [{"seed": 17}])


@pytest.mark.parametrize("policy,assets", [
    ("smv3-pv", ["smv3"]), ("soft-pv", ["soft"]),
    ("js-m1-shortlist", ["js_m1"]),
    ("m1-prior", ["m1", "prior_v2"]), ("w32-original", ["w32"]),
])
def test_model_recipe_exact_registration_without_loading(monkeypatch, policy, assets):
    from shengji.train import pv_search_policy, cwv_shortlist
    calls, checked = [], []
    sentinel = object()
    def asset(paths, key):
        checked.append(key)
        return "/synthetic/" + key, recipes._SHAS[key]
    def register(path, **kwargs):
        calls.append((path, kwargs))
        return {"registered": sentinel}
    monkeypatch.setattr(recipes, "_asset", asset)
    monkeypatch.setattr(pv_search_policy, "pv_registry_entries", register)
    monkeypatch.setattr(cwv_shortlist, "shortlist_registry_entries", register)
    prepared = recipes.prepare_recipe(policy, {})
    assert checked == assets
    assert prepared.factory is sentinel
    assert prepared.policy == "registered"
    assert prepared.identity["benchmark_id"] == policy
    path, args = calls[0]
    assert path == "/synthetic/" + assets[0]
    if policy.endswith("-pv"):
        assert args == dict(recipes._PV, sha256=recipes._SHAS[assets[0]])
    else:
        expected = dict(recipes._SHORTLIST, worlds=(32,), prior_checkpoint=None)
        if policy != "w32-original":
            prior = assets[-1]
            expected.update(prior_checkpoint="/synthetic/" + prior,
                            prior_sha256=recipes._SHAS[prior],
                            prior_threshold=1000, prior_top=256)
        assert args == expected


def test_release46_recipe_uses_frozen_serving_inputs(monkeypatch):
    from shengji.train import pv_search_policy

    checked, calls = [], []
    sentinel = object()

    def asset(paths, key):
        checked.append(key)
        return "/synthetic/" + key, recipes._SHAS[key]

    def register(**kwargs):
        calls.append(kwargs)
        return {"registered-r46": sentinel}

    monkeypatch.setattr(recipes, "_asset", asset)
    monkeypatch.setattr(pv_search_policy, "pv_registry_entries", register)
    prepared = recipes.prepare_recipe("release46-pv", {})

    assert checked == ["smv3", "belief"]
    assert prepared.factory is sentinel
    assert prepared.policy == "registered-r46"
    expected = {
        "checkpoint": "/synthetic/smv3",
        "sha256": recipes._SHAS["smv3"],
        "worlds": 64,
        "candidates": 8,
        "cap": 4000,
        "batch_size": 128,
        "serving_budget_seconds": 3.0,
        "admission_diversity": True,
        "refusal_constraints": True,
        "tiebreak_points": True,
        "lead_anchor": True,
        "doomed_throw_reselect": True,
        "value_declare": True,
        "value_declare_every_first": True,
        "world_history_legal": True,
        "world_history_draw": True,
        "belief_worlds": True,
        "belief_checkpoint": "/synthetic/belief",
        "belief_sha256": recipes._SHAS["belief"],
        "exact_lead_endgame": True,
        "exact_deep_cards": 7,
        "exact_follow": True,
        "exact_follow_solver": "compact-level",
        "exact_follow_max_cards": 7,
        "exact_follow_max_nodes": 50000000,
        "bury_arm": "hybrid",
        "bury_config": pv_search_policy.CWVBuryConfig(),
        "bury_serving_budget_seconds": 2.0,
        "bury_wide_value": True,
        "bury_wide_k": 64,
    }
    assert calls == [expected]
    assert prepared.identity["play_only"] is True
    assert prepared.identity["belief_sha256"] == recipes._SHAS["belief"]


def test_release46_registry_derives_name_without_loading_models(monkeypatch):
    from shengji.train import pv_search_policy

    paths = {"smv3": "/synthetic/smv3.npz", "belief": "/synthetic/belief.npz"}
    digests = {paths["smv3"]: recipes._SHAS["smv3"],
               paths["belief"]: recipes._SHAS["belief"]}
    monkeypatch.setattr(recipes, "_asset",
                        lambda _paths, key: (paths[key], recipes._SHAS[key]))
    monkeypatch.setattr(pv_search_policy, "file_sha256",
                        lambda path: digests[path])
    from shengji.ai import cwv_policy
    monkeypatch.setattr(cwv_policy, "file_sha256", lambda path: digests[path])

    prepared = recipes.prepare_recipe("release46-pv", {})

    assert prepared.policy == (
        "pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-"
        "xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0"
    )
    assert prepared.identity["policy"] == "release46-pv"


def test_release46_run_row_dry_run_json_roundtrip(tmp_path, monkeypatch):
    from scripts import production_llm_panel as panel
    from scripts.prepare_llm_panel_roots import prepare_roots
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy

    paths = {"smv3": "/synthetic/smv3.npz", "belief": "/synthetic/belief.npz"}
    digests = {paths["smv3"]: recipes._SHAS["smv3"],
               paths["belief"]: recipes._SHAS["belief"]}
    monkeypatch.setattr(recipes, "_asset",
                        lambda _paths, key: (paths[key], recipes._SHAS[key]))
    monkeypatch.setattr(pv_search_policy, "file_sha256",
                        lambda path: digests[path])
    monkeypatch.setattr(cwv_policy, "file_sha256", lambda path: digests[path])

    roots = tmp_path / "roots"
    prepare_roots(output=roots, seeds=[12])
    roots_sha = hashlib.sha256((roots / "result.json").read_bytes()).hexdigest()
    result = panel.run_row(
        row="release46-pv", model_paths={}, prepared_roots_from=roots,
        prepared_roots_sha256=roots_sha, output=tmp_path / "out", seeds=(12,),
        actor_only=True)

    assert result["mode"] == "dry-run"
    assert result["config"]["baseline_recipe"]["bury_config"] == {
        "max_candidates": 32, "model_worlds": 32, "selection_worlds": 32,
        "alternatives": 4,
    }
    assert json.loads(json.dumps(result, sort_keys=True)) == result


@pytest.mark.parametrize("kwargs", [{"js_prior_threshold": 999},
    {"js_prior_threshold": True}, {"js_prior_top": 255}, {"js_prior_top": 256.0}])
def test_js_recipe_refuses_unpinned_parameters(kwargs):
    with pytest.raises(ValueError, match="pinned"):
        recipes.prepare_recipe("js-m1-shortlist", {}, **kwargs)


def test_asset_hash_and_file_guards(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.bin"
    path.write_bytes(b"synthetic, not a model")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(recipes._SHAS, "smv3", digest)
    assert recipes._asset({"smv3": path}, "smv3") == (str(path.resolve()), digest)
    path.write_bytes(b"different")
    with pytest.raises(ValueError, match="SHA256"):
        recipes._asset({"smv3": path}, "smv3")
    link = tmp_path / "link"
    link.symlink_to(path)
    for invalid in (link, tmp_path, tmp_path / "missing"):
        with pytest.raises(ValueError, match="regular"):
            recipes._asset({"smv3": invalid}, "smv3")
    with pytest.raises(ValueError, match="missing model"):
        recipes._asset({}, "smv3")


@pytest.mark.parametrize("entries", [{}, {"a": object(), "b": object()}])
def test_ambiguous_registration_refused(entries):
    with pytest.raises(ValueError, match="exactly one"):
        recipes._one_entry(entries)


def test_unknown_policy_refused():
    with pytest.raises(ValueError, match="unknown benchmark"):
        recipes.prepare_recipe("unregistered", {})
