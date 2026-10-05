import copy
import json
from pathlib import Path

import pytest

from test_benchmark_panel_seals import packet, put, republish
from test_production_llm_panel_readout import _report
from test_benchmark_retention import _row
from shengji.luna.benchmark_failure_protocol import summarize_scheduled
from shengji.luna.benchmark_panel_seals import ROWS


@pytest.fixture
def full_packet(packet):
    root, plan, docs, refs = packet
    hashes = {str(s): f'{s:064x}' for s in range(10)}
    roots_ref = put(root / 'roots/result.json', {'roots': hashes})
    for name in ('prior', 'recovery'):
        for suffix in ('config', 'output'):
            docs[name + '-' + suffix]['prepared_roots_sha256'] = roots_ref['sha256']
        if name == 'recovery':
            continue  # retention digest not known until original results exist
        for suffix in ('config', 'output'):
            republish(packet, name + '-' + suffix)
        docs[name + '-terminal']['config_sha256'] = refs[name + '-config']['sha256']
        republish(packet, name + '-terminal')

    reports = {}
    for i, row in enumerate(ROWS):
        directory = Path(plan['rows'][row]['result']['path']).parent
        _report(directory.parent, row, source=roots_ref['sha256'], roots=hashes)
        report = json.loads((directory / 'result.json').read_bytes())
        report['config']['checkpoint'] = None
        if i >= 3:
            report['config'].update(failure_protocol='preserve-model-illegal-v1', illegal_failure_limit=8)
        reports[row] = report

    source = root / 'prior/run/m1-prior'
    source.mkdir()
    original = copy.deepcopy(reports['m1-prior'])
    original['config'].pop('failure_protocol')
    original['config'].pop('illegal_failure_limit')
    original_rows = []
    mirror_refs = {}
    for i, m in enumerate(original['mirrors']):
        kind = 'complete' if i < 31 else 'typed' if i == 31 else 'pending'
        row = _row('sol', m['information'], m['seed'], m['flip'], kind=kind)
        original_rows.append(row)
        mirror_refs[row['key']] = put(source / f"mirror-sol-{row['information']}-{row['seed']}-{row['flip']}.json", row)
    original['mirrors'] = original_rows
    plan['retained_result'].update(put(source / 'result.json', original))
    docs['retention'].update(legacy_illegal_sha256=[], result_sha256=plan['retained_result']['sha256'])
    republish(packet, 'retention')
    for suffix in ('config', 'output'):
        docs['recovery-' + suffix]['retention']['m1-prior']['sha256'] = refs['retention']['sha256']
        republish(packet, 'recovery-' + suffix)
    for name in ('recovery-terminal', 'summary'):
        docs[name]['config_sha256'] = refs['recovery-config']['sha256']
        republish(packet, name)

    binding = dict(plan=refs['retention']['path'], plan_sha256=refs['retention']['sha256'],
                   source=str(source), result_sha256=plan['retained_result']['sha256'], prior_cost_tokens=0)
    m1 = reports['m1-prior']
    m1['config']['retained_attempts'] = binding
    m1['retained_attempts'] = copy.deepcopy(binding)
    for i, row in enumerate(original_rows[:32]):
        m1['mirrors'][i] = copy.deepcopy(row)
        m1['mirrors'][i]['lineage'] = dict(source=str(source), source_result_sha256=binding['result_sha256'],
            source_row=mirror_refs[row['key']]['path'], source_row_sha256=mirror_refs[row['key']]['sha256'],
            kind='retained-terminal-attempt', retention_plan_sha256=binding['plan_sha256'])
    for i, row in enumerate(ROWS):
        if i >= 3:
            reports[row]['scheduled_summary'] = summarize_scheduled(reports[row]['mirrors'])
            counts = dict(status='scheduled-terminal', completed=39 if row == 'm1-prior' else 40,
                          failed=1 if row == 'm1-prior' else 0, unattempted=0, scheduled=40)
            docs[row + '-accounting'] = counts
            docs['summary']['rows'][row] = copy.deepcopy(counts)
            republish(packet, row + '-accounting')
        plan['rows'][row]['result'].update(put(Path(plan['rows'][row]['result']['path']), reports[row]))
    republish(packet, 'summary')
    return packet, reports


def run(packet):
    from scripts.sealed_production_llm_panel_readout import read_sealed_panel
    ref = put(packet[0] / 'plan.json', packet[1])
    return read_sealed_panel(ref['path'], ref['sha256'])


