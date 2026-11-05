"""Historical collector replay plus tiny-package serving-factory integration."""
import json
import copy
import random
from pathlib import Path

import pytest

from scripts import lead_admission_diagnostic as collector
from shengji.ai.refusal import RefusalLedger
from shengji.rl.replay_log import rebuild_round
from shengji.train.lead_root_capture import restore_with_ledger, fingerprint
from shengji.train.lead_root_capture import observe_finish_pool, classify_finish_lead
from shengji.train import pv_search_policy as pv
from test_pv_search_serving import package  # noqa: F401


@pytest.mark.parametrize('mode', ['historical', 'served', 'fallback', 'served_round',
                                  'served_stop', 'served_error'])
def test_collector_saves_pre_analysis_decision_and_every_committed_play(tmp_path, monkeypatch, mode):
    events = json.loads((Path(__file__).parent / 'fixtures/xmtj_round1.json').read_text())
    plays = [e for e in events if e['e'] == 'play']
    rnd = rebuild_round(events)
    cursor = 0

    class Sampler:
        def __init__(self, seed=0):
            pass

    class Bot:
        def __init__(self):
            self.sampler = Sampler()
            self._refusals = RefusalLedger()

        def decide_play(self, root, seat):
            nonlocal cursor
            if mode == 'served_error' and cursor == 4:
                raise RuntimeError('injected later decision failure')
            self._refusals.observe(root)
            event = plays[cursor]
            assert event['seat'] == seat
            cursor += 1
            if mode == 'served_stop' and cursor == 4:
                (tmp_path / 'stop').touch()
            self._cap = ([event['attempted'], ['fixture-only']],)
            self._probe = True
            self.last_decision_record = dict(work_complete=mode != 'fallback', played=list(event['attempted']))
            return list(event['attempted'])

    class Game:
        game_over = False

        def __init__(self, rng):
            pass

        def finish_round(self):
            assert rnd.phase == 'round_end'

    def analyze(bot, root, seat, rec, times, samplers):
        # Mimic later diagnostic mutation; saved actual decision must survive.
        assert rec == bot.last_decision_record
        bot.last_decision_record['played'].clear()
        rec['played'].clear()
        return {'diagnostic_stub': True}

    monkeypatch.setattr(collector, 'Game', Game)
    monkeypatch.setattr(collector, 'make_pv_search_bot', lambda *a, **kw: Bot())
    monkeypatch.setattr(collector.env, 'prepare_round', lambda *a: rnd)
    monkeypatch.setattr(collector, 'analyze', analyze)
    if mode != 'historical':
        def forbidden(*a, **kw):
            pytest.fail('capture-only must not analyze or construct Probe')
        monkeypatch.setattr(collector, 'analyze', forbidden)
        monkeypatch.setattr(collector, 'make_pv_search_bot', forbidden)
        monkeypatch.setattr(collector, 'served_capture_bots',
                            lambda *a: ([Bot() for _ in range(4)], {'mode': 'test-served'}))
    out = tmp_path / 'rows.jsonl'
    args = ['unused', 'unused', '1', '16', '9999999999', str(out), str(tmp_path/'lock'), str(tmp_path/'stop')]
    if mode != 'historical':
        snapshot = tmp_path / 'env.json'
        snapshot.write_text('{}')
        args = ['--served-env', str(snapshot), *args]
    costs = tmp_path / 'costs.jsonl'
    if mode.startswith('served_'):
        args = ['--max-rounds', '1', '--cost-out', str(costs), *args]
        # A round cap, not the lead cap, must stop the next deal.
        args[args.index('16')] = '128'
    if mode == 'served_error':
        with pytest.raises(RuntimeError, match='injected later'):
            collector.main(args)
    else:
        collector.main(args)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    if mode.startswith('served_'):
        journal = [json.loads(line) for line in costs.read_text().splitlines()]
        assert journal[0]['kind'] == 'start'
        assert journal[-1]['kind'] == 'terminal'
        decisions = [r for r in journal if r['kind'] == 'decision']
        assert len(decisions) == cursor
        assert all(r['seconds'] >= 0 and r['played'] for r in decisions)
        assert any(not r['lead'] for r in decisions)
        assert all('scores' not in r and 'winner' not in r for r in journal)
        if mode in ('served_stop', 'served_error'):
            assert cursor == 4 and len(rows) == 1
            assert journal[-1]['rounds'] == 0
            assert journal[-1]['reason'] == ('stop_file' if mode == 'served_stop'
                                             else 'error:RuntimeError')
            assert not any(r['kind'] == 'round_complete' for r in journal)
            return  # partial roots and every completed decision survived
        assert journal[-1]['reason'] == 'max_rounds'
        assert journal[-1]['rounds'] == 1
    assert cursor == len(plays) == 64
    assert len(rows) == 16
    if mode != 'historical':
        from scripts.lead_finish_classify import main as classify
        classified = tmp_path / 'classified.json'
        classify([str(out), str(classified)])
        result = json.loads(classified.read_text())
        assert result['counts']['all_roots'] == 16
        assert result['counts']['eligible_roots'] == 5
        assert result['counts']['eligible:whole_hand_refused_true_deal:True'] == 5
        assert result['counts']['eligible:pool_present:None'] == 5
        assert result['counts']['eligible:admitted:None'] == 5
        assert all(r['ranking_or_horizon_error'] is None for r in result['rows'])
        with pytest.raises(FileExistsError):
            classify([str(out), str(classified)])
    for row in rows:
        root, ledger = restore_with_ledger(row['replay'])
        assert root.turn == row['seat'] and not root.trick.plays
        assert row['replay']['decision']['played']
        assert row['replay']['decision']['work_complete'] == (mode != 'fallback')
        if mode != 'historical':
            assert row['attempted'] == row['replay']['decision']['played']
            assert 'variants' not in row
        assert ledger.observe(root) == ledger.refusals
    assert any(e['attempted'] != e['accepted'] for row in rows for e in row['replay']['plays'])
    assert any(row['replay']['ledger']['refusals'] and row['replay']['root']['notice'] is None for row in rows)
    saved = out.read_bytes()
    with pytest.raises(FileExistsError):
        collector.main(args)
    assert out.read_bytes() == saved


