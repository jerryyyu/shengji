"""Project a validated S11 trajectory into the existing public-fixture path.

No sampler, predictor, artifact access or collection is invoked. The caller
authenticates/normalizes the shard and freezes the position first. An unsupported
public rebuild is a scheduled-root refusal, never permission to replace it.
"""
import copy
from collections import Counter
from dataclasses import asdict

from .s11_reconstruction import reconstruct_s11_trajectory
from .public_refusal_history import public_root_with_ledger
from .tactical import public_fixture


def public_s11_fixture(rows, selected_ply, *, root_id, fill_seed=0):
    """Return an actor-scoped fixture, without private trajectory metadata.

    Validate the full mirror to terminal before projecting the chosen prefix.
    Reuse public-fixture reconstruction to prove that the same retained refusal
    notices survive. Observation cadence is PVC's per-seat decision cadence,
    not the production room-shared bot cadence. Full deck, original deal seed,
    other hands, non-banker burial, future actions and labels are never exported.

    The existing public rebuild does not support undeclared kitty-flip roots;
    it raises explicitly. Neither omit these roots from a scheduled report nor
    draw a replacement. Broader population support remains an integration gate.
    """
    if type(root_id) is not str or not root_id:
        raise ValueError("nonempty opaque root_id required")
    if type(fill_seed) is not int or fill_seed < 0:
        raise ValueError("fill_seed must be a nonnegative integer")
    rebuilt = reconstruct_s11_trajectory(rows, selected_ply)
    root, seat = rebuilt['root'], rebuilt['actor_seat']
    plays = []
    for row in rows[:selected_ply]:
        actual = row.get('engine_play', row['action'])
        play = {'seat': row['seat'], 'cards': list(actual)}
        if Counter(actual) != Counter(row['action']):
            play['attempted'] = list(row['action'])
        plays.append(play)
    fixture = public_fixture(
        root, seat, plays, copy.deepcopy(rows[0]['setup'].get('declarations') or []),
        id=root_id, category='observation',
        source={'kind': 's11-public-projection', 'cadence': 'per-seat-decision'},
        observed={}, predicate='observe_follow',
        why='Outcome-blind scheduled S11 decision; not a known-mistake label.')
    public_root, ledger, receipt = public_root_with_ledger(
        fixture, mode='history-primed', fill_seed=fill_seed)
    expected = [asdict(r) for r in rebuilt['ledger'].refusals]
    if receipt['retained_refusals'] != expected:
        raise ValueError('public projection changed retained refusal history')
    if (public_root.turn != seat or
            Counter(public_root.hands[seat]) != Counter(root.hands[seat])):
        raise ValueError('public projection changed actor state')
    return fixture
