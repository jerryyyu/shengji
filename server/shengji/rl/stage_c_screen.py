"""Pure whole-game screen mechanics for a future Stage-C composition packet.

This module supplies the reusable gameplay and aggregation boundary. It does
not choose seeds, paths, model artifacts, a state population, or authority;
those belong in a separately frozen and independently reviewed controller.

The screen has three arms on identical mirrored deals:

* treatment: the selected model proposes one protected challenger;
* matched null: the same model trigger buys the same per-decision report work
  but a deterministic random non-incumbent replaces the model choice;
* champion reference: live report-LCB against itself.

A positive screen must beat both the live reference and the matched null,
while the null remains statistically compatible with the reference. Every
Stage-C decision must reconcile, trigger at least once, and have zero fallback.
"""
from __future__ import annotations

import math
import random
import time
from collections import Counter
from typing import Callable, Mapping, Sequence

from ..ai.env import play_round
from ..engine.game import Game
from ..evaluation import counters, paired_by_seed
from .stage_c_composition import TELEMETRY_FIELDS, stage_c_policy_telemetry


SCHEMA = "teacher-stage-c-composition-screen-record-v1"
AGGREGATE_SCHEMA = "teacher-stage-c-composition-screen-aggregate-v1"
LABELS = ("treatment", "matched_null", "champion")


class StageCScreenError(RuntimeError):
    """The screen population, work, telemetry, or contrast drifted."""


BotFactory = Callable[[int], object]


def feature_off_telemetry() -> dict:
    return {
        "schema": "teacher-stage-c-policy-telemetry-v1",
        **{field: 0 for field in TELEMETRY_FIELDS},
        "exact_reconciliation": True,
        "strength_claim": False,
    }


def run_arm_factories(
    label: str, policy_factory: BotFactory, opponent_factory: BotFactory,
    *, clusters: int, seed0: int, run_id: str,
    policy_has_stage_c: bool,
    progress: bool = True,
    deadline_monotonic: float | None = None,
) -> list[dict]:
    """Play one mirrored arm using bound factories rather than registry names."""
    if (label not in LABELS
            or isinstance(clusters, bool) or not isinstance(clusters, int)
            or clusters <= 0
            or isinstance(seed0, bool) or not isinstance(seed0, int)
            or seed0 < 0
            or not isinstance(run_id, str) or not run_id
            or not callable(policy_factory) or not callable(opponent_factory)
            or (deadline_monotonic is not None
                and (isinstance(deadline_monotonic, bool)
                     or not isinstance(deadline_monotonic, (int, float))
                     or not math.isfinite(float(deadline_monotonic))))):
        raise StageCScreenError("Stage-C screen arm identity drift")
    if policy_has_stage_c is not (label != "champion"):
        raise StageCScreenError("Stage-C screen feature-arm identity drift")
    records = []
    for cluster in range(clusters):
        seed = seed0 + cluster
        for flip in (0, 1):
            if (deadline_monotonic is not None
                    and time.monotonic() >= deadline_monotonic):
                raise StageCScreenError(
                    "Stage-C screen shard exceeded its reviewed timeout")
            a1 = policy_factory(seed)
            a2 = policy_factory(seed + 500_000)
            b1 = opponent_factory(seed + 1_000_000)
            b2 = opponent_factory(seed + 1_500_000)
            policies = ([a1, b1, a2, b2] if flip == 0
                        else [b1, a1, b2, a2])
            log = play_round(Game(random.Random(seed)), policies)
            won = int(log.winner_team == (0 if flip == 0 else 1))
            arm_stage_c = (stage_c_policy_telemetry([a1, a2])
                           if policy_has_stage_c else feature_off_telemetry())
            record = {
                "schema": SCHEMA,
                "run": run_id,
                "label": label,
                "seed": seed,
                "flip": flip,
                "won": won,
                "level_utility": (
                    (1 if won else -1) * max(1, int(log.level_change))),
                "arm": {
                    **counters([a1, a2]),
                    "stage_c": arm_stage_c,
                },
                "opp": {
                    **counters([b1, b2]),
                    "stage_c": feature_off_telemetry(),
                },
            }
            records.append(record)
        if progress and cluster and cluster % 50 == 0:
            print(f"    {label}: {2 * cluster}/{2 * clusters} rounds",
                  flush=True)
    return records