@pytest.mark.parametrize('flags', [['--max-rounds', '0'], ['--max-rounds', '-1'],
                                   ['--cost-out', 'unused']])
def test_cost_diagnostic_rejects_invalid_mode_before_constructing_bots(flags, monkeypatch):
    monkeypatch.setattr(collector, 'make_pv_search_bot',
                        lambda *a, **kw: pytest.fail('must reject before construction'))
    with pytest.raises(SystemExit):
        collector.main([*flags, *(['unused'] * 8)])


@pytest.mark.parametrize('budget', ['0.000000001', '60'])
def test_capture_factory_uses_served_declare_bury_play_and_budgets(package, budget):
    """Real tiny package, registry factory, lifecycle and lead replay; no screen."""
    path, sha = package
    env = dict(SHENGJI_PV_CKPT=path, SHENGJI_PV_SHA256=sha,
               SHENGJI_PV_WORLDS='2', SHENGJI_PV_CANDIDATES='2', SHENGJI_PV_CAP='100',
               SHENGJI_PV_VALUE_DECLARE='1', SHENGJI_PV_DOOMED_THROW_RESELECT='1',
               SHENGJI_PV_BURY_ARM='hybrid', SHENGJI_PV_SERVING_BUDGET_SECONDS=budget,
               SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS=budget,
               SHENGJI_PV_VALUE_DECLARE_WORLDS='2', SHENGJI_PV_BURY_MAX_CANDIDATES='4',
               SHENGJI_PV_BURY_MODEL_WORLDS='2', SHENGJI_PV_BURY_SELECTION_WORLDS='2',
               SHENGJI_PV_BURY_ALTERNATIVES='1')
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    env['SHENGJI_BOT'], = entries
    bots, identity = collector.served_capture_bots(path, sha, 7, env)
    direct = [entries[env['SHENGJI_BOT']](seed=70 + s) for s in range(4)]
    assert all(type(bot) is pv.PVSearchBuryBot for bot in bots)
    assert identity['recipe']['value_declare'] and identity['recipe']['doomed_throw_reselect']
    assert identity['recipe']['serving_budget_seconds'] == float(budget)
    roots = [collector.env.prepare_round(collector.Game(random.Random(17)), group)
             for group in (bots, direct)]
    assert fingerprint(roots[0]) == fingerprint(roots[1])
    for group in (bots, direct):
        bury = group[roots[0].banker].last_bury_record
        if float(budget) < 1:
            assert bury['reason'] == 'budget'
        else:
            assert bury['schema'] == 'cwv-bury-policy-v1'
        assert any(bot.last_declare_record is not None for bot in group)
    root = roots[0]
    cards = bots[root.turn].decide_play(root, root.turn)
    assert cards == direct[root.turn].decide_play(roots[1], root.turn)
    record = bots[root.turn].last_decision_record
    assert record['work_complete'] == (float(budget) > 1)
    packet = collector.LeadCapture(root).capture(root, ledger=bots[root.turn]._refusals, decision=record)
    restored, _ = restore_with_ledger(packet)
    restored.play(root.turn, cards)
    expected = copy.deepcopy(root)
    expected.play(root.turn, cards)
    assert fingerprint(restored) == fingerprint(expected)
    with pytest.raises(ValueError, match='SHA differs'):
        collector.served_capture_bots(path, '0' * 64, 7, env)
    with pytest.raises(ValueError, match='SHENGJI_BOT differs'):
        collector.served_capture_bots(path, sha, 7, {**env, 'SHENGJI_BOT': 'wrong'})


