"""Opt-in, gate-controlled extra-trick CWV continuation.

The ordinary heuristic matrix on the selection worlds is the pilot. Only when
its nominated non-incumbent is within the paired uncertainty band is the
existing bounded double-shortlist continuation allowed to replace the first
four worlds; the report fold remains separately sampled.
"""
from __future__ import annotations

import copy
import math
from collections import Counter
from typing import Any

import numpy as np

from ..ai.cwv_policy import afterstate
from ..harvest.legal import count_multiset_subsets, enumerate_legal
from .cwv_double_shortlist import CWVDoubleShortlistBot, DoubleShortlistError


class CWVSelectiveDepthBot(CWVDoubleShortlistBot):
    """Learned extra-trick guidance gated by a flat selection-world pilot."""

    SELECTIVE_RECORD_SCHEMA = "cwv-selective-depth-v1"
    SELECTIVE_GATE = "paired-flat-gap-v1"
    INNER_RAW_FOLLOW_LIMIT = 4096

    def __init__(self, evaluator, *, seed=0, config=None,
                 reuse_successors=False, gate_z=1.7,
                 inner_legal_limit=128, inner_batch_size=128,
                 inner_reuse_successors=False, **kwargs):
        if type(gate_z) not in (int, float) or isinstance(gate_z, bool) \
                or not math.isfinite(gate_z) or gate_z <= 0:
            raise DoubleShortlistError("gate_z must be a finite positive number")
        if type(inner_legal_limit) is not int or inner_legal_limit < 1:
            raise DoubleShortlistError("inner_legal_limit must be a positive integer")
        # This treatment is deliberately fixed: its only variable is whether
        # the already-existing four-world learned continuation is admitted.
        if kwargs.pop("inner_mode", "learned") != "learned":
            raise DoubleShortlistError("selective depth requires learned inner guidance")
        if kwargs.pop("inner_worlds", 4) != 4:
            raise DoubleShortlistError("selective depth requires four guided worlds")
        if kwargs.pop("inner_alternatives", 4) != 4:
            raise DoubleShortlistError("selective depth requires four inner alternatives")
        if kwargs:
            name = next(iter(kwargs))
            raise TypeError(f"unexpected selective-depth argument {name!r}")
        super().__init__(
            evaluator, seed=seed, config=config,
            reuse_successors=reuse_successors, inner_mode="learned",
            inner_worlds=4, inner_alternatives=4,
            inner_batch_size=inner_batch_size,
            inner_reuse_successors=inner_reuse_successors)
        self.gate_z = gate_z
        self.inner_legal_limit = inner_legal_limit
        self.last_selective_depth: dict[str, Any] | None = None
        self.selective_depth_counts = {
            "decisions": 0, "triggered": 0, "gate_false": 0,
            "selection_calls": 0, "report_calls": 0,
            "inner_eligible": 0, "inner_skipped": 0,
            "inner_raw_follow_skipped": 0,
            "inner_rollouts": 0, "extra_rollouts": 0, "reused_flat_cells": 0,
        }
        self._selective_gate = False

    def decide_play(self, rnd, seat):
        # Forced singleton decisions never inherit a prior gate or trace.
        self.last_selective_depth = None
        self._selective_gate = False
        self._selective_pending_outer_rollouts = 0
        played = super().decide_play(rnd, seat)
        detail = self.last_selective_depth
        if detail is not None:
            self.selective_depth_counts["decisions"] += 1
            self.selective_depth_counts["triggered"] += int(detail["triggered"])
            self.selective_depth_counts["gate_false"] += int(not detail["triggered"])
            self.selective_depth_counts["inner_eligible"] += detail["inner_eligible"]
            self.selective_depth_counts["inner_skipped"] += detail["inner_skipped"]
            self.selective_depth_counts["inner_raw_follow_skipped"] += detail[
                "inner_raw_follow_skipped"]
            self.selective_depth_counts["inner_rollouts"] += detail["inner_rollouts"]
            self.selective_depth_counts["extra_rollouts"] += detail["extra_rollout_cost"]
            self.selective_depth_counts["reused_flat_cells"] += detail["reused_flat_cells"]
            if self.last_decision_record is not None:
                self.last_decision_record["cwv_selective_depth"] = copy.deepcopy(detail)
                self.last_decision_record["work"]["selective_depth_rollouts"] = (
                    detail["extra_rollout_cost"])
                self.last_decision_record["work"]["total_rollouts_including_selective_depth"] = (
                    self.last_decision_record["work"].get(
                        "total_rollouts_including_inner",
                        self.last_decision_record["work"]["total_rollouts"]))
                self.last_decision_record["work"]["total_rollouts_including_selective_depth"] += (
                    detail["extra_rollout_cost"])
        return played

    # ------------------------------------------------------------ flat pilot
    def _flat_matrix(self, rnd, seat, worlds, candidates, *, stage, sessions):
        """Run the native inherited flat rollout on the supplied worlds."""
        values = np.empty((len(worlds), len(candidates)), dtype=np.float64)
        for wi, (hands, buried) in enumerate(worlds):
            sampled = {s: list(hands[s]) for s in range(4) if s != seat}
            session = None if sessions is None else sessions[wi]
            prepared = (self._prepare_report_world(
                rnd, seat, sampled, buried=list(buried))
                        if stage == "report" else None)
            for ci, candidate in enumerate(candidates):
                if prepared is None:
                    values[wi, ci] = self._rollout(
                        rnd, seat, sampled, list(buried), list(candidate),
                        exact_session=session)
                else:
                    values[wi, ci] = self._report_rollout(
                        rnd, seat, sampled, list(buried), list(candidate),
                        exact_session=session, prepared=prepared)
        if not np.isfinite(values).all():
            raise DoubleShortlistError(
                f"selective-depth {stage} flat pilot produced no value")
        return values

    def _pilot_gate(self, rnd, seat, values, candidates):
        n_worlds, n_candidates = values.shape
        if n_worlds < 1:
            return False, "selection-worlds-underfilled", None, None, None
        if n_candidates < 2:
            return False, "no-non-incumbent", None, None, None
        team = 1.0 if rnd.is_attacker(seat) else -1.0
        means = np.asarray([
            np.mean([team * self._score(float(value)) for value in values[:, i]])
            for i in range(n_candidates)
        ])
        nominated = self._pick_index(candidates, means.tolist(), range(1, n_candidates))
        deltas = np.asarray([
            team * (self._score(float(values[w, nominated]))
                    - self._score(float(values[w, 0])))
            for w in range(n_worlds)
        ])
        gap = float(np.mean(deltas)) if n_worlds else None
        se = (self._paired_se(float(np.sum(deltas)), float(np.sum(deltas * deltas)), n_worlds)
              if n_worlds else None)
        if n_worlds != self.N_DETERMINIZATIONS:
            return False, "selection-worlds-underfilled", nominated, gap, se
        if se is None or not math.isfinite(se) or se <= 0:
            return False, "paired-se-not-positive", nominated, gap, se
        triggered = abs(gap) <= self.gate_z * se
        return triggered, "within-paired-band" if triggered else "outside-paired-band", \
            nominated, gap, se

    # -------------------------------------------------------------- bounded inner
    def _rank_inner_many(self, parents, stats):
        eligible = []
        fallback = {}
        stats.setdefault("inner_eligible", 0)
        stats.setdefault("inner_skipped", 0)
        stats.setdefault("inner_raw_follow_skipped", 0)
        reasons = stats.setdefault("inner_skip_reasons", {})
        for index, parent in enumerate(parents):
            state, mover = parent["state"], parent["mover"]
            incumbent = tuple(sorted(self.rollout_policy.decide_play(state, mover)))
            reason = None
            legal = None
            if state.trick is not None and state.trick.plays:
                raw = count_multiset_subsets(
                    list(Counter(state.hands[mover]).values()),
                    len(state.trick.plays[0].cards))
                if raw > self.INNER_RAW_FOLLOW_LIMIT:
                    reason = "raw-follow-bound"
                    stats["inner_raw_follow_skipped"] += 1
            if reason is None:
                legal = enumerate_legal(
                    state, mover, cap=self.inner_legal_limit + 1,
                    must_include=[incumbent])
                if legal.count is None:
                    reason = "count-unknown"
                elif not legal.complete:
                    reason = "incomplete"
                elif legal.count > self.inner_legal_limit:
                    reason = "overlimit"
            if reason is not None:
                stats["inner_skipped"] += 1
                reasons[reason] = reasons.get(reason, 0) + 1
                stats["inner_actions"] += (0 if legal is None else len(legal.actions))
                leaf = afterstate(
                    state, mover, state.hands, state.buried, incumbent,
                    finish_trick=True, policy=self.rollout_policy)
                fallback[index] = ([incumbent], {incumbent: leaf})
                continue
            stats["inner_eligible"] += 1
            child = dict(parent)
            child["legal"] = legal
            eligible.append((index, child))

        ranked = self._rank_eligible_many([child for _, child in eligible], stats)
        result = []
        by_index = {index: row for (index, _), row in zip(eligible, ranked)}
        for index in range(len(parents)):
            result.append(fallback[index] if index in fallback else by_index[index])
        return result

    def _rank_eligible_many(self, parents, stats):
        return super()._rank_inner_many(parents, stats)

    # ------------------------------------------------------------- gate wiring
    def _lockstep_values(self, rnd, seat, worlds, candidates, *, stage,
                         sessions=None):
        self._selective_pending_outer_rollouts = 0
        sessions = list(sessions) if sessions is not None else None
        if stage == "selection":
            baseline = self._flat_matrix(
                rnd, seat, worlds, candidates, stage=stage, sessions=sessions)
            triggered, reason, nominated, gap, se = self._pilot_gate(
                rnd, seat, baseline, candidates)
            self._selective_gate = triggered
            self.last_selective_depth = {
                "schema": self.SELECTIVE_RECORD_SCHEMA,
                "gate": self.SELECTIVE_GATE, "gate_z": self.gate_z,
                "triggered": triggered, "reason": reason,
                "pilot_gap": gap, "pilot_se": se,
                "pilot_worlds": len(worlds),
                "pilot_worlds_required": self.N_DETERMINIZATIONS,
                "pilot_nominated_index": nominated,
                "pilot_nominated": (None if nominated is None else list(candidates[nominated])),
                "inner_legal_limit": self.inner_legal_limit,
                "inner_raw_follow_limit": self.INNER_RAW_FOLLOW_LIMIT,
                "inner_eligible": 0, "inner_skipped": 0,
                "inner_raw_follow_skipped": 0,
                "inner_skip_reasons": {}, "inner_rollouts": 0,
                "reused_flat_cells": 0,
                "extra_rollout_cost": 0, "stages": [],
            }
            if triggered:
                guided_worlds = min(len(worlds), self.inner_worlds)
                self.last_selective_depth["reused_flat_cells"] = max(
                    0, baseline.size - guided_worlds * len(candidates))
                values = super()._lockstep_values(
                    rnd, seat, worlds, candidates, stage=stage,
                    sessions=sessions, baseline_values=baseline)
                # The ordinary NK pilot is already charged by the selection
                # adapter.  Guided outer completions are additional work; the
                # inherited base separately accounts inner finalist rollouts.
                self._selective_pending_outer_rollouts = guided_worlds * len(candidates)
                self.rollouts += self._selective_pending_outer_rollouts
            else:
                values = baseline
                self._selective_pending_outer_rollouts = 0
                self.last_double_shortlist = None
            self._append_stage_record(stage, values, triggered)
            return values

        if stage == "report" and not self._selective_gate:
            values = self._flat_matrix(
                rnd, seat, worlds, candidates, stage=stage, sessions=sessions)
            self.last_double_shortlist = None
            self._append_stage_record(stage, values, False)
            return values
        values = super()._lockstep_values(
            rnd, seat, worlds, candidates, stage=stage, sessions=sessions)
        self._selective_pending_outer_rollouts = 0
        self._append_stage_record(stage, values, self._selective_gate)
        return values

    def _append_stage_record(self, stage, values, guided):
        detail = self.last_selective_depth
        if detail is None:
            return
        inner = self.last_double_shortlist
        row = {
            "stage": stage, "worlds": int(values.shape[0]),
            "cells": int(values.size), "guided": bool(guided),
            "inner_eligible": 0, "inner_skipped": 0,
            "inner_raw_follow_skipped": 0,
            "inner_skip_reasons": {}, "inner_rollouts": 0,
            "extra_rollout_cost": getattr(self, "_selective_pending_outer_rollouts", 0),
        }
        if guided and inner is not None:
            stage_rows = [r for r in inner.get("stages", []) if r.get("stage") == stage]
            if stage_rows:
                source = stage_rows[-1]
                row.update({key: source.get(key, row[key]) for key in (
                    "inner_eligible", "inner_skipped", "inner_raw_follow_skipped",
                    "inner_skip_reasons")})
                row["inner_rollouts"] = source.get("inner_full_rollouts", 0)
        detail["stages"].append(row)
        detail["inner_eligible"] += row["inner_eligible"]
        detail["inner_skipped"] += row["inner_skipped"]
        detail["inner_raw_follow_skipped"] += row["inner_raw_follow_skipped"]
        detail["inner_rollouts"] += row["inner_rollouts"]
        for reason, count in row["inner_skip_reasons"].items():
            detail["inner_skip_reasons"][reason] = (
                detail["inner_skip_reasons"].get(reason, 0) + count)
        detail["extra_rollout_cost"] += row["extra_rollout_cost"]
        self.selective_depth_counts[f"{stage}_calls"] += 1


__all__ = ["CWVSelectiveDepthBot"]
