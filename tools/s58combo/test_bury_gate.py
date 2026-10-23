"""Banker coverage and all-arm optional-stage fault ceilings."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server' / 'tests'))
from bury_gate import check_optional_stages, _bury_valid
from test_decision_gate import inputs


def receipt(seat=0):
    return dict(seat=seat, schema='cwv-bury-policy-v1', elapsed_seconds=.1,
        fallback_reason=None, leaf_first_trick='heuristic', leaf_first_trick_fallbacks=0,
        candidate_count=2, model_positions=4, finalist_count=0, mc_rollouts=0,
        mc_evidence=None, selection_worlds=0, shortlist=[0], rollout_seconds=0.,
        candidates__len=2, model_means__len=2, model_worlds=2, picked_index=0)


def packet():
    plan, shards = inputs()
    for arm in shards.values():
        shard = arm[0]
        for row in shard['records']:
            row['banker'] = row['mirror']
        for trace in shard['decision_traces']:
            seat = trace['decisions'][0]['seat']
            trace['bury_decisions'] = [receipt(seat)] if seat == trace['mirror'] else []
    return plan, shards


def test_valid_stages():
    result = check_optional_stages(*packet())
    assert result['verdict'] == 'VALID'
    assert result['counts']['candidate'] == dict(buries=2, bury_fallback=0, declares=4, declare_abandon=0)


@pytest.mark.parametrize('kind,failures,valid', [('bury', 1, True), ('bury', 2, False),
                                               ('declare', 2, True), ('declare', 3, False)])
def test_one_percent_ceiling_boundary(kind, failures, valid):
    plan, shards = packet()
    for side in shards:
        shards[side] = [copy.deepcopy(shards[side][0]) for _ in range(50)]
    for shard in shards['comparator'][:failures]:
        trace = shard['decision_traces'][0]
        if kind == 'bury':
            trace['bury_decisions'][0].update(schema='cwv-bury-fallback-v1', fallback_reason='budget',
                                              candidate_count=None, model_positions=0)
        else:
            trace['declare_decisions'][0].update(evaluated=False, fallback_reason='hard_budget', worlds_completed=0)
    assert (check_optional_stages(plan, shards)['verdict'] == 'VALID') == valid


@pytest.mark.parametrize('side', ['candidate', 'comparator'])
@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'wrong_banker', 'schema', 'positions', 'bury_fallback', 'declare_abandon'])
def test_symmetric_optional_stage_refusal(side, defect):
    plan, shards = packet()
    trace = shards[side][0]['decision_traces'][0]
    rec = trace['bury_decisions'][0]
    if defect == 'missing':
        trace['bury_decisions'] = []
    elif defect == 'duplicate':
        trace['bury_decisions'].append(copy.deepcopy(rec))
    elif defect == 'wrong_banker':
        rec['seat'] = 2
    elif defect == 'schema':
        rec['schema'] = 'unknown'
    elif defect == 'positions':
        rec['model_positions'] = 3
    elif defect == 'bury_fallback':
        rec.update(schema='cwv-bury-fallback-v1', fallback_reason='budget', candidate_count=None, model_positions=0)
    else:
        trace['declare_decisions'][0].update(evaluated=False, fallback_reason='hard_budget', worlds_completed=0)
    assert check_optional_stages(plan, shards)['verdict'] == 'SCREEN_INVALID'


def test_optional_stage_refusal_blocks_estimator(monkeypatch):
    import outcome_gate as consumer
    plan, shards = packet()
    shards['comparator'][0]['decision_traces'][0]['bury_decisions'] = []
    monkeypatch.setattr(consumer, 'admit_records', lambda *a: {})
    for name in ('check_outcomes', 'check_decisions', 'check_exact'):
        monkeypatch.setattr(consumer, name, lambda *a: dict(verdict='VALID'))
    monkeypatch.setattr(consumer, 'paired_result', lambda *a: pytest.fail('faulty optional stage reached estimator'))
    assert consumer.outcome_checked_result(plan, {}, {}, shards)['status'] == 'OPTIONAL_STAGE_INVALID'


@pytest.mark.parametrize('budget', [None, 0.000000001])
def test_actual_wide_bury_to_trace_validator(budget):
    from test_cwv_bury_wide_value import served_bury, bury_state
    from shengji.train.search_screen import TimedPolicy
    bot = served_bury(bury_wide_value=True, bury_budget=budget)
    rnd = bury_state(65)
    policy = TimedPolicy(bot)
    policy.decide_bury(rnd, rnd.banker)
    rec, = policy.bury_decisions
    assert _bury_valid(rec)
    assert rec['schema'] == ('cwv-bury-policy-v1' if budget is None else 'cwv-bury-fallback-v1')
    rec['model_positions'] = -1
    assert not _bury_valid(rec)
