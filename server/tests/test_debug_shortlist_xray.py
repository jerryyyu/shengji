"""Consumer-level diagnostics, redaction and shared-worker admission witnesses."""
import asyncio
import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shengji.api import debug, model_serving
from shengji.api.debug_play import MAX_CANDIDATES, play_analysis
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_debug_xray import _lead_state, _RecordingBot
from tests.test_world_shortlist import play_state, round_signature


class Values:
    def score(self, states, seat):
        return np.asarray([r.attacker_points for r in states], dtype=float)

    def identity(self):
        return dict(backend="fixture", checkpoint_sha256="a" * 64,
                    source_checkpoint_sha256="b" * 64, encoding="reference",
                    checkpoint="/private/secret/model", hidden_world="NEVER_EXPOSE")


def test_real_shortlist_decision_survives_xray_with_exact_scores(monkeypatch):
    rnd = play_state()
    seat = rnd.turn
    bot = CWVShortlistBot(Values(), seed=13, config=CWVShortlistConfig(
        worlds=1, selection_worlds=2, alternatives=4, batch_size=17))
    bot.REPORT_FOLD_WORLDS = 30
    # Real sampler, enumeration, ranking, MC selection/report and finalization;
    # only terminal playout cost is replaced by a deterministic cheap outcome.
    monkeypatch.setattr(CWVShortlistBot, "_rollout",
                        lambda self, rnd, seat, hands, buried, action, **kw: float(len(action)))
    before = round_signature(rnd), bot.rng.getstate()
    clone = copy.deepcopy(bot)
    expected_pick = clone.decide_play(copy.deepcopy(rnd), seat)
    rnd_copy, bot_copy = debug._snapshot_xray(rnd, bot)
    out = debug._xray(rnd_copy, seat, bot_copy)
    assert before == (round_signature(rnd), bot.rng.getstate())
    rec = clone.last_decision_record
    detail = rec['cwv_shortlist']
    assert out['analysis']['model']['checkpoint_sha256'] == 'a' * 64
    assert out['analysis']['reason'] == rec['reason']
    assert out['analysis']['recipe']['worlds'] == 1
    assert out['analysis']['shortlist']['legal_count'] == detail['legal_count']
    assert out['analysis']['report']['se'] == rec['report_fold']['se']
    assert out['analysis']['report']['statistic'] == rec['report_fold']['statistic']
    assert out['analysis']['work']['report_rollouts'] == 60
    assert out['analysis']['historical_decision'] is False
    for row in out['candidates']:
        i = row['index']
        assert row['model_score'] == detail['shortlist_means'][i]
        assert row['attackers_avg'] == rec['means'][i] * (1 if rnd.is_attacker(seat) else -1)
        assert row['paired_se_vs_incumbent'] == rec['paired_se'][i]
        assert row['se'] is None
        assert row['old_ballot'] == (tuple(sorted(row['play'])) in
                                    {tuple(c) for c in detail['production_keys']})
    assert next(r['play'] for r in out['candidates'] if r['bot_plays']) == expected_pick
    assert 'NEVER_EXPOSE' not in json.dumps(out)
    assert '/private/secret' not in json.dumps(out)
    assert 'rng_state' not in json.dumps(out)
    # The UI consumes a captured response from this exact producer. Ignore
    # only measured timing and additive fields when comparing its fixture.
    fixture = json.loads((Path(__file__).resolve().parents[2] /
        'web/src/components/xray-shortlist.fixture.json').read_text())
    assert out['candidates'] == fixture['candidates']
    assert out['analysis']['report'] == fixture['analysis']['report']
    assert out['analysis']['work'] == fixture['analysis']['work']


def test_forced_or_no_model_has_unavailable_scores_not_invented_zero():
    bot = SimpleNamespace(last_eval=None, last_decision_record=None)
    rows, info = play_analysis(bot, ['SA'], is_attacker=True, elapsed=.1)
    assert rows[0]['attackers_avg'] is None and rows[0]['se'] is None
    assert rows[0]['model_score'] is None and rows[0]['bot_plays']
    assert info['model'] is None and info['report'] is None
    assert info['reason'] == 'forced_or_no_search'


def test_no_model_selection_preserves_points_and_never_invents_se():
    rnd, seat = _lead_state()
    out = debug._xray(rnd, seat, _RecordingBot())
    assert out['analysis']['model'] is None
    assert all(r['se'] is None and r['paired_se_vs_incumbent'] is None for r in out['candidates'])
    assert out['candidates'][0]['attackers_avg'] == 2.5 * (1 if rnd.is_attacker(seat) else -1)


