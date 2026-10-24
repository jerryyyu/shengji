import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import project_pair
from run_saved import run_saved
from test_diagnostic import bound_fixture, factory


def saved(tmp_path):
    locator, rows = bound_fixture()
    for row in rows:
        row.pop('history')
        row.pop('buried')
    path = tmp_path / 'prefix.json'
    raw = json.dumps(project_pair(rows, locator)).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), locator


def test_saved_projection_to_completed_diagnostic(tmp_path):
    path, sha, locator = saved(tmp_path)
    output = tmp_path / 'result.json'
    result = run_saved(path, sha, output, factory, policy_identity='synthetic-flat-pv',
                       seed=51, locator=locator)
    assert json.loads(output.read_text()) == result
    assert result['input_sha256'] == sha
    assert all(w['completed_tricks'] == 2 for a in result['continuation']['actions']
               for w in a['worlds'])
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        run_saved(path, sha, output, lambda **kw: pytest.fail('policy called'),
                  policy_identity='synthetic-flat-pv', seed=51, locator=locator)
    assert output.read_bytes() == before


@pytest.mark.parametrize('fault', ['sha', 'locator', 'schema'])
def test_invalid_saved_input_stops_before_policy(tmp_path, fault):
    path, sha, locator = saved(tmp_path)
    if fault == 'sha':
        sha = '0' * 64
    else:
        data = json.loads(path.read_text())
        data[fault] = None
        raw = json.dumps(data).encode()
        path.write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        run_saved(path, sha, tmp_path / 'result.json', lambda **kw: pytest.fail('policy called'),
                  policy_identity='synthetic-flat-pv', seed=51, locator=locator)
    assert not (tmp_path / 'result.json').exists()


def test_isolated_cli_help(tmp_path):
    script = Path(__file__).with_name('run_saved.py')
    result = subprocess.run([sys.executable, '-I', str(script), '--help'],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--prefix-sha' in result.stdout and '--policy-identity' in result.stdout
    assert '--admission-only' in result.stdout


def test_saved_admission_uses_served_scorer_without_reply_or_resample(tmp_path):
    from capture import capture_lead
    from served import replay_served_prefix
    locator, rows = bound_fixture()
    bot, root, _ = replay_served_prefix(rows[1], factory, seat=2)
    cap = capture_lead(bot, root)
    alternative = next([c] for c in root.hands[2]
                       if [c] not in cap['served_ballot'])
    locator['exploiter_action'] = alternative
    rows[0]['dtrace'][locator['index']][5] = alternative
    for row in rows:
        row.pop('history')
        row.pop('buried')
    raw = json.dumps(project_pair(rows, locator)).encode()
    path = tmp_path / 'prefix.json'
    path.write_bytes(raw)
    calls = []
    def counted(*, seed):
        b = factory(seed=seed)
        calls.append(b)
        if len(calls) == 2:
            b.decide_play = b._worlds = lambda *a, **k: pytest.fail('no replies or resampling')
        assert len(calls) <= 2
        return b
    output = tmp_path / 'admission.json'
    result = run_saved(path, hashlib.sha256(raw).hexdigest(), output, counted,
                       policy_identity='synthetic-flat-pv', seed=51,
                       locator=locator, admission_only=True)
    assert json.loads(output.read_text()) == result
    assert result['schema'] == 's61-flat-admission-diagnostic-v1'
    assert not result['in_served_ballot'] and result['ballot_parity']
    assert result['actions'] == cap['served_ballot'] + [alternative]
    assert result['served_record']['played'] == cap['played']
    assert result['value_means'][:-1] == pytest.approx(cap['served_record']['value_means'])
    assert result['alternative_delta_over_ballot_max'] == pytest.approx(
        result['value_means'][-1] - max(result['value_means'][:-1]))


@pytest.mark.parametrize('fault', ['parity', 'greedy'])
def test_admission_refuses_unsupported_scorer_without_publishing(tmp_path, fault):
    path, sha, locator = saved(tmp_path)
    calls = []
    def changed(*, seed):
        b = factory(seed=seed)
        calls.append(b)
        if fault == 'greedy':
            b.leaf_greedy_finish = True
        elif len(calls) == 2:
            original = b._value_means
            def drift(*args, **kwargs):
                values, batches = original(*args, **kwargs)
                return values + 1, batches
            b._value_means = drift
        return b
    output = tmp_path / 'admission.json'
    with pytest.raises(ValueError, match='parity|greedy'):
        run_saved(path, sha, output, changed, policy_identity='synthetic-flat-pv',
                  seed=51, locator=locator, admission_only=True)
    assert not output.exists()
