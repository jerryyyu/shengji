import copy

import pytest

from shengji.luna.benchmark_failure_protocol import attempt_disposition, PRESERVE_ILLEGAL
from shengji.luna.benchmark_failure_protocol import summarize_scheduled


def failed():
    return {'complete': False, 'flip': 1, 'error': 'IllegalPlay: must follow',
            'events': [{'seat': 3, 'attempted_cards': ['C7']}],
            'failure': {'schema': 'benchmark-action-failure-v1',
                        'category': 'model_illegal_action', 'stage': 'engine_play',
                        'seat': 3, 'attempted_cards': ['C7'], 'event_index': 0}}


def test_explicit_opt_in_preserves_failure_without_mutation():
    row = failed()
    original = copy.deepcopy(row)
    assert attempt_disposition(row) == 'stop'
    assert attempt_disposition(row, protocol=PRESERVE_ILLEGAL) == 'retained-model-failure'
    assert row == original and row['complete'] is False


@pytest.mark.parametrize('field,value', [
    ('schema', 'legacy'), ('category', 'provider_error'), ('stage', 'policy_decision'),
    ('seat', 2), ('seat', True), ('event_index', True), ('event_index', 1),
    ('attempted_cards', ['C8']), ('attempted_cards', []),
])
def test_malformed_or_other_failure_refuses(field, value):
    row = failed()
    row['failure'][field] = value
    assert attempt_disposition(row, protocol=PRESERVE_ILLEGAL) == 'stop'


@pytest.mark.parametrize('field,value', [
    ('complete', 0), ('complete', True), ('flip', True), ('flip', 0),
    ('events', []), ('error', None), ('status', 'setup_failed'),
])
def test_inconsistent_row_refuses(field, value):
    row = failed()
    row[field] = value
    assert attempt_disposition(row, protocol=PRESERVE_ILLEGAL) == 'stop'


def test_legacy_error_text_is_not_proof():
    row = failed()
    del row['failure']
    assert attempt_disposition(row, protocol=PRESERVE_ILLEGAL) == 'stop'


def test_unattempted_is_distinct_from_terminal_failure():
    row = {'complete': False, 'status': 'not_run', 'calls': []}
    assert attempt_disposition(row, protocol=PRESERVE_ILLEGAL) == 'unattempted'
    row['calls'] = [{}]
    assert attempt_disposition(row, protocol=PRESERVE_ILLEGAL) == 'stop'


def test_completed_game_and_unknown_protocol():
    assert attempt_disposition({'complete': True}) == 'complete'
    with pytest.raises(ValueError):
        attempt_disposition(failed(), protocol='retry')


def scheduled_failure(seed=1):
    row = failed()
    row.update(information='perfect', seed=seed)
    return row


def completed(seed=1, flip=0, score=3):
    return dict(complete=True, information='perfect', seed=seed, flip=flip,
                signed_levels=score)


def test_forfeit_pair_keeps_failed_mirror_and_drops_completed_only_pair():
    summary = summarize_scheduled([completed(), scheduled_failure()])
    mode = summary['modes']['perfect']
    assert mode['completed_paired_mean'] is None
    assert mode['forfeit_paired_mean'] == 1  # (3 + -1) / 2
    assert mode['failure_rate'] == .5 and mode['failed'] == 1


def test_unattempted_never_becomes_forfeit():
    pending = dict(complete=False, status='not_run', information='perfect', seed=1, flip=1)
    summary = summarize_scheduled([completed(), pending])['modes']['perfect']
    assert summary['forfeit_paired_mean'] is None
    assert summary['unattempted'] == 1 and summary['failed'] == 0


def test_failure_limit_counts_row_across_modes():
    rows = []
    for seed in range(8):
        pair = [completed(seed), scheduled_failure(seed)]
        if seed >= 4:
            for row in pair:
                row['information'] = 'actor-only'
        rows.extend(pair)
    assert summarize_scheduled(rows)['stop_required'] is True
    assert summarize_scheduled(rows[:-2])['stop_required'] is False


def test_success_pair_unchanged_and_input_not_mutated():
    rows = [completed(score=3), completed(flip=1, score=-1)]
    original = copy.deepcopy(rows)
    mode = summarize_scheduled(rows)['modes']['perfect']
    assert mode['completed_paired_mean'] == mode['forfeit_paired_mean'] == 1
    assert rows == original


@pytest.mark.parametrize('rows', [
    [completed()], [completed(), completed()],
    [completed(), completed(flip=1, score=float('nan'))],
    [completed(), completed(flip=1, score=True)],
    [completed(), dict(complete=False, information='perfect', seed=1, flip=1, error='timeout')],
])
def test_invalid_schedules_or_infra_failure_refuse(rows):
    with pytest.raises(ValueError):
        summarize_scheduled(rows)
