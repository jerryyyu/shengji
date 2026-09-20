import json

import pytest

from shengji.train import policy_world_duel as duel
from test_policy_world_search import state


def test_worker_flushes_before_pair_finishes_and_never_overwrites(monkeypatch, tmp_path):
    path = tmp_path / '7.jsonl'
    def interrupted(*args, progress, **kwargs):
        progress(dict(event='decision_start', mirror=0, move=3, seat=2, role='policy'))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [r['event'] for r in rows] == ['pair_start', 'decision_start']
        assert rows[-1]['seed'] == 7
        raise SystemExit('simulate termination before pair result')
    monkeypatch.setattr(duel, 'play_pair', interrupted)
    args = (7, 'ck', 'sha', 1, 'mc-lcb', 'policy-value', 8, None, str(path))
    with pytest.raises(SystemExit):
        duel._worker_pair(args)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        duel._worker_pair(args)
    assert path.read_bytes() == original


@pytest.mark.parametrize('refused', [False, True])
def test_mirror_boundaries_and_refusal_do_not_become_scores(monkeypatch, tmp_path, refused):
    def mirror(seed, parity, *args, progress):
        progress(dict(event='decision_start', move=0, seat=parity, role='policy'))
        one = dict(sides={r: duel._empty_side() for r in ('policy', 'control')})
        if refused:
            return dict(one, timeout=True, error={'type': 'TimeoutError', 'message': 'private detail'})
        progress(dict(event='decision_complete', move=0, seat=parity, role='policy', decision_seconds=.1))
        return dict(one, utility=1.)
    monkeypatch.setattr(duel, '_play_one', mirror)
    path = tmp_path / '7.jsonl'
    result = duel._worker_pair((7, 'ck', 'sha', 1, 'mc-lcb', 'policy-value', 8, None, str(path)))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[-1]['event'] == ('pair_refused' if refused else 'pair_complete')
    assert [r['mirror'] for r in rows if r['event'] == 'mirror_start'] == ([0] if refused else [0, 1])
    assert 'private detail' not in path.read_text()
    if refused:
        assert 'utility' not in result
        assert any(r['event'] == 'mirror_refused' and r['timeout'] for r in rows)
    else:
        assert result['utility'] == 1.


def test_move_progress_preserves_actions_and_public_metadata(monkeypatch):
    monkeypatch.setattr(duel, '_prepare_round', lambda *a: state())
    monkeypatch.setattr(duel, 'make_policy', lambda *a, **k: duel.HeuristicBot())
    monkeypatch.setattr(duel, 'make_control', lambda *a, **k: duel.HeuristicBot())
    actions = []
    def timed(bot, rnd, seat):
        cards = bot.decide_play(rnd, seat)
        actions.append((seat, tuple(cards)))
        return cards, .01
    monkeypatch.setattr(duel, '_timed_play', timed)
    plain = duel._play_one(7, 0, 'ck', 'sha', 1, 'mc-lcb')
    original = list(actions)
    actions.clear()
    events = []
    logged = duel._play_one(7, 0, 'ck', 'sha', 1, 'mc-lcb', progress=events.append)
    assert actions == original and actions
    assert {k: v for k, v in logged.items() if k != 'max_rss_kib'} == {
        k: v for k, v in plain.items() if k != 'max_rss_kib'}
    assert len(events) == 2 * len(actions)
    for i in range(len(actions)):
        start, end = events[2*i:2*i+2]
        assert start['event'] == 'decision_start'
        assert end['event'] == 'decision_complete'
        assert start['move'] == end['move'] == i
        assert set(end) == {'event', 'move', 'seat', 'role', 'decision_seconds'}
