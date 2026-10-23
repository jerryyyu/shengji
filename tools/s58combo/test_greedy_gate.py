import copy
import pytest
from greedy_gate import FIELDS, SKIP, greedy_shape, check_greedy


def record(skipped=False, forced=False):
    values = [False, 0, 0, 0, 0, 0] if skipped else [True, 3, 6, 1, 2, 0]
    if forced:
        values = [True, 3, 0, 0, 0, 0]
    return dict(schema='pv-search-decision-v1', **dict(zip(FIELDS, values)),
                **{SKIP: skipped}, exact_lead_status='complete' if skipped else 'ineligible')


def packet():
    plan = dict(arms={s: dict(identity=dict(config=dict(leaf_greedy_finish=s == 'candidate',
                  leaf_greedy_finish_exact_skip=s == 'candidate'))) for s in ('candidate', 'comparator')},
                windows=[dict(side=s, output=s) for s in ('candidate', 'comparator')])
    shards = {s: [dict(decision_traces=[dict(side='arm', decisions=records)])]
              for s, records in [('candidate', [record(), record(True)]),
                                  ('comparator', [dict(schema='pv-search-decision-v1')])]}
    return plan, shards


@pytest.mark.parametrize('skipped,forced,shape', [(False,False,'applied'), (False,True,'applied'), (True,False,'skipped')])
def test_valid_producer_shapes(skipped, forced, shape):
    assert greedy_shape(record(skipped, forced), True) == shape


@pytest.mark.parametrize('key,value', [(FIELDS[0],1), (FIELDS[1],True), (FIELDS[1],-1),
    (FIELDS[2],11), (FIELDS[3],3), (FIELDS[4],4), (FIELDS[5],1), (SKIP,None), (SKIP,True)])
def test_bad_counts_and_skip_fail_closed(key, value):
    rec = record(); rec[key] = value
    with pytest.raises(ValueError): greedy_shape(rec, True)


@pytest.mark.parametrize('key', [*FIELDS, SKIP])
def test_missing_field_refused(key):
    rec = record(); del rec[key]
    with pytest.raises(ValueError): greedy_shape(rec, True)


def test_skip_zero_state_and_forced_follow():
    rec = record(True); rec[FIELDS[1]] = 1
    with pytest.raises(ValueError): greedy_shape(rec, True)
    rec = record(True); rec['exact_lead_status'] = 'ineligible'; rec['exact_follow_attempted'] = True
    assert greedy_shape(rec, True) == 'skipped'


@pytest.mark.parametrize('side', ['candidate', 'comparator'])
def test_recipe_mismatch_rejected(side):
    plan, shards = packet()
    plan['arms'][side]['identity']['config']['leaf_greedy_finish'] = side != 'candidate'
    assert check_greedy(plan, shards)['verdict'] == 'SCREEN_INVALID'


def test_activation_and_comparator_contamination():
    plan, shards = packet()
    assert check_greedy(plan, shards)['verdict'] == 'VALID'
    for index in [0, 1]:
        altered = copy.deepcopy(shards)
        del altered['candidate'][0]['decision_traces'][0]['decisions'][index]
        assert check_greedy(plan, altered)['verdict'] == 'SCREEN_INVALID'
    shards['comparator'][0]['decision_traces'][0]['decisions'][0][SKIP] = False
    assert check_greedy(plan, shards)['verdict'] == 'SCREEN_INVALID'


def test_contamination_blocks_real_consumer_estimation(monkeypatch):
    import outcome_gate as consumer
    plan, shards = packet()
    shards['comparator'][0]['decision_traces'][0]['decisions'][0][SKIP] = False
    monkeypatch.setattr(consumer, 'admit_records', lambda *a: {})
    for name in ('check_outcomes', 'check_decisions', 'check_exact', 'check_optional_stages', 'check_dtrx'):
        monkeypatch.setattr(consumer, name, lambda *a: dict(verdict='VALID'))
    monkeypatch.setattr(consumer, 'paired_result', lambda *a: pytest.fail('invalid greedy treatment reached estimator'))
    assert consumer.outcome_checked_result(plan, {}, {}, shards)['status'] == 'GREEDY_INVALID'


def test_not_applied_and_fallback_shapes():
    rec = record(True); rec[SKIP] = False; rec['exact_lead_status'] = 'ineligible'
    assert greedy_shape(rec, True) == 'not_applied'
    for enabled in (False, True):
        fallback = dict(schema='pv-search-fallback-v1', reason='budget')
        assert greedy_shape(fallback, enabled) == 'fallback'
        fallback[SKIP] = False
        with pytest.raises(ValueError): greedy_shape(fallback, enabled)


def test_valid_treatment_reaches_estimator_after_prior_gates(monkeypatch):
    import outcome_gate as consumer
    plan, shards = packet()
    monkeypatch.setattr(consumer, 'admit_records', lambda *a: {})
    for name in ('check_outcomes', 'check_decisions', 'check_exact', 'check_optional_stages', 'check_dtrx'):
        monkeypatch.setattr(consumer, name, lambda *a: dict(verdict='VALID'))
    calls = []
    monkeypatch.setattr(consumer, 'paired_result', lambda *a: calls.append(a) or {'fixture': True})
    result = consumer.outcome_checked_result(plan, {}, {}, shards)
    assert len(calls) == 1 and result['estimate'] == {'fixture': True}
    assert result['greedy_check']['verdict'] == 'VALID'
    assert result['status'] == 'STAGE_OUTCOME_CHECKED_ONLY'
