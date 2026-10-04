"""Three-pass diagnostic binding, with no sampling or artifact/launch authority.

Caller supplies a validated root, complete legal pool, fixed tape and a factory
for fresh bots of the SAME reviewed model/recipe. This module does not authenticate
that provenance. Shared-matrix restrictions and separately batched ballot replays
remain separate outputs: the latter cannot isolate admission from batch effects.
"""
import copy

from .ballot_matrix import _canonical_collection, _finite_result
from .ballot_full_pool import summarize_full_pool_matrix
from .ballot_points_selection import summarize_points_selection
from .fixed_tape_capture import capture_fixed_tape


def collect_fixed_tape_panel(bot_factory, root, seat, actions, control_ballot,
                             treatment_ballot, worlds, *, check_budget=None):
    """Score full pool and both ordered ballots on copies of one fixed tape.

    Factory calls may load models, so running this with a real factory is a
    scientific collection requiring the external reviewed packet and RELEASE.
    No factory is called during import. Every pass has a fresh bot/root/tape.
    The captures are retained to support a separately qualified sealed reader.
    """
    full = _canonical_collection(actions, "actions")
    ballots = {
        "control": _canonical_collection(control_ballot, "control_ballot"),
        "treatment": _canonical_collection(treatment_ballot, "treatment_ballot"),
    }
    if any(not set(ballot) <= set(full) for ballot in ballots.values()):
        raise ValueError("ballot member absent from full pool")
    if type(worlds) is not list or not worlds:
        raise ValueError("a nonempty frozen tape is required")
    if any(not isinstance(world, (tuple, list)) or len(world) != 2 for world in worlds):
        raise ValueError("worlds must contain (hands, buried) pairs")
    if type(seat) is not int or seat not in range(4) or root.turn != seat:
        raise ValueError("seat must be the current player")
    tape = copy.deepcopy(worlds)
    frozen_root = copy.deepcopy(root)
    groups = {"full_pool": actions, "control": control_ballot,
              "treatment": treatment_ballot}
    captures, bots = {}, []
    for name, ballot in groups.items():
        if check_budget is not None:
            check_budget()
        bot = bot_factory()
        from ..train.policy_value_search import PolicyValueBot
        # Final equality misses mutate-then-restore overrides. Require the
        # reviewed production leaf, which clones the supplied world state.
        if getattr(getattr(bot, "_leaf", None), "__func__", None) is not PolicyValueBot._leaf:
            raise ValueError("canonical production leaf implementation is required")
        if any(bot is previous for previous in bots):
            raise ValueError("each capture requires a fresh dedicated bot")
        bots.append(bot)
        pass_tape = copy.deepcopy(tape)
        captures[name] = capture_fixed_tape(
            bot, copy.deepcopy(frozen_root), seat, copy.deepcopy(ballot), pass_tape,
            check_budget=check_budget)
        if pass_tape != tape:
            raise ValueError("capture mutated the frozen world tape")

    shared = captures["full_pool"]
    indices = {action: i for i, action in enumerate(full)}
    replays, shared_replays, schedule_deltas = {}, {}, {}
    for name, ballot in ballots.items():
        capture = captures[name]
        columns = [indices[action] for action in ballot]
        shared_points = [[row[i] for i in columns] for row in shared["signed_trick_points"]]
        if shared_points != capture["signed_trick_points"]:
            raise ValueError("resolved points differ across identical world/action cells")
        shared_means = [shared["serving_value_means"][i] for i in columns]
        # Same accumulator reduction, DIFFERENT batch schedule: report both.
        replays[name] = summarize_points_selection(
            groups[name], capture["serving_value_means"], capture["signed_trick_points"])
        shared_replays[name] = summarize_points_selection(groups[name], shared_means, shared_points)
        schedule_deltas[name] = [
            _finite_result(value - common, "batch schedule value difference")
            for value, common in zip(capture["serving_value_means"], shared_means)
        ]
    return {
        "schema": "fixed-tape-three-pass-panel-v1",
        "captures": captures,
        "shared_matrix_summary": summarize_full_pool_matrix(
            actions, control_ballot, treatment_ballot, shared["value_matrix"]),
        "shared_matrix_points_replay": shared_replays,
        "ballot_schedule_points_replay": replays,
        "ballot_minus_full_schedule_value_deltas": schedule_deltas,
        "shared_summary_reduction": "math.fsum",
        "selector_reduction": "serving sequential np.add.at / world_count",
        "provenance_verified": False,
        "strategic_quality_assessed": False,
    }


def collect_history_primed_panel(bot_factory, root, seat, actions,
                                 control_ballot, treatment_ballot, worlds,
                                 *, check_budget=None):
    """Capture one complete pool on one fixed tape and project both ballots.

    The name describes the caller's intended tape mode only; this function
    neither samples worlds nor verifies that the supplied tape is history-
    primed.  Ballot columns are projected from the one full-pool capture, so
    this diagnostic does not make served or treatment-admission claims.
    """
    full = _canonical_collection(actions, "actions")
    control = _canonical_collection(control_ballot, "control_ballot")
    treatment = _canonical_collection(treatment_ballot, "treatment_ballot")
    full_set = set(full)
    if not set(control) <= full_set or not set(treatment) <= full_set:
        raise ValueError("ballot member absent from full pool")
    if type(worlds) is not list or not worlds:
        raise ValueError("a nonempty frozen tape is required")
    if any(not isinstance(world, (tuple, list)) or len(world) != 2 for world in worlds):
        raise ValueError("worlds must contain (hands, buried) pairs")
    if type(seat) is not int or seat not in range(4) or root.turn != seat:
        raise ValueError("seat must be the current player")

    tape = copy.deepcopy(worlds)
    frozen_root = copy.deepcopy(root)
    from ..train.policy_value_search import PolicyValueBot

    if check_budget is not None:
        check_budget()
    bot = bot_factory()
    # Match the three-pass panel's canonical leaf guard.  capture_fixed_tape
    # separately enforces the canonical world-major scoring loop.
    if getattr(getattr(bot, "_leaf", None), "__func__", None) is not PolicyValueBot._leaf:
        raise ValueError("canonical production leaf implementation is required")
    pass_tape = copy.deepcopy(tape)
    full_capture = capture_fixed_tape(
        bot, copy.deepcopy(frozen_root), seat, copy.deepcopy(actions), pass_tape,
        check_budget=check_budget)
    if pass_tape != tape:
        raise ValueError("capture mutated the frozen world tape")

    summary = summarize_full_pool_matrix(
        actions, control_ballot, treatment_ballot, full_capture["value_matrix"])
    return {
        "schema": "fixed-tape-history-primed-panel-v1",
        "full_pool_capture": full_capture,
        "shared_matrix_summary": summary,
        "union_is_projection": True,
        "saved_ballots_generated_under_this_sampler": False,
        "sampler_mode_verified": False,
        "provenance_verified": False,
        "strategic_quality_assessed": False,
    }
