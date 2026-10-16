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
