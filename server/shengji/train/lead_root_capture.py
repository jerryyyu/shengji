"""DEV collector adapter: JSON engine roots, not exact bot/RNG replay.

Start after bury, call committed after EVERY play, capture before the lead's
analysis mutates bot diagnostic state. Full hidden deal stays DEV-only; never
feed this payload directly to a policy. No inference or file IO in this module.
"""
import copy
import json
from collections import Counter
from dataclasses import asdict, is_dataclass

from shengji.harvest.rebuild import round_from_setup, setup_from_round
from shengji.ai.refusal import Refusal, RefusalLedger, on_record


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
