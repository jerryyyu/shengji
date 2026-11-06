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
                                  'served_stop', 'served_error', 'calibration'])
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
            self.worlds = 1
            self._refusals = RefusalLedger()

        def _worlds(self, root, seat):
            return [(copy.deepcopy(root.hands), list(root.buried))], 1

        def decide_play(self, root, seat):
            nonlocal cursor
            if mode == 'served_error' and cursor == 4:
                raise RuntimeError('injected later decision failure')
            self._refusals.observe(root)
            if mode == "calibration" and not root.trick.plays:
                self._worlds(root, seat)
                self._worlds(root, seat)
            event = plays[cursor]
            assert event['seat'] == seat
            cursor += 1
            if mode == 'served_stop' and cursor == 4:
                (tmp_path / 'stop').touch()
            self._cap = ([event['attempted'], ['fixture-only']],)
            self._probe = True
            self.last_decision_record = dict(schema='pv-search-decision-v1', work_complete=mode != 'fallback', played=list(event['attempted']))
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
    if mode == 'calibration':
        args = ['--throw-calibration', *args]
    costs = tmp_path / 'costs.jsonl'
    if mode.startswith('served_') or mode == 'calibration':
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
    if mode == 'calibration':
        from scripts.throw_calibration_summary import summarize
        summary = summarize(rows)
        assert summary['counts']['leads'] == 16
        assert summary['verdict'] == 'INSUFFICIENT'
        assert summary['overprediction'] == 0
        from scripts.throw_calibration_summary import main as read_calibration
        report = tmp_path / 'calibration.json'
        read_calibration([str(out), str(report), '--journal', str(costs)])
        assert json.loads(report.read_text())['counts'] == summary['counts']
        for row in rows:
            measured = row['throw_calibration']
            root, _ = restore_with_ledger(row['replay'])
            root.play(root.turn, row['attempted'])
            assert measured['accepted'] == root.trick.plays[-1].cards
            if measured['is_throw']:
                assert measured['predicted_success'] == float(measured['succeeded'])
                assert measured['worlds'] == 1
                assert measured['extra_draws'] == 1
                assert measured['unavailable'] is None
        assert any(x['throw_calibration']['is_throw'] and not x['throw_calibration']['succeeded'] for x in rows)
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
                                   ['--cost-out', 'unused'], ['--throw-calibration']])
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
    from shengji.train.throw_calibration import observe_worlds
    with observe_worlds(bot) as draws, observe_finish_pool(bot, root, root.turn) as evidence:
        action = bot.decide_play(root, root.turn)
    assert '_legal' not in vars(bot)
    assert '_worlds' not in vars(bot)
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


def test_throw_forecast_uses_sampled_worlds_and_checks_partner():
    from types import SimpleNamespace
    from shengji.engine.cards import Ordering
    from shengji.train.throw_calibration import forecast, committed
    hand = ['S4', 'S4', 'SJ']
    rnd = SimpleNamespace(phase='play', trick=SimpleNamespace(plays=[]), turn=0,
                          hands=[hand, ['SA'], ['SA'], ['SA']], banker=1,
                          history=[], ordering=Ordering('C', '2'))
    # No true hidden hand or kitty may affect the probability. Only one sampled
    # world has a beating card, held by the partner rather than an opponent.
    worlds = [([hand, ['H3'], ['SA'], ['D3']], []),
              ([hand, ['H3'], ['H4'], ['D3']], [])]
    record = dict(schema='pv-search-decision-v1', work_complete=True, played=hand)
    measured = forecast(rnd, 0, hand, [worlds], record, 2)
    assert measured['predicted_success'] == 0.5
    rnd.hands[1:] = [None, None, None]
    assert forecast(rnd, 0, hand, [worlds], record, 2) == measured
    assert not committed(measured, ['SJ'])['succeeded']
    assert committed(measured, hand)['succeeded']
    assert forecast(rnd, 0, hand, [worlds[:1]], record, 2)['unavailable']
    confirmation = forecast(rnd, 0, hand, [worlds, worlds[:1]], record, 2)
    assert confirmation['unavailable'] is None
    assert confirmation['predicted_success'] == 0.5
    assert confirmation['extra_draws'] == 1
    assert forecast(rnd, 0, hand, [], record, 2)['unavailable']
    assert forecast(rnd, 0, hand, [worlds], {**record, 'work_complete': False}, 2)['unavailable']
    with pytest.raises(ValueError, match='action drift'):
        forecast(rnd, 0, hand, [worlds], {**record, 'played': ['SJ']}, 2)


