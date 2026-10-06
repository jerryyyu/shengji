"""Read a reviewed/pinned terminal panel once; never launch games.

Caller still owns reader/runtime pinning and exclusive read ownership. This
module has no CLI or automatic plan creation. Do not use on real artifacts
until the full adapter and its exact plan have been reviewed.
"""
from pathlib import Path

from scripts import production_llm_panel_readout as arithmetic
from shengji.luna.benchmark_failure_protocol import FAIL_STOP
from shengji.luna.benchmark_panel_seals import ROWS, _metadata, _require, _at, _row_exit, admit_panel_metadata
from shengji.luna.benchmark_retention import _strict_equal, load_retained_attempts
from shengji.luna.benchmark_terminal import validate_scheduled_terminal
from shengji.luna.benchmark_retained_content import validate_retained_content


def label_endpoint_coverage(result, accounting):
    """Label every published contrast without changing scores or imputing slots."""
    scheduled = len(result['seeds'])

    def label(contrast, capped, endpoint):
        if contrast is None:
            return
        count = contrast['count']
        contrast['coverage'] = {
            'scored_pairs': count, 'scheduled_pairs': scheduled,
            'failure_cap_reached': capped,
            'endpoint': endpoint,
            'label': (f'over {count} of {scheduled} scheduled deal pairs'
                      + (' reached before the failure cap' if capped else '')
                      + '; ' + endpoint + '; unattempted mirrors never imputed'),
        }

    capped = {row: counts['unattempted'] > 0 for row, counts in accounting.items()}
    for row, policy in result['policies'].items():
        for mode in ('sol', 'pt_sol'):
            arm = policy[mode]
            label(arm['paired_signed_levels'], capped[row], 'completed-only')
            if 'forfeit_endpoint' in arm:
                label(arm['forfeit_endpoint']['paired_signed_levels'], capped[row],
                      'typed-illegality forfeits included')
    for difference in result['row_differences']:
        limited = capped[difference['left']] or capped[difference['right']]
        for mode in ('sol', 'pt_sol'):
            label(difference[mode], limited, 'matching completed-only pairs')
            if 'forfeit_endpoint' in difference:
                label(difference['forfeit_endpoint'][mode]['paired_signed_levels'], limited,
                      'matching scored pairs; typed-illegality forfeits included')


def read_sealed_panel(plan_path, expected_sha256):
    admitted = admit_panel_metadata(plan_path, expected_sha256)
    plan, configs = admitted['plan'], admitted['configs']
    config = configs['prior']
    roots = _metadata({'path': str(Path(config['prepared_roots']) / 'result.json'),
                       'sha256': config['prepared_roots_sha256']}, 'prepared roots')
    hashes = roots.get('roots')
    _require(type(hashes) is dict and set(hashes) == {str(s) for s in config['seeds']},
             'prepared root coverage mismatch')
    _require(all(type(h) is str and len(h) == 64 and all(c in '0123456789abcdef' for c in h)
                 for h in hashes.values()), 'invalid prepared root hashes')
    context = {'seeds': config['seeds'], 'source_result_sha256': config['prepared_roots_sha256'],
               'root_hashes': hashes}
    reports = {row: _metadata(plan['rows'][row]['result'], row + ' sealed result') for row in ROWS}
    # Shape/root validation first. Arithmetic sees the SAME decoded objects.
    for i, row in enumerate(ROWS):
        report, mirrors, identity = arithmetic._validate_row_report(
            row, None, campaign=context, report_data=reports[row])
        _require(identity['seeds'] == config['seeds'], 'row seed order mismatch')
        if i < 3:
            _require(report['config'].get('failure_protocol', FAIL_STOP) == FAIL_STOP,
                     'historical protocol must remain fail-stop')
            _require(all(m['complete'] is True and 'error' not in m and 'failure' not in m
                         and m.get('status') not in ('not_run', 'setup_failed') for m in mirrors),
                     'historical row is not fully complete')

    m1 = reports['m1-prior']
    binding = m1['config'].get('retained_attempts')
    _require(type(binding) is dict and binding.get('plan') == plan['retention_plan']['path'],
             'retention plan path mismatch')
    expected_config = {key: m1['config'][key] for key in (
        'seeds', 'models', 'information', 'policy', 'baseline_recipe', 'checkpoint', 'prepared_roots_from')}
    retained = load_retained_attempts(plan['retention_plan']['path'], plan['retention_plan']['sha256'],
                                      expected_config=expected_config)
    _require(retained['result_sha256'] == plan['retained_result']['sha256']
             and str(Path(retained['path']) / 'result.json') == plan['retained_result']['path'],
             'authenticated retention source mismatch')
    terminal_accounting = {row: {'status': 'complete', 'completed': 40, 'failed': 0,
                                 'unattempted': 0, 'scheduled': 40} for row in ROWS[:3]}
    for row in ROWS[3:]:
        if row == 'm1-prior':
            counts = validate_retained_content(reports[row], retained)
        else:
            counts = validate_scheduled_terminal(reports[row], seeds=config['seeds'])
        _require(_strict_equal(counts, admitted['accounting'][row]), 'recomputed accounting mismatch')
        terminal_accounting[row] = counts
    result = arithmetic.analyze_panel_reports(reports, {row: context for row in ROWS})
    # Legacy arithmetic's failure_count includes incomplete slots. Preserve
    # that API but publish authoritative failures versus pending separately.
    result['terminal_accounting'] = terminal_accounting
    label_endpoint_coverage(result, terminal_accounting)
    result['accounting_note'] = 'Use terminal_accounting for failed versus unattempted counts; legacy failure_count includes incomplete slots.'
    result['seals'] = {'plan_sha256': expected_sha256,
                       'result_refs': {row: plan['rows'][row]['result'] for row in ROWS},
                       'retained_result': plan['retained_result'],
                       'metadata_and_content_validated': True}
    return result


