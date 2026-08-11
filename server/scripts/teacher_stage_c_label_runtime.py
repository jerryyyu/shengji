#!/usr/bin/env python3
"""Finite-work labeling primitives for Teacher Stage C.

This module is deliberately not an execution controller.  It implements the
outcome-producing core that a later, dataset-bound and independently reviewed
controller may call.  Importing it, running its tests, or compiling it samples
no worlds and publishes no labels.

The important boundaries are executable here:

* every fold has a domain-separated deterministic iid stream;
* rejected sampler draws consume attempts until a finite reviewed cap;
* all candidates in a fold share the same accepted worlds;
* successful draws are retained with replacement, preserving posterior mass
  even when the hidden-world support is small;
* selection and report use independent streams; an underlying world may recur
  naturally within or across folds without coupling their RNG draws;
* hard-tail report folds evaluate two *logical* slots (candidate zero and the
  frozen selection winner), even when both slots name candidate zero;
* audit report folds evaluate three logical slots (candidate zero, the frozen
  audit-selection winner, and the frozen label choice) on 400 common worlds;
  this preserves the reviewed 1,200 candidate-world budget that the broken
  two-action/600-world geometry could not use to answer both estimands;
* the report fold never reselects; and
* raw attacker points and acting-team signed level utilities are retained for
  every action/world cell.

The 3x400 audit geometry is a narrow successor label-contract amendment.  It
must be externally reviewed before any audit outcome is sampled; this module
alone authorizes no labels or audit work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.pilot_folds import world_key
from shengji.rl.bc_generate import round_value


SCHEMA = "teacher-stage-c-label-row-v2"
SAMPLER_SCHEMA = "teacher-stage-c-label-sampler-v2"
FOLD_SCHEMA = "teacher-stage-c-label-fold-v2"
WORK_SCHEMA = "teacher-stage-c-label-work-v2"
STREAM_SCHEMA = "teacher-stage-c-label-stream-v2"

ORDINARY_SELECTION_WORLDS = 256
ORDINARY_REPORT_WORLDS = 256
HARD_SELECTION_WORLDS = 64
HARD_REPORT_WORLDS = 300
AUDIT_SELECTION_WORLDS = 128
AUDIT_REPORT_WORLDS = 400
AUDIT_REPORT_ACTIONS = 3
AUDIT_REPORT_CANDIDATE_WORLDS = 1_200
SAMPLE_ATTEMPT_FACTOR = 40
PLAY_CANDIDATE_CAP = 20
BURY_CANDIDATE_CAP = 33

# One-sided 95% Student-t criticals.  These are fixed-look, fixed-pair bounds:
# selection and report use domain-separated iid streams, so the report contrast
# is not winner-picked on the same random draws.  Repeated underlying worlds
# remain valid iid samples and preserve their posterior mass.  These are not
# simultaneous intervals over states.
HARD_T_95_DF299 = 1.649966
AUDIT_T_95_DF399 = 1.648682

SAMPLER_COUNTERS = (
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds",
)
FOLDS = ("selection", "report", "audit_selection", "audit_report")


class LabelRefused(RuntimeError):
    """A Stage-C label row cannot satisfy its reviewed finite-work contract."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def action_key(action: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(str(card) for card in action))


def seed_for(state: Mapping[str, object], purpose: str) -> int:
    """Derive a stable stream without consuming another fold's RNG state."""
    if purpose not in FOLDS:
        raise LabelRefused(f"unknown Stage-C fold purpose: {purpose}")
    identity = [
        STREAM_SCHEMA, state.get("split"), state.get("state_id"),
        state.get("surface_type"), purpose,
    ]
    return int.from_bytes(hashlib.sha256(canonical_json(identity)).digest()[:16],
                          "big")


def acting_utility(attacker_points: float, *, attacker: bool) -> float:
    points = float(attacker_points)
    if not math.isfinite(points) or points < 0 or not points.is_integer():
        raise LabelRefused("rollout produced non-integral/negative attacker points")
    value = float(round_value(int(points)))
    return value if attacker else -value


def _sampler_snapshot(bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) for name in SAMPLER_COUNTERS}


def _sampler_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    return {name: int(after[name]) - int(before[name]) for name in before}


def _world_hash(hands, buried) -> str:
    key = world_key(hands, buried)
    public = [
        [[seat, list(cards)] for seat, cards in key[0]],
        list(key[1]),
    ]
    return sha256_bytes(canonical_json(public))


@dataclass
class WorkLedger:
    """Exact candidate-world accounting that survives an expected refusal."""

    attempted: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in FOLDS})
    completed: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in FOLDS})
    samplers: dict[str, dict] = field(default_factory=dict)
    sampler_sequence: list[str] = field(default_factory=list)
    world_hashes_by_fold: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def prior_world_hashes(self) -> set[str]:
        return {value for values in self.world_hashes_by_fold.values()
                for value in values}

    def record_sampler(self, fold: str, sampler: Mapping[str, object]) -> None:
        if fold not in FOLDS or fold in self.samplers:
            raise LabelRefused("duplicate or unknown label sampler fold")
        hashes = sampler.get("world_key_sha256s")
        if not isinstance(hashes, list):
            raise LabelRefused("label sampler world identities are missing")
        prior = self.prior_world_hashes()
        duplicate_draws = len(hashes) - len(set(hashes))
        prior_overlaps = sum(value in prior for value in hashes)
        if (sampler.get("accepted") != len(hashes)
                or sampler.get("unique_worlds") != len(set(hashes))
                or sampler.get("duplicate_draws_retained") != duplicate_draws
                or sampler.get("prior_fold_overlap_draws_retained")
                != prior_overlaps
                or sampler.get("sampling_with_replacement") is not True
                or sampler.get("domain_separated_stream") is not True):
            raise LabelRefused("label sampler iid stream telemetry drift")
        self.samplers[fold] = dict(sampler)
        self.sampler_sequence.append(fold)
        self.world_hashes_by_fold[fold] = tuple(str(value) for value in hashes)

    def begin_candidate_world(self, fold: str) -> None:
        if fold not in FOLDS:
            raise LabelRefused("unknown label work fold")
        self.attempted[fold] += 1

    def finish_candidate_world(self, fold: str) -> None:
        if self.completed[fold] >= self.attempted[fold]:
            raise LabelRefused("candidate-world completion precedes attempt")
        self.completed[fold] += 1

    def snapshot(self) -> dict:
        return {
            "schema": WORK_SCHEMA,
            "candidate_worlds_attempted": dict(self.attempted),
            "candidate_worlds_completed": dict(self.completed),
            "total_candidate_worlds_attempted": sum(self.attempted.values()),
            "total_candidate_worlds_completed": sum(self.completed.values()),
            "samplers": dict(sorted(self.samplers.items())),
            "sampler_sequence": list(self.sampler_sequence),
            "accounting_complete": self.attempted == self.completed,
        }


def make_label_bot(seed: int):
    """Construct the frozen non-recursive HeuristicBot continuation."""
    bot = make_bot("mc-s0-report-lcb", seed=seed)
    if (type(bot.rollout_policy) is not HeuristicBot
            or bool(getattr(bot, "EXACT_ENDGAME", False))
            or int(getattr(bot, "SAMPLE_ATTEMPT_FACTOR", -1))
            != SAMPLE_ATTEMPT_FACTOR):
        raise LabelRefused("Stage-C production continuation/sampler drift")
    return bot


def draw_common_worlds(rnd, seat: int, count: int, seed: int, *,
                       fold: str, ledger: WorkLedger,
                       bot_factory: Callable[[int], object] = make_label_bot
                       ) -> tuple[object, list[tuple], dict]:
    if fold not in FOLDS or count <= 0:
        raise LabelRefused("invalid Stage-C sampler fold/count")
    bot = bot_factory(seed)
    factor = int(getattr(bot, "SAMPLE_ATTEMPT_FACTOR", SAMPLE_ATTEMPT_FACTOR))
    if factor != SAMPLE_ATTEMPT_FACTOR:
        raise LabelRefused("Stage-C sampler attempt factor drift")
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    before = _sampler_snapshot(bot)
    worlds: list[tuple] = []
    world_hashes: list[str] = []
    seen: set[str] = set()
    prior = ledger.prior_world_hashes()
    prior_overlap_draws = 0
    duplicate_draws = 0
    attempts = 0
    cap = count * factor
    while len(worlds) < count and attempts < cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is not None:
            digest = _world_hash(*sampled)
            if digest in seen:
                duplicate_draws += 1
            if digest in prior:
                prior_overlap_draws += 1
            seen.add(digest)
            worlds.append(sampled)
            world_hashes.append(digest)
    delta = _sampler_delta(before, _sampler_snapshot(bot))
    sampler = {
        "schema": SAMPLER_SCHEMA,
        "fold": fold,
        "seed": seed,
        "requested": count,
        "accepted": len(worlds),
        "accepted_draws": delta["accepted_worlds"],
        "attempts": attempts,
        "attempt_cap": cap,
        "counters": delta,
        "world_key_sha256s": world_hashes,
        "world_keys_sha256": sha256_bytes(canonical_json(world_hashes)),
        "unique_worlds": len(seen),
        "duplicate_draws_retained": duplicate_draws,
        "prior_fold_overlap_draws_retained": prior_overlap_draws,
        "sampling_with_replacement": True,
        "domain_separated_stream": True,
        "complete": len(worlds) == count,
    }
    ledger.record_sampler(fold, sampler)
    if (delta["sample_attempts"] != attempts
            or delta["accepted_worlds"] != len(worlds)
            or delta["sample_attempts"] !=
            delta["accepted_worlds"] + delta["failed_worlds"]
            or delta["rejected_worlds"] > delta["failed_worlds"]
            or len(worlds) != count):
        raise LabelRefused("Stage-C strict sampler underfilled or counters diverged")
    return bot, worlds, sampler