@pytest.mark.parametrize('budget', [1e-9, 60.0])
def test_finish_pool_observation_preserves_real_decision_and_rng(package, budget):
    from test_lead_root_capture import packets
    from shengji.train.lead_root_capture import finish_eligible
    path, sha = package
    packet = next(p for p in packets() if finish_eligible(restore_with_ledger(p)[0], p['root']['turn']))
    roots = [restore_with_ledger(packet)[0] for _ in range(2)]
    bots = [pv.make_pv_search_bot(path, sha256=sha, seed=17, worlds=2, candidates=2,
                                 serving_budget_seconds=budget) for _ in range(2)]
    for bot in bots:
        _, bot._refusals = restore_with_ledger(packet)
    root, direct_root = roots
    bot, direct = bots
    assert '_legal' not in vars(bot)
    with observe_finish_pool(bot, root, root.turn) as evidence:
        action = bot.decide_play(root, root.turn)
    assert '_legal' not in vars(bot)
    assert action == direct.decide_play(direct_root, direct_root.turn)
    assert bot.sampler.rng.getstate() == direct.sampler.rng.getstate()
    def stable(record):
        return {k: v for k, v in record.items() if k not in ('seconds', 'elapsed_seconds')}
    assert stable(bot.last_decision_record) == stable(direct.last_decision_record)
    assert evidence['eligible'] is True
    # This recipe returns its legal pool before its first budget check; a
    # fallback still has observed pool evidence, but no completed admission.
    assert type(evidence['present']) is bool
    packet['decision'] = bot.last_decision_record
    row = dict(replay=packet, seat=root.turn, attempted=action, finish_pool=evidence)
    result = classify_finish_lead(row)
    assert result['pool_present'] == evidence['present']
    assert result['whole_hand_refused_true_deal'] is True
    assert result['ranking_or_horizon_error'] is None
    if budget < 1:
        assert result['admitted'] is None


def test_finish_pool_restores_hook_on_error_and_preserves_unknown():
    from types import SimpleNamespace
    from test_lead_root_capture import packets
    from shengji.train.lead_root_capture import finish_eligible
    root = next(r for p in packets() if finish_eligible(r := restore_with_ledger(p)[0], r.turn))
    def failing(*a):
        raise RuntimeError('enumeration expired')
    bot = SimpleNamespace(_legal=failing)
    with pytest.raises(RuntimeError, match='expired'):
        with observe_finish_pool(bot, root, root.turn) as evidence:
            bot._legal(root, root.turn, [])
    assert evidence['present'] is None and bot._legal is failing


