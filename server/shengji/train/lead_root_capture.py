"""DEV collector adapter: JSON engine roots, not exact bot/RNG replay.

Start after bury, call committed after EVERY play, capture before the lead's
analysis mutates bot diagnostic state. Full hidden deal stays DEV-only; never
feed this payload directly to a policy. No inference or file IO in this module.
"""
import copy
import json
from collections import Counter
from dataclasses import asdict, is_dataclass
from contextlib import contextmanager

from shengji.harvest.rebuild import round_from_setup, setup_from_round
from shengji.ai.refusal import Refusal, RefusalLedger, on_record


def finish_eligible(rnd, seat):
    hand = rnd.hands[seat]
    return (rnd.phase == 'play' and not rnd.trick.plays and 2 <= len(hand) <= 8
            and len({rnd.ordering.eff_suit(c) for c in hand}) == 1)


@contextmanager
def observe_finish_pool(bot, rnd, seat):
    """Observe the actual returned legal pool; never rerun enumeration/inference.

    Unknown if the decision expires before returning a pool. This instrumentation
    is collector-only and neither changes the factory class nor supplies actions.
    """
    evidence = {'eligible': finish_eligible(rnd, seat), 'present': None}
    if not evidence['eligible'] or not hasattr(bot, '_legal'):
        yield evidence
        return
    hand = tuple(sorted(rnd.hands[seat]))
    original = bot._legal
    had_own = '_legal' in vars(bot)
    own = vars(bot).get('_legal')

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        evidence.update(present=any(tuple(sorted(a)) == hand for a in result.actions),
                        complete=result.complete, count=result.count)
        return result

    bot._legal = observed
    try:
        yield evidence
    finally:
        if had_own:
            bot._legal = own
        else:
            del bot._legal


def classify_finish_lead(row):
    """Engine-only evidence, not counterfactual value or strength attribution.

    True-deal refusal is hindsight, not information available to the bot. Missing
    capture/admission fields remain unknown, including budget-fallback records.
    """
    from shengji.harvest.legal import forced_lead
    rnd, _ = restore_with_ledger(row['replay'])
    if rnd.phase != 'play' or rnd.trick.plays or rnd.turn != row['seat']:
        raise ValueError('not the captured lead turn')
    rec = row['replay'].get('decision') or {}
    attempted = row.get('attempted', rec.get('played'))
    if not attempted or (rec.get('played') is not None
                         and sorted(attempted) != sorted(rec['played'])):
        raise ValueError('attempted action drift')
    eligible = finish_eligible(rnd, rnd.turn)
    pool = row.get('finish_pool')
    if pool is not None and pool.get('eligible') != eligible:
        raise ValueError('finish eligibility drift')
    present = None if pool is None else pool.get('present')
    if present is not None and type(present) is not bool:
        raise ValueError('invalid pool presence')
    hand = sorted(rnd.hands[rnd.turn])
    admitted = (rec.get('admitted') if rec.get('schema') == 'pv-search-decision-v1'
                and rec.get('work_complete') is True else None)
    in_admitted = (any(sorted(a) == hand for a in admitted)
                   if eligible and isinstance(admitted, list) else None)
    if present is False and in_admitted is True:
        raise ValueError('admitted finish absent from captured pool')
    forced = forced_lead(rnd, rnd.turn, hand) if eligible else None
    return dict(eligible=eligible, hand_size=len(hand),
                decision_schema=rec.get('schema'), work_complete=rec.get('work_complete'),
                pool_present=present if eligible else None, admitted=in_admitted,
                whole_hand_played=sorted(attempted) == hand,
                whole_hand_refused_true_deal=(forced is not None) if eligible else None,
                forced_component=forced,
                ranking_or_horizon_error=None)


def normalized(obj):
    def default(value):
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        return vars(value)
    return json.loads(json.dumps(obj, default=default, sort_keys=True))


def fingerprint(rnd):
    state = dict(vars(rnd))
    # Ordering memoization is execution history, not game state.
    state['ordering'] = {k: v for k, v in vars(rnd.ordering).items()
                         if not k.startswith('_')}
    return normalized(state)


