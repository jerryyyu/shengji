"""Symmetric adversarial decision validity with synthetic producer-shaped traces."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_gate import check_decisions


def inputs():
    plan = dict(arms={a: {'identity': {'config': dict(worlds=64, value_declare_worlds=64)}}
                     for a in ('candidate', 'comparator')}, windows=[])
    shards = {}
    for arm in plan['arms']:
        plan['windows'].append(dict(output=arm, side=arm))
        shard = dict(records=[dict(mirror=m, committed_history=[[s, ['C7']] for s in range(4)])
                              for m in (0, 1)], decision_traces=[])
        for m in (0, 1):
            for seat in range(m, 4, 2):
                shard['decision_traces'].append(dict(side='arm', mirror=m,
                    decisions=[dict(seat=seat, trick=seat, schema='pv-search-decision-v1',
                                    worlds=64, belief_fallback=0)],
                    declare_decisions=[dict(evaluated=True, worlds=64, worlds_completed=64)]))
        shards[arm] = [shard]
    return plan, shards


def test_valid_decisions_on_both_arms():
    result = check_decisions(*inputs())
    assert result['verdict'] == 'VALID'
    assert result['counts']['candidate'] == result['counts']['comparator']


def test_actual_trace_wrapper_matches_committed_play_keys():
    from shengji.train.search_screen import TimedPolicy

    class Bot:
        def decide_play(self, rnd, seat):
            self.last_decision_record = dict(schema='pv-search-decision-v1', worlds=64,
                                             belief_fallback=0, played=['C7'])
            return ['C7']
    plan, shards = inputs()
    for per_arm in shards.values():
        for trace in per_arm[0]['decision_traces']:
            seat = trace['decisions'][0]['seat']
            bot = TimedPolicy(Bot())
            bot.decide_play(SimpleNamespace(history=[None] * seat), seat)
            trace['decisions'] = bot.decisions
    assert check_decisions(plan, shards)['verdict'] == 'VALID'


@pytest.mark.parametrize('arm', ['candidate', 'comparator'])
@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'worlds', 'fallback', 'belief', 'declare', 'unknown'])
def test_symmetric_adversarial_refusals(arm, defect):
    plan, shards = inputs()
    trace = shards[arm][0]['decision_traces'][0]
    rec = trace['decisions'][0]
    if defect == 'missing':
        trace['decisions'].clear()
    elif defect == 'duplicate':
        trace['decisions'].append(copy.deepcopy(rec))
    elif defect == 'worlds':
        rec['worlds'] = 63
    elif defect == 'fallback':
        rec.update(schema='pv-search-fallback-v1', worlds=None)
    elif defect == 'belief':
        rec['belief_fallback'] = 1
    elif defect == 'declare':
        trace['declare_decisions'][0]['worlds_completed'] = 63
    else:
        rec['schema'] = 'unknown'
    assert check_decisions(plan, shards)['verdict'] == 'SCREEN_INVALID'


def test_valid_outcomes_cannot_bypass_invalid_decisions(monkeypatch):
    import outcome_gate as gate
    from test_outcome_gate import row
    plan, shards = inputs()
    shards['comparator'][0]['decision_traces'][0]['decisions'][0]['worlds'] = 1
    monkeypatch.setattr(gate, 'admit_records', lambda *args: {'synthetic': [row(80)]})
    def forbidden(*args):
        pytest.fail('estimator reached despite invalid comparator')
    monkeypatch.setattr(gate, 'paired_result', forbidden)
    result = gate.outcome_checked_result(plan, {}, {}, shards)
    assert result['status'] == 'DECISION_INVALID' and 'estimate' not in result
