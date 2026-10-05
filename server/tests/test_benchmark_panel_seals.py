import hashlib
import json
from pathlib import Path

import pytest

from shengji.luna.benchmark_panel_seals import ROWS, SCHEMA, admit_panel_metadata


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def packet(tmp_path):
    root = tmp_path.resolve()
    docs, refs = {}, {}
    def add(name, path, value):
        docs[name] = value
        refs[name] = put(path, value)
        return refs[name]
    campaigns, rows = {}, {}
    retained = {'path': str(root / 'prior/run/m1-prior/result.json'), 'sha256': 'a' * 64}
    retention = add('retention', root / 'retention.json', {
        'schema': 'benchmark-retention-v1', 'source_directory': str(root / 'prior/run/m1-prior'),
        'result_sha256': retained['sha256']})
    counts = dict(status='scheduled-terminal', completed=39, failed=1, unattempted=0, scheduled=40)
    for name, names in [('prior', ROWS), ('recovery', ROWS[3:])]:
        output = root / name / 'run'
        config = dict(schema='sol-nine-policy-campaign-v2' if name == 'prior' else 'sol-six-row-recovery-v1',
                      output=str(output), rows=list(names), seeds=list(range(10)),
                      prepared_roots=str(root / 'roots'), prepared_roots_sha256='b' * 64)
        if name == 'recovery':
            config['retention'] = {'m1-prior': dict(plan=retention['path'], sha256=retention['sha256'])}
            config.update(failure_protocol='preserve-model-illegal-v1', illegal_failure_limit=8)
        cref = add(name + '-config', root / name / 'campaign.json', config)
        oref = add(name + '-output', output / 'config.json', dict(config))
        exits = []
        for row in names[:4] if name == 'prior' else names:
            ex = dict(row=row, status='exited', returncode=0, pid=123, elapsed_seconds=10)
            exits.append(ex)
            rows[row] = {
                # Deliberately nonexistent raw results: metadata must not open them.
                'result': {'path': str(output / row / 'result.json'), 'sha256': 'c' * 64},
                'terminal': add(row + '-terminal', output / (row + '.terminal.json'), ex)}
            if name == 'recovery':
                rows[row]['accounting'] = add(row + '-accounting', output / (row + '.accounting.json'), dict(counts))
        tref = add(name + '-terminal', output / 'terminal.json', {
            'status': 'failed' if name == 'prior' else 'scheduled-terminal',
            'config_sha256': cref['sha256'], 'rows': exits})
        campaigns[name] = dict(config=cref, output_config=oref, terminal=tref)
        if name == 'recovery':
            campaigns[name]['summary'] = add('summary', output / 'recovery-summary.json', {
                'schema': 'sol-six-row-recovery-summary-v1', 'config_sha256': cref['sha256'],
                'status': 'scheduled-terminal', 'required_prior_rows': list(ROWS[:3]),
                'rows': {r: dict(counts) for r in names}})
    plan = dict(schema=SCHEMA, campaigns=campaigns, rows=rows,
                retention_plan=retention, retained_result=retained)
    return root, plan, docs, refs


def admit(packet):
    root, plan, _, _ = packet
    ref = put(root / 'plan.json', plan)
    return admit_panel_metadata(ref['path'], ref['sha256'])


def republish(packet, key):
    _, _, docs, refs = packet
    refs[key].update(put(Path(refs[key]['path']), docs[key]))


def test_admission_never_reads_raw_results(packet, monkeypatch):
    original = Path.read_bytes
    def guard(path):
        assert path.name != 'result.json', 'metadata gate opened raw results'
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', guard)
    got = admit(packet)
    assert got['status'] == 'metadata-admitted-results-unverified'
    assert set(got['accounting']) == set(ROWS[3:])
    assert got['retention_binding']['result_sha256'] == 'a' * 64


@pytest.mark.parametrize('key,field,value', [
    ('recovery-terminal', 'status', 'running'),
    ('recovery-terminal', 'status', 'failed'),
    ('prior-terminal', 'status', 'running'),
    ('recovery-terminal', 'config_sha256', '0' * 64),
    ('prior-terminal', 'rows', []),
    ('recovery-terminal', 'rows', []),
    ('smv3-pv-terminal', 'returncode', True),
    ('smv3-pv-terminal', 'returncode', 1),
    ('mc-terminal', 'status', 'deadline'),
    ('summary', 'required_prior_rows', []),
    ('summary', 'config_sha256', '0' * 64),
    ('m1-prior-accounting', 'completed', 0),
    ('m1-prior-accounting', 'scheduled', True),
    ('m1-prior-accounting', 'status', 'failure-limit'),
    ('retention', 'source_directory', '/wrong'),
    ('retention', 'result_sha256', '0' * 64),
])
def test_semantic_metadata_drift_refused_even_when_repinned(packet, key, field, value):
    packet[2][key][field] = value
    republish(packet, key)
    with pytest.raises(ValueError):
        admit(packet)