def restore(packet):
    if packet['schema'] != 'lead-root-capture-dev-v1':
        raise ValueError('unknown schema')
    rnd = round_from_setup(packet['deck'], packet['setup'])
    rnd.first_round = packet['first_round']
    for event in packet['plays']:
        before = Counter(rnd.hands[event['seat']])
        rnd.play(event['seat'], event['attempted'])
        if before - Counter(rnd.hands[event['seat']]) != Counter(event['accepted']):
            raise ValueError('accepted cards drift')
    if fingerprint(rnd) != packet['root']:
        raise ValueError('root state drift')
    return rnd


def restore_with_ledger(packet):
    rnd = restore(packet)
    saved = packet['ledger']
    ledger = RefusalLedger()
    ledger.key = tuple(saved['key']) if saved['key'] is not None else None
    if ledger.key is not None and ledger.key != tuple(rnd.deck):
        raise ValueError('ledger belongs to another round')
    ledger.refusals = [Refusal(seat=r['seat'], attempted=tuple(r['attempted']),
                              forced=tuple(r['forced']), trick_index=r['trick_index'])
                       for r in saved['refusals']]
    if ledger.refusals and ledger.key is None:
        raise ValueError('nonempty unbound ledger')
    if not all(on_record(rnd, r) for r in ledger.refusals):
        raise ValueError('ledger unsupported by replay')
    return rnd, ledger


def _stage_worlds(rnd, worlds, seat):
    """Validate and copy the sampled exact-stage inputs at a captured root."""
    if type(seat) is not int or not 0 <= seat < 4 or rnd.turn != seat:
        raise ValueError('exact stage acting seat drift')
    if not isinstance(worlds, (list, tuple)) or not worlds:
        raise ValueError('exact stage requires sampled worlds')
    expected = Counter(card for hand in rnd.hands for card in hand)
    expected += Counter(rnd.buried)
    shape = [len(hand) for hand in rnd.hands]
    copied = []
    for world in worlds:
        if not isinstance(world, (list, tuple)) or len(world) != 2:
            raise ValueError('malformed sampled world')
        hands, buried = world
        if (not isinstance(hands, (list, tuple)) or len(hands) != 4
                or not isinstance(buried, (list, tuple))):
            raise ValueError('malformed sampled world')
        if [len(hand) for hand in hands] != shape:
            raise ValueError('sampled world changes public hand sizes')
        if Counter(card for hand in hands for card in hand) + Counter(buried) != expected:
            raise ValueError('sampled world changes card multiset')
        if Counter(hands[seat]) != Counter(rnd.hands[seat]):
            raise ValueError('sampled world changes the acting hand')
        copied.append([copy.deepcopy([list(hand) for hand in hands]), list(buried)])
    return copied


def restore_exact_stage(packet):
    """Restore a DEV exact-stage packet without model or RNG reconstruction.

    The returned stage inputs are copies.  ``worlds`` are sampled hidden-world
    inputs, not a claim about the true deal; the replay is the only engine root.
    """
    if packet.get('schema') != 'exact-stage-capture-dev-v1':
        raise ValueError('unknown exact-stage schema')
    replay = packet.get('replay')
    if not isinstance(replay, dict):
        raise ValueError('exact stage replay is missing')
    rnd, ledger = restore_with_ledger(replay)
    if rnd.phase != 'play' or rnd.trick is None:
        raise ValueError('exact stage requires a play root')
    seat = packet.get('seat')
    if type(seat) is not int or rnd.turn != seat:
        raise ValueError('exact stage acting seat drift')
    admitted = packet.get('admitted')
    if (not isinstance(admitted, list) or not admitted
            or any(not isinstance(action, list) or not action for action in admitted)):
        raise ValueError('malformed admitted actions')
    baseline = packet.get('baseline_index')
    if type(baseline) is not int or not 0 <= baseline < len(admitted):
        raise ValueError('baseline index is outside the ballot')
    actual = packet.get('actual_action')
    if actual is not None and (not isinstance(actual, list) or actual not in admitted):
        raise ValueError('actual action is outside the ballot')
    worlds = _stage_worlds(rnd, packet.get('worlds'), seat)
    return rnd, ledger, copy.deepcopy(admitted), worlds, baseline, copy.deepcopy(actual)


