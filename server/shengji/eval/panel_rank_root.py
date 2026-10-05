"""In-memory S10 root binding; not authentication or rank execution.

Caller supplies the authenticated, per-record-validated selected panel, fixture
and model/runtime. This verifies their public-root/config joins without I/O,
sampling or prediction. Physical tape conservation remains capture_policy_ranks'
gate. Refusal fallback worlds are not filtered or replaced here.
"""
import copy

from ..ai.memory import Memory
from .ballot_matrix import _canonical_collection
from .observation_queue import _canonical
from .public_fixture_panel import _snapshot_bot
from .public_refusal_history import public_root_with_ledger


def bind_panel_rank_root(panel, fixture, bot):
    """Return the matching public root (hidden hands are placeholders).

    Never score those placeholder hands: pass the original panel worlds to
    capture_policy_ranks. No provenance, serving-parity or strength claim.
    """
    panel = copy.deepcopy(panel)
    fixture = copy.deepcopy(fixture)
    if (type(panel) is not dict or panel.get('schema') != 'public-fixture-panel-v1'
            or panel.get('fixture_id') != fixture.id):
        raise ValueError('panel/fixture identity mismatch')
    if type(panel.get('fill_seed')) is not int or panel['fill_seed'] != 0:
        raise ValueError('panel fill seed must be zero')
    if type(panel.get('seed')) is not int or panel['seed'] not in (0, 1, 2):
        raise ValueError('strict panel seed required')
    snapshot = _snapshot_bot(bot, seed=panel.get('seed'), label='rank bot')
    for key in ('config', 'effective', 'checkpoint_sha256'):
        if _canonical(snapshot[key]) != _canonical(panel.get(key)):
            raise ValueError(f'panel/rank bot {key} mismatch')
    if type(snapshot['effective']['cap']) is not int or snapshot['effective']['cap'] < 1:
        raise ValueError('positive integer legal cap required')
    root, _ledger, receipt = public_root_with_ledger(
        fixture, mode=panel.get('mode'), fill_seed=panel['fill_seed'])
    if type(fixture.seat) is not int or root.turn != fixture.seat:
        raise ValueError('public root actor mismatch')
    tape = panel.get('tape_receipt')
    if type(tape) is not dict or _canonical(tape.get('ledger_receipt')) != _canonical(receipt):
        raise ValueError('reconstructed ledger receipt mismatch')
    from ..harvest.legal import enumerate_legal
    legal = enumerate_legal(root, fixture.seat, cap=snapshot['effective']['cap'])
    if (legal.complete is not True or type(panel.get('legal_count')) is not int
            or legal.count != panel['legal_count']
            or _canonical_collection(legal.actions, 'legal actions')
            != _canonical_collection(panel.get('actions'), 'panel actions')):
        raise ValueError('complete ordered legal pool mismatch')
    worlds = panel.get('worlds')
    if type(worlds) is not list or len(worlds) != 64:
        raise ValueError('retained 64-world tape required')
    memory = Memory(root, fixture.seat, own_kitty=getattr(bot.sampler, 'BANKER_KITTY', True))
    for hands, _buried in worlds:
        if any(root.ordering.eff_suit(card) in memory.voids[seat]
               for seat in range(4) if seat != fixture.seat for card in hands[seat]):
            raise ValueError('retained tape violates public voids')
    return root


def project_panel_rank_repair(selected, fixture, bot, *, arm, check_budget=None):
    """Single-arm compatibility API; use the plural API to compare both arms."""
    result = project_panel_rank_repairs(selected, fixture, bot, arms=(arm,),
                                        check_budget=check_budget)
    projection = result.pop('projections')[arm]
    result.update(schema='selected-panel-rank-repair-v1', arm=arm, projection=projection)
    return result


def project_panel_rank_repairs(selected, fixture, bot, *,
                              arms=('control', 'treatment'), check_budget=None):
    """Project requested ballots from one shared policy-rank capture.

    Caller must authenticate selected-reader output, fixture, model and runtime
    before entry. No I/O, sampling or value execution occurs here. Real policy
    execution still needs the reviewed outer invocation and authorization.
    Validation errors propagate per root; callers must retain refusal reasons,
    never replace/filter worlds or silently omit failed roots.
    """
    from .fixed_tape_policy import capture_policy_ranks
    from .m9_panel_readout import _capture
    from .pair_resource_admission import project_rank_repair

    if check_budget is not None:
        check_budget()
    selected = copy.deepcopy(selected)
    if type(selected) is not dict or selected.get('schema') != 'selected-m9-panel-v1':
        raise ValueError('validated selection required')
    if (type(arms) not in (tuple, list) or not arms
            or any(type(arm) is not str or arm not in ('control', 'treatment') for arm in arms)
            or len(set(arms)) != len(arms)):
        raise ValueError('unique nonempty control/treatment arms required')
    arms = tuple(arms)
    panel, job = selected['panel'], selected['job']
    for key in ('fixture_id', 'mode', 'seed'):
        if _canonical(job.get(key)) != _canonical(panel.get(key)):
            raise ValueError(f'selected job/panel {key} mismatch')
    root = bind_panel_rank_root(panel, fixture, bot)
    actions = panel['actions']
    full = set(_canonical_collection(actions, 'full pool'))
    baselines = {arm: job[f'{arm}_ballot'] for arm in arms}
    for arm, baseline in baselines.items():
        ballot = _canonical_collection(baseline, f'{arm} baseline')
        if not ballot or not set(ballot) <= full:
            raise ValueError(f'{arm} baseline absent from full pool')
    collection = panel['collection']
    saved = (collection['captures']['full_pool'] if panel['mode'] == 'fresh-root'
             else collection['full_pool_capture'])
    # Fail malformed saved data before the sole, potentially costly prediction.
    values = _capture(saved, actions, 'full_pool capture')['means']
    ranks = capture_policy_ranks(bot, root, fixture.seat, actions, panel['worlds'],
                                 check_budget=check_budget)
    projections = {arm: project_rank_repair(root, fixture.seat, ranks, baseline, actions, values)
                   for arm, baseline in baselines.items()}
    if check_budget is not None:
        check_budget()
    return {'schema': 'selected-panel-rank-repairs-v1',
            'fixture_id': fixture.id, 'mode': panel['mode'], 'seed': panel['seed'],
            'capture': ranks, 'projections': projections,
            'provenance_verified': False, 'serving_choice_assessed': False,
            'strategic_quality_assessed': False}