def test_finish_classification_distinguishes_absence_from_unknown():
    from test_lead_root_capture import packets
    from shengji.train.lead_root_capture import finish_eligible
    from scripts.lead_finish_classify import summarize
    packet = next(p for p in packets() if finish_eligible(restore_with_ledger(p)[0], p['root']['turn']))
    root = restore_with_ledger(packet)[0]
    row = dict(replay=packet, seat=root.turn, game='fixture', round=0, trick=1)
    assert classify_finish_lead(row)['pool_present'] is None
    row['finish_pool'] = dict(eligible=True, present=False)
    packet['decision'].update(schema='pv-search-decision-v1', work_complete=True)
    packet['decision']['admitted'] = [packet['decision']['played']]
    result = classify_finish_lead(row)
    assert result['pool_present'] is False and result['admitted'] is False
    packet['decision']['admitted'].append(list(root.hands[root.turn]))
    with pytest.raises(ValueError, match='absent from captured pool'):
        classify_finish_lead(row)
    row['finish_pool']['present'] = True
    assert classify_finish_lead(row)['admitted'] is True
    with pytest.raises(ValueError, match='duplicate'):
        summarize([row, row])


def test_non_refused_finish_is_not_declared_a_ranking_error(monkeypatch):
    """Surgical engine state: a paired high trump is not a multi-component throw.

    Replay authenticity is covered above; this unit isolates the positive branch
    of classification, not a naturally observed or stronger-play claim.
    """
    from shengji.train import lead_root_capture as capture_module
    from test_lead_root_capture import packets
    root, ledger = restore_with_ledger(packets()[-1])
    root.hands[root.turn] = ['BJ', 'BJ']
    monkeypatch.setattr(capture_module, 'restore_with_ledger', lambda packet: (root, ledger))
    rec = dict(schema='pv-search-decision-v1', work_complete=True,
               admitted=[['BJ'], ['BJ', 'BJ']], played=['BJ'])
    row = dict(seat=root.turn, replay={'decision': rec},
               finish_pool=dict(eligible=True, present=True))
    result = classify_finish_lead(row)
    assert result['eligible'] and result['admitted']
    assert result['whole_hand_refused_true_deal'] is False
    assert result['whole_hand_played'] is False
    assert result['ranking_or_horizon_error'] is None


def test_common_world_lead_comparison_uses_real_scorer_without_mutating_bot():
    import copy
    import json
    from shengji.train.lead_counterfactual import compare_lead_actions
    from test_pv_leaf_greedy_finish import leaf_bot
    from test_pv_small_joker_lead import _fresh_round
    from test_pv_doomed_throw_reselect import HashNoiseEvaluator

    rnd = _fresh_round(707014)
    bot = leaf_bot(HashNoiseEvaluator(), worlds=2)
    control = copy.deepcopy(bot)
    alternatives = [[c] for c in sorted(set(rnd.hands[rnd.turn]))[:2]]
    result = compare_lead_actions(bot, rnd, rnd.turn, alternatives, gate=lambda: None)
    assert result['worlds'] == 2
    assert len(result['values']) == 2
    assert result['actions'][0]['delta_vs_played'] == 0
    assert result['actions'][0]['paired_se'] == 0
    assert all(r['policy_rank'] > 0 for r in result['actions'])
    json.dumps(result, allow_nan=False)
    assert bot.last_decision_record == control.last_decision_record
    assert bot.decide_play(copy.deepcopy(rnd), rnd.turn) == control.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert result['played'] == bot.last_decision_record['played']


def test_common_world_lead_comparison_refuses_expiry_and_invalid_alternatives():
    from shengji.train.lead_counterfactual import compare_lead_actions
    from test_pv_leaf_greedy_finish import leaf_bot
    from test_pv_small_joker_lead import _fresh_round
    import pytest

    rnd = _fresh_round(707014)
    bot = leaf_bot(worlds=2)
    with pytest.raises(ValueError, match='duplicate'):
        compare_lead_actions(bot, rnd, rnd.turn, [['S3'], ['S3']], gate=lambda: None)
    bot.leaf_greedy_top = 1
    with pytest.raises(ValueError, match='top-m'):
        compare_lead_actions(bot, rnd, rnd.turn, [['S3']], gate=lambda: None)
    bot.leaf_greedy_top = 0
    def expired():
        raise TimeoutError('diagnostic deadline')
    with pytest.raises(TimeoutError):
        compare_lead_actions(bot, rnd, rnd.turn, [[rnd.hands[rnd.turn][0]]], gate=expired)


