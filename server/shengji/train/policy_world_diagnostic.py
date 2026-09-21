"""Saved-position sensitivity diagnostic, not a gameplay-strength estimator.

Cross admission sample counts with value sample counts on common prefixes.
Fresh-world scores audit selection noise only over the union of admitted actions;
they are neither a legal-action oracle nor held-out gameplay evidence.
"""
import numpy as np

from ..ai.heuristic import HeuristicBot
from ..harvest.legal import enumerate_legal
from .policy_value_search import PolicyValueBot
from .policy_world_search import world_diversity


def diagnose_position(predict, evaluator, rnd, seat, *, counts=(64, 128, 256),
                      candidates=8, cap=4000, seed=577, audit_seed=578):
    counts = tuple(counts)
    if (not counts or any(type(n) is not int or not 1 <= n <= 256 for n in counts)
            or tuple(sorted(set(counts))) != counts):
        raise ValueError('counts must be increasing unique integers in [1,256]')
    if type(seed) is not int or type(audit_seed) is not int or seed == audit_seed:
        raise ValueError('distinct integer discovery and audit seeds required')
    maximum = counts[-1]
    bot = PolicyValueBot(predict, evaluator=evaluator, worlds=maximum,
                         candidates=candidates, cap=cap, seed=seed)
    audit = PolicyValueBot(predict, evaluator=evaluator, worlds=maximum,
                           candidates=candidates, cap=cap, seed=audit_seed)
    anchor = HeuristicBot().decide_play(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=cap, must_include=[anchor])
    actions = list(legal.actions)
    anchor_index = next(i for i, action in enumerate(actions)
                        if sorted(action) == sorted(anchor))
    worlds, attempts = bot._worlds(rnd, seat)
    audit_worlds, audit_attempts = audit._worlds(rnd, seat)
    preferences = bot.scores(rnd, seat, actions, worlds)
    admitted = {}
    for n in counts:
        means = preferences[:n].mean(axis=0)
        ranked = sorted(range(len(actions)), key=lambda i: (-means[i], i))
        admitted[n] = ([anchor_index] + [i for i in ranked if i != anchor_index])[:candidates]
    union = sorted({i for indices in admitted.values() for i in indices})
    union_actions = [actions[i] for i in union]
    columns = {index: col for col, index in enumerate(union)}

    def values(sampled):
        # Reuse the exact current-trick/root-team value path. Each row is one
        # world shared by every union action; duplicate draws retain weight.
        return np.asarray([bot._value_means(rnd, seat, union_actions, [world])[0]
                           for world in sampled])

    discovery_values = values(worlds)
    audit_values = values(audit_worlds)
    fresh = audit_values.mean(axis=0)
    cells = []
    for admission_n in counts:
        indices = admitted[admission_n]
        cols = [columns[i] for i in indices]
        for value_n in counts:
            means = discovery_values[:value_n, cols].mean(axis=0)
            order = sorted(range(len(cols)), key=lambda i: (-means[i], i))
            winner = order[0]
            runner = order[1] if len(order) > 1 else None
            paired = (discovery_values[:value_n, cols[winner]] -
                      discovery_values[:value_n, cols[runner]]) if runner is not None else None
            cells.append(dict(
                admission_worlds=admission_n, value_worlds=value_n,
                selected_index=indices[winner], selected_value=float(means[winner]),
                runner_up_index=None if runner is None else indices[runner],
                selected_gap=None if runner is None else float(means[winner] - means[runner]),
                paired_world_difference_variance=(float(np.var(paired, ddof=1))
                    if paired is not None and value_n > 1 else None),
                fresh_selected_value=float(fresh[cols[winner]]),
                fresh_union_gap=float(fresh.max() - fresh[cols[winner]])))
    reference = set(admitted[maximum])
    return dict(schema='policy-world-position-diagnostic-v1', seed=seed, audit_seed=audit_seed,
                counts=list(counts), candidates=candidates, legal_count=legal.count,
                legal_complete=legal.complete, enumerated_actions=len(actions),
                union_indices=union, union_actions=union_actions,
                admissions=[dict(worlds=n, indices=admitted[n],
                    overlap_with_largest=len(set(admitted[n]) & reference),
                    **world_diversity(worlds[:n])) for n in counts],
                sample_attempts=attempts, audit_sample_attempts=audit_attempts,
                audit_worlds=maximum, audit_diversity=world_diversity(audit_worlds),
                value_evaluations=2 * maximum * len(union), cells=cells,
                caveat='Single-position sensitivity; fresh union gap is not oracle regret or gameplay strength. '
                       'Selected pair variance is descriptive, not a post-selection confidence interval.')
