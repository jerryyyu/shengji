import json

import pytest

from scripts import prepare_llm_panel_roots as producer
from scripts import w32_llm_benchmark as runner
from shengji.luna.benchmark_recipes import prepare_recipe
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL
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


@pytest.mark.parametrize("feedback", [False, True])
@pytest.mark.parametrize("attribution", [False, True])
def test_action_controls_reach_real_mirrors_independently(kwargs, feedback, attribution):
    seen = []
    class FakeTransport:
        def __init__(self, **options):
            self.calls = []
        def __call__(self, packet):
            return planner(packet)
    def checked_mirror(game, **options):
        assert options.get('invalid_action_feedback', False) is feedback
        assert options.get('classify_final_action_failures', False) is attribution
        assert ('invalid_action_feedback' in options) is feedback
        assert ('classify_final_action_failures' in options) is attribution
        seen.append(options['flip'])
        return runner.play_mirror(game, **options)
    report = runner.run_benchmark(
        **kwargs, run=True, token_limit=1000000,
        invalid_action_feedback=feedback, classify_final_action_failures=attribution,
        runner=checked_mirror, transport_factory=FakeTransport)
    assert len(seen) == 4
    assert ('invalid_action_feedback' in report['config']) is feedback
    assert ('classify_final_action_failures' in report['config']) is attribution
    assert all(row['complete'] for row in report['mirrors'])
    assert all(row['invalid_action_feedback'] is feedback for row in report['mirrors'])
    assert all(('classify_final_action_failures' in row) is attribution
               for row in report['mirrors'])


def test_attributed_illegal_action_still_stops_panel(kwargs):
    calls = []
    class IllegalTransport:
        def __init__(self, **options):
            self.calls = []
        def __call__(self, packet):
            calls.append(packet)
            return {'cards': [], 'memory': ''}
    report = runner.run_benchmark(
        **kwargs, run=True, token_limit=1000000,
        classify_final_action_failures=True, transport_factory=IllegalTransport)
    failed, *pending = report['mirrors']
    assert calls and failed['complete'] is False
    assert failed['failure']['category'] == 'model_illegal_action'
    assert failed['failure']['stage'] == 'engine_play'
    assert 'signed_levels' not in failed
    assert len(pending) == 3
    assert all(row['status'] == 'not_run' and row['calls'] == [] for row in pending)


@pytest.mark.parametrize('limit', [1, 2, 8])
def test_preserve_protocol_counts_real_illegal_actions_without_retry(kwargs, limit):
    calls = []
    class IllegalTransport:
        def __init__(self, **options):
            self.calls = []
        def __call__(self, packet):
            calls.append(packet)
            return {'cards': [], 'memory': ''}
    report = runner.run_benchmark(
        **kwargs, run=True, token_limit=1000000,
        classify_final_action_failures=True, failure_protocol=PRESERVE_ILLEGAL,
        illegal_failure_limit=limit, transport_factory=IllegalTransport)
    attempted = min(limit, 4)
    assert len(calls) == attempted
    assert len(report['mirrors']) == 4
    assert len({row['key'] for row in report['mirrors']}) == 4
    assert all(row['failure']['category'] == 'model_illegal_action'
               for row in report['mirrors'][:attempted])
    assert all(row['status'] == 'not_run' for row in report['mirrors'][attempted:])
    assert all(not row['complete'] and 'signed_levels' not in row
               for row in report['mirrors'])
    assert report['scheduled_summary']['failed'] == attempted
    assert report['scheduled_summary']['stop_required'] is (limit <= 4)
    assert report['config']['illegal_failure_limit'] == limit


@pytest.mark.parametrize('throws', [False, True])
def test_preserve_protocol_infrastructure_failure_blocks_summary(kwargs, throws):
    attempted = []
    def broken(game, **options):
        attempted.append(options['flip'])
        if throws:
            raise RuntimeError('synthetic timeout')
        return {'complete': False, 'error': 'synthetic timeout'}
    report = runner.run_benchmark(
        **kwargs, run=True, token_limit=1000000, runner=broken,
        classify_final_action_failures=True, failure_protocol=PRESERVE_ILLEGAL)
    assert len(attempted) == 1
    assert report['scheduled_summary']['blocked'] is True
    assert report['scheduled_summary']['blocked_reason']['category'] == 'unclassified_infrastructure_failure'
    assert all(row['status'] == 'not_run' for row in report['mirrors'][1:])


@pytest.mark.parametrize('change', [
    {'failure_protocol': 'retry'}, {'illegal_failure_limit': True},
    {'illegal_failure_limit': 0}, {'illegal_failure_limit': 8.0},
    {'classify_final_action_failures': False}, {'models': ['luna']},
])
def test_preserve_protocol_invalid_configuration_refuses(kwargs, change):
    kwargs.update(failure_protocol=PRESERVE_ILLEGAL, classify_final_action_failures=True)
    kwargs.update(change)
    with pytest.raises(runner.BenchmarkRefusal):
        runner.run_benchmark(**kwargs)
    assert not kwargs['output'].exists()