def read_sealed_stage1(plan_path, expected_sha256):
    """Admit fresh stage-1 metadata before opening either pinned row result."""
    return _read_sealed_stage(plan_path, expected_sha256, stage=1)


def read_sealed_stage2(plan_path, expected_sha256):
    """Read the seven separately sealed feedback-ON rows, not an implicit panel."""
    return _read_sealed_stage(plan_path, expected_sha256, stage=2)


def read_saved_feedback_panel(plan_path, expected_sha256):
    """Assemble published stage results only; never follow their raw refs.

    The reviewed plan must pin the previously accepted result AND receipt for
    each stage. Hash agreement authenticates bytes, not scientific approval.
    Cross-stage paired contrasts cannot be recovered from marginal summaries.
    """
    from scripts.launch_production_llm_panel import STAGE1_ROWS, STAGE2_ROWS
    plan = _metadata({'path': str(plan_path), 'sha256': expected_sha256}, 'saved-stage plan')
    _require(set(plan) == {'schema', 'stages'}
             and plan['schema'] == 'sol-saved-feedback-panel-plan-v1', 'invalid saved-stage plan')
    _require(type(plan['stages']) is dict and set(plan['stages']) == {'stage1', 'stage2'},
             'exact two saved stages required')
    stages = {}
    for stage, rows in ((1, STAGE1_ROWS), (2, STAGE2_ROWS)):
        name = f'stage{stage}'
        refs = plan['stages'][name]
        _require(type(refs) is dict and set(refs) == {'result', 'receipt'}, 'saved-stage refs')
        receipt = _metadata(refs['receipt'], name + ' publication receipt')
        _require(receipt.get('status') == 'complete'
                 and receipt.get('result_sha256') == refs['result']['sha256'],
                 'saved-stage publication incomplete or mismatched')
        result = _metadata(refs['result'], name + ' saved readout')
        _require(result.get('schema') == f'sol-feedback-on-stage{stage}-readout-v1'
                 and result.get('treatment') == 'feedback-ON'
                 and result.get('status') in ('complete', 'partial')
                 and type(result.get('panel_size')) is int and result['panel_size'] == len(rows)
                 and result.get('benchmark_ids') == list(rows), 'saved-stage identity mismatch')
        seals = result.get('seals', {})
        _require(seals.get('metadata_and_content_validated') is True
                 and type(seals.get('result_refs')) is dict
                 and set(seals['result_refs']) == set(rows), 'saved-stage seals missing')
        for field in ('policies', 'terminal_accounting'):
            _require(type(result.get(field)) is dict and set(result[field]) == set(rows),
                     'saved-stage row coverage mismatch')
        for key, policy in result['policies'].items():
            _require(policy.get('benchmark_id') == key, 'saved-stage policy identity mismatch')
        _require(type(result.get('row_differences')) is list, 'saved-stage contrasts missing')
        stages[name] = result
    first, second = stages['stage1'], stages['stage2']
    for field in ('seeds', 'prepared_roots', 'bootstrap'):
        _require(field in first and field in second
                 and _strict_equal(first[field], second[field]), 'saved-stage ' + field + ' mismatch')
    return {
        'schema': 'sol-saved-feedback-panel-v1', 'treatment': 'feedback-ON',
        'status': 'complete' if all(s['status'] == 'complete' for s in stages.values()) else 'partial',
        'panel_size': 9, 'benchmark_ids': list(arithmetic.POLICIES),
        **{field: first[field] for field in ('seeds', 'prepared_roots', 'bootstrap')},
        **{field: {key: stage[field][key] for stage in stages.values() for key in stage[field]}
           for field in ('policies', 'terminal_accounting')},
        'within_stage_row_differences': {key: stage['row_differences'] for key, stage in stages.items()},
        'cross_stage_row_differences': {
            'status': 'unavailable',
            'reason': 'Saved aggregates lack joint per-deal values; no raw reread or covariance imputation.'},
        'provenance': {'plan_sha256': expected_sha256, 'stages': plan['stages']},
        'interpretation': 'Saved row statistics copied unchanged. No new ranking, superiority or equivalence claim.',
    }


