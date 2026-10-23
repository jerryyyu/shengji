"""Symmetric adversarial decision validity with synthetic producer-shaped traces."""
import copy
import sys
from pathlib import Path
import random

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_gate import check_decisions


def declaration():
    return dict(schema='pv-value-declare-decision-v1', evaluated=True, changed=False,
                final=False, fallback_reason=None, seconds=.1, worlds=64, worlds_completed=64,
                leaf_first_trick='heuristic', leaf_first_trick_fallbacks=0,
                cards_dealt=80, played='PASS', heuristic='PASS')


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
                    decisions=[dict(seat=seat, trick=0, schema='pv-search-decision-v1',
                                    worlds=64, belief_fallback=0)],
                    declare_decisions=[declaration()]))
        shards[arm] = [shard]
    return plan, shards


def test_valid_decisions_on_both_arms():
    result = check_decisions(*inputs())
    assert result['verdict'] == 'VALID'
    assert result['counts']['candidate'] == result['counts']['comparator']


def test_actual_trace_wrapper_matches_committed_play_keys():
    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game
    from shengji.train.search_screen import TimedPolicy

    class Bot(HeuristicBot):
        def decide_play(self, rnd, seat):
            played = super().decide_play(rnd, seat)
            self.last_decision_record = dict(schema='pv-search-decision-v1', worlds=64,
                                             belief_fallback=0, played=played)
            return played
    helper = HeuristicBot()
    rnd = prepare_round(Game(random.Random(17)), [helper for _ in range(4)])
    bots = [TimedPolicy(Bot()) for _ in range(4)]
    history = []
    while len(rnd.history) < 3:
        seat = rnd.turn
        played = bots[seat].decide_play(rnd, seat)
        rnd.play(seat, played)
        history.append([seat, list(played)])
    assert len(history) == 12
    assert all([r['trick'] for r in bot.decisions] == [0, 1, 2] for bot in bots)
    plan, shards = inputs()
    for per_arm in shards.values():
        for row in per_arm[0]['records']:
            row['committed_history'] = copy.deepcopy(history)
        for trace in per_arm[0]['decision_traces']:
            seat = trace['decisions'][0]['seat']
            trace['decisions'] = copy.deepcopy(bots[seat].decisions)
    assert check_decisions(plan, shards)['verdict'] == 'VALID'


@pytest.mark.parametrize('defect', ['partial_trick', 'duplicate_seat', 'play_index'])
def test_rejects_malformed_trick_coverage(defect):
    plan, shards = inputs()
    shard = shards['comparator'][0]
    if defect == 'partial_trick':
        shard['records'][0]['committed_history'].pop()
    elif defect == 'duplicate_seat':
        shard['records'][0]['committed_history'][1][0] = 0
    else:
        shard['decision_traces'][1]['decisions'][0]['trick'] = 2
    assert check_decisions(plan, shards)['verdict'] == 'SCREEN_INVALID'


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


@pytest.mark.parametrize('defect', ['worlds', 'declare_schema'])
def test_valid_outcomes_cannot_bypass_invalid_decisions(monkeypatch, defect):
    import outcome_gate as gate
    from test_outcome_gate import row
    plan, shards = inputs()
    trace = shards['comparator'][0]['decision_traces'][0]
    if defect == 'worlds':
        trace['decisions'][0]['worlds'] = 1
    else:
        trace['declare_decisions'][0]['schema'] = 'unknown'
    monkeypatch.setattr(gate, 'admit_records', lambda *args: {'synthetic': [row(80)]})
    def forbidden(*args):
        pytest.fail('estimator reached despite invalid comparator')
    monkeypatch.setattr(gate, 'paired_result', forbidden)
    result = gate.outcome_checked_result(plan, {}, {}, shards)
    assert result['status'] == 'DECISION_INVALID' and 'estimate' not in result


@pytest.mark.parametrize('arm', ['candidate', 'comparator'])
@pytest.mark.parametrize('patch', [dict(schema='unknown'), dict(evaluated=1),
    dict(fallback_reason='hard_budget'), dict(seconds=float('nan')), dict(worlds=True),
    dict(leaf_first_trick_fallbacks=1), dict(cards_dealt=101), dict(played='C2'),
    dict(evaluated=False, fallback_reason='error', changed=True, played='C2')])
def test_malformed_declaration_refuses_on_either_arm(arm, patch):
    plan, shards = inputs()
    shards[arm][0]['decision_traces'][0]['declare_decisions'][0].update(patch)
    assert check_decisions(plan, shards)['verdict'] == 'SCREEN_INVALID'


@pytest.mark.parametrize('defect', ['empty', 'baseline'])
def test_invalid_declaration_trace_refuses(defect):
    plan, shards = inputs()
    trace = shards['comparator'][0]['decision_traces'][0]
    if defect == 'empty':
        trace['declare_decisions'] = []
    else:
        shards['comparator'][0]['decision_traces'].append(
            dict(side='baseline', declare_decisions=[declaration()]))
    assert check_decisions(plan, shards)['verdict'] == 'SCREEN_INVALID'


def test_real_value_declare_through_wrapper_and_admission():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server' / 'tests'))
    from test_cwv_leaf_policy_first_trick import served, CountingPredict, NTEvaluator, drive_declare, fresh_deal
    from shengji.train.search_screen import TimedPolicy
    policy = TimedPolicy(served(CountingPredict(), NTEvaluator(), value_declare=True,
                                value_declare_worlds=2))
    drive_declare(fresh_deal(5, True), policy)
    assert policy.declare_decisions
    plan, shards = inputs()
    for arm in plan['arms']:
        plan['arms'][arm]['identity']['config']['value_declare_worlds'] = 2
        for trace in shards[arm][0]['decision_traces']:
            trace['declare_decisions'] = copy.deepcopy(policy.declare_decisions)
    assert check_decisions(plan, shards)['verdict'] == 'VALID'
    shards['comparator'][0]['decision_traces'][0]['declare_decisions'][0]['changed'] = True
    assert check_decisions(plan, shards)['verdict'] == 'SCREEN_INVALID'
