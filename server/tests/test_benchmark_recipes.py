"""Synthetic source qualification; never load a checkpoint or call a provider."""
import hashlib

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