def _read_sealed_stage(plan_path, expected_sha256, *, stage):
    plan = _metadata({'path': str(plan_path), 'sha256': expected_sha256}, 'stage1 plan')
    admitted = _admit_stage_metadata(plan, stage=stage)
    reports = {row: _metadata(plan['rows'][row]['result'], row + ' result')
               for row in admitted['rows']}
    analyze = arithmetic.analyze_stage1_reports if stage == 1 else arithmetic.analyze_stage2_reports
    result = analyze(
        reports, {row: admitted['context'] for row in admitted['rows']})
    _require(_strict_equal(result['terminal_accounting'], admitted['accounting']),
             'stage1 recomputed accounting mismatch')
    label_endpoint_coverage(result, admitted['accounting'])
    result['accounting_note'] = 'Use terminal_accounting for failures versus unattempted slots.'
    result['seals'] = dict(plan_sha256=expected_sha256,
                          result_refs={row: plan['rows'][row]['result']
                                       for row in admitted['rows']},
                          metadata_and_content_validated=True)
    return result


def admit_stage1_metadata(plan):
    """Authenticate stage-1 metadata while leaving row results unopened.

    Result references are shape-checked only.  A plan builder can therefore
    pass all-zero result digests in memory, admit this complete metadata cone,
    and take one subsequent streaming pass over each result.
    """
    return _admit_stage_metadata(plan, stage=1)


def admit_stage2_metadata(plan):
    return _admit_stage_metadata(plan, stage=2)


