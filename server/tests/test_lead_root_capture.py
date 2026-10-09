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
