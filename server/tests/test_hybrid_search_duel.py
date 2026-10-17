import json
from pathlib import Path

import pytest

from scripts import hybrid_search_duel as duel


class _Log:
    level_change = 2

    def __init__(self, winner_team):
        self.winner_team = winner_team


class _Bot:
    def __init__(self, seed):
        self.seed = seed
        self.hybrid_last_fields = {"hybrid_attempted": seed % 2 == 0,
                                   "hybrid_applied": True,
                                   "hybrid_changed": False,
                                   "hybrid_expired": False}


def test_runner_preserves_seeded_mirrors_and_reader_scores_clusters(monkeypatch, tmp_path):
    seen = []
    seats = []

    def factory(seed):
        seen.append(seed)
        return _Bot(seed)

    def play(game, bots):
        seats.append([bot.seed for bot in bots])
        # Candidate wins the first mirror and loses the second.  Candidate
        # team is determined by the runner, so the paired deal utility is 0.
        return _Log(0)

    monkeypatch.setattr(duel, "play_round", play)
    result = duel.run_duel(factory, factory, tmp_path / "out.jsonl", deals=1,
                           seed0=10, wall_seconds=10,
                           header={"recipe": {"model": "/pin.npz"}})
    assert result["deals"] == 1
    assert result["paired_utility_mean"] == 0.0
    assert seen == [10, 500010, 1000010, 1500010] * 2
    assert seats == [[10, 1000010, 500010, 1500010],
                     [1000010, 10, 1500010, 500010]]
    assert result["header"]["recipe"]["model"] == "/pin.npz"


def test_reader_rejects_duplicate_or_unpaired_final(tmp_path):
    path = tmp_path / "bad.jsonl"
    header = {"kind": "header", "schema": duel.SCHEMA}
    row = {"kind": "round", "seed": 1, "flip": 0,
           "level_utility": 1}
    terminal = {"kind": "terminal", "schema": duel.SCHEMA, "status": "COMPLETE",
                "completed_deals": 1, "paired_utility_mean": 1.0,
                "paired_utility_ci": None}
    path.write_text("\n".join(json.dumps(x) for x in (header, row, terminal)) + "\n")
    with pytest.raises(duel.DuelRefusal, match="unpaired"):
        duel.read_duel(path)


def test_partial_pair_has_no_terminal_or_score(monkeypatch, tmp_path):
    calls = 0

    def play(game, bots):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("deadline")
        return _Log(0)

    monkeypatch.setattr(duel, "play_round", play)
    path = tmp_path / "partial.jsonl"
    result = duel.run_duel(lambda seed: _Bot(seed), lambda seed: _Bot(seed),
                           path, deals=2, seed0=1, wall_seconds=10,
                           header={"recipe": {}})
    assert result["status"] == "FAILED"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert any(row.get("kind") == "terminal" for row in rows)
    assert sum(row.get("kind") == "round" for row in rows) == 1
    assert duel.read_duel(path)["status"] == "FAILED"


def test_wall_expiry_preserves_complete_prefix_and_dangling_mirror(monkeypatch, tmp_path):
    calls = 0
    def play(game, bots):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise duel.DuelWallExpired('cap')
        return _Log(0)
    monkeypatch.setattr(duel, 'play_round', play)
    path = tmp_path / 'partial.jsonl'
    result = duel.run_duel(_Bot, _Bot, path, deals=3, seed0=20,
                           wall_seconds=30, header={})
    assert result['status'] == 'PARTIAL'
    assert result['deals'] == 1
    assert result['paired_utility_mean'] == 0
    assert result['paired_utility_ci'] is None
    assert len(result['rows']) == 3
    with pytest.raises(FileExistsError):
        duel.run_duel(_Bot, _Bot, path, deals=1, seed0=20,
                      wall_seconds=30, header={})


def test_completed_mirror_is_durable_before_next_mirror(monkeypatch, tmp_path):
    path = tmp_path / 'interrupted.jsonl'
    calls = 0

    def play(game, bots):
        nonlocal calls
        calls += 1
        if calls == 2:
            saved = [json.loads(line) for line in path.read_text().splitlines()]
            assert [row['kind'] for row in saved] == ['header', 'round']
            assert saved[1]['seed'] == 20 and saved[1]['flip'] == 0
            raise KeyboardInterrupt('simulated non-cooperative stop')
        return _Log(0)

    monkeypatch.setattr(duel, 'play_round', play)
    with pytest.raises(KeyboardInterrupt):
        duel.run_duel(_Bot, _Bot, path, deals=1, seed0=20,
                      wall_seconds=30, header={})
    saved = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row['kind'] for row in saved] == ['header', 'round']
    with pytest.raises(duel.DuelRefusal, match='terminal'):
        duel.read_duel(path)