class LeadCapture:
    def __init__(self, rnd):
        if rnd.phase != 'play' or rnd.history or rnd.trick.plays:
            raise ValueError('capture must start immediately after bury')
        setup = setup_from_round(rnd)
        setup['buried'] = list(rnd.buried)
        setup['declarations'] = ([{'seat': rnd.declaration['seat'],
                                  'cards': list(rnd.declaration['cards'])}]
                                 if rnd.declaration else [])
        setup['passed'] = sorted(rnd.passed)
        self.packet = dict(schema='lead-root-capture-dev-v1', deck=list(rnd.deck),
                           setup=setup, first_round=rnd.first_round, plays=[],
                           root=fingerprint(rnd))
        # Refuse unsupported setup compression rather than save unreplayable roots.
        restore(self.packet)

    def committed(self, rnd, seat, attempted):
        trick = rnd.trick if rnd.trick and rnd.trick.plays else rnd.last_trick
        play = trick.plays[-1]
        if play.seat != seat:
            raise ValueError('committed seat mismatch')
        self.packet['plays'].append(dict(seat=seat, attempted=list(attempted),
                                         accepted=list(play.cards)))

    def capture(self, rnd, *, ledger, decision):
        if rnd.phase != 'play' or rnd.trick.plays:
            raise ValueError('not a lead root')
        if ledger.key is not None and tuple(rnd.deck) != ledger.key:
            raise ValueError('ledger belongs to another round')
        packet = copy.deepcopy(self.packet)
        packet['root'] = fingerprint(rnd)
        packet['ledger'] = normalized(vars(ledger))
        packet['decision'] = normalized(decision)
        packet['limits'] = ['Full hidden deal: DEV-only, not policy input.',
                            'Exact engine state and observed ledger only; no bot RNG restoration.',
                            'No claim of historical provenance or playing strength.']
        restore_with_ledger(packet)
        return packet

    def capture_exact_stage(self, rnd, *, ledger, admitted, worlds,
                            baseline_index=0, actual_action=None):
        """Capture a play root and its immutable exact-stage inputs.

        This is opt-in collector plumbing.  The caller commits every observed
        play as usual, then passes the exact ballot/worlds sent to
        the exact stage; no model, RNG, or serving path is reconstructed.
        """
        if rnd.phase != 'play' or rnd.trick is None:
            raise ValueError('exact stage requires a play root')
        replay = copy.deepcopy(self.packet)
        replay['root'] = fingerprint(rnd)
        replay['ledger'] = normalized(vars(ledger))
        replay['limits'] = [
            'Full hidden deal: DEV-only, not policy input.',
            'Exact engine state and observed ledger only; no bot RNG restoration.',
            'No claim of historical provenance or playing strength.',
        ]
        replay['schema'] = 'lead-root-capture-dev-v1'
        restore_with_ledger(replay)
        admitted_copy = normalized(admitted)
        if (not isinstance(admitted_copy, list) or not admitted_copy
                or any(not isinstance(action, list) or not action
                       for action in admitted_copy)):
            raise ValueError('malformed admitted actions')
        if type(baseline_index) is not int or not 0 <= baseline_index < len(admitted_copy):
            raise ValueError('baseline index is outside the ballot')
        if actual_action is not None and actual_action not in admitted_copy:
            raise ValueError('actual action is outside the ballot')
        packet = dict(schema='exact-stage-capture-dev-v1', replay=replay,
                      seat=rnd.turn, admitted=admitted_copy,
                      worlds=normalized(worlds), baseline_index=baseline_index,
                      actual_action=normalized(actual_action),
                      limits=['Sampled worlds are exact-stage inputs, not true-deal labels.',
                              'No model or RNG reconstruction; no serving changes.'])
        restore_exact_stage(packet)
        return packet