def score_actions(bot, rnd, state: Mapping[str, object], worlds: Sequence[tuple],
                  candidate_indices: Sequence[int], *, fold: str,
                  ledger: WorkLedger) -> dict:
    """Score logical action slots; duplicate indices intentionally cost work."""
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LabelRefused("Stage-C state has no candidate tensor")
    surface = state.get("surface_type")
    if surface not in {"play", "bury"}:
        raise LabelRefused("Stage-C state surface is not play/bury")
    seat = int(state["seat"])
    attacker = bool(rnd.is_attacker(seat))
    actions = []
    for logical_index, candidate_index in enumerate(candidate_indices):
        if (isinstance(candidate_index, bool)
                or not isinstance(candidate_index, int)
                or not 0 <= candidate_index < len(candidates)):
            raise LabelRefused("Stage-C fold candidate index outside tensor")
        candidate = candidates[candidate_index]
        cards = list(candidate["cards"])
        raw: list[float] = []
        utilities: list[float] = []
        for hands, buried in worlds:
            ledger.begin_candidate_world(fold)
            if surface == "bury":
                points = bot._rollout_from_bury(rnd, seat, hands, cards)
            else:
                points = bot._rollout(rnd, seat, hands, buried, cards)
            utility = acting_utility(float(points), attacker=attacker)
            ledger.finish_candidate_world(fold)
            raw.append(float(points))
            utilities.append(utility)
        if len(raw) != len(worlds):
            raise LabelRefused("Stage-C action tensor is underfilled")
        actions.append({
            "logical_index": logical_index,
            "candidate_index": candidate_index,
            "cards": list(action_key(cards)),
            "sources": sorted(str(value) for value in candidate.get("sources", [])),
            "raw_attacker_points": raw,
            "signed_level_utility": utilities,
            "mean_signed_level_utility": sum(utilities) / len(utilities),
        })
    return {
        "schema": FOLD_SCHEMA,
        "fold": fold,
        "worlds": len(worlds),
        "candidate_indices": list(candidate_indices),
        "tensor_orientation": "logical_action_by_common_world",
        "actions": actions,
        "candidate_worlds": len(candidate_indices) * len(worlds),
        "complete": True,
    }


def _validate_domain_separated_streams(
        samplers: Sequence[Mapping[str, object]]) -> None:
    """Authenticate independent RNG streams without forbidding iid repeats."""
    seeds: list[int] = []
    prior: set[str] = set()
    for sampler in samplers:
        hashes = sampler.get("world_key_sha256s")
        seed = sampler.get("seed")
        if (not isinstance(hashes, list)
                or isinstance(seed, bool) or not isinstance(seed, int)
                or sampler.get("domain_separated_stream") is not True
                or sampler.get("sampling_with_replacement") is not True
                or sampler.get("unique_worlds") != len(set(hashes))
                or sampler.get("duplicate_draws_retained")
                != len(hashes) - len(set(hashes))
                or sampler.get("prior_fold_overlap_draws_retained")
                != sum(value in prior for value in hashes)):
            raise LabelRefused("Stage-C iid stream separation drift")
        seeds.append(seed)
        prior.update(str(value) for value in hashes)
    if len(set(seeds)) != len(seeds):
        raise LabelRefused("Stage-C label folds reused an RNG stream")


def run_fold(rnd, state: Mapping[str, object], candidate_indices: Sequence[int],
             count: int, purpose: str, ledger: WorkLedger) -> dict:
    seed = seed_for(state, purpose)
    bot, worlds, sampler = draw_common_worlds(
        rnd, int(state["seat"]), count, seed, fold=purpose, ledger=ledger)
    scored = score_actions(
        bot, rnd, state, worlds, candidate_indices, fold=purpose, ledger=ledger)
    return {"seed": seed, "sampler": sampler, **scored}


def selection_winner(fold: Mapping[str, object], candidate_count: int) -> int:
    actions = fold.get("actions")
    if (not isinstance(actions, list) or len(actions) != candidate_count
            or fold.get("candidate_indices") != list(range(candidate_count))):
        raise LabelRefused("selection fold is not the full candidate tensor")
    means = [float(action["mean_signed_level_utility"]) for action in actions]
    if not means or not all(math.isfinite(value) for value in means):
        raise LabelRefused("selection means are missing/non-finite")
    # Python's max keeps the first index on ties: the reviewed low-index rule.
    return max(range(candidate_count), key=lambda index: means[index])


def paired_summary(left: Sequence[float], right: Sequence[float], *,
                   critical: float) -> dict:
    if (len(left) != len(right) or len(left) < 2
            or not math.isfinite(float(critical)) or critical <= 0):
        raise LabelRefused("invalid fixed-pair report contrast")
    diffs = [float(a) - float(b) for a, b in zip(left, right, strict=True)]
    if not all(math.isfinite(value) for value in diffs):
        raise LabelRefused("non-finite paired report utility")
    mean = sum(diffs) / len(diffs)
    variance = sum((value - mean) ** 2 for value in diffs) / (len(diffs) - 1)
    se = math.sqrt(max(0.0, variance) / len(diffs))
    return {
        "n": len(diffs),
        "mean": mean,
        "sample_variance": variance,
        "se": se,
        "critical": float(critical),
        "one_sided_95_lcb": mean - float(critical) * se,
        "one_sided_95_ucb": mean + float(critical) * se,
        "family": ("per-state fixed-pair Student-t; independent iid "
                   "selection/report streams with replacement"),
    }


def _report_contrast(report: Mapping[str, object], *, critical: float) -> dict:
    actions = report.get("actions")
    if not isinstance(actions, list) or len(actions) != 2:
        raise LabelRefused("hard-tail report must contain two logical actions")
    return paired_summary(
        actions[1]["signed_level_utility"],
        actions[0]["signed_level_utility"], critical=critical)


def recipe_for_state(state: Mapping[str, object]) -> str:
    return "ordinary_anchor" if state.get("stratum") == "ordinary_anchor" \
        else "hard_tail"


FoldRunner = Callable[[object, Mapping[str, object], Sequence[int], int, str,
                       WorkLedger], dict]


def label_replayed_state(state: Mapping[str, object], rnd, *,
                         include_audit: bool = False,
                         fold_runner: FoldRunner = run_fold,
                         ledger: WorkLedger | None = None) -> dict:
    """Produce one complete label row from a replayed, candidate-verified state."""
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LabelRefused("Stage-C label state lacks candidates")
    cap = PLAY_CANDIDATE_CAP if state.get("surface_type") == "play" \
        else BURY_CANDIDATE_CAP
    if len(candidates) > cap:
        raise LabelRefused("Stage-C label candidate cap exceeded")
    ledger = ledger or WorkLedger()
    all_indices = list(range(len(candidates)))
    recipe = recipe_for_state(state)
    if recipe == "ordinary_anchor":
        selection = fold_runner(
            rnd, state, all_indices, ORDINARY_SELECTION_WORLDS,
            "selection", ledger)
        winner = selection_winner(selection, len(candidates))
        report = fold_runner(
            rnd, state, all_indices, ORDINARY_REPORT_WORLDS,
            "report", ledger)
        final_index = winner
        decision = {
            "selection_winner_index": winner,
            "final_index": final_index,
            "reason": "ordinary_fixed_selection_argmax",
            "report_never_selected": True,
            "report_lcb_vs_candidate0": None,
        }
    else:
        selection = fold_runner(
            rnd, state, all_indices, HARD_SELECTION_WORLDS,
            "selection", ledger)
        winner = selection_winner(selection, len(candidates))
        # Two logical slots are mandatory under the frozen max-work arithmetic.
        report = fold_runner(
            rnd, state, [0, winner], HARD_REPORT_WORLDS,
            "report", ledger)
        contrast = _report_contrast(report, critical=HARD_T_95_DF299)
        final_index = winner if contrast["one_sided_95_lcb"] > 0 else 0
        decision = {
            "selection_winner_index": winner,
            "final_index": final_index,
            "reason": ("hard_tail_report_lcb_override" if final_index != 0
                       else "hard_tail_report_lcb_fallback"),
            "report_never_selected": True,
            "report_lcb_vs_candidate0": contrast,
        }
    expected_label = (len(candidates) *
                (ORDINARY_SELECTION_WORLDS + ORDINARY_REPORT_WORLDS)
                if recipe == "ordinary_anchor" else
                len(candidates) * HARD_SELECTION_WORLDS
                + 2 * HARD_REPORT_WORLDS)
    audit = None
    if include_audit:
        audit_selection = fold_runner(
            rnd, state, all_indices, AUDIT_SELECTION_WORLDS,
            "audit_selection", ledger)
        audit_winner = selection_winner(audit_selection, len(candidates))
        plan = audit_report_plan(audit_winner, final_index)
        audit_report = fold_runner(
            rnd, state, plan["candidate_indices"], plan["worlds"],
            "audit_report", ledger)
        audit = {
            "selection": audit_selection,
            "report": audit_report,
            "decision": audit_report_summary(
                audit_report,
                audit_selection_winner=audit_winner,
                frozen_label_choice=final_index,
            ),
            "independent_stream_from_label": True,
        }
    work = ledger.snapshot()
    expected = expected_label + (
        len(candidates) * AUDIT_SELECTION_WORLDS
        + AUDIT_REPORT_CANDIDATE_WORLDS if include_audit else 0)
    if (work["total_candidate_worlds_attempted"] != expected
            or work["total_candidate_worlds_completed"] != expected):
        raise LabelRefused("Stage-C label candidate-world work drift")
    used_folds = [selection, report]
    if audit is not None:
        used_folds.extend([audit["selection"], audit["report"]])
    _validate_domain_separated_streams(
        [fold["sampler"] for fold in used_folds])
    final = candidates[final_index]
    row = {
        "schema": SCHEMA,
        "status": "COMPLETE",
        "state_id": state["state_id"],
        "split": state["split"],
        "surface_type": state["surface_type"],
        "stratum": state["stratum"],
        "candidate_count": len(candidates),
        "candidate_tensor_sha256": sha256_bytes(canonical_json(candidates)),
        "recipe": recipe,
        "selection": selection,
        "report": report,
        "audit": audit,
        "decision": decision,
        "label_action": {
            "index": final_index,
            "cards": list(action_key(final["cards"])),
            "sources": sorted(str(value) for value in final.get("sources", [])),
        },
        "work": work,
        "raw_action_tensor_preserved": True,
        "recursive_mc_continuation_rollouts": 0,
        "complete": True,
    }
    row["row_sha256"] = sha256_bytes(canonical_json(row))
    return row


