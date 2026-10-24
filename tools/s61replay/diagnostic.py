"""Consume a validated prefix pair through the served continuation path."""
from collections import Counter

from capture import capture_lead, compare_captured
from extract import LOCATOR, project_pair
from served import endpoint_evaluator, replay_served_prefix, reply_factory


def diagnose_pair(rows, make_bot, *, policy_identity, seed, tricks=2, locator=LOCATOR):
    """Reproduce the saved served choice before comparing the named alternative.

    Artifact access and run authorization belong to the caller. All worlds from
    the reproduced decision are retained; the endpoint uses a separate bot.
    """
    if not policy_identity or type(seed) is not int:
        raise ValueError('bound policy identity and diagnostic seed required')
    prefix = project_pair(rows, locator)
    seat = locator['seat']
    served_row = prefix['rows'][1 - seat % 2]
    bot, root, replay_witness = replay_served_prefix(served_row, make_bot, seat=seat)
    captured = capture_lead(bot, root)
    if Counter(captured['played']) != Counter(locator['release46_action']):
        raise ValueError('replayed served choice differs from saved locator')
    endpoint_bot = make_bot(seed=seed)
    if endpoint_bot is bot:
        raise ValueError('endpoint requires a separate bot')
    result = compare_captured(captured, [locator['exploiter_action']], tricks=tricks,
        reply_factory=reply_factory(make_bot), evaluate=endpoint_evaluator(endpoint_bot),
        seed=seed, reply_identity=policy_identity, evaluator_identity=policy_identity)
    return dict(schema='s61-served-lead-diagnostic-v1', locator=prefix['locator'],
                replay=replay_witness, mirror_witness=prefix['witness'],
                served_record=captured['served_record'], continuation=result)
