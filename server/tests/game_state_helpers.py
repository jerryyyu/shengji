"""Shared game-state construction helpers for tests."""

import random

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game


def pair_ruff_control_state():
    """Artificial eight-card control witness, not a sampled production state."""
    from shengji.engine.cards import Ordering
    from shengji.engine.round import Round, Trick

    rnd = Round("2", banker=0, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("S", "2")
    rnd.trump_suit = "S"
    rnd.trump_is_nt = False
    rnd.hands = [
        ["SA", "HA", "HA", "HK", "HK", "D3", "C3", "S3"],
        ["SQ", "H9", "H9", "D5", "D5", "C5", "C5", "S4"],
        ["S2", "S2", "HQ", "HQ", "D6", "D6", "C6", "C6"],
        ["S10", "S10", "H10", "H10", "D7", "D7", "C7", "C7"],
    ]
    rnd.buried = []
    rnd.attacker_points = 0
    rnd.trick = Trick(leader=0)
    rnd.turn = 0
    return rnd


def state_after(seed: int, plies: int):
    """Build a fresh complete-world round after up to ``plies`` SmartBot plays.

    Each call owns its seeded RNG, bots, hands and history. Never cache the
    returned mutable round or share it across tests.
    """
    game = Game(random.Random(seed))
    rnd = game.start_round()
    bots = [SmartBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    for _ in range(plies):
        if rnd.phase != "play":
            break
        seat = rnd.turn
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
    return rnd
