import copy
import json
import time
from pathlib import Path

import pytest

from shengji.train.lead_root_capture import (
    LeadCapture, fingerprint, observe_exact_follow, restore, restore_with_ledger,
    restore_exact_stage, normalized,
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


def _observed_follow_bot():
    """Build the real PV search wrapper used by the exact-follow fixture."""
    import numpy as np

    from shengji.train import pv_search_policy as pv
    from shengji.ai.heuristic import HeuristicBot
    from shengji.harvest.legal import enumerate_legal
    from test_pv_admission_rules import predict, ZeroEvaluator

    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    ledgers = [RefusalLedger() for _ in range(4)]
    driver = HeuristicBot()
    while not (rnd.trick.plays and max(map(len, rnd.hands)) <= 3):
        seat = rnd.turn
        ledgers[seat].observe(rnd)
        attempted = driver.decide_play(rnd, seat)
        rnd.play(seat, attempted)
        capture.committed(rnd, seat, attempted)
    seat = rnd.turn
    anchor = HeuristicBot().decide_play(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=4000, must_include=[anchor])
    preferred = next(list(action) for action in legal.actions
                     if list(action) != list(anchor))
    bot = pv.PVSearchBot(
        predict, evaluator=ZeroEvaluator(), version=2,
        config=pv.PVSearchConfig(
            checkpoint_sha256='f' * 64, worlds=2, candidates=8, cap=4000,
            exact_follow=True, exact_follow_max_nodes=10_000),
        checkpoint='/dev/null', seed=7)
    worlds = [(copy.deepcopy(rnd.hands), list(rnd.buried)) for _ in range(2)]
    bot._worlds = lambda *args: (worlds, 2)
    bot.scores = lambda r, s, actions, w: np.zeros((len(w), len(actions)))
    bot._value_means = lambda r, s, actions, w, check: (
        np.asarray([1.0 if a == preferred else 0.0 for a in actions]), 1)
    bot._refusals = ledgers[rnd.turn]
    return bot, rnd, capture, anchor


def _observed_lead_bot(deep=False):
    """Build a real PV bot at a small lead root for lead-hook probes."""
    import numpy as np

    from shengji.train import pv_search_policy as pv
    from shengji.ai.heuristic import HeuristicBot
    from shengji.harvest.legal import enumerate_legal
    from test_pv_admission_rules import predict, ZeroEvaluator

    rnd = rebuild_round(EVENTS)
    capture = LeadCapture(rnd)
    ledgers = [RefusalLedger() for _ in range(4)]
    driver = HeuristicBot()
    while rnd.phase == 'play' and (rnd.trick.plays or max(map(len, rnd.hands)) > 3):
        seat = rnd.turn
        ledgers[seat].observe(rnd)
        attempted = driver.decide_play(rnd, seat)
        rnd.play(seat, attempted)
        capture.committed(rnd, seat, attempted)
    seat = rnd.turn
    ledgers[seat].observe(rnd)
    anchor = HeuristicBot().decide_play(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=4000, must_include=[anchor])
    preferred = next(list(action) for action in legal.actions
                     if list(action) != list(anchor))
    config = pv.PVSearchConfig(
        checkpoint_sha256='f' * 64, worlds=2, candidates=8, cap=4000,
        exact_lead_endgame=True, exact_deep_cards=4 if deep else 0,
        exact_lead_max_seconds=30.0,
        exact_deep_max_nodes=10_000 if deep else 50_000_000)
    bot = pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2,
                         config=config, checkpoint='/dev/null', seed=7)
    worlds = [(copy.deepcopy(rnd.hands), list(rnd.buried)) for _ in range(2)]
    bot._worlds = lambda *args: (worlds, 2)
    bot.scores = lambda r, s, actions, w: np.zeros((len(w), len(actions)))
    bot._value_means = lambda r, s, actions, w, check: (
        np.asarray([1.0 if a == preferred else 0.0 for a in actions]), 1)
    bot._refusals = ledgers[seat]
    return bot, rnd, capture, anchor


def test_observe_exact_follow_captures_real_search_and_json_replay():
    from shengji.train.pv_exact_follow import rerank_follow

    unobserved, root, _, anchor = _observed_follow_bot()
    expected = unobserved._search(copy.deepcopy(root), root.turn, anchor,
                                  time.perf_counter())

    observed, root, capture, anchor = _observed_follow_bot()
    with observe_exact_follow(observed, capture) as rows:
        actual = observed._search(root, root.turn, anchor, time.perf_counter())
    assert actual == expected
    assert len(rows) == 1 and rows[0]['stage'] == 'result'
    row = json.loads(json.dumps(rows[0]))
    assert row['input']['baseline_index'] != 0
    assert row['config']['max_nodes'] == 10_000

    replayed_root, _, admitted, worlds, baseline, _ = restore_exact_stage(row['input'])
    replayed = rerank_follow(
        replayed_root, row['input']['seat'], admitted, worlds,
        baseline_index=baseline, **row['config'])
    assert normalized(replayed) == row['result']
    assert row['result']['winner'] == replayed.winner


