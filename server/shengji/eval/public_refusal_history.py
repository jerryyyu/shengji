"""Explicit diagnostic ledger reconstruction; never changes serving defaults.

Uses only the fixture's public plays and actor hand. Returned hidden hands are
placeholders, NOT a sampled world or model input. Callers must declare the mode
in their reviewed packet and bind the returned root and ledger together.
"""
from dataclasses import asdict

from ..ai.refusal import RefusalLedger
from . import tactical


def _observe_history(fixture, root, ledger, should_observe):
    setup = {
        "trump_rank": fixture.setup["trump_rank"],
        "banker": int(fixture.setup["banker"]),
        "declarations": [{"seat": int(d["seat"]), "cards": list(d["cards"])}
                         for d in fixture.setup["declarations"]],
        "trump_suit": fixture.setup.get("trump_suit"),
        "trump_is_nt": bool(fixture.setup.get("trump_is_nt")),
        "buried": list(root.buried),
    }
    replay = tactical.round_from_setup(list(root.deck), setup)
    observations = []
    for index, play in enumerate(fixture.plays):
        if should_observe(index, replay.turn):
            ledger.observe(replay)
            observations.append({"play_index": index, "seat": replay.turn})
        tactical._replay_public(replay, [play], fixture.seat)
    # Ordering has identity equality; compare its value fields separately.
    expected, actual = dict(vars(root)), dict(vars(replay))
    expected["ordering"] = vars(root.ordering)
    actual["ordering"] = vars(replay.ordering)
    if expected != actual:
        raise ValueError("history replay differs from the final public root")
    return observations


def public_root_with_ledger(fixture, *, mode, fill_seed=0):
    """Return (public root, ledger, mode receipt) without models or sampling.

    ``fresh-root`` observes only the currently posted notice. ``history-primed``
    observes at this actor's decision turns while replaying the identical deck;
    it does NOT inject every failed throw ever recorded. No RNG/model policy
    state is reconstructed, so this is not a full live-bot state restoration.
    """
    if mode not in ("fresh-root", "history-primed"):
        raise ValueError("explicit fresh-root or history-primed mode required")
    if type(fill_seed) is not int or fill_seed < 0:
        raise ValueError("fill_seed must be a nonnegative integer")
    tactical.validate_fixture(fixture)
    root = tactical.public_round(fixture, fill_seed)
    ledger = RefusalLedger()
    observations = 0
    if mode == "history-primed":
        observations = len(_observe_history(
            fixture, root, ledger, lambda index, seat: seat == fixture.seat))
    refusals = ledger.observe(root)
    observations += 1
    return root, ledger, {
        "schema": "public-refusal-ledger-v1",
        "fixture_id": fixture.id,
        "mode": mode,
        "fill_seed": fill_seed,
        "actor_turn_observations": observations,
        "retained_refusals": [asdict(refusal) for refusal in refusals],
        "hidden_hands_are_placeholders": True,
        "live_rng_state_reconstructed": False,
        "provenance_verified": False,
    }


def public_root_with_observation_schedule(fixture, *, observed_play_indices, fill_seed=0):
    """Reconstruct a caller-declared observation schedule, then observe the root.

    Indices identify observations BEFORE zero-based accepted historical plays.
    They must describe committed observations of one persistent bot instance;
    seat ownership alone does not prove observation (errors or discarded turn
    snapshots can intervene). Empty means no historical observations. The final
    decision-root observation is always separate. No ownership is inferred and
    no claim is made that the supplied schedule matches an actual online room.
    """
    if type(fill_seed) is not int or fill_seed < 0:
        raise ValueError("fill_seed must be a nonnegative integer")
    tactical.validate_fixture(fixture)
    if type(observed_play_indices) not in (list, tuple):
        raise ValueError("observed_play_indices must be an explicit list or tuple")
    indices = list(observed_play_indices)
    if any(type(i) is not int or not 0 <= i < len(fixture.plays) for i in indices):
        raise ValueError("observation indices must be historical play indices")
    if any(a >= b for a, b in zip(indices, indices[1:])):
        raise ValueError("observation indices must be strictly increasing and unique")
    root = tactical.public_round(fixture, fill_seed)
    ledger = RefusalLedger()
    selected = set(indices)
    observations = _observe_history(
        fixture, root, ledger, lambda index, seat: index in selected)
    refusals = ledger.observe(root)
    return root, ledger, {
        "schema": "public-refusal-observation-schedule-v1",
        "fixture_id": fixture.id,
        "fill_seed": fill_seed,
        "historical_observations": observations,
        "final_root_observation": {"play_index": len(fixture.plays), "seat": root.turn},
        "retained_refusals": [asdict(refusal) for refusal in refusals],
        "hidden_hands_are_placeholders": True,
        "live_rng_state_reconstructed": False,
        "provenance_verified": False,
        "observation_schedule_verified": False,
    }
