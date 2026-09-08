"""Use the existing points-leaf consumer on an unchanged saved shortlist.

No registration, reranking, new gate, coefficient fitting or policy default.
This isolates leaf substitution from the historical leaf arm's narrower
production ballot. The caller must bind the checkpoint and reference data.
"""
from __future__ import annotations

import json

from .cwv_horizon_audit import _actions, _positive_int
from .leaf_policy import MCValueLeafSearch


def verify_sampling(saved, actual):
    """Compare logical sampling identity across live tuples and saved JSON."""
    for field in ('n_by_candidate', 'worlds', 'rng_state', 'report_seed'):
        left = json.dumps(saved[field], sort_keys=True, separators=(',', ':'), allow_nan=False)
        right = json.dumps(actual[field], sort_keys=True, separators=(',', ':'), allow_nan=False)
        if left != right:
            raise ValueError(f'leaf changed sampling identity: {field}')


class LastActorPointsLeaf:
    """Same global points target, but the producer's post-action viewpoint.

    Training rows encode the player who just acted, not the next mover.
    No sign flip: both wrappers predict final ATTACKER points.
    """
    def __init__(self, leaf):
        self.leaf = leaf
        self.kind = getattr(leaf, 'kind', 'audit-last-actor')
        self.points_clamp = getattr(leaf, 'points_clamp', None)

    def final_attacker_points(self, clone, _mover):
        plays = clone.trick.plays if clone.trick is not None else []
        if not plays and clone.history:
            plays = clone.history[-1].plays
        if not plays:
            raise ValueError('last-actor leaf requires a post-action state')
        return self.leaf.final_attacker_points(clone, plays[-1].seat)


def run_fixed_leaf_ballot(rnd, seat, ballot, leaf, *, seed=0,
                          selection_worlds=30, report_worlds=300,
                          leaf_tricks=1, leaf_view='mover'):
    selection_worlds = _positive_int(selection_worlds, 'selection_worlds')
    report_worlds = _positive_int(report_worlds, 'report_worlds')
    leaf_tricks = _positive_int(leaf_tricks, 'leaf_tricks', zero=True)
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ValueError('seed must be an integer or None')
    if leaf_view not in ('mover', 'last_actor'):
        raise ValueError('leaf_view must be mover or last_actor')
    if leaf_view == 'last_actor':
        leaf = LastActorPointsLeaf(leaf)
    actions = _actions(ballot)

    def candidates(self, _rnd, _seat):
        return [list(action) for action in self._fixed_ballot]

    fixed_type = type('CWVFixedBallotPointsLeaf', (MCValueLeafSearch,), {
        'N_DETERMINIZATIONS': selection_worlds,
        'REPORT_FOLD_WORLDS': report_worlds,
        'TRACTOR_LOCK': False,
        '_candidates': candidates,
    })
    bot = fixed_type(leaf, seed=seed, leaf_tricks=leaf_tricks, leaf_stage='all')
    bot._fixed_ballot = tuple(tuple(action) for action in actions)
    played = bot.decide_play(rnd, seat)
    if tuple(sorted(played)) not in {tuple(sorted(a)) for a in actions}:
        raise ValueError('leaf consumer submitted an action outside fixed ballot')
    return {'played': played, 'record': bot.last_decision_record,
            'leaf_counts': dict(bot.leaf_counts), 'stage_counts': dict(bot.stage_counts),
            'leaf_seconds': bot.leaf_secs, 'leaf_tricks': leaf_tricks,
            'leaf_stage': bot.leaf_stage, 'leaf_view': leaf_view}
