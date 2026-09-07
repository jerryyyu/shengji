import importlib.util
from pathlib import Path

import pytest

from shengji.ai.registry import REGISTRY
from shengji.luna.game import _state_snapshot
from shengji.train.cwv_selector_objective_audit import replay_selector
from tests.test_world_shortlist import play_state


@pytest.fixture
def runner():
    path = Path(__file__).parents[1] / 'scripts/cwv_stage_substitution_audit.py'
    spec = importlib.util.spec_from_file_location('stage_runner_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(runner):
    rnd = play_state()
    assert not rnd.is_attacker(rnd.turn)
    actions = [list(a) for a in sorted({tuple(sorted(a)) for a in REGISTRY['mc-s0-report-lcb'](seed=7)._candidates(rnd, rnd.turn)})[:3]]
    assert len(actions) == 3
    selection, report = [[100, 90, 110]] * 30, [[100, 90, 110]] * 300
    entry = {'id': 'a' * 64, 'deal_key': 'deal1', 'snapshot': _state_snapshot(rnd),
             'provenance': {'split': 'fit'}}
    saved = {'state_id': entry['id'], 'incumbent': actions[0], 'actions': actions, 'arms': {}}
    picks = {}
    for name, ballot in {'a/finished': [0, 1], 'b/finished': [0, 2]}.items():
        result = replay_selector(rnd, rnd.turn, [actions[i] for i in ballot],
                                 [[r[i] for i in ballot] for r in selection],
                                 [[r[i] for i in ballot] for r in report], seed=13)
        saved['arms'][name] = {'shortlist_indices': ballot, 'final_mc_record': result['record'], 'played': result['played']}
        picks[name] = actions.index(result['played'])
    reference = {'state_id': entry['id'], 'actions': actions,
                 'binding': {'entry_hash': runner.digest(entry)}, 'returns': {'levels': [[0, 1, 3]] * 1024}}
    matrices = {'state_id': entry['id'], 'source_state_sha256': runner.digest(saved),
                'reference_sha256': runner.digest(reference), 'actions': actions,
                'folds': {'selection': {'points': selection}, 'report': {'points': report}},
                'arms': {name + '/points': {'final_lift_vs_incumbent': [0, 1, 3][pick]} for name, pick in picks.items()}}
    return entry, saved, reference, matrices


def test_actual_consumer_stage_wiring_reaches_nonzero_output_cells(runner):
    inputs = fixture(runner)
    row = runner.run_case(*inputs, seed=13, k=2)
    assert row['all_controls_reproduced'] and row['fresh_rollouts'] == 0
    assert row['values']['a/finished'] == {'model_mc': 1., 'reference_mc': 0.,
                                          'model_reference': 1., 'reference_reference': 3.}
    assert row['values']['b/finished'] == {'model_mc': 0., 'reference_mc': 0.,
                                          'model_reference': 3., 'reference_reference': 3.}
    for fold in row['folds']:
        assert fold['reference_mc_record']['reason'] != 'report_lcb_override'
        assert set(fold['plan']['selection_rows']).isdisjoint(fold['plan']['evaluation_rows'])
    result = runner.summarize([row])
    assert result['contrasts']['a/finished']['nomination_only']['mean'] == -1
    assert result['contrasts']['b/finished']['selector_only']['mean'] == 3


def test_validation_rejected_before_reconstruction(runner, monkeypatch):
    monkeypatch.setattr(runner, '_round_from_snapshot', lambda *_: pytest.fail('must not rebuild validation'))
    with pytest.raises(ValueError, match='^stage diagnostic accepts only FIT positions$'):
        runner.run_case({'provenance': {'split': 'validation'}}, {}, {}, {}, seed=13)


def test_control_record_mismatch_refuses_counterfactuals(runner):
    entry, saved, reference, matrices = fixture(runner)
    saved['arms']['a/finished']['final_mc_record']['report_fold']['statistic'] -= 1
    matrices['source_state_sha256'] = runner.digest(saved)
    with pytest.raises(ValueError, match='^control report mismatch: statistic$'):
        runner.run_case(entry, saved, reference, matrices, seed=13, k=2)


def test_matrix_column_reordering_refuses(runner):
    entry, saved, reference, matrices = fixture(runner)
    matrices['actions'] = matrices['actions'][::-1]
    with pytest.raises(ValueError, match='^matrix action order or population mismatch$'):
        runner.run_case(entry, saved, reference, matrices, seed=13, k=2)


def test_deals_not_folds_or_roots_are_independent_units(runner):
    def row(deal, delta):
        return {'deal_key': deal, 'all_controls_reproduced': True, 'fresh_rollouts': 0, 'wall_seconds': 0,
                'values': {'a': {'model_mc': 0, 'reference_mc': delta, 'model_reference': delta, 'reference_reference': delta}}}
    rows = [row('a', 1), row('a', 1), row('b', -1)]
    result = runner.summarize(rows)
    assert result['states'] == 3 and result['deals'] == 2
    assert result['contrasts']['a']['both']['mean'] == 0
    rows[0]['all_controls_reproduced'] = False
    with pytest.raises(ValueError, match='^incomplete actual-consumer controls$'):
        runner.summarize(rows)
