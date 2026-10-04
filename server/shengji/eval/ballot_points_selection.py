"""Offline replay of the completed PV points selector, not a serving simulation.

The caller supplies the actual ordered ballot, value means and signed resolved
trick points on the same worlds. No engine, model or deadline is executed here.
In particular this cannot establish that the serving rebuild finished in time,
that the point evidence matches the value leaves, or that a choice is correct.
"""

from .ballot_matrix import _canonical_collection, _finite_number, _finite_result


def summarize_points_selection(actions, value_means, world_trick_points, *, epsilon=0.02):
    """Replay the points rule with admission-order ties and inclusive epsilon.

    ``value_means`` must be the exact means to replay (no recomputation with a
    different summation algorithm). Point entries must be signed engine integers,
    excluding kitty bonuses, not value-head scores or estimated point means.
    All supplied worlds must be complete. This deliberately refuses missing cells.
    The result is conditional on completion, with no lead-prior rule applied.
    """
    ballot = _canonical_collection(actions, "actions")
    if type(value_means) is not list or len(value_means) != len(ballot):
        raise ValueError("value_means must match actions")
    for value in value_means:
        _finite_number(value, "value mean")
    _finite_number(epsilon, "epsilon")
    if epsilon < 0:
        raise ValueError("epsilon must be nonnegative")
    if type(world_trick_points) is not list or not world_trick_points:
        raise ValueError("world_trick_points must contain complete worlds")
    for row in world_trick_points:
        if type(row) is not list or len(row) != len(ballot):
            raise ValueError("point matrix must be rectangular and match actions")
        for value in row:
            if type(value) is not int:
                raise ValueError("signed trick points must be integers (not bool)")
            _finite_number(value, "signed trick points")
    raw = max(range(len(ballot)), key=value_means.__getitem__)
    threshold = _finite_result(value_means[raw] - epsilon, "epsilon threshold")
    near = [i for i, value in enumerate(value_means) if value >= threshold]
    sums = {i: sum(row[i] for row in world_trick_points) for i in near}
    for total in sums.values():
        _finite_number(total, "point sum")
    chosen = min(near, key=lambda i: (-sums[i], i != raw, i))
    return {
        "schema": "completed-pv-points-selection-v1",
        "actions": [list(action) for action in ballot],
        "raw_index": raw,
        "selected_index": chosen,
        "near_indices": near,
        "near_count": len(near),
        # Serving does not rebuild or publish points for a singleton near-set.
        "near_point_means": [sums[i] / len(world_trick_points) for i in near]
        if len(near) > 1 else [],
        "changed": chosen != raw,
        "selected_value_gap": _finite_result(value_means[raw] - value_means[chosen],
                                              "selected value gap"),
        "epsilon": epsilon,
        "world_count": len(world_trick_points),
        "conditional_on_complete_rebuild": True,
        "serving_deadline_assessed": False,
        "strategic_quality_assessed": False,
    }
