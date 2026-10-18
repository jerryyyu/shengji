import copy
import json
from pathlib import Path

import pytest

from shengji.train.lead_root_capture import (
    LeadCapture, fingerprint, restore, restore_with_ledger, restore_exact_stage,
    normalized,
)
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


def _exact_follow_capture(hand_cap=2, solve=True):
    """A real partial-trick root with a small legal endgame continuation."""
    from shengji.ai.endgame import exhaustive_legal_actions
    from shengji.ai.heuristic import HeuristicBot
    from shengji.train.pv_exact_follow import rerank_follow

    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    ledgers = [RefusalLedger() for _ in range(4)]
    driver = HeuristicBot()
    while not (rnd.trick.plays and max(map(len, rnd.hands)) <= hand_cap):
        seat = rnd.turn
        ledgers[seat].observe(rnd)
        attempted = driver.decide_play(rnd, seat)
        rnd.play(seat, attempted)
        capture.committed(rnd, seat, attempted)
    seat = rnd.turn
    ledgers[seat].observe(rnd)
    admitted = exhaustive_legal_actions(rnd, seat, max_hand_cards=max(hand_cap, 4))
    worlds = [([list(hand) for hand in rnd.hands], list(rnd.buried))]
    original = (rerank_follow(rnd, seat, admitted, worlds, max_nodes=10000)
                if solve else None)
    packet = capture.capture_exact_stage(
        rnd, ledger=ledgers[seat], admitted=admitted, worlds=worlds,
        baseline_index=0, actual_action=admitted[0])
    return rnd, packet, original


def test_exact_stage_capture_replays_follow_root_and_copies_inputs():
    from shengji.train.pv_exact_follow import rerank_follow

    original_root, packet, original = _exact_follow_capture()
    serialized = json.loads(json.dumps(packet))
    restored, ledger, admitted, worlds, baseline, actual = restore_exact_stage(serialized)
    assert restored.trick.plays and restored.turn == original_root.turn
    replayed = rerank_follow(restored, restored.turn, admitted, worlds,
                             baseline_index=baseline, max_nodes=10000)
    assert replayed == original
    assert actual == admitted[0]
    assert normalized(vars(ledger)) == serialized['replay']['ledger']
    admitted[0].append('mutated')
    worlds[0][0][0].append('mutated')
    assert serialized['admitted'][0] != admitted[0]
    assert 'mutated' not in serialized['worlds'][0][0][0]


def test_exact_stage_capture_replays_an_eight_card_follow_root_without_solving():
    original_root, packet, _ = _exact_follow_capture(hand_cap=8, solve=False)
    assert max(map(len, original_root.hands)) <= 8
    restored, _, _, worlds, _, _ = restore_exact_stage(json.loads(json.dumps(packet)))
    assert fingerprint(restored) == fingerprint(original_root)
    assert worlds and [len(hand) for hand in worlds[0][0]] == [len(hand) for hand in original_root.hands]


def _swap_opponent_cards(packet):
    seat = packet['seat']
    hands = packet['worlds'][0][0]
    others = [s for s in range(4) if s != seat]
    left, right = others[:2]
    hands[left][0], hands[right][0] = hands[right][0], hands[left][0]


def _swap_acting_card(packet):
    seat = packet['seat']
    hands = packet['worlds'][0][0]
    other = next(s for s in range(4) if s != seat)
    hands[seat][0], hands[other][0] = hands[other][0], hands[seat][0]


def test_exact_stage_keeps_a_nontrivial_hidden_world_swap():
    _, packet, _ = _exact_follow_capture()
    swapped = json.loads(json.dumps(packet))
    original = copy.deepcopy(swapped['worlds'][0][0])
    _swap_opponent_cards(swapped)
    restored, _, _, worlds, _, _ = restore_exact_stage(swapped)
    assert fingerprint(restored) == packet['replay']['root']
    assert worlds[0][0] != original
    assert worlds[0][0][swapped['seat']] == original[swapped['seat']]


@pytest.mark.parametrize('mutation,match', [
    (lambda p: p['worlds'][0][0].__setitem__(0, ['C2']),
     'public hand sizes'),
    (lambda p: p.__setitem__('seat', (p['seat'] + 1) % 4), 'acting seat drift'),
    (lambda p: p.__setitem__('baseline_index', 99), 'baseline index'),
    (lambda p: p.__setitem__('baseline_index', True), 'baseline index'),
    (lambda p: p['worlds'][0][1].pop(), 'card multiset'),
    (_swap_acting_card, 'sampled world changes the acting hand'),
])
def test_exact_stage_restore_rejects_malformed_inputs(mutation, match):
    import copy

    _, packet, _ = _exact_follow_capture()
    bad = copy.deepcopy(packet)
    mutation(bad)
    with pytest.raises(ValueError, match=match):
        restore_exact_stage(bad)


def test_exact_stage_lead_capture_copies_producer_inputs():
    rnd = rebuild_round(EVENTS)
    collector = LeadCapture(rnd)
    ledger = RefusalLedger()
    ledger.observe(rnd)
    admitted = [[rnd.hands[rnd.turn][0]]]
    worlds = [[copy.deepcopy(rnd.hands), list(rnd.buried)]]
    packet = collector.capture_exact_stage(
        rnd, ledger=ledger, admitted=admitted, worlds=worlds)
    admitted[0].clear()
    worlds[0][0][0].clear()
    restored, _, ballot, sampled, baseline, _ = restore_exact_stage(
        json.loads(json.dumps(packet)))
    assert not restored.trick.plays
    assert fingerprint(restored) == fingerprint(rnd)
    assert ballot == [[rnd.hands[rnd.turn][0]]] and baseline == 0
    assert sampled[0][0] == rnd.hands