def test_telemetry_counts_each_decision_and_clears_stale_fields():
    class Bot:
        def decide_play(self, mode):
            if mode:
                self.hybrid_last_fields = {'hybrid_attempted': True,
                                           'hybrid_fallback': 'budget'}
            return ['C2']
    bot = Bot()
    duel._instrument(bot)
    bot.decide_play(True)
    bot.decide_play(False)
    assert duel._telemetry(bot)['hybrid_attempted'] == 1
    assert duel._telemetry(bot)['hybrid_expired'] == 1


@pytest.mark.parametrize('mutation', ['team', 'seed', 'population'])
def test_reader_refuses_wrong_pair_contract(monkeypatch, tmp_path, mutation):
    monkeypatch.setattr(duel, 'play_round', lambda *args: _Log(0))
    path = tmp_path / 'result.jsonl'
    duel.run_duel(_Bot, _Bot, path, deals=1, seed0=10, wall_seconds=30, header={})
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == 'team':
        rows[1]['candidate_team'] = 1
    elif mutation == 'seed':
        rows[1]['seed'] = rows[2]['seed'] = 11
    else:
        rows[0]['deals'] = 2
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(duel.DuelRefusal):
        duel.read_duel(path)


def test_blind_runner_reports_complete_capacity_without_outcomes(monkeypatch, tmp_path):
    class Bot(_Bot):
        def decide_play(self, reason):
            self.last_decision_record = {'schema': 'pv-search-fallback-v1', 'reason': reason}
            self.hybrid_last_fields = {'hybrid_attempted': True,
                                      'hybrid_fallback': 'budget'}
            return ['C2']
    def play(game, bots):
        for bot in bots:
            bot.decide_play('budget')
            bot.decide_play('search-error')
        return _Log(0)
    monkeypatch.setattr(duel, 'play_round', play)
    path = tmp_path / 'blind.jsonl'
    result = duel.run_duel(Bot, Bot, path, deals=1, seed0=9300,
                           wall_seconds=30, header={}, blind=True)
    assert result == duel.rehearsal_counters(path)
    assert result['completed_deals'] == 1 and result['mirrors_written'] == 2
    assert result['elapsed_seconds'] >= 0 and result['error'] is None
    for arm in ('candidate', 'baseline'):
        counters = result['counters'][arm]
        assert counters['play_decisions'] == 8
        assert counters['pv_fallback_budget'] == 4
        assert counters['pv_fallback_search_error'] == 4
        assert counters['hybrid_expired'] == 8
    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
    assert not any(any(word in key for word in ('utility', 'winner', 'level_change'))
                   for key in keys(result))
    rows = path.read_text().splitlines()
    path.write_text('\n'.join(rows[:-1]) + '\n')
    with pytest.raises(duel.DuelRefusal, match='terminal'):
        duel.rehearsal_counters(path)


def test_missing_pv_record_is_not_reused_from_previous_decision():
    class Bot:
        def decide_play(self, write):
            if write:
                self.last_decision_record = {'schema': 'pv-search-fallback-v1', 'reason': 'budget'}
            return ['C2']
    bot = Bot()
    duel._instrument(bot)
    bot.decide_play(True)
    bot.decide_play(False)
    counters = duel._telemetry(bot)
    assert counters['play_decisions'] == 2
    assert counters['pv_fallback_budget'] == 1
    assert counters['pv_record_missing'] == 1


@pytest.mark.parametrize("seconds", [None, 30.0])
def test_cli_records_deadline_and_only_attaches_candidate(monkeypatch, tmp_path, seconds):
    from scripts import cwv_serving_smoke as smoke, hybrid_duel_policy
    from shengji.ai import registry

    recipe = tmp_path / 'recipe.json'
    fly = tmp_path / 'fly.toml'
    fly.write_text('')
    recipe.write_text(json.dumps({'fly_toml': str(fly)}))
    monkeypatch.setattr(smoke, 'env_from_fly_toml', lambda *args: {})
    monkeypatch.setattr(smoke, 'build_production_bot', lambda env: ('served', object()))
    monkeypatch.setattr(registry, 'make_bot', lambda name, seed: {'seed': seed})
    def attach(bot, *, enabled, total_seconds):
        return {**bot, 'total_seconds': total_seconds, 'hybrid': enabled}
    monkeypatch.setattr(hybrid_duel_policy, 'attach_hybrid', attach)
    def run(candidate, baseline, output, **kwargs):
        assert baseline(12) == {'seed': 12}
        assert candidate(12) == {'seed': 12, 'total_seconds': seconds, 'hybrid': True}
        header = kwargs['header']['hybrid']
        assert header['total_seconds'] == seconds
        assert header['stop_fraction'] == (0.8 if seconds is None else 1.0)
        return {}
    monkeypatch.setattr(duel, 'run_duel', run)
    args = ['--recipe', str(recipe), '--output', str(tmp_path / 'out.jsonl')]
    if seconds is not None:
        args += ['--hybrid-total-seconds', str(seconds)]
    duel._main(args)


