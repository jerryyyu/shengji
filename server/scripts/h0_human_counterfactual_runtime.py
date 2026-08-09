#!/usr/bin/env python3
"""One-shot runtime for the reviewed H0 human-action counterfactual pilot.

This module is inert until a frozen controller packet receives an independent
PASS marker and an exclusive execution receipt.  It then runs deterministic
deal-clustered shards, publishes every selected row exactly once, and refuses
partial folds without attaching utility to the refused row.  Its aggregate is
diagnostic only: no result can label data, train a model, claim strength,
promote a policy, or deploy it.

The terminal verifier can rerun every complete row from the immutable source
logs and named RNG streams.  That replay is intentionally expensive: H0 is a
one-shot evidence asset, not an interactive tuning loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import h0_human_counterfactual_controller as CTRL  # noqa: E402
import live_champion_parent as LIVE_PARENT  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.pilot_folds import world_key  # noqa: E402
from shengji.rl.torch_policy import _load_npnet  # noqa: E402


class RuntimeRefused(RuntimeError):
    """The reviewed H0 runtime contract or one execution row failed closed."""


ROW_STAGES = (
    "not-started", "replay", "candidate-union", "reference-root",
    "selection-sampling", "selection-scoring", "report-sampling",
    "report-scoring", "validation", "complete",
)


class RowWorkLedger:
    """Outcome-free, exact accounting retained when a row refuses.

    A refused row may not expose cards, scores, or utilities. It still has to
    explain how much of the frozen dose was consumed. Expected protocol
    failures update this ledger before raising; an unexpected exception aborts
    the shard instead of publishing a falsely exact refusal record.
    """

    def __init__(self, surface_type: str):
        if surface_type not in {"play", "bury"}:
            raise RuntimeRefused("row-work surface drift")
        self.surface_type = surface_type
        self.stage = "not-started"
        self.candidate_worlds_attempted = {
            "reference": 0, "selection": 0, "report": 0,
        }
        self.candidate_worlds_completed = {
            "reference": 0, "selection": 0, "report": 0,
        }
        self.samplers: dict[str, dict] = {}

    def enter(self, stage: str) -> None:
        if stage not in ROW_STAGES:
            raise RuntimeRefused(f"unknown row-work stage {stage}")
        if ROW_STAGES.index(stage) < ROW_STAGES.index(self.stage):
            raise RuntimeRefused("row-work stage moved backwards")
        self.stage = stage

    def record_sampler(self, fold: str, record: Mapping[str, object]) -> None:
        if fold not in {"selection", "report"} or fold in self.samplers:
            raise RuntimeRefused("row-work sampler fold drift")
        self.samplers[fold] = dict(record)

    def attempted(self, fold: str) -> None:
        self.candidate_worlds_attempted[fold] += 1

    def completed(self, fold: str) -> None:
        self.candidate_worlds_completed[fold] += 1

    def set_reference(self, candidate_worlds: int) -> None:
        if (isinstance(candidate_worlds, bool)
                or not isinstance(candidate_worlds, int)
                or candidate_worlds < 0):
            raise RuntimeRefused("reference work is not a non-negative integer")
        self.candidate_worlds_attempted["reference"] = candidate_worlds
        self.candidate_worlds_completed["reference"] = candidate_worlds

    def snapshot(self) -> dict:
        attempted = dict(self.candidate_worlds_attempted)
        completed = dict(self.candidate_worlds_completed)
        return {
            "accounting_complete": True,
            "last_stage": self.stage,
            "candidate_worlds_attempted": attempted,
            "candidate_worlds_completed": completed,
            "total_candidate_worlds_attempted": sum(attempted.values()),
            "total_candidate_worlds_completed": sum(completed.values()),
            "samplers": dict(sorted(self.samplers.items())),
        }


def _git(*args: str) -> str:
    return CTRL._git(*args)


def _load_json(path: Path) -> dict:
    try:
        return CTRL._load_json(path)
    except CTRL.ControllerRefused as exc:
        raise RuntimeRefused(str(exc)) from exc


def _external_sha(packet: Mapping[str, object]) -> str:
    return CTRL.sha256_bytes(CTRL.canonical_json(packet))


def _is_terminal_file(path: Path) -> bool:
    return (CTRL.is_regular_unlinked(path)
            and not os.path.lexists(Path(str(path) + ".partial")))


def _self_hash(payload: Mapping[str, object], field: str) -> str:
    return CTRL.sha256_bytes(CTRL.canonical_json({
        key: value for key, value in payload.items() if key != field
    }))


def _expected_slot_path() -> Path:
    return (REPO / CTRL.admission_slot_logical_path()).resolve()


def _controller_packet(path: Path, expected_sha256: str | None = None) -> dict:
    try:
        execution_runtime = CTRL.require_execution_runtime()
    except CTRL.ControllerRefused as exc:
        raise RuntimeRefused(str(exc)) from exc
    if _git("status", "--porcelain"):
        raise RuntimeRefused("H0 runtime refuses a dirty tree")
    if not _is_terminal_file(path):
        raise RuntimeRefused("controller packet is not regular/unlinked")
    actual_sha = CTRL.sha256_file(path)
    if expected_sha256 is not None and actual_sha != expected_sha256:
        raise RuntimeRefused("controller packet SHA-256 drift")
    packet = _load_json(path)
    if (packet.get("schema") != CTRL.SCHEMA
            or packet.get("packet_id") != CTRL.PACKET_ID
            or packet.get("run_id") != CTRL.RUN_ID
            or packet.get("packet_sha256") !=
            CTRL.sha256_bytes(CTRL.canonical_json({
                key: value for key, value in packet.items()
                if key != "packet_sha256"
            }))):
        raise RuntimeRefused("controller packet identity/self-hash drift")
    authority = packet.get("authority", {})
    if (authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("counterfactual_execution_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        raise RuntimeRefused("controller packet authority widened")
    if packet.get("producer", {}).get("git") != _git("rev-parse", "HEAD"):
        raise RuntimeRefused("controller packet Git differs from runtime")
    if packet.get("execution_runtime") != execution_runtime:
        raise RuntimeRefused("controller packet execution runtime drift")
    return packet


def _expected_review_claim(packet: dict, packet_sha256: str) -> dict:
    return {
        "schema": CTRL.REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_script_sha256": packet["producer"]["script_sha256"],
        "runtime_script_sha256": packet["runtime_sources"][
            "server/scripts/h0_human_counterfactual_runtime.py"],
        "packet_sha256": packet_sha256,
        "design_packet_sha256": CTRL.DESIGN_PACKET_SHA256,
        "design_review_git": CTRL.DESIGN_REVIEW_GIT,
        "corpus_manifest_sha256": CTRL.CORPUS_MANIFEST_SHA256,
        "source_manifest_sha256": CTRL.SOURCE_MANIFEST_SHA256,
        "v11_checkpoint_sha256": CTRL.V11PAIR_SHA256,
        "selected_play_rows_sha256": CTRL.SELECTED_PLAY_ROWS_SHA256,
        "selected_bury_rows_sha256": CTRL.SELECTED_BURY_ROWS_SHA256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "candidate_geometry_sha256": packet["score_free_preflight"][
            "candidate_geometry_sha256"],
        "max_candidate_worlds": CTRL.MAX_CANDIDATE_WORLDS,
        "score_free_preflight_verified": True,
        "strict_runtime_verified": True,
        "fast_router_sha256": packet["execution_runtime"][
            "fast_router_sha256"],
        "compiled_fast_binary_sha256": packet["execution_runtime"][
            "compiled_fast_binary_sha256"],
        "admission_slot_logical_path": CTRL.admission_slot_logical_path(),
        "deletion_proof_one_shot": True,
        "worlds_sampled_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "one_counterfactual_execution_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _review_claim(review_record: Path, packet: dict,
                  packet_sha256: str) -> dict:
    if not _is_terminal_file(review_record):
        raise RuntimeRefused("controller review record is not regular/unlinked")
    try:
        claim = CTRL._marker_claim(review_record, CTRL.REVIEW_MARKER)
    except CTRL.ControllerRefused as exc:
        raise RuntimeRefused(str(exc)) from exc
    expected = _expected_review_claim(packet, packet_sha256)
    if claim != expected:
        raise RuntimeRefused("controller review marker drift")
    return claim


def _validate_current_inputs(packet: dict, design_path: Path, corpus: Path,
                             source_root: Path, source_manifest: Path,
                             v11_checkpoint: Path) -> dict:
    try:
        design = CTRL.validate_design_packet(design_path)
        manifest, _plays, _buries, catalog = CTRL.validate_inputs(
            design, corpus, source_root, source_manifest, v11_checkpoint)
        parent = LIVE_PARENT.require_portable_live_champion_parent()
    except (CTRL.ControllerRefused, LIVE_PARENT.ProtocolRefused) as exc:
        raise RuntimeRefused(str(exc)) from exc
    if parent != packet.get("inputs", {}).get("live_parent"):
        raise RuntimeRefused("live parent drift since controller freeze")
    if CTRL.runtime_sources() != packet.get("runtime_sources"):
        raise RuntimeRefused("runtime transitive source drift")
    if CTRL.build_schedule(design) != packet.get("schedule"):
        raise RuntimeRefused("runtime schedule drift")
    preflight = CTRL.score_free_preflight(design, source_root, v11_checkpoint)
    if preflight != packet.get("score_free_preflight"):
        raise RuntimeRefused("runtime score-free candidate geometry drift")
    if (manifest.get("producer_git") != packet["inputs"]["human_corpus"][
            "producer_git"]
            or catalog != packet["inputs"]["source_snapshot"]["members"]):
        raise RuntimeRefused("runtime corpus/source catalog drift")
    return design


def _receipt(path: Path, expected_sha256: str | None,
             packet: dict, packet_sha256: str) -> dict:
    expected_path = (REPO / "server" / "runs" / "logs" / CTRL.RUN_ID /
                     "execution-receipt.json").resolve()
    if path.resolve() != expected_path:
        raise RuntimeRefused("execution receipt differs from reviewed path")
    if not _is_terminal_file(path):
        raise RuntimeRefused("execution receipt is not regular/unlinked")
    if expected_sha256 is not None and CTRL.sha256_file(path) != expected_sha256:
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
        "design_and_audit_launch_together": True,
        "counterfactual_execution_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    for key, expected in fixed.items():
        if receipt.get(key) != expected:
            raise RuntimeRefused(f"execution receipt field drift: {key}")
    if receipt.get("review_claim", {}).get(
            "one_counterfactual_execution_authorized") is not True:
        raise RuntimeRefused("execution receipt lacks reviewed one-shot authority")
    if receipt.get("review_claim") != _expected_review_claim(
            packet, packet_sha256):
        raise RuntimeRefused("execution receipt review claim drift")
    if receipt.get("input_identities") != packet.get("inputs"):
        raise RuntimeRefused("execution receipt input identities drift")
    if receipt.get("receipt_sha256") != _self_hash(
            receipt, "receipt_sha256"):
        raise RuntimeRefused("execution receipt self-hash drift")
    slot_path = _expected_slot_path()
    if not _is_terminal_file(slot_path):
        raise RuntimeRefused("durable admission slot is missing")
    slot = _load_json(slot_path)
    expected_slot = {
        "schema": CTRL.ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(expected_path),
        "receipt_file_sha256": CTRL.sha256_file(path),
        "consumed_even_if_receipt_publication_fails": True,
    }
    expected_slot["slot_sha256"] = _self_hash(expected_slot, "slot_sha256")
    if slot != expected_slot:
        raise RuntimeRefused("durable admission slot drift")
    return receipt


def admit(*, packet_path: Path, expected_packet_sha256: str,
          review_record: Path, receipt_path: Path, namespace: Path,
          design_path: Path, corpus: Path, source_root: Path,
          source_manifest: Path, v11_checkpoint: Path) -> dict:
    packet = _controller_packet(packet_path, expected_packet_sha256)
    design = _validate_current_inputs(
        packet, design_path, corpus, source_root, source_manifest,
        v11_checkpoint)
    del design
    claim = _review_claim(review_record, packet, expected_packet_sha256)
    expected_namespace = (REPO / "server" / "runs" / "logs" /
                          CTRL.RUN_ID).resolve()
    if namespace.resolve() != expected_namespace:
        raise RuntimeRefused("execution namespace differs from reviewed path")
    if (receipt_path.parent.resolve() != namespace.resolve()
            or receipt_path.name != "execution-receipt.json"):
        raise RuntimeRefused("execution receipt must use its reviewed path")
    slot_path = _expected_slot_path()
    if (os.path.lexists(slot_path)
            or os.path.lexists(Path(str(slot_path) + ".partial"))):
        raise RuntimeRefused("one-shot admission slot is already consumed")
    namespace.mkdir(parents=True, exist_ok=True)
    allowed_existing = {packet_path.resolve(), review_record.resolve()}
    for path in namespace.iterdir():
        if path.resolve() not in allowed_existing:
            raise RuntimeRefused(
                f"one-shot namespace already contains execution target {path.name}")
    receipt = {
        "schema": CTRL.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "admission_slot": str(slot_path),
        "review_record_sha256": CTRL.sha256_file(review_record),
        "review_claim": claim,
        "input_identities": packet["inputs"],
        "one_shot": True,
        "design_and_audit_launch_together": True,
        "counterfactual_execution_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    slot = {
        "schema": CTRL.ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(receipt_path.resolve()),
        "receipt_file_sha256": CTRL.sha256_bytes(
            CTRL.canonical_json(receipt)),
        "consumed_even_if_receipt_publication_fails": True,
    }
    slot["slot_sha256"] = _self_hash(slot, "slot_sha256")
    # Consume authority first. A crash or receipt-publication failure may
    # strand this one run, but deleting the receipt cannot make it reusable.
    CTRL.publish_exclusive(slot_path, slot)
    CTRL.publish_exclusive(receipt_path, receipt)
    return receipt


def _sampler_snapshot(bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) for name in (
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds",
    )}


def _sampler_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict:
    return {name: after[name] - before[name] for name in before}


def _worlds_digest(worlds: Sequence[tuple]) -> str:
    keys = []
    for hands, buried in worlds:
        key = world_key(hands, buried)
        keys.append([
            [[seat, list(cards)] for seat, cards in key[0]],
            list(key[1]),
        ])
    return CTRL.sha256_bytes(CTRL.canonical_json(keys))


def draw_worlds(rnd, seat: int, count: int, seed: int, *,
                ledger: RowWorkLedger | None = None,
                fold: str | None = None) -> tuple[object, list, dict]:
    if count <= 0:
        raise RuntimeRefused("world count must be positive")
    bot = make_bot("mc-s0-report-lcb", seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    before = _sampler_snapshot(bot)
    worlds = []
    attempts = 0
    cap = count * int(bot.SAMPLE_ATTEMPT_FACTOR)
    while len(worlds) < count and attempts < cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is not None:
            worlds.append(sampled)
    after = _sampler_snapshot(bot)
    delta = _sampler_delta(before, after)
    sampler = {
        "requested": count,
        "accepted": len(worlds),
        "attempts": attempts,
        "attempt_cap": cap,
        "counters": delta,
        "world_keys_sha256": _worlds_digest(worlds),
    }
    if ledger is not None:
        if fold is None:
            raise RuntimeRefused("row-work sampler fold missing")
        ledger.record_sampler(fold, sampler)
    if (len(worlds) != count
            or delta["sample_attempts"] != attempts
            or delta["accepted_worlds"] != len(worlds)
            or delta["sample_attempts"] !=
            delta["accepted_worlds"] + delta["failed_worlds"]
            or delta["rejected_worlds"] > delta["failed_worlds"]):
        raise RuntimeRefused("strict sampler underfilled or counters diverged")
    return bot, worlds, sampler


def _score_actions(bot, rnd, seat: int, worlds: Sequence[tuple],
                   candidates: Sequence[Mapping[str, object]], *,
                   bury: bool, ledger: RowWorkLedger | None = None,
                   fold: str | None = None) -> dict:
    attacker = rnd.is_attacker(seat)
    records = []
    for candidate in candidates:
        cards = list(candidate["cards"])
        raw = []
        utilities = []
        for hands, buried_cards in worlds:
            if ledger is not None:
                if fold is None:
                    raise RuntimeRefused("row-work scoring fold missing")
                ledger.attempted(fold)
            if bury:
                points = bot._rollout_from_bury(rnd, seat, hands, cards)
            else:
                points = bot._rollout(
                    rnd, seat, hands, buried_cards, cards)
            value = CTRL.acting_utility(points, attacker=attacker)
            if ledger is not None:
                ledger.completed(fold)
            raw.append(float(points))
            utilities.append(value)
        records.append({
            "cards": list(CTRL.action_key(cards)),
            "sources": sorted(candidate.get("sources", [])),
            "raw_attacker_points": raw,
            "utilities": utilities,
            "mean_utility": sum(utilities) / len(utilities),
        })
    return {"actions": records, "candidate_worlds": len(records) * len(worlds)}


def _fixed_action_candidates(actions: Iterable[Sequence[str]],
                             union: Sequence[Mapping[str, object]]) -> list[dict]:
    sources = {CTRL.action_key(item["cards"]): sorted(item["sources"])
               for item in union}
    result = []
    seen = set()
    for action in actions:
        key = CTRL.action_key(action)
        if key not in seen:
            seen.add(key)
            result.append({"cards": list(key), "sources": sources.get(key, [])})
    return result


def _reference_action(rnd, seat: int, split: str,
                      replay_key_value: str,
                      ledger: RowWorkLedger | None = None) -> dict:
    seed = CTRL.seed_for(
        CTRL.DESIGN.REFERENCE_WORLD_DOMAIN, split, replay_key_value,
        "play", "live-report-lcb-root",
    )
    bot = make_bot("mc-s0-report-lcb", seed=seed)
    ballot = CTRL._dedupe_actions(bot._candidates(rnd, seat))
    cap = (CTRL.DESIGN.LIVE_LEAD_MAX_CANDIDATES if not rnd.trick.plays else
           CTRL.DESIGN.LIVE_FOLLOW_MAX_CANDIDATES)
    if not ballot or len(ballot) > cap:
        raise RuntimeRefused("reference ballot cap/emptiness drift")
    try:
        action = list(CTRL.action_key(bot.decide_play(rnd, seat)))
    finally:
        if ledger is not None:
            # MCBot owns exact cumulative candidate-rollout accounting. A
            # protocol refusal after decide_play therefore retains the dose;
            # an unexpected exception aborts the shard rather than converting
            # an unknowable partial inner rollout to a row refusal.
            ledger.set_reference(int(bot.rollouts))
    if CTRL.action_key(action) not in {CTRL.action_key(item) for item in ballot}:
        raise RuntimeRefused("reference action absent from production ballot")
    record = bot.last_decision_record
    if record is None:
        evidence = {
            "seed": seed,
            "action": action,
            "candidates": ballot,
            "candidate_count": len(ballot),
            "reason": "search-free-production-path",
            "selection_means": [],
            "work": {
                "selection_rollouts": 0,
                "report_rollouts": 0,
                "total_rollouts": 0,
                "complete": True,
            },
            "sampler_counters": {name: 0 for name in _sampler_snapshot(bot)},
        }
        return evidence
    work = record.get("work", {})
    sampler = record.get("sampler_counters", {}).get("delta", {})
    if (record.get("policy") != "mc-s0-report-lcb"
            or [CTRL.action_key(item) for item in record.get("candidates", [])]
            != [CTRL.action_key(item) for item in ballot]
            or CTRL.action_key(record.get("played", [])) != CTRL.action_key(action)
            or work.get("complete") is not True
            or work.get("selection_rollouts") != len(ballot) * 30
            or work.get("report_rollouts") != 600
            or work.get("total_rollouts") != len(ballot) * 30 + 600
            or work.get("total_rollouts") >
            CTRL.DESIGN.PLAY_REFERENCE_MAX_CANDIDATE_WORLDS):
        raise RuntimeRefused("reference report-LCB work/decision drift")
    report = record.get("report_fold") or {}
    evidence = {
        "seed": seed,
        "action": action,
        "candidates": ballot,
        "candidate_count": len(ballot),
        "reason": record.get("reason"),
        "raw_winner_index": record.get("raw_winner_index"),
        "report_candidate_index": record.get("report_candidate_index"),
        "played_index": record.get("played_index"),
        "selection_means": record.get("means"),
        "report": {key: report.get(key) for key in (
            "gap", "se", "worlds", "attempts", "rejected", "complete",
            "critical", "statistic", "min_gain", "rule",
        )},
        "work": {key: work.get(key) for key in (
            "selection_rollouts", "report_rollouts", "total_rollouts",
            "complete",
        )},
        "sampler_counters": sampler,
    }
    return evidence


def _estimands(report_actions: Sequence[Mapping[str, object]],
               reference: Sequence[str], human: Sequence[str],
               selected: Sequence[str]) -> dict:
    by_key = {CTRL.action_key(item["cards"]): item for item in report_actions}

    def paired(left: Sequence[str], right: Sequence[str]) -> float:
        lhs = by_key[CTRL.action_key(left)]["utilities"]
        rhs = by_key[CTRL.action_key(right)]["utilities"]
        if len(lhs) != 300 or len(rhs) != 300:
            raise RuntimeRefused("report action dose drift")
        return sum(a - b for a, b in zip(lhs, rhs, strict=True)) / 300

    return {
        "human_minus_reference_paired_utility": paired(human, reference),
        "selected_minus_reference_paired_utility": paired(selected, reference),
        "selected_minus_human_paired_utility": paired(selected, human),
    }


def run_play_row(row: Mapping[str, object], cache: CTRL.ReplayCache, net,
                 ledger: RowWorkLedger | None = None) -> dict:
    ledger = ledger or RowWorkLedger("play")
    split = str(row["split"])
    replay_key_value = str(row["replay_key"])
    ledger.enter("replay")
    rnd = CTRL.replay_play(cache, row)
    seat = int(row["seat"])
    ledger.enter("candidate-union")
    union, diagnostics = CTRL.build_play_union(
        rnd, seat, row["human_action"], split, replay_key_value, net)
    ledger.enter("reference-root")
    reference = _reference_action(
        rnd, seat, split, replay_key_value, ledger=ledger)
    if [candidate["cards"] for candidate in union[:reference["candidate_count"]]] != \
            reference["candidates"]:
        raise RuntimeRefused("pilot/live reference ballot order drift")

    selection_seed = CTRL.seed_for(
        CTRL.DESIGN.SELECTION_WORLD_DOMAIN, split, replay_key_value,
        "play", "pilot-selection",
    )
    ledger.enter("selection-sampling")
    selection_bot, selection_worlds, selection_sampler = draw_worlds(
        rnd, seat, CTRL.DESIGN.PROPOSAL_WORLDS, selection_seed,
        ledger=ledger, fold="selection")
    ledger.enter("selection-scoring")
    selection = _score_actions(
        selection_bot, rnd, seat, selection_worlds, union, bury=False,
        ledger=ledger, fold="selection")
    means = [item["mean_utility"] for item in selection["actions"]]
    if not means or not all(map(math.isfinite, means)):
        raise RuntimeRefused("pilot selection means missing/non-finite")
    winner_index = max(range(len(means)), key=lambda index: means[index])
    winner = union[winner_index]["cards"]

    report_candidates = _fixed_action_candidates(
        [reference["action"], row["human_action"], winner], union)
    if len(report_candidates) > CTRL.DESIGN.REPORT_MAX_ACTIONS:
        raise RuntimeRefused("pilot report action cap drift")
    report_seed = CTRL.seed_for(
        CTRL.DESIGN.REPORT_WORLD_DOMAIN, split, replay_key_value,
        "play", "pilot-report",
    )
    ledger.enter("report-sampling")
    report_bot, report_worlds, report_sampler = draw_worlds(
        rnd, seat, CTRL.DESIGN.REPORT_WORLDS, report_seed,
        ledger=ledger, fold="report")
    ledger.enter("report-scoring")
    report = _score_actions(
        report_bot, rnd, seat, report_worlds, report_candidates, bury=False,
        ledger=ledger, fold="report")
    estimands = _estimands(
        report["actions"], reference["action"], row["human_action"], winner)
    total_work = (reference["work"]["total_rollouts"]
                  + selection["candidate_worlds"]
                  + report["candidate_worlds"])
    if total_work > CTRL.DESIGN.PLAY_MAX_CANDIDATE_WORLDS:
        raise RuntimeRefused("play row exceeded candidate-world ceiling")
    ledger.enter("validation")
    return {
        "schema": "human-h0-counterfactual-row-v1",
        "status": "COMPLETE",
        "row_key": CTRL.row_key(split, "play", replay_key_value),
        "split": split,
        "surface_type": "play",
        "replay_key": replay_key_value,
        "deal_key": row["deal_key"],
        "player_id": row["player_id"],
        "surface": row["surface"],
        "phase": row["phase"],
        "role": row["role"],
        "human_action": list(CTRL.action_key(row["human_action"])),
        "candidate_diagnostics": diagnostics,
        "candidates": union,
        "reference": reference,
        "selection": {
            "seed": selection_seed,
            "sampler": selection_sampler,
            **selection,
            "winner_index": winner_index,
            "winner": winner,
            "winner_sources": union[winner_index]["sources"],
        },
        "report": {
            "seed": report_seed,
            "sampler": report_sampler,
            **report,
        },
        "estimands": estimands,
        "work": {
            "reference_candidate_worlds": reference["work"]["total_rollouts"],
            "selection_candidate_worlds": selection["candidate_worlds"],
            "report_candidate_worlds": report["candidate_worlds"],
            "total_candidate_worlds": total_work,
            "max_candidate_worlds": CTRL.DESIGN.PLAY_MAX_CANDIDATE_WORLDS,
            "complete": True,
        },
    }


def run_bury_row(row: Mapping[str, object], cache: CTRL.ReplayCache,
                 ledger: RowWorkLedger | None = None) -> dict:
    ledger = ledger or RowWorkLedger("bury")
    split = str(row["split"])
    replay_key_value = str(row["replay_key"])
    ledger.enter("replay")
    rnd = CTRL.replay_bury(cache, row)
    seat = int(row["seat"])
    ledger.enter("candidate-union")
    union, diagnostics = CTRL.build_bury_union(
        rnd, seat, row["human_bury"])
    reference = union[0]["cards"]
    selection_seed = CTRL.seed_for(
        CTRL.DESIGN.SELECTION_WORLD_DOMAIN, split, replay_key_value,
        "bury", "pilot-selection",
    )
    ledger.enter("selection-sampling")
    selection_bot, selection_worlds, selection_sampler = draw_worlds(
        rnd, seat, CTRL.DESIGN.PROPOSAL_WORLDS, selection_seed,
        ledger=ledger, fold="selection")
    ledger.enter("selection-scoring")
    selection = _score_actions(
        selection_bot, rnd, seat, selection_worlds, union, bury=True,
        ledger=ledger, fold="selection")
    means = [item["mean_utility"] for item in selection["actions"]]
    if not means or not all(map(math.isfinite, means)):
        raise RuntimeRefused("bury selection means missing/non-finite")
    winner_index = max(range(len(means)), key=lambda index: means[index])
    winner = union[winner_index]["cards"]
    report_candidates = _fixed_action_candidates(
        [reference, row["human_bury"], winner], union)
    report_seed = CTRL.seed_for(
        CTRL.DESIGN.REPORT_WORLD_DOMAIN, split, replay_key_value,
        "bury", "pilot-report",
    )
    ledger.enter("report-sampling")
    report_bot, report_worlds, report_sampler = draw_worlds(
        rnd, seat, CTRL.DESIGN.REPORT_WORLDS, report_seed,
        ledger=ledger, fold="report")
    ledger.enter("report-scoring")
    report = _score_actions(
        report_bot, rnd, seat, report_worlds, report_candidates, bury=True,
        ledger=ledger, fold="report")
    estimands = _estimands(
        report["actions"], reference, row["human_bury"], winner)
    total_work = selection["candidate_worlds"] + report["candidate_worlds"]
    if total_work > CTRL.DESIGN.BURY_MAX_CANDIDATE_WORLDS:
        raise RuntimeRefused("bury row exceeded candidate-world ceiling")
    ledger.enter("validation")
    return {
        "schema": "human-h0-counterfactual-row-v1",
        "status": "COMPLETE",
        "row_key": CTRL.row_key(split, "bury", replay_key_value),
        "split": split,
        "surface_type": "bury",
        "replay_key": replay_key_value,
        "deal_key": row["deal_key"],
        "player_id": row["player_id"],
        "surface": "bury",
        "phase": "pre-play",
        "role": "defender",
        "human_action": list(CTRL.action_key(row["human_bury"])),
        "candidate_diagnostics": diagnostics,
        "candidates": union,
        "reference": {
            "action": reference,
            "candidate_count": len(union),
            "reason": "live-smart-bury-candidate-zero",
            "work": {"total_rollouts": 0, "complete": True},
        },
        "selection": {
            "seed": selection_seed,
            "sampler": selection_sampler,
            **selection,
            "winner_index": winner_index,
            "winner": winner,
            "winner_sources": union[winner_index]["sources"],
        },
        "report": {
            "seed": report_seed,
            "sampler": report_sampler,
            **report,
        },
        "estimands": estimands,
        "work": {
            "reference_candidate_worlds": 0,
            "selection_candidate_worlds": selection["candidate_worlds"],
            "report_candidate_worlds": report["candidate_worlds"],
            "total_candidate_worlds": total_work,
            "max_candidate_worlds": CTRL.DESIGN.BURY_MAX_CANDIDATE_WORLDS,
            "complete": True,
        },
    }


def _refusal(row: Mapping[str, object], exc: BaseException,
             ledger: RowWorkLedger | None = None) -> dict:
    split = str(row["split"])
    surface = str(row["surface_type"])
    reason = f"{type(exc).__name__}:{exc}"
    return {
        "schema": "human-h0-counterfactual-row-v1",
        "status": "REFUSED_SCORE_FREE",
        "row_key": CTRL.row_key(split, surface, str(row["replay_key"])),
        "split": split,
        "surface_type": surface,
        "replay_key": row["replay_key"],
        "deal_key": row["deal_key"],
        "player_id": row["player_id"],
        "surface": row.get("surface", "bury"),
        "phase": row.get("phase", "pre-play"),
        "role": row.get("role", "defender"),
        "reason_class": type(exc).__name__,
        "reason_sha256": hashlib.sha256(reason.encode()).hexdigest(),
        "attempted_work": (ledger or RowWorkLedger(surface)).snapshot(),
        "utility_published": False,
        "outcomes_published": False,
    }


def _derive_utilities(raw: Sequence[object], *, attacker: bool) -> list[float]:
    return [CTRL.acting_utility(float(value), attacker=attacker) for value in raw]


def _validate_sampler_record(value: object, *, expected_worlds: int,
                             require_complete: bool = True) -> None:
    if not isinstance(value, dict):
        raise RuntimeRefused("fold sampler record missing")
    counters = value.get("counters")
    names = {
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds",
    }
    if (not isinstance(counters, dict) or set(counters) != names
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or item < 0 for item in counters.values())):
        raise RuntimeRefused("fold sampler counters malformed")
    attempts = value.get("attempts")
    cap = value.get("attempt_cap")
    accepted = value.get("accepted")
    if (value.get("requested") != expected_worlds
            or isinstance(accepted, bool) or not isinstance(accepted, int)
            or not 0 <= accepted <= expected_worlds
            or (require_complete and accepted != expected_worlds)
            or isinstance(attempts, bool) or not isinstance(attempts, int)
            or not accepted <= attempts <= expected_worlds * 40
            or (accepted < expected_worlds
                and attempts != expected_worlds * 40)
            or cap != expected_worlds * 40
            or counters["sample_attempts"] != attempts
            or counters["accepted_worlds"] != accepted
            or counters["sample_attempts"] !=
            counters["accepted_worlds"] + counters["failed_worlds"]
            or counters["rejected_worlds"] > counters["failed_worlds"]
            or not CTRL.is_sha256(value.get("world_keys_sha256"))):
        raise RuntimeRefused("fold sampler work does not reconcile")


def _validate_refusal_work(value: object, *, surface: str) -> None:
    if not isinstance(value, dict) or set(value) != {
        "accounting_complete", "last_stage",
        "candidate_worlds_attempted", "candidate_worlds_completed",
        "total_candidate_worlds_attempted",
        "total_candidate_worlds_completed", "samplers",
    }:
        raise RuntimeRefused("refused row work ledger malformed")
    if (value["accounting_complete"] is not True
            or value["last_stage"] not in ROW_STAGES):
        raise RuntimeRefused("refused row work ledger is not exact")
    attempted = value["candidate_worlds_attempted"]
    completed = value["candidate_worlds_completed"]
    folds = {"reference", "selection", "report"}
    if (not isinstance(attempted, dict) or set(attempted) != folds
            or not isinstance(completed, dict) or set(completed) != folds
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or item < 0 for item in [*attempted.values(),
                                           *completed.values()])
            or any(completed[fold] > attempted[fold] for fold in folds)
            or isinstance(value["total_candidate_worlds_attempted"], bool)
            or not isinstance(value["total_candidate_worlds_attempted"], int)
            or isinstance(value["total_candidate_worlds_completed"], bool)
            or not isinstance(value["total_candidate_worlds_completed"], int)
            or value["total_candidate_worlds_attempted"] !=
            sum(attempted.values())
            or value["total_candidate_worlds_completed"] !=
            sum(completed.values())):
        raise RuntimeRefused("refused row candidate-work accounting drift")
    ceiling = (CTRL.DESIGN.PLAY_MAX_CANDIDATE_WORLDS
               if surface == "play"
               else CTRL.DESIGN.BURY_MAX_CANDIDATE_WORLDS)
    selection_ceiling = (
        (CTRL.DESIGN.PLAY_MAX_UNIQUE_CANDIDATES if surface == "play"
         else CTRL.DESIGN.BURY_MAX_UNIQUE_CANDIDATES)
        * CTRL.DESIGN.PROPOSAL_WORLDS
    )
    if (value["total_candidate_worlds_attempted"] > ceiling
            or attempted["reference"] != completed["reference"]
            or (surface == "bury" and attempted["reference"] != 0)
            or attempted["selection"] > selection_ceiling):
        raise RuntimeRefused("refused row work ceiling drift")
    if attempted["report"] > (CTRL.DESIGN.REPORT_MAX_ACTIONS *
                               CTRL.DESIGN.REPORT_WORLDS):
        raise RuntimeRefused("refused row report work ceiling drift")
    samplers = value["samplers"]
    if (not isinstance(samplers, dict)
            or not set(samplers) <= {"selection", "report"}):
        raise RuntimeRefused("refused row sampler population drift")
    for fold, record in samplers.items():
        expected = (CTRL.DESIGN.PROPOSAL_WORLDS if fold == "selection"
                    else CTRL.DESIGN.REPORT_WORLDS)
        _validate_sampler_record(
            record, expected_worlds=expected, require_complete=False)


def _validate_complete_ledger(row: Mapping[str, object],
                              ledger: RowWorkLedger) -> None:
    snapshot = ledger.snapshot()
    work = row["work"]
    expected = {
        "reference": work["reference_candidate_worlds"],
        "selection": work["selection_candidate_worlds"],
        "report": work["report_candidate_worlds"],
    }
    if (snapshot["candidate_worlds_attempted"] != expected
            or snapshot["candidate_worlds_completed"] != expected
            or snapshot["samplers"] != {
                "report": row["report"]["sampler"],
                "selection": row["selection"]["sampler"],
            }):
        raise RuntimeRefused("complete row execution ledger drift")


def _validate_candidate_diagnostics(row: Mapping[str, object],
                                    candidates: Sequence[Mapping[str, object]]) -> None:
    diagnostics = row.get("candidate_diagnostics")
    if not isinstance(diagnostics, dict):
        raise RuntimeRefused("candidate diagnostics missing")
    if row["surface_type"] == "play":
        expected_keys = {
            "live_candidates", "analysis_actions", "novel_pool",
            "human_in_live_ballot", "v11_proposed", "random_proposed",
            "v11_random_same", "v11_score_count",
        }
        if set(diagnostics) != expected_keys:
            raise RuntimeRefused("play candidate diagnostics schema drift")
        integer_keys = {
            "live_candidates", "analysis_actions", "novel_pool",
            "v11_score_count",
        }
        boolean_keys = expected_keys - integer_keys
        if (any(isinstance(diagnostics[key], bool)
                or not isinstance(diagnostics[key], int)
                or diagnostics[key] < 0 for key in integer_keys)
                or any(not isinstance(diagnostics[key], bool)
                       for key in boolean_keys)):
            raise RuntimeRefused("play candidate diagnostics type drift")
        live_count = sum(
            "live_production_ballot" in item["sources"] for item in candidates)
        human_item = next(item for item in candidates
                          if "human_action" in item["sources"])
        v11_count = sum(
            "v11pair_top_proposal" in item["sources"] for item in candidates)
        random_count = sum(
            "matched_random_proposal" in item["sources"] for item in candidates)
        if (diagnostics["live_candidates"] != live_count
                or not 1 <= live_count <=
                (CTRL.DESIGN.LIVE_LEAD_MAX_CANDIDATES
                 if row["surface"] == "lead"
                 else CTRL.DESIGN.LIVE_FOLLOW_MAX_CANDIDATES)
                or diagnostics["analysis_actions"] < live_count
                or diagnostics["v11_score_count"] != diagnostics["novel_pool"]
                or diagnostics["human_in_live_ballot"] !=
                ("live_production_ballot" in human_item["sources"])
                or diagnostics["v11_proposed"] != (v11_count == 1)
                or diagnostics["random_proposed"] != (random_count == 1)
                or diagnostics["v11_proposed"] !=
                (diagnostics["novel_pool"] > 0)
                or diagnostics["random_proposed"] !=
                diagnostics["v11_proposed"]):
            raise RuntimeRefused("play candidate diagnostics do not reconcile")
        v11_item = next((item for item in candidates
                         if "v11pair_top_proposal" in item["sources"]), None)
        random_item = next((item for item in candidates
                            if "matched_random_proposal" in item["sources"]), None)
        if diagnostics["v11_random_same"] != (
                v11_item is not None and random_item is not None
                and CTRL.action_key(v11_item["cards"]) ==
                CTRL.action_key(random_item["cards"])):
            raise RuntimeRefused("play proposal-overlap diagnostic drift")
        return

    expected_keys = {
        "structured_candidates", "structured_generated_unique",
        "structured_truncated", "human_in_structured_ballot",
    }
    if set(diagnostics) != expected_keys:
        raise RuntimeRefused("bury candidate diagnostics schema drift")
    if (any(isinstance(diagnostics[key], bool)
            or not isinstance(diagnostics[key], int)
            or diagnostics[key] < 0 for key in (
                "structured_candidates", "structured_generated_unique"))
            or not isinstance(diagnostics["structured_truncated"], bool)
            or not isinstance(diagnostics["human_in_structured_ballot"], bool)):
        raise RuntimeRefused("bury candidate diagnostics type drift")
    structured_count = sum(
        "structured_bury_ballot" in item["sources"] for item in candidates)
    human_item = next(item for item in candidates
                      if "human_action" in item["sources"])
    if (diagnostics["structured_candidates"] != structured_count
            or not 1 <= structured_count <=
            CTRL.DESIGN.BURY_STRUCTURED_MAX_CANDIDATES
            or diagnostics["structured_generated_unique"] < structured_count
            or diagnostics["human_in_structured_ballot"] !=
            ("structured_bury_ballot" in human_item["sources"])):
        raise RuntimeRefused("bury candidate diagnostics do not reconcile")


def _validate_reference_record(row: Mapping[str, object],
                               candidates: Sequence[Mapping[str, object]]) -> int:
    reference = row["reference"]
    surface = row["surface_type"]
    if surface == "bury":
        if (reference.get("candidate_count") != len(candidates)
                or reference.get("reason") !=
                "live-smart-bury-candidate-zero"
                or reference.get("work") != {
                    "total_rollouts": 0, "complete": True}):
            raise RuntimeRefused("complete bury reference drift")
        return 0

    expected_seed = CTRL.seed_for(
        CTRL.DESIGN.REFERENCE_WORLD_DOMAIN, str(row["split"]),
        str(row["replay_key"]), "play", "live-report-lcb-root")
    live = [item for item in candidates
            if "live_production_ballot" in item["sources"]]
    live_keys = [CTRL.action_key(item["cards"]) for item in live]
    reference_candidates = reference.get("candidates")
    if (reference.get("seed") != expected_seed
            or reference.get("candidate_count") != len(live)
            or not isinstance(reference_candidates, list)
            or [CTRL.action_key(item) for item in reference_candidates] != live_keys
            or CTRL.action_key(reference.get("action", [])) not in live_keys):
        raise RuntimeRefused("complete play reference identity drift")
    work = reference.get("work")
    sampler = reference.get("sampler_counters")
    if reference.get("reason") == "search-free-production-path":
        if (reference.get("selection_means") != []
                or work != {
                    "selection_rollouts": 0, "report_rollouts": 0,
                    "total_rollouts": 0, "complete": True,
                }
                or sampler != {name: 0 for name in (
                    "sample_attempts", "accepted_worlds", "failed_worlds",
                    "rejected_worlds", "impossible_worlds")}):
            raise RuntimeRefused("search-free reference work drift")
        return 0
    expected_selection = len(live) * 30
    expected_report = 2 * CTRL.DESIGN.REPORT_WORLDS
    indices = {
        "raw_winner_index": reference.get("raw_winner_index"),
        "report_candidate_index": reference.get("report_candidate_index"),
        "played_index": reference.get("played_index"),
    }
    if (len(live) <= 1
            or not isinstance(work, dict) or work != {
            "selection_rollouts": expected_selection,
            "report_rollouts": expected_report,
            "total_rollouts": expected_selection + expected_report,
            "complete": True,
            }
            or not isinstance(reference.get("selection_means"), list)
            or len(reference["selection_means"]) != len(live)
            or not all(isinstance(value, (int, float))
                       and not isinstance(value, bool) and math.isfinite(value)
                       for value in reference["selection_means"])
            or not isinstance(sampler, dict)
            or set(sampler) != {
                "sample_attempts", "accepted_worlds", "failed_worlds",
                "rejected_worlds", "impossible_worlds"}
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in sampler.values())
            or sampler["accepted_worlds"] != 30 + CTRL.DESIGN.REPORT_WORLDS
            or not 30 + CTRL.DESIGN.REPORT_WORLDS <=
            sampler["sample_attempts"] <=
            30 * 40 + CTRL.DESIGN.REPORT_WORLDS * 40
            or sampler["sample_attempts"] !=
            sampler["accepted_worlds"] + sampler["failed_worlds"]
            or sampler["rejected_worlds"] > sampler["failed_worlds"]
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or not 0 <= value < len(live) for value in indices.values())
            or live_keys[indices["played_index"]] !=
            CTRL.action_key(reference["action"])
            or reference.get("reason") not in {
                "report_lcb_below_min_gain", "report_lcb_override",
            }):
        raise RuntimeRefused("searched reference work drift")
    report = reference.get("report")
    if (not isinstance(report, dict) or set(report) != {
            "gap", "se", "worlds", "attempts", "rejected", "complete",
            "critical", "statistic", "min_gain", "rule",
            }
            or report.get("worlds") != CTRL.DESIGN.REPORT_WORLDS
            or report.get("complete") is not True
            or report.get("rule") != "lcb"
            or report.get("min_gain") != 0.0
            or report.get("critical") != 1.70
            or isinstance(report.get("attempts"), bool)
            or not isinstance(report.get("attempts"), int)
            or not CTRL.DESIGN.REPORT_WORLDS <= report["attempts"] <=
            CTRL.DESIGN.REPORT_WORLDS * 40
            or report.get("rejected") !=
            report["attempts"] - CTRL.DESIGN.REPORT_WORLDS
            or any(isinstance(report.get(name), bool)
                   or not isinstance(report.get(name), (int, float))
                   or not math.isfinite(report[name])
                   for name in ("gap", "se", "statistic"))):
        raise RuntimeRefused("searched reference report-fold drift")
    return expected_selection + expected_report


def validate_complete_row(row: Mapping[str, object]) -> None:
    if row.get("schema") != "human-h0-counterfactual-row-v1":
        raise RuntimeRefused("row schema drift")
    if row.get("status") == "REFUSED_SCORE_FREE":
        forbidden = set(CTRL.result_contract({"schedule_sha256": "x"})[
            "refused_row_forbids"])
        if forbidden & set(row):
            raise RuntimeRefused("refused row leaked outcome-bearing fields")
        if (row.get("utility_published") is not False
                or row.get("outcomes_published") is not False):
            raise RuntimeRefused("refused row publication flags drift")
        surface = row.get("surface_type")
        if surface not in {"play", "bury"}:
            raise RuntimeRefused("refused row surface drift")
        if (row.get("row_key") != CTRL.row_key(
                str(row.get("split")), str(surface),
                str(row.get("replay_key")))
                or not CTRL.is_sha256(row.get("reason_sha256"))):
            raise RuntimeRefused("refused row identity drift")
        _validate_refusal_work(row.get("attempted_work"), surface=surface)
        return
    if row.get("status") != "COMPLETE":
        raise RuntimeRefused("unknown row terminal state")
    surface = row.get("surface_type")
    if surface not in {"play", "bury"}:
        raise RuntimeRefused("row surface drift")
    candidates = row.get("candidates")
    selection = row.get("selection", {})
    report = row.get("report", {})
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeRefused("complete row missing candidates")
    expected_row_key = CTRL.row_key(
        str(row.get("split")), str(surface), str(row.get("replay_key")))
    if row.get("row_key") != expected_row_key:
        raise RuntimeRefused("complete row replay-key identity drift")
    keys = [CTRL.action_key(item.get("cards", [])) for item in candidates]
    if len(keys) != len(set(keys)):
        raise RuntimeRefused("complete row has duplicate candidates")
    cap = (CTRL.DESIGN.PLAY_MAX_UNIQUE_CANDIDATES if surface == "play"
           else CTRL.DESIGN.BURY_MAX_UNIQUE_CANDIDATES)
    if len(candidates) > cap:
        raise RuntimeRefused("complete row candidate cap drift")
    allowed_sources = {
        "live_production_ballot", "human_action", "v11pair_top_proposal",
        "matched_random_proposal", "structured_bury_ballot", "incumbent",
        "point_preserving", "trump_preserving", "pair_preserving",
        "short_suit", "low_strength",
    }
    for item in candidates:
        sources = item.get("sources")
        if (not isinstance(sources, list) or sources != sorted(set(sources))
                or not sources
                or any(not isinstance(source, str) for source in sources)
                or any(source not in allowed_sources and
                       not source.startswith("void:") and
                       ":boundary+" not in source for source in sources)):
            raise RuntimeRefused("complete row candidate source attribution drift")
    human_key = CTRL.action_key(row.get("human_action", []))
    if human_key not in keys or "human_action" not in candidates[
            keys.index(human_key)]["sources"]:
        raise RuntimeRefused("complete row human source attribution drift")
    _validate_candidate_diagnostics(row, candidates)
    reference_key = CTRL.action_key(row.get("reference", {}).get("action", []))
    if reference_key not in keys:
        raise RuntimeRefused("complete row reference absent from union")
    reference_work = _validate_reference_record(row, candidates)
    expected_selection_seed = CTRL.seed_for(
        CTRL.DESIGN.SELECTION_WORLD_DOMAIN, str(row["split"]),
        str(row["replay_key"]), str(surface), "pilot-selection")
    expected_report_seed = CTRL.seed_for(
        CTRL.DESIGN.REPORT_WORLD_DOMAIN, str(row["split"]),
        str(row["replay_key"]), str(surface), "pilot-report")
    if (selection.get("seed") != expected_selection_seed
            or report.get("seed") != expected_report_seed
            or expected_selection_seed == expected_report_seed):
        raise RuntimeRefused("complete row fold seed drift")
    _validate_sampler_record(
        selection.get("sampler"),
        expected_worlds=CTRL.DESIGN.PROPOSAL_WORLDS)
    _validate_sampler_record(
        report.get("sampler"), expected_worlds=CTRL.DESIGN.REPORT_WORLDS)
    selection_actions = selection.get("actions")
    if (not isinstance(selection_actions, list)
            or [CTRL.action_key(item.get("cards", []))
                for item in selection_actions] != keys):
        raise RuntimeRefused("selection action population drift")
    for item, candidate in zip(selection_actions, candidates, strict=True):
        raw = item.get("raw_attacker_points")
        expected = _derive_utilities(
            raw, attacker=row.get("role") == "attacker")
        if (len(raw) != CTRL.DESIGN.PROPOSAL_WORLDS
                or item.get("sources") != candidate.get("sources")
                or item.get("utilities") != expected
                or item.get("mean_utility") != sum(expected) / len(expected)):
            raise RuntimeRefused("selection raw/utility derivation drift")
    winner_index = selection.get("winner_index")
    means = [item["mean_utility"] for item in selection_actions]
    expected_winner = max(range(len(means)), key=lambda index: means[index])
    if (winner_index != expected_winner
            or CTRL.action_key(selection.get("winner", [])) != keys[expected_winner]
            or sorted(selection.get("winner_sources", [])) !=
            sorted(candidates[expected_winner].get("sources", []))):
        raise RuntimeRefused("selection winner drift")
    report_actions = report.get("actions")
    if not isinstance(report_actions, list) or not 1 <= len(report_actions) <= 3:
        raise RuntimeRefused("report action population drift")
    candidate_by_key = {
        CTRL.action_key(item["cards"]): item for item in candidates}
    for item in report_actions:
        item_key = CTRL.action_key(item.get("cards", []))
        if item_key not in candidate_by_key:
            raise RuntimeRefused("report action absent from candidate union")
        raw = item.get("raw_attacker_points")
        expected = _derive_utilities(
            raw, attacker=row.get("role") == "attacker")
        if (len(raw) != CTRL.DESIGN.REPORT_WORLDS
                or item.get("sources") != candidate_by_key[item_key].get("sources")
                or item.get("utilities") != expected
                or item.get("mean_utility") != sum(expected) / len(expected)):
            raise RuntimeRefused("report raw/utility derivation drift")
    expected_report_keys = []
    for key in (reference_key, human_key,
                CTRL.action_key(selection.get("winner", []))):
        if key not in expected_report_keys:
            expected_report_keys.append(key)
    if [CTRL.action_key(item.get("cards", []))
            for item in report_actions] != expected_report_keys:
        raise RuntimeRefused("report fixed-action population/order drift")
    expected_estimands = _estimands(
        report_actions, row["reference"]["action"], row["human_action"],
        selection["winner"])
    if row.get("estimands") != expected_estimands:
        raise RuntimeRefused("row estimands drift")
    expected_selection_work = len(candidates) * CTRL.DESIGN.PROPOSAL_WORLDS
    expected_report_work = len(report_actions) * CTRL.DESIGN.REPORT_WORLDS
    if (selection.get("candidate_worlds") != expected_selection_work
            or report.get("candidate_worlds") != expected_report_work):
        raise RuntimeRefused("fold candidate-world work drift")
    work = row.get("work", {})
    ceiling = (CTRL.DESIGN.PLAY_MAX_CANDIDATE_WORLDS if surface == "play"
               else CTRL.DESIGN.BURY_MAX_CANDIDATE_WORLDS)
    if work != {
        "reference_candidate_worlds": reference_work,
        "selection_candidate_worlds": expected_selection_work,
        "report_candidate_worlds": expected_report_work,
        "total_candidate_worlds": (
            reference_work + expected_selection_work + expected_report_work),
        "max_candidate_worlds": ceiling,
        "complete": True,
    } or work["total_candidate_worlds"] > ceiling:
        raise RuntimeRefused("row work accounting drift")


def _rows_for_shard(design: dict, packet: dict, shard_index: int) -> list[dict]:
    if not 0 <= shard_index < CTRL.SHARD_COUNT:
        raise RuntimeRefused("shard index outside reviewed population")
    wanted = set(packet["schedule"]["shards"][shard_index]["row_keys"])
    rows = [row for row in CTRL.selected_rows(design)
            if CTRL.row_key(row["split"], row["surface_type"],
                            row["replay_key"]) in wanted]
    actual = {CTRL.row_key(row["split"], row["surface_type"],
                           row["replay_key"]) for row in rows}
    if actual != wanted or len(rows) != len(wanted):
        raise RuntimeRefused("shard schedule row population drift")
    return rows


def _expected_shard_path(index: int) -> Path:
    return (REPO / "server" / "runs" / "logs" / CTRL.RUN_ID /
            f"shard-{index:02d}.json").resolve()


def _expected_aggregate_path() -> Path:
    return (REPO / "server" / "runs" / "logs" / CTRL.RUN_ID /
            "aggregate.json").resolve()


def run_shard(*, packet_path: Path, expected_packet_sha256: str,
              receipt_path: Path, expected_receipt_sha256: str,
              design_path: Path, corpus: Path, source_root: Path,
              source_manifest: Path, v11_checkpoint: Path,
              shard_index: int, out: Path, progress_every: int) -> dict:
    packet = _controller_packet(packet_path, expected_packet_sha256)
    receipt = _receipt(
        receipt_path, expected_receipt_sha256, packet,
        expected_packet_sha256)
    design = _validate_current_inputs(
        packet, design_path, corpus, source_root, source_manifest,
        v11_checkpoint)
    expected_out = _expected_shard_path(shard_index)
    if out.resolve() != expected_out:
        raise RuntimeRefused("shard output differs from reviewed path")
    if out.exists() or Path(str(out) + ".partial").exists():
        raise RuntimeRefused("refusing existing shard output/partial")
    rows = _rows_for_shard(design, packet, shard_index)
    cache = CTRL.ReplayCache(source_root)
    net = _load_npnet(str(v11_checkpoint))
    results = []
    for index, row in enumerate(rows, 1):
        ledger = RowWorkLedger(str(row["surface_type"]))
        try:
            result = (run_play_row(row, cache, net, ledger)
                      if row["surface_type"] == "play"
                      else run_bury_row(row, cache, ledger))
            validate_complete_row(result)
            _validate_complete_ledger(result, ledger)
            ledger.enter("complete")
        except (RuntimeRefused, CTRL.ControllerRefused) as exc:
            result = _refusal(row, exc, ledger)
            validate_complete_row(result)
        results.append(result)
        if progress_every > 0 and (index % progress_every == 0
                                   or index == len(rows)):
            print(json.dumps({
                "status": "RUNNING",
                "shard": shard_index,
                "rows_terminal": index,
                "rows_total": len(rows),
                "complete": sum(item["status"] == "COMPLETE"
                                for item in results),
                "refused": sum(item["status"] == "REFUSED_SCORE_FREE"
                               for item in results),
            }, sort_keys=True), file=sys.stderr, flush=True)
    # Close the source/checkpoint/runtime TOCTOU window before publishing any
    # outcome-bearing bytes. A changed input makes this shard refuse without a
    # final artifact; it never blesses results computed across two identities.
    _validate_current_inputs(
        packet, design_path, corpus, source_root, source_manifest,
        v11_checkpoint)
    _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    payload = {
        "schema": CTRL.SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "execution_receipt_sha256": expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "shard_index": shard_index,
        "row_keys": [item["row_key"] for item in results],
        "rows": results,
        "counts": {
            "terminal": len(results),
            "complete": sum(item["status"] == "COMPLETE" for item in results),
            "refused": sum(item["status"] == "REFUSED_SCORE_FREE"
                           for item in results),
        },
        "candidate_worlds_attempted": sum(
            item.get("work", {}).get("total_candidate_worlds", 0)
            if item["status"] == "COMPLETE" else
            item["attempted_work"]["total_candidate_worlds_attempted"]
            for item in results),
        "candidate_worlds_completed": sum(
            item.get("work", {}).get("total_candidate_worlds", 0)
            if item["status"] == "COMPLETE" else
            item["attempted_work"]["total_candidate_worlds_completed"]
            for item in results),
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["shard_sha256"] = CTRL.sha256_bytes(CTRL.canonical_json(payload))
    CTRL.publish_exclusive(out, payload)
    return payload


def validate_shard(shard: Mapping[str, object], packet: dict,
                   receipt_sha256: str, shard_index: int) -> None:
    expected_schedule = packet["schedule"]["shards"][shard_index]
    fixed = {
        "schema": CTRL.SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": _external_sha(packet),
        "execution_receipt_sha256": receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "shard_index": shard_index,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    for key, expected in fixed.items():
        if shard.get(key) != expected:
            raise RuntimeRefused(f"shard field drift: {key}")
    rows = shard.get("rows")
    if not isinstance(rows, list):
        raise RuntimeRefused("shard rows missing")
    if shard.get("row_keys") != expected_schedule["row_keys"]:
        raise RuntimeRefused("shard row schedule/order drift")
    if [row.get("row_key") for row in rows] != shard.get("row_keys"):
        raise RuntimeRefused("shard row-key payload drift")
    for row in rows:
        validate_complete_row(row)
    counts = {
        "terminal": len(rows),
        "complete": sum(row["status"] == "COMPLETE" for row in rows),
        "refused": sum(row["status"] == "REFUSED_SCORE_FREE" for row in rows),
    }
    if shard.get("counts") != counts:
        raise RuntimeRefused("shard terminal counters drift")
    attempted = sum(
        row.get("work", {}).get("total_candidate_worlds", 0)
        if row["status"] == "COMPLETE" else
        row["attempted_work"]["total_candidate_worlds_attempted"]
        for row in rows)
    completed = sum(
        row.get("work", {}).get("total_candidate_worlds", 0)
        if row["status"] == "COMPLETE" else
        row["attempted_work"]["total_candidate_worlds_completed"]
        for row in rows)
    if (shard.get("candidate_worlds_attempted") != attempted
            or shard.get("candidate_worlds_completed") != completed
            or completed > attempted
            or attempted > expected_schedule["max_candidate_worlds"]):
        raise RuntimeRefused("shard candidate-world accounting drift")
    expected_self = CTRL.sha256_bytes(CTRL.canonical_json({
        key: value for key, value in shard.items() if key != "shard_sha256"
    }))
    if shard.get("shard_sha256") != expected_self:
        raise RuntimeRefused("shard self-hash drift")


def _metric_summary(rows: Sequence[Mapping[str, object]], name: str) -> dict:
    by_deal: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_deal[str(row["deal_key"])].append(float(row["estimands"][name]))
    clusters = [sum(values) / len(values) for _, values in sorted(by_deal.items())]
    mean = sum(clusters) / len(clusters)
    if len(clusters) > 1:
        variance = sum((value - mean) ** 2 for value in clusters) / (
            len(clusters) - 1)
        se = math.sqrt(variance / len(clusters))
    else:
        se = float("inf")
    return {
        "estimand": name,
        "rows": len(rows),
        "deal_clusters": len(clusters),
        "mean": mean,
        "cluster_se": se,
        "two_sided_95_half": 1.96 * se,
        "cluster_values_sha256": CTRL.sha256_bytes(CTRL.canonical_json(clusters)),
    }


def aggregate_payload(packet: dict, receipt_sha256: str,
                      shards: Sequence[dict]) -> dict:
    rows = [row for shard in shards for row in shard["rows"]]
    refusals = [row for row in rows if row["status"] == "REFUSED_SCORE_FREE"]
    base = {
        "schema": CTRL.AGGREGATE_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": _external_sha(packet),
        "execution_receipt_sha256": receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "shards": [{
            "index": shard["shard_index"],
            "sha256": CTRL.sha256_bytes(CTRL.canonical_json(shard)),
            "self_sha256": shard["shard_sha256"],
        } for shard in shards],
        "row_counts": {
            "selected": len(rows),
            "complete": len(rows) - len(refusals),
            "refused": len(refusals),
        },
        "candidate_worlds_attempted": sum(
            row.get("work", {}).get("total_candidate_worlds", 0)
            if row["status"] == "COMPLETE" else
            row["attempted_work"]["total_candidate_worlds_attempted"]
            for row in rows),
        "candidate_worlds_completed": sum(
            row.get("work", {}).get("total_candidate_worlds", 0)
            if row["status"] == "COMPLETE" else
            row["attempted_work"]["total_candidate_worlds_completed"]
            for row in rows),
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    if refusals:
        reasons = Counter(
            ":".join((str(row["split"]), str(row["surface_type"]),
                      str(row["surface"]), str(row["phase"]),
                      str(row["role"]), str(row["reason_class"])))
            for row in refusals)
        payload = {
            **base,
            "status": "REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY",
            "refusal_counts": dict(sorted(reasons.items())),
            "refused_row_keys_sha256": CTRL.sha256_bytes(CTRL.canonical_json(
                sorted(row["row_key"] for row in refusals))),
            "diagnostic_utility_published": False,
        }
    else:
        names = (
            "human_minus_reference_paired_utility",
            "selected_minus_reference_paired_utility",
            "selected_minus_human_paired_utility",
        )
        metrics = {}
        for split in ("DESIGN", "AUDIT"):
            split_rows = [row for row in rows if row["split"] == split]
            metrics[split] = {}
            for surface in ("play", "bury"):
                surface_rows = [row for row in split_rows
                                if row["surface_type"] == surface]
                metrics[split][surface] = {
                    name: _metric_summary(surface_rows, name) for name in names}
        source_counts: dict[str, Counter[str]] = defaultdict(Counter)
        membership_counts: dict[str, Counter[str]] = defaultdict(Counter)
        heterogeneity: dict[str, dict] = {}
        for row in rows:
            cell = ":".join((str(row["split"]), str(row["surface_type"])))
            for source in row["selection"]["winner_sources"]:
                source_counts[cell][source] += 1
            diagnostics = row.get("candidate_diagnostics", {})
            if row["surface_type"] == "play":
                membership_counts[cell]["human_in_production_ballot"] += int(
                    diagnostics.get("human_in_live_ballot") is True)
                membership_counts[cell]["human_outside_production_ballot"] += int(
                    diagnostics.get("human_in_live_ballot") is False)
                membership_counts[cell]["v11_novel_proposal"] += int(
                    diagnostics.get("v11_proposed") is True)
                membership_counts[cell]["random_novel_proposal"] += int(
                    diagnostics.get("random_proposed") is True)
                membership_counts[cell]["empty_novel_pool"] += int(
                    diagnostics.get("novel_pool") == 0)
            else:
                membership_counts[cell]["human_in_structured_ballot"] += int(
                    diagnostics.get("human_in_structured_ballot") is True)
                membership_counts[cell]["human_outside_structured_ballot"] += int(
                    diagnostics.get("human_in_structured_ballot") is False)

        # Heterogeneity is descriptive and kept separate by pseudonymous
        # player, decision surface, phase, and role. It never changes the
        # frozen recipe or becomes a promotion test.
        groups: dict[tuple, list[Mapping[str, object]]] = defaultdict(list)
        for row in rows:
            groups[(row["split"], row["player_id"], row["surface_type"],
                    row["surface"], row["phase"], row["role"])].append(row)
        for group, group_rows in sorted(groups.items()):
            key = ":".join(map(str, group))
            heterogeneity[key] = {
                "rows": len(group_rows),
                "deal_clusters": len({row["deal_key"] for row in group_rows}),
                "mean_estimands": {
                    name: sum(float(row["estimands"][name])
                              for row in group_rows) / len(group_rows)
                    for name in names
                },
            }
        payload = {
            **base,
            "status": "PUBLISH_DIAGNOSTIC_ONLY",
            "metrics": metrics,
            "selected_winner_source_counts": {
                cell: dict(sorted(counts.items()))
                for cell, counts in sorted(source_counts.items())
            },
            "proposal_membership_counts": {
                cell: dict(sorted(counts.items()))
                for cell, counts in sorted(membership_counts.items())
            },
            "heterogeneity": heterogeneity,
            "diagnostic_utility_published": True,
            "formal_strength_conclusion": None,
        }
    payload["aggregate_sha256"] = CTRL.sha256_bytes(
        CTRL.canonical_json(payload))
    return payload


def aggregate(*, packet_path: Path, expected_packet_sha256: str,
              receipt_path: Path, expected_receipt_sha256: str,
              shard_paths: Sequence[Path], out: Path) -> dict:
    packet = _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    if len(shard_paths) != CTRL.SHARD_COUNT:
        raise RuntimeRefused("aggregate requires every reviewed shard")
    expected_out = _expected_aggregate_path()
    if out.resolve() != expected_out:
        raise RuntimeRefused("aggregate output differs from reviewed path")
    shards = []
    for index, path in enumerate(shard_paths):
        if path.resolve() != _expected_shard_path(index):
            raise RuntimeRefused(f"shard {index} differs from reviewed path")
        if not _is_terminal_file(path):
            raise RuntimeRefused(f"shard {index} is not regular/unlinked")
        shard = _load_json(path)
        validate_shard(shard, packet, expected_receipt_sha256, index)
        shards.append(shard)
    payload = aggregate_payload(packet, expected_receipt_sha256, shards)
    # Reopen immutable identities immediately before the one exclusive
    # publication. This refuses a shard/receipt/controller mutation that lands
    # between initial validation and aggregate write.
    _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    for shard, path in zip(shards, shard_paths, strict=True):
        if CTRL.sha256_file(path) != CTRL.sha256_bytes(
                CTRL.canonical_json(shard)):
            raise RuntimeRefused("shard changed during aggregation")
    CTRL.publish_exclusive(out, payload)
    return payload


def verify_result(*, packet_path: Path, expected_packet_sha256: str,
                  receipt_path: Path, expected_receipt_sha256: str,
                  design_path: Path, corpus: Path, source_root: Path,
                  source_manifest: Path, v11_checkpoint: Path,
                  shard_paths: Sequence[Path], aggregate_path: Path,
                  replay_every_row: bool) -> dict:
    if not replay_every_row:
        raise RuntimeRefused("terminal verification requires --replay-every-row")
    packet = _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    design = _validate_current_inputs(
        packet, design_path, corpus, source_root, source_manifest,
        v11_checkpoint)
    if len(shard_paths) != CTRL.SHARD_COUNT:
        raise RuntimeRefused("terminal verifier requires every shard")
    shards = []
    for index, path in enumerate(shard_paths):
        if path.resolve() != _expected_shard_path(index):
            raise RuntimeRefused(f"terminal shard {index} path drift")
        if not _is_terminal_file(path):
            raise RuntimeRefused(f"terminal shard {index} is not regular/unlinked")
        shard = _load_json(path)
        validate_shard(shard, packet, expected_receipt_sha256, index)
        shards.append(shard)
    expected = aggregate_payload(packet, expected_receipt_sha256, shards)
    if (aggregate_path.resolve() != _expected_aggregate_path()
            or not _is_terminal_file(aggregate_path)):
        raise RuntimeRefused("terminal aggregate path/type drift")
    actual = _load_json(aggregate_path)
    if actual != expected:
        raise RuntimeRefused("terminal aggregate full recomputation drift")
    if actual.get("aggregate_sha256") != CTRL.sha256_bytes(
            CTRL.canonical_json({key: value for key, value in actual.items()
                                 if key != "aggregate_sha256"})):
        raise RuntimeRefused("terminal aggregate self-hash drift")
    cache = CTRL.ReplayCache(source_root)
    net = _load_npnet(str(v11_checkpoint))
    stored = {row["row_key"]: row for shard in shards
              for row in shard["rows"]}
    selected = CTRL.selected_rows(design)
    if len(stored) != len(selected):
        raise RuntimeRefused("terminal stored-row population drift")
    replayed_count = refused_count = 0
    for index, row in enumerate(selected, 1):
        key = CTRL.row_key(
            row["split"], row["surface_type"], row["replay_key"])
        stored_row = stored.get(key)
        expected_identity = {
            "split": row["split"],
            "surface_type": row["surface_type"],
            "replay_key": row["replay_key"],
            "deal_key": row["deal_key"],
            "player_id": row["player_id"],
            "surface": row.get("surface", "bury"),
            "phase": row.get("phase", "pre-play"),
            "role": row.get("role", "defender"),
        }
        if (stored_row is None
                or any(stored_row.get(name) != value
                       for name, value in expected_identity.items())):
            raise RuntimeRefused(f"terminal row identity drift: {key}")
        if stored_row["status"] == "REFUSED_SCORE_FREE":
            refused_count += 1
        else:
            ledger = RowWorkLedger(str(row["surface_type"]))
            replayed = (run_play_row(row, cache, net, ledger)
                        if row["surface_type"] == "play"
                        else run_bury_row(row, cache, ledger))
            validate_complete_row(replayed)
            _validate_complete_ledger(replayed, ledger)
            if replayed != stored_row:
                raise RuntimeRefused(f"terminal row replay drift: {key}")
            replayed_count += 1
        print(json.dumps({
            "status": "VERIFYING",
            "rows_checked": index,
            "rows_total": len(stored),
            "complete_rows_replayed": replayed_count,
            "refused_rows_not_retried": refused_count,
        }, sort_keys=True), file=sys.stderr, flush=True)
    _validate_current_inputs(
        packet, design_path, corpus, source_root, source_manifest,
        v11_checkpoint)
    _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    for shard, path in zip(shards, shard_paths, strict=True):
        if CTRL.sha256_file(path) != CTRL.sha256_bytes(
                CTRL.canonical_json(shard)):
            raise RuntimeRefused("terminal shard changed during replay")
    if CTRL.sha256_file(aggregate_path) != CTRL.sha256_bytes(
            CTRL.canonical_json(actual)):
        raise RuntimeRefused("terminal aggregate changed during replay")
    return {
        "status": ("VERIFIED_COUNTERFACTUAL_DIAGNOSTIC"
                   if not refused_count else
                   "VERIFIED_REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY"),
        "aggregate_sha256": CTRL.sha256_file(aggregate_path),
        "rows": actual["row_counts"],
        "complete_rows_replayed": replayed_count,
        "refused_rows_not_retried": refused_count,
        "replay_every_row": True,
        "strength_claim": False,
        "production_promotion": False,
    }


def _identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--controller-packet", required=True)
    parser.add_argument("--expected-controller-packet-sha256", required=True)


def _receipt_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--execution-receipt", required=True)
    parser.add_argument("--expected-execution-receipt-sha256", required=True)


def _input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--design-packet", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--v11-checkpoint", required=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    admit_parser = commands.add_parser("admit")
    _identity_args(admit_parser)
    _input_args(admit_parser)
    admit_parser.add_argument("--review-record", required=True)
    admit_parser.add_argument("--namespace", required=True)
    admit_parser.add_argument("--out", required=True)

    shard_parser = commands.add_parser("run-shard")
    _identity_args(shard_parser)
    _receipt_args(shard_parser)
    _input_args(shard_parser)
    shard_parser.add_argument("--shard-index", required=True, type=int)
    shard_parser.add_argument("--progress-every", type=int, default=1)
    shard_parser.add_argument("--out", required=True)

    aggregate_parser = commands.add_parser("aggregate")
    _identity_args(aggregate_parser)
    _receipt_args(aggregate_parser)
    aggregate_parser.add_argument("--shards", nargs="+", required=True)
    aggregate_parser.add_argument("--out", required=True)

    verify_parser = commands.add_parser("verify-result")
    _identity_args(verify_parser)
    _receipt_args(verify_parser)
    _input_args(verify_parser)
    verify_parser.add_argument("--shards", nargs="+", required=True)
    verify_parser.add_argument("--aggregate", required=True)
    verify_parser.add_argument("--replay-every-row", action="store_true")
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if _git("rev-parse", "HEAD") != args.expected_git:
        raise RuntimeRefused("runtime Git differs from expected Git")
    common = {
        "packet_path": Path(args.controller_packet),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
    }
    if args.command == "admit":
        value = admit(
            **common, review_record=Path(args.review_record),
            receipt_path=Path(args.out), namespace=Path(args.namespace),
            design_path=Path(args.design_packet), corpus=Path(args.corpus),
            source_root=Path(args.source_root),
            source_manifest=Path(args.source_manifest),
            v11_checkpoint=Path(args.v11_checkpoint),
        )
    elif args.command == "run-shard":
        value = run_shard(
            **common, receipt_path=Path(args.execution_receipt),
            expected_receipt_sha256=args.expected_execution_receipt_sha256,
            design_path=Path(args.design_packet), corpus=Path(args.corpus),
            source_root=Path(args.source_root),
            source_manifest=Path(args.source_manifest),
            v11_checkpoint=Path(args.v11_checkpoint),
            shard_index=args.shard_index, out=Path(args.out),
            progress_every=args.progress_every,
        )
    elif args.command == "aggregate":
        value = aggregate(
            **common, receipt_path=Path(args.execution_receipt),
            expected_receipt_sha256=args.expected_execution_receipt_sha256,
            shard_paths=[Path(path) for path in args.shards],
            out=Path(args.out),
        )
    else:
        value = verify_result(
            **common, receipt_path=Path(args.execution_receipt),
            expected_receipt_sha256=args.expected_execution_receipt_sha256,
            design_path=Path(args.design_packet), corpus=Path(args.corpus),
            source_root=Path(args.source_root),
            source_manifest=Path(args.source_manifest),
            v11_checkpoint=Path(args.v11_checkpoint),
            shard_paths=[Path(path) for path in args.shards],
            aggregate_path=Path(args.aggregate),
            replay_every_row=args.replay_every_row,
        )
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except RuntimeRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
