import json

import pytest

from scripts import prepare_llm_panel_roots as producer
from scripts import w32_llm_benchmark as runner
from shengji.luna.benchmark_recipes import prepare_recipe
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL
from test_llm_benchmark_games import planner
from test_benchmark_retention import _write_source, _repin_report


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


@pytest.mark.parametrize('token_limit', [1000000, 7])
def test_feedback_exhaustion_real_scheduler_and_budget(tmp_path, token_limit):
    from shengji.luna.benchmark_terminal import validate_scheduled_terminal
    roots = tmp_path / 'roots'
    seeds = list(range(10))
    producer.prepare_roots(output=roots, seeds=seeds)
    recipe = prepare_recipe('smart', {})
    packets = []
    class IllegalTransport:
        def __init__(self, **options):
            self.calls = []
        def __call__(self, packet):
            packets.append(packet)
            self.calls.append({'usage': {'input_tokens': 5, 'output_tokens': 2}})
            return {'cards': [], 'memory': ''}
    report = runner.run_benchmark(
        checkpoint=None, policy=recipe.policy, prepared_recipe=recipe,
        prepared_roots_from=roots,
        prepared_roots_sha256=runner._sha_bytes((roots / 'result.json').read_bytes()),
        seeds=seeds, models=['sol'], output=tmp_path / 'output',
        run=True, token_limit=token_limit, invalid_action_feedback=True,
        classify_final_action_failures=True, failure_protocol=PRESERVE_ILLEGAL,
        transport_factory=IllegalTransport)
    if token_limit == 7:
        assert len(packets) == 1
        failed = report['mirrors'][0]
        assert len(failed['calls']) == len(failed['final_action_feedback']) == 1
        assert 'BudgetStop' in failed['error'] and 'failure' not in failed
        assert report['budget']['tokens'] == 7
        assert report['scheduled_summary']['blocked'] is True
        assert all(row['status'] == 'not_run' for row in report['mirrors'][1:])
        with pytest.raises(ValueError, match='unknown failure'):
            validate_scheduled_terminal(report, seeds=seeds)
    else:
        assert len(packets) == 24  # three calls per exhausted mirror, eight mirrors
        assert report['budget']['tokens'] == 168
        assert all(len(row['calls']) == len(row['final_action_feedback']) == 3
                   for row in report['mirrors'][:8])
        assert validate_scheduled_terminal(report, seeds=seeds) == {
            'status': 'failure-limit', 'completed': 0, 'failed': 8,
            'unattempted': 32, 'scheduled': 40}
    assert json.loads((tmp_path / 'output' / 'result.json').read_text()) == report


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


def _retention_fixture(kwargs, tmp_path):
    config = runner.run_benchmark(**kwargs)['config']
    # The one retained failure occurs LAST, but must count before first dispatch.
    plan, pin, _, source = _write_source(tmp_path, config=config, kinds={
        ('actor-only', 0): 'pending', ('actor-only', 1): 'complete',
        ('perfect', 0): 'complete', ('perfect', 1): 'typed'})
    report = json.loads((source / 'result.json').read_bytes())
    row = report['mirrors'][1]
    row['calls'] = [{'usage': {'input_tokens': 4, 'output_tokens': 3}}]
    path = source / f"mirror-sol-actor-only-{kwargs['seeds'][0]}-1.json"
    path.write_bytes(runner.canonical_json_bytes(row))
    pin = _repin_report(plan, source, report)
    return plan, pin, source


