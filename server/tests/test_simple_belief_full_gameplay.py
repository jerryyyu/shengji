import copy
import hashlib
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from shengji.train import simple_belief_full_gameplay as full
from shengji.train import simple_belief_gameplay as game
from shengji.train.cwv_bury_policy import CWVBuryConfig


def config(tmp_path):
    model = tmp_path / 'small.pt'
    model.write_bytes(b'model fixture')
    return {'output': str(tmp_path), 'config_sha256': 'cfg',
            'checkpoint': '/unused', 'checkpoint_sha256': 'value',
            'small_checkpoint': str(model),
            'small_checkpoint_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
            'cache_recipe_sha256': 'recipe', 'planned_deals': full.planned_deals(),
            'policy_seed_namespace': full.NAMESPACE,
            'arms': [('ordinary', None), ('uniform-pool', 0), ('uniform-pool', 1),
                     ('new-small', 0), ('new-small', 1)]}


def test_population_rank_balance_distinct_streams_and_real_round_preparation(tmp_path):
    c = config(tmp_path)
    specs = c['planned_deals']
    assert len(specs) == 260 == len({s['seed'] for s in specs})
    assert set(Counter(s['rank'] for s in specs).values()) == {20}
    assert set(Counter(s['initial_banker'] for s in specs).values()) == {52}
    assert not {s['seed'] for s in specs} & {game.spec_for(i)['seed'] for i in range(14)}
    for i in (0, 4, 13, 129, 259):
        rnd, _ = game.prepare_round(game.spec_for(i, c), c)
        assert rnd.phase == 'bury' and sorted(map(len, rnd.hands)) == [25, 25, 25, 33]
        assert [game.policy_seed(i,s,c) for s in range(4)] != [game.policy_seed(i,s) for s in range(4)]


def test_actual_cluster_wiring_no_r4_correct_mirrors_and_resume(tmp_path, monkeypatch):
    c = config(tmp_path)
    evaluator = SimpleNamespace(checkpoint_sha256='value', identity=lambda: {})
    monkeypatch.setattr(game, 'shared_evaluator', lambda *a, **kw: evaluator)
    predictor = object()
    monkeypatch.setattr(game, 'SmallBeliefPredictor', lambda *a: predictor)
    monkeypatch.setattr(game, 'R4RuntimeClient', lambda *a: pytest.fail('no R4 arm requested'))
    calls = []
    def make(mode, evaluator, seed, config, client, small):
        assert client is None and small is predictor
        return SimpleNamespace(mode=mode, seed=seed, bury_config=CWVBuryConfig())
    monkeypatch.setattr(game, '_make_bot', make)
    def play(rnd, bots, cluster, arm, team):
        calls.append((arm, team, [b.mode for b in bots], [b.seed for b in bots]))
        return {'team0_signed_levels': 1, 'banker': rnd.banker, 'attacker_points': 40,
                'kitty_bonus': 0, 'buried': list(rnd.hands[rnd.banker][:8]),
                'transcript': [], 'child_inference_wall_s': 0.0}
    monkeypatch.setattr(game, 'play_round', play)
    monkeypatch.setattr(game, '_work_counters', lambda *a: {})
    shard = game.run_cluster(c, 25)
    assert len(calls) == 5
    for arm, team, modes, seeds in calls:
        assert modes == [arm if s % 2 == team else 'ordinary' for s in range(4)]
        assert seeds == [game.policy_seed(25,s,c) for s in range(4)]
    monkeypatch.setattr(game, 'shared_evaluator', lambda *a, **kw: pytest.fail('completed arms rerun'))
    assert game.run_cluster(c,25) == shard
    path = tmp_path / 'cluster.json'
    path.write_text(json.dumps(shard))
    assert game.read_cluster(path,c,25) == shard
    shard['records'][3]['focal_team'] = 1
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match='^saved gameplay arm identity differs$'):
        game.read_cluster(path,c,25)


def test_summary_counts_deals_not_mirrors_and_compares_weighting_control(tmp_path):
    c = config(tmp_path)
    rows = [{'arm': a, 'focal_team': t, 'outcome': {'team0_signed_levels': score}}
            for (a,t),score in zip(c['arms'],[1,1,1,2,-2],strict=True)]
    s = game.summarize([{'records': rows}], c)
    assert s['rounds'] == 5 and s['independent_deals'] == 1 and not s['complete']
    assert set(s['comparisons']) == {'new-small', 'uniform-pool'}
    assert s['comparisons']['uniform-pool']['signed_levels']['mean'] == 0
    assert s['learned_minus_uniform']['signed_levels']['mean'] == 2
    with pytest.raises(ValueError, match='^incomplete arm population before aggregate$'):
        game.summarize([{'records':rows[:-1]}],c)


def test_overlap_refuses_real_deck_and_missing_mirror_refuses(tmp_path):
    c = config(tmp_path)
    spec = c['planned_deals'][0]
    rnd, _ = game.prepare_round(spec,c)
    key = game.record_deal_key({'deck':rnd.deck})
    recipe = tmp_path/'recipe.json'
    recipe.write_text(json.dumps({'deals':[{'deal_key':key}]}))
    with pytest.raises(ValueError, match='fresh gameplay deals overlap cache recipe'):
        game._fresh_check(recipe,[spec])
    c['arms'] = c['arms'][:-1]
    with pytest.raises(ValueError, match='^configured treatment mirrors differ$'):
        game.schedule(c)
