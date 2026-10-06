import copy
import json

import pytest

from shengji.eval.s11_schedule import collect_s11_schedule
from shengji.eval.s11_public_view import public_s11_fixture
from test_s11_collection import factory
from test_s11_public_view import trajectory

PIN = 'a' * 64


@pytest.fixture
def slots(trajectory):
    return [dict(root_id=f's11-{PIN}-draw-{draw:02d}', draw_index=draw,
        status='valid', selected_ply=98, fixture=public_s11_fixture(
            trajectory, 98, root_id=f's11-{PIN}-draw-{draw:02d}')) for draw in range(64)]


def run(slots, path, build, ceiling=0):
    return collect_s11_schedule(slots, path, build, manifest_sha256=PIN,
        packet_sha256='b' * 64, seed=17, max_public_refusals=ceiling)


def refusal(slot, stage='public-projection'):
    return dict(root_id=slot['root_id'], draw_index=slot['draw_index'],
                status='refused', stage=stage, reason='synthetic refusal')


@pytest.mark.parametrize('with_refusal', [False, True])
def test_real_collection_full_accounting_and_reuse(tmp_path, slots, with_refusal):
    if with_refusal:
        slots[4] = refusal(slots[4])
    calls = dict(leaves=0, policy=[], bots=[])
    summary = run(slots, tmp_path, factory(calls), ceiling=int(with_refusal))
    assert summary['scheduled_count'] == 64 and summary['missing_count'] == 0
    assert summary['coverage_complete'] is (not with_refusal)
    assert summary['valid_count'] == 64 - int(with_refusal)
    assert summary['refused_count'] == int(with_refusal)
    assert len(calls['policy']) == 64 - int(with_refusal)
    saved = json.loads((tmp_path / 'summary.json').read_text())
    assert saved == summary
    assert run(slots, tmp_path, lambda: pytest.fail('repeated model work'),
               ceiling=int(with_refusal)) == summary
    if with_refusal:
        assert json.loads((tmp_path / 'refused-04.json').read_text()) == slots[4]


@pytest.mark.parametrize('stage,ceiling', [('public-projection', 0), ('shard', 63), ('terminal', 63)])
def test_refusal_gates_before_inference_and_are_durable(tmp_path, slots, stage, ceiling):
    slots[0] = refusal(slots[0], stage)
    with pytest.raises(ValueError, match='refusal'):
        run(slots, tmp_path, lambda: pytest.fail('inference despite refusal'), ceiling=ceiling)
    assert (tmp_path / 'schedule.json').exists() and (tmp_path / 'refused-00.json').exists()
    assert not (tmp_path / 'summary.json').exists()


def test_schedule_change_cannot_relax_a_spent_gate(tmp_path, slots):
    slots[0] = refusal(slots[0])
    with pytest.raises(ValueError, match='ceiling'):
        run(slots, tmp_path, lambda: pytest.fail('inference'))
    before = (tmp_path / 'schedule.json').read_bytes()
    with pytest.raises(ValueError):
        run(slots, tmp_path, lambda: pytest.fail('changed ceiling'), ceiling=1)
    assert (tmp_path / 'schedule.json').read_bytes() == before


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reordered', 'wrong-ply'])
def test_schedule_must_match_frozen_coordinates_before_io(tmp_path, slots, damage):
    if damage == 'missing':
        slots.pop()
    elif damage == 'duplicate':
        slots[1] = copy.deepcopy(slots[0])
    elif damage == 'reordered':
        slots.reverse()
    else:
        slots[0]['selected_ply'] = 97
    with pytest.raises(ValueError):
        run(slots, tmp_path, lambda: pytest.fail('invalid schedule'))
    assert list(tmp_path.iterdir()) == []


def test_failed_collection_never_becomes_partial_success_or_retries(tmp_path, slots):
    def fail():
        raise RuntimeError('synthetic model failure')
    with pytest.raises(RuntimeError):
        run(slots, tmp_path, fail)
    assert not (tmp_path / 'summary.json').exists()
    with pytest.raises(ValueError, match='explicit disposition'):
        run(slots, tmp_path, lambda: pytest.fail('repeated failed root'))


def test_failure_after_completion_preserves_prefix_without_recomputing(tmp_path, slots):
    calls = dict(leaves=0, policy=[], bots=[])
    build = factory(calls)
    def fail_second_root():
        if len(calls['bots']) == 2:
            raise RuntimeError('second root failure')
        return build()
    with pytest.raises(RuntimeError, match='second root'):
        run(slots, tmp_path, fail_second_root)
    assert len(calls['policy']) == 1
    assert len(list(tmp_path.glob('*/completed.json'))) == 1
    assert not (tmp_path / 'summary.json').exists()
    with pytest.raises(ValueError, match='explicit disposition'):
        run(slots, tmp_path, lambda: pytest.fail('prefix recomputed or failure retried'))