@pytest.mark.parametrize('fault', ['matrix', 'late_expiry', 'fallback'])
def test_common_world_lead_comparison_never_returns_partial_evidence(monkeypatch, fault):
    import numpy as np
    from shengji.train.lead_counterfactual import compare_lead_actions
    from test_pv_leaf_greedy_finish import leaf_bot
    from test_pv_small_joker_lead import _fresh_round

    rnd = _fresh_round(707014)
    bot = leaf_bot(worlds=2)
    original = pv.PVSearchBot._lead_confirm_matrix
    finished = False
    def score(self, *args, **kwargs):
        nonlocal finished
        matrix = original(self, *args, **kwargs)
        finished = True
        if fault == 'matrix':
            matrix[0, 0] = np.nan
        return matrix
    monkeypatch.setattr(pv.PVSearchBot, '_lead_confirm_matrix', score)
    def gate():
        if finished and fault == 'late_expiry':
            raise TimeoutError('completed after deadline')
    if fault == 'fallback':
        def fallback(self, rnd, seat):
            self.last_decision_record = {'work_complete': False}
            return [rnd.hands[seat][0]]
        monkeypatch.setattr(pv.PVSearchBot, 'decide_play', fallback)
    with pytest.raises(TimeoutError if fault == 'late_expiry' else ValueError):
        compare_lead_actions(bot, rnd, rnd.turn, [[rnd.hands[rnd.turn][0]]], gate=gate)


def test_common_world_lead_deadline_is_checked_inside_initial_search(monkeypatch):
    from shengji.train.lead_counterfactual import compare_lead_actions
    from test_pv_leaf_greedy_finish import leaf_bot
    from test_pv_small_joker_lead import _fresh_round

    rnd = _fresh_round(707014)
    calls = 0
    def gate():
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise TimeoutError('inside search')
    def forbidden(*args, **kwargs):
        pytest.fail('pricing must not start after an expired decision')
    monkeypatch.setattr(pv.PVSearchBot, '_lead_confirm_matrix', forbidden)
    with pytest.raises(TimeoutError):
        compare_lead_actions(leaf_bot(worlds=2), rnd, rnd.turn,
                             [[rnd.hands[rnd.turn][0]]], gate=gate)
    assert calls >= 3


def test_common_world_comparison_separates_selected_throw_from_played_component():
    from shengji.train.lead_counterfactual import compare_lead_actions
    from test_pv_doomed_throw_swap import (oxps, served, throw_first_scores,
                                          RELEASE38_RULES, THROW, FORCED, SEAT)
    bot = served(doomed_throw_swap=True, **RELEASE38_RULES)
    bot.scores = throw_first_scores
    result = compare_lead_actions(bot, oxps(), SEAT, [THROW], gate=lambda: None)
    assert result['played'] == FORCED
    assert sorted(result['record_selected']) == sorted(THROW)
    assert result['actions'][0]['action'] == FORCED
    assert result['actions'][0]['delta_vs_played'] == 0
    assert result['decision']['doomed_throw_swap_applied'] is True


def _saved_diagnostic_fixture():
    import copy
    import random
    from shengji.engine.round import Round
    rnd = Round('2', 0, random.Random(1707))
    while rnd.phase == 'deal':
        rnd.deal_next()
    rnd.finalize_declare()
    buried = list(rnd.hands[0][:8])
    rnd.bury(0, buried)
    action = [rnd.hands[0][0]]
    row = dict(seed=1707, mirror=0, trump_rank='2', planned_banker=0,
               declares=[], banker=0, trump=('NT' if rnd.trump_is_nt else rnd.trump_suit), buried=buried,
               dtrace=[['P', 0, 0, True, 25, action]], history=[[0, action]])
    mirror = copy.deepcopy(row)
    mirror['mirror'] = 1
    return dict(validated_rows=[row, mirror]), dict(seed=1707, play_index=0,
                                                   seat=0, alternatives=[action])