def test_full_sealed_reader_uses_each_result_once(full_packet, monkeypatch):
    packet, reports = full_packet
    reads = {}
    original = Path.read_bytes
    def tracked(path):
        if path.name == 'result.json':
            reads[str(path)] = reads.get(str(path), 0) + 1
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', tracked)
    result = run(packet)
    assert result['seals']['metadata_and_content_validated'] is True
    assert len(reads) == 11  # nine rows + roots + original retained report
    assert set(reads.values()) == {1}
    assert result['policies']['m1-prior']['sol']['complete_mirrors'] == 20
    assert result['policies']['m1-prior']['pt_sol']['complete_mirrors'] == 19
    assert result['terminal_accounting']['m1-prior'] == dict(
        status='scheduled-terminal', completed=39, failed=1, unattempted=0, scheduled=40)
    assert result['terminal_accounting']['smv3-pv']['failed'] == 0
    coverage = result['policies']['m1-prior']['pt_sol']['forfeit_endpoint']['paired_signed_levels']['coverage']
    assert coverage['scored_pairs'] == coverage['scheduled_pairs'] == 10
    assert coverage['failure_cap_reached'] is False


def test_capped_coverage_labels_every_endpoint_without_changing_scores(full_packet):
    from scripts.sealed_production_llm_panel_readout import label_endpoint_coverage
    result = run(full_packet[0])
    counts = copy.deepcopy(result['terminal_accounting'])
    counts['m1-prior'].update(completed=24, failed=8, unattempted=8)
    before = copy.deepcopy(result)
    label_endpoint_coverage(result, counts)
    for row, policy in result['policies'].items():
        for mode in ('sol', 'pt_sol'):
            for endpoint in (policy[mode]['paired_signed_levels'],
                             policy[mode]['forfeit_endpoint']['paired_signed_levels']):
                assert endpoint['coverage']['failure_cap_reached'] == (row == 'm1-prior')
                assert endpoint['coverage']['scheduled_pairs'] == 10
    for diff, old in zip(result['row_differences'], before['row_differences']):
        capped = 'm1-prior' in (diff['left'], diff['right'])
        for mode in ('sol', 'pt_sol'):
            for endpoint, previous in ((diff[mode], old[mode]),
                    (diff['forfeit_endpoint'][mode]['paired_signed_levels'],
                     old['forfeit_endpoint'][mode]['paired_signed_levels'])):
                assert endpoint['coverage']['failure_cap_reached'] == capped
                assert ('before the failure cap' in endpoint['coverage']['label']) == capped
                assert {k: v for k, v in endpoint.items() if k != 'coverage'} == {
                    k: v for k, v in previous.items() if k != 'coverage'}


@pytest.mark.parametrize('kind', ['score', 'lineage', 'cost', 'accounting', 'result-seal', 'plan-path'])
def test_corruption_refuses_before_scoring(full_packet, monkeypatch, kind):
    from scripts import production_llm_panel_readout as arithmetic
    packet, reports = full_packet
    report = reports['m1-prior']
    if kind == 'score':
        report['mirrors'][0]['signed_levels'] += 1
    elif kind == 'lineage':
        report['mirrors'][0]['lineage']['source_row_sha256'] = '0' * 64
    elif kind == 'cost':
        report['config']['retained_attempts']['prior_cost_tokens'] = 1
    elif kind == 'accounting':
        report['scheduled_summary'] = {}
    elif kind == 'plan-path':
        report['config']['retained_attempts']['plan'] = '/other/plan.json'
        report['retained_attempts']['plan'] = '/other/plan.json'
    else:
        packet[1]['rows']['m1-prior']['result']['sha256'] = '0' * 64
    if kind != 'result-seal':
        ref = packet[1]['rows']['m1-prior']['result']
        ref.update(put(Path(ref['path']), report))
    monkeypatch.setattr(arithmetic, 'analyze_panel_reports', lambda *a, **k: pytest.fail('scored corrupt data'))
    with pytest.raises(ValueError):
        run(packet)


def test_bad_metadata_blocks_before_any_result_access(full_packet, monkeypatch):
    packet, _ = full_packet
    packet[2]['recovery-terminal']['status'] = 'running'
    republish(packet, 'recovery-terminal')
    original = Path.read_bytes
    def guard(path):
        assert path.name != 'result.json', 'raw access before admission'
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', guard)
    with pytest.raises(ValueError, match='not terminal'):
        run(packet)
