"""Collector-only throw forecasts from the decision's own sampled worlds.

No new sampling or policy changes. Forecasting runs after decide_play, outside
its deadline. The public-risk proxy uses the union of unseen cards, not hidden
hands; it is conservative and does not assert a feasible opponent allocation.
"""
from collections import Counter
from contextlib import contextmanager

from shengji.engine.cards import make_deck
from shengji.engine.combos import decompose
from shengji.engine.legal import validate_lead


@contextmanager
def observe_worlds(bot):
    """Keep references to completed draws without copying inside the timed call."""
    draws = []
    original = bot._worlds
    had_own = '_worlds' in vars(bot)
    own = vars(bot).get('_worlds')

    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        draws.append(result[0])
        return result

    bot._worlds = observed
    try:
        yield draws
    finally:
        if had_own:
            bot._worlds = own
        else:
            del bot._worlds


def forecast(rnd, seat, attempted, draws, record, expected_worlds):
    """Forecast only; never consult other true hands or the hidden kitty."""
    if rnd.phase != 'play' or rnd.trick.plays or rnd.turn != seat:
        raise ValueError('not a lead turn')
    hand = list(rnd.hands[seat])
    validate_lead(list(attempted), hand, [], rnd.ordering)
    row = dict(schema='throw-calibration-v1', attempted=list(attempted),
               is_throw=len(decompose(list(attempted), rnd.ordering).components) > 1,
               predicted_success=None, worlds=0, unavailable=None,
               extra_draws=max(0, len(draws) - 1))
    if not row['is_throw']:
        return row
    seen = Counter(hand)
    for trick in rnd.history:
        for play in trick.plays:
            seen.update(play.cards)
    if seat == rnd.banker:
        seen.update(rnd.buried)
    unseen = list((Counter(make_deck()) - seen).elements())
    _, message = validate_lead(list(attempted), hand, [unseen], rnd.ordering)
    row['unseen_union_risky'] = message is not None
    if not record or record.get('schema') != 'pv-search-decision-v1' or record.get('work_complete') is not True:
        row['unavailable'] = 'incomplete_decision'
        return row
    if sorted(record.get('played', [])) != sorted(attempted):
        raise ValueError('decision action drift')
    if not draws or len(draws[0]) != expected_worlds or expected_worlds <= 0:
        row['unavailable'] = 'missing_or_short_base_draw'
        return row
    successes = 0
    for hands, _ in draws[0]:
        if len(hands) != 4 or Counter(hands[seat]) != Counter(hand):
            raise ValueError('sampled hand drift')
        _, message = validate_lead(list(attempted), hand,
                                   [list(hands[s]) for s in range(4) if s != seat], rnd.ordering)
        successes += message is None
    row.update(worlds=len(draws[0]), predicted_success=successes / len(draws[0]))
    return row


def committed(row, accepted):
    """Bind the forecast to the actual engine transition, including failed throws."""
    if not accepted or Counter(accepted) - Counter(row['attempted']):
        raise ValueError('accepted cards are not a nonempty subset of attempted')
    return dict(row, accepted=list(accepted), succeeded=Counter(accepted) == Counter(row['attempted']))