def test_small_ballot_without_model_evaluation_is_not_called_model_nominated():
    bot = SimpleNamespace(last_eval=([['SA'], ['SK']], [1., 2.]),
        last_decision_record={'cwv_shortlist': {'shortlist': [['SA'], ['SK']],
                                               'shortlist_means': None}})
    rows, _ = play_analysis(bot, ['SK'], is_attacker=True, elapsed=0.)
    assert not any(row['model_nominated'] for row in rows)


def test_allowlist_caps_rows_keeps_finalists_and_redacts_unknown_fields():
    candidates = [[f'fixture{i}'] for i in range(100)]
    rec = dict(report_candidate_index=98, played_index=99, secret='NEVER_EXPOSE',
               report_fold=dict(gap=3., se=.25, worlds=300, complete=True,
                                statistic=2.5, min_gain=0., rng_state='NEVER_EXPOSE'),
               work=dict(total_rollouts=600, hidden='NEVER_EXPOSE'))
    bot = SimpleNamespace(last_eval=(candidates, [float('inf')] * 100), last_decision_record=rec)
    rows, info = play_analysis(bot, candidates[99], is_attacker=False, elapsed=.2)
    assert len(rows) == MAX_CANDIDATES
    assert {0,98,99} <= {r['index'] for r in rows}
    assert info['candidates_truncated'] and info['candidate_count'] == 100
    assert info['report']['gap'] == 3. and info['report']['se'] == .25
    assert all(r['attackers_avg'] is None for r in rows)
    assert 'NEVER_EXPOSE' not in json.dumps([rows,info], allow_nan=False)


def test_route_authentication_and_invalid_seat_do_not_start_search(monkeypatch):
    monkeypatch.setenv('SHENGJI_DEBUG_TOKEN', 'test-token')
    rnd, _ = _lead_state()
    room = SimpleNamespace(round=rnd, bot=_RecordingBot(), lock=asyncio.Lock())
    app = FastAPI(); debug.register_debug(app, {'TEST': room})
    monkeypatch.setattr(debug, '_snapshot_xray', lambda *a: pytest.fail('must not snapshot'))
    with TestClient(app) as client:
        assert client.get('/debug/xray?room=TEST&seat=0').json() == {'error': 'not found'}
        assert client.get('/debug/xray?room=TEST&seat=4&token=test-token').json() == {'error': 'invalid seat'}


def test_authenticated_route_returns_isolated_analysis_without_mutating_room(monkeypatch):
    monkeypatch.setenv('SHENGJI_DEBUG_TOKEN', 'test-token')
    rnd, seat = _lead_state()
    bot = _RecordingBot()
    rng_before = bot.rng.getstate()
    room = SimpleNamespace(round=rnd, bot=bot, lock=asyncio.Lock())
    app = FastAPI(); debug.register_debug(app, {'TEST': room})
    with TestClient(app) as client:
        response = client.get(f'/debug/xray?room=test&seat={seat}&token=test-token')
    assert response.status_code == 200
    out = response.json()
    assert out['analysis']['source'] == 'isolated_current_state_replay'
    assert out['analysis']['snapshot'] == {
        'trick_number': 1, 'plays_in_trick': 0, 'acting_seat': seat}
    assert out['analysis']['model'] is None
    assert sum(c['bot_plays'] for c in out['candidates']) == 1
    assert bot.calls == 0 and bot.rng.getstate() == rng_before


def test_busy_gameplay_rejects_xray_before_snapshot(monkeypatch):
    monkeypatch.setattr(debug, '_snapshot_xray', lambda *a: pytest.fail('must not snapshot'))
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def gameplay():
            started.set(); await release.wait()
        task = asyncio.create_task(model_serving.run_model_search(gameplay, lambda *a, **kw: None))
        await started.wait()
        result = await debug._xray_room(None, 0, None)
        assert result['error'].startswith('search busy')
        release.set(); await task
    asyncio.run(scenario())


def test_cancelled_xray_keeps_shared_permit_until_thread_finishes(monkeypatch):
    started, release = threading.Event(), threading.Event()
    def cpu(*a):
        started.set(); assert release.wait(3); return {'ok': True}
    monkeypatch.setattr(debug, '_xray', cpu)
    rnd, seat = _lead_state()
    async def scenario():
        room = SimpleNamespace(round=rnd, bot=_RecordingBot(), lock=asyncio.Lock())
        task = asyncio.create_task(debug._xray_room(room, seat, None))
        while not started.is_set(): await asyncio.sleep(0)
        task.cancel(); await asyncio.sleep(0)
        assert model_serving._semaphore().locked()
        assert (await debug._xray_room(room,seat,None))['error'].startswith('search busy')
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert not model_serving._semaphore().locked()
    asyncio.run(scenario())
