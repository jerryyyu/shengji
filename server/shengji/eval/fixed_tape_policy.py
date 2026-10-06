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


def release38_admission(root, seat, capture, *, check_budget=None):
    """Reproduce release-38's admission boundary on supplied policy scores.

    No predictor, sampler, value evaluator or file access. Recompute the
    canonical heuristic anchor and capped ordered pool, then invoke serving's
    actual admission methods (K8, diversity and lead-anchor on; extras off).
    Refuse captures from a different pool/order instead of reindexing ties.
    The caller still authenticates root, model, refusal-aware W64 tape and
    capture provenance. This is not full served-choice or strength evidence.
    """
    from ..ai.heuristic import HeuristicBot
    from ..train.pv_search_policy import PVSearchBot
    from .ballot_matrix import _finite_number

    if type(seat) is not int or seat not in range(4) or root.turn != seat:
        raise ValueError('seat must be the current player')
    if (not isinstance(capture, dict)
            or capture.get('schema') != 'fixed-tape-policy-ranks-v1'
            or type(capture.get('world_count')) is not int
            or capture['world_count'] != 64):
        raise ValueError('release38 requires a W64 policy capture')
    canonical = _canonical_collection(capture.get('actions'), 'policy actions')
    preferences, ranked = capture.get('preferences'), capture.get('ranked_indices')
    if (type(preferences) is not list or len(preferences) != len(canonical)
            or type(ranked) is not list or any(type(i) is not int for i in ranked)):
        raise ValueError('complete policy preferences and integer ranks required')
    for value in preferences:
        _finite_number(value, 'policy preference')
    if ranked != sorted(range(len(canonical)), key=lambda i: (-preferences[i], i)):
        raise ValueError('policy rank order drift')
    if check_budget is not None:
        check_budget()
    rnd = copy.deepcopy(root)
    # Allocate only the state consumed by canonical enumeration/admission.
    # No constructor/factory can load a model or initialize a sampler here.
    bot = object.__new__(PVSearchBot)
    bot.cap, bot.candidates, bot.max_per_structure = 4000, 8, 2
    bot.admission_diversity, bot.lead_anchor = True, True
    bot.admit_forced_single, bot.adaptive_k = False, False
    anchor = HeuristicBot.decide_play(bot, rnd, seat)
    legal = PVSearchBot._legal(bot, rnd, seat, [anchor])
    actions = list(legal.actions)
    if canonical != _canonical_collection(actions, 'served actions'):
        raise ValueError('capture differs from release38 ordered scored pool')
    if check_budget is not None:
        check_budget()
    anchor_key = tuple(sorted(anchor))
    anchor_index = next(i for i, action in enumerate(actions)
                        if tuple(sorted(action)) == anchor_key)
    chosen = bot._admission(rnd, seat, actions, np.asarray(preferences),
                            anchor_index, None, check_budget)
    if check_budget is not None:
        check_budget()
    return {
        'schema': 'release38-admission-boundary-v1',
        'actions': copy.deepcopy(actions), 'chosen_indices': chosen,
        'baseline_actions': [list(actions[i]) for i in chosen],
        'heuristic_anchor_index': anchor_index, 'effective_anchor_index': chosen[0],
        'admission_record': bot._admission_record(),
        'legal_count': legal.count, 'legal_complete': legal.complete,
        'cap': 4000, 'candidates': 8,
        'provenance_verified': False, 'serving_choice_assessed': False,
    }