def test_saved_readout_to_common_world_scorer():
    import json
    from shengji.train.lead_saved_diagnostic import diagnose_saved_leads
    from test_pv_leaf_greedy_finish import leaf_bot
    saved, case = _saved_diagnostic_fixture()
    built = []
    def build(seed):
        bot = leaf_bot(worlds=2)
        built.append(bot)
        return bot
    result = diagnose_saved_leads(json.loads(json.dumps(saved)), [case], build,
                                  gate=lambda: None)
    assert result['cases'][0]['case'] == case
    assert result['cases'][0]['evidence']['worlds'] == 2
    assert result['cases'][0]['evidence']['decision']['work_complete'] is True
    assert built[0].last_decision_record is None
    json.dumps(result, allow_nan=False)


def test_saved_diagnostic_refuses_bad_mirror_before_build():
    import pytest
    from shengji.train.lead_saved_diagnostic import diagnose_saved_leads
    saved, case = _saved_diagnostic_fixture()
    def forbidden(seed):
        pytest.fail('bad input must refuse before model construction')
    with pytest.raises(ValueError, match='duplicate case'):
        diagnose_saved_leads(saved, [case, case], forbidden, gate=lambda: None)
    saved['validated_rows'].pop()
    with pytest.raises(ValueError, match='two mirrors'):
        diagnose_saved_leads(saved, [case], forbidden, gate=lambda: None)


def test_diagnostic_supervisor_publishes_only_success_and_never_overwrites(tmp_path):
    import sys
    from shengji.train.lead_diagnostic_run import supervise
    target = tmp_path / 'result.json'
    command = [sys.executable, '-c',
               'import json,sys; json.dump({"schema":"saved-lead-diagnostic-v1"},open(sys.argv[1],"w"))']
    supervise(command, target, 5, expected={})
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        supervise(command, target, 5, expected={})
    assert target.read_bytes() == original
    failed = tmp_path / 'failed.json'
    with pytest.raises(RuntimeError, match='exited 1'):
        supervise(command[:-1] + [command[-1] + '; sys.exit(1)'], failed, 5, expected={})
    assert not failed.exists()


def test_diagnostic_supervisor_hard_timeout_cannot_publish(tmp_path):
    import subprocess
    import sys
    from shengji.train.lead_diagnostic_run import supervise
    target = tmp_path / 'result.json'
    with pytest.raises(subprocess.TimeoutExpired):
        supervise([sys.executable, '-c', 'import time; time.sleep(30)'], target, .1, expected={})
    assert not target.exists()
    assert not list(tmp_path.iterdir())


def test_diagnostic_pinned_input_refuses_hash_drift_and_oversize(tmp_path):
    import hashlib
    from shengji.train.lead_diagnostic_run import pinned_json
    source = tmp_path / 'saved.json'
    source.write_bytes(b'{"validated_rows": []}')
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    assert pinned_json(source, sha, 100) == {'validated_rows': []}
    with pytest.raises(ValueError, match='hash mismatch'):
        pinned_json(source, '0' * 64, 100)
    with pytest.raises(ValueError, match='byte limit'):
        pinned_json(source, sha, 2)