@pytest.mark.parametrize('limit,expected_new', [(1, 0), (2, 1)])
def test_retention_authenticates_and_counts_before_dispatch(kwargs, tmp_path, limit, expected_new):
    plan, pin, source = _retention_fixture(kwargs, tmp_path)
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    attempted = []
    def complete(game, **options):
        attempted.append((options['information'], options['flip']))
        return {'complete': True, 'signed_levels': 2}
    report = runner.run_benchmark(
        **kwargs, run=True, token_limit=1000000, runner=complete,
        failure_protocol=PRESERVE_ILLEGAL, classify_final_action_failures=True,
        illegal_failure_limit=limit, retention_plan=str(plan), retention_plan_sha256=pin)
    assert len(attempted) == expected_new
    assert report['scheduled_summary']['failed'] == 1  # never counted twice
    assert report['budget']['prior_tokens'] == report['budget']['combined_tokens'] == 7
    assert report['budget']['new_tokens'] == 0
    assert report['mirrors'][0]['complete'] is bool(expected_new)
    for row in report['mirrors'][1:]:
        assert row['lineage']['kind'] == 'retained-terminal-attempt'
        assert row['lineage']['retention_plan_sha256'] == pin
    assert {p.name: p.read_bytes() for p in source.iterdir()} == original
    assert report['retained_attempts'] == report['config']['retained_attempts']
    assert report['retained_attempts']['prior_cost_tokens'] == 7
    assert set(report['retained_attempts']) == {
        'plan', 'plan_sha256', 'source', 'result_sha256', 'prior_cost_tokens'}


@pytest.mark.parametrize('change', ['wrong_pin', 'missing_pin', 'missing_plan', 'default_protocol', 'continue'])
def test_bad_retention_refuses_before_output(kwargs, tmp_path, change):
    plan, pin, _ = _retention_fixture(kwargs, tmp_path)
    kwargs.update(retention_plan=str(plan), retention_plan_sha256=pin,
                  failure_protocol=PRESERVE_ILLEGAL, classify_final_action_failures=True)
    if change == 'wrong_pin':
        kwargs['retention_plan_sha256'] = '0' * 64
    elif change == 'missing_pin':
        kwargs['retention_plan_sha256'] = None
    elif change == 'missing_plan':
        kwargs['retention_plan'] = None
    elif change == 'default_protocol':
        kwargs.pop('failure_protocol')
    else:
        kwargs['continue_from'] = 'not-read'
    with pytest.raises(ValueError):
        runner.run_benchmark(**kwargs, run=True, token_limit=1000000)
    assert not kwargs['output'].exists()


def test_retention_dry_run_checks_plan_but_does_not_write(kwargs, tmp_path):
    plan, pin, _ = _retention_fixture(kwargs, tmp_path)
    report = runner.run_benchmark(
        **kwargs, retention_plan=str(plan), retention_plan_sha256=pin,
        failure_protocol=PRESERVE_ILLEGAL, classify_final_action_failures=True)
    assert report['mode'] == 'dry-run'
    assert report['config']['retained_attempts']['plan_sha256'] == pin
    assert not kwargs['output'].exists()


@pytest.mark.parametrize('limit', [6, 7])
@pytest.mark.parametrize('execute', [False, True])
def test_retained_cost_exhaustion_refuses_before_output(kwargs, tmp_path, limit, execute):
    plan, pin, _ = _retention_fixture(kwargs, tmp_path)
    with pytest.raises(runner.BenchmarkRefusal, match='exhaust soft token'):
        runner.run_benchmark(
            **kwargs, run=execute, token_limit=limit, retention_plan=str(plan),
            retention_plan_sha256=pin, failure_protocol=PRESERVE_ILLEGAL,
            classify_final_action_failures=True)
    assert not kwargs['output'].exists()


def test_retained_tokens_reduce_budget_for_new_provider_calls(kwargs, tmp_path):
    plan, pin, _ = _retention_fixture(kwargs, tmp_path)
    called = []
    class FakeTransport:
        def __init__(self, **options):
            self.calls = []
        def __call__(self, packet):
            called.append(packet)
            self.calls.append({'usage': {'input_tokens': 1, 'output_tokens': 0}})
            return {'cards': [], 'memory': ''}
    def two_calls(game, **options):
        provider = options['planner_factory'](0)
        provider({})
        provider({})  # must refuse: prior 7 + first new 1 reaches total ceiling 8
        raise AssertionError('budget failed to stop second provider call')
    report = runner.run_benchmark(
        **kwargs, run=True, token_limit=8, runner=two_calls,
        transport_factory=FakeTransport, retention_plan=str(plan),
        retention_plan_sha256=pin, failure_protocol=PRESERVE_ILLEGAL,
        classify_final_action_failures=True)
    assert len(called) == 1
    assert report['budget']['new_tokens'] == 1
    assert report['budget']['prior_tokens'] == 7
    assert report['budget']['combined_tokens'] == 8
    assert report['scheduled_summary']['blocked'] is True


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
