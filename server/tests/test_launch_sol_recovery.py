import hashlib
import json
from pathlib import Path

import pytest

from scripts import launch_production_llm_panel as launcher
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL, summarize_scheduled
from test_launch_production_llm_panel import _config, _stub_validation, _real_validation_fixture


def _controls():
    return dict(recovery_controls=dict(capacity_retries=True,
                accept_recovered_reconnects=False, invalid_action_feedback=False,
                classify_final_action_failures=True),
                provider_capacity_retry_delays=[15, 30, 60])


@pytest.fixture(autouse=True)
def _safe_recovery_memory(monkeypatch):
    monkeypatch.setattr(launcher.benchmark_batch,
                        'assert_memory_headroom', lambda: True)


@pytest.fixture(autouse=True)
def _safe_recovery_release(monkeypatch):
    monkeypatch.setattr(launcher, '_require_recovery_release', lambda *args: None)


def _retention(tmp_path):
    plan = tmp_path / 'retention.json'
    plan.write_text(json.dumps({'source_directory': '/sealed', 'result_sha256': 'b' * 64}))
    return {'m1-prior': {'plan': str(plan), 'sha256': 'a' * 64}}


def _binding():
    return {'source': '/sealed', 'result_sha256': 'b' * 64, 'plan_sha256': 'a' * 64}


def _stage1(config):
    config.update(schema=launcher.STAGE1_SCHEMA, rows=list(launcher.STAGE1_ROWS),
                  **_controls(), failure_protocol=PRESERVE_ILLEGAL,
                  illegal_failure_limit=8)
    config['recovery_controls']['invalid_action_feedback'] = True
    return config


@pytest.mark.parametrize('mutation', ['none', 'rows', 'order', 'feedback', 'retention', 'binary', 'limit', 'tokens', 'reconnect'])
@pytest.mark.parametrize('stage', [1, 2])
def test_fresh_stage1_recipe_validation(tmp_path, mutation, stage):
    path, _, _ = _real_validation_fixture(tmp_path)
    config = _stage1(json.loads(path.read_text()))
    rows = launcher.STAGE1_ROWS if stage == 1 else launcher.STAGE2_ROWS
    if stage == 2:
        config.update(schema=launcher.STAGE2_SCHEMA, rows=list(rows))
    if mutation == 'rows':
        config['rows'] = list(launcher.ROWS)
    elif mutation == 'order':
        config['rows'].reverse()
    elif mutation == 'tokens':
        config['row_soft_tokens'] += 1
    elif mutation == 'reconnect':
        config['recovery_controls']['accept_recovered_reconnects'] = True
    elif mutation == 'feedback':
        config['recovery_controls']['invalid_action_feedback'] = False
    elif mutation == 'retention':
        config['retention'] = {}
    elif mutation == 'binary':
        config.pop('codex_binary_sha256')
    elif mutation == 'limit':
        config['illegal_failure_limit'] = True
    path.write_text(json.dumps(config))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if mutation != 'none':
        with pytest.raises(ValueError):
            launcher.validate(path, digest)
    else:
        actual, stamps = launcher.validate(path, digest)
        assert actual['rows'] == list(rows)
        launcher.fence(stamps)