def label_state(state: Mapping[str, object], *, net=None,
                include_audit: bool = False,
                fold_runner: FoldRunner = run_fold,
                ledger: WorkLedger | None = None) -> dict:
    """Replay and revalidate a captured state before producing its label."""
    rnd = CAPTURE.replay_state(state)
    if net is None:
        raise LabelRefused("candidate replay requires the frozen V11 network")
    CAPTURE._validate_candidates(state, rnd, net)
    return label_replayed_state(
        state, rnd, include_audit=include_audit,
        fold_runner=fold_runner, ledger=ledger)


def audit_report_plan(audit_selection_winner: int,
                      frozen_label_choice: int) -> dict:
    """Name the report actions needed for both audit decisions.

    Candidate zero is needed to apply the audit winner's LCB.  The frozen
    label choice is needed to measure regret on the same audit worlds.  Keep
    all three as logical slots even when identities coincide: 3 actions x 400
    worlds preserves the original 2 actions x 600-world candidate-work ceiling
    while making the previously-unidentified three-action case executable.
    """
    for value in (audit_selection_winner, frozen_label_choice):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LabelRefused("audit action index is not a nonnegative integer")
    required = [0, audit_selection_winner, frozen_label_choice]
    return {
        "candidate_indices": required,
        "worlds": AUDIT_REPORT_WORLDS,
        "candidate_worlds": AUDIT_REPORT_ACTIONS * AUDIT_REPORT_WORLDS,
        "slot_roles": [
            "candidate0", "audit_selection_winner", "frozen_label_choice"],
        "can_certify_winner_and_measure_regret": True,
    }


def audit_report_summary(report: Mapping[str, object], *,
                         audit_selection_winner: int,
                         frozen_label_choice: int) -> dict:
    """Resolve the fixed audit reference and its regret on common worlds."""
    plan = audit_report_plan(audit_selection_winner, frozen_label_choice)
    actions = report.get("actions")
    if (not isinstance(actions, list) or len(actions) != AUDIT_REPORT_ACTIONS
            or report.get("candidate_indices") != plan["candidate_indices"]
            or report.get("worlds") != AUDIT_REPORT_WORLDS
            or report.get("candidate_worlds")
            != AUDIT_REPORT_CANDIDATE_WORLDS):
        raise LabelRefused("audit report does not match fixed 3x400 geometry")
    winner_vs_incumbent = paired_summary(
        actions[1]["signed_level_utility"],
        actions[0]["signed_level_utility"], critical=AUDIT_T_95_DF399)
    audit_slot = 1 if winner_vs_incumbent["one_sided_95_lcb"] > 0 else 0
    audit_index = plan["candidate_indices"][audit_slot]
    regret_vs_label = paired_summary(
        actions[audit_slot]["signed_level_utility"],
        actions[2]["signed_level_utility"], critical=AUDIT_T_95_DF399)
    return {
        "audit_selection_winner_index": audit_selection_winner,
        "frozen_label_choice_index": frozen_label_choice,
        "audit_reference_index": audit_index,
        "audit_reference_reason": (
            "audit_report_lcb_override" if audit_slot == 1
            else "audit_report_lcb_fallback_to_candidate0"),
        "winner_vs_candidate0": winner_vs_incumbent,
        "audit_reference_minus_label_choice": regret_vs_label,
        "report_never_reselected": True,
        "candidate_worlds": AUDIT_REPORT_CANDIDATE_WORLDS,
    }


def _validate_sampler(sampler: Mapping[str, object], *, state: Mapping[str, object],
                      fold: str, requested: int) -> None:
    counters = sampler.get("counters")
    hashes = sampler.get("world_key_sha256s")
    unique_worlds = sampler.get("unique_worlds")
    duplicate_draws = sampler.get("duplicate_draws_retained")
    prior_overlaps = sampler.get("prior_fold_overlap_draws_retained")
    if (sampler.get("schema") != SAMPLER_SCHEMA
            or sampler.get("fold") != fold
            or sampler.get("seed") != seed_for(state, fold)
            or sampler.get("requested") != requested
            or sampler.get("accepted") != requested
            or not isinstance(sampler.get("attempts"), int)
            or isinstance(sampler.get("attempts"), bool)
            or not requested <= sampler["attempts"] <=
            requested * SAMPLE_ATTEMPT_FACTOR
            or sampler.get("attempt_cap") != requested * SAMPLE_ATTEMPT_FACTOR
            or not isinstance(counters, dict)
            or set(counters) != set(SAMPLER_COUNTERS)
            or not all(isinstance(value, int) and not isinstance(value, bool)
                       and value >= 0 for value in counters.values())
            or counters["sample_attempts"] != sampler["attempts"]
            or sampler.get("accepted_draws") != counters["accepted_worlds"]
            or counters["accepted_worlds"] != requested
            or counters["accepted_worlds"] + counters["failed_worlds"]
            != counters["sample_attempts"]
            or counters["rejected_worlds"] > counters["failed_worlds"]
            or not isinstance(sampler.get("world_keys_sha256"), str)
            or len(sampler["world_keys_sha256"]) != 64
            or any(char not in "0123456789abcdef"
                   for char in sampler["world_keys_sha256"])
            or not isinstance(hashes, list) or len(hashes) != requested
            or not all(isinstance(value, str) and len(value) == 64
                       and not any(char not in "0123456789abcdef"
                                   for char in value) for value in hashes)
            or isinstance(unique_worlds, bool)
            or not isinstance(unique_worlds, int)
            or unique_worlds != len(set(hashes))
            or isinstance(duplicate_draws, bool)
            or not isinstance(duplicate_draws, int)
            or duplicate_draws != requested - unique_worlds
            or isinstance(prior_overlaps, bool)
            or not isinstance(prior_overlaps, int)
            or not 0 <= prior_overlaps <= requested
            or sampler["world_keys_sha256"]
            != sha256_bytes(canonical_json(hashes))
            or sampler.get("sampling_with_replacement") is not True
            or sampler.get("domain_separated_stream") is not True
            or sampler.get("complete") is not True):
        raise LabelRefused(f"Stage-C {fold} sampler semantic drift")


def _validate_fold(fold_value: Mapping[str, object], *,
                   state: Mapping[str, object], rnd,
                   fold: str, requested: int,
                   candidate_indices: Sequence[int]) -> None:
    candidates = state["candidates"]
    actions = fold_value.get("actions")
    sampler = fold_value.get("sampler")
    if not isinstance(sampler, dict):
        raise LabelRefused(f"Stage-C {fold} sampler missing")
    _validate_sampler(sampler, state=state, fold=fold, requested=requested)
    if (fold_value.get("schema") != FOLD_SCHEMA
            or fold_value.get("fold") != fold
            or fold_value.get("seed") != seed_for(state, fold)
            or fold_value.get("worlds") != requested
            or fold_value.get("candidate_indices") != list(candidate_indices)
            or fold_value.get("tensor_orientation")
            != "logical_action_by_common_world"
            or not isinstance(actions, list)
            or len(actions) != len(candidate_indices)
            or fold_value.get("candidate_worlds")
            != len(candidate_indices) * requested
            or fold_value.get("complete") is not True):
        raise LabelRefused(f"Stage-C {fold} tensor geometry drift")
    attacker = bool(rnd.is_attacker(int(state["seat"])))
    for logical, (action, candidate_index) in enumerate(zip(
            actions, candidate_indices, strict=True)):
        candidate = candidates[candidate_index]
        raw = action.get("raw_attacker_points")
        utility = action.get("signed_level_utility")
        if (action.get("logical_index") != logical
                or action.get("candidate_index") != candidate_index
                or action.get("cards") != list(action_key(candidate["cards"]))
                or action.get("sources") != sorted(
                    str(value) for value in candidate.get("sources", []))
                or not isinstance(raw, list) or len(raw) != requested
                or not isinstance(utility, list) or len(utility) != requested
                or not all(isinstance(value, (int, float))
                           and not isinstance(value, bool)
                           and math.isfinite(float(value)) for value in raw)
                or not all(isinstance(value, (int, float))
                           and not isinstance(value, bool)
                           and math.isfinite(float(value)) for value in utility)):
            raise LabelRefused(f"Stage-C {fold} action tensor drift")
        expected_utility = [acting_utility(float(value), attacker=attacker)
                            for value in raw]
        if ([float(value) for value in utility] != expected_utility
                or not math.isclose(
                    float(action.get("mean_signed_level_utility")),
                    sum(expected_utility) / requested,
                    rel_tol=1e-12, abs_tol=1e-12)):
            raise LabelRefused(f"Stage-C {fold} utility transform drift")