def test_observe_exact_follow_restores_on_exception_and_rejects_nested():
    from shengji.train import pv_exact_follow

    bot, root, capture, anchor = _observed_follow_bot()
    rows = None
    original = pv_exact_follow.rerank_follow
    with pytest.raises(RuntimeError, match='nested exact-follow observer'):
        with observe_exact_follow(bot, capture) as rows:
            with observe_exact_follow(bot, capture):
                pass
    assert pv_exact_follow.rerank_follow is original

    def fail(*args, **kwargs):
        raise RuntimeError('fixture failure')

    pv_exact_follow.rerank_follow = fail
    try:
        with observe_exact_follow(bot, capture) as rows:
            bot._search(root, root.turn, anchor, time.perf_counter())
        assert rows[-1]['result'] == {'exception': 'RuntimeError'}
        assert pv_exact_follow.rerank_follow is fail
        assert '_search' not in vars(bot)
    finally:
        pv_exact_follow.rerank_follow = original

    class FailingCapture:
        def capture_exact_stage(self, *args, **kwargs):
            raise ValueError('capture failure')

    with pytest.raises(ValueError, match='capture failure'):
        with observe_exact_follow(bot, FailingCapture()):
            bot._search(root, root.turn, anchor, time.perf_counter())
    assert pv_exact_follow.rerank_follow is original
    assert '_search' not in vars(bot)


@pytest.mark.parametrize('mutation,match', [
    (lambda p: p['admitted'].append(list(p['admitted'][0])), 'duplicate admitted action'),
    (lambda p: p['admitted'][0].append('not-in-hand'), 'action cards outside acting hand'),
])
def test_exact_stage_rejects_action_multiset_corruption(mutation, match):
    _, packet, _ = _exact_follow_capture()
    bad = copy.deepcopy(packet)
    mutation(bad)
    with pytest.raises(ValueError, match=match):
        restore_exact_stage(bad)


@pytest.mark.parametrize('deep', [False, True])
def test_observe_exact_lead_real_search_and_json_replay(deep):
    from shengji.train.lead_root_capture import observe_exact_lead, replay_exact_lead

    plain, plain_root, _, plain_anchor = _observed_lead_bot(deep)
    expected = plain._search(plain_root, plain_root.turn, plain_anchor, time.perf_counter())
    bot, root, capture, anchor = _observed_lead_bot(deep)
    with observe_exact_lead(bot, capture) as rows:
        actual = bot._search(root, root.turn, anchor, time.perf_counter())
    assert actual == expected
    assert len(rows) == 1
    row = json.loads(json.dumps(rows[0]))
    assert row['leaf_fn_required_for_replay'] is True
    assert row['leaf_fn_source'] == 'caller-supplied'
    assert row['config']['solver'] == ('deep' if deep else 'shallow')
    replayed_means, replayed_stats = replay_exact_lead(row, bot._leaf)
    assert replayed_means.tolist() == row['result']['means']
    assert replayed_stats == row['result']['stats']
    assert row['input']['baseline_index'] >= 0
    assert row['baseline_played']


def test_exact_lead_ignores_direct_solver_calls_and_restores_methods():
    from shengji.train import pv_exact_endgame
    from shengji.harvest.legal import enumerate_legal
    from shengji.train.lead_root_capture import observe_exact_lead

    bot, root, capture, _ = _observed_lead_bot(False)
    actions = enumerate_legal(root, root.turn, cap=8).actions
    worlds, _ = bot._worlds(root, root.turn, actions)
    original_solver = pv_exact_endgame.exact_lead_means
    original_method = bot.__class__._exact_lead_decision
    with observe_exact_lead(bot, capture) as rows:
        pv_exact_endgame.exact_lead_means(root, root.turn, actions[:1], worlds, bot._leaf, None,
                                        max_nodes=1000)
    assert rows == []
    assert pv_exact_endgame.exact_lead_means is original_solver
    assert '_exact_lead_decision' not in vars(bot)
    assert bot.__class__._exact_lead_decision is original_method


def test_exact_lead_exception_and_cross_observer_nesting_restore(monkeypatch):
    from shengji.train import pv_exact_endgame
    from shengji.train.lead_root_capture import observe_exact_follow, observe_exact_lead

    bot, root, capture, anchor = _observed_lead_bot(False)
    original = pv_exact_endgame.exact_lead_means

    def fail(*args, **kwargs):
        raise RuntimeError('lead fixture failure')

    monkeypatch.setattr(pv_exact_endgame, 'exact_lead_means', fail)
    with observe_exact_lead(bot, capture) as rows:
        bot._search(root, root.turn, anchor, time.perf_counter())
    assert rows[-1]['result'] == {'exception': 'RuntimeError'}
    assert pv_exact_endgame.exact_lead_means is fail
    monkeypatch.setattr(pv_exact_endgame, 'exact_lead_means', original)

    with observe_exact_lead(bot, capture):
        with pytest.raises(RuntimeError, match='nested exact-follow observer'):
            with observe_exact_follow(bot, capture):
                pass


def test_exact_lead_baseline_override_is_not_required_in_ballot():
    import numpy as np
    from shengji.train.lead_root_capture import observe_exact_lead
    from shengji.harvest.legal import enumerate_legal

    bot, root, capture, _ = _observed_lead_bot()
    actions = enumerate_legal(root, root.turn, cap=4000).actions
    assert len(actions) >= 3
    admitted = [list(a) for a in actions[:2]]
    played = list(actions[2])
    worlds, _ = bot._worlds(root, root.turn, admitted)
    base = (np.zeros(2), 1, 1, played, 1)
    with observe_exact_lead(bot, capture) as rows:
        bot._exact_lead_decision(root, root.turn, admitted, worlds,
                                 time.perf_counter(), lambda: None, np.zeros(2), base)
    assert len(rows) == 1
    assert rows[0]['input']['baseline_index'] == 1
    assert rows[0]['input']['actual_action'] is None
    assert rows[0]['baseline_played'] == played
    assert played not in admitted