@pytest.mark.parametrize('total,fraction,valid', [
    (None, .8, True), (30., 1., True), (30., .8, False),
    (None, 1., False), (True, 1., False), (0., 1., False),
    (float('inf'), 1., False), ('30', 1., False),
])
def test_written_deadline_survives_readout_or_refuses_drift(
        monkeypatch, tmp_path, total, fraction, valid):
    monkeypatch.setattr(duel, 'play_round', lambda game, bots: _Log(0))
    path = tmp_path / 'duel.jsonl'
    hybrid = {'total_seconds': total, 'stop_fraction': fraction}
    if valid:
        result = duel.run_duel(_Bot, _Bot, path, deals=1, seed0=10,
                               wall_seconds=30, header={'hybrid': hybrid})
        assert result['header']['hybrid'] == hybrid
    else:
        with pytest.raises(duel.DuelRefusal, match='hybrid'):
            duel.run_duel(_Bot, _Bot, path, deals=1, seed0=10,
                           wall_seconds=30, header={'hybrid': hybrid})


def test_shards_pool_deals_not_worker_means(monkeypatch, tmp_path):
    results = iter([_Log(0), _Log(1)] + [_Log(1), _Log(0)] * 3)
    monkeypatch.setattr(duel, 'play_round', lambda *args: next(results))
    paths = [tmp_path / 'a.jsonl', tmp_path / 'b.jsonl']
    a = duel.run_duel(_Bot, _Bot, paths[0], deals=1, seed0=10, wall_seconds=30, header={})
    b = duel.run_duel(_Bot, _Bot, paths[1], deals=3, seed0=11, wall_seconds=30, header={})
    result = duel.read_duel_shards(paths)
    assert result['deals'] == result['requested_deals'] == 4
    assert result['paired_utility_mean'] == (
        a['paired_utility_mean'] + 3 * b['paired_utility_mean']) / 4
    assert result['paired_utility_mean'] != (
        a['paired_utility_mean'] + b['paired_utility_mean']) / 2
    assert duel.read_duel_shards(paths[::-1]) == result


@pytest.mark.parametrize('overlap', [True, False])
def test_shards_refuse_overlap_and_recipe_drift(monkeypatch, tmp_path, overlap):
    monkeypatch.setattr(duel, 'play_round', lambda *args: _Log(0))
    paths = [tmp_path / 'a.jsonl', tmp_path / 'b.jsonl']
    for i, path in enumerate(paths):
        duel.run_duel(_Bot, _Bot, path, deals=1, seed0=10 if overlap else 10 + i,
                      wall_seconds=30, header={'candidate': 'a' if overlap else str(i)})
    with pytest.raises(duel.DuelRefusal, match='overlapping|recipe mismatch'):
        duel.read_duel_shards(paths)


def test_shards_preserve_partial_pairs_but_do_not_score_them(monkeypatch, tmp_path):
    calls = [0]
    def play(*args):
        calls[0] += 1
        if calls[0] == 4:
            raise duel.DuelWallExpired('cap')
        return _Log(0)
    monkeypatch.setattr(duel, 'play_round', play)
    paths = [tmp_path / 'a.jsonl', tmp_path / 'b.jsonl']
    duel.run_duel(_Bot, _Bot, paths[0], deals=2, seed0=10, wall_seconds=30, header={})
    duel.run_duel(_Bot, _Bot, paths[1], deals=1, seed0=12, wall_seconds=30, header={})
    before = [p.read_bytes() for p in paths]
    result = duel.read_duel_shards(paths)
    assert result['status'] == 'PARTIAL'
    assert result['deals'] == 2 and result['requested_deals'] == 3
    assert result['unscored_mirrors'] == 1
    assert [p.read_bytes() for p in paths] == before


def test_shards_refuse_failed_worker(monkeypatch, tmp_path):
    def fail(*args):
        raise RuntimeError('worker failed')
    monkeypatch.setattr(duel, 'play_round', fail)
    path = tmp_path / 'failed.jsonl'
    duel.run_duel(_Bot, _Bot, path, deals=1, seed0=10, wall_seconds=30, header={})
    with pytest.raises(duel.DuelRefusal, match='failed duel shard'):
        duel.read_duel_shards([path])
    with pytest.raises(duel.DuelRefusal, match='no duel shards'):
        duel.read_duel_shards([])
