"""Explicit diagnostic ledger reconstruction; never changes serving defaults.

Uses only the fixture's public plays and actor hand. Returned hidden hands are
placeholders, NOT a sampled world or model input. Callers must declare the mode
in their reviewed packet and bind the returned root and ledger together.
"""
from dataclasses import asdict

from ..ai.refusal import RefusalLedger
from . import tactical


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
        for play in fixture.plays:
            if replay.turn == fixture.seat:
                ledger.observe(replay)
                observations += 1
            tactical._replay_public(replay, [play], fixture.seat)
        # Compare all Round fields; Ordering has identity equality, so compare
        # its value fields separately. Drift in public reconstruction fails closed.
        expected, actual = dict(vars(root)), dict(vars(replay))
        expected["ordering"] = vars(root.ordering)
        actual["ordering"] = vars(replay.ordering)
        if expected != actual:
            raise ValueError("history replay differs from the final public root")
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