def _admit_stage_metadata(plan, *, stage):
    from scripts.launch_production_llm_panel import STAGE1_ROWS, STAGE1_SCHEMA, STAGE2_ROWS, STAGE2_SCHEMA
    from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL
    rows = STAGE1_ROWS if stage == 1 else STAGE2_ROWS
    schema = STAGE1_SCHEMA if stage == 1 else STAGE2_SCHEMA

    _require(set(plan) == {'schema', 'campaign', 'rows'}
             and plan['schema'] == f'sol-feedback-on-stage{stage}-seals-v1', 'invalid stage plan')
    refs = plan['campaign']
    _require(type(refs) is dict and set(refs) == {'config', 'output_config', 'terminal', 'summary'},
             'stage1 campaign reference keys')
    _require(type(plan['rows']) is dict and set(plan['rows']) == set(rows), 'stage1 row set')
    config = _metadata(refs['config'], 'stage1 config')
    _require(config.get('schema') == schema and config.get('rows') == list(rows)
             and 'retention' not in config, 'stage1 fresh recipe required')
    _require(_strict_equal(config.get('recovery_controls'), dict(capacity_retries=True,
             accept_recovered_reconnects=False, invalid_action_feedback=True,
             classify_final_action_failures=True)), 'stage1 controls')
    _require(all(type(config.get(k)) is int and config[k] == expected for k, expected in
                 (('row_wall_seconds', 43200), ('row_soft_tokens', 45000000),
                  ('provider_call_seconds', 300)))
             and _strict_equal(config.get('provider_capacity_retry_delays'), [15, 30, 60]),
             'stage1 budget/retry limits')
    _require(config.get('failure_protocol') == PRESERVE_ILLEGAL
             and type(config.get('illegal_failure_limit')) is int
             and config['illegal_failure_limit'] == 8, 'stage1 failure limit')
    output = Path(config.get('output', ''))
    _require(output.is_absolute(), 'stage1 output must be absolute')
    for field, name in (('output_config', 'config.json'), ('terminal', 'terminal.json'),
                        ('summary', f'stage{stage}-summary.json')):
        _at(refs[field], output / name)
    _require(_strict_equal(config, _metadata(refs['output_config'], 'stage1 output config')),
             'stage1 output config drift')
    terminal = _metadata(refs['terminal'], 'stage1 terminal')
    summary = _metadata(refs['summary'], 'stage1 summary')
    for record in (terminal, summary):
        _require(record.get('config_sha256') == refs['config']['sha256']
                 and record.get('status') == 'scheduled-terminal', 'stage1 not terminal')
    _require(summary.get('schema') == f'sol-feedback-on-stage{stage}-summary-v1'
             and summary.get('required_prior_rows') == ([] if stage == 1 else list(STAGE1_ROWS))
             and type(summary.get('rows')) is dict
             and set(summary['rows']) == set(rows), 'stage1 summary drift')
    exits = terminal.get('rows')
    _require(type(exits) is list and len(exits) == len(rows), 'stage1 terminal cardinality')
    accounting = {}
    for index, row in enumerate(rows):
        row_refs = plan['rows'][row]
        _require(type(row_refs) is dict and set(row_refs) == {'result', 'terminal', 'accounting'},
                 'stage1 row refs')
        _at(row_refs['result'], output / row / 'result.json')
        _at(row_refs['terminal'], output / (row + '.terminal.json'))
        _at(row_refs['accounting'], output / (row + '.accounting.json'))
        exit_record = _metadata(row_refs['terminal'], row + ' terminal')
        _row_exit(exit_record, row)
        _require(_strict_equal(exit_record, exits[index]), 'stage1 row exit mismatch')
        counts = _metadata(row_refs['accounting'], row + ' accounting')
        _require(_strict_equal(counts, summary['rows'][row]), 'stage1 accounting mismatch')
        _require(set(counts) == {'status', 'completed', 'failed', 'unattempted', 'scheduled'}
                 and all(type(counts[k]) is int and counts[k] >= 0
                         for k in ('completed', 'failed', 'unattempted', 'scheduled'))
                 and counts['scheduled'] == 40
                 and counts['completed'] + counts['failed'] + counts['unattempted'] == 40
                 and counts['failed'] <= 8
                 and counts['status'] == ('failure-limit' if counts['failed'] == 8 else 'scheduled-terminal')
                 and (counts['failed'] == 8 or counts['unattempted'] == 0), 'stage1 accounting invalid')
        accounting[row] = counts
    roots = _metadata({'path': str(Path(config['prepared_roots']) / 'result.json'),
                       'sha256': config['prepared_roots_sha256']}, 'stage1 roots')
    context = dict(seeds=config['seeds'], source_result_sha256=config['prepared_roots_sha256'],
                   root_hashes=roots.get('roots'))
    return {'status': 'metadata-admitted-results-unverified', 'plan': plan,
            'rows': tuple(rows), 'config': config,
            'terminal': terminal, 'summary': summary,
            'accounting': accounting, 'context': context}
