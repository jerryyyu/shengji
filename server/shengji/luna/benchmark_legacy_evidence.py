"""Audit old perfect-information rollout evidence, without disposition.

The caller must authenticate the pins manifest and its association with the
reviewed source/run. Self-supplied hashes are not provenance. This adapter
checks exact supplied bytes, call/event joins and engine legality; it does
not manufacture modern producer bindings, rewrite a mirror, or approve a
forfeit/retry. No files, providers, world sampling or continuations are used.
"""
from __future__ import annotations

import hashlib
from collections import Counter

from shengji.engine.cards import Ordering, RANKS, SUITS
from shengji.engine.legal import IllegalPlay, validate_follow, validate_lead

from .benchmark_retention import _json, _strict_equal
from .benchmark_rollout_proof import _cards, _integer, _play_seats, _require
from .canonical import canonical_json_bytes


SOURCE_COMMIT = "c53ec3bc2852ce4eefa22173dc88777fdb914e94"
# SHA256 of the prompt prefix (including newline) in this source's
# BenchmarkTransport.__call__. The suffix is canonical packet JSON.
PROMPT_PREFIX_SHA256 = "98ac98f9bcee19b7cebb82ba186d400a119f45d6b52b493468cc567f4cd30a00"
# Frozen source vocabulary, not whatever a future producer may add.
_CONTINUATIONS = frozenset(("heuristic-all", "smart-all", "team-smart",
                            "opponent-smart", "exact-endgame-smart"))


def _hash(raw):
    _require(type(raw) is bytes, "evidence must be exact bytes")
    return hashlib.sha256(raw).hexdigest()


def _context(packet, events, flip):
    obs = packet.get("observation")
    _require(type(obs) is dict and obs.get("schema") == "w32-llm-seat-observation-v1"
             and obs.get("information") == "perfect", "legacy audit requires perfect observation")
    exposed = dict(obs)
    digest = exposed.pop("observation_sha256", None)
    _require(digest == _hash(canonical_json_bytes(exposed)), "observation digest drift")
    seat = _integer(obs.get("seat"), 0, 3, "seat")
    _require(seat % 2 == flip, "call is not from model partnership")
    history, trick = obs.get("history"), obs.get("current_trick")
    _require(type(history) is list and type(trick) is dict, "missing public context")
    actors = [s for past in history for s in _play_seats(past, completed=True)]
    actors.extend(_play_seats(trick, completed=False))
    coordinate = len(actors)
    _require(coordinate <= len(events) and actors == [e["seat"] for e in events[:coordinate]],
             "call does not match recorded event prefix")
    _require((trick["leader"] + len(trick["plays"])) % 4 == seat,
             "observation is not acting seat")
    hand = _cards(obs.get("own_hand"), "hand")
    _require(all(n <= 2 for n in Counter(hand).values()), "invalid hand multiplicities")
    suit, rank = obs.get("trump_suit"), obs.get("trump_rank")
    _require((suit is None or type(suit) is str and suit in SUITS and len(suit) == 1)
             and type(rank) is str and rank in RANKS, "invalid ordering")
    _require(type(obs.get("trump_is_nt")) is bool
             and obs["trump_is_nt"] == (suit is None), "no-trump drift")
    request = 2 - _integer(packet.get("rollout_calls_remaining"), 0, 2, "request budget")
    _require(type(packet.get("rollout_results")) is list, "missing local rollout results")
    return seat, coordinate, request, obs


def _legal(cards, obs):
    ordering = Ordering(obs["trump_suit"], obs["trump_rank"])
    plays = obs["current_trick"]["plays"]
    try:
        if plays:
            validate_follow(cards, obs["own_hand"], plays[0]["cards"], ordering)
        else:
            validate_lead(cards, obs["own_hand"], [], ordering)
    except IllegalPlay:
        return False
    return True


