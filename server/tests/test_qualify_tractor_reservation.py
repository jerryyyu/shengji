import asyncio
import copy
import json
from types import SimpleNamespace
import random

import pytest

from scripts import qualify_tractor_reservation as q
from shengji.api import server
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick
from shengji.harvest.legal import enumerate_legal


def test_public_root_has_a_real_legal_tractor():
    rnd = q.build_root()
    legal = enumerate_legal(rnd, rnd.turn, cap=4000)
    assert rnd.phase == 'play' and not rnd.trick.plays
    assert any(q._pure_tractor(rnd, action) for action in legal.actions)


def test_recipe_only_changes_reservation(monkeypatch):
    calls = []
    monkeypatch.setattr(q.pv, 'pv_registry_entries',
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    q._recipe('pkg.npz', 'a' * 64, False)
    q._recipe('pkg.npz', 'a' * 64, True)
    assert calls[0][0] == calls[1][0] == ('pkg.npz',)
    assert calls[0][1].pop('tractor_reservation') is False
    assert calls[1][1].pop('tractor_reservation') is True
    assert calls[0][1] == calls[1][1]
    assert calls[0][1]['worlds'] == 64
    assert calls[0][1]['candidates'] == 8


class _Ordering:
    def eff_suit(self, card):
        return card[0]


class _Round:
    phase = 'play'
    trick = SimpleNamespace(plays=[])
    turn = 0
    hands = [['C2'], ['S3'], ['D4'], ['H5']]
    ordering = _Ordering()


def _install_fake_qualification(monkeypatch, roots, *, submitted=None,
                                final=None, attempted=None,
                                engine_resolution=None, event=True,
                                record_played=None, value_means=None,
                                binding=True):
    submitted = ['S3'] if submitted is None else submitted
    final = submitted if final is None else final
    record_played = submitted if record_played is None else record_played
    value_means = [0.0] if value_means is None else value_means

    class Bot:
        def __init__(self, enabled):
            self.enabled = enabled
            self.last_decision_record = None

    monkeypatch.setattr(q, 'build_root', lambda seed: roots.pop(0))
    monkeypatch.setattr(q, '_recipe', lambda package, sha, enabled: {
        'off' if not enabled else 'on': lambda seed: Bot(enabled)})
    monkeypatch.setattr(q.srv, 'Room', lambda **kw: SimpleNamespace(
        **kw, ids=None, _kitty_given=False, log_event=None))
    monkeypatch.setattr(q.srv, 'Seat', lambda name, is_bot: name)

    async def paced(room, seat, minimum_turn_seconds=0):
        copied = copy.copy(room.bot)
        copied.last_decision_record = {
            'worlds': 64, 'work_complete': True, 'admitted': [['C2']],
            'admitted_indices': [7], 'selected_index': 7,
            'selected_action': ['C2'], 'played': list(record_played),
            'value_means': value_means,
        }
        return SimpleNamespace(decision=SimpleNamespace(
            cards=list(submitted), snapshot=SimpleNamespace(bot_copy=copied)))

    monkeypatch.setattr(q.srv, '_paced_bot_step', paced)

    committed = set()

    def commit(room, prepared):
        key = id(prepared)
        if key in committed:
            return False
        committed.add(key)
        if event:
            fields = {
                'seat': 0, 'cards': list(final), 'bot': True,
                'decision': copy.deepcopy(
                    prepared.decision.snapshot.bot_copy.last_decision_record)
                if binding else {},
            }
            if attempted is not None:
                fields['attempted_cards'] = list(attempted)
            if engine_resolution is not None:
                fields['engine_resolution'] = engine_resolution
            room.log_event('play', **fields)
        return True

    monkeypatch.setattr(q.srv, '_commit_bot_turn', commit)


def test_qualifier_binds_realistic_play_event_and_allows_postprocessing(monkeypatch,
                                                                         tmp_path):
    _install_fake_qualification(monkeypatch, [_Round(), _Round()])
    out = tmp_path / 'rows.jsonl'
    with out.open('w') as dest:
        rows = asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
    assert len(rows) == 2 and len(out.read_text().splitlines()) == 2
    assert all(row['passed'] and row['evidence_valid'] for row in rows)
    assert rows[0]['submitted_cards'] == ['S3']
    assert rows[0]['final_cards'] == ['S3']
    assert rows[0]['selected_action'] == ['C2']


def test_qualifier_records_legitimate_failed_throw_resolution(monkeypatch, tmp_path):
    submitted = ['C2', 'C2', 'D3', 'D3']
    _install_fake_qualification(
        monkeypatch, [_Round(), _Round()], submitted=submitted,
        final=['C2', 'C2'], attempted=submitted,
        engine_resolution='failed_throw_forced')
    out = tmp_path / 'rows.jsonl'
    with out.open('w') as dest:
        rows = asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
    assert all(row['passed'] for row in rows)
    assert rows[0]['submitted_cards'] == submitted
    assert rows[0]['final_cards'] == ['C2', 'C2']
    assert rows[0]['attempted_cards'] == submitted
    assert rows[0]['engine_resolution'] == 'failed_throw_forced'


def test_play_evidence_accepts_real_engine_failed_throw_event():
    candidate = ['C7', 'C7', 'D7', 'D7', 'H7', 'H7']
    submitted = list(candidate)
    rnd = Round('7', 0, random.Random(1))
    rnd.phase = 'play'
    rnd.turn = 0
    rnd.trump_suit = 'H'
    rnd.trump_is_nt = False
    rnd.ordering = Ordering('H', '7')
    rnd.hands = [candidate, ['LJ', 'LJ'], ['C8'], ['D8']]
    rnd.kitty = []
    rnd.buried = []
    rnd.history = []
    rnd.trick = Trick(leader=0)

    class Bot:
        def __init__(self):
            self.last_decision_record = None

        def decide_play(self, _rnd, _seat):
            self.last_decision_record = {
                'played': list(candidate), 'admitted': [list(candidate)],
                'value_means': [0.0], 'worlds': 64,
                'work_complete': True,
            }
            return list(candidate)

    game = Game(random.Random(7))
    game.round = rnd
    room = server.Room(
        code='TRACTOR-REAL-EVENT', game=game, bot=Bot(),
        seats=[server.Seat(str(seat), is_bot=True) for seat in range(4)])
    room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
    room._kitty_given = True
    events = []
    room.log_event = lambda kind, **data: events.append({'e': kind, **copy.deepcopy(data)})

    snapshot = server._snapshot_bot_turn(room, 0, 'bot')
    decision = server._compute_bot_turn(snapshot)
    prepared = server._PreparedBotTurn(
        decision=decision, compute_seconds=0.0,
        pacing_seconds=0.0, turn_seconds=0.0)
    assert server._commit_bot_turn(room, prepared) is True
    assert server._commit_bot_turn(room, prepared) is False
    record = prepared.decision.snapshot.bot_copy.last_decision_record
    play = next(event for event in events if event['e'] == 'play')
    final, attempted, resolution = q._play_evidence(
        events, 0, record, submitted)
    assert final == ['D7', 'D7']
    assert attempted == submitted
    assert resolution == 'failed_throw_forced'
    assert play['decision'] == record


@pytest.mark.parametrize('case,kwargs,error', [
    ('missing event', {'event': False}, 'exactly one play event'),
    ('record mismatch', {'record_played': ['C2']}, 'does not match submitted_cards'),
    ('nonfinite value', {'value_means': [float('nan')]}, 'non-finite'),
    ('value length', {'value_means': [0.0, 1.0]}, 'value_means length'),
    ('event binding', {'binding': False}, 'decision is not bound'),
    ('bad resolution', {'final': ['C2']}, 'failed-throw resolution'),
])
def test_qualifier_flushes_and_rejects_malformed_evidence(monkeypatch, tmp_path,
                                                           case, kwargs, error):
    _install_fake_qualification(monkeypatch, [_Round(), _Round()], **kwargs)
    out = tmp_path / 'rows.jsonl'
    with out.open('w') as dest:
        with pytest.raises(RuntimeError, match=error):
            asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]['passed'] is False
    assert rows[0]['evidence_valid'] is False
    assert error.split()[0] in rows[0]['evidence_error']


