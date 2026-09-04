"""Extractor: live room logs (``logs/*.jsonl`` + ``logs/archive/*/*.jsonl`` +
``logs/local/*.jsonl``).

Rounds are rebuilt with ``replay_log.rebuild_round`` (round_start.deck +
declare events + bury) and replayed play by play.  A round counts only when
it carries round_start/trump/bury/round_end AND replays to ``round_end`` with
the logged ``attacker_points`` (192 complete rounds expected).

Per play event one ``play`` record is emitted; per bury event one ``bury``
record.  ``play`` events may carry a nested ``decision`` blob
(``mc-decision-v2``): its ``candidates`` become ``ballot`` and its
``n_by_candidate`` / ``means`` / ``paired_se`` (plus the report fold and the
reason) become ``allocation``.  Three early blobs predate the schema field
(``chosen_index`` instead of ``played_index``); they are adapted, not dropped.

Format facts (verified): human plays are logged with the ENGINE's cards
(a failed human throw is logged post-penalty); bot plays log the engine's
cards plus ``attempted_cards`` / ``engine_resolution`` when a throw failed
(none present in the current logs).  ``event_index`` in human_v8 pointers is
the index within the round's event list in file order — the same indexing
``source_ref`` uses here.
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator, Sequence

from ..engine.round import Round
from ..rl.replay_log import rebuild_round
from .common import (REPO, ROOM_LOG_GLOBS, ExtractResult, InputRegistry,
                     action_key, human_policy)
from .legal import bury_action_count, enumerate_legal
from .rebuild import (actor_role, engine_level_change, outcome_for,
                      round_from_setup)
from .schema import finalize_record

REQUIRED_EVENTS = ("round_start", "trump", "bury", "round_end")


class RoomLogError(ValueError):
    pass


def log_files(repo: Path = REPO, patterns: Sequence[str] = ROOM_LOG_GLOBS) -> list[Path]:
    found: set[Path] = set()
    for pattern in patterns:
        found.update(Path(p) for p in glob.glob(str(repo / pattern)))
    return sorted(found)


def log_ref(path: Path, repo: Path = REPO) -> str:
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


def log_group(ref: str) -> str:
    """``main`` (logs/*.jsonl), ``archive`` or ``local``."""
    if "/archive/" in ref:
        return "archive"
    if "/local/" in ref:
        return "local"
    return "main"


def read_rounds(path: Path, registry: InputRegistry) -> tuple[dict[int, list[dict]], int]:
    """Round number -> events (file order).  Returns (rounds, bad_lines)."""
    by_round: dict[int, list[dict]] = defaultdict(list)
    bad = 0
    for raw in registry.read_bytes(path).decode("utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
            by_round[int(event["round"])].append(event)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            bad += 1
    return dict(by_round), bad


def _allocation_from_decision(decision: dict) -> dict[str, Any]:
    """The search's own account of the decision, raw fields kept by name."""
    played_index = decision.get("played_index", decision.get("chosen_index"))
    out: dict[str, Any] = {
        "kind": decision.get("schema") or "mc-decision-pre-v2",
        "policy": decision.get("policy"),
        "n_determinizations": decision.get("n_determinizations"),
        "worlds": decision.get("worlds"),
        "n_by_candidate": list(decision.get("n_by_candidate") or []),
        "means": list(decision.get("means") or []),
        "paired_se": list(decision.get("paired_se") or []),
        "eligible_indices": decision.get("eligible_indices"),
        "played_index": played_index,
        "raw_winner_index": decision.get("raw_winner_index"),
        "report_candidate_index": decision.get("report_candidate_index"),
        "reason": decision.get("reason"),
    }
    fold = decision.get("report_fold")
    if isinstance(fold, dict):
        out["report_fold"] = {k: fold.get(k) for k in (
            "gap", "se", "worlds", "attempts", "rejected", "complete", "rule",
            "critical", "statistic", "min_gain", "bound")}
    else:
        out["report_fold"] = None
    alloc = decision.get("alloc")
    if isinstance(alloc, dict):
        out["selection"] = {k: alloc.get(k) for k in (
            "mode", "worlds", "rollouts", "budget", "short", "attempts")}
    ballot = decision.get("ballot")
    if isinstance(ballot, dict):
        out["ballot_identity"] = ballot.get("display") or ballot.get("digest")
    return out


def _seat_policies(events: list[dict]) -> dict[int, str]:
    """Bot policy per seat from bot_timing / decision blobs in the round."""
    policies: dict[int, str] = {}
    for event in events:
        kind = event.get("e")
        if kind == "bot_timing" and isinstance(event.get("policy"), str):
            policies.setdefault(int(event["seat"]), event["policy"])
        elif kind == "play" and isinstance(event.get("decision"), dict):
            policy = event["decision"].get("policy")
            if isinstance(policy, str):
                policies.setdefault(int(event["seat"]), policy)
    return policies


def file_bot_policy(rounds: dict[int, list[dict]]) -> str | None:
    """The one bot policy a room ran (``room.bot``), from any round that
    recorded it; None for logs that predate policy telemetry."""
    names = {p for events in rounds.values() for p in _seat_policies(events).values()}
    return sorted(names)[0] if len(names) == 1 else None


def _authority(events: list[dict]) -> dict | None:
    for event in events:
        experiment = event.get("experiment")
        if event.get("training_excluded") is True or (
                isinstance(experiment, dict)
                and experiment.get("training_excluded") is True):
            return {"training_excluded": True,
                    "experiment_schema": (experiment or {}).get("schema")}
    return None


def extract_round(ref: str, round_no: int, events: list[dict], *,
                  cap: int | None = 256,
                  fallback_policy: str | None = None) -> tuple[list[dict], dict[str, int]]:
    """Records for one complete, replayable round (raises on failure).

    ``fallback_policy`` names the room's bot policy when this round carries
    no telemetry of its own (older logs); unknown stays ``bot:unknown``.
    """
    kinds = {e.get("e") for e in events}
    if not set(REQUIRED_EVENTS) <= kinds:
        raise RoomLogError("round_incomplete")
    start = next(e for e in events if e["e"] == "round_start")
    trump = next(e for e in events if e["e"] == "trump")
    bury = next(e for e in events if e["e"] == "bury")
    end = next(e for e in events if e["e"] == "round_end")
    players = start.get("players") or []
    names = {int(p["seat"]): str(p["name"]) for p in players}
    if set(names) != {0, 1, 2, 3}:
        raise RoomLogError("round_player_seats")
    rnd = rebuild_round(events)
    if rnd is None:
        raise RoomLogError("round_missing_setup")
    if rnd.banker != trump.get("banker") or bury.get("seat") != rnd.banker:
        raise RoomLogError("logged trump/bury banker mismatch")
    deck = list(start["deck"])
    declarations = [{"seat": e["seat"], "cards": list(e["cards"])}
                    for e in events if e.get("e") == "declare"]
    setup = {
        "trump_rank": rnd.trump_rank,
        "banker": rnd.banker,
        "declarations": declarations,
        "declaration": None if rnd.declaration is None else dict(rnd.declaration),
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": bool(rnd.trump_is_nt),
        "buried": sorted(bury["cards"]),
    }
    # the record path must rebuild the same start-of-play state
    twin = round_from_setup(deck, setup)
    if [sorted(h) for h in twin.hands] != [sorted(h) for h in rnd.hands] \
            or twin.turn != rnd.turn or twin.trump_suit != rnd.trump_suit:
        raise RoomLogError("setup does not round-trip")
    policies = _seat_policies(events)
    authority = _authority(events)
    banker = rnd.banker
    final_points = int(end["attacker_points"])
    if end.get("winner_team") is not None and end["winner_team"] != (
            (1 - banker % 2) if final_points >= 80 else banker % 2):
        raise RoomLogError("logged winner_team drift")
    if end.get("level_change") is not None and end["level_change"] != \
            engine_level_change(final_points):
        raise RoomLogError("logged level_change drift")

    def policy_for(event: dict) -> str:
        # the event's own flag decides: a bot may act for a human seat
        # (disconnect takeover, ``bot_timing.mode == "takeover"``)
        seat = int(event["seat"])
        if event.get("bot") is False:
            return human_policy(names[seat])
        decision = event.get("decision")
        if isinstance(decision, dict) and isinstance(decision.get("policy"), str):
            return decision["policy"]
        return policies.get(seat) or fallback_policy or "bot:unknown"

    records: list[dict] = []
    counts = {"plays": 0, "decision_blobs": 0, "human_plays": 0,
              "bury_records": 0, "failed_throws": 0}
    # ---- bury record (state before the bury)
    pre = round_from_setup(deck, setup, stop_before_bury=True)
    hand_before = sorted(pre.hands[banker])
    records.append(finalize_record({
        "source": "room-log",
        "source_ref": f"{ref}:round-{round_no}:event-{events.index(bury)}",
        "policy": policy_for(bury),
        "decision_kind": "bury",
        "deck": deck,
        "setup": setup,
        "plays_prefix": [],
        "seat": banker, "ply": None, "trick": None,
        "role": "banker-team",
        "legal_actions": None, "legal_actions_complete": False,
        "legal_actions_count": bury_action_count(hand_before),
        "ballot": None, "allocation": None, "action_values": None,
        "action": list(bury["cards"]),
        "outcome": outcome_for(final_points, banker=banker, seat=banker),
        "authority": authority,
        "hidden_hands": None,
    }))
    counts["bury_records"] += 1
    # ---- play records
    prefix: list[dict] = []
    for event_index, event in enumerate(events):
        if event.get("e") != "play" or rnd.phase != "play":
            continue
        seat = int(event["seat"])
        cards = list(event["cards"])
        if rnd.turn != seat:
            raise RoomLogError(f"play off turn at event {event_index}")
        attempted = event.get("attempted_cards")
        action = list(attempted) if attempted else cards
        decision = event.get("decision") if isinstance(event.get("decision"), dict) else None
        ballot = None
        allocation = None
        if decision is not None:
            ballot = [list(c) for c in decision.get("candidates") or []] or None
            allocation = _allocation_from_decision(decision)
            played = decision.get("played")
            if played is not None and action_key(played) != action_key(action):
                raise RoomLogError(f"decision/play mismatch at event {event_index}")
            counts["decision_blobs"] += 1
        legal = enumerate_legal(rnd, seat, cap=cap,
                                must_include=(ballot or []) + [action])
        fields = {
            "source": "room-log",
            "source_ref": f"{ref}:round-{round_no}:event-{event_index}",
            "policy": policy_for(event),
            "deck": deck,
            "setup": setup,
            "plays_prefix": [dict(p) for p in prefix],
            "seat": seat,
            "ply": len(prefix),
            "trick": len(prefix) // 4,
            "role": actor_role(rnd, seat),
            "legal_actions": legal.actions,
            "legal_actions_complete": legal.complete,
            "legal_actions_count": legal.count,
            "ballot": ballot,
            "allocation": allocation,
            "action_values": None,
            "action": action,
            "outcome": outcome_for(final_points, banker=banker, seat=seat),
            "authority": authority,
            "hidden_hands": None,
        }
        if attempted:
            fields["engine_play"] = cards
            counts["failed_throws"] += 1
        records.append(finalize_record(fields))
        counts["plays"] += 1
        if event.get("bot") is False:
            counts["human_plays"] += 1
        rnd.play(seat, cards)
        prefix.append({"seat": seat, "cards": cards})
    if rnd.phase != "round_end":
        raise RoomLogError("round_end_state")
    if rnd.attacker_points != final_points:
        raise RoomLogError("round_score_mismatch")
    return records, counts


def iter_round_events(files: Sequence[Path], registry: InputRegistry,
                      repo: Path = REPO) -> Iterator[tuple[str, int, list[dict], int, str | None]]:
    for path in files:
        rounds, bad = read_rounds(path, registry)
        fallback = file_bot_policy(rounds)
        for round_no in sorted(rounds):
            yield log_ref(path, repo), round_no, rounds[round_no], bad, fallback


def extract_room_logs(files: Sequence[Path] | None = None, *, cap: int | None = 256,
                      registry: InputRegistry | None = None,
                      repo: Path = REPO,
                      limit_rounds: int | None = None) -> ExtractResult:
    registry = registry or InputRegistry()
    files = list(files) if files is not None else log_files(repo)
    result = ExtractResult("room-log")
    totals = {"files": len(files), "rounds_seen": 0, "rounds": 0,
              "rounds_incomplete": 0, "rounds_rejected": 0, "decisions": 0,
              "plays": 0, "decision_blobs": 0, "human_plays": 0,
              "bury_records": 0, "failed_throws": 0, "bad_lines": 0}
    rejections: dict[str, int] = defaultdict(int)
    per_dir: dict[str, dict[str, int]] = {}
    seen_bad: set[str] = set()
    for ref, round_no, events, bad, fallback in iter_round_events(files, registry, repo):
        if ref not in seen_bad:
            totals["bad_lines"] += bad
            seen_bad.add(ref)
        totals["rounds_seen"] += 1
        if limit_rounds is not None and totals["rounds"] >= limit_rounds:
            break
        kinds = {e.get("e") for e in events}
        if not set(REQUIRED_EVENTS) <= kinds:
            totals["rounds_incomplete"] += 1
            continue
        try:
            records, counts = extract_round(ref, round_no, events, cap=cap,
                                            fallback_policy=fallback)
        except Exception as exc:  # noqa: BLE001 - partial/corrupt round
            totals["rounds_rejected"] += 1
            rejections[f"{type(exc).__name__}:{exc}"[:120]] += 1
            continue
        totals["rounds"] += 1
        group = log_group(ref)
        bucket = per_dir.setdefault(group, {"rounds": 0, "plays": 0,
                                            "decision_blobs": 0, "human_plays": 0})
        bucket["rounds"] += 1
        for key, value in counts.items():
            totals[key] += value
            if key in bucket:
                bucket[key] += value
        totals["decisions"] += counts["plays"]
        for record in records:
            result.add(record, None)
    result.counts = totals
    result.extras["rejections"] = dict(sorted(rejections.items()))
    result.extras["per_directory"] = {k: per_dir[k] for k in sorted(per_dir)}
    result.inputs = registry.rows()
    result.notes.append("decisions = play records; bury records are counted "
                        "separately (decision_kind = 'bury')")
    return result


def player_names(events: list[dict]) -> dict[int, str]:
    start = next(e for e in events if e.get("e") == "round_start")
    return {int(p["seat"]): str(p["name"]) for p in start["players"]}


def rebuild_start_of_play(events: list[dict]) -> Round | None:
    return rebuild_round(events)
