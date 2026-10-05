"""Metadata admission for the three-prior/six-recovery Sol readout.

This is NOT the scientific reader or permission to read results. It verifies
the terminal/config/retention metadata first, without opening game results.
A later consumer must authenticate the pinned result bytes, reuse terminal
and retention validation, and score those same bytes (not reopen paths).
"""
from pathlib import Path

from .benchmark_failure_protocol import PRESERVE_ILLEGAL
from .benchmark_retention import _directory, _hex, _json, _read, _strict_equal

ROWS = ('smv3-pv', 'soft-pv', 'js-m1-shortlist', 'm1-prior',
        'w32-original', 'mc-lcb', 'mc-strong', 'mc', 'smart')
SCHEMA = 'sol-aligned-panel-seals-v1'


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _ref(value):
    _require(type(value) is dict and set(value) == {'path', 'sha256'}, 'invalid artifact reference')
    _require(type(value['path']) is str, 'artifact path must be a string')
    path = Path(value['path'])
    _require(path.is_absolute() and '..' not in path.parts, 'artifact path must be absolute without traversal')
    _hex(value['sha256'], 'artifact digest')
    return path


def _metadata(ref, label):
    path = _ref(ref)
    _directory(path.parent, label)
    raw, digest = _read(path, label)
    _require(digest == ref['sha256'], f'{label}: SHA mismatch')
    value = _json(raw, label)
    _require(type(value) is dict, f'{label}: object required')
    return value


def _at(ref, expected):
    _require(_ref(ref) == expected, f'artifact must be {expected}')


def _row_exit(value, row):
    _require(type(value) is dict and value.get('row') == row
             and value.get('status') == 'exited'
             and type(value.get('returncode')) is int and value['returncode'] == 0,
             f'{row}: clean row exit required')