@pytest.mark.parametrize('refuse_first', [False, True])
@pytest.mark.parametrize('stage', [1, 2])
def test_stage1_dispatch_and_terminal_path(tmp_path, monkeypatch, refuse_first, stage):
    from scripts import production_llm_panel_readout
    monkeypatch.setattr(production_llm_panel_readout, 'analyze_panel',
                        lambda *a, **kw: pytest.fail('stage1 sent to nine-row reader'))
    config = _stage1(_config(tmp_path))
    rows = launcher.STAGE1_ROWS if stage == 1 else launcher.STAGE2_ROWS
    if stage == 2:
        config.update(schema=launcher.STAGE2_SCHEMA, rows=list(rows))
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, 'LOCK', tmp_path / 'lock')
    assert launcher.run(tmp_path / 'config.json', 'synthetic') == {
        'status': 'unarmed', 'rows': len(rows), 'rounds': 40 * len(rows)}
    assert not Path(config['output']).exists()
    releases = []
    monkeypatch.setattr(launcher, '_require_recovery_release',
                        lambda *args: releases.append(args))
    seen = []

    def supervise(command, *, row, output, **kwargs):
        seen.append(row)
        assert '--retention-plan' not in command
        assert '--invalid-action-feedback' in command
        assert '--classify-final-action-failures' in command
        assert command.count('--retry-provider-capacity') == 1
        output.mkdir()
        report = _report(config['seeds'], failures=0, pending=refuse_first)
        report['config']['invalid_action_feedback'] = True
        (output / 'result.json').write_text(json.dumps(report))
        return {'returncode': 0, 'status': 'exited', 'row': row}

    monkeypatch.setattr(launcher, 'supervise', supervise)
    if refuse_first:
        with pytest.raises(ValueError):
            launcher.run(tmp_path / 'config.json', 'synthetic', arm=True)
        assert seen == [rows[0]]
    else:
        result = launcher.run(tmp_path / 'config.json', 'synthetic', arm=True)
        assert result['status'] == 'scheduled-terminal'
        assert seen == list(rows)
    assert len(releases) == 1 + len(seen)
    output = tmp_path / 'campaign-output'
    summary = json.loads((output / f'stage{stage}-summary.json').read_text())
    assert summary['required_prior_rows'] == ([] if stage == 1 else list(launcher.STAGE1_ROWS))
    assert set(summary['rows']) == set(rows)
    assert summary['status'] == ('failed' if refuse_first else 'scheduled-terminal')
    assert not (output / 'panel-readout.json').exists()
    assert not (output / 'recovery-summary.json').exists()


@pytest.mark.parametrize('mutation', ['omit', 'substitute'])
def test_external_config_digest_binds_transport_declaration(tmp_path, mutation):
    config = {'schema': launcher.RECOVERY_SCHEMA,
              'transport_amendment': {'sha256': 'a' * 64, 'reference': 'reviewed'}}
    path = tmp_path / 'packet.json'
    path.write_text(json.dumps(config))
    released_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if mutation == 'omit':
        config.pop('transport_amendment')
    else:
        config['transport_amendment'] = {'sha256': 'b' * 64, 'reference': 'other'}
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='campaign config hash mismatch'):
        launcher.validate(path, released_digest)


def _report(seeds, failures=1, pending=False):
    rows = []
    for mode in ('actor-only', 'perfect'):
        for seed in seeds:
            for flip in (0, 1):
                row = dict(schema='w32-llm-benchmark-mirror-v1',
                           key=f'sol-{mode}-seed{seed}-flip{flip}', arm=f'sol-{mode}',
                           model='sol', information=mode, seed=seed, flip=flip,
                           complete=True, signed_levels=1, calls=[])
                if len(rows) < failures:
                    row.pop('signed_levels')
                    row.update(complete=False, error='IllegalPlay: rejected',
                               events=[dict(seat=flip, attempted_cards=['C7'])],
                               failure=dict(schema='benchmark-action-failure-v1',
                                            category='model_illegal_action', stage='engine_play',
                                            seat=flip, attempted_cards=['C7'], event_index=0))
                elif pending:
                    row.pop('signed_levels')
                    row.update(complete=False, status='not_run')
                rows.append(row)
    return dict(schema='w32-llm-benchmark-v1', mode='run',
                config=dict(failure_protocol=PRESERVE_ILLEGAL, illegal_failure_limit=8,
                            seeds=seeds, models=['sol'], information=['actor-only', 'perfect']),
                mirrors=rows, scheduled_summary=summarize_scheduled(rows))


@pytest.mark.parametrize('capacity,reconnect,feedback', [
    (a, b, c) for a in (False, True) for b in (False, True) for c in (False, True)])
