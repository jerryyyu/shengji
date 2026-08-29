"""Precision label-ceiling mechanics for absolute Value-Afterstate V2.

This module deliberately consumes only sealed :class:`ContinuationOutcomeV2`
rows bound to the preregistered P0 slot ledger.  It does not open audits, run
the engine, select states, or authorize any downstream action.  All estimands
are computed in half-level ``Fraction`` arithmetic; integer microlevels are
used at the report boundary.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import category_signed_level
from .world_afterstate_v2_protocol import (
    P0_CELLS, PopulationSlotV2, STATE_SOURCES, TierSpecV2,
    select_p0_population,
)


LABEL_SCHEMA = "world-afterstate-v2-p0-precision-label-v0"
OUTCOME_SCHEMA = "world-afterstate-v2-continuation-outcome-v1"
MECHANICS_EVIDENCE_SCHEMA = "world-afterstate-v2-p0-mechanics-evidence-v1"
MECHANICS_SURFACES = (
    "transition", "continuation", "perspective", "symmetry")
BOOTSTRAP_REPLICATES = 10_000
REPLICATES = tuple(range(8))
HALVES = ((0, 1, 2, 3), (4, 5, 6, 7))
P0_DEALS = 96
P0_PER_CELL = 8
STATISTICAL_STOP = "STOP_NO_REPRODUCIBLE_VALUE_LABEL"
FLOOR_STOP = "STOP_BELOW_WORTHWHILE_VALUE_FLOOR"
MECHANICS_STOP = "REFUSE_MECHANICS_OR_CONTROL"
WORTHWHILE_FLOOR = Fraction(1, 10)
AUTHORITY = {
    "dataset_opening_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateV2LabelError(ValueError):
    """An outcome population or precision report violated the frozen contract."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2LabelError(f"{label} drift")
    return value


def _candidate_set_sha256(
        state_sha256: str, successors: Sequence[str]) -> str:
    _digest(state_sha256, "candidate-set state SHA-256")
    if type(successors) not in (list, tuple) or len(successors) < 2:
        raise WorldAfterstateV2LabelError("candidate-set population drift")
    for successor in successors:
        _digest(successor, "candidate-set successor SHA-256")
    if len(set(successors)) != len(successors):
        raise WorldAfterstateV2LabelError("candidate-set successor drift")
    return _sha({"schema": "world-afterstate-v2-candidate-set-v1",
                 "state_sha256": state_sha256,
                 "successor_sha256s": list(successors)})


def _validate_mechanics_evidence(
        value: object, *, population_sha256: str) -> bool:
    required = {"schema", "population_sha256", "checks", "authority",
                "evidence_sha256"}
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != MECHANICS_EVIDENCE_SCHEMA \
            or value.get("authority") != AUTHORITY \
            or value.get("population_sha256") != population_sha256:
        raise WorldAfterstateV2LabelError("P0 mechanics evidence binding drift")
    _digest(value["population_sha256"], "P0 mechanics population SHA-256")
    checks = value["checks"]
    if type(checks) is not list:
        raise WorldAfterstateV2LabelError("P0 mechanics check population drift")
    required_row = {"surface", "case_sha256", "observed_sha256",
                    "expected_sha256"}
    keys = []
    surfaces = []
    for row in checks:
        if type(row) is not dict or set(row) != required_row \
                or row["surface"] not in MECHANICS_SURFACES:
            raise WorldAfterstateV2LabelError("P0 mechanics check row drift")
        for key in ("case_sha256", "observed_sha256", "expected_sha256"):
            _digest(row[key], f"P0 mechanics {key}")
        key = (row["surface"], row["case_sha256"])
        if key in keys:
            raise WorldAfterstateV2LabelError(
                "P0 mechanics duplicate check")
        keys.append(key)
        surfaces.append(row["surface"])
    if keys != sorted(keys) or set(surfaces) != set(MECHANICS_SURFACES) \
            or any(surfaces.count(surface) < 1 for surface in MECHANICS_SURFACES):
        raise WorldAfterstateV2LabelError(
            "P0 mechanics check population drift")
    body = {key: item for key, item in value.items()
            if key != "evidence_sha256"}
    _digest(value["evidence_sha256"], "P0 mechanics evidence SHA-256")
    if value["evidence_sha256"] != _sha(body):
        raise WorldAfterstateV2LabelError(
            "P0 mechanics evidence reconstruction drift")
    return all(row["observed_sha256"] == row["expected_sha256"]
               for row in checks)


