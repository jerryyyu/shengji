import json
from pathlib import Path
import pytest
import launcher
import fallback_diagnostic as diagnostic
from test_sealed_input import completed


class ReceiptsOnly(dict):
    def __getitem__(self, key):
        assert key == 'decision_traces', 'outcome access'
        return super().__getitem__(key)


def test_projection_never_accesses_outcomes():
    receipt = dict(schema='pv-search-fallback-v1', reason='budget',
                   error_class='PVSearchBudgetExceeded', error_stage=None)
    shard = ReceiptsOnly(decision_traces=[dict(side='arm', decisions=[receipt]),
                                         dict(side='baseline', decisions=[receipt])],
                         records='FORBIDDEN', outcome='FORBIDDEN')
    result = diagnostic.project([shard])
    assert result['counts'] == dict(decisions=1, play_fallback=1)
    assert result['causes'][0]['reason'] == 'budget'
    assert 'FORBIDDEN' not in json.dumps(result)


@pytest.fixture
def invocation(completed, monkeypatch):
    plan, expected, pins = completed
    root = pins['root']
    (root / 'READOUT_HOLD').unlink()
    terminal = json.loads((root / 'terminal.json').read_text())
    for item in terminal['results']:
        target = Path(item['output'])
        for path in target.glob('cluster-*.json'):
            path.write_text(json.dumps(dict(decision_traces=[dict(side='arm', decisions=[dict(
                schema='pv-search-fallback-v1', reason='budget', error_class='PVSearchBudgetExceeded')])],
                records='never inspected')))
        (root / 'seals' / (target.name + '.json')).unlink()
        item['seal_sha256'] = launcher.seal_window(target, expected[str(target)], root / 'seals' / (target.name + '.json'))
    (root / 'terminal.json').write_text(json.dumps(terminal))
    terminal_sha = launcher._sha(root / 'terminal.json')
    saved = dict(status='DECISION_INVALID', terminal_sha256=terminal_sha,
                 reader_sha256='original', packet_sha256=launcher.packet_digest(plan, expected),
                 decision_check=dict(counts={arm: dict(decisions=5200, play_fallback=5200)
                                             for arm in ('candidate', 'comparator')}))
    (root / 'readout.json').write_text(json.dumps(saved))
    (root / 'READOUT_CONSUMED.json').write_text(json.dumps(dict(terminal_sha256=terminal_sha, reader_sha256='original')))
    for name, value in [('plan', plan), ('expected', expected)]:
        (root / (name + '.json')).write_text(json.dumps(value))
    monkeypatch.setattr(diagnostic.subprocess, 'check_output', lambda argv, **kw: 'a'*40 if 'rev-parse' in argv else '')
    return dict(source_head='a'*40, reader_sha=launcher._sha(Path(diagnostic.__file__)),
                root=root, terminal_sha=terminal_sha, plan_path=root/'plan.json',
                expected_path=root/'expected.json', saved_sha=launcher._sha(root/'readout.json'))


def test_sealed_projection_reconciles_saved_counts_once(invocation):
    root = invocation['root']
    original = (root/'readout.json').read_bytes(), (root/'READOUT_CONSUMED.json').read_bytes()
    result = diagnostic.diagnose(**invocation)
    assert result['status'] == 'DIAGNOSTIC_COMPLETE'
    assert all(arm['causes'][0]['count'] == 5200 for arm in result['arms'].values())
    with pytest.raises(FileExistsError):
        diagnostic.diagnose(**invocation)
    assert original == ((root/'readout.json').read_bytes(), (root/'READOUT_CONSUMED.json').read_bytes())


def test_hold_refuses_before_diagnostic_claim(invocation):
    (invocation['root']/'READOUT_HOLD').write_text('hold')
    with pytest.raises(ValueError, match='HOLD'):
        diagnostic.diagnose(**invocation)
    assert not (invocation['root']/'fallback-diagnostic.json').exists()


def test_drift_saves_failure_without_retry(invocation):
    root = invocation['root']
    target = next(root.glob('*/cluster-00000.json'))
    target.write_text('{}')
    assert diagnostic.diagnose(**invocation)['status'] == 'DIAGNOSTIC_FAILED'
    with pytest.raises(FileExistsError):
        diagnostic.diagnose(**invocation)
