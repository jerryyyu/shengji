"""Offline policy ranks on supplied worlds; no sampling, value search or I/O.

Real predictor execution requires external authorization. Caller authenticates
root, ordered legal pool, tape, model and encoder; this helper proves none of
that provenance and must not be used to silently regenerate historical ranks.
"""
import copy
from collections import Counter

import numpy as np

from .ballot_matrix import _canonical_collection


def capture_policy_ranks(bot, root, seat, actions, worlds, *, check_budget=None):
    """Call canonical serving policy scoring once, retain every preference.

    Input copies protect caller data. No bot factory, sampler, admission,
    heuristic anchor, leaf scorer or value evaluator is invoked. Budget checks
    bracket the indivisible prediction; expiration returns no result.
    """
    from ..train.pv_search_policy import PVSearchBot
    from ..ai.mcbot import MCBot, DeterminizationContractError

    if (not isinstance(bot, PVSearchBot)
            or getattr(bot.scores, '__func__', None) is not PVSearchBot.scores):
        raise ValueError('canonical PVSearchBot policy scoring required')
    _canonical_collection(actions, 'actions')
    if type(seat) is not int or seat not in range(4) or root.turn != seat:
        raise ValueError('seat must be the current player')
    if type(worlds) is not list or not worlds:
        raise ValueError('nonempty supplied world tape required')
    hand = Counter(root.hands[seat])
    if any(Counter(action) - hand for action in actions):
        raise ValueError('action is not a subset of actor hand')
    # This existing validator is state-free: do not initialize a sampler or
    # consume RNG. Its sorted return is deliberately discarded; score the
    # caller's original ordered tape, not a canonicalized replacement.
    validator = object.__new__(MCBot)
    for world in worlds:
        if (not isinstance(world, (tuple, list)) or len(world) != 2
                or len(world[0]) != 4 or Counter(world[0][seat]) != hand):
            raise ValueError('world must retain actor hand and four seats')
        hands, buried = world
        if len(buried) != len(root.buried):
            raise ValueError('world must retain buried card count')
        try:
            MCBot._complete_determinized_hands(
                validator, root, seat,
                {s: hands[s] for s in range(4) if s != seat}, buried=buried)
        except DeterminizationContractError as exc:
            raise ValueError('world violates card conservation or hand counts') from exc
    if check_budget is not None:
        check_budget()
    scores = np.asarray(PVSearchBot.scores(
        bot, copy.deepcopy(root), seat, copy.deepcopy(actions), copy.deepcopy(worlds)
    ), dtype=np.float64)
    if scores.shape != (len(worlds), len(actions)) or not np.isfinite(scores).all():
        raise ValueError('finite world-by-action policy scores required')
    preferences = scores.mean(axis=0)
    if not np.isfinite(preferences).all():
        raise ValueError('finite mean policy scores required')
    ranked = sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
    if check_budget is not None:
        check_budget()
    return {
        'schema': 'fixed-tape-policy-ranks-v1',
        'actions': copy.deepcopy(actions), 'world_count': len(worlds),
        'encoder_version': bot.version,
        'preferences': preferences.tolist(), 'ranked_indices': ranked,
        'reduction': 'numpy mean(axis=0) of serving policy scores',
        'tie_order': 'supplied action index ascending',
        'provenance_verified': False, 'legal_completeness_verified': False,
        'serving_choice_assessed': False,
    }
