import copy
import numpy as np
import pytest

from test_cwv_bounded_puct import root
from test_cwv_truncated_value import Evaluator
from shengji.ai.registry import make_bot
from shengji.train.cwv_leaf_probe import compare_values, probe_root


def test_world_average_precedes_action_choice():
    out = compare_values([[10, 0], [-12, 2]], [[0, 2], [0, 2]])
    assert out['selected_index'] == 1 and out['comparator_regret'] == 0
    assert out['strict_pairs'] == 1 and out['pairwise_accuracy'] == 1


def test_no_preference_is_not_perfect_accuracy():
    assert compare_values([[1, 2]], [[0, 0]])['pairwise_accuracy'] is None
    with pytest.raises(ValueError):
        compare_values([[float('nan')]], [[0]])


def test_real_root_probe_preserves_inputs_and_work():
    rnd = root()
    original = copy.deepcopy(rnd)
    bot = make_bot('mc-s0-report-lcb', seed=91)
    actions = bot._candidates(rnd, rnd.turn)[:3]
    result = probe_root(rnd, rnd.turn, actions, sampler=bot, evaluator=Evaluator(), worlds=2)
    assert set(result['values']) == {'full', '0', '1', '2'}
    assert result['work']['full']['model_rows'] == 0
    assert result['work']['full']['terminal_rows'] == 2*len(actions)
    for values in result['values'].values():
        assert np.asarray(values).shape == (2, len(actions))
    assert rnd.hands == original.hands and rnd.history == original.history
