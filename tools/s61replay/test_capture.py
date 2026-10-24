from copy import deepcopy
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server/tests'))
from capture import capture_lead, compare_captured
from test_continuation import fixture, factory, endpoint
from test_pv_leaf_greedy_finish import leaf_bot, R46_RULES
from test_pv_doomed_throw_reselect import HashNoiseEvaluator


def make_bot():
    return leaf_bot(HashNoiseEvaluator(), worlds=2, seed=41, on=False, **R46_RULES)


def test_served_capture_to_completed_paired_continuation():
    root, _ = fixture()
    bot, plain = make_bot(), make_bot()
    before = deepcopy(root.hands)
    capture = capture_lead(bot, root)
    assert capture['played'] == plain.decide_play(deepcopy(root), root.turn)
    assert bot.sampler.rng.getstate() == plain.sampler.rng.getstate()
    assert root.hands == before and '_worlds' not in vars(bot)
    for key in ('admitted', 'admitted_indices', 'value_means', 'selected_index'):
        assert capture['served_record'][key] == plain.last_decision_record[key]
    assert capture['served_ballot'] == capture['served_record']['admitted']
    alternative = next([c] for c in root.hands[root.turn] if [c] != capture['played'])
    result = compare_captured(capture, [alternative], tricks=2, reply_factory=factory,
        evaluate=endpoint, seed=51, reply_identity='heuristic-test', evaluator_identity='points-test')
    assert len(result['actions']) == 2
    assert all(w['completed_tricks'] == 2 for a in result['actions'] for w in a['worlds'])
    assert result['weights'] == [.5, .5]


def test_hook_restored_after_error():
    root, _ = fixture()
    bot = make_bot()
    def broken(*args):
        raise RuntimeError('stop')
    bot.decide_play = broken
    with pytest.raises(RuntimeError): capture_lead(bot, root)
    assert '_worlds' not in vars(bot)


def test_incomplete_decision_refused():
    root, _ = fixture()
    bot = make_bot()
    bot.decide_play = lambda *args: []
    with pytest.raises(ValueError): capture_lead(bot, root)


def test_existing_hook_and_exact_sample_population_preserved():
    root, _ = fixture()
    bot = make_bot()
    original = bot._worlds
    seen = []
    def sampling(*args, **kwargs):
        value = original(*args, **kwargs)
        seen.append(deepcopy(value[0]))
        return value
    bot._worlds = sampling
    capture = capture_lead(bot, root)
    assert bot._worlds is sampling and len(seen) == 1
    assert [(world.hands, world.buried) for world in capture['worlds']] == seen[0]
    assert all(world._determinized_world for world in capture['worlds'])


@pytest.mark.parametrize('flag', ['adaptive_worlds', 'adaptive_worlds_leads', 'oracle_worlds', 'oracle_mix_k', 'oracle_pin_q'])
def test_unsupported_world_populations_refused(flag):
    root, _ = fixture()
    bot = make_bot()
    setattr(bot, flag, True)
    with pytest.raises(ValueError, match='world population'):
        capture_lead(bot, root)
