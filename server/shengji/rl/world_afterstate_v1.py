"""Action-relative Value-Afterstate V1 label-ceiling mechanics.

V0 predicted absolute terminal outcomes.  V1 first asks a cheaper causal
question: do sibling actions have continuation advantages that reproduce from
one common-random-number replicate to another?  This module derives those
pairs from already-authenticated V0 evaluation rows and evaluates that ceiling.

It has no filesystem, dataset-opening, training, report, gameplay, merge,
strength, promotion, deployment, retry, or R5 authority.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_evaluation import EvaluationOutcomeV0


PAIR_SCHEMA = "world-afterstate-advantage-pair-v1"
LABEL_CEILING_SCHEMA = "world-afterstate-v1-label-ceiling-v0"
BOOTSTRAP_REPLICATES = 10_000
REPLICATES = (0, 1)
MINIMUM_SELECTION_DOSE_PPM = 50_000
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_authorized": False,
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1Error(ValueError):
    """A sibling identity, paired label, census, or P0 gate drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1Error(f"{label} drift")
    return value


def _strict_int(value: object, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or minimum is not None and value < minimum:
        raise WorldAfterstateV1Error(f"{label} drift")
    return value


@dataclass(frozen=True)
class AdvantagePairV1:
    deal_group_sha256: str
    state_group_id: str
    source: str
    fold: str
    root_role: str
    play_phase: str
    position: str
    trump_rank: str
    trump_mode: str
    points_bucket: str
    candidate_index: int
    replicate: int
    incumbent_successor_sha256: str
    candidate_successor_sha256: str
    incumbent_signed_level_category: int
    candidate_signed_level_category: int
    advantage_levels: int
    schema: str = PAIR_SCHEMA

    def validate(self) -> None:
        for label, value in (
                ("pair deal-group SHA-256", self.deal_group_sha256),
                ("pair state-group id", self.state_group_id),
                ("pair incumbent successor SHA-256",
                 self.incumbent_successor_sha256),
                ("pair candidate successor SHA-256",
                 self.candidate_successor_sha256)):
            _digest(value, label)
        if self.schema != PAIR_SCHEMA \
                or self.fold not in ("train", "calibration") \
                or any(type(value) is not str or not value for value in (
                    self.source, self.root_role, self.play_phase, self.position,
                    self.trump_rank, self.trump_mode, self.points_bucket)):
            raise WorldAfterstateV1Error("advantage pair identity drift")
        _strict_int(self.candidate_index, "pair candidate index", minimum=1)
        _strict_int(self.replicate, "pair replicate", minimum=0)
        incumbent = _strict_int(
            self.incumbent_signed_level_category,
            "pair incumbent category", minimum=0)
        candidate = _strict_int(
            self.candidate_signed_level_category,
            "pair candidate category", minimum=0)
        if incumbent >= 204 or candidate >= 204 \
                or self.advantage_levels != candidate - incumbent \
                or not -203 <= self.advantage_levels <= 203:
            raise WorldAfterstateV1Error("advantage pair label drift")

    def key(self) -> tuple[str, int, int]:
        self.validate()
        return (self.state_group_id, self.candidate_index, self.replicate)

    def state_identity(self) -> tuple[Any, ...]:
        self.validate()
        return (
            self.deal_group_sha256, self.source, self.fold, self.root_role,
            self.play_phase, self.position, self.trump_rank, self.trump_mode,
            self.points_bucket, self.incumbent_successor_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "deal_group_sha256": self.deal_group_sha256,
            "state_group_id": self.state_group_id,
            "source": self.source,
            "fold": self.fold,
            "root_role": self.root_role,
            "play_phase": self.play_phase,
            "position": self.position,
            "trump_rank": self.trump_rank,
            "trump_mode": self.trump_mode,
            "points_bucket": self.points_bucket,
            "candidate_index": self.candidate_index,
            "replicate": self.replicate,
            "incumbent_successor_sha256": self.incumbent_successor_sha256,
            "candidate_successor_sha256": self.candidate_successor_sha256,
            "incumbent_signed_level_category": (
                self.incumbent_signed_level_category),
            "candidate_signed_level_category": (
                self.candidate_signed_level_category),
            "advantage_levels": self.advantage_levels,
        }


def build_advantage_pairs(
        outcomes: Sequence[EvaluationOutcomeV0], *,
        allowed_folds: Sequence[str] = ("train", "calibration")) \
        -> tuple[AdvantagePairV1, ...]:
    """Derive candidate-minus-incumbent labels from exact sibling rows."""
    if type(outcomes) not in (list, tuple) or not outcomes \
            or type(allowed_folds) not in (list, tuple) \
            or not allowed_folds \
            or len(set(allowed_folds)) != len(allowed_folds) \
            or any(fold not in ("train", "calibration")
                   for fold in allowed_folds):
        raise WorldAfterstateV1Error("advantage population request drift")
    groups: dict[str, dict[int, dict[int, EvaluationOutcomeV0]]] = defaultdict(
        lambda: defaultdict(dict))
    for outcome in outcomes:
        if type(outcome) is not EvaluationOutcomeV0:
            raise WorldAfterstateV1Error("advantage outcome type drift")
        outcome.validate()
        if outcome.fold not in allowed_folds:
            raise WorldAfterstateV1Error("advantage outcome split drift")
        rows = groups[outcome.state_group_id][outcome.candidate_index]
        if outcome.replicate in rows:
            raise WorldAfterstateV1Error("duplicate advantage outcome")
        rows[outcome.replicate] = outcome

    result = []
    for state_group_id in sorted(groups):
        candidates = groups[state_group_id]
        indexes = sorted(candidates)
        if indexes != list(range(len(indexes))) or len(indexes) < 2:
            raise WorldAfterstateV1Error(
                "advantage sibling candidate population drift")
        if any(set(candidates[index]) != set(REPLICATES)
               for index in indexes):
            raise WorldAfterstateV1Error(
                "advantage sibling replicate population drift")
        incumbent_rows = candidates[0]
        incumbent_identity = None
        for replicate in REPLICATES:
            incumbent = incumbent_rows[replicate]
            identity = (
                incumbent.deal_group_sha256, incumbent.source, incumbent.fold,
                incumbent.stratum(), incumbent.successor_sha256)
            if incumbent_identity is None:
                incumbent_identity = identity
            elif identity != incumbent_identity:
                raise WorldAfterstateV1Error(
                    "advantage incumbent replicate binding drift")
            if incumbent.protected_incumbent is not True:
                raise WorldAfterstateV1Error(
                    "advantage protected incumbent drift")
        if incumbent_identity is None:
            raise WorldAfterstateV1Error(
                "advantage incumbent population is empty")
        for candidate_index in indexes[1:]:
            candidate_successor = None
            for replicate in REPLICATES:
                incumbent = incumbent_rows[replicate]
                candidate = candidates[candidate_index][replicate]
                candidate_identity = (
                    candidate.deal_group_sha256, candidate.source,
                    candidate.fold, candidate.stratum())
                if candidate_identity != incumbent_identity[:4] \
                        or candidate.protected_incumbent is not False:
                    raise WorldAfterstateV1Error(
                        "advantage cross-candidate binding drift")
                if candidate_successor is None:
                    candidate_successor = candidate.successor_sha256
                elif candidate.successor_sha256 != candidate_successor:
                    raise WorldAfterstateV1Error(
                        "advantage candidate replicate binding drift")
                pair = AdvantagePairV1(
                    deal_group_sha256=candidate.deal_group_sha256,
                    state_group_id=state_group_id,
                    source=candidate.source, fold=candidate.fold,
                    root_role=candidate.root_role,
                    play_phase=candidate.play_phase,
                    position=candidate.position,
                    trump_rank=candidate.trump_rank,
                    trump_mode=candidate.trump_mode,
                    points_bucket=candidate.points_bucket,
                    candidate_index=candidate_index, replicate=replicate,
                    incumbent_successor_sha256=incumbent.successor_sha256,
                    candidate_successor_sha256=candidate.successor_sha256,
                    incumbent_signed_level_category=(
                        incumbent.signed_level_category),
                    candidate_signed_level_category=(
                        candidate.signed_level_category),
                    advantage_levels=(candidate.signed_level_category
                                      - incumbent.signed_level_category))
                pair.validate()
                result.append(pair)
    keys = [pair.key() for pair in result]
    if len(keys) != len(set(keys)):
        raise WorldAfterstateV1Error("duplicate advantage pair")
    return tuple(sorted(result, key=lambda pair: pair.key()))


def _census(states: Mapping[str, Sequence[AdvantagePairV1]]) \
        -> dict[str, list[list[Any]]]:
    axes = {
        "source": Counter(),
        "fold": Counter(),
        "root_role": Counter(),
        "play_phase": Counter(),
        "position": Counter(),
        "trump_rank": Counter(),
        "trump_mode": Counter(),
        "points_bucket": Counter(),
    }
    for rows in states.values():
        first = rows[0]
        for axis in axes:
            axes[axis][getattr(first, axis)] += 1
    return {
        axis: [[key, counts[key]] for key in sorted(counts)]
        for axis, counts in sorted(axes.items())
    }


def _correlation_ppm(xs: Sequence[int], ys: Sequence[int]) -> int:
    if len(xs) != len(ys) or not xs:
        raise WorldAfterstateV1Error("advantage correlation population drift")
    count = len(xs)
    numerator = count * sum(x * y for x, y in zip(xs, ys, strict=True)) \
        - sum(xs) * sum(ys)
    left = count * sum(value * value for value in xs) - sum(xs) ** 2
    right = count * sum(value * value for value in ys) - sum(ys) ** 2
    if left < 0 or right < 0:
        raise WorldAfterstateV1Error("advantage correlation arithmetic drift")
    denominator = math.isqrt(left * right)
    if denominator == 0:
        return 0
    magnitude = abs(numerator) * 1_000_000 // denominator
    return max(-1_000_000, min(1_000_000,
                               magnitude if numerator >= 0 else -magnitude))


def _bootstrap_interval(
        deal_values: Mapping[str, tuple[int, int]], *,
        replicates: int) -> tuple[int, int, int]:
    if not deal_values or isinstance(replicates, bool) \
            or not isinstance(replicates, int) or replicates < 100:
        raise WorldAfterstateV1Error("label-ceiling bootstrap request drift")
    deals = sorted(deal_values)
    rng = random.Random(int.from_bytes(hashlib.sha256(
        b"world-afterstate-v1-p0-label-ceiling").digest()[:16], "big"))
    samples = []
    for _ in range(replicates):
        numerator = 0
        denominator = 0
        for _ in deals:
            value, count = deal_values[deals[rng.randrange(len(deals))]]
            numerator += value
            denominator += count
        samples.append(numerator * 1_000_000 // denominator)
    samples.sort()
    mean = sum(value for value, _ in deal_values.values()) * 1_000_000 \
        // sum(count for _, count in deal_values.values())
    return (mean, samples[(replicates * 5) // 100],
            samples[(replicates * 95) // 100])


def evaluate_label_ceiling(
        pairs: Sequence[AdvantagePairV1], *,
        bootstrap_replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    """Cross-fit sibling actions across the two frozen V0 repetitions."""
    if type(pairs) not in (list, tuple) or not pairs:
        raise WorldAfterstateV1Error("label-ceiling pair population drift")
    by_state: dict[str, list[AdvantagePairV1]] = defaultdict(list)
    seen = set()
    for pair in pairs:
        if type(pair) is not AdvantagePairV1:
            raise WorldAfterstateV1Error("label-ceiling pair type drift")
        key = pair.key()
        if key in seen:
            raise WorldAfterstateV1Error("duplicate label-ceiling pair")
        seen.add(key)
        by_state[pair.state_group_id].append(pair)

    direction_totals = {"0-to-1": [0, 0], "1-to-0": [0, 0]}
    deal_values: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    selected_nonincumbent = 0
    advantage_xs = []
    advantage_ys = []
    nonzero_pairs = 0
    for state_group_id in sorted(by_state):
        rows = sorted(by_state[state_group_id], key=lambda row: row.key())
        identities = {row.state_identity() for row in rows}
        if len(identities) != 1:
            raise WorldAfterstateV1Error(
                "label-ceiling state identity drift")
        candidates = sorted({row.candidate_index for row in rows})
        if candidates != list(range(1, max(candidates) + 1)):
            raise WorldAfterstateV1Error(
                "label-ceiling candidate population drift")
        values = {(row.candidate_index, row.replicate): row.advantage_levels
                  for row in rows}
        if set(values) != {(candidate, replicate)
                           for candidate in candidates
                           for replicate in REPLICATES}:
            raise WorldAfterstateV1Error(
                "label-ceiling replicate population drift")
        for candidate in candidates:
            candidate_rows = [
                row for row in rows if row.candidate_index == candidate]
            if len({row.candidate_successor_sha256
                    for row in candidate_rows}) != 1:
                raise WorldAfterstateV1Error(
                    "label-ceiling candidate successor binding drift")
            x = values[(candidate, 0)]
            y = values[(candidate, 1)]
            advantage_xs.append(x)
            advantage_ys.append(y)
            nonzero_pairs += int(x != 0 or y != 0)
        deal = rows[0].deal_group_sha256
        for selection_replicate, truth_replicate, name in (
                (0, 1, "0-to-1"), (1, 0, "1-to-0")):
            choices = {0: 0, **{
                candidate: values[(candidate, selection_replicate)]
                for candidate in candidates}}
            selected = max(choices, key=lambda index: (choices[index], -index))
            improvement = 0 if selected == 0 \
                else values[(selected, truth_replicate)]
            direction_totals[name][0] += improvement
            direction_totals[name][1] += 1
            deal_values[deal][0] += improvement
            deal_values[deal][1] += 1
            selected_nonincumbent += int(selected != 0)

    state_count = len(by_state)
    pair_candidate_count = len(advantage_xs)
    if state_count <= 0 or pair_candidate_count <= 0:
        raise WorldAfterstateV1Error("label-ceiling population is empty")
    direction_means = {
        name: total * 1_000_000 // count
        for name, (total, count) in direction_totals.items()
    }
    combined = _bootstrap_interval(
        {key: tuple(value) for key, value in deal_values.items()},
        replicates=bootstrap_replicates)
    selection_opportunities = state_count * len(REPLICATES)
    selection_dose = selected_nonincumbent * 1_000_000 \
        // selection_opportunities
    sign_agreement = sum(
        ((x > 0) - (x < 0)) == ((y > 0) - (y < 0))
        for x, y in zip(advantage_xs, advantage_ys, strict=True))
    passed = (
        direction_means["0-to-1"] > 0
        and direction_means["1-to-0"] > 0
        and combined[1] > 0
        and selection_dose >= MINIMUM_SELECTION_DOSE_PPM
    )
    pair_population_sha256 = _sha([
        pair.to_dict() for pair in sorted(pairs, key=lambda row: row.key())])
    body = {
        "schema": LABEL_CEILING_SCHEMA,
        "pair_population_sha256": pair_population_sha256,
        "eligible_state_count": state_count,
        "deal_count": len(deal_values),
        "candidate_pair_count": pair_candidate_count,
        "raw_pair_row_count": len(pairs),
        "nonzero_candidate_pair_count": nonzero_pairs,
        "replicate_advantage_correlation_ppm": _correlation_ppm(
            advantage_xs, advantage_ys),
        "replicate_sign_agreement_ppm": (
            sign_agreement * 1_000_000 // pair_candidate_count),
        "crossfit_direction_mean_microlevels": direction_means,
        "combined_crossfit_microlevels": {
            "mean": combined[0],
            "bootstrap_lower": combined[1],
            "bootstrap_upper": combined[2],
        },
        "selected_nonincumbent_count": selected_nonincumbent,
        "selection_opportunity_count": selection_opportunities,
        "selection_dose_ppm": selection_dose,
        "minimum_selection_dose_ppm": MINIMUM_SELECTION_DOSE_PPM,
        "bootstrap_replicates": bootstrap_replicates,
        "state_census": _census(by_state),
        "passed": passed,
        "authority": dict(AUTHORITY),
    }
    result = {**body, "result_sha256": _sha(body)}
    validate_label_ceiling(result)
    return result


def validate_label_ceiling(value: Mapping[str, Any]) -> None:
    required = {
        "schema", "pair_population_sha256", "eligible_state_count",
        "deal_count", "candidate_pair_count", "raw_pair_row_count",
        "nonzero_candidate_pair_count",
        "replicate_advantage_correlation_ppm",
        "replicate_sign_agreement_ppm",
        "crossfit_direction_mean_microlevels",
        "combined_crossfit_microlevels", "selected_nonincumbent_count",
        "selection_opportunity_count", "selection_dose_ppm",
        "minimum_selection_dose_ppm", "bootstrap_replicates",
        "state_census", "passed", "authority", "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != LABEL_CEILING_SCHEMA \
            or value.get("authority") != AUTHORITY \
            or type(value.get("passed")) is not bool:
        raise WorldAfterstateV1Error("label-ceiling result schema drift")
    _digest(value["pair_population_sha256"],
            "label-ceiling pair population SHA-256")
    for key in (
            "eligible_state_count", "deal_count", "candidate_pair_count",
            "raw_pair_row_count", "nonzero_candidate_pair_count",
            "replicate_advantage_correlation_ppm",
            "replicate_sign_agreement_ppm", "selected_nonincumbent_count",
            "selection_opportunity_count", "selection_dose_ppm",
            "minimum_selection_dose_ppm", "bootstrap_replicates"):
        _strict_int(value.get(key), f"label-ceiling {key}")
    if value["eligible_state_count"] <= 0 or value["deal_count"] <= 0 \
            or value["candidate_pair_count"] <= 0 \
            or value["raw_pair_row_count"] \
            != value["candidate_pair_count"] * len(REPLICATES) \
            or not 0 <= value["nonzero_candidate_pair_count"] \
            <= value["candidate_pair_count"] \
            or not -1_000_000 \
            <= value["replicate_advantage_correlation_ppm"] <= 1_000_000 \
            or not 0 <= value["replicate_sign_agreement_ppm"] <= 1_000_000 \
            or value["selection_opportunity_count"] \
            != value["eligible_state_count"] * len(REPLICATES) \
            or not 0 <= value["selected_nonincumbent_count"] \
            <= value["selection_opportunity_count"] \
            or value["selection_dose_ppm"] \
            != value["selected_nonincumbent_count"] * 1_000_000 \
            // value["selection_opportunity_count"] \
            or value["minimum_selection_dose_ppm"] \
            != MINIMUM_SELECTION_DOSE_PPM \
            or value["bootstrap_replicates"] < 100:
        raise WorldAfterstateV1Error("label-ceiling count drift")
    directions = value["crossfit_direction_mean_microlevels"]
    combined = value["combined_crossfit_microlevels"]
    expected_census_axes = {
        "source", "fold", "root_role", "play_phase", "position",
        "trump_rank", "trump_mode", "points_bucket",
    }
    census = value["state_census"]
    if type(directions) is not dict or set(directions) != {
            "0-to-1", "1-to-0"} \
            or any(type(item) is not int for item in directions.values()) \
            or type(combined) is not dict or set(combined) != {
                "mean", "bootstrap_lower", "bootstrap_upper"} \
            or any(type(item) is not int for item in combined.values()) \
            or type(census) is not dict or set(census) != expected_census_axes:
        raise WorldAfterstateV1Error("label-ceiling metric drift")
    for rows in census.values():
        if type(rows) is not list or not rows \
                or any(type(row) is not list or len(row) != 2
                       or type(row[0]) is not str or not row[0]
                       or isinstance(row[1], bool) or not isinstance(row[1], int)
                       or row[1] <= 0 for row in rows) \
                or [row[0] for row in rows] != sorted(row[0] for row in rows) \
                or len({row[0] for row in rows}) != len(rows) \
                or sum(row[1] for row in rows) \
                != value["eligible_state_count"]:
            raise WorldAfterstateV1Error("label-ceiling census drift")
    expected_pass = (
        directions["0-to-1"] > 0
        and directions["1-to-0"] > 0
        and combined["bootstrap_lower"] > 0
        and value["selection_dose_ppm"] >= MINIMUM_SELECTION_DOSE_PPM
    )
    if value["passed"] is not expected_pass:
        raise WorldAfterstateV1Error("label-ceiling gate drift")
    body = {key: item for key, item in value.items()
            if key != "result_sha256"}
    if value["result_sha256"] != _sha(body):
        raise WorldAfterstateV1Error(
            "label-ceiling result reconstruction drift")


__all__ = [
    "AUTHORITY", "BOOTSTRAP_REPLICATES", "LABEL_CEILING_SCHEMA",
    "MINIMUM_SELECTION_DOSE_PPM", "PAIR_SCHEMA", "REPLICATES",
    "AdvantagePairV1", "WorldAfterstateV1Error", "build_advantage_pairs",
    "evaluate_label_ceiling", "validate_label_ceiling",
]
