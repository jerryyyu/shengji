"""Integrated sealed-reader validity path over producer-shaped synthetic shards."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_admission import packet
from outcome_gate import outcome_checked_result
from shengji.train.cwv_shortlist_screen import _recipe


def _declaration():
    return dict(schema='pv-value-declare-decision-v1', evaluated=True,
                changed=False, final=False, fallback_reason=None, seconds=.1,
                worlds=64, worlds_completed=64, leaf_first_trick='heuristic',
                leaf_first_trick_fallbacks=0, cards_dealt=80, played='PASS',
                heuristic='PASS')


def _bury(seat):
    return dict(seat=seat, schema='cwv-bury-policy-v1', elapsed_seconds=.1,
                fallback_reason=None, leaf_first_trick='heuristic',
                leaf_first_trick_fallbacks=0, candidate_count=2,
                model_positions=4, finalist_count=0, mc_rollouts=0,
                mc_evidence=None, selection_worlds=0, shortlist=[0],
                rollout_seconds=0., candidates__len=2, model_means__len=2,
                model_worlds=2, picked_index=0,
                wide_value=dict(candidates=2, worlds=2, chosen_index=0,
                                 chosen_is_incumbent=True, seconds=.1, k=64))


def _decision(side, seat, trick, *, lead=False, applied=False, skipped=False):
    rec = dict(policy= 'a' if side == 'candidate' else 'b', seat=seat, trick=trick, schema='pv-search-decision-v1',
               played=['C7'], worlds=64, seconds=.1, admitted__len=2,
               belief_fallback=0,
               doomed_throw_reselect_applied=False,
               doomed_throw_reselect_from='SJ', doomed_throw_reselect_to='SJ',
               doomed_throw_reselect_doomed_candidates=0,
               doomed_throw_reselect_forced_excluded=0,
               doomed_throw_reselect_fallback_forced=False)
    if side == 'candidate':
        rec.update(doomed_throw_reselect_exact_guarded=True,
                   doomed_throw_reselect_exact_floor_excluded=0)
    if lead:
        if applied:
            rec.update(exact_deep_cards=7, exact_lead_status='ineligible',
                       exact_lead_worlds_completed=0, exact_lead_nodes=None,
                       exact_lead_cache_hits=None, exact_lead_changed=False)
        elif skipped:
            rec.update(exact_deep_cards=7, exact_lead_status='skipped_budget',
                       exact_lead_worlds_completed=0, exact_lead_nodes=None,
                       exact_lead_cache_hits=None, exact_lead_changed=False)
        else:
            rec.update(exact_deep_cards=7, exact_lead_status='complete',
                       exact_lead_worlds_completed=64, exact_lead_nodes=10,
                       exact_lead_cache_hits=0, exact_lead_changed=True,
                       exact_lead_base_level_mean=0., exact_lead_base_played=['D7'],
                       exact_lead_base_played__len=1,
                       exact_lead_base_selected_index=0,
                       exact_lead_base_value_means__len=2,
                       exact_lead_base_value_means=[0., 1.],
                       exact_lead_change_kind='higher', exact_lead_seconds=.05,
                       exact_lead_selected_level_delta=1.,
                       exact_lead_selected_level_mean=1.)
    else:
        rec.update(exact_deep_cards=7, exact_lead_status='ineligible',
                   exact_lead_worlds_completed=0, exact_lead_nodes=None,
                   exact_lead_cache_hits=None, exact_lead_changed=False,
                   exact_follow_attempted=True, exact_follow_applied=True,
                   exact_follow_abandoned=None, exact_follow_nodes=10,
                   exact_follow_worlds=64, exact_follow_scores__len=2,
                   exact_follow_scores=[1., 0.], admitted_indices=[0, 1],
                   selected_index=0)
    if side == 'candidate':
        rec.update(leaf_greedy_finish_applied=applied,
                   leaf_greedy_reply_plays=1 if applied else 0,
                   leaf_greedy_reply_evaluations=2 if applied else 0,
                   leaf_greedy_reply_differs_heuristic=1 if applied else 0,
                   leaf_greedy_policy_rows=1 if applied else 0,
                   leaf_greedy_uncached_leaves=0,
                   leaf_greedy_finish_exact_skipped=skipped)
    return rec


def _augment(plan, configs, shards):
    for side in ('candidate', 'comparator'):
        representative = next(x for x in plan['windows'] if x['side'] == side)
        cfg = configs[representative['output']]
        identity = {'config': dict(worlds=64,
            value_declare_worlds=64, doomed_throw_reselect=True,
            doomed_throw_reselect_exact_guard=side == 'candidate',
            leaf_greedy_finish=side == 'candidate',
            leaf_greedy_finish_exact_skip=side == 'candidate')}
        plan['arms'][side]['identity'] = copy.deepcopy(identity)
        cfg['arm_policy_identity'] = identity
        for w in [x for x in plan['windows'] if x['side'] == side]:
            cfg = configs[w['output']]
            cfg['arm_policy_identity'] = copy.deepcopy(configs[representative['output']]['arm_policy_identity'])
            for shard_index, shard in enumerate(shards[w['output']]):
                for row in shard['records']:
                    # Keep paired deal identity fixed while varying a valid
                    # engine outcome by mirror/cluster.  The variation gives
                    # the unmocked bootstrap estimator non-zero within-window
                    # SE; identical synthetic utilities would be degenerate.
                    points = 0 if (side == 'candidate' and row['mirror'] == 0
                                   and row['cluster'] % 2 == 0) else (
                                       40 if (side == 'candidate'
                                              and row['mirror'] == 0) else 80)
                    banker = row['banker']
                    if points == 0:
                        winner_team, level_change = 0, 3
                    elif points == 40:
                        winner_team, level_change = banker % 2, 1
                    else:
                        winner_team, level_change = 1 - (banker % 2), 0
                    arm_won = int(winner_team == row['mirror'])
                    arm_utility = max(1, level_change) * (1 if arm_won else -1)
                    row.update(attacker_points=points, winner_team=winner_team,
                               level_change=level_change, arm_team=row['mirror'],
                               arm_won=arm_won, baseline_utility=-arm_utility,
                               arm_utility=arm_utility, kitty_bonus=0)
                    row['trump_suit'] = 'S'
                    ntricks = 8 if side == 'candidate' and shard_index == 0 else 1
                    row['committed_history'] = [[s, ['C7']] for _ in range(ntricks) for s in range(4)]
                traces = []
                for mirror in (0, 1):
                    seats = [mirror, mirror + 2]
                    ntricks = 8 if side == 'candidate' and shard_index == 0 else 1
                    for index, seat in enumerate(seats):
                        decisions = []
                        for trick in range(ntricks):
                            rec = _decision(side, seat, trick,
                                lead=seat == 0,
                                applied=side == 'candidate' and shard_index == 0 and seat == 0 and trick == 0,
                                skipped=side == 'candidate' and seat != 0
                                    and not (shard_index == 0 and trick == 0 and seat != 0))
                            # On the first trick of the long fixture the
                            # maximum remaining hand is eight, so follow exact
                            # search is ineligible; omit its stage receipt.
                            if side == 'candidate' and shard_index == 0 and trick == 0 and seat != 0:
                                for key in tuple(rec):
                                    if key.startswith('exact_follow_') or key in ('admitted_indices', 'selected_index'):
                                        del rec[key]
                            if side == 'candidate' and shard_index == 1 and seat == 0 and trick == 0:
                                # A completed exact lead can legitimately skip
                                # the greedy finish; keep its work counters zero.
                                rec['leaf_greedy_finish_exact_skipped'] = True
                            if side == 'candidate' and seat == 0 and not (shard_index == 0 and trick == 0):
                                rec['leaf_greedy_finish_exact_skipped'] = True
                            decisions.append(rec)
                        traces.append(dict(mirror=mirror, side='arm',
                            decisions=decisions,
                            bury_decisions=[_bury(seat)]
                                if seat == shard['records'][mirror]['banker'] else [],
                            declare_decisions=[_declaration()],
                            declare_coverage=dict(calls=1, expected=1)))
                shard['decision_traces'] = traces
                shard['recipe'] = _recipe(cfg)


def _valid_packet(tmp_path):
    plan, expected, configs, shards = packet(tmp_path)
    # Each side's identity is frozen per config, and all shards share the same shape.
    _augment(plan, configs, shards)
    expected = copy.deepcopy(configs)
    return plan, expected, configs, shards


def test_full_pipeline_reaches_estimator(tmp_path):
    plan, expected, configs, shards = _valid_packet(tmp_path)
    result = outcome_checked_result(plan, expected, configs, shards)
    assert result['status'] == 'STAGE_OUTCOME_CHECKED_ONLY', result
    assert 'estimate' in result


@pytest.mark.parametrize('side', ['candidate', 'comparator'])
@pytest.mark.parametrize('kind', ['worlds', 'declaration', 'fallback', 'outcome'])
def test_full_pipeline_refuses_invalid_arm_before_estimator(tmp_path, side, kind):
    plan, expected, configs, shards = _valid_packet(tmp_path)
    target = next(w for w in plan['windows'] if w['side'] == side)
    shard = shards[target['output']][0]
    if kind == 'worlds':
        shard['decision_traces'][0]['decisions'][0]['worlds'] = 63
    elif kind == 'declaration':
        shard['decision_traces'][0]['declare_decisions'][0]['worlds_completed'] = 63
    elif kind == 'fallback':
        decision = shard['decision_traces'][0]['decisions'][0]
        identity = {key: decision[key] for key in ('seat', 'trick', 'played')}
        decision.clear()
        decision.update(identity, schema='pv-search-fallback-v1', reason='budget', worlds=None)
    else:
        shard['records'][0]['arm_utility'] = 999
    result = outcome_checked_result(plan, expected, configs, shards)
    assert result['status'] in ('DECISION_INVALID', 'OUTCOME_INVALID')
    assert 'estimate' not in result
