"""Portable handoff tests; no historical helper import or scientific access."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def lane(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/v52ec_reader.py'
    spec = importlib.util.spec_from_file_location('v52ec_handoff_test', script)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    record = dict(
        schema='claude-reservation-v1', lane='v52ec',
        seeds=list(reader.HOST_SEEDS['cloud']), count=520,
        pairing='candidate and control on the same seeds',
        launcher='/root/claude_v52ec_screen_cloud.sh', launcher_sha256=reader.LAUNCHER_SHA,
        status='/root/claude_v52ec_screen.status',
        output_root='/root/vol-screen-claude-v52ec-r38-20261005',
        created_at='2026-10-05T00:00:00Z',
        expected_identity={side: sha + '  /root/claude_v52ec_expected_' + suffix + '.json'
                           for side, suffix, sha in zip(('candidate', 'comparator'),
                                                       ('cand', 'cmp'), reader.EXPECTED_SHA)},
    )
    reservation, status = tmp_path / 'reservation.json', tmp_path / 'status'
    reservation.write_text(json.dumps(record))
    status.write_text(
        '2026-10-05T00:00:00Z v52ec armed (pid 123, launcher sha256 ' + reader.LAUNCHER_SHA + ')\n'
        '2026-10-05T01:00:00Z v52ec PHASE B DONE (release 38 as served x5, same seeds); LANE DONE\n'
    )
    def load(path):
        assert path == reservation, 'handoff must not open scientific outcomes'
        raw = path.read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    def check():
        return reader.check_lane(root=tmp_path, reservation=reservation, status=status, load=load)
    return record, reservation, status, check


def test_accepts_bound_terminal_metadata(lane):
    _, reservation, _, check = lane
    assert check() == {reservation: hashlib.sha256(reservation.read_bytes()).hexdigest()}


@pytest.mark.parametrize('field,value', [
    ('lane', 'another-lane'), ('count', 519), ('seeds', [52060910]),
    ('launcher_sha256', '0' * 64), ('expected_identity', {}),
    ('output_root', '/root/another-run'), ('created_at', 'yesterday'),
])
def test_rejects_reservation_drift(lane, field, value):
    record, reservation, _, check = lane
    record[field] = value
    reservation.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize('change', ['missing', 'extra'])
def test_rejects_reservation_field_drift(lane, change):
    record, reservation, _, check = lane
    if change == 'missing':
        del record['created_at']
    else:
        record['unexpected'] = True
    reservation.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='fields drift'):
        check()


@pytest.mark.parametrize('change', ['empty', 'armed-only', 'missing-armed', 'abort', 'refusing', 'trailing'])
def test_rejects_unsealed_status(lane, change):
    _, _, status, check = lane
    text = status.read_text()
    if change == 'empty':
        text = ''
    elif change == 'armed-only':
        text = text.splitlines()[0] + '\n'
    elif change == 'missing-armed':
        text = text.splitlines()[-1] + '\n'
    elif change in ('abort', 'refusing'):
        text = change.upper() + ': synthetic failure\n' + text
    else:
        text += 'new activity after terminal\n'
    status.write_text(text)
    with pytest.raises(ValueError):
        check()


@pytest.mark.parametrize('which', [1, 2])
def test_rejects_symlinked_handoff(lane, which):
    path, check = lane[which], lane[3]
    target = path.with_suffix('.real')
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match='symlinked'):
        check()
