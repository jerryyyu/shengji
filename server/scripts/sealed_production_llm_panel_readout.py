"""Read a reviewed/pinned terminal panel once; never launch games.

Caller still owns reader/runtime pinning and exclusive read ownership. This
module has no CLI or automatic plan creation. Do not use on real artifacts
until the full adapter and its exact plan have been reviewed.
"""
from pathlib import Path

from scripts import production_llm_panel_readout as arithmetic
from shengji.luna.benchmark_failure_protocol import FAIL_STOP
from shengji.luna.benchmark_panel_seals import ROWS, _metadata, _require, admit_panel_metadata
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
