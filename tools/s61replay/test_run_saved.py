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
