"""Shared game-state construction helpers for tests."""

import random

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game


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
