"""Pin M9's scientific recipe without constructing a model or a bot."""

import hashlib
from dataclasses import asdict

from scripts.tactical_report import _canonical_json
from shengji.eval import tactical
from shengji.eval.observation_recipe import FIXTURE_SHA256, MODEL_SHA256
from shengji.train import pv_search_policy as pv


def test_m9_resolved_numeric_recipe(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("recipe inspection must not construct a model/bot")

    monkeypatch.setattr(pv, "pv_registry_entries", forbidden)
    environs = tactical.observation_comparison_environs("/models/smv3.npz", MODEL_SHA256)
    assert set(environs) == {"r36-smv3", "div+rc+tb+la"}
    enabled = {"admission_diversity", "refusal_constraints", "tiebreak_points", "lead_anchor"}
    for label, environ in environs.items():
        resolved = pv.pv_env_recipe(environ)
        assert resolved.pop("checkpoint") == "/models/smv3.npz"
        assert resolved.pop("sha256") == MODEL_SHA256
        assert resolved.pop("bury_arm") == "hybrid"
        assert resolved.pop("bury_serving_budget_seconds") == 2.0
        assert asdict(resolved.pop("bury_config")) == {
            "max_candidates": 32, "model_worlds": 32,
            "selection_worlds": 32, "alternatives": 4,
        }
        config = pv.PVSearchConfig(checkpoint_sha256=MODEL_SHA256, **resolved)
        assert (config.worlds, config.candidates, config.cap, config.batch_size) == (64, 8, 4000, 128)
        assert config.serving_budget_seconds == 3.0
        assert config.encoding == "mlp-static"
        assert config.tree is None
        digest, name = {
            "r36-smv3": ("4a09aef5", "pv-search-491ee4bf-w64-k8-r4a09aef5"),
            "div+rc+tb+la": ("7092480e", "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e"),
        }[label]
        assert pv.recipe_digest(config) == digest
        assert pv.pv_policy_name(MODEL_SHA256[:8], config) == name
        assert {key for key in pv.RULE_FLAGS.values() if getattr(config, key)} == (
            enabled if label == "div+rc+tb+la" else set())
        payload = pv.recipe_payload(config)
        if label == "div+rc+tb+la":
            assert payload["max_per_structure"] == 2
            assert payload["tiebreak_epsilon"] == 0.02
        else:
            assert "max_per_structure" not in payload
            assert "tiebreak_epsilon" not in payload


def test_m9_public_fixture_pins():
    path = tactical.FIXTURES_PATH.with_name("public_observations.jsonl")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_SHA256
    fixtures = tactical.load_fixtures(path)
    assert len(fixtures) == 4
    assert all(fx.category == "observation" and fx.current_bot is None for fx in fixtures)
    assert hashlib.sha256(_canonical_json([fx.to_json() for fx in fixtures])).hexdigest() == (
        "f3d0c48ab6a077fdec6c83ebdd30550a801048edb1617b0037456a30e423e5e6")
