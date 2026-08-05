"""Versioned, exact replay for raw state-reservoir rows.

Deep-lead capture stores accepted declarations at the deal position where they
occurred.  Replaying those events is deliberately independent of whichever bot
happens to be registered today; regenerating declarations with a new policy is
not replay, even when it happens to land on the same trump.
"""
from __future__ import annotations

import random

from .engine.game import Game


DEEP_LEAD_STATE_SCHEMA = "deep-lead-state-v1"


def replay_deep_lead(row: dict):
    """Rebuild one ``deep-lead-state-v1`` row and verify every stored boundary."""
    if row.get("schema") != DEEP_LEAD_STATE_SCHEMA:
        raise ValueError(f"unsupported deep-lead schema {row.get('schema')!r}")
    setup = row["setup"]
    seed = int(row["seed"])
    game = Game(random.Random(seed))
    rnd = game.start_round()
    if list(rnd.deck) != list(setup["deck"]):
        raise ValueError("deep-lead deck does not reproduce from its seed")
    if rnd.banker != setup.get("initial_banker"):
        raise ValueError("deep-lead initial banker mismatch")
    if rnd.trump_rank != setup["trump_rank"]:
        raise ValueError("deep-lead initial trump rank mismatch")

    events = list(setup["declarations"])
    event_i = 0
    while rnd.phase == "deal":
        rnd.deal_next()
        while event_i < len(events) and events[event_i]["stage"] == "deal":
            event = events[event_i]
            if event["deal_pos"] < rnd._deal_pos:
                raise ValueError("deep-lead declaration was not replayed in order")
            if event["deal_pos"] != rnd._deal_pos:
                break
            rnd.declare(event["seat"], list(event["cards"]))
            event_i += 1
    if event_i < len(events) and events[event_i]["stage"] == "deal":
        raise ValueError("deep-lead declaration lies beyond the deal")
    while event_i < len(events):
        event = events[event_i]
        if event["stage"] != "final" or event["deal_pos"] != rnd._deal_pos:
            raise ValueError("invalid final declaration event")
        rnd.declare(event["seat"], list(event["cards"]))
        event_i += 1

    rnd.finalize_declare()
    if rnd.banker != setup["banker"]:
        raise ValueError("deep-lead banker mismatch after declarations")
    if rnd.trump_suit != setup["trump_suit"]:
        raise ValueError("deep-lead trump suit mismatch")
    if rnd.trump_is_nt != setup["trump_is_nt"]:
        raise ValueError("deep-lead no-trump flag mismatch")
    stored_decl = setup.get("final_declaration")
    live_decl = None if rnd.declaration is None else {
        "seat": rnd.declaration["seat"],
        "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }
    if live_decl != stored_decl:
        raise ValueError("deep-lead final declaration mismatch")

    rnd.bury(rnd.banker, list(setup["buried"]))
    for play in row["plays"]:
        if rnd.turn != play["seat"]:
            raise ValueError("deep-lead play order mismatch")
        rnd.play(play["seat"], list(play["cards"]))

    if len(row["plays"]) != row["ply"]:
        raise ValueError("deep-lead ply count mismatch")
    if len(rnd.history) != row["trick"]:
        raise ValueError("deep-lead trick index mismatch")
    if rnd.phase != "play" or rnd.trick is None or rnd.trick.plays:
        raise ValueError("deep-lead replay did not land at a lead state")
    if rnd.turn != row["seat"]:
        raise ValueError("deep-lead replay landed on the wrong seat")
    role = "attacker" if rnd.is_attacker(rnd.turn) else "defender"
    if role != row["role"]:
        raise ValueError("deep-lead leader role mismatch")
    return rnd
