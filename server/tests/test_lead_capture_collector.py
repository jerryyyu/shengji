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
                                  'served_stop', 'served_error', 'horizon', 'horizon_timeout',
                                  'horizon_yield'])
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

        def _select(self, root, seat, admitted, means, worlds=None):
            return 0

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
            if mode.startswith('horizon'):
                self._select(root, seat, [list(event['attempted'])], [0.0],
                             worlds=[([list(h) for h in root.hands], list(root.buried))])
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
    if mode.startswith('horizon'):
        from shengji.train import paired_horizon
        def measured(bot, captured, record, *, gate):
            gate()
            assert captured['actions'] == [record['played']]
            assert len(captured['worlds']) == 1
            if mode == 'horizon_timeout':
                raise pv.PVSearchBudgetExceeded('test deadline')
            if mode == 'horizon_yield':
                raise collector.Yield('stop_file')
            return {'status': 'complete', 'consumer_witness': True}
        monkeypatch.setattr(paired_horizon, 'measure_captured_horizon', measured)
        args = ['--paired-horizon-seconds', '1', *args]
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
    assert len(plays) == 64
    assert cursor == (1 if mode == 'horizon_yield' else 61 if mode.startswith('horizon') else 64)
    assert len(rows) == (1 if mode == 'horizon_yield' else 16)
    if mode.startswith('horizon'):
        # Stop before committing the final captured action, never finish the
        # rest of its trick/round after max_positions or a global stop signal.
        assert rnd.phase == 'play' and not rnd.trick.plays
    assert all(('paired_horizon' in row) == mode.startswith('horizon') for row in rows)
    if mode.startswith('horizon'):
        assert all(row['collection']['mode'] == 'served-recipe-paired-horizon-dev' for row in rows)
        assert all(row['collection']['paired_horizon_seconds'] == 1 for row in rows)
        assert all('No counterfactual analysis or bot RNG restoration.' not in row['collection']['limits']
                   for row in rows)
    if mode == 'horizon':
        assert all(row['paired_horizon']['consumer_witness'] for row in rows)
    if mode == 'horizon_timeout':
        assert all(row['paired_horizon'] == {'status': 'abandoned', 'reason': 'PVSearchBudgetExceeded'}
                   for row in rows)
    if mode == 'horizon_yield':
        assert rows[0]['paired_horizon'] == {'status': 'abandoned', 'reason': 'Yield'}
    if mode not in ('historical', 'horizon_yield'):
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
    if mode != 'horizon_yield':
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
    from shengji.train.paired_horizon import capture_horizon_inputs, measure_captured_horizon
    with capture_horizon_inputs(bots[root.turn]) as horizon_inputs:
        cards = bots[root.turn].decide_play(root, root.turn)
    assert cards == direct[root.turn].decide_play(roots[1], root.turn)
    record = bots[root.turn].last_decision_record
    assert record['work_complete'] == (float(budget) > 1)
    rng = bots[root.turn].sampler.rng.getstate()
    saved_record = copy.deepcopy(record)
    counter_keys = ('calls', 'positions', 'model_rows', 'terminal_rows',
                    'forward_calls', 'wall_secs', 'cpu_secs')
    evaluator_before = {k: getattr(bots[root.turn].evaluator, k) for k in counter_keys}
    horizon = measure_captured_horizon(bots[root.turn], horizon_inputs, record, gate=lambda: None)
    assert horizon['status'] == ('complete' if float(budget) > 1 else 'skipped')
    assert bots[root.turn].sampler.rng.getstate() == rng
    assert bots[root.turn].last_decision_record == saved_record
    assert {k: getattr(bots[root.turn].evaluator, k) for k in counter_keys} == evaluator_before
    if horizon['status'] == 'complete':
        assert horizon['actions'] == record['admitted']
        assert horizon['worlds'] == 2
        serialized = json.loads(json.dumps(horizon))
        for name, depth in [('trick', 1), ('policy', 2)]:
            assert len(serialized['arms'][name]['values']) == 2
            assert all(r['completed_tricks'] == depth for r in serialized['arms'][name]['leaves'])
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