def test_pinned_worker_consumes_saved_json_with_real_scorer(tmp_path, monkeypatch):
    import hashlib
    import json
    import os
    from shengji.ai import registry
    from shengji.train.lead_diagnostic_run import worker
    from test_pv_leaf_greedy_finish import leaf_bot
    saved, case = _saved_diagnostic_fixture()
    source = tmp_path / 'saved.json'
    source.write_text(json.dumps(saved))
    spec = dict(schema='saved-lead-run-v1', saved_path=str(source),
                saved_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                cases=[case], policy='pv-search-test', wall_seconds=5,
                env={'SHENGJI_BOT': 'pv-search-test'})
    packet = tmp_path / 'run.json'
    packet.write_text(json.dumps(spec))
    sha = hashlib.sha256(packet.read_bytes()).hexdigest()
    def build(name, seed):
        assert name == 'pv-search-test' and seed == case['seed']
        assert os.environ['SHENGJI_BOT'] == name
        assert 'SHENGJI_PV_UNKNOWN_OVERRIDE' not in os.environ
        return leaf_bot(worlds=2)
    monkeypatch.setattr(registry, 'make_bot', build)
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    os.environ['SHENGJI_PV_UNKNOWN_OVERRIDE'] = '1'
    result_path = tmp_path / 'result.json'
    worker(packet, sha, result_path)
    result = json.loads(result_path.read_text())
    assert result['run_spec_sha256'] == sha
    assert result['saved_sha256'] == spec['saved_sha256']
    assert result['cases'][0]['evidence']['worlds'] == 2
    assert result['cases'][0]['evidence']['decision']['work_complete']


@pytest.mark.parametrize('payload', ['{"schema":"wrong"}',
                                     '{"schema":"saved-lead-diagnostic-v1","value":NaN}'])
def test_diagnostic_supervisor_rejects_invalid_result(tmp_path, payload):
    import sys
    from shengji.train.lead_diagnostic_run import supervise
    target = tmp_path / 'result.json'
    with pytest.raises(ValueError):
        supervise([sys.executable, '-c',
                   'import sys; open(sys.argv[2],"w").write(sys.argv[1])', payload], target, 5, expected={})
    assert not target.exists()


@pytest.mark.parametrize('key', ['run_spec_sha256', 'saved_sha256', 'policy'])
def test_diagnostic_supervisor_refuses_wrong_run_identity(tmp_path, key):
    import json
    import sys
    from shengji.train.lead_diagnostic_run import supervise
    expected = dict(run_spec_sha256='a' * 64, saved_sha256='b' * 64, policy='pv-search-test')
    payload = dict(schema='saved-lead-diagnostic-v1', **expected)
    payload[key] = 'wrong'
    with pytest.raises(ValueError, match='identity mismatch'):
        supervise([sys.executable, '-c',
                   'import sys; open(sys.argv[2],"w").write(sys.argv[1])', json.dumps(payload)],
                  tmp_path / 'result.json', 5, expected=expected)
    assert not (tmp_path / 'result.json').exists()


def test_diagnostic_recipe_controls_subprocess_package_import(tmp_path, monkeypatch):
    import json
    import sys
    from shengji.train.lead_diagnostic_run import recipe_environment, supervise
    monkeypatch.setenv('SHENGJI_FAST', '1')
    monkeypatch.setenv('SHENGJI_PV_UNKNOWN_OVERRIDE', '1')
    spec = dict(schema='saved-lead-run-v1', policy='pv-search-test',
                env={'SHENGJI_BOT': 'pv-search-test', 'SHENGJI_FAST': '0'})
    target = tmp_path / 'result.json'
    code = ('import os,sys,json,shengji; '
            'assert "shengji.engine.fast" not in sys.modules; '
            'assert "SHENGJI_PV_UNKNOWN_OVERRIDE" not in os.environ; '
            'json.dump({"schema":"saved-lead-diagnostic-v1"},open(sys.argv[1],"w"))')
    supervise([sys.executable, '-c', code], target, 5,
              expected={}, env=recipe_environment(spec))
    assert json.loads(target.read_text())['schema'] == 'saved-lead-diagnostic-v1'


