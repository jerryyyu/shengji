import copy
from dataclasses import asdict

import pytest

from shengji.eval.m9_panel_recipe import (
    POLICY, SAVED_READOUT_SHA256, SCHEMA, panel_model_environ, validate_panel_recipe,
    build_panel_worker_command,
)
from shengji.eval.observation_recipe import FIXTURE_SHA256, MODEL_SHA256, validate_recipe


def recipe():
    return dict(schema=SCHEMA, python="/env/bin/python", source_root="/source",
                model="/inputs/model.npz", fixtures="/source/fixtures.jsonl",
                saved_readout="/inputs/readout.json", output_dir="/outputs/panel",
                evidence="/outputs/process.json", model_sha256=MODEL_SHA256,
                fixture_sha256=FIXTURE_SHA256, saved_readout_sha256=SAVED_READOUT_SHA256,
                seeds=[0, 1, 2], fill_seed=0, runtime_profile="panel", policy=POLICY)


def test_recipe_is_distinct_from_original_command_and_immutable():
    value = recipe()
    before = copy.deepcopy(value)
    validate_panel_recipe(value)
    assert value == before
    with pytest.raises(ValueError, match="recipe keys"):
        validate_recipe(value)


def test_panel_worker_command_requires_explicit_mode_and_pinned_packet():
    spec = recipe()
    before = copy.deepcopy(spec)
    assert build_panel_worker_command(spec, "/packets/panel.json", "a" * 64) == (
        "/env/bin/python", "-I", "-B", "/source/server/scripts/observation_worker.py",
        "--panel", "--packet", "/packets/panel.json", "--sha256", "a" * 64)
    assert spec == before
    for bad_path, bad_sha in [("relative", "a" * 64), ("/p", "A" * 64),
                              ("/p", None), ("/p", "a" * 63)]:
        with pytest.raises(ValueError):
            build_panel_worker_command(spec, bad_path, bad_sha)


@pytest.mark.parametrize("field,value", [
    ("schema", "m9-admission-v1"), ("policy", "r36-smv3"),
    ("runtime_profile", "observation"), ("model_sha256", "0" * 64),
    ("fixture_sha256", "0" * 64), ("saved_readout_sha256", "0" * 64),
    ("seeds", [False, 1, 2]), ("seeds", [0, 1, 3]), ("seeds", (0, 1, 2)),
    ("fill_seed", False), ("fill_seed", 1),
])
def test_recipe_drift_refuses(field, value):
    spec = recipe()
    spec[field] = value
    with pytest.raises(ValueError, match=field):
        validate_panel_recipe(spec)


@pytest.mark.parametrize("field", list(recipe()))
def test_missing_fields_refuse(field):
    spec = recipe()
    del spec[field]
    with pytest.raises(ValueError, match="exact M9 panel recipe keys"):
        validate_panel_recipe(spec)


def test_unreviewed_overrides_refuse():
    spec = recipe()
    spec["tree"] = True
    with pytest.raises(ValueError, match="exact M9 panel recipe keys"):
        validate_panel_recipe(spec)


@pytest.mark.parametrize("field,value", [
    ("output_dir", "/source/out"), ("output_dir", "/inputs"),
    ("output_dir", "/inputs/readout.json"), ("evidence", "/outputs/panel/process.json"),
    ("evidence", "/outputs"), ("evidence", "/source/process.json"),
    ("saved_readout", "relative.json"), ("model", "/inputs/../model.npz"),
    ("output_dir", "/"),
])
def test_publication_aliases_refuse(field, value):
    spec = recipe()
    spec[field] = value
    with pytest.raises(ValueError, match="overlaps|absolute|aliases|root"):
        validate_panel_recipe(spec)


def test_model_environment_uses_frozen_treatment_without_model_construction(monkeypatch):
    from shengji.train import pv_search_policy as pv

    def forbidden(*args, **kwargs):
        raise AssertionError("must not load a model or construct a bot")

    monkeypatch.setattr(pv, "pv_registry_entries", forbidden)
    environment = panel_model_environ(recipe())
    resolved = pv.pv_env_recipe(environment)
    assert resolved.pop("checkpoint") == "/inputs/model.npz"
    assert resolved.pop("sha256") == MODEL_SHA256
    assert resolved.pop("bury_arm") == "hybrid"
    assert resolved.pop("bury_serving_budget_seconds") == 2.0
    assert asdict(resolved.pop("bury_config")) == dict(
        max_candidates=32, model_worlds=32, selection_worlds=32, alternatives=4)
    config = pv.PVSearchConfig(checkpoint_sha256=MODEL_SHA256, **resolved)
    assert pv.recipe_digest(config) == "7092480e"
    assert (config.worlds, config.candidates, config.cap, config.batch_size) == (64, 8, 4000, 128)
    assert config.tree is None and config.encoding == "mlp-static"
    assert config.serving_budget_seconds == 3.0
    assert {key for key in pv.RULE_FLAGS.values() if getattr(config, key)} == {
        "admission_diversity", "refusal_constraints", "tiebreak_points", "lead_anchor"}
    environment.clear()
    assert panel_model_environ(recipe())