def validate_label_row(state: Mapping[str, object], rnd,
                       row: Mapping[str, object], *,
                       audit_expected: bool) -> None:
    """Recompute every decision/work semantic without rerunning rollouts."""
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LabelRefused("Stage-C validation state lacks candidates")
    if (row.get("schema") != SCHEMA or row.get("status") != "COMPLETE"
            or row.get("state_id") != state.get("state_id")
            or row.get("split") != state.get("split")
            or row.get("surface_type") != state.get("surface_type")
            or row.get("stratum") != state.get("stratum")
            or row.get("candidate_count") != len(candidates)
            or row.get("candidate_tensor_sha256")
            != sha256_bytes(canonical_json(candidates))
            or row.get("recipe") != recipe_for_state(state)
            or row.get("raw_action_tensor_preserved") is not True
            or row.get("recursive_mc_continuation_rollouts") != 0
            or row.get("complete") is not True
            or row.get("row_sha256") != sha256_bytes(canonical_json({
                key: value for key, value in row.items()
                if key != "row_sha256"
            }))):
        raise LabelRefused("Stage-C label row identity/self-hash drift")
    all_indices = list(range(len(candidates)))
    recipe = recipe_for_state(state)
    selection_worlds = (ORDINARY_SELECTION_WORLDS
                        if recipe == "ordinary_anchor" else
                        HARD_SELECTION_WORLDS)
    _validate_fold(row["selection"], state=state, rnd=rnd,
                   fold="selection", requested=selection_worlds,
                   candidate_indices=all_indices)
    winner = selection_winner(row["selection"], len(candidates))
    if recipe == "ordinary_anchor":
        report_indices = all_indices
        report_worlds = ORDINARY_REPORT_WORLDS
        final_index = winner
        expected_decision = {
            "selection_winner_index": winner,
            "final_index": final_index,
            "reason": "ordinary_fixed_selection_argmax",
            "report_never_selected": True,
            "report_lcb_vs_candidate0": None,
        }
    else:
        report_indices = [0, winner]
        report_worlds = HARD_REPORT_WORLDS
        _validate_fold(row["report"], state=state, rnd=rnd,
                       fold="report", requested=report_worlds,
                       candidate_indices=report_indices)
        contrast = _report_contrast(
            row["report"], critical=HARD_T_95_DF299)
        final_index = winner if contrast["one_sided_95_lcb"] > 0 else 0
        expected_decision = {
            "selection_winner_index": winner,
            "final_index": final_index,
            "reason": ("hard_tail_report_lcb_override" if final_index != 0
                       else "hard_tail_report_lcb_fallback"),
            "report_never_selected": True,
            "report_lcb_vs_candidate0": contrast,
        }
    if recipe == "ordinary_anchor":
        _validate_fold(row["report"], state=state, rnd=rnd,
                       fold="report", requested=report_worlds,
                       candidate_indices=report_indices)
    if row.get("decision") != expected_decision:
        raise LabelRefused("Stage-C frozen label decision drift")
    candidate = candidates[final_index]
    if row.get("label_action") != {
        "index": final_index,
        "cards": list(action_key(candidate["cards"])),
        "sources": sorted(str(value) for value in candidate.get("sources", [])),
    }:
        raise LabelRefused("Stage-C label action identity drift")
    used = [row["selection"], row["report"]]
    audit = row.get("audit")
    if audit_expected:
        if not isinstance(audit, dict):
            raise LabelRefused("Stage-C frozen audit row is missing")
        _validate_fold(audit["selection"], state=state, rnd=rnd,
                       fold="audit_selection",
                       requested=AUDIT_SELECTION_WORLDS,
                       candidate_indices=all_indices)
        audit_winner = selection_winner(audit["selection"], len(candidates))
        plan = audit_report_plan(audit_winner, final_index)
        _validate_fold(audit["report"], state=state, rnd=rnd,
                       fold="audit_report", requested=AUDIT_REPORT_WORLDS,
                       candidate_indices=plan["candidate_indices"])
        expected_audit = audit_report_summary(
            audit["report"], audit_selection_winner=audit_winner,
            frozen_label_choice=final_index)
        if (audit.get("decision") != expected_audit
                or audit.get("independent_stream_from_label") is not True):
            raise LabelRefused("Stage-C audit decision drift")
        used.extend([audit["selection"], audit["report"]])
    elif audit is not None:
        raise LabelRefused("Stage-C non-audit row exposed audit outcomes")
    _validate_domain_separated_streams(
        [value["sampler"] for value in used])
    expected_fold_work = {
        "selection": len(candidates) * selection_worlds,
        "report": len(report_indices) * report_worlds,
        "audit_selection": (len(candidates) * AUDIT_SELECTION_WORLDS
                            if audit_expected else 0),
        "audit_report": (AUDIT_REPORT_CANDIDATE_WORLDS
                         if audit_expected else 0),
    }
    work = row.get("work")
    expected_samplers = {value["fold"]: value["sampler"] for value in used}
    expected_sampler_sequence = [value["fold"] for value in used]
    if (not isinstance(work, dict) or work.get("schema") != WORK_SCHEMA
            or work.get("candidate_worlds_attempted") != expected_fold_work
            or work.get("candidate_worlds_completed") != expected_fold_work
            or work.get("total_candidate_worlds_attempted")
            != sum(expected_fold_work.values())
            or work.get("total_candidate_worlds_completed")
            != sum(expected_fold_work.values())
            or work.get("samplers") != dict(sorted(expected_samplers.items()))
            or work.get("sampler_sequence") != expected_sampler_sequence
            or work.get("accounting_complete") is not True):
        raise LabelRefused("Stage-C label work ledger drift")


def _expected_sampler_worlds(state: Mapping[str, object], fold: str) -> int:
    recipe = recipe_for_state(state)
    values = {
        "selection": (ORDINARY_SELECTION_WORLDS
                      if recipe == "ordinary_anchor" else
                      HARD_SELECTION_WORLDS),
        "report": (ORDINARY_REPORT_WORLDS
                   if recipe == "ordinary_anchor" else
                   HARD_REPORT_WORLDS),
        "audit_selection": AUDIT_SELECTION_WORLDS,
        "audit_report": AUDIT_REPORT_WORLDS,
    }
    return values[fold]


def _validate_refusal_sampler(sampler: Mapping[str, object], *,
                              state: Mapping[str, object], fold: str) -> None:
    requested = _expected_sampler_worlds(state, fold)
    counters = sampler.get("counters")
    hashes = sampler.get("world_key_sha256s")
    accepted = sampler.get("accepted")
    attempts = sampler.get("attempts")
    unique_worlds = sampler.get("unique_worlds")
    duplicate_draws = sampler.get("duplicate_draws_retained")
    prior_overlaps = sampler.get("prior_fold_overlap_draws_retained")
    if (sampler.get("schema") != SAMPLER_SCHEMA
            or sampler.get("fold") != fold
            or sampler.get("seed") != seed_for(state, fold)
            or sampler.get("requested") != requested
            or isinstance(accepted, bool) or not isinstance(accepted, int)
            or not 0 <= accepted <= requested
            or isinstance(attempts, bool) or not isinstance(attempts, int)
            or not accepted <= attempts <= requested * SAMPLE_ATTEMPT_FACTOR
            or sampler.get("attempt_cap") != requested * SAMPLE_ATTEMPT_FACTOR
            or not isinstance(counters, dict)
            or set(counters) != set(SAMPLER_COUNTERS)
            or not all(isinstance(value, int) and not isinstance(value, bool)
                       and value >= 0 for value in counters.values())
            or counters["sample_attempts"] != attempts
            or sampler.get("accepted_draws") != counters["accepted_worlds"]
            or counters["accepted_worlds"] != accepted
            or counters["accepted_worlds"] + counters["failed_worlds"]
            != attempts
            or counters["rejected_worlds"] > counters["failed_worlds"]
            or not isinstance(hashes, list) or len(hashes) != accepted
            or not all(isinstance(value, str) and len(value) == 64
                       and not any(char not in "0123456789abcdef"
                                   for char in value) for value in hashes)
            or isinstance(unique_worlds, bool)
            or not isinstance(unique_worlds, int)
            or unique_worlds != len(set(hashes))
            or isinstance(duplicate_draws, bool)
            or not isinstance(duplicate_draws, int)
            or duplicate_draws != accepted - unique_worlds
            or isinstance(prior_overlaps, bool)
            or not isinstance(prior_overlaps, int)
            or not 0 <= prior_overlaps <= accepted
            or sampler.get("world_keys_sha256")
            != sha256_bytes(canonical_json(hashes))
            or sampler.get("sampling_with_replacement") is not True
            or sampler.get("domain_separated_stream") is not True
            or sampler.get("complete") is not (accepted == requested)):
        raise LabelRefused(f"Stage-C refusal sampler drift: {fold}")