@pytest.mark.parametrize('failures,pending', [(1, False), (8, True)])
def test_recovery_dispatches_exact_six_rows_without_retry(
        tmp_path, monkeypatch, failures, pending, capacity, reconnect, feedback):
    from scripts import production_llm_panel_readout
    monkeypatch.setattr(production_llm_panel_readout, 'analyze_panel',
                        lambda *a, **kw: pytest.fail('six rows sent to nine-row reader'))
    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, **_controls(),
                  retention=_retention(tmp_path))
    config['recovery_controls'].update(capacity_retries=capacity,
        accept_recovered_reconnects=reconnect, invalid_action_feedback=feedback)
    config['provider_capacity_retry_delays'] = [15, 30, 60] if capacity else []
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, 'LOCK', tmp_path / 'lock')
    seen = []

    def supervise(command, *, row, output, **kwargs):
        seen.append(row)
        for key, flag in launcher.CONTROL_FLAGS.items():
            assert command.count(flag) == int(config['recovery_controls'][key])
        assert command[command.index('--failure-protocol') + 1] == PRESERVE_ILLEGAL
        assert ('--retention-plan' in command) == (row == 'm1-prior')
        output.mkdir()
        report = _report(config['seeds'], failures, pending)
        if row == 'm1-prior':
            report['config']['retained_attempts'] = _binding()
        (output / 'result.json').write_text(json.dumps(report))
        return {'returncode': 0, 'status': 'exited', 'row': row}

    monkeypatch.setattr(launcher, 'supervise', supervise)
    result = launcher.run(tmp_path / 'config.json', 'synthetic', arm=True)
    assert seen == list(launcher.RECOVERY_ROWS)
    assert result['status'] == 'scheduled-terminal'
    accounting = json.loads((tmp_path / 'campaign-output/m1-prior.accounting.json').read_text())
    assert accounting['failed'] == failures
    output = tmp_path / 'campaign-output'
    summary = json.loads((output / 'recovery-summary.json').read_text())
    assert summary['status'] == 'scheduled-terminal'
    assert summary['scientific_readout'] == 'pending-aligned-nine-row-reader'
    assert summary['required_prior_rows'] == list(launcher.ROWS[:3])
    assert set(summary['rows']) == set(launcher.RECOVERY_ROWS)
    assert all(row['failed'] == failures for row in summary['rows'].values())
    assert not (output / 'panel-readout.json').exists()
    assert not (output / 'readout-error.json').exists()


@pytest.mark.parametrize('bad', [None, {}, True, {
    **_controls()['recovery_controls'], 'extra': False}, {
    **_controls()['recovery_controls'], 'classify_final_action_failures': False}])
def test_explicit_controls_required(bad):
    config = _controls()
    config['recovery_controls'] = bad
    with pytest.raises(ValueError, match='strict-bool'):
        launcher.recovery_control_args(config)


@pytest.mark.parametrize('key', list(launcher.CONTROL_FLAGS))
@pytest.mark.parametrize('bad', [0, 1, 'true', None])
def test_control_values_are_strict_bools(key, bad):
    config = _controls()
    config['recovery_controls'][key] = bad
    with pytest.raises(ValueError, match='strict-bool'):
        launcher.recovery_control_args(config)


def test_retry_declaration_must_match_controls():
    config = _controls()
    config['provider_capacity_retry_delays'] = []
    with pytest.raises(ValueError, match='retry declaration'):
        launcher.recovery_control_args(config)


def test_recovery_incomplete_below_cap_stops_campaign(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, **_controls(),
                  retention=_retention(tmp_path))
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, 'LOCK', tmp_path / 'lock')
    seen = []
    def supervise(command, *, row, output, **kwargs):
        seen.append(row)
        output.mkdir()
        report = _report(config['seeds'], 1, True)
        report['config']['retained_attempts'] = _binding()
        (output / 'result.json').write_text(json.dumps(report))
        return {'returncode': 0, 'status': 'exited', 'row': row}
    monkeypatch.setattr(launcher, 'supervise', supervise)
    with pytest.raises(ValueError):
        launcher.run(tmp_path / 'config.json', 'synthetic', arm=True)
    assert seen == ['m1-prior']
    assert (tmp_path / 'campaign-output/m1-prior/result.json').exists()
    summary = json.loads((tmp_path / 'campaign-output/recovery-summary.json').read_text())
    assert summary['status'] == 'failed'
    assert all(row['status'] == 'not-terminally-validated'
               for row in summary['rows'].values())


