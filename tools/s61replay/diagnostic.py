"""Consume a validated prefix pair through the served continuation path."""
from collections import Counter
from copy import deepcopy
import math

from capture import capture_lead, compare_captured
from extract import LOCATOR, project_pair
from served import endpoint_evaluator, replay_served_prefix, reply_factory


def diagnose_admission(rows, make_bot, *, policy_identity, seed, locator=LOCATOR):
    """Price an omitted lead with the flat served scorer, without continuations.

    Reproducing every recorded ballot value is required before interpreting a
    new action. Greedy leaf caches and deadlines need a separate replay contract.
    """
    if not policy_identity or type(seed) is not int:
        raise ValueError('bound policy identity and diagnostic seed required')
    prefix = project_pair(rows, locator)
    seat = locator['seat']
    row = prefix['rows'][1 - seat % 2]
    bot, root, witness = replay_served_prefix(row, make_bot, seat=seat)
    if getattr(bot, 'leaf_greedy_finish', False):
        raise ValueError('flat leaf scorer required; greedy replay unsupported')
    captured = capture_lead(bot, root)
    if Counter(captured['played']) != Counter(locator['release46_action']):
        raise ValueError('replayed served choice differs from saved locator')
    scorer = make_bot(seed=seed)
    if scorer is bot or getattr(scorer, 'leaf_greedy_finish', False):
        raise ValueError('separate flat leaf scorer required')
    ballot = captured['served_ballot']
    alternative = locator['exploiter_action']
    from replay import branch_action
    _, accepted = branch_action(root, alternative)
    worlds = [(deepcopy(w.hands), list(w.buried)) for w in captured['worlds']]
    recorded = captured['served_record']['value_means']

    def score(actions):
        means, _ = scorer._value_means(deepcopy(root), seat, actions, deepcopy(worlds))
        values = [float(v) for v in means]
        if len(values) != len(actions) or not all(math.isfinite(v) for v in values):
            raise ValueError('invalid flat leaf scores')
        return values

    def parity(values):
        if len(recorded) != len(ballot) or any(
                not math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-8)
                for a, b in zip(recorded, values)):
            raise ValueError('recorded ballot value parity failed')

    original = score(ballot)
    parity(original)
    in_ballot = next((i for i, a in enumerate(ballot)
                      if Counter(a) == Counter(alternative)), None)
    expanded = ballot if in_ballot is not None else [*ballot, alternative]
    values = score(expanded)
    parity(values[:len(ballot)])
    alternative_index = in_ballot if in_ballot is not None else len(ballot)
    return dict(schema='s61-flat-admission-diagnostic-v1', locator=prefix['locator'],
                replay=witness, policy_identity=policy_identity,
                served_record=captured['served_record'], worlds=len(worlds),
                alternative=accepted, in_served_ballot=in_ballot is not None,
                actions=expanded, value_means=values, ballot_parity=True,
                alternative_delta_over_ballot_max=values[alternative_index] - max(original),
                claim='flat value ranking diagnostic; no selection or gameplay strength claim')


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