def test_throw_summary_refuses_bad_evidence_and_does_not_promote_small_samples(tmp_path):
    from scripts.throw_calibration_summary import summarize, main
    rec = dict(schema='throw-calibration-v1', attempted=['S4', 'SJ'], accepted=['S4'],
               is_throw=True, succeeded=False, worlds=64, predicted_success=0.5,
               unseen_union_risky=True, unavailable=None)
    row = dict(seed=1, game='1:0', round=0, trick=1, seat=0,
               attempted=rec['attempted'], throw_calibration=rec, collection={'policy': 'test'})
    assert summarize([row])['verdict'] == 'INSUFFICIENT'
    with pytest.raises(ValueError, match='duplicate'):
        summarize([row, row])
    rows = [dict(row, round=i) for i in range(1000)]
    result = summarize(rows)
    assert result['verdict'] == 'CALIBRATION_GAP'
    assert result['overprediction_ci95'] == [0.5, 0.5]
    sparse = [dict(r, throw_calibration=dict(rec, unseen_union_risky=i < 199))
              for i, r in enumerate(rows)]
    assert summarize(sparse)['verdict'] == 'INSUFFICIENT'
    # Two correlated rounds cannot masquerade as a thousand independent throws.
    correlated = [dict(row, round=i // 500, trick=i,
                       throw_calibration=dict(rec, predicted_success=0.7,
                           accepted=rec['attempted'] if i < 500 else rec['accepted'],
                           succeeded=i < 500)) for i in range(1000)]
    uncertain = summarize(correlated)
    assert uncertain['overprediction'] == pytest.approx(0.2)
    assert uncertain['risky_rounds'] == 2
    assert uncertain['overprediction_ci95'] == pytest.approx([-0.3, 0.7])
    assert uncertain['verdict'] == 'BAR_NOT_MET'
    assert summarize([dict(r, round=0) for r in correlated])['verdict'] == 'INSUFFICIENT'
    bad = copy.deepcopy(row)
    bad['throw_calibration']['unavailable'] = 'incomplete_decision'
    assert summarize([bad])['verdict'] == 'INCOMPLETE'
    bad['throw_calibration']['succeeded'] = True
    with pytest.raises(ValueError, match='outcome'):
        summarize([bad])
    source, output = tmp_path/'rows.jsonl', tmp_path/'summary.json'
    source.write_text(json.dumps(row)+'\n')
    journal = tmp_path/'journal.jsonl'
    entries = [dict(kind='start', identity=row['collection'], seed=1),
               dict(kind='decision', lead=True, round=0, seat=0, played=row['attempted']),
               dict(kind='terminal', positions=1, rounds=1, reason='max_rounds')]
    journal.write_text(''.join(json.dumps(e)+'\n' for e in entries))
    main([str(source), str(output), '--journal', str(journal)])
    assert json.loads(output.read_text())['overprediction'] == 0.5
    with pytest.raises(FileExistsError):
        main([str(source), str(output), '--journal', str(journal)])


