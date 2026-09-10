import json
import pytest

from shengji.train.r4_mixture_gameplay import ARMS, read_arm, read_cluster, schedule, spec_for, summarize


def outcome():
    return {'team0_signed_levels': 1, 'banker': 0, 'attacker_points': 60,
            'kitty_bonus': 0, 'transcript': [], 'buried': ['S2']*8}


def test_fresh_plan_all_ranks_first_round_and_unique_seeds():
    specs = [spec_for(i) for i in range(14)]
    assert len({s['seed'] for s in specs}) == 14
    assert len({s['rank'] for s in specs}) == 13
    assert specs[-1]['initial_banker'] is None
    assert {s['initial_banker'] for s in specs[:-1]} == {0, 1, 2, 3}
    assert len(schedule()) == 5  # one shared baseline, not two duplicate games


def test_team_perspective_and_deal_not_mirror_is_statistical_unit():
    rows = [{'arm': 'ordinary', 'focal_team': None,
             'outcome': {'team0_signed_levels': 1, 'kitty_bonus': 0}}]
    for name in ARMS:
        for team, levels in ((0, 2), (1, -1)):
            rows.append({'arm': name, 'focal_team': team,
                         'outcome': {'team0_signed_levels': levels, 'kitty_bonus': 10}})
    result = summarize([{'records': rows}])
    for n in ARMS:
        assert result['comparisons'][n]['signed_levels']['mean'] == 1.5
        assert result['comparisons'][n]['wins']['mean'] == .5
        assert result['comparisons'][n]['signed_levels']['n_independent_states'] == 1
    assert not result['complete'] and result['rounds'] == 5
    with pytest.raises(ValueError, match='five distinct'):
        summarize([{'records': rows+[rows[0]]}])


def test_completed_arm_refuses_wrong_recipe_and_team(tmp_path):
    path = tmp_path/'arm.json'
    config = {'config_sha256': 'a'}
    row = {'config_sha256': 'a', 'spec': spec_for(0), 'arm': ARMS[0], 'focal_team': 0,
           'outcome': outcome()}
    path.write_text(json.dumps(row))
    assert read_arm(path, config, spec_for(0), ARMS[0], 0) == row
    with pytest.raises(ValueError, match='saved gameplay arm identity differs'):
        read_arm(path, config, spec_for(0), ARMS[0], 1)
    with pytest.raises(ValueError, match='saved gameplay arm identity differs'):
        read_arm(path, {'config_sha256': 'b'}, spec_for(0), ARMS[0], 0)


@pytest.mark.parametrize('field,value,error', [
    ('spec', spec_for(1), 'arm identity'),
    ('config_sha256', 'other', 'arm identity'),
    ('focal_team', 1, 'arm identity'),
    ('arm', 'ordinary', 'arm identity'),
    ('outcome', {}, 'outcome shape'),
])
def test_actual_completed_cluster_reopen_checks_each_member(tmp_path, field, value, error):
    config = {'config_sha256': 'a'}
    records = [{'config_sha256': 'a', 'spec': spec_for(0), 'arm': arm, 'focal_team': team,
                'outcome': outcome()} for arm, team in schedule()]
    shard = {'config_sha256': 'a', 'cluster': 0, 'records': records}
    path = tmp_path/'cluster-00000.json'
    path.write_text(json.dumps(shard))
    assert read_cluster(path, config, 0) == shard
    records[1][field] = value
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match=error):
        read_cluster(path, config, 0)