def test_metadata_tamper_refused(packet):
    Path(packet[3]['summary']['path']).write_text('{}')
    with pytest.raises(ValueError, match='SHA mismatch'):
        admit(packet)


def test_duplicate_json_keys_refused(packet):
    ref = packet[3]['summary']
    raw = b'{"status": "scheduled-terminal", "status": "failed"}'
    Path(ref['path']).write_bytes(raw)
    ref['sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match='duplicate'):
        admit(packet)


def test_symlink_metadata_refused(packet):
    path = Path(packet[3]['summary']['path'])
    target = path.with_suffix('.saved')
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match='regular'):
        admit(packet)


@pytest.mark.parametrize('kind', ['missing', 'extra', 'swapped-result', 'bad-digest'])
def test_exact_nine_row_mapping(packet, kind):
    rows = packet[1]['rows']
    if kind == 'missing':
        del rows['smart']
    elif kind == 'extra':
        rows['extra'] = rows['smart']
    elif kind == 'swapped-result':
        rows['mc']['result'] = dict(rows['smart']['result'])
    else:
        rows['mc']['result']['sha256'] = 'bad'
    with pytest.raises(ValueError):
        admit(packet)


def test_counts_pending_below_limit_refused(packet):
    counts = dict(status='scheduled-terminal', completed=38, failed=1, unattempted=1, scheduled=40)
    packet[2]['mc-accounting'].update(counts)
    packet[2]['summary']['rows']['mc'].update(counts)
    republish(packet, 'mc-accounting')
    republish(packet, 'summary')
    with pytest.raises(ValueError, match='pending below'):
        admit(packet)


def test_failure_limit_terminal_is_allowed(packet):
    counts = dict(status='failure-limit', completed=20, failed=8, unattempted=12, scheduled=40)
    packet[2]['mc-accounting'].update(counts)
    packet[2]['summary']['rows']['mc'].update(counts)
    republish(packet, 'mc-accounting')
    republish(packet, 'summary')
    assert admit(packet)['accounting']['mc'] == counts


@pytest.mark.parametrize('field,value', [('seeds', list(range(10, 20))),
                                      ('prepared_roots_sha256', 'd' * 64),
                                      ('prepared_roots', '/different/roots')])
def test_campaigns_must_share_schedule_and_root_identity(packet, field, value):
    for key in ('recovery-config', 'recovery-output'):
        packet[2][key][field] = value
        republish(packet, key)
    digest = packet[3]['recovery-config']['sha256']
    packet[2]['recovery-terminal']['config_sha256'] = digest
    packet[2]['summary']['config_sha256'] = digest
    republish(packet, 'recovery-terminal')
    republish(packet, 'summary')
    with pytest.raises(ValueError, match='root/schedule mismatch'):
        admit(packet)


def test_row_exit_must_match_campaign_receipt(packet):
    packet[2]['mc-terminal'] = dict(packet[2]['mc-terminal'], pid=456)
    republish(packet, 'mc-terminal')
    with pytest.raises(ValueError, match='differs from campaign'):
        admit(packet)


def test_duplicate_terminal_row_refused(packet):
    packet[2]['recovery-terminal']['rows'][1] = packet[2]['recovery-terminal']['rows'][0]
    republish(packet, 'recovery-terminal')
    with pytest.raises(ValueError, match='ordered unique prefix'):
        admit(packet)


def test_bad_plan_digest_refused_before_metadata(packet):
    root, plan, _, _ = packet
    ref = put(root / 'plan.json', plan)
    with pytest.raises(ValueError, match='SHA mismatch'):
        admit_panel_metadata(ref['path'], '0' * 64)


@pytest.mark.parametrize('field,value', [('failure_protocol', 'fail-stop'),
                                      ('illegal_failure_limit', True),
                                      ('illegal_failure_limit', 7)])
def test_recovery_protocol_must_be_amended_exactly(packet, field, value):
    for key in ('recovery-config', 'recovery-output'):
        packet[2][key][field] = value
        republish(packet, key)
    packet[2]['recovery-terminal']['config_sha256'] = packet[3]['recovery-config']['sha256']
    republish(packet, 'recovery-terminal')
    with pytest.raises(ValueError, match='failure protocol'):
        admit(packet)


@pytest.mark.parametrize('length', [3, 5])
def test_prior_stop_is_exact_four_row_prefix(packet, length):
    exits = packet[2]['prior-terminal']['rows']
    packet[2]['prior-terminal']['rows'] = exits[:length] if length == 3 else exits + [dict(exits[-1], row='w32-original')]
    republish(packet, 'prior-terminal')
    with pytest.raises(ValueError, match='cardinality'):
        admit(packet)
