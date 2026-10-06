"""Verify a structured rollout rejection, without accepting or scoring it.

The caller must authenticate the mirror and supplied evidence bytes against
its reviewed source pins. This checks their internal join and independently
rechecks legality; hashes supplied by an unauthenticated caller are not proof
of provenance. Historical unbound diagnostics require a separate adapter.
No files, model calls, retries, rollouts, or protocol amendments occur here.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from shengji.engine.cards import Ordering, RANKS, SUITS, make_deck
from shengji.engine.legal import IllegalPlay, validate_follow, validate_lead

from .canonical import canonical_json_bytes
from .game import MAX_NEW_EVALUATIONS_PER_CALL, MAX_ROLLOUT_CALLS_PER_DECISION
from .benchmark_retention import _json, _strict_equal


_CARDS = frozenset(make_deck())
_DIAGNOSTIC = {
    "schema", "stage", "error_type", "seat", "request_index",
    "evaluation_index", "cards", "continuation", "completed_play_events",
}
_BINDING = {
    "schema", "seat", "request_index", "evaluation_index",
    "observation_sha256", "packet_sha256", "reply_sha256", "completed_play_events",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _integer(value: Any, low: int, high: int, label: str) -> int:
    _require(type(value) is int and low <= value <= high, f"invalid {label}")
    return value


def _cards(value: Any, label: str) -> list[str]:
    _require(type(value) is list and all(type(c) is str and c in _CARDS for c in value),
             f"invalid {label} cards")
    return value


def _play_seats(trick: Any, *, completed: bool) -> list[int]:
    _require(type(trick) is dict, "missing trick context")
    plays = trick.get("plays")
    _require(type(plays) is list and (len(plays) == 4 if completed else len(plays) < 4),
             "invalid recorded trick size")
    leader = _integer(trick.get("leader"), 0, 3, "leader")
    seats = []
    for index, play in enumerate(plays):
        _require(type(play) is dict and type(play.get("seat")) is int
                 and play["seat"] == (leader + index) % 4, "invalid recorded trick order")
        _require(bool(_cards(play.get("cards"), "trick")), "empty recorded play")
        seats.append(play["seat"])
    return seats


def verify_rollout_rejection(row: dict, *, packet_bytes: bytes,
                             final_bytes: bytes) -> dict:
    """Join a failed mirror's structured bindings and recheck its candidate.

    A successful return is evidence of an IllegalPlay in the authenticated
    recorded context, NOT a terminal disposition, forfeit, or retry authority.
    Only feedback-OFF validation failures from the structured producer qualify.
    """
    _require(type(row) is dict and row.get("complete") is False,
             "proof requires an incomplete mirror")
    _require(row.get("invalid_action_feedback") is False,
             "proof requires explicit feedback OFF")
    _require("failure" not in row and "signed_levels" not in row,
             "proof cannot reinterpret a scored or classified row")
    diagnostic, binding = row.get("rollout_diagnostic"), row.get("rollout_request_binding")
    _require(type(diagnostic) is dict and set(diagnostic) == _DIAGNOSTIC,
             "missing or malformed rollout diagnostic")
    _require(type(binding) is dict and set(binding) == _BINDING,
             "missing or malformed rollout request binding")
    _require(diagnostic["schema"] == "benchmark-rollout-diagnostic-v1"
             and diagnostic["stage"] == "rollout_validate"
             and diagnostic["error_type"] == "IllegalPlay",
             "only engine validation IllegalPlay can qualify")
    _require(binding["schema"] == "benchmark-rollout-request-binding-v1",
             "invalid request binding schema")
    seat = _integer(diagnostic["seat"], 0, 3, "seat")
    request = _integer(diagnostic["request_index"], 0, MAX_ROLLOUT_CALLS_PER_DECISION - 1,
                       "request index")
    evaluation = _integer(diagnostic["evaluation_index"], 0, MAX_NEW_EVALUATIONS_PER_CALL - 1,
                          "evaluation index")
    events = row.get("events")
    _require(type(events) is list, "missing completed play events")
    event_seats = []
    for event in events:
        _require(type(event) is dict, "invalid recorded event")
        event_seats.append(_integer(event.get("seat"), 0, 3, "event seat"))
        _require(bool(_cards(event.get("attempted_cards"), "event")),
                 "empty recorded event action")
    completed = _integer(diagnostic["completed_play_events"], 0, len(events),
                         "completed play events")
    _require(completed == len(events), "completed play event count drift")
    for key in ("seat", "request_index", "evaluation_index", "completed_play_events"):
        _require(_strict_equal(binding[key], diagnostic[key]), f"binding {key} drift")
    flip = _integer(row.get("flip"), 0, 1, "flip")
    _require(seat % 2 == flip, "diagnostic is not the model partnership")
    _require(type(packet_bytes) is bytes and type(final_bytes) is bytes,
             "evidence must be exact bytes")
    packet_sha = hashlib.sha256(packet_bytes).hexdigest()
    final_sha = hashlib.sha256(final_bytes).hexdigest()
    _require(binding["packet_sha256"] == packet_sha, "packet hash drift")
    packet, final = _json(packet_bytes, "packet"), _json(final_bytes, "final")
    _require(type(packet) is dict, "packet must be an object")
    _require(type(final) is dict and set(final) == {"cards", "evaluations", "memory"}
             and final["cards"] is None and type(final["memory"]) is str,
             "final is not a rollout request")
    evaluations = final["evaluations"]
    _require(type(evaluations) is list
             and 1 <= len(evaluations) <= MAX_NEW_EVALUATIONS_PER_CALL
             and evaluation < len(evaluations), "evaluation is outside request")
    reply_sha = hashlib.sha256(canonical_json_bytes(
        {"evaluations": evaluations, "memory": final["memory"]})).hexdigest()
    _require(binding["reply_sha256"] == reply_sha, "normalized reply hash drift")
    expected_response = {
        "schema": "benchmark-response-binding-v1", "packet_sha256": packet_sha,
        "final_sha256": final_sha, "reply_sha256": reply_sha,
    }
    calls = row.get("calls")
    _require(type(calls) is list and all(type(c) is dict for c in calls),
             "missing call receipts")
    matches = [c for c in calls if _strict_equal(c.get("response_binding"), expected_response)]
    _require(len(matches) == 1 and matches[0].get("accepted") is True,
             "response must have one accepted receipt binding")
    selected = evaluations[evaluation]
    _require(type(selected) is dict and set(selected) == {"cards", "continuation"},
             "malformed selected evaluation")
    cards = _cards(selected["cards"], "evaluation")
    _require(_strict_equal(cards, diagnostic["cards"])
             and type(selected["continuation"]) is str
             and selected["continuation"] == diagnostic["continuation"],
             "diagnostic does not identify the selected evaluation")
    _require(type(packet.get("rollout_calls_remaining")) is int
             and packet["rollout_calls_remaining"] == MAX_ROLLOUT_CALLS_PER_DECISION - request,
             "request index does not match packet budget")
    observation = packet.get("observation")
    _require(type(observation) is dict
             and observation.get("schema") == "w32-llm-seat-observation-v1",
             "missing seat observation")
    exposed = dict(observation)
    observation_sha = exposed.pop("observation_sha256", None)
    _require(observation_sha == binding["observation_sha256"]
             and observation_sha == hashlib.sha256(canonical_json_bytes(exposed)).hexdigest(),
             "observation hash drift")
    _require(type(observation.get("seat")) is int and observation["seat"] == seat,
             "observation seat drift")
    _require(observation.get("information") in ("actor-only", "perfect")
             and observation["information"] == row.get("information"), "information mode drift")
    hand = _cards(observation.get("own_hand"), "hand")
    _require(all(n <= 2 for n in Counter(hand).values()), "invalid hand multiplicities")
    suit, rank = observation.get("trump_suit"), observation.get("trump_rank")
    _require((suit is None or type(suit) is str and suit in SUITS and len(suit) == 1)
             and type(rank) is str and rank in RANKS, "invalid recorded ordering")
    _require(type(observation.get("trump_is_nt")) is bool
             and observation["trump_is_nt"] == (suit is None), "inconsistent no-trump context")
    history, trick = observation.get("history"), observation.get("current_trick")
    _require(type(history) is list and type(trick) is dict, "missing trick context")
    public_seats = [s for past in history for s in _play_seats(past, completed=True)]
    public_seats.extend(_play_seats(trick, completed=False))
    plays = trick["plays"]
    leader = _integer(trick.get("leader"), 0, 3, "leader")
    _require((leader + len(plays)) % 4 == seat, "acting seat does not follow trick order")
    _require(4 * len(history) + len(plays) == completed, "observation decision coordinate drift")
    # Compare actors, not attempted-vs-committed cards: a legal lead throw
    # may be reduced by the engine before it reaches public trick history.
    _require(public_seats == event_seats, "recorded event seat sequence drift")
    ordering = Ordering(suit, rank)
    validation = "follow" if plays else "lead"
    try:
        if plays:
            validate_follow(cards, hand, plays[0]["cards"], ordering)
        else:
            validate_lead(cards, hand, [], ordering)
    except IllegalPlay:
        pass
    else:
        raise ValueError("candidate is legal in the recorded context")
    return {
        "schema": "benchmark-rollout-rejection-proof-v1", "seat": seat,
        "request_index": request, "evaluation_index": evaluation,
        "completed_play_events": completed, "cards": list(cards),
        "continuation": selected["continuation"], "validation": validation,
        "packet_sha256": packet_sha, "final_sha256": final_sha,
        "reply_sha256": reply_sha, "observation_sha256": observation_sha,
    }
