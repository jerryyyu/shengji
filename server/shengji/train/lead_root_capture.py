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
def observe_throw_verdicts(bot):
    """Collector-only: observe existing sampled-engine verdicts, never rerun them.

    An empty list means no completed verdict call, not zero refusal probability.
    A budget exception records no partial counts. Restore instance overrides too.
    """
    evidence = []
    if not hasattr(bot, '_doomed_verdicts'):
        yield evidence
        return
    original = bot._doomed_verdicts
    had_own = '_doomed_verdicts' in vars(bot)
    own = vars(bot).get('_doomed_verdicts')

    def observed(rnd, seat, action, worlds, *args, **kwargs):
        result = original(rnd, seat, action, worlds, *args, **kwargs)
        refused, variants = result
        evidence.append(dict(action=sorted(action), worlds=len(worlds),
                             refused=refused, forced_variants=len(variants)))
        return result

    bot._doomed_verdicts = observed
    try:
        yield evidence
    finally:
        if had_own:
            bot._doomed_verdicts = own
        else:
            del bot._doomed_verdicts


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
    sampled = []
    for call in row.get('throw_verdicts') or []:
        w, r, v = (call[k] for k in ('worlds', 'refused', 'forced_variants'))
        if (any(type(n) is not int for n in (w, r, v)) or not 0 <= v <= r <= w
                or w < 1 or (r > 0 and v == 0)):
            raise ValueError('invalid sampled throw verdict counts')
        if sorted(call['action']) == sorted(attempted):
            sampled.append(dict(worlds=w, refused=r, forced_variants=v))
    return dict(eligible=eligible, hand_size=len(hand),
                decision_schema=rec.get('schema'), work_complete=rec.get('work_complete'),
                pool_present=present if eligible else None, admitted=in_admitted,
                whole_hand_played=sorted(attempted) == hand,
                whole_hand_refused_true_deal=(forced is not None) if eligible else None,
                forced_component=forced,
                sampled_throw_verdicts=sampled or None,
                reselection_abandoned=rec.get('doomed_throw_reselect_abandoned'),
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