def test_throw_summary_refuses_partial_or_misbound_journal():
    from scripts.throw_calibration_summary import validated_summary
    row = dict(seed=1, collection={'policy': 'test'}, round=0, seat=0, attempted=['S4'])
    journal = [dict(kind='start', identity=row['collection'], seed=1),
               dict(kind='decision', lead=True, round=0, seat=0, played=['S4']),
               dict(kind='terminal', reason='deadline', positions=1)]
    with pytest.raises(ValueError, match='did not complete'):
        validated_summary([row], journal)
    with pytest.raises(ValueError, match='missing collection terminal'):
        validated_summary([row], journal[:-1])
    journal[-1]['reason'] = 'max_positions'
    journal[-1]['positions'] = 2
    with pytest.raises(ValueError, match='count drift'):
        validated_summary([row], journal)
    journal[-1]['positions'] = 1
    journal[1]['played'] = ['SA']
    with pytest.raises(ValueError, match='decision drift'):
        validated_summary([row], journal)


def test_throw_world_hook_restores_existing_override_after_failure():
    from types import SimpleNamespace
    from shengji.train.throw_calibration import observe_worlds
    def fail(*args):
        raise RuntimeError('draw refused')
    bot = SimpleNamespace(_worlds=fail)
    with pytest.raises(RuntimeError, match='draw refused'):
        with observe_worlds(bot) as draws:
            bot._worlds(None, 0)
    assert bot._worlds is fail
    assert draws == []


def test_calibration_shards_require_every_planned_collection(tmp_path):
    from scripts.throw_calibration_shards import aggregate, main

    def shard(seed):
        rec = dict(schema='throw-calibration-v1', attempted=['S4', 'SJ'],
                   accepted=['S4'], is_throw=True, succeeded=False, worlds=64,
                   predicted_success=0.5, unseen_union_risky=True, unavailable=None)
        identity = dict(policy='same', seat_seeds=[seed * 10 + s for s in range(4)])
        rows = [dict(seed=seed, game='same-game', round=0, trick=1, seat=0,
                     attempted=rec['attempted'], throw_calibration=rec, collection=identity)]
        journal = [dict(kind='start', seed=seed, identity=identity, max_rounds=1),
                   dict(kind='decision', lead=True, round=0, seat=0, played=rec['attempted']),
                   dict(kind='terminal', reason='max_rounds', rounds=1, positions=1)]
        return [seed, 1, rows, journal]

    first, second = shard(100), shard(200)
    result = aggregate([first, second])
    assert result['counts']['throws'] == 2
    assert result['risky_rounds'] == 2
    assert result['verdict'] == 'INSUFFICIENT'
    assert first[2][0]['collection']['seat_seeds'] == [1000, 1001, 1002, 1003]
    with pytest.raises(ValueError, match='duplicate shard seed'):
        aggregate([first, first])
    for change, message in [
        (lambda s: s[3].pop(), 'terminal'),
        (lambda s: s.__setitem__(0, 201), 'unplanned seed'),
        (lambda s: s.__setitem__(1, 2), 'planned rounds'),
        (lambda s: s[2][0]['collection'].__setitem__('policy', 'other'), 'mixed policy'),
        (lambda s: s[2][0]['collection'].__setitem__('seat_seeds', [0]*4), 'seat seed'),
    ]:
        bad = copy.deepcopy(second)
        change(bad)
        with pytest.raises(ValueError, match=message):
            aggregate([first, bad])
    entries = []
    for seed, rounds, rows, journal in [first, second]:
        for name, values in [('rows', rows), ('journal', journal)]:
            (tmp_path/f'{seed}.{name}').write_text(''.join(json.dumps(v)+'\n' for v in values))
        entries.append(dict(seed=seed, rounds=rounds, rows=f'{seed}.rows', journal=f'{seed}.journal'))
    manifest, output = tmp_path/'manifest.json', tmp_path/'summary.json'
    manifest.write_text(json.dumps(dict(schema='throw-calibration-shards-v1', shards=entries)))
    main([str(manifest), str(output)])
    assert json.loads(output.read_text()) == result
    with pytest.raises(FileExistsError):
        main([str(manifest), str(output)])
    (tmp_path/'200.journal').unlink()
    with pytest.raises(FileNotFoundError):
        main([str(manifest), str(tmp_path/'partial.json')])
    assert not (tmp_path/'partial.json').exists()