def build_p0_mechanics_evidence(
        outcomes: Sequence[ContinuationOutcomeV2], *,
        required_slots: Mapping[str, PopulationSlotV2],
        natural_fit_population: Sequence[Any], tier: TierSpecV2,
        checks: Mapping[str, Sequence[tuple[str, str]]]) -> dict[str, Any]:
    """Bind raw expected/observed mechanics witnesses to the exact P0 rows."""
    _groups, population_sha256 = _validate_population(
        outcomes, required_slots=required_slots,
        natural_fit_population=natural_fit_population, tier=tier)
    if type(checks) is not dict or set(checks) != set(MECHANICS_SURFACES):
        raise WorldAfterstateV2LabelError("P0 mechanics request drift")
    rows = []
    for surface in MECHANICS_SURFACES:
        values = checks[surface]
        if type(values) not in (tuple, list) or not values:
            raise WorldAfterstateV2LabelError(
                "P0 mechanics request population drift")
        for index, pair in enumerate(values):
            if type(pair) is not tuple or len(pair) != 2:
                raise WorldAfterstateV2LabelError("P0 mechanics request row drift")
            observed, expected = pair
            _digest(observed, "P0 observed mechanics SHA-256")
            _digest(expected, "P0 expected mechanics SHA-256")
            rows.append({
                "surface": surface,
                "case_sha256": _sha({"surface": surface, "index": index,
                                      "observed": observed,
                                      "expected": expected}),
                "observed_sha256": observed,
                "expected_sha256": expected,
            })
    rows.sort(key=lambda row: (row["surface"], row["case_sha256"]))
    body = {"schema": MECHANICS_EVIDENCE_SCHEMA,
            "population_sha256": population_sha256, "checks": rows,
            "authority": dict(AUTHORITY)}
    result = {**body, "evidence_sha256": _sha(body)}
    _validate_mechanics_evidence(result, population_sha256=population_sha256)
    return result


@dataclass(frozen=True)
class ContinuationOutcomeV2:
    """One sealed engine outcome with slot and CRN identity bindings."""

    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    source: str
    split: str
    role: str
    phase: str
    position: str
    trump_rank: str
    trump_mode: str
    points_bucket: str
    candidate_index: int
    protected_incumbent: bool
    successor_sha256: str
    continuation_sha256: str
    replica: int
    signed_level_category: int
    schema: str = OUTCOME_SCHEMA

    def validate(self) -> None:
        for label, value in (
                ("outcome deal SHA-256", self.deal_sha256),
                ("outcome slot SHA-256", self.slot_sha256),
                ("outcome state SHA-256", self.state_sha256),
                ("outcome candidate-set SHA-256", self.candidate_set_sha256),
                ("outcome successor SHA-256", self.successor_sha256),
                ("outcome continuation SHA-256", self.continuation_sha256)):
            _digest(value, label)
        if self.schema != OUTCOME_SCHEMA \
                or self.source not in STATE_SOURCES \
                or self.split not in ("fit", "select", "audit") \
                or (self.phase, self.position, self.role) not in P0_CELLS \
                or type(self.trump_rank) is not str or not self.trump_rank \
                or type(self.trump_mode) is not str or not self.trump_mode \
                or type(self.points_bucket) is not str or not self.points_bucket \
                or isinstance(self.candidate_index, bool) \
                or not isinstance(self.candidate_index, int) \
                or self.candidate_index < 0 \
                or type(self.protected_incumbent) is not bool \
                or isinstance(self.replica, bool) \
                or not isinstance(self.replica, int) or self.replica < 0:
            raise WorldAfterstateV2LabelError(
                "continuation outcome identity drift")
        category_signed_level(self.signed_level_category)


def _utility(category: int) -> Fraction:
    # category_signed_level is the one canonical category mapping.  Its
    # support is half-integral, so multiplying before Fraction avoids float
    # approximation entirely.
    value = category_signed_level(category)
    return Fraction(int(round(value * 2)), 2)


def _micro(value: Fraction) -> int:
    return value.numerator * 1_000_000 // value.denominator


