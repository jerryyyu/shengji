#!/usr/bin/env python3
"""Execute and verify the reviewed S3c one-card capacity experiment.

This runtime is inert until an exact controller-review PASS is present and a
canonical one-shot receipt is created.  It evaluates no competing actions:
every selected public root has exactly one legal play.  The exact solver's
terminal attacker-point values are used internally to traverse each sampled
world, then discarded.  Artifacts publish only state/action/world digests and
sampler/solver capacity counters.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(SERVER))

import s3c_exact_root_design as DESIGN  # noqa: E402
import s3c_one_card_controller as CTRL  # noqa: E402
from shengji.ai.endgame import (ExactEndgameBudgetExceeded,  # noqa: E402
                                ExactEndgameRefusal,
                                exhaustive_legal_actions)
from shengji.ai.mcbot import (DeterminizationContractError,  # noqa: E402
                              MCBot)
from shengji.ai.memory import Memory  # noqa: E402


class RuntimeRefused(RuntimeError):
    """Runtime identity, work, or evidence differs from the reviewed packet."""


class OneCardExactBot(MCBot):
    """Experiment-local exact continuation; never registered in production."""

    EXACT_ENDGAME = True
    EXACT_ENDGAME_MAX_CARDS = CTRL.MAX_HAND_CARDS
    EXACT_ENDGAME_MAX_NODES = CTRL.MAX_NODES_PER_WORLD_SESSION


FORBIDDEN_RESULT_KEYS = {
    "sampled_hands", "buried_cards", "attacker_points", "action_value",
    "utility", "utilities", "estimand", "estimands", "winner",
}


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RuntimeRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeRefused(f"JSON root is not an object: {path}")
    return value


def _terminal_file(path: Path) -> bool:
    return CTRL.is_regular_unlinked(path)


def _self_hash(payload: Mapping[str, object], field: str) -> str:
    return CTRL.sha256_bytes(CTRL.canonical_json({
        key: value for key, value in payload.items() if key != field
    }))


def _external_packet_sha(packet: Mapping[str, object]) -> str:
    value = packet.get("external_packet_sha256")
    if not CTRL.is_hex_digest(value):
        raise RuntimeRefused("controller packet external SHA unavailable")
    return str(value)


def _assert_no_forbidden_keys(value: object, *, path: str = "result") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_RESULT_KEYS:
                raise RuntimeRefused(f"forbidden result field: {path}.{key}")
            _assert_no_forbidden_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden_keys(child, path=f"{path}[{index}]")


def _controller_packet(packet_path: Path, expected_sha256: str,
                       design_path: Path, census_path: Path,
                       design_review_record: Path) -> dict:
    if (not _terminal_file(packet_path)
            or CTRL.sha256_file(packet_path) != expected_sha256):
        raise RuntimeRefused("controller packet identity drift")
    packet = _load_json(packet_path)
    internal = packet.get("packet_sha256")
    unhashed = {key: value for key, value in packet.items()
                if key != "packet_sha256"}
    if (not CTRL.is_hex_digest(internal)
            or internal != CTRL.sha256_bytes(CTRL.canonical_json(unhashed))):
        raise RuntimeRefused("controller packet self-hash drift")
    try:
        expected = CTRL.build_controller_packet(
            design_path, census_path, design_review_record, smoke=False)
    except (CTRL.ControllerRefused, DESIGN.S3CDesignError) as exc:
        raise RuntimeRefused(str(exc)) from exc
    if CTRL.packet_problems(packet, expected):
        raise RuntimeRefused("controller packet full recomputation drift")
    packet = dict(packet)
    packet["external_packet_sha256"] = expected_sha256
    return packet


def expected_review_claim(packet: Mapping[str, object],
                          packet_sha256: str) -> dict:
    return {
        "schema": CTRL.REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_script_sha256": packet["producer"][
            "controller_script_sha256"],
        "runtime_script_sha256": packet["runtime_sources"][
            "server/scripts/s3c_one_card_runtime.py"],
        "packet_sha256": packet_sha256,
        "design_packet_sha256": CTRL.DESIGN_PACKET_SHA256,
        "census_sha256": CTRL.CENSUS_SHA256,
        "design_review_git": CTRL.DESIGN_REVIEW_GIT,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "root_geometry_sha256": packet["score_free_preflight"][
            "root_geometry_sha256"],
        "roots": CTRL.ROOT_COUNT,
        "worlds": CTRL.WORLD_COUNT,
        "max_execution_nodes": CTRL.MAX_EXECUTION_NODES,
        "max_terminal_replay_nodes": CTRL.MAX_TERMINAL_REPLAY_NODES,
        "score_free_preflight_verified": True,
        "worlds_sampled_before_review": 0,
        "exact_solver_sessions_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "one_card_capacity_execution_authorized": True,
        "two_card_packet_review_authorized": False,
        "solver_or_strength_screen_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _controller_review(review_record: Path, packet: Mapping[str, object],
                       packet_sha256: str) -> dict:
    try:
        claim = CTRL.marker_claim(review_record, CTRL.REVIEW_MARKER)
    except CTRL.ControllerRefused as exc:
        raise RuntimeRefused(str(exc)) from exc
    if claim != expected_review_claim(packet, packet_sha256):
        raise RuntimeRefused("one-card controller review marker drift")
    return claim


def _expected_namespace() -> Path:
    return (REPO / "server" / "runs" / "logs" / CTRL.RUN_ID).resolve()


def _expected_receipt_path() -> Path:
    return _expected_namespace() / "execution-receipt.json"


def _expected_slot_path() -> Path:
    return (REPO / "server" / "runs" / "locks" /
            f"{CTRL.RUN_ID}.consumed.json").resolve()


def _expected_result_path() -> Path:
    return _expected_namespace() / "capacity-result.json"


def _expected_final_path() -> Path:
    return _expected_namespace() / "terminal-final.json"


def _receipt(path: Path, expected_sha256: str | None,
             packet: Mapping[str, object], packet_sha256: str) -> dict:
    if path.resolve() != _expected_receipt_path():
        raise RuntimeRefused("execution receipt differs from reviewed path")
    if not _terminal_file(path):
        raise RuntimeRefused("execution receipt is not regular/unlinked")
    if expected_sha256 and CTRL.sha256_file(path) != expected_sha256:
        raise RuntimeRefused("execution receipt SHA-256 drift")
    receipt = _load_json(path)
    fixed = {
        "schema": CTRL.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "admission_slot": str(_expected_slot_path()),
        "one_shot": True,
        "one_card_capacity_execution_authorized": True,
        "two_card_packet_review_authorized": False,
        "solver_or_strength_screen_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    for key, expected in fixed.items():
        if receipt.get(key) != expected:
            raise RuntimeRefused(f"execution receipt field drift: {key}")
    if receipt.get("review_claim") != expected_review_claim(
            packet, packet_sha256):
        raise RuntimeRefused("execution receipt review claim drift")
    if receipt.get("receipt_sha256") != _self_hash(
            receipt, "receipt_sha256"):
        raise RuntimeRefused("execution receipt self-hash drift")
    slot_path = _expected_slot_path()
    if not _terminal_file(slot_path):
        raise RuntimeRefused("durable admission slot is missing")
    slot = _load_json(slot_path)
    expected_slot = {
        "schema": "s3c-one-card-capacity-admission-slot-v1",
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(_expected_receipt_path()),
        "receipt_file_sha256": CTRL.sha256_file(path),
        "consumed_even_if_receipt_publication_fails": True,
    }
    expected_slot["slot_sha256"] = _self_hash(
        expected_slot, "slot_sha256")
    if slot != expected_slot:
        raise RuntimeRefused("durable admission slot drift")
    return receipt


def admit(*, packet_path: Path, expected_packet_sha256: str,
          design_path: Path, census_path: Path, design_review_record: Path,
          controller_review_record: Path, namespace: Path,
          receipt_path: Path) -> dict:
    packet = _controller_packet(
        packet_path, expected_packet_sha256, design_path, census_path,
        design_review_record)
    claim = _controller_review(
        controller_review_record, packet, expected_packet_sha256)
    if namespace.resolve() != _expected_namespace():
        raise RuntimeRefused("execution namespace differs from reviewed path")
    if receipt_path.resolve() != _expected_receipt_path():
        raise RuntimeRefused("execution receipt must use reviewed path")
    slot_path = _expected_slot_path()
    if os.path.lexists(slot_path) or os.path.lexists(str(slot_path) + ".partial"):
        raise RuntimeRefused("one-shot admission slot is already consumed")
    namespace.mkdir(parents=True, exist_ok=True)
    if any(namespace.iterdir()):
        raise RuntimeRefused("one-shot namespace is not empty")
    receipt = {
        "schema": CTRL.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "admission_slot": str(slot_path),
        "controller_review_record_sha256": CTRL.sha256_file(
            controller_review_record),
        "review_claim": claim,
        "one_shot": True,
        "one_card_capacity_execution_authorized": True,
        "two_card_packet_review_authorized": False,
        "solver_or_strength_screen_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    slot = {
        "schema": "s3c-one-card-capacity-admission-slot-v1",
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(receipt_path.resolve()),
        "receipt_file_sha256": CTRL.sha256_bytes(CTRL.canonical_json(receipt)),
        "consumed_even_if_receipt_publication_fails": True,
    }
    slot["slot_sha256"] = _self_hash(slot, "slot_sha256")
    # Consume authority before publishing the receipt. A crash/short write can
    # strand the run but cannot silently make a second admission available.
    CTRL.publish_exclusive(slot_path, slot)
    CTRL.publish_exclusive(receipt_path, receipt)
    return receipt


def sampler_snapshot(bot: MCBot) -> dict[str, int]:
    return {name: int(getattr(bot, name)) for name in (
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds",
    )}


def exact_snapshot(bot: MCBot) -> dict[str, int]:
    return {
        "attempts": int(bot.exact_endgame_attempts),
        "successes": int(bot.exact_endgame_calls),
        "refusals": int(bot.exact_endgame_refusals),
        "budget_overflows": int(bot.exact_endgame_budget_exceeded),
        "sessions": int(bot.exact_endgame_sessions),
        "nodes": int(bot.exact_endgame_nodes),
        "cache_hits": int(bot.exact_endgame_cache_hits),
    }


def replay_root(root: Mapping[str, object]):
    rnd = DESIGN.replay_prefix(
        int(root["deal_seed"]), CTRL.MAX_HAND_CARDS,
        int(root["within_trick_offset"]),
    )
    replayed = DESIGN.prefix_row(
        int(root["deal_seed"]), CTRL.MAX_HAND_CARDS,
        int(root["within_trick_offset"]),
    )
    expected = {key: root[key] for key in (
        "state_id", "deal_seed", "within_trick_offset", "actor_seat",
        "actor_role", "surface", "state_sha256", "legal_action_count",
        "legal_action_size_counts",
    )}
    actual = None if replayed is None else {key: replayed[key]
                                            for key in expected}
    if rnd is None or actual != expected:
        raise RuntimeRefused(f"public-root replay drift: {root['state_id']}")
    if rnd.turn != root["actor_seat"]:
        raise RuntimeRefused(f"public-root actor drift: {root['state_id']}")
    actions = exhaustive_legal_actions(
        rnd, rnd.turn, max_hand_cards=CTRL.MAX_HAND_CARDS)
    if len(actions) != 1 or root["legal_action_count"] != 1:
        raise RuntimeRefused(f"one-card root is not forced: {root['state_id']}")
    return rnd, actions


def sampled_world_sha256(state_id: str, world_seed: int,
                         sampled: Mapping[int, Sequence[str]],
                         buried: Sequence[str]) -> str:
    return CTRL.sha256_bytes(CTRL.canonical_json({
        "state_id": state_id,
        "world_seed": world_seed,
        "sampled_hands": {
            str(seat): sorted(cards) for seat, cards in sorted(sampled.items())
        },
        "buried": sorted(buried),
    }))


def _expected_exact_frontiers(offset: int) -> int:
    return 0 if offset == 3 else 1


def validate_world_record(record: Mapping[str, object], *, offset: int) -> None:
    expected_frontiers = _expected_exact_frontiers(offset)
    if record.get("status") == "REFUSED_SCORE_FREE":
        reason = record.get("reason_class")
        sampler = record.get("sampler")
        exact = record.get("exact")
        session = record.get("session")
        if (reason not in {
                "SAMPLER_REFUSAL", "EXACT_REFUSAL", "EXACT_BUDGET_OVERFLOW",
                "DETERMINIZATION_REFUSAL"}
                or not isinstance(sampler, dict)
                or set(sampler) != {
                    "sample_attempts", "accepted_worlds", "failed_worlds",
                    "rejected_worlds", "impossible_worlds"}
                or any(not isinstance(value, int) or value < 0
                       for value in sampler.values())
                or sampler["sample_attempts"] != 1
                or sampler["accepted_worlds"] not in {0, 1}
                or not isinstance(exact, dict)
                or set(exact) != {
                    "attempts", "successes", "refusals", "budget_overflows",
                    "sessions", "nodes", "cache_hits"}
                or any(not isinstance(value, int) or value < 0
                       for value in exact.values())
                or not isinstance(session, dict)
                or set(session) != {
                    "frontiers", "nodes", "cache_hits", "max_hand_cards",
                    "max_nodes"}
                or session.get("max_hand_cards") != CTRL.MAX_HAND_CARDS
                or session.get("max_nodes") != CTRL.MAX_NODES_PER_WORLD_SESSION
                or not isinstance(session.get("nodes"), int)
                or not 0 <= session["nodes"] <= CTRL.MAX_NODES_PER_WORLD_SESSION
                or not isinstance(session.get("cache_hits"), int)
                or session["cache_hits"] < 0
                or exact["nodes"] != session["nodes"]
                or exact["cache_hits"] != session["cache_hits"]
                or exact["successes"] != 0):
            raise RuntimeRefused("malformed refused world record")
        if reason == "SAMPLER_REFUSAL":
            if (sampler != {
                    "sample_attempts": 1, "accepted_worlds": 0,
                    "failed_worlds": 1, "rejected_worlds": 1,
                    "impossible_worlds": 0}
                    or any(exact.values()) or session["frontiers"] != 0):
                raise RuntimeRefused("sampler refusal accounting drift")
        elif reason == "DETERMINIZATION_REFUSAL":
            if (sampler["accepted_worlds"] != 1
                    or exact["sessions"] != 1
                    or exact["attempts"] != 0
                    or exact["refusals"] != 0
                    or exact["budget_overflows"] != 0
                    or session["frontiers"] != 0):
                raise RuntimeRefused("determinization refusal accounting drift")
        else:
            expected_overflow = int(reason == "EXACT_BUDGET_OVERFLOW")
            if (sampler["accepted_worlds"] != 1
                    or exact["sessions"] != 1
                    or exact["attempts"] != 1
                    or exact["refusals"] != 1
                    or exact["budget_overflows"] != expected_overflow
                    or session["frontiers"] != 1):
                raise RuntimeRefused("exact refusal accounting drift")
        if (not isinstance(record.get("world_index"), int)
                or not isinstance(record.get("world_seed"), int)):
            raise RuntimeRefused("refused world identity drift")
        _assert_no_forbidden_keys(record)
        return
    if record.get("status") != "COMPLETE":
        raise RuntimeRefused("world status drift")
    sampler = record.get("sampler")
    exact = record.get("exact")
    session = record.get("session")
    if sampler != {
        "sample_attempts": 1,
        "accepted_worlds": 1,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }:
        raise RuntimeRefused("complete world sampler counters drift")
    if (not isinstance(exact, dict) or not isinstance(session, dict)
            or exact.get("sessions") != 1
            or exact.get("attempts") != expected_frontiers
            or exact.get("successes") != expected_frontiers
            or exact.get("refusals") != 0
            or exact.get("budget_overflows") != 0
            or session.get("frontiers") != expected_frontiers
            or session.get("max_hand_cards") != CTRL.MAX_HAND_CARDS
            or session.get("max_nodes") != CTRL.MAX_NODES_PER_WORLD_SESSION
            or not isinstance(session.get("nodes"), int)
            or not 0 <= session["nodes"] <= CTRL.MAX_NODES_PER_WORLD_SESSION
            or not isinstance(session.get("cache_hits"), int)
            or session["cache_hits"] < 0
            or exact.get("nodes") != session["nodes"]
            or exact.get("cache_hits") != session["cache_hits"]):
        raise RuntimeRefused("complete world exact/session counters drift")
    if (not isinstance(record.get("world_seed"), int)
            or not CTRL.is_hex_digest(record.get("world_sha256"))):
        raise RuntimeRefused("complete world identity drift")
    _assert_no_forbidden_keys(record)


def run_world(rnd, action: list[str], root: Mapping[str, object],
              world: Mapping[str, object]) -> dict:
    seed = int(world["seed"])
    bot = OneCardExactBot(seed=seed)
    seat = rnd.turn
    if seat is None:
        raise RuntimeRefused("one-card root has no actor")
    memory = Memory(rnd, seat, own_kitty=True)
    sampled_result = bot._sample_hands(rnd, seat, memory)
    sampler = sampler_snapshot(bot)
    empty_session = {
        "frontiers": 0,
        "nodes": 0,
        "cache_hits": 0,
        "max_hand_cards": CTRL.MAX_HAND_CARDS,
        "max_nodes": CTRL.MAX_NODES_PER_WORLD_SESSION,
    }
    if sampled_result is None:
        record = {
            "status": "REFUSED_SCORE_FREE",
            "world_index": world["index"],
            "world_seed": seed,
            "reason_class": "SAMPLER_REFUSAL",
            "sampler": sampler,
            "exact": exact_snapshot(bot),
            "session": empty_session,
        }
        validate_world_record(
            record, offset=int(root["within_trick_offset"]))
        return record
    sampled, buried = sampled_result
    session = bot._new_exact_world_session(rnd, buried)
    if session is None:
        raise RuntimeRefused("exact one-card session was not created")
    reason = None
    try:
        internal_terminal_score = bot._rollout(
            rnd, seat, sampled, buried, action, exact_session=session)
        if not isinstance(internal_terminal_score, (int, float)):
            raise RuntimeRefused("exact solver returned nonnumeric internal score")
        del internal_terminal_score
    except ExactEndgameBudgetExceeded:
        reason = "EXACT_BUDGET_OVERFLOW"
    except ExactEndgameRefusal:
        reason = "EXACT_REFUSAL"
    except DeterminizationContractError:
        reason = "DETERMINIZATION_REFUSAL"
    exact = exact_snapshot(bot)
    session_record = {
        "frontiers": int(session.frontiers),
        "nodes": int(session.nodes),
        "cache_hits": int(session.cache_hits),
        "max_hand_cards": int(session.solver.max_hand_cards),
        "max_nodes": int(session.solver.max_nodes),
    }
    if reason is None:
        record = {
            "status": "COMPLETE",
            "world_index": world["index"],
            "world_seed": seed,
            "world_sha256": sampled_world_sha256(
                str(root["state_id"]), seed, sampled, buried),
            "sampler": sampler,
            "exact": exact,
            "session": session_record,
        }
    else:
        record = {
            "status": "REFUSED_SCORE_FREE",
            "world_index": world["index"],
            "world_seed": seed,
            "reason_class": reason,
            "sampler": sampler,
            "exact": exact,
            "session": session_record,
        }
    validate_world_record(record, offset=int(root["within_trick_offset"]))
    return record


def _sum_world_counters(worlds: Sequence[Mapping[str, object]]) -> dict:
    return {
        "worlds_attempted": len(worlds),
        "worlds_complete": sum(world.get("status") == "COMPLETE"
                               for world in worlds),
        "worlds_refused": sum(world.get("status") == "REFUSED_SCORE_FREE"
                              for world in worlds),
        "sample_attempts": sum(int(world["sampler"]["sample_attempts"])
                               for world in worlds),
        "accepted_worlds": sum(int(world["sampler"]["accepted_worlds"])
                               for world in worlds),
        "sampler_refusals": sum(world.get("reason_class") == "SAMPLER_REFUSAL"
                                for world in worlds),
        "exact_attempts": sum(int(world["exact"]["attempts"])
                              for world in worlds),
        "exact_successes": sum(int(world["exact"]["successes"])
                               for world in worlds),
        "exact_refusals": sum(int(world["exact"]["refusals"])
                              for world in worlds),
        "exact_budget_overflows": sum(
            int(world["exact"]["budget_overflows"]) for world in worlds),
        "exact_sessions": sum(int(world["exact"]["sessions"])
                              for world in worlds),
        "exact_nodes": sum(int(world["exact"]["nodes"])
                           for world in worlds),
        "exact_cache_hits": sum(int(world["exact"]["cache_hits"])
                                for world in worlds),
        "exact_frontiers": sum(int(world["session"]["frontiers"])
                               for world in worlds),
    }


def validate_root_record(record: Mapping[str, object],
                         scheduled: Mapping[str, object]) -> None:
    identity = {key: scheduled[key] for key in (
        "state_id", "deal_seed", "within_trick_offset", "actor_seat",
        "actor_role", "surface", "state_sha256", "legal_action_count",
        "selection_hash",
    )}
    if any(record.get(key) != value for key, value in identity.items()):
        raise RuntimeRefused("root identity drift")
    if (record.get("legal_action_count") != 1
            or not CTRL.is_hex_digest(record.get("legal_action_sha256"))):
        raise RuntimeRefused("root action geometry drift")
    worlds = record.get("worlds")
    if not isinstance(worlds, list):
        raise RuntimeRefused("root world records missing")
    if len(worlds) > CTRL.WORLDS_PER_ROOT:
        raise RuntimeRefused("root world count exceeds schedule")
    for index, world_record in enumerate(worlds):
        scheduled_world = scheduled["worlds"][index]
        if (world_record.get("world_index") != scheduled_world["index"]
                or world_record.get("world_seed") != scheduled_world["seed"]):
            raise RuntimeRefused("root world schedule drift")
        validate_world_record(
            world_record, offset=int(scheduled["within_trick_offset"]))
    summary = _sum_world_counters(worlds)
    if record.get("work") != summary:
        raise RuntimeRefused("root work summary drift")
    if record.get("status") == "COMPLETE":
        if (len(worlds) != CTRL.WORLDS_PER_ROOT
                or summary["worlds_complete"] != CTRL.WORLDS_PER_ROOT
                or summary["worlds_refused"] != 0):
            raise RuntimeRefused("complete root has incomplete world dose")
    elif record.get("status") == "REFUSED_SCORE_FREE":
        if (not worlds or worlds[-1].get("status") != "REFUSED_SCORE_FREE"
                or record.get("reason_class") != worlds[-1].get("reason_class")):
            raise RuntimeRefused("refused root reason/work drift")
    else:
        raise RuntimeRefused("root status drift")
    _assert_no_forbidden_keys(record)


def run_root(root: Mapping[str, object]) -> dict:
    rnd, actions = replay_root(root)
    action = actions[0]
    worlds = []
    for world in root["worlds"]:
        record = run_world(rnd, action, root, world)
        worlds.append(record)
        if record["status"] == "REFUSED_SCORE_FREE":
            break
    result = {
        "status": ("COMPLETE" if len(worlds) == CTRL.WORLDS_PER_ROOT
                   and all(world["status"] == "COMPLETE" for world in worlds)
                   else "REFUSED_SCORE_FREE"),
        "state_id": root["state_id"],
        "deal_seed": root["deal_seed"],
        "within_trick_offset": root["within_trick_offset"],
        "actor_seat": root["actor_seat"],
        "actor_role": root["actor_role"],
        "surface": root["surface"],
        "state_sha256": root["state_sha256"],
        "selection_hash": root["selection_hash"],
        "legal_action_count": len(actions),
        "legal_action_sha256": CTRL.sha256_bytes(
            CTRL.canonical_json(sorted(actions[0]))),
        "worlds": worlds,
        "work": _sum_world_counters(worlds),
    }
    if result["status"] == "REFUSED_SCORE_FREE":
        result["reason_class"] = worlds[-1]["reason_class"]
    validate_root_record(result, root)
    return result


def result_payload(packet: Mapping[str, object], receipt_sha256: str,
                   roots: Sequence[dict]) -> dict:
    schedule = packet["schedule"]
    if len(roots) != CTRL.ROOT_COUNT:
        raise RuntimeRefused("result requires every selected root")
    for record, scheduled in zip(roots, schedule["roots"], strict=True):
        validate_root_record(record, scheduled)
    refused = [root for root in roots
               if root["status"] == "REFUSED_SCORE_FREE"]
    totals = Counter()
    for root in roots:
        totals.update(root["work"])
    status = ("COMPLETE_CAPACITY_ONLY" if not refused
              else "REFUSED_INCOMPLETE_NO_NEXT_AUTHORITY")
    payload = {
        "schema": CTRL.RESULT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": _external_packet_sha(packet),
        "execution_receipt_sha256": receipt_sha256,
        "schedule_sha256": schedule["schedule_sha256"],
        "status": status,
        "roots": list(roots),
        "counts": {
            "roots_selected": len(roots),
            "roots_complete": len(roots) - len(refused),
            "roots_refused": len(refused),
            **dict(sorted(totals.items())),
        },
        "refusal_counts": dict(sorted(Counter(
            root["reason_class"] for root in refused).items())),
        "internal_terminal_scores_published": False,
        "action_values_published": False,
        "utility_or_strength_gate": False,
        "two_card_packet_review_authorized": False,
        "solver_or_strength_screen_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["result_sha256"] = _self_hash(payload, "result_sha256")
    _assert_no_forbidden_keys(payload)
    return payload


def validate_result(payload: Mapping[str, object],
                    packet: Mapping[str, object], receipt_sha256: str) -> None:
    if (payload.get("schema") != CTRL.RESULT_SCHEMA
            or payload.get("run_id") != CTRL.RUN_ID
            or payload.get("git") != packet["producer"]["git"]
            or payload.get("controller_packet_sha256")
            != _external_packet_sha(packet)
            or payload.get("execution_receipt_sha256") != receipt_sha256
            or payload.get("schedule_sha256")
            != packet["schedule"]["schedule_sha256"]
            or payload.get("result_sha256") != _self_hash(
                payload, "result_sha256")):
        raise RuntimeRefused("capacity result identity/self-hash drift")
    roots = payload.get("roots")
    if not isinstance(roots, list):
        raise RuntimeRefused("capacity result roots missing")
    expected = result_payload(packet, receipt_sha256, roots)
    if payload != expected:
        raise RuntimeRefused("capacity result full recomputation drift")
    _assert_no_forbidden_keys(payload)


def run(*, packet_path: Path, expected_packet_sha256: str,
        design_path: Path, census_path: Path, design_review_record: Path,
        receipt_path: Path, expected_receipt_sha256: str, out: Path,
        progress_every: int) -> dict:
    packet = _controller_packet(
        packet_path, expected_packet_sha256, design_path, census_path,
        design_review_record)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    if out.resolve() != _expected_result_path():
        raise RuntimeRefused("capacity result differs from reviewed path")
    if out.exists() or Path(str(out) + ".partial").exists():
        raise RuntimeRefused("refusing existing capacity result/partial")
    roots = []
    for index, root in enumerate(packet["schedule"]["roots"], 1):
        roots.append(run_root(root))
        if progress_every > 0 and (index % progress_every == 0
                                   or index == CTRL.ROOT_COUNT):
            print(json.dumps({
                "status": "RUNNING_CAPACITY_ONLY",
                "roots_terminal": index,
                "roots_total": CTRL.ROOT_COUNT,
                "complete": sum(item["status"] == "COMPLETE"
                                for item in roots),
                "refused": sum(item["status"] == "REFUSED_SCORE_FREE"
                               for item in roots),
                "outcomes_published": False,
            }, sort_keys=True), file=sys.stderr, flush=True)
    # Close source/packet/receipt TOCTOU immediately before publication.
    packet = _controller_packet(
        packet_path, expected_packet_sha256, design_path, census_path,
        design_review_record)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    payload = result_payload(packet, expected_receipt_sha256, roots)
    CTRL.publish_exclusive(out, payload)
    return payload


def terminal_payload(packet: Mapping[str, object], result_path: Path,
                     result: Mapping[str, object], replayed_roots: int,
                     replay_nodes: int) -> dict:
    complete = result.get("status") == "COMPLETE_CAPACITY_ONLY"
    payload = {
        "schema": CTRL.FINAL_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": _external_packet_sha(packet),
        "result_file_sha256": CTRL.sha256_file(result_path),
        "result_internal_sha256": result["result_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "status": ("AUTHORIZE_TWO_CARD_MECHANISM_PACKET_REVIEW"
                   if complete else "REFUSED_INCOMPLETE_NO_NEXT_AUTHORITY"),
        "roots_verified": CTRL.ROOT_COUNT,
        "complete_roots_reexecuted": replayed_roots,
        "refused_roots_retried": 0,
        "terminal_replay_nodes": replay_nodes,
        "internal_terminal_scores_published": False,
        "action_values_published": False,
        "utility_or_strength_gate": False,
        "two_card_packet_review_authorized": complete,
        "solver_or_strength_screen_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["final_sha256"] = _self_hash(payload, "final_sha256")
    _assert_no_forbidden_keys(payload)
    return payload


def verify_result(*, packet_path: Path, expected_packet_sha256: str,
                  design_path: Path, census_path: Path,
                  design_review_record: Path, receipt_path: Path,
                  expected_receipt_sha256: str, result_path: Path,
                  out: Path, replay_every_complete_root: bool) -> dict:
    if not replay_every_complete_root:
        raise RuntimeRefused(
            "terminal verification requires --replay-every-complete-root")
    packet = _controller_packet(
        packet_path, expected_packet_sha256, design_path, census_path,
        design_review_record)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    if (result_path.resolve() != _expected_result_path()
            or not _terminal_file(result_path)):
        raise RuntimeRefused("capacity result path/type drift")
    result = _load_json(result_path)
    validate_result(result, packet, expected_receipt_sha256)
    stored = {root["state_id"]: root for root in result["roots"]}
    replayed_roots = 0
    replay_nodes = 0
    for scheduled in packet["schedule"]["roots"]:
        record = stored.get(scheduled["state_id"])
        if record is None:
            raise RuntimeRefused("terminal selected-root population drift")
        # Every public state is replayed. A refused world's hidden sample is
        # never retried, preventing verification from replacing a failed dose.
        replay_root(scheduled)
        if record["status"] == "COMPLETE":
            replayed = run_root(scheduled)
            if replayed != record:
                raise RuntimeRefused(
                    f"terminal capacity replay drift: {scheduled['state_id']}")
            replayed_roots += 1
            replay_nodes += int(replayed["work"]["exact_nodes"])
    if replay_nodes > CTRL.MAX_TERMINAL_REPLAY_NODES:
        raise RuntimeRefused("terminal replay exceeded frozen node ceiling")
    # Reopen identities after replay and before the one terminal publication.
    packet = _controller_packet(
        packet_path, expected_packet_sha256, design_path, census_path,
        design_review_record)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    if CTRL.sha256_file(result_path) != CTRL.sha256_bytes(
            CTRL.canonical_json(result)):
        raise RuntimeRefused("capacity result changed during verification")
    if out.resolve() != _expected_final_path():
        raise RuntimeRefused("terminal final differs from reviewed path")
    payload = terminal_payload(
        packet, result_path, result, replayed_roots, replay_nodes)
    CTRL.publish_exclusive(out, payload)
    return payload


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--controller-packet", required=True)
    parser.add_argument("--expected-controller-packet-sha256", required=True)
    parser.add_argument("--design-packet", required=True)
    parser.add_argument("--census", required=True)
    parser.add_argument("--design-review-record", required=True)


def _receipt_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--execution-receipt", required=True)
    parser.add_argument("--expected-execution-receipt-sha256", required=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    admit_parser = commands.add_parser("admit")
    _common(admit_parser)
    admit_parser.add_argument("--controller-review-record", required=True)
    admit_parser.add_argument("--namespace", required=True)
    admit_parser.add_argument("--out", required=True)
    run_parser = commands.add_parser("run")
    _common(run_parser)
    _receipt_args(run_parser)
    run_parser.add_argument("--out", required=True)
    run_parser.add_argument("--progress-every", type=int, default=1)
    verify_parser = commands.add_parser("verify-result")
    _common(verify_parser)
    _receipt_args(verify_parser)
    verify_parser.add_argument("--result", required=True)
    verify_parser.add_argument("--out", required=True)
    verify_parser.add_argument("--replay-every-complete-root",
                               action="store_true")
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if CTRL.git("rev-parse", "HEAD") != args.expected_git:
        raise RuntimeRefused("runtime Git differs from expected identity")
    common = {
        "packet_path": Path(args.controller_packet),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
        "design_path": Path(args.design_packet),
        "census_path": Path(args.census),
        "design_review_record": Path(args.design_review_record),
    }
    if args.command == "admit":
        payload = admit(
            **common,
            controller_review_record=Path(args.controller_review_record),
            namespace=Path(args.namespace), receipt_path=Path(args.out),
        )
    elif args.command == "run":
        payload = run(
            **common, receipt_path=Path(args.execution_receipt),
            expected_receipt_sha256=args.expected_execution_receipt_sha256,
            out=Path(args.out), progress_every=args.progress_every,
        )
    else:
        payload = verify_result(
            **common, receipt_path=Path(args.execution_receipt),
            expected_receipt_sha256=args.expected_execution_receipt_sha256,
            result_path=Path(args.result), out=Path(args.out),
            replay_every_complete_root=args.replay_every_complete_root,
        )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeRefused, CTRL.ControllerRefused, DESIGN.S3CDesignError,
            OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
