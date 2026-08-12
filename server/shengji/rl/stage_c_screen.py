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
from ..evaluation import counters
from .stage_c_composition import TELEMETRY_FIELDS, stage_c_policy_telemetry


SCHEMA = "teacher-stage-c-composition-screen-record-v1"
AGGREGATE_SCHEMA = "teacher-stage-c-composition-screen-aggregate-v1"
LABELS = ("treatment", "matched_null", "champion")
ONE_SIDED_CRITICAL = 1.645
TWO_SIDED_CRITICAL = 1.96
MAX_ATTACKER_POINTS = 4_120
MAX_LEVEL_CHANGE = 101


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
            policy_team = 0 if flip == 0 else 1
            won = int(log.winner_team == policy_team)
            arm_stage_c = (stage_c_policy_telemetry([a1, a2])
                           if policy_has_stage_c else feature_off_telemetry())
            record = {
                "schema": SCHEMA,
                "run": run_id,
                "label": label,
                "seed": seed,
                "flip": flip,
                "banker": int(log.banker),
                "attacker_points": int(log.attacker_points),
                "winner_team": int(log.winner_team),
                "level_change": int(log.level_change),
                "policy_role": (
                    "defender" if int(log.banker) % 2 == policy_team
                    else "attacker"),
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
                fields["scope_checks"]):
            problems.append("Stage-C feature focus calls do not reconcile")
        if fields["scope_checks"] != (
                fields["scope_eligible"] + fields["scope_ineligible"]):
            problems.append("Stage-C scope checks do not reconcile")
        if fields["scope_eligible"] != (
                fields["model_keeps"] + fields["model_triggers"]):
            problems.append("Stage-C eligible scope does not reconcile")
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
    worlds per contested play. The protected play wrapper keeps that complete
    live search, adds one N=30 public scope diagnostic over 2..20 candidates,
    and on a model trigger adds one fresh N=300 two-action report. A focused
    bury trigger retains its older one-report geometry. These identities make
    hidden or partially-accounted work red instead of trusting a boolean.
    """
    if surface not in {"play", "bury"}:
        return ["Stage-C work surface drift"]
    searches = int(counters["searches"])
    rollouts = int(counters["rollouts"])
    accepted = int(counters["accepted_worlds"])
    triggers = int(telemetry["model_triggers"]) if feature_on else 0
    if feature_on and surface == "play":
        scope_checks = int(telemetry["scope_checks"])
        scope_rollouts = int(telemetry["scope_candidate_rollouts"])
        problems = []
        if (scope_rollouts < 60 * scope_checks
                or scope_rollouts > 600 * scope_checks
                or scope_rollouts % 30):
            problems.append("uncertainty-scope candidate work drift")
        live_searches = searches - scope_checks - triggers
        if live_searches < 0:
            problems.append("protected play search decomposition drift")
            return problems
        expected_accepted = (
            330 * live_searches + 30 * scope_checks + 300 * triggers)
        if accepted != expected_accepted:
            problems.append("protected play accepted-world work drift")
        live_selection_rollouts = (
            rollouts - scope_rollouts
            - 600 * live_searches - 600 * triggers)
        if (live_selection_rollouts < 60 * live_searches
                or live_selection_rollouts > 420 * live_searches
                or live_selection_rollouts % 30):
            problems.append("protected live selection work drift")
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


def _expected_round_outcome(*, banker: object,
                            attacker_points: object) -> tuple[int, int]:
    if (isinstance(banker, bool) or not isinstance(banker, int)
            or not 0 <= banker < 4):
        raise StageCScreenError("screen banker identity drift")
    if (isinstance(attacker_points, bool)
            or not isinstance(attacker_points, int)
            or not 0 <= attacker_points <= MAX_ATTACKER_POINTS
            or attacker_points % 5):
        raise StageCScreenError("screen attacker-points geometry drift")
    banker_team = banker % 2
    if attacker_points >= 80:
        return 1 - banker_team, (attacker_points - 80) // 40
    return banker_team, (3 if attacker_points == 0
                         else 2 if attacker_points < 40 else 1)


def _per_seed_values(records: Sequence[dict], field: str, *,
                     scale: float = 1.0,
                     allowed_keys: set[tuple[int, int]] | None = None,
                     require_two_flips: bool = True,
                     average_selected: bool = False,
                     ) -> dict[int, float]:
    values: dict[int, float] = {}
    counts: Counter[int] = Counter()
    for record in records:
        key = (int(record["seed"]), int(record["flip"]))
        if allowed_keys is not None and key not in allowed_keys:
            continue
        values[key[0]] = values.get(key[0], 0.0) + float(record[field]) * scale
        counts[key[0]] += 1
    if require_two_flips and any(count != 2 for count in counts.values()):
        raise StageCScreenError("paired diagnostic seed geometry drift")
    if not require_two_flips and any(count not in {1, 2}
                                     for count in counts.values()):
        raise StageCScreenError("stratified diagnostic seed geometry drift")
    if average_selected:
        values = {seed: value / counts[seed]
                  for seed, value in values.items()}
    return values


def _paired_summary(
    left: Sequence[dict], right: Sequence[dict], *, field: str,
    scale: float = 1.0, two_sided: bool = False,
    allowed_keys: set[tuple[int, int]] | None = None,
) -> dict:
    stratified = allowed_keys is not None
    left_by = _per_seed_values(
        left, field, scale=scale, allowed_keys=allowed_keys,
        require_two_flips=not stratified, average_selected=stratified)
    right_by = _per_seed_values(
        right, field, scale=scale, allowed_keys=allowed_keys,
        require_two_flips=not stratified, average_selected=stratified)
    if set(left_by) != set(right_by):
        raise StageCScreenError("paired diagnostic population drift")
    deltas = [left_by[seed] - right_by[seed] for seed in sorted(left_by)]
    n = len(deltas)
    if not deltas:
        return {
            "mean": None, "standard_error": None, "critical": None,
            "lcb95": None, "ucb95": None, "clusters": 0,
            "bound": "not estimable: empty stratum",
        }
    mean = sum(deltas) / n
    if n < 2:
        standard_error = float("inf")
    else:
        variance = sum((value - mean) ** 2 for value in deltas) / (n - 1)
        standard_error = math.sqrt(variance / n)
    critical = TWO_SIDED_CRITICAL if two_sided else ONE_SIDED_CRITICAL
    margin = critical * standard_error
    return {
        "mean": mean,
        "standard_error": standard_error,
        "critical": critical,
        "lcb95": mean - margin,
        "ucb95": mean + margin,
        "clusters": n,
        "bound": ("paired-seed two-sided 95%" if two_sided
                  else "paired-seed one-sided 95% lower bound"),
    }


def _contrast(left: Sequence[dict], right: Sequence[dict], *,
              two_sided: bool = False) -> dict:
    return _paired_summary(
        left, right, field="level_utility", two_sided=two_sided)


def _arm_win_rate(records: Sequence[dict]) -> dict:
    values = list(_per_seed_values(records, "won", scale=0.5).values())
    if not values:
        raise StageCScreenError("empty arm win-rate population")
    mean = sum(values) / len(values)
    variance = (sum((value - mean) ** 2 for value in values)
                / max(len(values) - 1, 1))
    se = math.sqrt(variance / len(values))
    margin = TWO_SIDED_CRITICAL * se
    return {
        "mean": mean, "standard_error": se,
        "lower95": mean - margin, "upper95": mean + margin,
        "clusters": len(values), "bound": "clustered two-sided 95%",
    }


def _level_change_tails(records: Sequence[dict]) -> dict:
    result = Counter()
    for record in records:
        outcome = "win" if record["won"] else "loss"
        level_change = int(record["level_change"])
        band = "0_or_1" if level_change <= 1 else (
            "2" if level_change == 2 else "3_plus")
        result[f"{outcome}:{band}"] += 1
    return {key: result[key] for key in (
        "win:0_or_1", "win:2", "win:3_plus",
        "loss:0_or_1", "loss:2", "loss:3_plus")}


def _screen_diagnostics(records: Mapping[str, Sequence[dict]]) -> dict:
    champion_roles = {role: {
        (int(record["seed"]), int(record["flip"]))
        for record in records["champion"] if record["policy_role"] == role
    } for role in ("attacker", "defender")}
    return {
        "round_win_rate": {
            "arms": {label: _arm_win_rate(records[label]) for label in LABELS},
            "paired": {
                "treatment_champion": _paired_summary(
                    records["treatment"], records["champion"],
                    field="won", scale=0.5, two_sided=True),
                "treatment_matched_null": _paired_summary(
                    records["treatment"], records["matched_null"],
                    field="won", scale=0.5, two_sided=True),
                "matched_null_champion": _paired_summary(
                    records["matched_null"], records["champion"],
                    field="won", scale=0.5, two_sided=True),
            },
        },
        "champion_reference_role_utility": {
            role: {
                "treatment_champion": _paired_summary(
                    records["treatment"], records["champion"],
                    field="level_utility", two_sided=True,
                    allowed_keys=keys),
                "treatment_matched_null": _paired_summary(
                    records["treatment"], records["matched_null"],
                    field="level_utility", two_sided=True,
                    allowed_keys=keys),
            } for role, keys in champion_roles.items()
        },
        "level_change_tails": {
            label: _level_change_tails(records[label]) for label in LABELS},
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
            try:
                winner, level_change = _expected_round_outcome(
                    banker=row.get("banker"),
                    attacker_points=row.get("attacker_points"))
            except StageCScreenError as exc:
                problems.append(f"{label}: {exc}")
                continue
            policy_team = 0 if row.get("flip") == 0 else 1
            expected_won = int(winner == policy_team)
            expected_utility = ((1 if expected_won else -1)
                                * max(1, level_change))
            expected_role = ("defender" if int(row["banker"]) % 2
                             == policy_team else "attacker")
            if (row.get("winner_team") != winner
                    or row.get("level_change") != level_change
                    or row.get("won") != expected_won
                    or row.get("level_utility") != expected_utility
                    or row.get("policy_role") != expected_role):
                problems.append(f"{label}: record outcome derivation drift")
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
            records["matched_null"], records["champion"], two_sided=True),
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
    positive_but_unresolved = (
        stats["treatment_champion"]["mean"] > 0
        and stats["treatment_matched_null"]["mean"] > 0
        and not criteria["all"])
    status = ("AUTHORIZE_CONFIRM_PACKET_REVIEW" if criteria["all"]
              else "POSITIVE_BUT_UNRESOLVED"
              if positive_but_unresolved else "SELECT_NONE")
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
        "diagnostics": _screen_diagnostics(records),
        "criteria": criteria,
        "status": status,
        "exploration_interpretation": (
            "positive point estimates without a passed strength gate; "
            "preserve for mechanism diagnosis, but do not claim strength or "
            "extend this spent population"
            if positive_but_unresolved else
            "registered strength screen passed"
            if criteria["all"] else
            "at least one treatment contrast was non-positive or a structural "
            "gate failed"),
        "strength_claim": False,
        "retry_or_extension_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
