import copy

import numpy as np
import pytest

from shengji.train.cwv_stage_substitution_audit import fold_plan


def test_choosing_and_judging_use_opposite_world_rows():
    values = [[0, 10, 0], [0, -7, 9], [0, 10, 0], [0, -7, 9]]
    ballots = {'a': [0, 1], 'b': [0, 2]}
    first, second = fold_plan(values, ballots, 0, k=2)
    assert first['selection_rows'] == [0, 2] and first['evaluation_rows'] == [1, 3]
    assert first['reference_ballot'] == [0, 1] and first['reference_pick'] == 1
    assert first['evaluation_means'] == [0, -7, 9]
    assert first['evaluation_means'][first['reference_pick']] == -7
    assert second['reference_ballot'] == [0, 2] and second['reference_pick'] == 2
    assert second['evaluation_means'][second['reference_pick']] == 0
    # Changing evaluation outcomes cannot change this fold's choices. The
    # opposite fold legitimately changes because those rows become its fit.
    changed = copy.deepcopy(values)
    changed[1] = changed[3] = [0, 100, -100]
    other = fold_plan(changed, ballots, 0, k=2)[0]
    assert other['reference_ballot'] == first['reference_ballot']
    assert other['reference_pick'] == first['reference_pick']
    assert other['model_reference_picks'] == first['model_reference_picks']
    assert other['evaluation_means'] != first['evaluation_means']


def test_reference_nominations_and_direct_choices_are_real_interventions():
    first, _ = fold_plan([[0, 1, 3]] * 4, {'a': [0, 1], 'b': [0, 2]}, 0, k=2)
    assert first['reference_ballot'] == [0, 2]  # replaces a's retained option
    assert first['model_reference_picks'] == {'a': 1, 'b': 2}
    assert first['reference_pick'] == 2


def test_incumbent_and_tie_order_are_preserved():
    first, _ = fold_plan(np.zeros((4, 3)), {'a': [2, 1], 'b': [2, 0]}, 2, k=2)
    assert first['reference_ballot'] == [2, 0]
    assert first['reference_pick'] == 2
    assert first['model_reference_picks'] == {'a': 2, 'b': 2}


def test_single_action_and_inputs_unchanged():
    values = np.zeros((4, 1))
    ballot = {'a': [0]}
    before = copy.deepcopy(ballot)
    assert fold_plan(values, ballot, 0)[0]['reference_pick'] == 0
    assert ballot == before and not values.any()


@pytest.mark.parametrize('case', ['odd', 'nan', 'missing_union', 'duplicate', 'incumbent', 'cardinality'])
def test_misaligned_populations_refuse(case):
    values = np.zeros((4, 3))
    ballot = {'a': [0, 1], 'b': [0, 2]}
    if case == 'odd':
        values = values[:3]
    elif case == 'nan':
        values[1, 1] = np.nan
    elif case == 'missing_union':
        del ballot['b']
    elif case == 'duplicate':
        ballot['a'] = [0, 0]
    elif case == 'incumbent':
        ballot['a'] = [1, 0]
    else:
        ballot['a'] = [0]
    with pytest.raises(ValueError):
        fold_plan(values, ballot, 0, k=2)