@pytest.mark.parametrize('missing_runtime_pin', [False, True])
def test_recovery_config_and_plan_fence(tmp_path, missing_runtime_pin):
    path, _, _ = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    source = tmp_path / 'prior'
    source.mkdir()
    (source / 'result.json').write_text('{}')
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps({'source_directory': str(source)}))
    config.update(schema=launcher.RECOVERY_SCHEMA, rows=list(launcher.RECOVERY_ROWS),
                  **_controls(),
                  failure_protocol=PRESERVE_ILLEGAL, illegal_failure_limit=8,
                  retention={'m1-prior': {'plan': str(plan),
                             'sha256': hashlib.sha256(plan.read_bytes()).hexdigest()}})
    if missing_runtime_pin:
        del config['codex_binary_sha256']
    path.write_text(json.dumps(config))
    if missing_runtime_pin:
        with pytest.raises(ValueError, match='Codex binary SHA256 pin required'):
            launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())
        return
    _, stamps = launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())
    launcher.fence(stamps)
    plan.write_text(plan.read_text() + '\n')
    with pytest.raises(ValueError, match='changed after validation'):
        launcher.fence(stamps)
    with pytest.raises(ValueError, match='retention plan hash'):
        launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_recovery_memory_unsafe_before_reservation_creates_nothing(tmp_path, monkeypatch):
    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, **_controls(),
                  retention=_retention(tmp_path))
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, 'LOCK', tmp_path / 'lock')
    monkeypatch.setattr(launcher.benchmark_batch, 'assert_memory_headroom',
                        lambda: False)
    monkeypatch.setattr(launcher, 'supervise',
                        lambda *args, **kwargs: pytest.fail('provider launched'))

    with pytest.raises(ValueError, match='memory headroom unsafe before reservation'):
        launcher.run(tmp_path / 'config.json', 'synthetic', arm=True)
    assert not Path(config['output']).exists()
    assert not (tmp_path / 'lock').exists()


def test_recovery_memory_pressure_between_rows_preserves_completed_row(
        tmp_path, monkeypatch):
    from shengji.luna import benchmark_terminal

    config = _config(tmp_path)
    config.update(schema=launcher.RECOVERY_SCHEMA, **_controls(),
                  retention=_retention(tmp_path))
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher, 'LOCK', tmp_path / 'lock')
    levels = iter((True, True, False))
    monkeypatch.setattr(launcher.benchmark_batch, 'assert_memory_headroom',
                        lambda: next(levels))
    monkeypatch.setattr(
        benchmark_terminal, 'validate_scheduled_terminal',
        lambda report, **kwargs: {'status': 'scheduled-terminal',
                                  'completed': 40, 'failed': 0,
                                  'unattempted': 0, 'scheduled': 40})
    dispatched = []

    def supervise(command, *, row, output, **kwargs):
        dispatched.append(row)
        output.mkdir()
        (output / 'result.json').write_text('{}')
        return {'returncode': 0, 'status': 'exited', 'row': row}

    monkeypatch.setattr(launcher, 'supervise', supervise)
    with pytest.raises(ValueError, match='memory headroom unsafe before row'):
        launcher.run(tmp_path / 'config.json', 'synthetic', arm=True)
    assert dispatched == [launcher.RECOVERY_ROWS[0]]
    output = Path(config['output'])
    assert (output / launcher.RECOVERY_ROWS[0] / 'result.json').exists()
    assert not (output / launcher.RECOVERY_ROWS[1]).exists()


def test_legacy_unarmed_path_does_not_apply_recovery_memory_gate(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _stub_validation(monkeypatch, config)
    monkeypatch.setattr(launcher.benchmark_batch, 'assert_memory_headroom',
                        lambda: pytest.fail('legacy memory gate invoked'))
    assert launcher.run(tmp_path / 'config.json', 'synthetic', arm=False)['status'] \
        == 'unarmed'


@pytest.mark.parametrize('field,value', [('rows', list(launcher.ROWS)),
                                      ('illegal_failure_limit', 9),
                                      ('failure_protocol', 'fail-stop-v1'),
                                      ('retention', {})])
def test_recovery_recipe_drift_refuses(tmp_path, field, value):
    path, _, _ = _real_validation_fixture(tmp_path)
    config = json.loads(path.read_text())
    config.update(schema=launcher.RECOVERY_SCHEMA, rows=list(launcher.RECOVERY_ROWS),
                  **_controls(),
                  failure_protocol=PRESERVE_ILLEGAL, illegal_failure_limit=8,
                  retention={'m1-prior': {'plan': '/missing', 'sha256': 'a' * 64}})
    config[field] = value
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='drift'):
        launcher.validate(path, hashlib.sha256(path.read_bytes()).hexdigest())
