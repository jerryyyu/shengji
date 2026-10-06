import fcntl
import hashlib
import os
import shutil

import pytest

from shengji.eval.s11_schedule import (
    collect_s11_schedule,
    inspect_s11_schedule,
)
from shengji.eval.s11_public_view import public_s11_fixture
from test_s11_collection import factory
from test_s11_public_view import trajectory


MANIFEST = 'a' * 64
PACKET = 'b' * 64


def _slots(trajectory):
    return [dict(root_id=f's11-{MANIFEST}-draw-{draw:02d}', draw_index=draw,
                 status='valid', selected_ply=98,
                 fixture=public_s11_fixture(
                     trajectory, 98,
                     root_id=f's11-{MANIFEST}-draw-{draw:02d}'))
            for draw in range(64)]


@pytest.fixture
def slots(trajectory):
    return _slots(trajectory)


@pytest.fixture(scope='module')
def completed_source(tmp_path_factory, trajectory):
    """Exercise the real full collector once, not once per corruption case."""
    directory = tmp_path_factory.mktemp('s11-completed-source')
    collect(_slots(trajectory), directory,
            factory(dict(leaves=0, policy=[], bots=[])))
    return directory


@pytest.fixture
def completed_run(tmp_path, completed_source):
    # Copies, never hard links: corruption in one test cannot reach another.
    shutil.copytree(completed_source, tmp_path, dirs_exist_ok=True)
    return tmp_path


def collect(slots, path, build, **kwargs):
    options = dict(manifest_sha256=MANIFEST, packet_sha256=PACKET,
                   seed=17, max_public_refusals=63)
    options.update(kwargs)
    return collect_s11_schedule(slots, path, build, **options)


def inspect(slots, path, **kwargs):
    options = dict(manifest_sha256=MANIFEST, packet_sha256=PACKET,
                   seed=17, max_public_refusals=63)
    options.update(kwargs)
    return inspect_s11_schedule(slots, path, **options)


def root(path, fixture):
    return path / hashlib.sha256(fixture.id.encode()).hexdigest()


def test_inventory_distinguishes_prefix_failure_and_never_retries(tmp_path, slots):
    calls = dict(leaves=0, policy=[], bots=[])
    build = factory(calls)

    def fail_second_root():
        if len(calls['bots']) == 2:
            raise RuntimeError('synthetic second-root failure')
        return build()

    with pytest.raises(RuntimeError, match='second-root'):
        collect(slots, tmp_path, fail_second_root)
    before = len(calls['bots'])
    result = inspect(slots, tmp_path)
    assert result['counts'] == {
        'completed': 1, 'refused': 0, 'interrupted': 1, 'unattempted': 62}
    assert result['roots'][0]['status'] == 'completed'
    assert result['roots'][1]['status'] == 'interrupted'
    assert len(calls['bots']) == before


def test_pre_start_budget_expiry_is_unattempted_and_snapshot_is_unchanged(tmp_path, slots):
    def expired():
        raise TimeoutError('expired before start')

    with pytest.raises(TimeoutError, match='expired'):
        collect(slots, tmp_path, lambda: pytest.fail('model call'), check_budget=expired)
    files_before = {p.relative_to(tmp_path): p.read_bytes()
                    for p in tmp_path.rglob('*') if p.is_file()}
    result = inspect(slots, tmp_path)
    assert result['counts'] == {
        'completed': 0, 'refused': 0, 'interrupted': 0, 'unattempted': 64}
    files_after = {p.relative_to(tmp_path): p.read_bytes()
                   for p in tmp_path.rglob('*') if p.is_file()}
    assert files_after == files_before


def test_input_refusal_is_durable_and_prevents_inference(tmp_path, slots):
    slots[4] = {
        'root_id': slots[4]['root_id'], 'draw_index': 4, 'status': 'refused',
        'stage': 'shard', 'reason': 'synthetic input refusal',
    }
    with pytest.raises(ValueError, match='input integrity refusal'):
        collect(slots, tmp_path, lambda: pytest.fail('model call'))
    result = inspect(slots, tmp_path)
    assert result['counts'] == {
        'completed': 0, 'refused': 1, 'interrupted': 0, 'unattempted': 63}
    assert result['roots'][4]['status'] == 'refused'


