#!/usr/bin/env python3
"""Finite-work labeling primitives for Teacher Stage C.

This module is deliberately not an execution controller.  It implements the
outcome-producing core that a later, dataset-bound and independently reviewed
controller may call.  Importing it, running its tests, or compiling it samples
no worlds and publishes no labels.

The important boundaries are executable here:

* every fold has a domain-separated deterministic stream;
* rejected sampler draws consume attempts until a finite reviewed cap;
* all candidates in a fold share the same accepted worlds;
* selection and report folds are disjoint;
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

import hashlib
import json
import math
import sys
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


SCHEMA = "teacher-stage-c-label-row-v1"
SAMPLER_SCHEMA = "teacher-stage-c-label-sampler-v1"
FOLD_SCHEMA = "teacher-stage-c-label-fold-v1"
WORK_SCHEMA = "teacher-stage-c-label-work-v1"
STREAM_SCHEMA = "teacher-stage-c-label-stream-v1"

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
# selection uses a disjoint fold, so the report contrast is not winner-picked
# on the same observations.  They are not simultaneous intervals over states.
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


def _worlds_digest(worlds: Sequence[tuple]) -> str:
    keys = []
    for hands, buried in worlds:
        key = world_key(hands, buried)
        keys.append([
            [[seat, list(cards)] for seat, cards in key[0]],
            list(key[1]),
        ])
    return sha256_bytes(canonical_json(keys))


@dataclass
class WorkLedger:
    """Exact candidate-world accounting that survives an expected refusal."""

    attempted: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in FOLDS})
    completed: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in FOLDS})
    samplers: dict[str, dict] = field(default_factory=dict)

    def record_sampler(self, fold: str, sampler: Mapping[str, object]) -> None:
        if fold not in FOLDS or fold in self.samplers:
            raise LabelRefused("duplicate or unknown label sampler fold")
        self.samplers[fold] = dict(sampler)

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
            "accounting_complete": True,
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
    attempts = 0
    cap = count * factor
    while len(worlds) < count and attempts < cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is not None:
            worlds.append(sampled)
    delta = _sampler_delta(before, _sampler_snapshot(bot))
    sampler = {
        "schema": SAMPLER_SCHEMA,
        "fold": fold,
        "seed": seed,
        "requested": count,
        "accepted": len(worlds),
        "attempts": attempts,
        "attempt_cap": cap,
        "counters": delta,
        "world_keys_sha256": _worlds_digest(worlds),
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
        "family": "per-state fixed-pair Student-t; selection/report disjoint",
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
                         fold_runner: FoldRunner = run_fold) -> dict:
    """Produce one complete label row from a replayed, candidate-verified state."""
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LabelRefused("Stage-C label state lacks candidates")
    cap = PLAY_CANDIDATE_CAP if state.get("surface_type") == "play" \
        else BURY_CANDIDATE_CAP
    if len(candidates) > cap:
        raise LabelRefused("Stage-C label candidate cap exceeded")
    ledger = WorkLedger()
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
    work = ledger.snapshot()
    expected = (len(candidates) *
                (ORDINARY_SELECTION_WORLDS + ORDINARY_REPORT_WORLDS)
                if recipe == "ordinary_anchor" else
                len(candidates) * HARD_SELECTION_WORLDS
                + 2 * HARD_REPORT_WORLDS)
    if (work["total_candidate_worlds_attempted"] != expected
            or work["total_candidate_worlds_completed"] != expected):
        raise LabelRefused("Stage-C label candidate-world work drift")
    if (selection["sampler"]["world_keys_sha256"]
            == report["sampler"]["world_keys_sha256"]
            or selection["seed"] == report["seed"]):
        raise LabelRefused("Stage-C selection/report worlds are not disjoint")
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
                fold_runner: FoldRunner = run_fold) -> dict:
    """Replay and revalidate a captured state before producing its label."""
    rnd = CAPTURE.replay_state(state)
    if net is None:
        raise LabelRefused("candidate replay requires the frozen V11 network")
    CAPTURE._validate_candidates(state, rnd, net)
    return label_replayed_state(state, rnd, fold_runner=fold_runner)


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


def refusal_record(state: Mapping[str, object], exc: BaseException,
                   ledger: WorkLedger | None = None) -> dict:
    """Publish exact work and a reason hash, never partial outcome tensors."""
    reason = f"{type(exc).__name__}:{exc}"
    return {
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
