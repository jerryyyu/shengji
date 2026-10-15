import copy
import json
from pathlib import Path

import pytest

from shengji.train.lead_root_capture import LeadCapture, fingerprint, restore, restore_with_ledger, normalized
from shengji.ai.refusal import RefusalLedger
from shengji.rl.replay_log import rebuild_round

EVENTS = json.loads((Path(__file__).parent / 'fixtures/xmtj_round1.json').read_text())
PLAYS = [e for e in EVENTS if e['e'] == 'play']


def packets():
    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    ledgers = [RefusalLedger() for _ in range(4)]
    out = []
    for event in PLAYS:
        seat = rnd.turn
        ledger = ledgers[seat]
        ledger.observe(rnd)
        if not rnd.trick.plays:
            before = fingerprint(rnd)
            packet = capture.capture(rnd, ledger=ledger, decision={'played': event['attempted']})
            assert fingerprint(rnd) == before
            loaded = json.loads(json.dumps(packet))
            assert fingerprint(restore(loaded)) == before
            restored, replay_ledger = restore_with_ledger(loaded)
            assert normalized(vars(replay_ledger)) == normalized(vars(ledger))
            assert replay_ledger.observe(restored) == ledger.refusals
            out.append(loaded)
        rnd.play(seat, event['attempted'])
        capture.committed(rnd, seat, event['attempted'])
    assert rnd.phase == 'round_end'
    return out


def test_actual_producer_json_to_engine_consumer_with_expired_refusals():
    rows = packets()
    assert len(rows) == 16
    assert any(row['ledger']['refusals'] and row['root']['notice'] is None for row in rows)
    assert any(e['attempted'] != e['accepted'] for row in rows for e in row['plays'])


def test_follow_capture_json_replays_actual_continuation_and_keeps_lead_api_strict():
    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    ledgers = [RefusalLedger() for _ in range(4)]
    follows = 0
    for event in PLAYS:
        seat = rnd.turn
        ledgers[seat].observe(rnd)
        if rnd.trick.plays:
            before = fingerprint(rnd)
            with pytest.raises(ValueError, match='not a lead root'):
                capture.capture(rnd, ledger=ledgers[seat], decision={})
            packet = capture.capture_turn(rnd, ledger=ledgers[seat], decision={})
            restored, ledger = restore_with_ledger(json.loads(json.dumps(packet)))
            assert fingerprint(rnd) == fingerprint(restored) == before
            assert normalized(vars(ledger)) == normalized(vars(ledgers[seat]))
            restored.play(seat, event['attempted'])
            follows += 1
        else:
            restored = None
        rnd.play(seat, event['attempted'])
        capture.committed(rnd, seat, event['attempted'])
        if restored is not None:
            assert fingerprint(restored) == fingerprint(rnd)
    assert follows == 48
    with pytest.raises(ValueError, match='not a play root'):
        capture.capture_turn(rnd, ledger=ledgers[seat], decision={})


def test_follow_capture_reaches_server_snapshot_compute_commit():
    import asyncio
    import random
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from test_pv_admission_rules import served

    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    first = PLAYS[0]
    rnd.play(rnd.turn, first['attempted'])
    capture.committed(rnd, first['seat'], first['attempted'])
    ledger = RefusalLedger()
    ledger.observe(rnd)
    packet = capture.capture_turn(rnd, ledger=ledger, decision={})
    restored, restored_ledger = restore_with_ledger(json.loads(json.dumps(packet)))

    async def decide(root, observed):
        bot = served(refusal_constraints=True)
        bot._refusals = observed
        room = srv.Room(code='FOLLOWCAPTURE', bot=bot)
        room.game = Game(random.Random(7))
        room.game.round = root
        room.seats = [srv.Seat(name=str(s), is_bot=True) for s in range(4)]
        room.ids = [dict(enumerate(h)) for h in root.hands]
        room._kitty_given = True
        prepared = await srv._paced_bot_step(room, root.turn, minimum_turn_seconds=0)
        assert prepared is not None
        async with room.lock:
            assert srv._commit_bot_turn(room, prepared)
        return list(prepared.decision.cards), fingerprint(root)

    # Real server transaction with stub network, not model latency evidence.
    assert asyncio.run(decide(restored, restored_ledger)) == asyncio.run(decide(rnd, ledger))


