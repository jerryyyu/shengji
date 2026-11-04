"""Bounded offline lead diagnosis; never called by serving.

The caller supplies an authorized reconstructed root and a cooperative deadline.
An external watchdog must enforce a hard wall limit around non-interruptible calls.
Values are model-relative common-world contrasts, not regret or playing strength.
Fresh bot RNG is not a replay of a historical decision's RNG. Capture overhead
can affect budget-limited decisions; this is not serving latency evidence.
"""
import copy
import time

import numpy as np


def compare_lead_actions(bot, rnd, seat, alternatives, *, gate):
    """Run one diagnostic decision and price up to four supplied alternatives.

    Both admission and pricing use the decision's base worlds. The actual
    played action is added to the comparison. All mutations, including RNG
    and refusal state, belong to a private bot copy. An expired or incomplete
    pass raises rather than exporting a partial matrix.
    """
    if rnd.phase != 'play' or rnd.turn != seat or rnd.trick.plays:
        raise ValueError('comparison requires the acting lead seat')
    if bot.leaf_greedy_top:
        raise ValueError("top-m leaves are unsupported by the confirmation scorer")
    alternatives = [tuple(sorted(a)) for a in alternatives]
    if not 1 <= len(alternatives) <= 4 or any(not a for a in alternatives):
        raise ValueError('supply one to four nonempty alternatives')
    if len(set(alternatives)) != len(alternatives):
        raise ValueError('duplicate alternatives')
    gate()
    diagnostic, root = copy.deepcopy(bot), copy.deepcopy(rnd)
    captured = {}
    admission = diagnostic._admission
    own_admission = vars(diagnostic).get("_admission")
    had_admission = "_admission" in vars(diagnostic)

    def observe(rnd, seat, actions, preferences, anchor_index, worlds, check_budget=None):
        chosen = admission(rnd, seat, actions, preferences, anchor_index, worlds, check_budget)
        captured.update(actions=copy.deepcopy(actions), preferences=np.array(preferences),
                        worlds=copy.deepcopy(worlds))
        return chosen

    search = diagnostic._search
    own_search = vars(diagnostic).get("_search")
    had_search = "_search" in vars(diagnostic)

    def bounded_search(rnd, seat, anchor, started, check_budget=None):
        def check():
            gate()
            if check_budget is not None:
                check_budget()
        return search(rnd, seat, anchor, started, check)

    diagnostic._admission = observe
    diagnostic._search = bounded_search
    try:
        played = diagnostic.decide_play(root, seat)
    finally:
        if had_search:
            diagnostic._search = own_search
        else:
            del diagnostic._search
        if had_admission:
            diagnostic._admission = own_admission
        else:
            del diagnostic._admission
    gate()
    record = copy.deepcopy(diagnostic.last_decision_record)
    if not captured or not record or record.get('work_complete') is not True:
        raise ValueError('incomplete diagnostic decision')
    pool = [tuple(sorted(a)) for a in captured['actions']]
    played_key = tuple(sorted(played))
    actions = list(dict.fromkeys([played_key, *alternatives]))
    if any(a not in pool for a in actions):
        raise ValueError('comparison action absent from generated legal pool')
    worlds = captured['worlds']
    if not worlds:
        raise ValueError('no captured base worlds')
    # Cached leaves and absolute deadlines belong to the completed decision.
    diagnostic._leaf_greedy = None
    diagnostic._leaf_greedy_pruned = frozenset()
    if diagnostic.leaf_greedy_deadline_ms:
        diagnostic._leaf_greedy_deadline_at = (
            time.perf_counter() + diagnostic.leaf_greedy_deadline_ms / 1000.0)
    matrix = diagnostic._lead_confirm_matrix(
        root, seat, [list(a) for a in actions], worlds, gate)
    gate()
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (len(worlds), len(actions)) or not np.isfinite(matrix).all():
        raise ValueError('incomplete common-world matrix')
    preferences = captured['preferences']
    if preferences.shape != (len(pool),) or not np.isfinite(preferences).all():
        raise ValueError('incomplete admission preferences')
    order = sorted(range(len(pool)), key=lambda i: (-preferences[i], i))
    admitted = {tuple(sorted(a)) for a in record['admitted']}
    selected_slot = record['admitted_indices'].index(record['selected_index'])
    record_selected = list(record['admitted'][selected_slot])
    rows = []
    for j, action in enumerate(actions):
        delta = matrix[:, j] - matrix[:, 0]
        rows.append(dict(action=list(action), policy_rank=order.index(pool.index(action)) + 1,
                         admitted=action in admitted, mean=float(matrix[:, j].mean()),
                         delta_vs_played=float(delta.mean()),
                         paired_se=(float(delta.std(ddof=1) / np.sqrt(len(worlds)))
                                    if len(worlds) > 1 else None)))
    return dict(scorer="lead_confirmation_on_base_worlds",
                played=list(played), record_selected=record_selected, decision=record, worlds=len(worlds), actions=rows,
                values=matrix.tolist(),
                claim='Confirmation-scorer repricing, not original selection values, historical RNG replay or strength.')