def audit_legacy_rollout_failure(row_bytes, *, evidence, pins):
    """Infer one pre-validation failure from an exact legacy call inventory.

    Only the frozen c53ec3bc perfect/feedback-OFF producer contract is handled.
    Rejected transport attempts remain in the pinned row but are not counted
    as returned evaluations. All accepted calls require prompt/final pins.
    A return is a separate legacy audit, not a modern rejection-proof receipt.
    """
    _require(type(pins) is dict and set(pins) == {
        "schema", "source_commit", "row_sha256", "calls"}, "invalid pins manifest")
    _require(pins["schema"] == "benchmark-legacy-evidence-pins-v1"
             and pins["source_commit"] == SOURCE_COMMIT, "unsupported legacy source")
    row_sha = _hash(row_bytes)
    _require(row_sha == pins["row_sha256"], "mirror hash drift")
    row = _json(row_bytes, "legacy mirror")
    _require(type(row) is dict and row.get("complete") is False
             and row.get("invalid_action_feedback") is False
             and row.get("information") == "perfect" and row.get("status") is None,
             "requires incomplete feedback-OFF perfect mirror")
    # Corroborate the frozen producer's terminal state; this text alone is
    # never proof (the byte/counter/context joins and legality check follow).
    _require(type(row.get("error")) is str and row["error"].startswith("IllegalPlay:"),
             "legacy terminal error does not match legality rejection")
    _require(not any(k in row for k in ("failure", "signed_levels", "rollout_diagnostic",
                                       "rollout_request_binding")), "not an unclassified legacy row")
    flip = _integer(row.get("flip"), 0, 1, "flip")
    events, calls = row.get("events"), row.get("calls")
    _require(type(events) is list and type(calls) is list and calls, "missing mirror evidence")
    for event in events:
        _require(type(event) is dict, "invalid event")
        _integer(event.get("seat"), 0, 3, "event seat")
        _require(bool(_cards(event.get("attempted_cards"), "event")), "empty event")
    accepted, all_paths = {}, set()
    for call in calls:
        _require(type(call) is dict and type(call.get("accepted")) is bool,
                 "invalid call receipt")
        path = call.get("evidence_path")
        _require(type(path) is str and path and path not in all_paths, "duplicate or missing call path")
        all_paths.add(path)
        _require("response_binding" not in call, "not a legacy response receipt")
        if call["accepted"]:
            accepted[path] = call
    _require(type(evidence) is dict and type(pins["calls"]) is dict
             and set(evidence) == set(pins["calls"]) == set(accepted),
             "accepted-call evidence coverage drift")
    inventory = []
    for path in accepted:
        blobs, binding = evidence[path], pins["calls"][path]
        _require(type(blobs) is dict and set(blobs) == {"prompt_bytes", "final_bytes"}
                 and type(binding) is dict and set(binding) == {"prompt_sha256", "final_sha256"},
                 "invalid call byte pins")
        _require(_hash(blobs["prompt_bytes"]) == binding["prompt_sha256"]
                 and _hash(blobs["final_bytes"]) == binding["final_sha256"], "call hash drift")
        prefix, separator, raw_packet = blobs["prompt_bytes"].partition(b"\n")
        _require(separator and _hash(prefix + separator) == PROMPT_PREFIX_SHA256,
                 "historical prompt prefix drift")
        packet = _json(raw_packet, "legacy packet")
        _require(type(packet) is dict and canonical_json_bytes(packet) == raw_packet,
                 "noncanonical legacy packet")
        seat, coordinate, request, obs = _context(packet, events, flip)
        final = _json(blobs["final_bytes"], "legacy final")
        _require(type(final) is dict and set(final) == {"cards", "evaluations", "memory"}
                 and type(final["memory"]) is str
                 and (final["cards"] is None) != (final["evaluations"] is None),
                 "invalid legacy final reply")
        if final["cards"] is None:
            evaluations = final["evaluations"]
            _require(request < 2 and type(evaluations) is list and 1 <= len(evaluations) <= 16,
                     "invalid evaluation batch")
            for item in evaluations:
                _require(type(item) is dict and set(item) == {"cards", "continuation"}
                         and type(item["continuation"]) is str
                         and item["continuation"] in _CONTINUATIONS, "invalid evaluation")
                _cards(item["cards"], "evaluation")
        else:
            _cards(final["cards"], "final")
        inventory.append((coordinate, request, seat, path, packet, final, obs))
    inventory.sort(key=lambda call: call[:2])
    _require(inventory and len({call[:2] for call in inventory}) == len(inventory),
             "ambiguous call coordinates")
    expected_coordinates = {i for i, event in enumerate(events) if event["seat"] % 2 == flip}
    expected_coordinates.add(len(events))
    _require({call[0] for call in inventory} == expected_coordinates, "model decision coverage drift")
    usage = row.get("rollout_usage")
    _require(type(usage) is dict and set(usage) == {
        "requested_batches", "attempted_evaluations", "completed_evaluations",
        "completed_world_rollouts"}, "missing aggregate rollout counts")
    for key, value in usage.items():
        _integer(value, 0, 100000, key)
    completed, batches = 0, 0
    selected = None
    for coordinate in sorted(expected_coordinates):
        group = [call for call in inventory if call[0] == coordinate]
        _require([call[1] for call in group] == list(range(len(group))), "request sequence gap")
        local = []
        for index, (_, request, seat, path, packet, final, obs) in enumerate(group):
            _require(_strict_equal(obs, group[0][6]), "observation changed within decision")
            results = packet["rollout_results"]
            _require(len(results) == len(local), "decision-local result count drift")
            for result, evaluation in zip(results, local):
                _require(type(result) is dict and _strict_equal(result.get("cards"), evaluation["cards"])
                         and result.get("continuation") == evaluation["continuation"]
                         and type(result.get("worlds")) is int and result["worlds"] == 1,
                         "decision-local result join drift")
            terminal = coordinate == len(events) and index == len(group) - 1
            if final["cards"] is not None:
                _require(not terminal and index == len(group) - 1 and coordinate < len(events)
                         and events[coordinate]["seat"] == seat
                         and _strict_equal(events[coordinate]["attempted_cards"], final["cards"]),
                         "final reply does not join a recorded action")
                continue
            batches += 1
            candidates = final["evaluations"]
            if terminal:
                evaluation_index = usage["completed_evaluations"] - completed
                _integer(evaluation_index, 0, len(candidates) - 1, "inferred evaluation index")
                _require(usage["attempted_evaluations"] == completed + evaluation_index + 1,
                         "attempt/completion count mismatch")
                for candidate in candidates[:evaluation_index]:
                    _require(_legal(candidate["cards"], obs), "earlier candidate was illegal")
                candidate = candidates[evaluation_index]
                _require(not _legal(candidate["cards"], obs), "inferred candidate is legal")
                selected = dict(seat=seat, request_index=request, evaluation_index=evaluation_index,
                                completed_play_events=coordinate, candidate_cards=candidate["cards"],
                                continuation=candidate["continuation"], evidence_path=path,
                                prior_completed_evaluations=completed,
                                decision_local_completed_evaluations=len(local))
            else:
                _require(index < len(group) - 1, "earlier decision lacks final reply")
                for candidate in candidates:
                    _require(_legal(candidate["cards"], obs), "completed candidate was illegal")
                completed += len(candidates)
                local.extend(candidates)
    _require(selected is not None and batches == usage["requested_batches"]
             and usage["completed_world_rollouts"] == usage["completed_evaluations"],
             "aggregate rollout accounting drift")
    return {"schema": "benchmark-legacy-rollout-audit-v1", "source_commit": SOURCE_COMMIT,
            "row_sha256": row_sha, "pins_sha256": _hash(canonical_json_bytes(pins)),
            "accepted_call_count": len(inventory), **selected}