def test_latency_worker_consumes_lead_and_follow_roots(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from shengji.api import server as srv
    from scripts import exact_endgame_latency as worker
    from test_pv_admission_rules import served

    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    ledger = RefusalLedger()
    roots = []
    for event in PLAYS:
        ledger.observe(rnd)
        if max(map(len, rnd.hands)) <= 6 and len(roots) < 4:
            roots.append(dict(root_index=len(roots), deal_seed=0, trick=len(rnd.history),
                              seat=rnd.turn, hand_size=len(rnd.hands[rnd.turn]),
                              lead=not bool(rnd.trick.plays), max_hand=max(map(len, rnd.hands)),
                              packet=capture.capture_turn(rnd, ledger=ledger, decision={})))
        rnd.play(rnd.turn, event['attempted'])
        capture.committed(rnd, event['seat'], event['attempted'])
    assert {r['lead'] for r in roots} == {True, False}
    path = tmp_path / 'roots.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in roots))
    args = SimpleNamespace(roots=path, pass_label='test', arm='r45')
    result = asyncio.run(worker.measure(args, srv, served(refusal_constraints=True), tmp_path))
    rows = [json.loads(line) for line in (tmp_path / 'measure_test.jsonl').read_text().splitlines()]
    assert result == {'roots_measured': 4}
    assert [r['lead'] for r in rows] == [r['lead'] for r in roots]
    assert all(r['committed_once'] and r['wall_total_seconds'] >= r['wall_step_seconds'] >= 0 for r in rows)
    rec = dict(exact_follow_attempted=True, exact_follow_applied=False,
               exact_follow_abandoned='soft_budget', exact_follow_error='TimeoutError')
    assert all(worker.record_fields(rec)[k] == v for k, v in rec.items())
    original = path.read_text()
    for field in ('hand_size', 'trick'):
        bad = copy.deepcopy(roots)
        bad[0][field] += 1
        path.write_text(''.join(json.dumps(r) + '\n' for r in bad))
        args.pass_label = 'bad_' + field
        with pytest.raises(AssertionError):
            asyncio.run(worker.measure(args, srv, served(), tmp_path))
        assert not (tmp_path / f'measure_{args.pass_label}.jsonl').read_text()
    path.write_text(original)
    timed = worker.timed_turn
    async def failed_commit(*a):
        prepared, step, commit, _ = await timed(*a)
        return prepared, step, commit, False
    monkeypatch.setattr(worker, 'timed_turn', failed_commit)
    args.pass_label = 'refused'
    with pytest.raises(RuntimeError, match='not committed'):
        asyncio.run(worker.measure(args, srv, served(), tmp_path))
    assert not (tmp_path / 'measure_refused.jsonl').read_text()


def test_latency_worker_seals_factory_refusal_without_retry(tmp_path, monkeypatch):
    from scripts import exact_endgame_latency as worker

    calls = []
    def refuse(*args):
        calls.append(args)
        raise ValueError('D6+X6 source required')
    monkeypatch.setattr(worker, 'build', refuse)
    assert worker.main(['measure', '--out', str(tmp_path), '--fly-toml', 'unused',
                        '--roots', 'unused', '--pass-label', 'test', '--arm', 'dx']) == 1
    row = json.loads((tmp_path / 'terminal_measure_test.json').read_text())
    assert len(calls) == 1 and row['result'] is None and row['policy'] is None
    assert row['error'] == dict(type='ValueError', message='D6+X6 source required')
    assert not (tmp_path / 'measure_test.jsonl').exists()


def test_latency_harvest_refuses_old_capture_source_before_creating_output(tmp_path, monkeypatch):
    import asyncio
    from scripts import exact_endgame_latency as worker
    monkeypatch.delattr(LeadCapture, 'capture_turn')
    with pytest.raises(RuntimeError, match='integrated follow-root capture source'):
        asyncio.run(worker.harvest(None, None, None, tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_every_captured_lead_replays_to_round_end_with_observed_ledger():
    # Snapshot equality alone does not exercise the continuation consumer.
    # Build an independent uninterrupted trajectory, preserving each seat's
    # actual observe-on-own-turn cadence (not an omniscient shared ledger).
    rnd = rebuild_round(EVENTS)
    ledgers = [RefusalLedger() for _ in range(4)]
    states, observations = [], {}
    for index, event in enumerate(PLAYS):
        seat = rnd.turn
        ledgers[seat].observe(rnd)
        observations[index] = normalized(vars(ledgers[seat]))
        rnd.play(seat, event['attempted'])
        states.append(fingerprint(rnd))
    assert rnd.phase == 'round_end'

    transitions = 0
    for row in packets():
        root, ledger = restore_with_ledger(row)
        owner = root.turn
        start = len(row['plays'])
        for index in range(start, len(PLAYS)):
            if root.turn == owner:
                ledger.observe(root)
                assert normalized(vars(ledger)) == observations[index]
            event = PLAYS[index]
            assert root.turn == event['seat']
            root.play(root.turn, event['attempted'])
            assert fingerprint(root) == states[index]
            transitions += 1
        # Includes final points, kitty settlement and winner in the full state.
        assert root.phase == 'round_end'
        assert fingerprint(root) == states[-1]
    assert transitions == sum(range(4, 65, 4)) == 544


def test_accepted_only_replay_is_rejected():
    row = next(r for r in packets() if any(e['attempted'] != e['accepted'] for e in r['plays']))
    for event in row['plays']:
        event['attempted'] = list(event['accepted'])
    with pytest.raises(ValueError, match='root state drift'):
        restore(row)


def test_alternative_lead_continuation_matches_independent_state_and_isolates_forks():
    from shengji.ai.heuristic import HeuristicBot

    # Exercise a different legal action, not another historical replay. No
    # network or counterfactual quality estimate: the heuristic only drives
    # the two equivalent engine states to settlement.
    row = next(row for row in packets()
               if row['plays'] and row['ledger']['refusals'])
    saved = copy.deepcopy(row)
    restored, ledger = restore_with_ledger(row)
    untouched, untouched_ledger = restore_with_ledger(row)
    independent = rebuild_round(EVENTS)
    observed = [RefusalLedger() for _ in range(4)]
    for event in PLAYS[:len(row['plays'])]:
        observed[independent.turn].observe(independent)
        independent.play(independent.turn, event['attempted'])
    owner = independent.turn
    observed[owner].observe(independent)
    assert normalized(vars(observed[owner])) == normalized(vars(ledger))
    # A singleton lead is always legal; choose one different from history.
    alternative = next([card] for card in sorted(set(independent.hands[owner]))
                       if [card] != row['decision']['played'])
    independent.play(owner, alternative)
    restored.play(owner, alternative)
    assert fingerprint(restored) == fingerprint(independent)
    driver = HeuristicBot()
    transitions = 1
    while independent.phase == 'play':
        seat = independent.turn
        if seat == owner:
            ledger.observe(restored)
            observed[owner].observe(independent)
            assert normalized(vars(ledger)) == normalized(vars(observed[owner]))
        cards = driver.decide_play(independent, seat)
        independent.play(seat, cards)
        restored.play(seat, cards)
        assert fingerprint(restored) == fingerprint(independent)
        transitions += 1
        assert transitions <= 100
    assert restored.phase == independent.phase == 'round_end'
    assert row == saved
    assert fingerprint(untouched) == row['root']
    assert normalized(vars(untouched_ledger)) == row['ledger']
    assert fingerprint(restore(row)) == row['root']


def test_capture_rejects_missing_prefix_and_foreign_ledger():
    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    ledger = RefusalLedger()
    ledger.key = ('wrong',)
    with pytest.raises(ValueError, match='another round'):
        capture.capture(rnd, ledger=ledger, decision={})
    for event in PLAYS[:4]:
        rnd.play(event['seat'], event['attempted'])
    with pytest.raises(ValueError, match='root state drift'):
        capture.capture(rnd, ledger=RefusalLedger(), decision={})
    with pytest.raises(ValueError, match='immediately after bury'):
        LeadCapture(rnd)


def test_accepted_card_corruption_is_rejected():
    row = next(r for r in packets() if r['plays'])
    row['plays'][0]['accepted'] = ['BJ']
    with pytest.raises(ValueError, match='accepted cards drift'):
        restore(row)


def test_ledger_corruption_is_rejected_by_consumer():
    row = next(r for r in packets() if r['ledger']['refusals'])
    bad = copy.deepcopy(row)
    bad['ledger']['key'] = ['wrong']
    with pytest.raises(ValueError, match='another round'):
        restore_with_ledger(bad)
    bad = copy.deepcopy(row)
    bad['ledger']['refusals'][0]['trick_index'] = 10000
    with pytest.raises(ValueError, match='unsupported'):
        restore_with_ledger(bad)


def test_served_search_record_to_capture_and_restored_engine():
    # Real served wrapper/search/record producer; two worlds and stub network.
    from test_pv_admission_rules import served
    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    bot = served(admission_diversity=True, refusal_constraints=True,
                 tiebreak_points=True, lead_anchor=True, doomed_throw_swap=True)
    cards = bot.decide_play(rnd, rnd.turn)
    record = copy.deepcopy(bot.last_decision_record)
    assert record['work_complete'] and len(record['admitted']) > 1
    ledger_before = normalized(vars(bot._refusals))
    packet = capture.capture(rnd, ledger=bot._refusals, decision=record)
    assert normalized(vars(bot._refusals)) == ledger_before
    assert bot.last_decision_record == record
    packet = json.loads(json.dumps(packet))
    assert packet['decision'] == normalized(record)
    root, ledger = restore_with_ledger(packet)
    assert ledger.observe(root) == bot._refusals.refusals
    root.play(root.turn, cards)
    rnd.play(rnd.turn, cards)
    assert fingerprint(root) == fingerprint(rnd)
    # Subsequent producer mutations must not rewrite the saved decision.
    bot.last_decision_record['admitted'].clear()
    assert packet['decision']['admitted']
