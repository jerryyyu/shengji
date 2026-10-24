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


def test_release46_package_capture(monkeypatch):
    import os
    import tomllib
    from shengji.train import pv_search_policy as pv
    play = os.environ.get('REPLAY_PLAY_PACKAGE')
    belief = os.environ.get('REPLAY_BELIEF_PACKAGE')
    if not play and not belief:
        pytest.skip('explicit release46 package paths required')
    assert play and belief
    env = tomllib.loads((Path(__file__).resolve().parents[2] / 'fly.toml').read_text())['env']
    env = {key: value for key, value in env.items() if key.startswith('SHENGJI_PV_')}
    env.update(SHENGJI_PV_CKPT=play, SHENGJI_PV_BELIEF_CKPT=belief)
    for key in tuple(os.environ):
        if key.startswith('SHENGJI_'):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    (name, factory_), = entries.items()
    assert name == ('pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-'
                    'xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0')
    root, _ = fixture()
    bot, plain = factory_(seed=41), factory_(seed=41)
    assert bot.belief_worlds and bot.worlds == 64 and bot.serving_budget_seconds == 3
    captured = capture_lead(bot, root)
    assert captured['played'] == plain.decide_play(deepcopy(root), root.turn)
    assert len(captured['worlds']) == 64
    assert captured['weights'] == [1 / 64] * 64
    assert plain.last_decision_record['schema'] == 'pv-search-decision-v1'
    for key in ('admitted', 'value_means', 'selected_index'):
        assert captured['served_record'][key] == plain.last_decision_record[key]
    assert bot.sampler.rng.getstate() == plain.sampler.rng.getstate()

    from served import reply_factory, endpoint_evaluator
    from continuation import compare_continuations
    alternative = next([card] for card in root.hands[root.turn] if [card] != captured['played'])
    evaluator_bot = factory_(seed=42)
    evaluate = endpoint_evaluator(evaluator_bot)
    seen = []
    def checked_endpoint(state, root_seat):
        assert root_seat == root.turn == 2
        assert len(state.history) == 2
        value = evaluate(state, root_seat)
        assert value == float(evaluator_bot.evaluator.score([state], root_seat)[0])
        seen.append(root_seat)
        return value
    result = compare_continuations(captured['worlds'][:1], [1.],
        [captured['played'], alternative], tricks=2,
        reply_factory=reply_factory(factory_), evaluate=checked_endpoint, seed=51,
        reply_identity=name, evaluator_identity=name,
        served_ballot=captured['served_ballot'])
    assert seen == [2, 2]
    assert all(row['worlds'][0]['completed_tricks'] == 2 for row in result['actions'])

    from served import replay_served_prefix
    from test_replay import recording
    from shengji.ai.heuristic import HeuristicBot
    original = factory_(seed=19 * 16 + 2 + 7)
    heuristic = HeuristicBot()
    class PrefixBots:
        def decide_declare(self, state, seat, final=False):
            bot = original if seat == 2 else heuristic
            return bot.decide_declare(state, seat, final=final)
        def decide_bury(self, state, seat):
            return (original if seat == 2 else heuristic).decide_bury(state, seat)
        def decide_play(self, state, seat):
            # The fixture records subsequent plays without advancing original.
            return heuristic.decide_play(state, seat)
    row, _ = recording('fixed_banker', PrefixBots())
    restored, restored_root, witness = replay_served_prefix(row, factory_, seat=2)
    assert restored.sampler.rng.getstate() == original.sampler.rng.getstate()
    fresh = factory_(seed=19 * 16 + 2 + 7)
    assert restored.sampler.rng.getstate() == fresh.sampler.rng.getstate()
    assert restored.decide_play(deepcopy(restored_root), 2) == original.decide_play(deepcopy(restored_root), 2)
    assert restored.last_decision_record['admitted'] == original.last_decision_record['admitted']
    assert restored.last_decision_record['value_means'] == original.last_decision_record['value_means']


def test_fallback_root_never_reaches_continuation():
    root, _ = fixture()
    bot = make_bot()
    decide = bot.decide_play
    def fallback_with_complete_record(*args):
        cards = decide(*args)
        bot.last_decision_record['fallback_reason'] = 'PVSearchBudgetExceeded'
        return cards
    bot.decide_play = fallback_with_complete_record
    with pytest.raises(ValueError, match='complete served ballot'):
        capture_lead(bot, root)
    assert '_worlds' not in vars(bot)
