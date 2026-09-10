"""Fresh DEV bury positions and a shared-world value/MC diagnostic.

Saved setup/deck are reconstruction evidence, never model features. The
decision pipeline samples opponents anew from banker-visible information.
"""
from __future__ import annotations

import hashlib
import random
import time

import numpy as np

from ..ai.cwv_policy import sample_worlds
from ..ai.registry import make_bot
from ..engine.cards import RANKS
from ..engine.game import Game
from ..engine.round import Round
from ..harvest.rebuild import round_from_setup, setup_from_round

SCHEMA = "cwv-bury-state-v1"
NAMESPACE = "cwv-bury-dev-20260909-panel-v1"
ALLRANK_POPULATION = "all-ranks-known-banker-v1"
ALLRANK_NAMESPACE = "cwv-bury-allrank-confirm-20260909-v1"


def derived_seed(label: str, index: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{label}:{index}".encode()).digest()[:8], "big") >> 1


def capture_state(index: int) -> dict:
    seed = derived_seed(NAMESPACE, index)
    rnd = Game(random.Random(seed)).start_round()
    bots = [make_bot("mc-s0-report-lcb", seed=derived_seed(f"{NAMESPACE}:declare:{index}", s))
            for s in range(4)]
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    setup = setup_from_round(rnd)
    setup["declarations"] = declarations
    row = {"schema": SCHEMA, "index": index, "seed": seed,
           "namespace": NAMESPACE, "deck": list(rnd.deck), "setup": setup,
           "banker_hand": list(rnd.hands[rnd.banker]),
           "declaration_policy": "mc-s0-report-lcb"}
    reopened = reopen_state(row)
    if reopened.hands != rnd.hands:
        raise ValueError("saved bury setup changed dealt hands or their order")
    return row


def _capture_state(index: int, *, namespace: str, root) -> dict:
    """Capture one already-known-banker root using the natural declaration loop."""
    seed = derived_seed(namespace, index)
    rnd = root(seed)
    initial_banker = rnd.banker
    bots = [make_bot("mc-s0-report-lcb", seed=derived_seed(
        f"{namespace}:declare:{index}", s)) for s in range(4)]
    declarations = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    setup = setup_from_round(rnd)
    setup["declarations"] = declarations
    row = {"schema": SCHEMA, "population": ALLRANK_POPULATION,
           "index": index, "seed": seed, "namespace": namespace,
           "initial_banker": initial_banker, "deck": list(rnd.deck),
           "setup": setup, "banker_hand": list(rnd.hands[rnd.banker]),
           "declaration_policy": "mc-s0-report-lcb"}
    reopened = reopen_state(row)
    if reopened.hands != rnd.hands:
        raise ValueError("saved bury setup changed dealt hands or their order")
    if reopened.banker != initial_banker:
        raise ValueError("known banker changed after declaration")
    return row


def capture_allrank_state(index: int) -> dict:
    """Capture a fresh all-rank, all-known-banker natural deal root."""
    if index < 0:
        raise ValueError("all-rank state index must be nonnegative")
    rank = RANKS[index % len(RANKS)]
    banker = (index // len(RANKS)) % 4
    return _capture_state(
        index, namespace=ALLRANK_NAMESPACE,
        root=lambda seed: Round(rank, banker, random.Random(seed)))


def reopen_state(row: dict):
    if row.get("schema") != SCHEMA:
        raise ValueError("bury state schema/namespace mismatch")
    allrank = row.get("population") == ALLRANK_POPULATION
    namespace = ALLRANK_NAMESPACE if allrank else NAMESPACE
    if row.get("namespace") != namespace:
        raise ValueError("bury state schema/namespace mismatch")
    if row["seed"] != derived_seed(namespace, row["index"]):
        raise ValueError("bury state seed binding mismatch")
    if allrank:
        expected_rank = RANKS[row["index"] % len(RANKS)]
        expected_banker = (row["index"] // len(RANKS)) % 4
        if row.get("initial_banker") != expected_banker:
            raise ValueError("all-rank derived banker binding mismatch")
        if row.get("setup", {}).get("trump_rank") != expected_rank:
            raise ValueError("all-rank derived rank binding mismatch")
        expected_deck = Round(expected_rank, expected_banker,
                              random.Random(row["seed"])).deck
    else:
        expected_deck = Game(random.Random(row["seed"])).start_round().deck
    if expected_deck != row["deck"]:
        raise ValueError("bury state deck binding mismatch")
    rnd = round_from_setup(row["deck"], row["setup"], stop_before_bury=True)
    if allrank and rnd.banker != row["initial_banker"]:
        raise ValueError("known banker changed after declaration")
    if rnd.hands[rnd.banker] != row["banker_hand"]:
        raise ValueError("bury banker hand reconstruction mismatch")
    return rnd


def pick_mc(points, bot, eligible):
    """Keep existing MC bury's objective, stable ties and incumbent margin."""
    eligible = list(eligible)
    if not eligible or eligible[0] != 0:
        raise ValueError("MC bury shortlist must retain incumbent first")
    scores = np.asarray([[-bot._score(float(p)) for p in row] for row in points])
    means = scores.mean(axis=0)
    best = max(eligible, key=lambda i: (float(means[i]), -i))
    return 0 if means[best] - means[0] < bot.MARGIN else best


def diagnose(row: dict, evaluator, *, model_worlds=32, reference_worlds=256,
             selection_worlds=32, alternatives=4) -> dict:
    from .cwv_bury import bury_candidates, score_bury_candidates, rollout_bury_values
    if min(model_worlds, selection_worlds, alternatives) < 1 or reference_worlds <= selection_worlds:
        raise ValueError("diagnostic needs positive doses and an independent reference tail")
    started = time.perf_counter()
    rnd = reopen_state(row)
    bot = make_bot("mc-s0-report-lcb", seed=derived_seed(f"{NAMESPACE}:model", row["index"]))
    candidates = bury_candidates(rnd, bot)
    model_draws, model_attempts = sample_worlds(bot, rnd, rnd.banker, model_worlds)
    if len(model_draws) != model_worlds:
        raise ValueError("model-world sample underfill")
    model_matrix = score_bury_candidates(rnd, candidates, model_draws, evaluator,
                                        first_trick_policy=bot.rollout_policy)
    model_seconds = time.perf_counter() - started
    reference_bot = make_bot("mc-s0-report-lcb", seed=derived_seed(f"{NAMESPACE}:reference", row["index"]))
    reference_draws, reference_attempts = sample_worlds(reference_bot, rnd, rnd.banker, reference_worlds)
    if len(reference_draws) != reference_worlds:
        raise ValueError("reference-world sample underfill")
    utility, points = rollout_bury_values(rnd, candidates, reference_draws, reference_bot)
    means = np.mean(model_matrix, axis=0)
    order = sorted(range(len(candidates)), key=lambda i: (-float(means[i]), i))
    kept = [0] + [i for i in order if i != 0][:alternatives]
    evaluation = np.mean(utility[selection_worlds:], axis=0)
    mc_pick = pick_mc(points[:selection_worlds], reference_bot, range(len(candidates)))
    hybrid_pick = pick_mc(points[:selection_worlds], reference_bot, kept)
    return {
        "schema": "cwv-bury-diagnostic-v1", "cluster": row["index"],
        "state": row, "checkpoint_sha256": evaluator.checkpoint_sha256,
        "candidates": candidates, "model_values": model_matrix.tolist(),
        "reference_values": utility.tolist(), "reference_attacker_points": points.tolist(),
        "model_worlds": model_worlds, "reference_worlds": reference_worlds,
        "selection_worlds": selection_worlds, "model_attempts": model_attempts,
        "reference_attempts": reference_attempts, "shortlist": kept,
        "mc_objective": "negative bot._score(attacker_points), existing incumbent margin",
        "mc_margin": reference_bot.MARGIN, "mc_level_objective": reference_bot.LEVEL_OBJECTIVE,
        "model_seconds": model_seconds,
        "model_leaf": "after one heuristic-continuation trick",
        "immediate_post_bury": "unsupported: frozen encoder rejects zero played-card history",
        "picks": {"heuristic": 0, "model": order[0], "mc": mc_pick, "hybrid": hybrid_pick},
        "independent_reference_gain_vs_heuristic": {
            name: float(evaluation[i] - evaluation[0])
            for name, i in (("model", order[0]), ("mc", mc_pick), ("hybrid", hybrid_pick))},
        "scope": "natural rank2 DEV bury roots; sampled opponents; heuristic-continuation reference, not optimal play",
        "wall_seconds": time.perf_counter() - started,
    }
