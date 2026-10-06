"""One S11 public root: one sampled tape, one policy pass, one value pass.

No artifact I/O or model loading. Real execution requires the separately
reviewed source/model/population packet and authorization. Pool completeness
is reported, not required: the estimand is the release-38 capped served pool.
"""
import copy

from ..ai.heuristic import HeuristicBot
from ..train.policy_value_search import PolicyValueBot
from ..train.pv_search_policy import PVSearchBot
from .fixed_tape_capture import capture_fixed_tape
from .fixed_tape_policy import capture_policy_ranks
from .public_fixture_panel import _snapshot_bot
from .public_refusal_tape import sample_public_refusal_tape
from .s11_report import project_s11


def _snapshot(bot, seed):
    snapshot = _snapshot_bot(bot, seed=seed, label='S11 bot')
    required = dict(worlds=64, candidates=8, cap=4000,
                    refusal_constraints=True, admission_diversity=True,
                    lead_anchor=True, tiebreak_points=True,
                    refusal_event_complete=False, admit_forced_single=False,
                    adaptive_k=False, lead_tiebreak_prior=False,
                    doomed_throw_swap=False)
    for field, value in required.items():
        if (type(getattr(bot.config, field)) is not type(value)
                or getattr(bot.config, field) != value
                or type(getattr(bot, field)) is not type(value)
                or getattr(bot, field) != value):
            raise ValueError(f'S11 release38 {field} mismatch')
    if bot.config.tree is not None:
        raise ValueError('S11 requires one-ply search')
    if getattr(bot._leaf, '__func__', None) is not PolicyValueBot._leaf:
        raise ValueError('canonical production leaf required')
    return snapshot


def collect_s11_fixture(bot_factory, fixture, *, seed, fill_seed=0,
                        check_budget=None):
    """Return saved tape/captures and B/C/T projection, or propagate failure.

    The caller must retain a failed scheduled root and its reason, never replace
    it. Bots are dedicated to this invocation; no live serving bot may be used.
    Sampler fallbacks are retained in the receipt, not discarded or resampled.
    """
    if type(seed) is not int or seed < 0:
        raise ValueError('nonnegative integer seed required')
    if type(fill_seed) is not int or fill_seed < 0:
        raise ValueError('nonnegative integer fill seed required')
    if type(fixture.id) is not str or not fixture.id:
        raise ValueError('nonempty root id required')
    if check_budget is not None:
        check_budget()
    fixture = copy.deepcopy(fixture)
    sampler = bot_factory()
    snapshot = _snapshot(sampler, seed)
    scorer = bot_factory()
    if scorer is sampler or scorer.sampler is sampler.sampler:
        raise ValueError('sampler and scorer must be independently owned')
    if _snapshot(scorer, seed) != snapshot or scorer.version != sampler.version:
        raise ValueError('sampler/scorer recipe drift')
    root, worlds, receipt = sample_public_refusal_tape(
        sampler, fixture, mode='history-primed', seed=seed,
        fill_seed=fill_seed, check_budget=check_budget)
    # Invoke the serving enumeration with the serving heuristic anchor. Plain
    # enumerate_legal would omit anchor insertion and can reorder this pool.
    anchor = HeuristicBot.decide_play(scorer, root, fixture.seat)
    legal = PVSearchBot._legal(scorer, root, fixture.seat, [anchor])
    actions = copy.deepcopy(list(legal.actions))
    rng = scorer.sampler.rng.getstate()
    ranks = capture_policy_ranks(scorer, root, fixture.seat, actions, worlds,
                                 check_budget=check_budget)
    value_tape = copy.deepcopy(worlds)
    values = capture_fixed_tape(scorer, copy.deepcopy(root), fixture.seat,
                                copy.deepcopy(actions), value_tape,
                                check_budget=check_budget)
    if value_tape != worlds or scorer.sampler.rng.getstate() != rng:
        raise ValueError('scoring mutated tape or consumed sampler RNG')
    report = project_s11(fixture.id, root, fixture.seat, ranks, actions,
                         values['serving_value_means'], check_budget=check_budget)
    return dict(schema='s11-collected-root-v1', root_id=fixture.id,
                seed=seed, fill_seed=fill_seed, recipe=snapshot,
                encoder_version=scorer.version, tape_receipt=receipt,
                worlds=worlds, policy_capture=ranks, value_capture=values,
                report=report, legal_count=legal.count,
                legal_complete=legal.complete,
                pool_scope='release38 capped served pool',
                provenance_verified=False, model_verified=False,
                serving_choice_assessed=False)