def _telemetry_problems(value: object, *, feature_on: bool) -> list[str]:
    if not isinstance(value, dict):
        return ["Stage-C telemetry is not an object"]
    problems = []
    if (value.get("schema") != "teacher-stage-c-policy-telemetry-v1"
            or value.get("strength_claim") is not False):
        problems.append("Stage-C telemetry identity drift")
    fields = {field: value.get(field) for field in TELEMETRY_FIELDS}
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0
           for item in fields.values()):
        problems.append("Stage-C telemetry counter drift")
        return problems
    if feature_on:
        if value.get("exact_reconciliation") is not True:
            problems.append("Stage-C feature telemetry is not exact")
        if fields["fallbacks"]:
            problems.append("Stage-C feature arm used a fallback")
        if fields["focus_calls"] != (
                fields["model_keeps"] + fields["model_triggers"]):
            problems.append("Stage-C feature focus calls do not reconcile")
        if fields["model_triggers"] != (
                fields["report_overrides"] + fields["report_rejections"]
                + fields["report_underfills"]):
            problems.append("Stage-C feature triggers do not reconcile")
    elif (any(fields.values())
          or value.get("exact_reconciliation") is not True):
        problems.append("Stage-C feature-off telemetry is nonzero")
    return problems


def _counter_problems(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["search counters are not an object"]
    problems = []
    required = (
        "rollouts", "searches", "sample_attempts", "accepted_worlds",
        "failed_worlds",
        "rejected_worlds", "void_fallbacks", "short_searches", "zero_world",
    )
    values = {field: value.get(field) for field in required}
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0
           for item in values.values()):
        return ["search counter population drift"]
    if values["sample_attempts"] != (
            values["accepted_worlds"] + values["failed_worlds"]):
        problems.append("sampler attempts do not reconcile")
    if values["rejected_worlds"]:
        problems.append("constraint-correct sampler rejected a world")
    if values["void_fallbacks"]:
        problems.append("sampler used an impossible-void fallback")
    if values["short_searches"]:
        problems.append("a search underfilled its registered work")
    if values["zero_world"]:
        problems.append("a search sampled zero worlds")
    return problems


def _search_work_problems(
    counters: Mapping[str, object], telemetry: Mapping[str, object], *,
    feature_on: bool, surface: str,
) -> list[str]:
    """Recompute exact live/report work from searches and model triggers.

    Live report-LCB spends 30 common selection worlds and 300 paired report
    worlds per contested play. With K candidates this is ``30*K + 600``
    rollouts, where ``2 <= K <= 14``, and exactly 330 accepted worlds.

    A focused play trigger fixes K=2. A focused bury trigger adds one N=300
    two-candidate banker report (600 rollouts, 300 accepted worlds) while its
    later play decisions retain the ordinary live formula. These identities
    make a zero-work or partially-accounted record red instead of trusting a
    hard-coded exact-work flag.
    """
    if surface not in {"play", "bury"}:
        return ["Stage-C work surface drift"]
    searches = int(counters["searches"])
    rollouts = int(counters["rollouts"])
    accepted = int(counters["accepted_worlds"])
    triggers = int(telemetry["model_triggers"]) if feature_on else 0
    if feature_on and surface == "play":
        problems = []
        if searches != triggers:
            problems.append("focused play searches differ from model triggers")
        if accepted != 330 * triggers:
            problems.append("focused play accepted-world work drift")
        if rollouts != 660 * triggers:
            problems.append("focused play rollout work drift")
        return problems

    # Feature-off policies have only live play searches. A bury-focused policy
    # additionally has one search per model trigger, without an N=30 selection
    # fold for that bury decision.
    play_searches = searches - triggers
    problems = []
    if play_searches < 0:
        return ["bury trigger/search work drift"]
    expected_accepted = 330 * play_searches + 300 * triggers
    if accepted != expected_accepted:
        problems.append("live/bury accepted-world work drift")
    selection_rollouts = rollouts - 600 * searches
    if (selection_rollouts < 60 * play_searches
            or selection_rollouts > 420 * play_searches
            or selection_rollouts % 30):
        problems.append("live play candidate-rollout work drift")
    return problems


