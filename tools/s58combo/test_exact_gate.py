"""Exact-stage producer receipts, symmetric refusal and estimator ordering."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server' / 'tests'))
import exact_gate as gate
from test_pv_search_serving import package


def packet():
    plan = dict(arms={a: dict(name=a) for a in ('candidate', 'comparator')}, windows=[])
    shards = {}
    for side in plan['arms']:
        plan['windows'].append(dict(side=side, output=side))
        shard = dict(records=[], decision_traces=[])
        for mirror in (0, 1):
            seats = [(mirror + i) % 4 for i in range(4)]
            shard['records'].append(dict(mirror=mirror, committed_history=[[s, ['C7']] for s in seats]))
            for seat in (mirror, mirror + 2):
                lead = seat == mirror
                rec = dict(policy=side, schema='pv-search-decision-v1', seat=seat, trick=0,
                           played=['C7'], worlds=64, seconds=.1, admitted__len=2,
                           exact_deep_cards=7, exact_lead_status='complete' if lead else 'ineligible',
                           exact_lead_worlds_completed=64 if lead else 0,
                           exact_lead_nodes=10 if lead else None,
                           exact_lead_cache_hits=0 if lead else None, exact_lead_changed=lead)
                if lead:
                    rec.update(exact_lead_base_level_mean=0., exact_lead_base_played=['D7'],
                        exact_lead_base_played__len=1, exact_lead_base_selected_index=0,
                        exact_lead_base_value_means__len=2, exact_lead_base_value_means=[0., 1.],
                        exact_lead_change_kind='higher', exact_lead_seconds=.05,
                        exact_lead_selected_level_delta=1., exact_lead_selected_level_mean=1.)
                else:
                    rec.update(exact_follow_attempted=True, exact_follow_applied=True,
                        exact_follow_abandoned=None, exact_follow_nodes=10, exact_follow_worlds=64,
                        exact_follow_scores__len=2, exact_follow_scores=[1., 0.],
                        admitted_indices=[0, 1], selected_index=0)
                shard['decision_traces'].append(dict(side='arm', mirror=mirror, decisions=[rec]))
        shards[side] = [shard]
    return plan, shards


def test_valid_exact_stages_on_both_arms():
    assert gate.check_exact(*packet())['verdict'] == 'VALID'


@pytest.mark.parametrize('side', ['candidate', 'comparator'])
@pytest.mark.parametrize('defect', ['missing', 'eligibility', 'worlds', 'cards', 'policy', 'follow', 'budget', 'malformed'])
def test_symmetric_exact_refusals(side, defect):
    plan, shards = packet()
    traces = shards[side][0]['decision_traces']
    rec = traces[0]['decisions'][0]
    if defect == 'missing':
        del rec['exact_deep_cards']
    elif defect == 'eligibility':
        rec['exact_lead_status'] = 'ineligible'
    elif defect == 'worlds':
        rec['exact_lead_worlds_completed'] = 63
    elif defect == 'cards':
        rec['played'] = ['D7']
    elif defect == 'policy':
        rec['policy'] = 'other'
    elif defect == 'follow':
        traces[1]['decisions'][0]['selected_index'] = 1
    elif defect == 'budget':
        for k in list(rec):
            if k.startswith('exact_lead_'):
                del rec[k]
        rec.update(exact_lead_status='skipped_budget', exact_lead_worlds_completed=0,
                   exact_lead_nodes=None, exact_lead_cache_hits=None, exact_lead_changed=False)
    else:
        rec['exact_lead_change_kind'] = []
    assert gate.check_exact(plan, shards)['verdict'] == 'SCREEN_INVALID'


def test_exact_refusal_prevents_estimation(monkeypatch):
    import outcome_gate as consumer
    plan, shards = packet()
    del shards['comparator'][0]['decision_traces'][0]['decisions'][0]['exact_deep_cards']
    monkeypatch.setattr(consumer, 'admit_records', lambda *a: {})
    monkeypatch.setattr(consumer, 'check_outcomes', lambda *a: dict(verdict='VALID'))
    monkeypatch.setattr(consumer, 'check_decisions', lambda *a: dict(verdict='VALID'))
    monkeypatch.setattr(consumer, 'paired_result', lambda *a: pytest.fail('invalid exact evidence reached estimator'))
    assert consumer.outcome_checked_result(plan, {}, {}, shards)['status'] == 'EXACT_INVALID'


@pytest.mark.parametrize('abandon', [False, True])
def test_real_exact_lead_to_trace_validator(package, monkeypatch, abandon):
    from test_pv_finish_lead import root
    from shengji.train import pv_search_policy as pv, pv_exact_deep
    from shengji.train.search_screen import TimedPolicy
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=17, worlds=2, candidates=8, exact_lead_endgame=True, exact_deep_cards=7)
    if abandon:
        def fail(*a, **kw):
            raise RuntimeError('injected exact failure')
        monkeypatch.setattr(pv_exact_deep, 'exact_root_means', fail)
    rnd = root(2)
    policy = TimedPolicy(bot)
    policy.decide_play(rnd, rnd.turn)
    rec, = policy.decisions
    outcome = gate._ex_lead_outcome(rec, rec['exact_lead_status'], rec['admitted__len'])
    assert outcome is not None, str({k:v for k,v in rec.items() if k.startswith("exact_lead") or k in ("worlds", "admitted__len", "played")})
    assert outcome[0] == ('other_error' if abandon else 'complete')
    broken = copy.deepcopy(rec)
    broken['exact_lead_worlds_completed'] = 999
    assert gate._ex_lead_outcome(broken, broken['exact_lead_status'], broken['admitted__len']) is None
