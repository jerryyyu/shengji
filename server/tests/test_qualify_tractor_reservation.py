import asyncio
import copy
import json
from types import SimpleNamespace
import pytest

from scripts import qualify_tractor_reservation as q
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


class _Round:
    phase = 'play'
    trick = SimpleNamespace(plays=[])
    turn = 0
    hands = [['C2'], ['S3'], ['D4'], ['H5']]
    ordering = SimpleNamespace(eff_suit=lambda _self, card: card[0])


@pytest.mark.parametrize('complete,bound', [(True, True), (False, True), (True, False)])
def test_qualifier_flushes_bounded_records_and_accepts_unchanged(monkeypatch, tmp_path, complete, bound):
    roots = [_Round(), _Round()]
    seen = []

    class Bot:
        def __init__(self, enabled):
            self.enabled = enabled
            self.last_decision_record = None

        def _legal(self, rnd, seat, anchor):
            return SimpleNamespace(actions=[['C2']], count=1, complete=True)

    monkeypatch.setattr(q, 'build_root', lambda seed: roots.pop(0))
    monkeypatch.setattr(q, '_recipe', lambda package, sha, enabled: {
        'off' if not enabled else 'on': lambda seed: Bot(enabled)})
    monkeypatch.setattr(q.HeuristicBot, 'decide_play', lambda self, rnd, seat: ['C2'])
    monkeypatch.setattr(q.srv, 'Room', lambda **kw: SimpleNamespace(**kw, ids=None,
                                                                      _kitty_given=False,
                                                                      log_event=None))
    monkeypatch.setattr(q.srv, 'Seat', lambda name, is_bot: name)

    async def paced(room, seat, minimum_turn_seconds=0):
        copied = copy.copy(room.bot)
        copied.last_decision_record = {
            'worlds': 64, 'work_complete': complete, 'admitted': [['C2']],
            'admitted_indices': [7] if bound else [],
            'selected_index': 7, 'value_means': [0.0],
        }
        return SimpleNamespace(decision=SimpleNamespace(
            cards=['S3'], snapshot=SimpleNamespace(bot_copy=copied)))

    commits = []
    def commit(room, prepared):
        if commits and commits[-1] is prepared:
            return False
        commits.append(prepared)
        return True

    monkeypatch.setattr(q.srv, '_paced_bot_step', paced)
    monkeypatch.setattr(q.srv, '_commit_bot_turn', commit)
    out = tmp_path / 'rows.jsonl'
    with out.open('w') as dest:
        if complete and bound:
            rows = asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
        else:
            with pytest.raises(RuntimeError, match='qualification failed'):
                asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
            rows = [json.loads(line) for line in out.read_text().splitlines()]
            assert len(rows) == 1 and rows[0]['passed'] is False
            assert len(commits) == 1
            return
    assert len(rows) == 2 and len(out.read_text().splitlines()) == 2
    assert all(row['committed'] and row['snapshot_unchanged'] for row in rows)
    assert rows[0]['displacement_from_off'] is False
    assert rows[1]['displacement_from_off'] is False
    assert rows[0]['selected_action'] == ['C2']
    assert rows[0]['final_cards'] == ['S3']


def test_partial_output_survives_second_call_failure(monkeypatch, tmp_path):
    roots = [_Round(), _Round()]
    monkeypatch.setattr(q, 'build_root', lambda seed: roots.pop(0))
    class Bot:
        def _legal(self, rnd, seat, anchor):
            return SimpleNamespace(actions=[['C2']], count=1, complete=True)
    monkeypatch.setattr(q, '_recipe', lambda *args: {'x': lambda seed: Bot()})
    monkeypatch.setattr(q.HeuristicBot, 'decide_play', lambda self, rnd, seat: ['C2'])
    monkeypatch.setattr(q.srv, 'Room', lambda **kw: SimpleNamespace(**kw, ids=None,
                                                                      _kitty_given=False,
                                                                      log_event=None))
    monkeypatch.setattr(q.srv, 'Seat', lambda name, is_bot: name)
    calls = [0]
    async def fail_second(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError('synthetic failure')
        copied = SimpleNamespace(last_decision_record={
            'worlds': 64, 'work_complete': True, 'admitted': [['C2']],
            'admitted_indices': [0],
            'selected_index': 0, 'played': ['C2'], 'value_means': [0.0]})
        return SimpleNamespace(decision=SimpleNamespace(
            cards=['C2'], snapshot=SimpleNamespace(bot_copy=copied)))
    monkeypatch.setattr(q.srv, '_paced_bot_step', fail_second)
    committed = set()
    def commit(room, prepared):
        key = id(prepared)
        if key in committed:
            return False
        committed.add(key)
        return True
    monkeypatch.setattr(q.srv, '_commit_bot_turn', commit)
    out = tmp_path / 'partial.jsonl'
    with out.open('w') as dest:
        try:
            asyncio.run(q.qualify('pkg.npz', 'a' * 64, dest))
        except RuntimeError as exc:
            assert str(exc) == 'synthetic failure'
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['enabled'] is False
