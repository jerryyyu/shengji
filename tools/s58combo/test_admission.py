"""Synthetic producer recipes through admission and the paired consumer."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admission import admit_records
from paired_result import paired_result
from test_paired_result import fixture
from shengji.train.cwv_shortlist_screen import _recipe
from shengji.train.screen_deadline import RECIPE as DEADLINE_RECIPE


def packet(tmp_path):
    windows, records = fixture(tmp_path)
    arms = {side: dict(name=name, identity={'test_identity': name})
            for side, name in [('candidate', 'a'), ('comparator', 'b')]}
    plan = dict(windows=windows, arms=arms)
    configs, shards = {}, {}
    for w in windows:
        arm = arms[w['side']]
        config = dict(schema='synthetic-config', arm='policy', arm_policy=arm['name'],
                      arm_policy_identity=arm['identity'], baseline='production',
                      seed0=w['seed'], clusters=520, trump_ranks=w['ranks'].split(','),
                      round_kind=w['round_kind'], decision_deadline=dict(DEADLINE_RECIPE),
                      checkpoint_sha256=None, shortlist={}, report_worlds=300,
                      production_multiplier=1, target_wall_multiplier=1)
        if w['round_kind'] == 'first':
            del config['round_kind']
        configs[w['output']] = config
        rows = records[w['output']]
        for row in rows:
            row['arm'] = 'policy'
            row['arm_utility'] = row['cluster'] % 2 if w['side'] == 'candidate' else 0
        shards[w['output']] = [dict(schema='cwv-shortlist-shard-v1', cluster=c,
                                    seed=w['seed'] + c, rank=rows[2*c]['trump_rank'],
                                    recipe=_recipe(config), records=rows[2*c:2*c+2])
                               for c in range(520)]
    return plan, copy.deepcopy(configs), configs, shards


def test_producer_recipe_to_admission_to_paired_estimator(tmp_path):
    args = packet(tmp_path)
    records = admit_records(*args)
    result = paired_result(args[0]['windows'], records)
    assert result['candidate_minus_comparator_levels_per_round']['mean'] == pytest.approx(.5)
    assert len(result['windows']) == 10


@pytest.mark.parametrize('defect', ['config', 'identity', 'recipe', 'missing', 'duplicate',
                                  'mirror', 'inventory', 'plan'])
def test_refuses_before_outcomes_are_returned(tmp_path, defect):
    plan, expected, configs, shards = packet(tmp_path)
    out = plan['windows'][-1]['output']
    if defect == 'config':
        configs[out]['decision_deadline'] = 0
    elif defect == 'identity':
        expected[out]['arm_policy_identity'] = configs[out]['arm_policy_identity'] = {}
    elif defect == 'recipe':
        shards[out][0]['recipe']['baseline'] = 'different'
    elif defect == 'missing':
        shards[out].pop()
    elif defect == 'duplicate':
        shards[out][-1] = shards[out][0]
    elif defect == 'mirror':
        shards[out][0]['records'][1]['mirror'] = 0
    elif defect == 'inventory':
        del shards[out]
    else:
        plan['windows'][-1]['seed'] += 1
    with pytest.raises(ValueError):
        admit_records(plan, expected, configs, shards)
