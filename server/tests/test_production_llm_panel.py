import itertools
from types import SimpleNamespace

import pytest
from scripts import production_llm_panel as panel
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL

FLAGS = ('capacity_retries', 'accept_recovered_reconnects',
         'invalid_action_feedback', 'classify_final_action_failures')


@pytest.fixture
def options():
    return dict(row='smart', model_paths={}, prepared_roots_from='/synthetic/roots',
                prepared_roots_sha256='a' * 64, output='/synthetic/out', seeds=(12,))


@pytest.mark.parametrize('values', list(itertools.product((False, True), repeat=4)))
def test_independent_controls_and_fixed_recipe(options, monkeypatch, values):
    monkeypatch.setattr(panel, 'run_benchmark', lambda **kw: kw)
    result = panel.run_row(**options, **dict(zip(FLAGS, values)))
    for key, value in zip(FLAGS, values):
        assert (key in result) is value
    assert result['run'] is False
    assert result['models'] == ('sol',)
    assert result['information'] == ('actor-only', 'perfect')
    assert result['token_limit'] == 45000000
    assert result['wall_seconds'] == 43200
    assert result['timeout_seconds'] == 300
    assert result['prepared_recipe'].identity['benchmark_id'] == 'smart'


@pytest.mark.parametrize('flag', FLAGS + ('run',))
def test_controls_refuse_truthy_nonbool_before_recipe(options, monkeypatch, flag):
    monkeypatch.setattr(panel, 'prepare_recipe', lambda *a: pytest.fail('recipe reached'))
    with pytest.raises(ValueError, match='bool'):
        panel.run_row(**options, **{flag: 1})


def test_retained_protocol_is_explicit_and_keeps_total_budget(options, monkeypatch):
    monkeypatch.setattr(panel, 'prepare_recipe', lambda *a: SimpleNamespace(identity={}, policy='synthetic'))
    monkeypatch.setattr(panel, 'run_benchmark', lambda **kw: kw)
    options['row'] = 'm1-prior'
    with pytest.raises(ValueError, match='attribution'):
        panel.run_row(**options, failure_protocol=PRESERVE_ILLEGAL)
    result = panel.run_row(**options, failure_protocol=PRESERVE_ILLEGAL,
                          classify_final_action_failures=True,
                          retention_plan='/synthetic/plan', retention_plan_sha256='b'*64)
    assert result['illegal_failure_limit'] == 8
    assert result['retention_plan_sha256'] == 'b'*64
    # The runner subtracts prior usage; do not subtract twice in this adapter.
    assert result['token_limit'] == 45000000


def test_cli_controls_reach_adapter_without_implied_run(monkeypatch):
    calls = []
    monkeypatch.setattr(panel, 'run_row', lambda **kw: calls.append(kw) or {})
    panel.main(['--row', 'smart', '--prepared-roots-from', '/synthetic/roots',
                '--prepared-roots-sha256', 'a'*64, '--output', '/synthetic/out',
                '--seeds', '12', '--retry-provider-capacity', '--accept-recovered-reconnects',
                '--invalid-action-feedback', '--classify-final-action-failures'])
    assert calls[0]['run'] is False
    assert all(calls[0][key] is True for key in FLAGS)


@pytest.mark.parametrize('extra,match', [
    ({'failure_protocol': 'unknown'}, 'protocol'),
    ({'retention_plan': '/synthetic/plan'}, 'together'),
    ({'retention_plan_sha256': 'b'*64}, 'together'),
    ({'retention_plan': '/synthetic/plan', 'retention_plan_sha256': 'b'*64}, 'amended M1'),
    ({'retention_plan': '/synthetic/plan', 'retention_plan_sha256': 'b'*64,
      'failure_protocol': PRESERVE_ILLEGAL, 'classify_final_action_failures': True}, 'amended M1'),
    ({'prepared_roots_from': None}, 'shared pinned roots'),
])
def test_invalid_contract_refuses_before_recipe(options, monkeypatch, extra, match):
    monkeypatch.setattr(panel, 'prepare_recipe', lambda *a: pytest.fail('recipe reached'))
    with pytest.raises(ValueError, match=match):
        panel.run_row(**(options | extra))


def test_real_runner_dry_run_no_output(tmp_path):
    from scripts.prepare_llm_panel_roots import prepare_roots
    import hashlib
    roots = tmp_path/'roots'
    prepare_roots(output=roots, seeds=[12])
    output = tmp_path/'out'
    result = panel.run_row(row='smart', model_paths={}, prepared_roots_from=roots,
                          prepared_roots_sha256=hashlib.sha256((roots/'result.json').read_bytes()).hexdigest(),
                          output=output, seeds=(12,), failure_protocol=PRESERVE_ILLEGAL,
                          classify_final_action_failures=True, invalid_action_feedback=True)
    assert result['mode'] == 'dry-run'
    assert result['planned_mirrors'] == 4
    assert not output.exists()