def test_all_completed_roots_are_reused_without_collection(completed_run, slots):
    tmp_path = completed_run
    result = inspect(slots, tmp_path)
    assert result['counts'] == {
        'completed': 64, 'refused': 0, 'interrupted': 0, 'unattempted': 0}


def test_mismatched_binding_refuses_before_root_inspection(completed_run, slots):
    tmp_path = completed_run
    before = (tmp_path / 'schedule.json').read_bytes()
    with pytest.raises(ValueError, match='schedule binding mismatch'):
        inspect(slots, tmp_path, packet_sha256='c' * 64)
    assert (tmp_path / 'schedule.json').read_bytes() == before


@pytest.mark.parametrize('damage', ['contradictory', 'corrupt', 'partial'])
def test_contradictory_or_corrupt_completion_is_interrupted(
        completed_run, completed_source, slots, damage):
    tmp_path = completed_run
    first_root = root(tmp_path, slots[0]['fixture'])
    completion = first_root / 'completed.json'
    source_completion = completed_source / completion.relative_to(tmp_path)
    source_bytes = source_completion.read_bytes()
    assert completion.stat().st_ino != source_completion.stat().st_ino
    if damage == 'contradictory':
        failed = first_root / 'failed.json'
        failed.write_bytes(b'contradictory')
        failed.chmod(0o400)
    elif damage == 'partial':
        completion.rename(first_root / '.completed.json.partial')
    else:
        original = completion.read_bytes()
        completion.chmod(0o600)
        completion.write_bytes(original[:-1] + b'!')
        completion.chmod(0o400)
    result = inspect(slots, tmp_path)
    assert result['roots'][0]['status'] == 'interrupted'
    assert result['counts']['completed'] == 63
    assert source_completion.read_bytes() == source_bytes
    assert not (source_completion.parent / 'failed.json').exists()


def test_live_root_lock_conflict_fails_closed_without_model_work(tmp_path, slots):
    with pytest.raises(TimeoutError, match='expired'):
        collect(slots, tmp_path, lambda: pytest.fail('model call'),
                check_budget=lambda: (_ for _ in ()).throw(TimeoutError('expired')))
    state = root(tmp_path, slots[0]['fixture'])
    descriptor = os.open(state / 'owner.lock', os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            inspect(slots, tmp_path)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize('damage', ['missing', 'symlink', 'fifo'])
def test_unsafe_refusal_record_never_becomes_a_root_state(tmp_path, slots, damage):
    slots[4] = dict(root_id=slots[4]['root_id'], draw_index=4,
                    status='refused', stage='shard', reason='synthetic')
    with pytest.raises(ValueError, match='input integrity'):
        collect(slots, tmp_path, lambda: pytest.fail('model call'))
    record = tmp_path / 'refused-04.json'
    record.unlink()
    if damage == 'symlink':
        record.symlink_to(tmp_path / 'schedule.json')
    elif damage == 'fifo':
        os.mkfifo(record)
    with pytest.raises(ValueError, match='refusal'):
        inspect(slots, tmp_path)


@pytest.mark.parametrize('name', ['refused-04.json', '.refused-04.json.partial',
                                'refused-64.json'])
def test_unscheduled_refusal_artifact_is_rejected(tmp_path, slots, name):
    def expired():
        raise TimeoutError('before start')
    with pytest.raises(TimeoutError):
        collect(slots, tmp_path, lambda: pytest.fail('model call'), check_budget=expired)
    (tmp_path / name).write_bytes(b'contradictory refusal')
    with pytest.raises(ValueError, match='refusal artifact inventory mismatch'):
        inspect(slots, tmp_path)