def _sum_stage(records: Sequence[Mapping[str, object]], side: str) -> dict:
    totals = Counter({field: 0 for field in TELEMETRY_FIELDS})
    for record in records:
        telemetry = record[side]["stage_c"]
        for field in TELEMETRY_FIELDS:
            totals[field] += telemetry[field]
    return {
        "schema": "teacher-stage-c-policy-telemetry-v1",
        **dict(totals),
        "exact_reconciliation": True,
        "strength_claim": False,
    }


def _sum_work(records: Sequence[Mapping[str, object]], side: str) -> dict:
    fields = (
        "rollouts", "searches", "sample_attempts", "accepted_worlds",
        "failed_worlds", "rejected_worlds", "void_fallbacks",
        "short_searches", "zero_world",
    )
    return {
        field: sum(int(record[side][field]) for record in records)
        for field in fields
    }


def _contrast(left: Sequence[dict], right: Sequence[dict]) -> dict:
    mean, half, n = paired_by_seed(left, right)
    return {
        "mean": mean,
        "half95": half,
        "lcb95": mean - half,
        "ucb95": mean + half,
        "clusters": n,
    }


def validate_screen_records(
    records: Mapping[str, Sequence[dict]], *, expected_seed0: int,
    expected_clusters: int, expected_surface: str,
) -> dict:
    """Validate exact population/work without returning any outcome statistic."""
    if (set(records) != set(LABELS)
            or isinstance(expected_seed0, bool)
            or not isinstance(expected_seed0, int) or expected_seed0 < 0
            or isinstance(expected_clusters, bool)
            or not isinstance(expected_clusters, int)
            or expected_clusters <= 0
            or expected_surface not in {"play", "bury"}):
        raise StageCScreenError("Stage-C screen validation identity drift")
    expected_keys = {(seed, flip)
                     for seed in range(
                         expected_seed0, expected_seed0 + expected_clusters)
                     for flip in (0, 1)}
    problems = []
    run_ids = set()
    for label in LABELS:
        rows = records[label]
        if not isinstance(rows, (list, tuple)):
            problems.append(f"{label}: records are not a sequence")
            continue
        keys = [(row.get("seed"), row.get("flip"))
                for row in rows if isinstance(row, dict)]
        if (len(rows) != len(expected_keys)
                or len(keys) != len(rows)
                or len(keys) != len(set(keys))
                or set(keys) != expected_keys):
            problems.append(f"{label}: seed/flip population drift")
        for row in rows:
            if not isinstance(row, dict):
                continue
            run_ids.add(row.get("run"))
            if (row.get("schema") != SCHEMA or row.get("label") != label
                    or row.get("won") not in {0, 1}
                    or isinstance(row.get("level_utility"), bool)
                    or not isinstance(row.get("level_utility"), int)
                    or row.get("level_utility") == 0
                    or ((row.get("level_utility") > 0)
                        is not bool(row.get("won")))):
                problems.append(f"{label}: record identity/value drift")
                continue
            for side in ("arm", "opp"):
                side_value = row.get(side)
                structural = _counter_problems(side_value)
                problems.extend(
                    f"{label}/{side}: {problem}"
                    for problem in structural)
                telemetry = (side_value.get("stage_c")
                             if isinstance(side_value, dict) else None)
                feature_on = label != "champion" and side == "arm"
                telemetry_structural = _telemetry_problems(
                    telemetry, feature_on=feature_on)
                problems.extend(
                    f"{label}/{side}: {problem}"
                    for problem in telemetry_structural)
                if isinstance(side_value, dict) and isinstance(telemetry, dict):
                    if not structural and not telemetry_structural:
                        problems.extend(
                            f"{label}/{side}: {problem}"
                            for problem in _search_work_problems(
                                side_value, telemetry,
                                feature_on=feature_on,
                                surface=expected_surface))
    if len(run_ids) != 1 or not all(isinstance(value, str) and value
                                    for value in run_ids):
        problems.append("Stage-C screen run identity drift")
    if problems:
        raise StageCScreenError(
            "Stage-C screen records refused:\n  - " + "\n  - ".join(problems))

    return {
        "run_id": next(iter(run_ids)),
        "surface": expected_surface,
        "seed0": expected_seed0,
        "clusters": expected_clusters,
        "record_counts": {
            label: len(records[label]) for label in LABELS},
        "stage_c_telemetry": {
            "treatment": _sum_stage(records["treatment"], "arm"),
            "matched_null": _sum_stage(records["matched_null"], "arm"),
        },
        "work_totals": {
            label: {
                side: _sum_work(records[label], side)
                for side in ("arm", "opp")
            } for label in LABELS
        },
        "all_records_exact_work": True,
    }