def validate_refusal_record(state: Mapping[str, object],
                            row: Mapping[str, object], *,
                            audit_expected: bool) -> None:
    work = row.get("attempted_work")
    if (row.get("schema") != SCHEMA
            or row.get("status") != "REFUSED_NO_LABEL"
            or row.get("state_id") != state.get("state_id")
            or row.get("split") != state.get("split")
            or row.get("surface_type") != state.get("surface_type")
            or row.get("stratum") != state.get("stratum")
            or not isinstance(row.get("reason_class"), str)
            or not row["reason_class"]
            or not isinstance(row.get("reason_sha256"), str)
            or len(row["reason_sha256"]) != 64
            or any(char not in "0123456789abcdef"
                   for char in row["reason_sha256"])
            or row.get("utility_published") is not False
            or row.get("label_published") is not False
            or row.get("training_authorized") is not False
            or any(name in row for name in (
                "selection", "report", "audit", "decision", "label_action"))
            or row.get("row_sha256") != sha256_bytes(canonical_json({
                key: value for key, value in row.items()
                if key != "row_sha256"
            }))
            or not isinstance(work, dict) or work.get("schema") != WORK_SCHEMA):
        raise LabelRefused("Stage-C refusal identity/outcome leakage")
    attempted = work.get("candidate_worlds_attempted")
    completed = work.get("candidate_worlds_completed")
    samplers = work.get("samplers")
    sampler_sequence = work.get("sampler_sequence")
    if (not isinstance(attempted, dict) or set(attempted) != set(FOLDS)
            or not isinstance(completed, dict) or set(completed) != set(FOLDS)
            or not all(isinstance(value, int) and not isinstance(value, bool)
                       and value >= 0 for value in attempted.values())
            or not all(isinstance(value, int) and not isinstance(value, bool)
                       and value >= 0 for value in completed.values())
            or any(completed[name] > attempted[name] for name in FOLDS)
            or work.get("total_candidate_worlds_attempted")
            != sum(attempted.values())
            or work.get("total_candidate_worlds_completed")
            != sum(completed.values())
            or work.get("accounting_complete")
            is not (attempted == completed)
            or not isinstance(samplers, dict)
            or not set(samplers).issubset(FOLDS)
            or not isinstance(sampler_sequence, list)
            or any(not isinstance(value, str) for value in sampler_sequence)
            or len(set(sampler_sequence)) != len(sampler_sequence)
            or set(sampler_sequence) != set(samplers)):
        raise LabelRefused("Stage-C refusal work ledger drift")
    allowed_folds = {"selection", "report"}
    if audit_expected:
        allowed_folds.update({"audit_selection", "audit_report"})
    if not set(samplers).issubset(allowed_folds):
        raise LabelRefused("Stage-C refusal sampled an unauthorized fold")
    sequence = ["selection", "report"]
    if audit_expected:
        sequence.extend(["audit_selection", "audit_report"])
    if sampler_sequence != sequence[:len(sampler_sequence)]:
        raise LabelRefused("Stage-C refusal sampler sequence is not a prefix")
    ordered_samplers = []
    for fold in sampler_sequence:
        sampler = samplers[fold]
        if not isinstance(sampler, dict):
            raise LabelRefused("Stage-C refusal sampler type drift")
        _validate_refusal_sampler(sampler, state=state, fold=fold)
        ordered_samplers.append(sampler)
    _validate_domain_separated_streams(ordered_samplers)
    candidates = len(state["candidates"])
    fold_ceilings = {
        "selection": candidates * _expected_sampler_worlds(state, "selection"),
        "report": ((candidates if recipe_for_state(state) == "ordinary_anchor"
                    else 2) * _expected_sampler_worlds(state, "report")),
        "audit_selection": (candidates * AUDIT_SELECTION_WORLDS
                            if audit_expected else 0),
        "audit_report": (AUDIT_REPORT_CANDIDATE_WORLDS
                         if audit_expected else 0),
    }
    if (any(attempted[name] > fold_ceilings[name] for name in FOLDS)
            or any(attempted[name] for name in FOLDS if name not in samplers)
            or any(attempted[name] for name, sampler in samplers.items()
                   if sampler["complete"] is not True)):
        raise LabelRefused("Stage-C refusal fold work exceeds sampler authority")
    expected_ceiling = (
        candidates * (ORDINARY_SELECTION_WORLDS + ORDINARY_REPORT_WORLDS)
        if recipe_for_state(state) == "ordinary_anchor" else
        candidates * HARD_SELECTION_WORLDS + 2 * HARD_REPORT_WORLDS)
    if audit_expected:
        expected_ceiling += (candidates * AUDIT_SELECTION_WORLDS
                             + AUDIT_REPORT_CANDIDATE_WORLDS)
    if sum(attempted.values()) > expected_ceiling:
        raise LabelRefused("Stage-C refusal exceeded candidate-world ceiling")


def refusal_record(state: Mapping[str, object], exc: BaseException,
                   ledger: WorkLedger | None = None) -> dict:
    """Publish exact work and a reason hash, never partial outcome tensors."""
    reason = f"{type(exc).__name__}:{exc}"
    record = {
        "schema": SCHEMA,
        "status": "REFUSED_NO_LABEL",
        "state_id": state.get("state_id"),
        "split": state.get("split"),
        "surface_type": state.get("surface_type"),
        "stratum": state.get("stratum"),
        "reason_class": type(exc).__name__,
        "reason_sha256": hashlib.sha256(reason.encode()).hexdigest(),
        "attempted_work": (ledger or WorkLedger()).snapshot(),
        "utility_published": False,
        "label_published": False,
        "training_authorized": False,
    }
    record["row_sha256"] = sha256_bytes(canonical_json(record))
    return record


# ---------------------------------------------------------------- execution

REPO = SERVER.parent


def _ctrl():
    # The controller imports this primitive module to freeze its source hash;
    # keep the reverse dependency lazy so normal imports are acyclic.
    import teacher_stage_c_label_controller as controller
    return controller


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _terminal_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink() and not path.name.endswith(".partial"))