def test_preserve_protocol_keeps_complete_and_forfeit_endpoints_separate(kwargs):
    attempted = []
    def mixed(game, **options):
        attempted.append((options['information'], options['flip']))
        if len(attempted) == 1:
            return {'complete': False, 'error': 'IllegalPlay: synthetic',
                    'events': [{'seat': 0, 'attempted_cards': []}],
                    'failure': {'schema': 'benchmark-action-failure-v1',
                                'category': 'model_illegal_action', 'stage': 'engine_play',
                                'seat': 0, 'attempted_cards': [], 'event_index': 0}}
        return {'complete': True, 'signed_levels': 3}
    report = runner.run_benchmark(
        **kwargs, run=True, token_limit=1000000, runner=mixed,
        classify_final_action_failures=True, failure_protocol=PRESERVE_ILLEGAL)
    assert len(attempted) == len(set(attempted)) == 4
    modes = report['scheduled_summary']['modes']
    assert modes['actor-only']['completed_paired_mean'] is None
    assert modes['actor-only']['forfeit_paired_mean'] == 1
    assert modes['perfect']['completed_paired_mean'] == 3
    assert modes['perfect']['forfeit_paired_mean'] == 3


@pytest.mark.parametrize("capacity", [False, True])
@pytest.mark.parametrize("reconnect", [False, True])
def test_prepared_real_engine_fake_planner_keeps_exact_roots(kwargs, capacity, reconnect):
    constructed = []
    class FakeTransport:
        def __init__(self, **options):
            constructed.append(options)
            self.calls = []
        def __call__(self, packet):
            return planner(packet)
    def forbidden(*args, **options):
        raise AssertionError("prepared path must not deal or register a baseline")
    report = runner.run_benchmark(**kwargs, run=True, token_limit=1000000,
        capacity_retries=capacity, accept_recovered_reconnects=reconnect,
        transport_factory=FakeTransport, prepare_fn=forbidden,
        register_fn=forbidden, bot_factory=forbidden)
    assert len(report["mirrors"]) == 4
    assert all(row["complete"] for row in report["mirrors"])
    assert report["setup_failures"] == {}
    assert len(constructed) == 8
    for options in constructed:
        assert callable(options["deadline_provider"])
        if capacity:
            assert options["capacity_retry_delays"] == (15, 30, 60)
        else:
            assert "capacity_retry_delays" not in options
        if reconnect:
            assert options["accept_recovered_reconnects"] is True
        else:
            assert "accept_recovered_reconnects" not in options
    assert ("provider_capacity_retry_delays" in report["config"]) is capacity
    assert ("accept_recovered_reconnects" in report["config"]) is reconnect
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


@pytest.mark.parametrize("flag", ["capacity_retries", "accept_recovered_reconnects",
                                  "invalid_action_feedback", "classify_final_action_failures"])
@pytest.mark.parametrize("invalid", [0, 1, "true", None])
def test_recovery_flags_require_strict_bool(kwargs, flag, invalid):
    with pytest.raises(runner.BenchmarkRefusal, match="boolean"):
        runner.run_benchmark(**kwargs, **{flag: invalid})
    assert not kwargs["output"].exists()


@pytest.mark.parametrize("flag", ["capacity_retries", "accept_recovered_reconnects",
                                  "invalid_action_feedback", "classify_final_action_failures"])
@pytest.mark.parametrize("models", [["luna"], ["sol", "luna"], ["sol", "sol"]])
def test_recovery_requires_sol_only(kwargs, flag, models):
    kwargs["models"] = models
    with pytest.raises(runner.BenchmarkRefusal, match="explicit Sol"):
        runner.run_benchmark(**kwargs, **{flag: True})
    assert not kwargs["output"].exists()


@pytest.mark.parametrize("flag", ["capacity_retries", "accept_recovered_reconnects",
                                  "invalid_action_feedback", "classify_final_action_failures"])
def test_recovery_refuses_legacy_path(kwargs, monkeypatch, flag):
    kwargs["prepared_recipe"] = None
    monkeypatch.setattr(runner, "_checkpoint_identity", lambda path: {})
    with pytest.raises(runner.BenchmarkRefusal, match="explicit Sol"):
        runner.run_benchmark(**kwargs, **{flag: True})
    assert not kwargs["output"].exists()


@pytest.mark.parametrize("raise_error", [False, True])
@pytest.mark.parametrize("failure_index", [0, 1])
def test_prepared_panel_stops_after_first_incomplete(kwargs, raise_error, failure_index):
    attempted = []
    def fake_runner(game, **options):
        attempted.append((options["information"], options["flip"]))
        if len(attempted) - 1 == failure_index:
            if raise_error:
                raise RuntimeError("synthetic failure")
            return {"complete": False, "error": "synthetic failure"}
        return {"complete": True, "signed_levels": 0}
    report = runner.run_benchmark(**kwargs, run=True, token_limit=1000000,
                                  runner=fake_runner)
    assert len(attempted) == failure_index + 1
    rows = report["mirrors"]
    assert len(rows) == 4
    assert sum(row["complete"] for row in rows) == failure_index
    assert "synthetic failure" in rows[failure_index]["error"]
    for row in rows[failure_index + 1:]:
        assert row["status"] == "not_run"
        assert row["calls"] == []
        assert "signed_levels" not in row
    assert len({row["key"] for row in rows}) == 4