def admit_panel_metadata(plan_path, expected_sha256):
    """Authenticate metadata only; result refs returned remain UNVERIFIED."""
    plan = _metadata({'path': str(plan_path), 'sha256': expected_sha256}, 'readout plan')
    _require(set(plan) == {'schema', 'campaigns', 'rows', 'retention_plan', 'retained_result'}
             and plan['schema'] == SCHEMA, 'unknown readout plan')
    _require(type(plan['campaigns']) is dict and set(plan['campaigns']) == {'prior', 'recovery'},
             'exact two campaigns required')
    _require(type(plan['rows']) is dict and set(plan['rows']) == set(ROWS), 'exact nine rows required')
    configs, terminals = {}, {}
    for name in ('prior', 'recovery'):
        refs = plan['campaigns'][name]
        keys = {'config', 'output_config', 'terminal'} | ({'summary'} if name == 'recovery' else set())
        _require(type(refs) is dict and set(refs) == keys, 'campaign reference keys')
        config = _metadata(refs['config'], name + ' config')
        output = Path(config.get('output', ''))
        _require(output.is_absolute(), 'absolute campaign output required')
        _at(refs['output_config'], output / 'config.json')
        _at(refs['terminal'], output / 'terminal.json')
        _require(_strict_equal(config, _metadata(refs['output_config'], name + ' output config')),
                 'output config differs from pinned launch config')
        terminal = _metadata(refs['terminal'], name + ' terminal')
        _require(terminal.get('config_sha256') == refs['config']['sha256'], 'terminal config mismatch')
        expected_rows = list(ROWS if name == 'prior' else ROWS[3:])
        schemas = ('sol-nine-policy-campaign-v1', 'sol-nine-policy-campaign-v2') if name == 'prior' else ('sol-six-row-recovery-v1',)
        _require(config.get('schema') in schemas and config.get('rows') == expected_rows,
                 'campaign schema or row order mismatch')
        seeds = config.get('seeds')
        _require(type(seeds) is list and len(seeds) == 10
                 and all(type(s) is int for s in seeds) and len(set(seeds)) == 10, 'ten exact integer seeds required')
        _hex(config.get('prepared_roots_sha256'), 'prepared roots digest')
        _require(type(config.get('prepared_roots')) is str and Path(config['prepared_roots']).is_absolute(),
                 'prepared roots path missing')
        _require(terminal.get('status') == ('failed' if name == 'prior' else 'scheduled-terminal'),
                 'campaign not terminal for aligned read')
        rows = terminal.get('rows')
        # The historical campaign sealed three complete rows and then stopped
        # validating M1's result (its worker itself exited zero). Only its first
        # three rows enter this readout; the fourth is the retention source.
        _require(type(rows) is list and len(rows) == (4 if name == 'prior' else 6), 'terminal row cardinality')
        names = [r.get('row') if type(r) is dict else None for r in rows]
        _require(names == expected_rows[:len(names)], 'terminal rows not ordered unique prefix')
        if name == 'recovery':
            _require(config.get('failure_protocol') == PRESERVE_ILLEGAL
                     and type(config.get('illegal_failure_limit')) is int
                     and config['illegal_failure_limit'] == 8, 'recovery failure protocol mismatch')
        else:
            _row_exit(rows[3], 'm1-prior')
        configs[name], terminals[name] = config, terminal

    prior, recovery = configs['prior'], configs['recovery']
    for key in ('seeds', 'prepared_roots', 'prepared_roots_sha256'):
        _require(_strict_equal(prior[key], recovery[key]), 'campaign root/schedule mismatch')
    retention = _metadata(plan['retention_plan'], 'retention plan')
    _require(type(recovery.get('retention')) is dict and set(recovery['retention']) == {'m1-prior'},
             'only M1 retention allowed')
    _require(recovery['retention']['m1-prior'] == {
        'plan': plan['retention_plan']['path'], 'sha256': plan['retention_plan']['sha256']},
        'retention plan differs from campaign')
    retained = plan['retained_result']
    _at(retained, Path(prior['output']) / 'm1-prior' / 'result.json')
    _require(retention.get('source_directory') == str(Path(prior['output']) / 'm1-prior')
             and retention.get('result_sha256') == retained['sha256'], 'retained source mismatch')
    summary_ref = plan['campaigns']['recovery']['summary']
    _at(summary_ref, Path(recovery['output']) / 'recovery-summary.json')
    summary = _metadata(summary_ref, 'recovery summary')
    _require(summary.get('schema') == 'sol-six-row-recovery-summary-v1'
             and summary.get('config_sha256') == plan['campaigns']['recovery']['config']['sha256']
             and summary.get('status') == 'scheduled-terminal'
             and summary.get('required_prior_rows') == list(ROWS[:3])
             and type(summary.get('rows')) is dict and set(summary['rows']) == set(ROWS[3:]),
             'recovery summary mismatch')
    accounting = {}
    for i, row in enumerate(ROWS):
        name = 'prior' if i < 3 else 'recovery'
        root = Path(configs[name]['output'])
        refs = plan['rows'][row]
        _require(type(refs) is dict and set(refs) == ({'result', 'terminal'} if i < 3 else {'result', 'terminal', 'accounting'}),
                 'row reference keys')
        _at(refs['result'], root / row / 'result.json')  # Never opened here.
        _at(refs['terminal'], root / (row + '.terminal.json'))
        exit_record = _metadata(refs['terminal'], row + ' terminal')
        _row_exit(exit_record, row)
        _require(_strict_equal(exit_record, terminals[name]['rows'][i if i < 3 else i - 3]),
                 'row terminal differs from campaign terminal')
        if i >= 3:
            _at(refs['accounting'], root / (row + '.accounting.json'))
            counts = _metadata(refs['accounting'], row + ' accounting')
            _require(set(counts) == {'status', 'completed', 'failed', 'unattempted', 'scheduled'}
                     and all(type(counts[k]) is int and counts[k] >= 0 for k in ('completed', 'failed', 'unattempted', 'scheduled'))
                     and counts['scheduled'] == 40
                     and counts['completed'] + counts['failed'] + counts['unattempted'] == 40
                     and counts['failed'] <= 8, 'invalid accounting counts')
            expected_status = 'failure-limit' if counts['failed'] == 8 else 'scheduled-terminal'
            _require(counts['status'] == expected_status and (counts['failed'] == 8 or counts['unattempted'] == 0),
                     'pending below failure limit')
            _require(_strict_equal(counts, summary['rows'][row]), 'summary accounting mismatch')
            accounting[row] = counts
    return {'status': 'metadata-admitted-results-unverified', 'plan_sha256': expected_sha256,
            'plan': plan, 'configs': configs, 'accounting': accounting,
            'retention_binding': {'source': retention['source_directory'],
                                  'result_sha256': retained['sha256'],
                                  'plan_sha256': plan['retention_plan']['sha256']}}