def test_diagnostic_file_cli_isolates_environment_before_package_import(tmp_path):
    import hashlib
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    from shengji.train import lead_diagnostic_run as runner
    package = tmp_path / 'shengji'
    package.mkdir()
    witness = tmp_path / 'imports.txt'
    actual_package = Path(runner.__file__).resolve().parents[1]
    (package / '__init__.py').write_text(
        'import os\nfrom pathlib import Path\n'
        f'Path({str(witness)!r}).write_text(os.environ.get("SHENGJI_FAST", "absent"))\n'
        'assert os.environ.get("SHENGJI_FAST") == "0"\n'
        f'__path__ = [{str(actual_package)!r}]\n')
    saved = tmp_path / 'saved.json'
    saved.write_text('{}')
    spec = dict(schema='saved-lead-run-v1', policy='pv-search-test', wall_seconds=5,
                env={'SHENGJI_BOT': 'pv-search-test', 'SHENGJI_FAST': '0'},
                saved_path=str(saved), saved_sha256='0' * 64)
    packet = tmp_path / 'run.json'
    packet.write_text(json.dumps(spec))
    sha = hashlib.sha256(packet.read_bytes()).hexdigest()
    output = tmp_path / 'result.json'
    proc = subprocess.run([sys.executable, runner.__file__, '--spec', str(packet),
                           '--sha256', sha, str(output)], capture_output=True, text=True,
                          env={**os.environ, 'PYTHONPATH': str(tmp_path), 'SHENGJI_FAST': '1'},
                          cwd=tmp_path, timeout=10)
    assert proc.returncode != 0 and 'input hash mismatch' in proc.stderr
    assert witness.read_text() == '0'
    assert not output.exists()


@pytest.mark.parametrize('signal_name', ['SIGTERM', 'SIGHUP', 'SIGINT'])
def test_diagnostic_cli_signal_reaps_worker_without_publishing(tmp_path, signal_name):
    import hashlib
    import json
    import os
    from pathlib import Path
    import signal
    import subprocess
    import sys
    import time
    from shengji.train import lead_diagnostic_run as runner

    package = tmp_path / 'shengji' / 'train'
    package.mkdir(parents=True)
    (package.parent / '__init__.py').write_text('')
    (package / '__init__.py').write_text('')
    marker = tmp_path / 'worker.pid'
    (package / 'lead_diagnostic_run.py').write_text(
        'import os,time\nfrom pathlib import Path\n'
        f'Path({str(marker)!r}).write_text(str(os.getpid()))\n'
        'time.sleep(30)\n')
    spec = dict(schema='saved-lead-run-v1', policy='pv-search-test', wall_seconds=20,
                env={'SHENGJI_BOT': 'pv-search-test'}, saved_sha256='0' * 64)
    packet = tmp_path / 'run.json'
    packet.write_text(json.dumps(spec))
    sha = hashlib.sha256(packet.read_bytes()).hexdigest()
    output = tmp_path / 'result.json'
    proc = subprocess.Popen([sys.executable, runner.__file__, '--spec', str(packet),
                             '--sha256', sha, str(output)], cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': str(tmp_path)})
    worker = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert marker.exists(), 'worker did not start'
        worker = int(marker.read_text())
        sig = getattr(signal, signal_name)
        proc.send_signal(sig)
        assert proc.wait(timeout=5) == 128 + sig
        with pytest.raises(ProcessLookupError):
            os.kill(worker, 0)
        assert not output.exists()
        assert not list(tmp_path.glob('.lead-diagnostic-*'))
    finally:
        if worker is not None:
            try:
                os.killpg(worker, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


@pytest.mark.parametrize('signal_name', ['SIGTERM', 'SIGHUP', 'SIGINT'])
def test_diagnostic_signal_during_spawn_reaps_worker(tmp_path, monkeypatch, signal_name):
    import os
    import signal
    import subprocess
    import sys
    from shengji.train import lead_diagnostic_run as runner

    original = subprocess.Popen
    children = []
    sig = getattr(signal, signal_name)
    handler = signal.getsignal(sig)

    def interrupted_spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        os.kill(os.getpid(), sig)
        return child

    monkeypatch.setattr(runner.subprocess, 'Popen', interrupted_spawn)
    output = tmp_path / 'result.json'
    try:
        with pytest.raises(SystemExit) as error:
            runner.supervise([sys.executable, '-c', 'import time; time.sleep(30)'],
                             output, 5, expected={})
        assert error.value.code == 128 + sig
        assert len(children) == 1
        assert children[0].returncode is not None
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
        assert signal.getsignal(sig) == handler
        assert not output.exists()
        assert not list(tmp_path.glob('.lead-diagnostic-*'))
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
