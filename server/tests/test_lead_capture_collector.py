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
from shengji.train import pv_search_policy as pv
from test_pv_search_serving import package  # noqa: F401


@pytest.mark.parametrize('mode', ['historical', 'served', 'fallback'])
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
            self._refusals.observe(root)
            event = plays[cursor]
            assert event['seat'] == seat
            cursor += 1
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
    collector.main(args)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert cursor == len(plays) == 64
    assert len(rows) == 16
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