def _load_json(path: Path) -> dict:
    if not _terminal_file(path):
        raise LabelRefused(f"label input is not terminal/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise LabelRefused(f"cannot read label JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LabelRefused(f"label JSON root is not an object: {path}")
    return value


def _self_hash(value: Mapping[str, object], field: str) -> str:
    return sha256_bytes(canonical_json({
        key: item for key, item in value.items() if key != field
    }))


def _publish_exclusive(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise LabelRefused(f"refusing existing Stage-C label output: {path}")
    data = canonical_json(value)
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    except BaseException:
        try:
            partial.unlink()
        except OSError:
            pass
        raise


def _require_clean_tree() -> None:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise LabelRefused("Stage-C label runtime refuses a dirty tree")


def _controller_packet(path: Path, expected_sha256: str) -> dict:
    ctrl = _ctrl()
    _require_clean_tree()
    expected_path = (REPO / ctrl.CONTROLLER_PACKET_PATH).resolve()
    if path.resolve() != expected_path or not _terminal_file(path):
        raise LabelRefused("label-controller packet path/type drift")
    if ctrl.sha256_file(path) != expected_sha256:
        raise LabelRefused("label-controller external SHA-256 drift")
    packet = _load_json(path)
    authority = packet.get("authority", {})
    try:
        runtime_mode = ctrl.CAPTURE_CTRL.require_runtime_mode()
        sources = ctrl.runtime_sources()
        ctrl.require_admission_slot_ignored()
        shard_slots = ctrl.require_shard_admission_slots_ignored()
    except ctrl.ControllerRefused as exc:
        raise LabelRefused(str(exc)) from exc
    if (packet.get("schema") != ctrl.SCHEMA
            or packet.get("packet_id") != ctrl.PACKET_ID
            or packet.get("run_id") != ctrl.RUN_ID
            or packet.get("packet_sha256") != ctrl.self_hash(packet)
            or packet.get("producer", {}).get("git")
            != _git("rev-parse", "HEAD")
            or packet.get("runtime_mode") != runtime_mode
            or packet.get("runtime_sources") != sources
            or packet.get("result_contract", {}).get(
                "shard_admission_slots") != shard_slots
            or authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("labels_computed") is not False
            or authority.get("one_label_execution_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("report_open_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        raise LabelRefused("label-controller identity/authority drift")
    packet = dict(packet)
    packet["external_sha256"] = expected_sha256
    return packet


def _validated_parents(packet: Mapping[str, object],
                       state_set_review_record: Path) -> tuple[dict, dict]:
    ctrl = _ctrl()
    parents = packet["parents"]
    state_parent = parents["state_set"]
    verification_parent = parents["capture_verification"]
    try:
        state_set, verification, claim = ctrl.validate_state_set(
            (REPO / state_parent["logical_path"]).resolve(),
            state_parent["external_sha256"],
            (REPO / verification_parent["logical_path"]).resolve(),
            verification_parent["external_sha256"],
            state_set_review_record,
        )
    except ctrl.ControllerRefused as exc:
        raise LabelRefused(str(exc)) from exc
    if (claim != state_parent["review_claim"]
            or ctrl.build_schedule(state_set) != packet["schedule"]):
        raise LabelRefused("label-controller state-set/schedule drift")
    return state_set, verification


def _controller_review_claim(review_record: Path, packet: dict,
                             packet_sha256: str) -> dict:
    ctrl = _ctrl()
    try:
        claim = ctrl.marker_claim(review_record, ctrl.REVIEW_MARKER)
    except ctrl.ControllerRefused as exc:
        raise LabelRefused(str(exc)) from exc
    if claim != ctrl.expected_review_claim(packet, packet_sha256):
        raise LabelRefused("label-controller PASS marker drift")
    return claim


def _receipt(path: Path, expected_sha256: str, packet: Mapping[str, object],
             packet_sha256: str, controller_review_record: Path,
             state_set_review_record: Path) -> dict:
    ctrl = _ctrl()
    expected_path = (REPO / packet["result_contract"]["receipt"]).resolve()
    if path.resolve() != expected_path or not _terminal_file(path):
        raise LabelRefused("label receipt path/type drift")
    if ctrl.sha256_file(path) != expected_sha256:
        raise LabelRefused("label receipt external SHA-256 drift")
    receipt = _load_json(path)
    expected = {
        "schema": ctrl.RECEIPT_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "admission_slot": ctrl.admission_slot_logical_path(),
        "controller_review_record_sha256": ctrl.sha256_file(
            controller_review_record),
        "state_set_review_record_sha256": ctrl.sha256_file(
            state_set_review_record),
        "controller_review_claim": _controller_review_claim(
            controller_review_record, dict(packet), packet_sha256),
        "one_shot": True,
        "labels_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LabelRefused(f"label receipt field drift: {key}")
    if receipt.get("receipt_sha256") != _self_hash(receipt, "receipt_sha256"):
        raise LabelRefused("label receipt self-hash drift")
    slot_path = (REPO / ctrl.admission_slot_logical_path()).resolve()
    if not _terminal_file(slot_path):
        raise LabelRefused("durable label admission is missing")
    slot = _load_json(slot_path)
    expected_slot = {
        "schema": ctrl.ADMISSION_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(path.resolve()),
        "receipt_sha256": expected_sha256,
        "consumed_even_if_receipt_publication_fails": True,
    }
    expected_slot["slot_sha256"] = _self_hash(expected_slot, "slot_sha256")
    if slot != expected_slot:
        raise LabelRefused("durable label admission drift")
    return receipt


def admit(*, packet_path: Path, expected_packet_sha256: str,
          controller_review_record: Path, state_set_review_record: Path,
          out: Path) -> dict:
    ctrl = _ctrl()
    packet = _controller_packet(packet_path, expected_packet_sha256)
    _validated_parents(packet, state_set_review_record)
    claim = _controller_review_claim(
        controller_review_record, packet, expected_packet_sha256)
    expected_out = (REPO / packet["result_contract"]["receipt"]).resolve()
    if out.resolve() != expected_out:
        raise LabelRefused("label receipt output path drift")
    slot_path = (REPO / ctrl.admission_slot_logical_path()).resolve()
    if os.path.lexists(slot_path) or os.path.lexists(Path(str(slot_path) + ".partial")):
        raise LabelRefused("one-shot label admission is already consumed")
    receipt = {
        "schema": ctrl.RECEIPT_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "admission_slot": ctrl.admission_slot_logical_path(),
        "controller_review_record_sha256": ctrl.sha256_file(
            controller_review_record),
        "state_set_review_record_sha256": ctrl.sha256_file(
            state_set_review_record),
        "controller_review_claim": claim,
        "one_shot": True,
        "labels_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    receipt_file_sha = ctrl.sha256_bytes(ctrl.canonical_json(receipt))
    slot = {
        "schema": ctrl.ADMISSION_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(out.resolve()),
        "receipt_sha256": receipt_file_sha,
        "consumed_even_if_receipt_publication_fails": True,
    }
    slot["slot_sha256"] = _self_hash(slot, "slot_sha256")
    _publish_exclusive(slot_path, slot)
    _publish_exclusive(out, receipt)
    return receipt


def _expected_shard_path(packet: Mapping[str, object], index: int) -> Path:
    try:
        logical = packet["result_contract"]["shards"][index]
    except (IndexError, KeyError, TypeError) as exc:
        raise LabelRefused("Stage-C label shard index outside schedule") from exc
    return (REPO / logical).resolve()


def _consume_shard_slot(packet: Mapping[str, object], *, index: int,
                        packet_sha256: str, receipt_sha256: str) -> tuple[dict, str]:
    ctrl = _ctrl()
    logical = ctrl.shard_admission_logical_path(index)
    if packet["result_contract"]["shard_admission_slots"][index] != logical:
        raise LabelRefused("Stage-C label shard admission path drift")
    path = (REPO / logical).resolve()
    if os.path.lexists(path) or os.path.lexists(Path(str(path) + ".partial")):
        raise LabelRefused("Stage-C label shard admission already consumed")
    schedule = packet["schedule"]["shards"][index]
    slot = {
        "schema": ctrl.SHARD_ADMISSION_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "label_receipt_sha256": receipt_sha256,
        "shard_index": index,
        "state_ids_sha256": schedule["state_ids_sha256"],
        "consumed_before_sampler_or_outcome": True,
        "retry_after_crash_or_refusal_authorized": False,
    }
    slot["slot_sha256"] = _self_hash(slot, "slot_sha256")
    _publish_exclusive(path, slot)
    return slot, ctrl.sha256_file(path)


def _validate_shard_slot(packet: Mapping[str, object], *, index: int,
                         packet_sha256: str, receipt_sha256: str,
                         expected_file_sha256: str) -> None:
    ctrl = _ctrl()
    logical = ctrl.shard_admission_logical_path(index)
    path = (REPO / logical).resolve()
    if (packet["result_contract"]["shard_admission_slots"][index] != logical
            or not _terminal_file(path)
            or ctrl.sha256_file(path) != expected_file_sha256):
        raise LabelRefused("Stage-C label shard admission file drift")
    slot = _load_json(path)
    expected = {
        "schema": ctrl.SHARD_ADMISSION_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "label_receipt_sha256": receipt_sha256,
        "shard_index": index,
        "state_ids_sha256": packet["schedule"]["shards"][index][
            "state_ids_sha256"],
        "consumed_before_sampler_or_outcome": True,
        "retry_after_crash_or_refusal_authorized": False,
    }
    expected["slot_sha256"] = _self_hash(expected, "slot_sha256")
    if slot != expected:
        raise LabelRefused("Stage-C label shard admission content drift")


def _state_map(state_set: Mapping[str, object]) -> dict[str, dict]:
    states = state_set.get("states")
    if not isinstance(states, list):
        raise LabelRefused("Stage-C state-set rows missing")
    result = {str(state["state_id"]): state for state in states}
    if len(result) != len(states):
        raise LabelRefused("Stage-C state-set identity collision")
    return result


def _load_v11():
    ctrl = _ctrl()
    path = REPO / CAPTURE.V11_PATH
    if ctrl.sha256_file(path) != CAPTURE.V11_SHA256:
        raise LabelRefused("Stage-C frozen V11 checkpoint drift")
    return CAPTURE._load_npnet(str(path))


def _work_from_rows(rows: Sequence[Mapping[str, object]]) -> dict:
    attempted = 0
    completed = 0
    sampler_attempts = 0
    accepted_worlds = 0
    for row in rows:
        work = row["work"] if row.get("status") == "COMPLETE" \
            else row["attempted_work"]
        attempted += int(work["total_candidate_worlds_attempted"])
        completed += int(work["total_candidate_worlds_completed"])
        for sampler in work["samplers"].values():
            sampler_attempts += int(sampler["attempts"])
            accepted_worlds += int(sampler["accepted"])
    return {
        "candidate_worlds_attempted": attempted,
        "candidate_worlds_completed": completed,
        "sampler_attempts": sampler_attempts,
        "accepted_worlds": accepted_worlds,
    }


def run_shard(*, packet_path: Path, expected_packet_sha256: str,
              receipt_path: Path, expected_receipt_sha256: str,
              controller_review_record: Path, state_set_review_record: Path,
              shard_index: int,
              progress_every: int, out: Path) -> dict:
    ctrl = _ctrl()
    packet = _controller_packet(packet_path, expected_packet_sha256)
    state_set, _verification = _validated_parents(
        packet, state_set_review_record)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, controller_review_record,
             state_set_review_record)
    if not 0 <= shard_index < ctrl.LABEL_SHARDS or progress_every <= 0:
        raise LabelRefused("Stage-C label shard/progress argument drift")
    if out.resolve() != _expected_shard_path(packet, shard_index):
        raise LabelRefused("Stage-C label shard output path drift")
    if os.path.lexists(out) or os.path.lexists(Path(str(out) + ".partial")):
        raise LabelRefused("refusing existing Stage-C label shard/partial")
    schedule = packet["schedule"]["shards"][shard_index]
    _slot, slot_file_sha256 = _consume_shard_slot(
        packet, index=shard_index,
        packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256)
    states = _state_map(state_set)
    net = _load_v11()
    audit_ids = set(schedule["audit_state_ids"])
    rows = []
    for index, state_id in enumerate(schedule["state_ids"], 1):
        state = states[state_id]
        ledger = WorkLedger()
        try:
            row = label_state(
                state, net=net, include_audit=state_id in audit_ids,
                ledger=ledger)
            rnd = CAPTURE.replay_state(state)
            validate_label_row(
                state, rnd, row, audit_expected=state_id in audit_ids)
        except Exception as exc:
            row = refusal_record(state, exc, ledger)
        rows.append(row)
        if index % progress_every == 0 or index == len(schedule["state_ids"]):
            print(json.dumps({
                "status": "LABELING",
                "shard": shard_index,
                "states_complete": index,
                "states_total": len(schedule["state_ids"]),
                "refusals": sum(value["status"] != "COMPLETE" for value in rows),
            }, sort_keys=True), file=sys.stderr, flush=True)
    work = _work_from_rows(rows)
    refusals = sum(row["status"] != "COMPLETE" for row in rows)
    payload = {
        "schema": ctrl.SHARD_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "label_receipt_sha256": expected_receipt_sha256,
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "shard_index": shard_index,
        "split": schedule["split"],
        "local_shard": schedule["local_shard"],
        "state_ids": list(schedule["state_ids"]),
        "state_ids_sha256": schedule["state_ids_sha256"],
        "audit_state_ids": list(schedule["audit_state_ids"]),
        "shard_admission_slot": ctrl.shard_admission_logical_path(shard_index),
        "shard_admission_file_sha256": slot_file_sha256,
        "status": ("COMPLETE" if refusals == 0
                   else "REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY"),
        "complete_rows": len(rows) - refusals,
        "refused_rows": refusals,
        "rows": rows,
        "row_sha256s": [row["row_sha256"] for row in rows],
        "work": work,
        "expected_candidate_worlds": schedule["candidate_worlds"],
        "candidate_world_ceiling_respected":
            work["candidate_worlds_attempted"] <= schedule["candidate_worlds"],
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["shard_sha256"] = _self_hash(payload, "shard_sha256")
    _controller_packet(packet_path, expected_packet_sha256)
    final_state_set, _final_verification = _validated_parents(
        packet, state_set_review_record)
    if final_state_set != state_set:
        raise LabelRefused("Stage-C state set changed during label shard")
    if ctrl.sha256_file(REPO / CAPTURE.V11_PATH) != CAPTURE.V11_SHA256:
        raise LabelRefused("Stage-C V11 checkpoint changed during label shard")
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, controller_review_record,
             state_set_review_record)
    _publish_exclusive(out, payload)
    return payload


def validate_shard(shard: Mapping[str, object], *, packet: Mapping[str, object],
                   receipt_sha256: str, state_set: Mapping[str, object],
                   index: int, net) -> None:
    ctrl = _ctrl()
    schedule = packet["schedule"]["shards"][index]
    rows = shard.get("rows")
    if (shard.get("schema") != ctrl.SHARD_SCHEMA
            or shard.get("run_id") != ctrl.RUN_ID
            or shard.get("git") != packet["producer"]["git"]
            or shard.get("controller_packet_sha256")
            != packet["external_sha256"]
            or shard.get("label_receipt_sha256") != receipt_sha256
            or shard.get("state_set_sha256")
            != packet["parents"]["state_set"]["external_sha256"]
            or shard.get("schedule_sha256")
            != packet["schedule"]["schedule_sha256"]
            or shard.get("shard_index") != index
            or shard.get("split") != schedule["split"]
            or shard.get("local_shard") != schedule["local_shard"]
            or shard.get("state_ids") != schedule["state_ids"]
            or shard.get("state_ids_sha256") != schedule["state_ids_sha256"]
            or shard.get("audit_state_ids") != schedule["audit_state_ids"]
            or shard.get("shard_admission_slot")
            != ctrl.shard_admission_logical_path(index)
            or not isinstance(shard.get("shard_admission_file_sha256"), str)
            or not isinstance(rows, list) or len(rows) != schedule["state_count"]
            or shard.get("shard_sha256") != _self_hash(shard, "shard_sha256")
            or shard.get("training_authorized") is not False
            or shard.get("report_open_authorized") is not False):
        raise LabelRefused(f"Stage-C label shard {index} identity drift")
    _validate_shard_slot(
        packet, index=index, packet_sha256=packet["external_sha256"],
        receipt_sha256=receipt_sha256,
        expected_file_sha256=shard["shard_admission_file_sha256"])
    states = _state_map(state_set)
    audit_ids = set(schedule["audit_state_ids"])
    complete = 0
    refused = 0
    for state_id, row in zip(schedule["state_ids"], rows, strict=True):
        state = states[state_id]
        if row.get("state_id") != state_id:
            raise LabelRefused(f"Stage-C label shard {index} row order drift")
        if row.get("status") == "COMPLETE":
            rnd = CAPTURE.replay_state(state)
            CAPTURE._validate_candidates(state, rnd, net)
            validate_label_row(
                state, rnd, row, audit_expected=state_id in audit_ids)
            complete += 1
        else:
            validate_refusal_record(
                state, row, audit_expected=state_id in audit_ids)
            refused += 1
    expected_status = ("COMPLETE" if refused == 0
                       else "REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY")
    work = _work_from_rows(rows)
    if (shard.get("status") != expected_status
            or shard.get("complete_rows") != complete
            or shard.get("refused_rows") != refused
            or shard.get("row_sha256s") != [row["row_sha256"] for row in rows]
            or shard.get("work") != work
            or shard.get("expected_candidate_worlds")
            != schedule["candidate_worlds"]
            or shard.get("candidate_world_ceiling_respected")
            is not (work["candidate_worlds_attempted"]
                    <= schedule["candidate_worlds"])):
        raise LabelRefused(f"Stage-C label shard {index} work/status drift")


def _t_critical_for_n(n: int) -> float:
    # Frozen one-sided 95% Student-t criticals for the only report populations.
    values = {48: 1.677927, 64: 1.669402, 192: 1.652871, 256: 1.650851}
    try:
        return values[n]
    except KeyError as exc:
        raise LabelRefused(f"unreviewed Stage-C clustered population: {n}") from exc


def _cluster_summary(values: Sequence[float]) -> dict:
    result = paired_summary(
        values, [0.0] * len(values), critical=_t_critical_for_n(len(values)))
    result["unit"] = "frozen REPORT deal/state"
    return result


def _audit_gate(rows: Sequence[Mapping[str, object]],
                states: Mapping[str, dict]) -> dict:
    audit_rows = [row for row in rows if row.get("audit") is not None]
    if len(audit_rows) != 256:
        raise LabelRefused("Stage-C audit row population drift")
    grouped = {"ordinary_anchor": [], "hard_tail": []}
    diagnostics: dict[str, list[float]] = {}
    v11_diffs = []
    for row in audit_rows:
        state = states[str(row["state_id"])]
        regret = float(row["audit"]["decision"][
            "audit_reference_minus_label_choice"]["mean"])
        grouped[recipe_for_state(state)].append(regret)
        cell = ":".join(str(state.get(name)) for name in (
            "surface_type", "stratum", "phase", "role", "surface"))
        diagnostics.setdefault(cell, []).append(regret)
        if state.get("stratum") == "proposal_disagreement":
            target = int(row["audit"]["decision"]["audit_reference_index"])
            candidates = state["candidates"]
            source_sets = [set(candidate.get("sources", []))
                           for candidate in candidates]
            names = set().union(*source_sets)
            if ("v11pair_top_proposal" not in names
                    or "same_budget_random_diversifier" not in names):
                raise LabelRefused(
                    "Stage-C V11 recall row lacks matched one-action control")
            target_sources = source_sets[target]
            live = "live_production_ballot" in target_sources or target == 0
            treatment = live or "v11pair_top_proposal" in target_sources
            control = live or "same_budget_random_diversifier" in target_sources
            v11_diffs.append(float(treatment) - float(control))
    if [len(grouped[name]) for name in ("ordinary_anchor", "hard_tail")] != [64, 192]:
        raise LabelRefused("Stage-C ordinary/hard-tail audit quota drift")
    if len(v11_diffs) != 48:
        raise LabelRefused("Stage-C V11 recall REPORT quota drift")
    ordinary = _cluster_summary(grouped["ordinary_anchor"])
    hard = _cluster_summary(grouped["hard_tail"])
    v11 = _cluster_summary(v11_diffs)
    fidelity_pass = (ordinary["one_sided_95_ucb"] <= 0.10
                     and hard["one_sided_95_ucb"] <= 0.10)
    recall_pass = v11["one_sided_95_lcb"] > 0
    return {
        "schema": "teacher-stage-c-label-fidelity-gate-v2",
        "audit_states": 256,
        "ordinary_anchor_regret": ordinary,
        "hard_tail_regret": hard,
        "v11_recall_treatment_minus_matched_random": v11,
        "cell_diagnostics": {
            key: {"n": len(values), "mean_regret": sum(values) / len(values)}
            for key, values in sorted(diagnostics.items())
        },
        "fidelity_pass": fidelity_pass,
        "v11_recall_pass": recall_pass,
        "decision": ("AUTHORIZE_MODEL_PACKET_REVIEW"
                     if fidelity_pass and recall_pass else
                     "DIAGNOSE_FROZEN_STAGE_C_ONLY"),
        "training_authorized": False,
        "report_open_authorized": False,
    }


def recompute_aggregate_payload(
    *, packet: Mapping[str, object], expected_packet_sha256: str,
    expected_receipt_sha256: str, state_set: Mapping[str, object],
    shard_paths: Sequence[Path],
) -> tuple[dict, list[dict]]:
    """Reopen every label row and deterministically rebuild the aggregate."""
    ctrl = _ctrl()
    if len(shard_paths) != ctrl.LABEL_SHARDS:
        raise LabelRefused("Stage-C aggregate requires all label shards")
    net = _load_v11()
    shards = []
    for index, path in enumerate(shard_paths):
        if path.resolve() != _expected_shard_path(packet, index):
            raise LabelRefused("Stage-C aggregate shard path/order drift")
        shard = _load_json(path)
        validate_shard(
            shard, packet=packet, receipt_sha256=expected_receipt_sha256,
            state_set=state_set, index=index, net=net)
        shard = dict(shard)
        shard["external_sha256"] = ctrl.sha256_file(path)
        shards.append(shard)
    rows = [row for shard in shards for row in shard["rows"]]
    refusals = sum(row["status"] != "COMPLETE" for row in rows)
    work = _work_from_rows(rows)
    if (len(rows) != ctrl.EXPECTED_STATES
            or work["candidate_worlds_attempted"]
            > packet["result_contract"]["max_candidate_worlds"]
            or work["sampler_attempts"]
            > packet["result_contract"]["max_sampler_attempts"]):
        raise LabelRefused("Stage-C aggregate population/work drift")
    shard_manifest = [{
        "index": shard["shard_index"],
        "split": shard["split"],
        "sha256": shard["external_sha256"],
        "row_sha256s_sha256": sha256_bytes(canonical_json(
            shard["row_sha256s"])),
    } for shard in shards]
    training_label_states = getattr(ctrl, "TRAINING_LABEL_STATES", None)
    if training_label_states is None:
        expected_splits = getattr(ctrl, "EXPECTED_SPLITS", None)
        if expected_splits is not None:
            training_label_states = (expected_splits["DESIGN"]
                                     + expected_splits["CALIB"])
        else:
            training_label_states = sum(
                len(shard["rows"]) for shard in shards
                if shard["split"] in {"DESIGN", "CALIB"})
    training_label_states = int(training_label_states)
    reused_label_states = int(getattr(ctrl, "REUSED_LABEL_STATES", 0))
    sealed_report_states = int(getattr(ctrl, "SEALED_REPORT_STATES", 512))
    compute_fidelity_gate = bool(getattr(
        ctrl, "COMPUTE_FIDELITY_GATE", True))
    payload = {
        "schema": ctrl.AGGREGATE_SCHEMA,
        "run_id": ctrl.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "label_receipt_sha256": expected_receipt_sha256,
        "state_set_sha256": packet["parents"]["state_set"]["external_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "status": ("COMPLETE" if refusals == 0
                   else "TERMINAL_HOLD_NO_EXTENSION"),
        "states": len(rows),
        "complete_rows": len(rows) - refusals,
        "refused_rows": refusals,
        "work": work,
        "shards": shard_manifest,
        "design_calib_manifest": {
            "splits": ["DESIGN", "CALIB"],
            "shards": [item for item in shard_manifest
                       if item["split"] in {"DESIGN", "CALIB"}],
            "states": training_label_states,
            "reused_labels_not_in_shards": reused_label_states,
            "report_rows_included": False,
            "training_packet_review_authorized": False,
        },
        "sealed_report_manifest": {
            "split": "REPORT",
            "shards": [item for item in shard_manifest
                       if item["split"] == "REPORT"],
            "states": sealed_report_states,
            "sealed_from_training_and_seed_selection": True,
            "report_open_authorized": False,
        },
        "fidelity_gate": None,
        "utility_published": refusals == 0,
        "model_packet_review_authorized": False,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    if not hasattr(ctrl, "REUSED_LABEL_STATES"):
        payload["design_calib_manifest"].pop(
            "reused_labels_not_in_shards")
    if refusals == 0 and compute_fidelity_gate:
        gate = _audit_gate(rows, _state_map(state_set))
        payload["fidelity_gate"] = gate
        payload["model_packet_review_authorized"] = (
            gate["decision"] == "AUTHORIZE_MODEL_PACKET_REVIEW")
    elif refusals == 0:
        # Expanded labels add no audit/REPORT rows.  The original immutable
        # 2,048-state aggregate already passed its fidelity gate; this run's
        # only admissible question is whether every newly scheduled row
        # completed inside the frozen work ceiling.  A later model packet must
        # still independently authenticate and merge the reused labels.
        payload["fidelity_gate"] = {
            "schema": "teacher-stage-c-expanded-label-completion-gate-v1",
            "fidelity_recomputed": False,
            "reason": "no audit or REPORT rows scheduled in expansion",
            "original_fidelity_parent_required": True,
            "all_new_rows_complete": True,
            "decision": "AUTHORIZE_MODEL_PACKET_REVIEW",
            "training_authorized": False,
            "report_open_authorized": False,
        }
        payload["model_packet_review_authorized"] = True
    payload["aggregate_sha256"] = _self_hash(payload, "aggregate_sha256")
    return payload, shards


def aggregate(*, packet_path: Path, expected_packet_sha256: str,
              receipt_path: Path, expected_receipt_sha256: str,
              controller_review_record: Path, state_set_review_record: Path,
              shard_paths: Sequence[Path], out: Path) -> dict:
    ctrl = _ctrl()
    packet = _controller_packet(packet_path, expected_packet_sha256)
    state_set, _verification = _validated_parents(
        packet, state_set_review_record)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, controller_review_record,
             state_set_review_record)
    expected_out = (REPO / packet["result_contract"]["aggregate"]).resolve()
    if out.resolve() != expected_out:
        raise LabelRefused("Stage-C label aggregate output path drift")
    payload, shards = recompute_aggregate_payload(
        packet=packet, expected_packet_sha256=expected_packet_sha256,
        expected_receipt_sha256=expected_receipt_sha256,
        state_set=state_set, shard_paths=shard_paths)
    _controller_packet(packet_path, expected_packet_sha256)
    final_state_set, _final_verification = _validated_parents(
        packet, state_set_review_record)
    if final_state_set != state_set:
        raise LabelRefused("Stage-C state set changed during label aggregate")
    for path, shard in zip(shard_paths, shards, strict=True):
        if ctrl.sha256_file(path) != shard["external_sha256"]:
            raise LabelRefused("Stage-C label shard changed during aggregate")
    if ctrl.sha256_file(REPO / CAPTURE.V11_PATH) != CAPTURE.V11_SHA256:
        raise LabelRefused("Stage-C V11 checkpoint changed during aggregate")
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, controller_review_record,
             state_set_review_record)
    _publish_exclusive(out, payload)
    return payload


def _identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--controller-packet", required=True)
    parser.add_argument("--expected-controller-packet-sha256", required=True)


def _receipt_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--label-receipt", required=True)
    parser.add_argument("--expected-label-receipt-sha256", required=True)
    parser.add_argument("--controller-review-record", required=True)
    parser.add_argument("--state-set-review-record", required=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    admit_parser = commands.add_parser("admit")
    _identity_args(admit_parser)
    admit_parser.add_argument("--controller-review-record", required=True)
    admit_parser.add_argument("--state-set-review-record", required=True)
    admit_parser.add_argument("--out", required=True)
    shard_parser = commands.add_parser("run-shard")
    _identity_args(shard_parser)
    _receipt_args(shard_parser)
    shard_parser.add_argument("--shard-index", type=int, required=True)
    shard_parser.add_argument("--progress-every", type=int, default=1)
    shard_parser.add_argument("--out", required=True)
    aggregate_parser = commands.add_parser("aggregate")
    _identity_args(aggregate_parser)
    _receipt_args(aggregate_parser)
    aggregate_parser.add_argument("--shards", nargs="+", required=True)
    aggregate_parser.add_argument("--out", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if _git("rev-parse", "HEAD") != args.expected_git:
        raise LabelRefused("Stage-C label expected Git drift")
    common = {
        "packet_path": Path(args.controller_packet).resolve(),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
    }
    if args.command == "admit":
        value = admit(
            **common,
            controller_review_record=Path(
                args.controller_review_record).resolve(),
            state_set_review_record=Path(args.state_set_review_record).resolve(),
            out=Path(args.out).resolve(),
        )
    elif args.command == "run-shard":
        value = run_shard(
            **common,
            receipt_path=Path(args.label_receipt).resolve(),
            expected_receipt_sha256=args.expected_label_receipt_sha256,
            controller_review_record=Path(
                args.controller_review_record).resolve(),
            state_set_review_record=Path(args.state_set_review_record).resolve(),
            shard_index=args.shard_index,
            progress_every=args.progress_every,
            out=Path(args.out).resolve(),
        )
    else:
        value = aggregate(
            **common,
            receipt_path=Path(args.label_receipt).resolve(),
            expected_receipt_sha256=args.expected_label_receipt_sha256,
            controller_review_record=Path(
                args.controller_review_record).resolve(),
            state_set_review_record=Path(args.state_set_review_record).resolve(),
            shard_paths=[Path(value).resolve() for value in args.shards],
            out=Path(args.out).resolve(),
        )
    print(json.dumps({
        "status": value.get("status", "ADMITTED"),
        "sha256": sha256_bytes(canonical_json(value)),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LabelRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
