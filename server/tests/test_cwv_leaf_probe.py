import copy
import numpy as np
import pytest

from test_cwv_bounded_puct import root
from test_cwv_truncated_value import Evaluator
from shengji.ai.registry import make_bot
from shengji.train.cwv_leaf_probe import compare_values, probe_root
from shengji.train.cwv_leaf_probe import LeafRecorder
from shengji.train.cwv_bounded_puct import search_worlds, PuctConfig


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


def test_actual_tree_recorder_is_bounded_and_does_not_change_search():
    rnd = root()
    prior = lambda r, s, a: np.zeros(len(a))
    args = dict(prior_logits=prior, config=PuctConfig(sweeps=4, depth=4))
    control = search_worlds([rnd, copy.deepcopy(rnd)], rnd.turn, evaluator=Evaluator(), **args)
    recorder = LeafRecorder(Evaluator(), limit=3)
    captured = search_worlds([rnd, copy.deepcopy(rnd)], rnd.turn, evaluator=recorder, **args)
    assert captured == control
    assert len(recorder.rows) == 3
    report = recorder.compare_full()
    assert report['captured'] == 3 and len(report['predictions']) == 3
    assert np.isfinite(report['rmse'])