def test_commit_boundary_failure_is_flushed_before_rejection(monkeypatch, tmp_path):
    _install_fake_qualification(
        monkeypatch, [_Round(), _Round()], record_played=['C2'])

    def commit(_room, _prepared):
        raise RuntimeError('bot decision record/play mismatch')

    monkeypatch.setattr(q.srv, '_commit_bot_turn', commit)
    out = tmp_path / 'commit-failure.jsonl'
    with out.open('w') as dest:
        with pytest.raises(RuntimeError, match='commit failed'):
            asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]['passed'] is False
    assert rows[0]['evidence_valid'] is False
    assert 'bot decision record/play mismatch' in rows[0]['evidence_error']


def test_partial_output_survives_second_call_failure(monkeypatch, tmp_path):
    roots = [_Round(), _Round()]
    monkeypatch.setattr(q, 'build_root', lambda seed: roots.pop(0))

    class Bot:
        def __init__(self):
            self.last_decision_record = None

    monkeypatch.setattr(q, '_recipe', lambda *args: {'x': lambda seed: Bot()})
    monkeypatch.setattr(q.srv, 'Room', lambda **kw: SimpleNamespace(
        **kw, ids=None, _kitty_given=False, log_event=None))
    monkeypatch.setattr(q.srv, 'Seat', lambda name, is_bot: name)
    calls = [0]

    async def fail_second(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError('synthetic failure')
        copied = SimpleNamespace(last_decision_record={
            'worlds': 64, 'work_complete': True, 'admitted': [['C2']],
            'admitted_indices': [0], 'selected_index': 0,
            'played': ['C2'], 'value_means': [0.0]})
        return SimpleNamespace(decision=SimpleNamespace(
            cards=['C2'], snapshot=SimpleNamespace(bot_copy=copied)))

    monkeypatch.setattr(q.srv, '_paced_bot_step', fail_second)
    committed = set()

    def commit(room, prepared):
        key = id(prepared)
        if key in committed:
            return False
        committed.add(key)
        room.log_event('play', seat=0, cards=['C2'], bot=True,
                       decision=copy.deepcopy(
                           prepared.decision.snapshot.bot_copy.last_decision_record))
        return True

    monkeypatch.setattr(q.srv, '_commit_bot_turn', commit)
    out = tmp_path / 'partial.jsonl'
    with out.open('w') as dest:
        with pytest.raises(RuntimeError, match='synthetic failure'):
            asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['enabled'] is False
