import json

import pytest

from scripts import prepare_llm_panel_roots as producer
from scripts import w32_llm_benchmark as runner
from shengji.luna.benchmark_recipes import prepare_recipe
from test_llm_benchmark_games import planner


@pytest.fixture
def kwargs(tmp_path):
    roots = tmp_path / "roots"
    producer.prepare_roots(output=roots, seeds=[7123])
    recipe = prepare_recipe("smart", {})
    return dict(checkpoint=None, policy=recipe.policy, prepared_recipe=recipe,
                prepared_roots_from=roots,
                prepared_roots_sha256=runner._sha_bytes((roots / "result.json").read_bytes()),
                seeds=[7123], models=["sol"], output=tmp_path / "output")


def test_prepared_dry_run_creates_nothing(kwargs):
    result = runner.run_benchmark(**kwargs)
    assert result["mode"] == "dry-run"
    assert result["planned_mirrors"] == 4
    assert result["config"]["checkpoint"] is None
    assert result["config"]["baseline_recipe"]["benchmark_id"] == "smart"
    assert result["prepared_roots"]["result_sha256"] == kwargs["prepared_roots_sha256"]
    assert not kwargs["output"].exists()


def test_prepared_real_engine_fake_planner_keeps_exact_roots(kwargs):
    class FakeTransport:
        def __init__(self, **options):
            self.calls = []
        def __call__(self, packet):
            return planner(packet)
    def forbidden(*args, **options):
        raise AssertionError("prepared path must not deal or register a baseline")
    report = runner.run_benchmark(**kwargs, run=True, token_limit=1000000,
        transport_factory=FakeTransport, prepare_fn=forbidden,
        register_fn=forbidden, bot_factory=forbidden)
    assert len(report["mirrors"]) == 4
    assert all(row["complete"] for row in report["mirrors"])
    assert report["setup_failures"] == {}
    original = json.loads((kwargs["prepared_roots_from"] / "result.json").read_bytes())
    assert report["roots"] == original["roots"]
    assert report["prepared_roots"]["root_hashes"] == original["roots"]
    assert (kwargs["output"] / "root-7123.json").read_bytes() == (
        kwargs["prepared_roots_from"] / "root-7123.json").read_bytes()


@pytest.mark.parametrize("change", ["pin", "missing_pin", "missing_roots", "continue",
                                   "override", "checkpoint", "policy", "recipe_type"])
def test_prepared_mismatch_refused_before_output(kwargs, change):
    if change == "pin":
        kwargs["prepared_roots_sha256"] = "0" * 64
    elif change == "missing_pin":
        kwargs["prepared_roots_sha256"] = None
    elif change == "missing_roots":
        kwargs["prepared_roots_from"] = None
    elif change == "continue":
        kwargs["continue_from"] = "not-read"
    elif change == "override":
        kwargs["baseline_factory"] = lambda *a: None
    elif change == "checkpoint":
        kwargs["checkpoint"] = "not-read"
    elif change == "policy":
        kwargs["policy"] = "mc"
    else:
        kwargs["prepared_recipe"] = object()
    with pytest.raises(runner.BenchmarkRefusal):
        runner.run_benchmark(**kwargs)
    assert not kwargs["output"].exists()
