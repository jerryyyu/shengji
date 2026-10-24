"""One outcome-blind projection of the explicitly named failed PT mirror."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path('/root/vol-dev-codex-pt-r46-429-20261021')
TERMINAL_SHA = '4efb92095ab5535ce64b10dd823f29e18fe509f6449ec08ad66693d928f6249e'
KEY = 'sol-perfect-seed142060913-flip0'
TARGET = 'mirror-sol-perfect-142060913-0.json'
OUTPUT = Path('/root/codex-pt-failure-diagnostic-output')


def bounded_text(value, limit):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('failure text outside reviewed bounds')
    return value


def project(row):
    expected = dict(schema='w32-llm-benchmark-mirror-v1', key=KEY, arm='sol-perfect',
                    model='sol', information='perfect', seed=142060913, flip=0, complete=False)
    if any(type(row.get(k)) is not type(v) or row.get(k) != v for k, v in expected.items()):
        raise ValueError('wrong failed mirror')
    if any(k in row for k in ('signed_levels', 'winner', 'winner_team', 'level_change', 'attacker_points')):
        raise ValueError('outcome-bearing mirror refused')
    error = bounded_text(row.get('error'), 2048)
    if not error:
        raise ValueError('missing failure')
    failure = row.get('failure', {})
    if not isinstance(failure, dict):
        raise ValueError('invalid failure object')
    calls = row.get('calls')
    if not isinstance(calls, list) or len(calls) > 10000:
        raise ValueError('invalid transport inventory')
    categories, tail = Counter(), []
    for call in calls:
        if not isinstance(call, dict):
            raise ValueError('invalid transport receipt')
        category = bounded_text(call.get('error_type'), 128)
        categories[category or ('accepted' if call.get('accepted') is True else 'unclassified')] += 1
        if category or call.get('error'):
            entry = {k: bounded_text(call.get(k), 2048) for k in ('error_type', 'error', 'capacity_message')}
            for key in ('returncode', 'wall_ms', 'backoff_seconds'):
                value = call.get(key)
                if value is not None and (type(value) not in (int, float) or not 0 <= abs(value) <= 10**12):
                    raise ValueError('invalid transport scalar')
                entry[key] = value
            tail.append(entry)
    return dict(schema='pt-single-failure-diagnostic-v1', mirror=KEY, error=error,
                failure={k: bounded_text(failure.get(k), 128) for k in ('schema', 'category', 'stage')},
                transport_calls=len(calls), transport_categories=dict(categories),
                failed_transport_tail=tail[-8:], failed_transport_count=len(tail),
                claim='failure/transport evidence only; no gameplay estimate or retry authority')


def read_file(path, limit):
    if (any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > limit):
        raise ValueError('invalid diagnostic input')
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('input changed')
    return raw


def run():
    for folder in (ROOT, Path('/root/codex-pt-packet-1cae46e5'), OUTPUT.parent):
        if folder.is_symlink():
            raise ValueError('aliased diagnostic root')
    for folder in (ROOT, Path('/root/codex-pt-packet-1cae46e5'), Path(__file__).resolve().parent):
        if any((folder / name).exists() for name in ('HOLD', 'READOUT_HOLD')):
            raise ValueError('diagnostic HOLD')
    if any(Path('/proc', str(pid)).exists() for pid in (2340757, 2340760)):
        raise ValueError('producer live')
    terminal = read_file(ROOT / 'terminal.json', 16384)
    if hashlib.sha256(terminal).hexdigest() != TERMINAL_SHA:
        raise ValueError('terminal drift')
    OUTPUT.mkdir()
    (OUTPUT / 'claim.json').write_text(json.dumps({'mirror': KEY, 'terminal_sha256': TERMINAL_SHA}))
    try:
        raw = read_file(ROOT / 'benchmark' / TARGET, 32 * 1024 * 1024)
        result = project(json.loads(raw))
        result['input_sha256'] = hashlib.sha256(raw).hexdigest()
        result['input_path'] = str(ROOT / 'benchmark' / TARGET)
        (OUTPUT / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+'\n')
    except Exception as exc:
        (OUTPUT / 'refusal.json').write_text(json.dumps({'type': type(exc).__name__, 'error': str(exc)}))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.parse_args()
    run()