def _fraction_payload(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _reopen_fraction(value: object, label: str) -> Fraction:
    if type(value) is not dict or set(value) != {"numerator", "denominator"} \
            or isinstance(value["numerator"], bool) \
            or not isinstance(value["numerator"], int) \
            or isinstance(value["denominator"], bool) \
            or not isinstance(value["denominator"], int) \
            or value["denominator"] <= 0:
        raise WorldAfterstateV2LabelError(f"{label} fraction drift")
    result = Fraction(value["numerator"], value["denominator"])
    if _fraction_payload(result) != value:
        raise WorldAfterstateV2LabelError(f"{label} fraction drift")
    return result


def _mean(values: Sequence[Fraction]) -> Fraction:
    if not values:
        raise WorldAfterstateV2LabelError("empty precision mean")
    return sum(values, Fraction(0)) / len(values)


def _choose(values: Mapping[int, Fraction]) -> int:
    # Index zero is the protected incumbent.  It wins every exact tie,
    # including ties against a lower-index non-incumbent.
    best = max(values.values())
    if values.get(0) == best:
        return 0
    return min(index for index, value in values.items() if value == best)


def _correlation_ppm(xs: Sequence[Fraction], ys: Sequence[Fraction]) -> int:
    if len(xs) != len(ys) or not xs:
        return 0
    n = len(xs)
    sx, sy = sum(xs, Fraction(0)), sum(ys, Fraction(0))
    left = sum((x - sx / n) ** 2 for x in xs)
    right = sum((y - sy / n) ** 2 for y in ys)
    if not left or not right:
        return 0
    numerator = sum((x - sx / n) * (y - sy / n)
                    for x, y in zip(xs, ys))
    # Floor |numerator|*1e6/sqrt(left*right), exactly, by comparing squares.
    ratio = (numerator * numerator * 1_000_000_000_000) / (left * right)
    q = math.isqrt(ratio.numerator // ratio.denominator)
    while (q + 1) * (q + 1) * ratio.denominator <= ratio.numerator:
        q += 1
    while q * q * ratio.denominator > ratio.numerator:
        q -= 1
    magnitude = q
    return max(-1_000_000, min(1_000_000,
                               magnitude if numerator >= 0 else -magnitude))


def _bootstrap_seed(population_sha256: str, metric: str) -> int:
    return int.from_bytes(hashlib.sha256(
        f"{population_sha256}|{metric}".encode("ascii")).digest()[:16], "big")


def _bootstrap_lower(
        deal_values: Mapping[str, Fraction], *, population_sha256: str,
        metric: str, replicates: int) -> tuple[Fraction, int]:
    if not deal_values or isinstance(replicates, bool) \
            or not isinstance(replicates, int) or replicates < 100:
        raise WorldAfterstateV2LabelError("precision bootstrap request drift")
    deals = sorted(deal_values)
    rng = random.Random(_bootstrap_seed(population_sha256, metric))
    draws: list[Fraction] = []
    for _ in range(replicates):
        draws.append(_mean([deal_values[deals[rng.randrange(len(deals))]]
                            for _ in deals]))
    draws.sort()
    # Fifth percentile, nearest-rank convention (the minimum replicate count
    # accepted by this module makes the index non-negative).
    rank = (replicates * 5 + 99) // 100
    return _mean(tuple(deal_values.values())), draws[rank - 1]


def _validate_population(
        outcomes: Sequence[ContinuationOutcomeV2], *,
        required_slots: Mapping[str, PopulationSlotV2],
        natural_fit_population: Sequence[Any], tier: TierSpecV2) \
        -> tuple[
            dict[str, dict[int, dict[int, ContinuationOutcomeV2]]], str]:
    if type(outcomes) not in (list, tuple) or not outcomes:
        raise WorldAfterstateV2LabelError("precision outcome population drift")
    if type(required_slots) is not dict:
        raise WorldAfterstateV2LabelError("precision slot population drift")
    try:
        canonical_states = select_p0_population(
            natural_fit_population, tier=tier)
    except Exception as exc:
        raise WorldAfterstateV2LabelError(
            "canonical P0 subset population drift") from exc
    canonical_by_deal = {state.deal_sha256: state for state in canonical_states}
    if set(required_slots) != set(canonical_by_deal) \
            or any(type(slot) is not PopulationSlotV2
                   for slot in required_slots.values()):
        raise WorldAfterstateV2LabelError("canonical P0 subset mismatch")
    slots: dict[str, PopulationSlotV2] = {}
    for deal, slot in required_slots.items():
        _digest(deal, "precision assigned deal SHA-256")
        slot.validate()
        expected_state = canonical_by_deal[deal]
        if (slot.slot_sha256 != expected_state.slot_sha256
                or slot.group != "natural-fit" or slot.source != "natural"
                or slot.split != "fit" or slot.cell != expected_state.cell
                or slot.trump_rank != expected_state.trump_rank
                or slot.trump_mode != expected_state.trump_mode):
            raise WorldAfterstateV2LabelError("canonical P0 subset mismatch")
        slots[deal] = slot
    if len(slots) != P0_DEALS \
            or len({slot.slot_sha256 for slot in slots.values()}) != P0_DEALS \
            or len({slot.tier for slot in slots.values()}) != 1:
        raise WorldAfterstateV2LabelError("precision slot population drift")
    slot_cells: dict[tuple[str, str, str], int] = defaultdict(int)
    for slot in slots.values():
        assert slot.cell is not None
        slot_cells[slot.cell] += 1
    if any(slot_cells[cell] != P0_PER_CELL for cell in P0_CELLS):
        raise WorldAfterstateV2LabelError("precision slot cell balance drift")
    groups: dict[str, dict[int, dict[int, ContinuationOutcomeV2]]] = defaultdict(
        lambda: defaultdict(dict))
    deal_for_state: dict[str, str] = {}
    for row in outcomes:
        if type(row) is not ContinuationOutcomeV2:
            raise WorldAfterstateV2LabelError("precision outcome type drift")
        row.validate()
        if row.source != "natural" or row.split != "fit":
            raise WorldAfterstateV2LabelError(
                "precision accepts natural fit outcomes only")
        if row.deal_sha256 not in slots:
            raise WorldAfterstateV2LabelError("canonical P0 subset mismatch")
        slot = slots[row.deal_sha256]
        state = canonical_by_deal[row.deal_sha256]
        if row.slot_sha256 != slot.slot_sha256 \
            or (row.phase, row.position, row.role) != slot.cell \
            or row.trump_rank != slot.trump_rank \
            or row.trump_mode != slot.trump_mode \
            or row.state_sha256 != state.state_sha256:
            raise WorldAfterstateV2LabelError(
                "canonical P0 subset state binding drift")
        if row.replica not in REPLICATES:
            raise WorldAfterstateV2LabelError("precision replica population drift")
        prior = deal_for_state.setdefault(row.state_sha256, row.deal_sha256)
        if prior != row.deal_sha256:
            raise WorldAfterstateV2LabelError("precision state/deal binding drift")
        rows = groups[row.state_sha256][row.candidate_index]
        if row.replica in rows:
            raise WorldAfterstateV2LabelError("duplicate precision outcome")
        rows[row.replica] = row
    if len(groups) != P0_DEALS \
            or set(deal_for_state) != {state.state_sha256
                                       for state in canonical_states}:
        raise WorldAfterstateV2LabelError("canonical P0 subset mismatch")
    if set(deal_for_state.values()) != set(canonical_by_deal):
        raise WorldAfterstateV2LabelError(
            "canonical P0 subset mismatch")
    cells: dict[tuple[str, str, str], int] = defaultdict(int)
    for state, candidates in groups.items():
        indexes = sorted(candidates)
        if indexes != list(range(len(indexes))) or len(indexes) < 2:
            raise WorldAfterstateV2LabelError(
                "precision candidate set must be complete and contiguous")
        if any(set(rows) != set(REPLICATES) for rows in candidates.values()):
            raise WorldAfterstateV2LabelError(
                "precision requires exactly replicas 0 through 7")
        first = candidates[0][0]
        identity = (first.deal_sha256, first.slot_sha256,
                    first.candidate_set_sha256, first.source, first.split,
                    first.role, first.phase, first.position,
                    first.trump_rank, first.trump_mode, first.points_bucket)
        continuation_ids: dict[int, str] = {}
        successor_ids: list[str] = []
        for index in indexes:
            candidate_successor: str | None = None
            for replica in REPLICATES:
                row = candidates[index][replica]
                current = (row.deal_sha256, row.slot_sha256,
                            row.candidate_set_sha256, row.source, row.split,
                            row.role, row.phase, row.position,
                            row.trump_rank, row.trump_mode, row.points_bucket)
                if current != identity:
                    raise WorldAfterstateV2LabelError(
                        "precision sibling metadata binding drift")
                if row.protected_incumbent != (index == 0):
                    raise WorldAfterstateV2LabelError(
                        "precision protected incumbent drift")
                if candidate_successor is None:
                    candidate_successor = row.successor_sha256
                elif row.successor_sha256 != candidate_successor:
                    raise WorldAfterstateV2LabelError(
                        "precision successor identity drift across replicas")
                if row.candidate_index != index:
                    raise WorldAfterstateV2LabelError(
                        "precision candidate index binding drift")
                previous_continuation = continuation_ids.setdefault(
                    replica, row.continuation_sha256)
                if previous_continuation != row.continuation_sha256:
                    raise WorldAfterstateV2LabelError(
                        "precision sibling continuation binding drift")
            assert candidate_successor is not None
            successor_ids.append(candidate_successor)
        if len(set(continuation_ids.values())) != len(REPLICATES):
            raise WorldAfterstateV2LabelError(
                "precision continuation replica identity drift")
        expected_candidate_set = _candidate_set_sha256(state, successor_ids)
        if first.candidate_set_sha256 != expected_candidate_set:
            raise WorldAfterstateV2LabelError(
                "precision candidate-set reconstruction drift")
        cell = (first.phase, first.position, first.role)
        if cell not in P0_CELLS:
            raise WorldAfterstateV2LabelError("precision cell drift")
        cells[cell] += 1
    if any(cells[cell] != P0_PER_CELL for cell in P0_CELLS):
        raise WorldAfterstateV2LabelError("precision cell balance drift")
    # Hash only validated, canonical identity/outcome material.  This is also
    # the domain separator for every bootstrap metric.
    population = []
    for state in sorted(groups):
        population.extend(row.__dict__ for index in sorted(groups[state])
                          for replica in REPLICATES
                          for row in (groups[state][index][replica],))
    binding = {
        "tier": tier.payload(),
        "canonical_p0_states": [state.__dict__ for state in sorted(
            canonical_states, key=lambda value: value.deal_sha256)],
        "slots": {deal: slots[deal].payload() for deal in sorted(slots)},
        "outcomes": population,
    }
    return groups, _sha(binding)


def _icc(values: Sequence[Sequence[Fraction]]) -> int:
    if not values or len(values[0]) < 2 or any(len(row) != len(values[0])
                                               for row in values):
        return 0
    n, k = len(values), len(values[0])
    grand = _mean(tuple(value for row in values for value in row))
    between = k * sum((_mean(tuple(row)) - grand) ** 2 for row in values)
    within = sum((value - _mean(tuple(row))) ** 2
                 for row in values for value in row)
    if not between + within:
        return 1_000_000
    # ICC(1,1), clipped to the conventional range.
    between_ms = between / (n - 1)
    within_ms = within / (n * (k - 1))
    value = (between_ms - within_ms) \
        / (between_ms + (k - 1) * within_ms)
    return max(-1_000_000, min(1_000_000, _micro(value)))


def _curve(groups: Mapping[
        str, Mapping[int, Mapping[int, ContinuationOutcomeV2]]],
           count: int) -> dict[str, int]:
    rows = []
    agreement = 0
    error = Fraction(0)
    for candidates in groups.values():
        means = {index: _mean(tuple(_utility(candidates[index][r]
                                      .signed_level_category)
                                     for r in range(count)))
                 for index in candidates}
        chosen = _choose(means)
        choices = [_choose({index: _utility(candidates[index][r]
                                             .signed_level_category)
                            for index in candidates}) for r in range(count)]
        agreement += sum(choice == chosen for choice in choices)
        error += abs(means[chosen] - _mean(tuple(
            _utility(candidates[chosen][r].signed_level_category)
            for r in REPLICATES)))
        rows.append(tuple(_utility(candidates[chosen][r].signed_level_category)
                          for r in range(count)))
    total = P0_DEALS * count
    return {
        "action_agreement_ppm": agreement * 1_000_000 // total,
        "return_mean_error_microlevels": _micro(error / P0_DEALS),
        "intraclass_correlation_ppm": _icc(rows),
    }


def evaluate_precision_label(
        outcomes: Sequence[ContinuationOutcomeV2], *,
        required_slots: Mapping[str, PopulationSlotV2],
        natural_fit_population: Sequence[Any] | None = None,
        tier: TierSpecV2 | None = None,
        bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
        mechanics_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate the frozen P0 precision gates and return a closed report."""
    groups, population_sha = _validate_population(
        outcomes, required_slots=required_slots,
        natural_fit_population=natural_fit_population, tier=tier)
    mechanics_passed = _validate_mechanics_evidence(
        mechanics_evidence, population_sha256=population_sha)
    direction_values = {"0-to-1": [], "1-to-0": []}
    deal_values: dict[str, Fraction] = {}
    pair_halves: list[tuple[Fraction, Fraction, str]] = []
    chosen_incumbent: dict[str, tuple[Fraction, Fraction]] = {}
    for state in sorted(groups):
        candidates = groups[state]
        rows = candidates[0][0]
        utilities = {index: {replica: _utility(candidates[index][replica]
                                                 .signed_level_category)
                             for replica in REPLICATES}
                     for index in candidates}
        direction = []
        incumbent_diag = []
        for select_half, truth_half in ((HALVES[0], HALVES[1]),
                                        (HALVES[1], HALVES[0])):
            selected = _choose({index: _mean(tuple(utilities[index][r]
                                                    for r in select_half))
                                for index in candidates})
            chosen_value = _mean(tuple(utilities[selected][r]
                                       for r in truth_half))
            candidate_mean = _mean(tuple(
                _mean(tuple(utilities[index][r] for r in truth_half))
                for index in candidates))
            incumbent = _mean(tuple(utilities[0][r] for r in truth_half))
            direction.append(chosen_value - candidate_mean)
            incumbent_diag.append(chosen_value - incumbent)
        direction_values["0-to-1"].append(direction[0])
        direction_values["1-to-0"].append(direction[1])
        chosen_incumbent[state] = (incumbent_diag[0], incumbent_diag[1])
        deal_values[rows.deal_sha256] = _mean(tuple(direction))
        for index in sorted(candidates):
            if index == 0:
                continue
            pair_halves.append((
                _mean(tuple(utilities[index][r] - utilities[0][r]
                            for r in HALVES[0])),
                _mean(tuple(utilities[index][r] - utilities[0][r]
                            for r in HALVES[1])), rows.deal_sha256))
    pair_total = len(pair_halves)
    same_nonzero = sum(
        int(x != 0 and y != 0 and ((x > 0) == (y > 0)))
        for x, y, _ in pair_halves)
    sign_ppm = same_nonzero * 1_000_000 // pair_total
    sibling_by_deal: dict[str, list[tuple[Fraction, Fraction]]] = defaultdict(list)
    for x, y, deal in pair_halves:
        sibling_by_deal[deal].append((x, y))
    sibling_x = {deal: tuple(item[0] for item in values)
                 for deal, values in sibling_by_deal.items()}
    sibling_y = {deal: tuple(item[1] for item in values)
                 for deal, values in sibling_by_deal.items()}
    deals = sorted(sibling_by_deal)
    rng = random.Random(_bootstrap_seed(population_sha, "sibling-advantage-correlation"))
    correlations = []
    for _ in range(bootstrap_replicates):
        sampled = [deals[rng.randrange(len(deals))] for _ in deals]
        xs = tuple(v for deal in sampled for v in sibling_x[deal])
        ys = tuple(v for deal in sampled for v in sibling_y[deal])
        correlations.append(_correlation_ppm(xs, ys))
    correlations.sort()
    correlation_rank = (bootstrap_replicates * 5 + 99) // 100
    correlation_lower = correlations[correlation_rank - 1]
    combined_mean, combined_lower = _bootstrap_lower(
        deal_values, population_sha256=population_sha, metric="combined-crossfit",
        replicates=bootstrap_replicates)
    directional = {name: _micro(_mean(tuple(values)))
                   for name, values in direction_values.items()}
    directional_exact = {
        name: _mean(tuple(values)) for name, values in direction_values.items()}
    # Gate 4 is evaluated from the exact, unrounded point estimate.  The
    # published microlevel is a readable projection of that Fraction.
    incumbent_deal_values = tuple(
        _mean((values[0], values[1])) for values in chosen_incumbent.values())
    incumbent_mean = _mean(incumbent_deal_values)
    incumbent_variance = sum((value - incumbent_mean) ** 2
                             for value in incumbent_deal_values) \
        / (P0_DEALS - 1)
    sd_micro = math.isqrt(
        incumbent_variance.numerator * 1_000_000_000_000
        // incumbent_variance.denominator)
    stats_passed = (all(_mean(tuple(values)) > 0
                        for values in direction_values.values())
                    and combined_lower > 0
                    and correlation_lower > 0)
    # The sign-dose fraction is a separate preregistered threshold; preserve
    # the explicit >=5% gate while keeping all utility signs exact.
    stats_passed = (stats_passed and sign_ppm >= 50_000)
    floor_passed = incumbent_mean >= WORTHWHILE_FLOOR
    route = MECHANICS_STOP if not mechanics_passed else (
        STATISTICAL_STOP if not stats_passed else (
            "PASS_P0_PRECISION" if floor_passed else FLOOR_STOP))
    body: dict[str, Any] = {
        "schema": LABEL_SCHEMA,
        "population_sha256": population_sha,
        "deal_count": P0_DEALS,
        "state_count": len(groups),
        "raw_outcome_count": len(outcomes),
        "replica_count": len(REPLICATES),
        "candidate_pair_count": pair_total,
        "cell_counts": {"/".join(cell): sum(
            int(groups[state][0][0].phase == cell[0]
                and groups[state][0][0].position == cell[1]
                and groups[state][0][0].role == cell[2])
            for state in groups) for cell in P0_CELLS},
        "directional_candidate_mean_microlevels": directional,
        "combined_candidate_mean_microlevels": {
            "mean": _micro(combined_mean),
            "bootstrap_lower": _micro(combined_lower),
        },
        "sibling_same_nonzero_sign_ppm": sign_ppm,
        "sibling_advantage_correlation_ppm": _correlation_ppm(
            tuple(x for x, _, _ in pair_halves),
            tuple(y for _, y, _ in pair_halves)),
        "sibling_advantage_correlation_bootstrap_lower_ppm": correlation_lower,
        "chosen_minus_incumbent_microlevels": {
            name: _micro(_mean(tuple(values))) for name, values
            in (("0-to-1", [v[0] for v in chosen_incumbent.values()]),
                ("1-to-0", [v[1] for v in chosen_incumbent.values()]))},
        "gate_fractions": {
            "direction_0_to_1": _fraction_payload(
                directional_exact["0-to-1"]),
            "direction_1_to_0": _fraction_payload(
                directional_exact["1-to-0"]),
            "combined_mean": _fraction_payload(combined_mean),
            "combined_bootstrap_lower": _fraction_payload(combined_lower),
            "chosen_minus_incumbent_mean": _fraction_payload(incumbent_mean),
        },
        "bootstrap_replicates": bootstrap_replicates,
        "r2": _curve(groups, 2),
        "r4": _curve(groups, 4),
        "r8": _curve(groups, 8),
        "combined_chosen_minus_incumbent_microlevels": _micro(incumbent_mean),
        "incumbent_relative_bessel_s_microlevels": sd_micro,
        "mechanics_evidence": dict(mechanics_evidence),
        "mechanics_evidence_sha256": mechanics_evidence["evidence_sha256"],
        "mechanics_passed": mechanics_passed,
        "statistical_gates_passed": stats_passed,
        "worthwhile_floor_passed": floor_passed,
        "decision": route,
        "authority": dict(AUTHORITY),
    }
    result = {**body, "result_sha256": _sha(body)}
    validate_precision_label(result)
    return result


def validate_precision_label(value: Mapping[str, Any]) -> None:
    """Validate the closed authority/report envelope without opening outcomes."""
    required = {
        "schema", "population_sha256", "deal_count", "state_count",
        "raw_outcome_count", "replica_count", "candidate_pair_count",
        "cell_counts", "directional_candidate_mean_microlevels",
        "combined_candidate_mean_microlevels", "sibling_same_nonzero_sign_ppm",
        "sibling_advantage_correlation_ppm",
        "sibling_advantage_correlation_bootstrap_lower_ppm",
        "chosen_minus_incumbent_microlevels", "gate_fractions",
        "bootstrap_replicates", "r2",
        "r4", "r8", "combined_chosen_minus_incumbent_microlevels",
        "incumbent_relative_bessel_s_microlevels", "mechanics_evidence",
        "mechanics_evidence_sha256", "mechanics_passed",
        "statistical_gates_passed", "worthwhile_floor_passed", "decision",
        "authority", "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != LABEL_SCHEMA \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV2LabelError("precision result schema drift")
    _digest(value["population_sha256"], "precision population SHA-256")
    expected_mechanics = _validate_mechanics_evidence(
        value["mechanics_evidence"],
        population_sha256=value["population_sha256"])
    if value["mechanics_evidence_sha256"] \
            != value["mechanics_evidence"]["evidence_sha256"] \
            or value["mechanics_passed"] is not expected_mechanics:
        raise WorldAfterstateV2LabelError(
            "precision mechanics evidence derivation drift")
    if value["deal_count"] != P0_DEALS or value["state_count"] != P0_DEALS \
            or value["raw_outcome_count"] <= 0 or value["replica_count"] != 8 \
            or type(value["mechanics_passed"]) is not bool \
            or type(value["statistical_gates_passed"]) is not bool:
        raise WorldAfterstateV2LabelError("precision result count drift")
    integers = (
        value["raw_outcome_count"], value["candidate_pair_count"],
        value["sibling_same_nonzero_sign_ppm"],
        value["sibling_advantage_correlation_ppm"],
        value["sibling_advantage_correlation_bootstrap_lower_ppm"],
        value["bootstrap_replicates"],
        value["incumbent_relative_bessel_s_microlevels"],
        value["combined_chosen_minus_incumbent_microlevels"])
    if any(isinstance(item, bool) or not isinstance(item, int)
           for item in integers) or value["raw_outcome_count"] <= 0 \
            or value["candidate_pair_count"] < P0_DEALS \
            or value["raw_outcome_count"] != 8 * (
                value["candidate_pair_count"] + P0_DEALS) \
            or value["bootstrap_replicates"] < 100 \
            or value["incumbent_relative_bessel_s_microlevels"] < 0 \
            or not 0 <= value["sibling_same_nonzero_sign_ppm"] <= 1_000_000 \
            or not -1_000_000 <= value["sibling_advantage_correlation_ppm"] <= 1_000_000 \
            or not -1_000_000 <= value["sibling_advantage_correlation_bootstrap_lower_ppm"] <= 1_000_000:
        raise WorldAfterstateV2LabelError("precision result metric drift")
    cells = value["cell_counts"]
    if type(cells) is not dict or set(cells) != {"/".join(cell) for cell in P0_CELLS} \
            or any(type(item) is not int or item != P0_PER_CELL
                   for item in cells.values()):
        raise WorldAfterstateV2LabelError("precision result cell drift")
    directions = value["directional_candidate_mean_microlevels"]
    combined = value["combined_candidate_mean_microlevels"]
    incumbent = value["chosen_minus_incumbent_microlevels"]
    if type(directions) is not dict or set(directions) != {"0-to-1", "1-to-0"} \
            or any(type(item) is not int for item in directions.values()) \
            or type(combined) is not dict or set(combined) != {"mean", "bootstrap_lower"} \
            or any(type(item) is not int for item in combined.values()) \
            or type(incumbent) is not dict or set(incumbent) != {"0-to-1", "1-to-0"} \
            or any(type(item) is not int for item in incumbent.values()):
        raise WorldAfterstateV2LabelError("precision result utility drift")
    fractions = value["gate_fractions"]
    if type(fractions) is not dict or set(fractions) != {
            "direction_0_to_1", "direction_1_to_0", "combined_mean",
            "combined_bootstrap_lower", "chosen_minus_incumbent_mean"}:
        raise WorldAfterstateV2LabelError("precision gate fraction drift")
    exact = {key: _reopen_fraction(item, f"precision {key}")
             for key, item in fractions.items()}
    if (directions["0-to-1"] != _micro(exact["direction_0_to_1"])
            or directions["1-to-0"] != _micro(exact["direction_1_to_0"])
            or combined["mean"] != _micro(exact["combined_mean"])
            or combined["bootstrap_lower"] != _micro(
                exact["combined_bootstrap_lower"])
            or value["combined_chosen_minus_incumbent_microlevels"] != _micro(
                exact["chosen_minus_incumbent_mean"])):
        raise WorldAfterstateV2LabelError(
            "precision gate fraction projection drift")
    for curve_name in ("r2", "r4", "r8"):
        curve = value[curve_name]
        if type(curve) is not dict or set(curve) != {
                "action_agreement_ppm", "return_mean_error_microlevels",
                "intraclass_correlation_ppm"} \
                or any(type(item) is not int for item in curve.values()):
            raise WorldAfterstateV2LabelError("precision result curve drift")
    expected_statistical = (
        exact["direction_0_to_1"] > 0 and exact["direction_1_to_0"] > 0
        and exact["combined_bootstrap_lower"] > 0
        and value["sibling_same_nonzero_sign_ppm"] >= 50_000
        and value["sibling_advantage_correlation_bootstrap_lower_ppm"] > 0)
    if value["statistical_gates_passed"] is not expected_statistical:
        raise WorldAfterstateV2LabelError("precision statistical gate drift")
    if type(value["worthwhile_floor_passed"]) is not bool:
        raise WorldAfterstateV2LabelError("precision floor gate drift")
    if value["worthwhile_floor_passed"] != (
            exact["chosen_minus_incumbent_mean"] >= WORTHWHILE_FLOOR):
        raise WorldAfterstateV2LabelError("precision floor gate drift")
    if value["decision"] not in ("PASS_P0_PRECISION", STATISTICAL_STOP,
                                  FLOOR_STOP, MECHANICS_STOP):
        raise WorldAfterstateV2LabelError("precision decision drift")
    expected_decision = MECHANICS_STOP if not value["mechanics_passed"] else (
        STATISTICAL_STOP if not expected_statistical else (
            "PASS_P0_PRECISION" if value["worthwhile_floor_passed"]
            else FLOOR_STOP))
    if value["decision"] != expected_decision:
        raise WorldAfterstateV2LabelError("precision route drift")
    body = {key: item for key, item in value.items() if key != "result_sha256"}
    if value["result_sha256"] != _sha(body):
        raise WorldAfterstateV2LabelError("precision result reconstruction drift")


__all__ = [
    "AUTHORITY", "BOOTSTRAP_REPLICATES", "HALVES", "LABEL_SCHEMA",
    "MECHANICS_EVIDENCE_SCHEMA", "MECHANICS_SURFACES", "MECHANICS_STOP",
    "OUTCOME_SCHEMA", "P0_CELLS", "P0_DEALS",
    "P0_PER_CELL", "REPLICATES", "STATISTICAL_STOP", "FLOOR_STOP",
    "ContinuationOutcomeV2", "WorldAfterstateV2LabelError",
    "build_p0_mechanics_evidence", "evaluate_precision_label",
    "validate_precision_label",
]
