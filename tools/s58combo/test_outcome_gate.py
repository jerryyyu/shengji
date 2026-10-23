"""Producer outcome semantics and refusal-before-estimation tests."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outcome_gate as gate
from test_admission import packet


def row(points, mirror=0, banker=0):
    winner, change = gate.validity.engine_level_outcome(points, banker)
    won = int(winner == mirror)
    utility = max(1, change) * (1 if won else -1)
    return dict(banker=banker, attacker_points=points, winner_team=winner,
                level_change=change, mirror=mirror, arm_team=mirror,
                arm_won=won, arm_utility=utility, baseline_utility=-utility)


@pytest.mark.parametrize('points', [0, 35, 40, 75, 80, 115, 120, 155, 160, 200])
@pytest.mark.parametrize('mirror', [0, 1])
def test_engine_thresholds_and_mirrors(points, mirror):
    assert gate.check_outcomes({'x': [row(points, mirror)]})['verdict'] == 'VALID'


@pytest.mark.parametrize('mirror', [0, 1])
def test_actual_producer_zero_level_win_has_unit_utility(monkeypatch, mirror):
    from shengji.oracle import screen

    log = SimpleNamespace(winner_team=1, level_change=0, banker=0,
                          trump_rank='2', attacker_points=80, history=[])
    monkeypatch.setattr(screen, 'play_round', lambda *args, **kwargs: log)
    record, _ = screen.play_screen_round(
        {'arm': 'policy'}, 0, 17, mirror,
        bot_factory=lambda *args: SimpleNamespace(), counter_fn=lambda bots: {},
        game_factory=lambda rng: None)
    assert record['arm_utility'] == (-1 if mirror == 0 else 1)
    assert gate.check_outcomes({'real_producer': [record]})['verdict'] == 'VALID'
    record['arm_utility'] = 0
    assert gate.check_outcomes({'real_producer': [record]})['verdict'] == 'SCREEN_INVALID'


@pytest.mark.parametrize('field,value', [('arm_utility', 0), ('baseline_utility', 7),
    ('arm_team', 1), ('arm_won', True), ('level_change', 1), ('attacker_points', -5)])
def test_bad_outcomes_refuse(field, value):
    bad = row(80)
    bad[field] = value
    assert gate.check_outcomes({'x': [bad]})['verdict'] == 'SCREEN_INVALID'


def test_admission_to_outcome_gate_never_estimates_invalid_rows(tmp_path, monkeypatch):
    args = packet(tmp_path)
    for windows in args[3].values():
        for shard in windows:
            for record in shard['records']:
                record.update(row(80, record['mirror'], record['banker']))
    output = args[0]['windows'][-1]['output']
    args[3][output][-1]['records'][-1]['arm_utility'] = 999
    def forbidden(*args):
        pytest.fail('estimator ran on invalid outcomes')
    monkeypatch.setattr(gate, 'paired_result', forbidden)
    result = gate.outcome_checked_result(*args)
    assert result['status'] == 'OUTCOME_INVALID' and 'estimate' not in result