def aggregate_screen(
    records: Mapping[str, Sequence[dict]], *, expected_seed0: int,
    expected_clusters: int, expected_surface: str,
) -> dict:
    """Validate and gate one frozen three-arm whole-game screen population."""
    if (isinstance(expected_clusters, bool)
            or not isinstance(expected_clusters, int)
            or expected_clusters < 30):
        raise StageCScreenError("Stage-C screen aggregate identity drift")
    validation = validate_screen_records(
        records, expected_seed0=expected_seed0,
        expected_clusters=expected_clusters,
        expected_surface=expected_surface)

    treatment_stage = validation["stage_c_telemetry"]["treatment"]
    null_stage = validation["stage_c_telemetry"]["matched_null"]
    stats = {
        "treatment_champion": _contrast(
            records["treatment"], records["champion"]),
        "treatment_matched_null": _contrast(
            records["treatment"], records["matched_null"]),
        "matched_null_champion": _contrast(
            records["matched_null"], records["champion"]),
    }
    null_stat = stats["matched_null_champion"]
    criteria = {
        "treatment_champion_lcb_gt_zero": (
            stats["treatment_champion"]["lcb95"] > 0),
        "treatment_matched_null_lcb_gt_zero": (
            stats["treatment_matched_null"]["lcb95"] > 0),
        "matched_null_champion_interval_contains_zero": (
            null_stat["lcb95"] <= 0 <= null_stat["ucb95"]),
        "treatment_triggered": treatment_stage["model_triggers"] > 0,
        "matched_null_triggered": null_stage["model_triggers"] > 0,
        "treatment_zero_fallback": treatment_stage["fallbacks"] == 0,
        "matched_null_zero_fallback": null_stage["fallbacks"] == 0,
        "all_records_exact_work": validation["all_records_exact_work"],
    }
    criteria["all"] = all(criteria.values())
    return {
        "schema": AGGREGATE_SCHEMA,
        "complete": True,
        "run_id": validation["run_id"],
        "surface": expected_surface,
        "seed0": expected_seed0,
        "clusters": expected_clusters,
        "stats": stats,
        "stage_c_telemetry": {
            "treatment": treatment_stage,
            "matched_null": null_stage,
        },
        "work_totals": validation["work_totals"],
        "criteria": criteria,
        "status": ("AUTHORIZE_CONFIRM_PACKET_REVIEW" if criteria["all"]
                   else "SELECT_NONE"),
        "strength_claim": False,
        "retry_or_extension_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
