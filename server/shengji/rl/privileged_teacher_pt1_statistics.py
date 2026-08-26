"""Deterministic, state-level PT1 statistical reduction.

The reducer is deliberately downstream of the natural capture and exact PT1
record boundaries.  It verifies those inputs before computing any aggregate,
and treats each of the 416 captured states as one bootstrap unit after taking
the fixed four policy-seed mean within that state.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence

from .privileged_teacher_pt0 import PrivilegedTeacherPT0Error, canonical_json_bytes
from .privileged_teacher_pt1 import (
    AUTHORITY, PT1_RECORD_SCHEMA, PT1Record, PrivilegedTeacherPT1Error,
    verify_record,
)
from .privileged_teacher_pt1_natural import (
    NATURAL_PT1_STATE_SCHEMA, TARGET_STATE_COUNT, NaturalPT1Design,
    NaturalPT1State, _capture_id_sha256, _cluster_sha256, validate_population,
)


STATISTICS_SCHEMA = "privileged-teacher-pt1-statistics-v1"
STATISTICS_REPORT_SCHEMA = "privileged-teacher-pt1-statistics-report-v1"
POLICY_SEEDS = (0, 1, 2, 3)
RECORDS_PER_STATE = len(POLICY_SEEDS)
TOTAL_RECORD_COUNT = TARGET_STATE_COUNT * RECORDS_PER_STATE
BOOTSTRAP_REPLICATES = 5_000
BOOTSTRAP_SEED = 0x5054315354415449
PASS_STATUS = "PASS_TO_PT2_TEACHER_EVALUATION"
REFUSED_STATUS = "REFUSED"


class PT1StatisticsError(PrivilegedTeacherPT1Error):
    """The PT1 population or aggregate failed closed."""


@dataclass(frozen=True)
class PT1PopulationStateIdentity:
    """Manifest-bound state identity reopened from a sealed execution group.

    This is intentionally not a substitute for ``NaturalPT1State`` at capture
    or evaluation time.  It exists only so terminal reduction can consume the
    exact identities already validated against the frozen population manifest
    without reconstructing private ``Round`` objects after scores are sealed.
    """

    rank: str
    banker: int
    role: str
    remaining_hand_threshold: int
    replicate: int
    round_seed: int
    capture_round_cluster_sha256: str
    capture_id_sha256: str
    public_state_sha256: str
    true_world_sha256: str
    schema: str = NATURAL_PT1_STATE_SCHEMA


def _sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value):
        raise PT1StatisticsError(f"{label} must be a lowercase SHA-256")
    return value


def _fraction_payload(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _fraction(value: object, label: str) -> Fraction:
    if not isinstance(value, Mapping) or set(value) != {"numerator", "denominator"}:
        raise PT1StatisticsError(f"{label} fraction drift")
    numerator, denominator = value["numerator"], value["denominator"]
    if (isinstance(numerator, bool) or not isinstance(numerator, int)
            or isinstance(denominator, bool) or not isinstance(denominator, int)
            or denominator <= 0):
        raise PT1StatisticsError(f"{label} fraction drift")
    return Fraction(numerator, denominator)


def _mean(values: Sequence[int | Fraction]) -> Fraction:
    if not values:
        raise PT1StatisticsError("empty statistical population")
    return Fraction(sum(values), len(values))


def _record_seed(record: PT1Record) -> int:
    seeds = {arm.seed for arm in record.arms}
    if len(seeds) != 1:
        raise PT1StatisticsError("record arm seed identity drift")
    seed = next(iter(seeds))
    if seed not in POLICY_SEEDS:
        raise PT1StatisticsError("record policy seed is outside fixed four-seed set")
    return seed


def _record_deltas(record: PT1Record) -> tuple[int, int, int]:
    values = dict(record.selected_utilities)
    try:
        a, b, c = (values[name] for name in ("A", "B", "C"))
    except KeyError as exc:
        raise PT1StatisticsError("record arm utility population drift") from exc
    return c - b, b - a, c - a


def _population_identity(
        design: NaturalPT1Design,
        population: Mapping[tuple[str, int, str, int, int],
                            NaturalPT1State | PT1PopulationStateIdentity]) -> str:
    rows = []
    for key in design.state_keys:
        state = population[key]
        rows.append([list(key), state.schema, state.round_seed,
                     state.capture_round_cluster_sha256,
                     state.capture_id_sha256, state.public_state_sha256,
                     state.true_world_sha256])
    return hashlib.sha256(canonical_json_bytes(rows)).hexdigest()


@dataclass(frozen=True)
class PT1StateStatistic:
    rank: str
    banker: int
    role: str
    remaining_hand_threshold: int
    replicate: int
    replicate_count: int
    mean_cb: Fraction
    mean_ba: Fraction
    mean_ca: Fraction
    positive_seed_cb: int
    action_flips_ab: int
    action_flips_bc: int
    action_flips_ac: int

    def payload(self) -> dict[str, object]:
        return {"trump_rank": self.rank, "banker": self.banker,
                "role": self.role,
                "remaining_hand_threshold": self.remaining_hand_threshold,
                "replicate": self.replicate,
                "replicate_count": self.replicate_count,
                "mean_cb": _fraction_payload(self.mean_cb),
                "mean_ba": _fraction_payload(self.mean_ba),
                "mean_ca": _fraction_payload(self.mean_ca),
                "positive_seed_cb": self.positive_seed_cb,
                "action_flips": {"A_B": self.action_flips_ab,
                                  "B_C": self.action_flips_bc,
                                  "A_C": self.action_flips_ac}}


@dataclass(frozen=True)
class PT1StratumStatistic:
    dimension: str
    value: object
    state_count: int
    mean_cb: Fraction
    positive_state_count: int

    def payload(self) -> dict[str, object]:
        return {"dimension": self.dimension, "value": self.value,
                "state_count": self.state_count,
                "mean_cb": _fraction_payload(self.mean_cb),
                "positive_state_count": self.positive_state_count}


@dataclass(frozen=True)
class PT1StatisticsReport:
    design_sha256: str
    population_sha256: str
    seeds: tuple[int, ...]
    state_count: int
    record_count: int
    state_statistics: tuple[PT1StateStatistic, ...]
    strata: tuple[PT1StratumStatistic, ...]
    action_flip_dose: tuple[tuple[str, int, int], ...]
    mean_cb: Fraction
    bootstrap_seed: int
    bootstrap_replicates: int
    bootstrap_lcb_cb: Fraction
    positive_state_count: int
    c_regret_nonzero_count: int
    gate_results: tuple[tuple[str, bool], ...]
    status: str
    authority: Mapping[str, bool]
    schema: str = STATISTICS_REPORT_SCHEMA

    def _body(self) -> dict[str, object]:
        return {"schema": self.schema, "design_sha256": self.design_sha256,
                "population_sha256": self.population_sha256,
                "seeds": list(self.seeds), "state_count": self.state_count,
                "record_count": self.record_count,
                "state_statistics": [row.payload() for row in self.state_statistics],
                "strata": [row.payload() for row in self.strata],
                "action_flip_dose": {
                    name: {"flips": flips, "total": total}
                    for name, flips, total in self.action_flip_dose},
                "mean_cb": _fraction_payload(self.mean_cb),
                "bootstrap": {"seed": self.bootstrap_seed,
                              "replicates": self.bootstrap_replicates,
                              "one_sided_95_lcb_cb": _fraction_payload(
                                  self.bootstrap_lcb_cb)},
                "positive_state_count": self.positive_state_count,
                "c_regret_nonzero_count": self.c_regret_nonzero_count,
                "gate_results": {name: value for name, value in self.gate_results},
                "status": self.status, "authority": dict(self.authority)}

    def payload(self) -> dict[str, object]:
        body = self._body()
        return {**body, "report_sha256": hashlib.sha256(
            canonical_json_bytes(body)).hexdigest()}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())


def _strata(rows: Sequence[PT1StateStatistic]) -> tuple[PT1StratumStatistic, ...]:
    result = []
    for dimension, values in (("trump_rank", sorted({r.rank for r in rows})),
                              ("role", sorted({r.role for r in rows})),
                              ("remaining_hand_threshold",
                               sorted({r.remaining_hand_threshold for r in rows}))):
        for value in values:
            selected = [r for r in rows if getattr(
                r, {"trump_rank": "rank", "role": "role",
                    "remaining_hand_threshold": "remaining_hand_threshold"}[dimension]) == value]
            result.append(PT1StratumStatistic(
                dimension, value, len(selected),
                _mean([r.mean_cb for r in selected]),
                sum(r.mean_cb > 0 for r in selected)))
    return tuple(result)


def _bootstrap(values: Sequence[Fraction], *, seed: int, replicates: int) -> Fraction:
    rng = random.Random(seed)
    sums = []
    for _ in range(replicates):
        sums.append(sum(values[rng.randrange(len(values))]
                        for _ in range(len(values))))
    sums.sort()
    # Fixed nearest-lower order statistic: one-sided 95% lower bound.
    return sums[(replicates - 1) * 5 // 100] / len(values)


def _require_fixed_seeds(seeds: Sequence[int]) -> tuple[int, ...]:
    if tuple(seeds) != POLICY_SEEDS:
        raise PT1StatisticsError("PT1 requires exactly fixed seeds (0, 1, 2, 3)")
    return POLICY_SEEDS


def validate_reopened_population(
        design: NaturalPT1Design,
        population: Mapping[tuple[str, int, str, int, int],
                            PT1PopulationStateIdentity]) -> None:
    """Validate the identity-only population produced by group reopening.

    Full public/hidden mechanics are validated before evaluation and bound by
    the frozen population manifest.  This terminal boundary revalidates every
    identity field, derivation and uniqueness property that remains available
    after the live capabilities have deliberately been discarded.
    """
    if type(design) is not NaturalPT1Design:
        raise PT1StatisticsError("reopened statistics require NaturalPT1Design")
    if not isinstance(population, Mapping) \
            or set(population) != set(design.state_keys):
        raise PT1StatisticsError("reopened population cells incomplete or duplicated")
    round_seeds: set[int] = set()
    clusters: set[str] = set()
    capture_ids: set[str] = set()
    public_true: set[tuple[str, str]] = set()
    for key in design.state_keys:
        state = population[key]
        if (type(state) is not PT1PopulationStateIdentity
                or type(state.rank) is not str
                or type(state.banker) is not int
                or isinstance(state.banker, bool)
                or type(state.role) is not str
                or type(state.remaining_hand_threshold) is not int
                or isinstance(state.remaining_hand_threshold, bool)
                or type(state.replicate) is not int
                or isinstance(state.replicate, bool)
                or key != (state.rank, state.banker, state.role,
                           state.remaining_hand_threshold, state.replicate)):
            raise PT1StatisticsError("reopened population state identity drift")
        if state.schema != NATURAL_PT1_STATE_SCHEMA:
            raise PT1StatisticsError("reopened population state schema drift")
        if (type(state.round_seed) is not int or state.round_seed < 0
                or state.capture_round_cluster_sha256
                != _cluster_sha256(state.round_seed)
                or state.capture_id_sha256 != _capture_id_sha256(
                    state.rank, state.banker, state.role,
                    state.remaining_hand_threshold, state.replicate,
                    state.public_state_sha256)):
            raise PT1StatisticsError("reopened population derivation drift")
        for value, label in (
                (state.capture_round_cluster_sha256, "capture cluster"),
                (state.capture_id_sha256, "capture identity"),
                (state.public_state_sha256, "public state"),
                (state.true_world_sha256, "true world")):
            _sha(value, f"reopened {label}")
        identity = (state.public_state_sha256, state.true_world_sha256)
        if (state.round_seed in round_seeds
                or state.capture_round_cluster_sha256 in clusters
                or state.capture_id_sha256 in capture_ids
                or identity in public_true):
            raise PT1StatisticsError("reopened population duplicate identity")
        round_seeds.add(state.round_seed)
        clusters.add(state.capture_round_cluster_sha256)
        capture_ids.add(state.capture_id_sha256)
        public_true.add(identity)
    if len(round_seeds) != TARGET_STATE_COUNT:
        raise PT1StatisticsError("reopened population coverage drift")


def _reduce_prevalidated_pt1_statistics(
        design: NaturalPT1Design,
        population: Mapping[tuple[str, int, str, int, int],
                            NaturalPT1State | PT1PopulationStateIdentity],
        records: Sequence[PT1Record | Mapping[str, object] | bytes], *,
        seeds: Sequence[int], bootstrap_seed: int) -> PT1StatisticsReport:
    """Reduce a population whose appropriate validator already succeeded."""
    fixed_seeds = _require_fixed_seeds(seeds)
    if bootstrap_seed != BOOTSTRAP_SEED:
        raise PT1StatisticsError("PT1 requires the fixed bootstrap seed")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise PT1StatisticsError("records must be a sequence")
    # Reopen every record before binding or calculating any aggregate.
    verified = []
    for item in records:
        try:
            verified.append(verify_record(item))
        except PrivilegedTeacherPT0Error as exc:
            raise PT1StatisticsError("PT1 record verification refusal") from exc
    if len(verified) != TOTAL_RECORD_COUNT:
        raise PT1StatisticsError("PT1 record population must contain exactly 1664 records")

    state_by_identity = {}
    for key in design.state_keys:
        state = population[key]
        identity = (state.public_state_sha256, state.true_world_sha256)
        if identity in state_by_identity:
            raise PT1StatisticsError("duplicate natural state public/true identity")
        state_by_identity[identity] = (key, state)
    records_by_identity = {}
    for record in verified:
        identity = (record.public_state_sha256, record.true_world_sha256)
        if identity not in state_by_identity:
            raise PT1StatisticsError("record is not bound to natural population state")
        seed = _record_seed(record)
        slot = (identity, seed)
        if slot in records_by_identity:
            raise PT1StatisticsError("duplicate state policy seed record")
        records_by_identity[slot] = record
    expected_slots = {(identity, seed)
                      for identity in state_by_identity for seed in fixed_seeds}
    if set(records_by_identity) != expected_slots:
        raise PT1StatisticsError("state policy seed records incomplete or duplicated")

    rows = []
    for key in design.state_keys:
        state = population[key]
        identity = (state.public_state_sha256, state.true_world_sha256)
        state_records = [records_by_identity[(identity, seed)] for seed in fixed_seeds]
        deltas = [_record_deltas(record) for record in state_records]
        flips = {
            "A_B": sum(record.arms[0].selected_action != record.arms[1].selected_action
                       for record in state_records),
            "B_C": sum(record.arms[1].selected_action != record.arms[2].selected_action
                       for record in state_records),
            "A_C": sum(record.arms[0].selected_action != record.arms[2].selected_action
                       for record in state_records),
        }
        rows.append(PT1StateStatistic(
            state.rank, state.banker, state.role, state.remaining_hand_threshold,
            state.replicate, len(state_records), _mean([d[0] for d in deltas]),
            _mean([d[1] for d in deltas]), _mean([d[2] for d in deltas]),
            sum(d[0] > 0 for d in deltas), flips["A_B"], flips["B_C"],
            flips["A_C"]))
    rows = tuple(rows)
    mean_cb = _mean([row.mean_cb for row in rows])
    bootstrap_lcb = _bootstrap(
        [row.mean_cb for row in rows], seed=bootstrap_seed,
        replicates=BOOTSTRAP_REPLICATES)
    strata = _strata(rows)
    flip_totals = (
        ("A_B", sum(row.action_flips_ab for row in rows), TOTAL_RECORD_COUNT),
        ("B_C", sum(row.action_flips_bc for row in rows), TOTAL_RECORD_COUNT),
        ("A_C", sum(row.action_flips_ac for row in rows), TOTAL_RECORD_COUNT),
    )
    role_gate = all(_mean([r.mean_cb for r in rows if r.role == role]) >= 0
                    for role in ("banker-team", "attacker-team"))
    horizon_gate = all(_mean([r.mean_cb for r in rows
                              if r.remaining_hand_threshold == threshold]) >= 0
                       for threshold in (3, 4))
    gates = (
        ("population_complete", len(rows) == TARGET_STATE_COUNT),
        ("records_complete", len(verified) == TOTAL_RECORD_COUNT),
        ("fixed_seed_complete", True),
        ("mean_cb_floor", mean_cb >= Fraction(1, 100)),
        ("bootstrap_lcb_positive", bootstrap_lcb > 0),
        ("positive_state_count", sum(row.mean_cb > 0 for row in rows) >= 24),
        ("zero_c_regret", all(record.c_regret == 0 for record in verified)),
        ("no_negative_state_cb", all(row.mean_cb >= 0 for row in rows)),
        ("no_negative_state_ca", all(row.mean_ca >= 0 for row in rows)),
        ("role_means_nonnegative", role_gate),
        ("horizon_means_nonnegative", horizon_gate),
    )
    status = PASS_STATUS if all(value for _, value in gates) else REFUSED_STATUS
    return PT1StatisticsReport(
        hashlib.sha256(canonical_json_bytes(design.payload())).hexdigest(),
        _population_identity(design, population), fixed_seeds, len(rows),
        len(verified), rows, strata, flip_totals, mean_cb, bootstrap_seed,
        BOOTSTRAP_REPLICATES, bootstrap_lcb,
        sum(row.mean_cb > 0 for row in rows), 0, gates, status, dict(AUTHORITY))


def reduce_pt1_statistics(
        design: NaturalPT1Design,
        population: Mapping[tuple[str, int, str, int, int], NaturalPT1State],
        records: Sequence[PT1Record | Mapping[str, object] | bytes], *,
        seeds: Sequence[int] = POLICY_SEEDS,
        bootstrap_seed: int = BOOTSTRAP_SEED) -> PT1StatisticsReport:
    """Verify and reduce exactly one four-seed record set per natural state."""
    if type(design) is not NaturalPT1Design:
        raise PT1StatisticsError("statistics require NaturalPT1Design")
    try:
        validate_population(design, population)
    except (PrivilegedTeacherPT0Error, PrivilegedTeacherPT1Error) as exc:
        raise PT1StatisticsError("natural population integrity refusal") from exc
    return _reduce_prevalidated_pt1_statistics(
        design, population, records, seeds=seeds,
        bootstrap_seed=bootstrap_seed)


def reduce_reopened_pt1_statistics(
        design: NaturalPT1Design,
        population: Mapping[tuple[str, int, str, int, int],
                            PT1PopulationStateIdentity],
        records: Sequence[PT1Record | Mapping[str, object] | bytes], *,
        seeds: Sequence[int] = POLICY_SEEDS,
        bootstrap_seed: int = BOOTSTRAP_SEED) -> PT1StatisticsReport:
    """Reduce exact group-reopened identities after manifest validation."""
    validate_reopened_population(design, population)
    return _reduce_prevalidated_pt1_statistics(
        design, population, records, seeds=seeds,
        bootstrap_seed=bootstrap_seed)


def _report_from_payload(payload: Mapping[str, object]) -> PT1StatisticsReport:
    state_rows = []
    for row in payload["state_statistics"]:
        flips = row["action_flips"]
        state_rows.append(PT1StateStatistic(
            row["trump_rank"], row["banker"], row["role"],
            row["remaining_hand_threshold"], row["replicate"],
            row["replicate_count"],
            _fraction(row["mean_cb"], "state mean C-B"),
            _fraction(row["mean_ba"], "state mean B-A"),
            _fraction(row["mean_ca"], "state mean C-A"),
            row["positive_seed_cb"], flips["A_B"], flips["B_C"], flips["A_C"]))
    strata = tuple(PT1StratumStatistic(
        row["dimension"], row["value"], row["state_count"],
        _fraction(row["mean_cb"], "stratum mean C-B"),
        row["positive_state_count"]) for row in payload["strata"])
    doses = tuple((name, payload["action_flip_dose"][name]["flips"],
                   payload["action_flip_dose"][name]["total"])
                  for name in ("A_B", "B_C", "A_C"))
    return PT1StatisticsReport(
        payload["design_sha256"], payload["population_sha256"],
        tuple(payload["seeds"]), payload["state_count"], payload["record_count"],
        tuple(state_rows), strata, doses, _fraction(payload["mean_cb"], "mean C-B"),
        payload["bootstrap"]["seed"], payload["bootstrap"]["replicates"],
        _fraction(payload["bootstrap"]["one_sided_95_lcb_cb"], "bootstrap LCB"),
        payload["positive_state_count"], payload["c_regret_nonzero_count"],
        tuple((name, payload["gate_results"][name]) for name in (
            "population_complete", "records_complete", "fixed_seed_complete",
            "mean_cb_floor", "bootstrap_lcb_positive", "positive_state_count",
            "zero_c_regret", "no_negative_state_cb", "no_negative_state_ca",
            "role_means_nonnegative", "horizon_means_nonnegative")),
        payload["status"], dict(payload["authority"]), payload["schema"])


def verify_statistics_report(
        report: PT1StatisticsReport | Mapping[str, object] | bytes,
        *, design: NaturalPT1Design | None = None) -> PT1StatisticsReport:
    """Strictly reopen a canonical report and verify its internal contract."""
    import json
    if isinstance(report, bytes):
        raw = report
        try:
            report = json.loads(report.decode("ascii"))
        except Exception as exc:
            raise PT1StatisticsError("statistics report is not canonical") from exc
        if canonical_json_bytes(report) != raw:
            raise PT1StatisticsError("statistics report is not canonical")
    if isinstance(report, PT1StatisticsReport):
        payload = report.payload()
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        raise PT1StatisticsError("statistics report type refused")
    required = {"schema", "design_sha256", "population_sha256", "seeds",
                "state_count", "record_count", "state_statistics", "strata",
                "action_flip_dose", "mean_cb", "bootstrap",
                "positive_state_count", "c_regret_nonzero_count", "gate_results",
                "status", "authority",
                "report_sha256"}
    if set(payload) != required or payload["schema"] != STATISTICS_REPORT_SCHEMA:
        raise PT1StatisticsError("statistics report fields/schema drift")
    _sha(payload["design_sha256"], "design identity")
    _sha(payload["population_sha256"], "population identity")
    _sha(payload["report_sha256"], "statistics report")
    body = {key: payload[key] for key in required if key != "report_sha256"}
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != payload["report_sha256"]:
        raise PT1StatisticsError("statistics report hash drift")
    if design is not None:
        expected = hashlib.sha256(canonical_json_bytes(design.payload())).hexdigest()
        if payload["design_sha256"] != expected:
            raise PT1StatisticsError("statistics design identity drift")
    if payload["seeds"] != list(POLICY_SEEDS) or payload["state_count"] != TARGET_STATE_COUNT \
            or payload["record_count"] != TOTAL_RECORD_COUNT:
        raise PT1StatisticsError("statistics population contract drift")
    if payload["authority"] != AUTHORITY:
        raise PT1StatisticsError("statistics authority drift")
    if payload["bootstrap"]["replicates"] != BOOTSTRAP_REPLICATES:
        raise PT1StatisticsError("statistics bootstrap contract drift")
    typed = _report_from_payload(payload)
    if len(typed.state_statistics) != TARGET_STATE_COUNT:
        raise PT1StatisticsError("statistics state rows drift")
    row_keys = tuple((row.rank, row.banker, row.role,
                      row.remaining_hand_threshold, row.replicate)
                     for row in typed.state_statistics)
    if design is not None and row_keys != design.state_keys:
        raise PT1StatisticsError("statistics state order drift")
    if len(set(row_keys)) != TARGET_STATE_COUNT \
            or any(row.replicate_count != RECORDS_PER_STATE
                   or not 0 <= row.replicate < RECORDS_PER_STATE
                   or any(value < 0 or value > RECORDS_PER_STATE for value in (
                       row.positive_seed_cb, row.action_flips_ab,
                       row.action_flips_bc, row.action_flips_ac))
                   for row in typed.state_statistics):
        raise PT1StatisticsError("statistics state replicate drift")
    if typed.mean_cb != _mean([row.mean_cb for row in typed.state_statistics]):
        raise PT1StatisticsError("statistics mean C-B drift")
    if typed.positive_state_count != sum(
            row.mean_cb > 0 for row in typed.state_statistics):
        raise PT1StatisticsError("statistics positive-state count drift")
    if typed.c_regret_nonzero_count != 0:
        raise PT1StatisticsError("statistics C-regret count drift")
    if typed.bootstrap_seed != BOOTSTRAP_SEED:
        raise PT1StatisticsError("statistics bootstrap seed drift")
    expected_doses = (
        ("A_B", sum(row.action_flips_ab for row in typed.state_statistics),
         TOTAL_RECORD_COUNT),
        ("B_C", sum(row.action_flips_bc for row in typed.state_statistics),
         TOTAL_RECORD_COUNT),
        ("A_C", sum(row.action_flips_ac for row in typed.state_statistics),
         TOTAL_RECORD_COUNT),
    )
    if typed.action_flip_dose != expected_doses:
        raise PT1StatisticsError("statistics action-flip dose drift")
    if typed.strata != _strata(typed.state_statistics):
        raise PT1StatisticsError("statistics strata drift")
    if typed.bootstrap_lcb_cb != _bootstrap(
            [row.mean_cb for row in typed.state_statistics],
            seed=typed.bootstrap_seed, replicates=typed.bootstrap_replicates):
        raise PT1StatisticsError("statistics bootstrap drift")
    expected_gate_names = {
        "population_complete", "records_complete", "fixed_seed_complete",
        "mean_cb_floor", "bootstrap_lcb_positive", "positive_state_count",
        "zero_c_regret", "no_negative_state_cb", "no_negative_state_ca",
        "role_means_nonnegative", "horizon_means_nonnegative"}
    if set(name for name, _ in typed.gate_results) != expected_gate_names \
            or any(type(value) is not bool for _, value in typed.gate_results):
        raise PT1StatisticsError("statistics gate population drift")
    role_gate = all(_mean([row.mean_cb for row in typed.state_statistics
                           if row.role == role]) >= 0
                    for role in ("banker-team", "attacker-team"))
    horizon_gate = all(_mean([row.mean_cb for row in typed.state_statistics
                              if row.remaining_hand_threshold == threshold]) >= 0
                       for threshold in (3, 4))
    expected_gates = {
        "population_complete": True, "records_complete": True,
        "fixed_seed_complete": True,
        "mean_cb_floor": typed.mean_cb >= Fraction(1, 100),
        "bootstrap_lcb_positive": typed.bootstrap_lcb_cb > 0,
        "positive_state_count": typed.positive_state_count >= 24,
        "zero_c_regret": typed.c_regret_nonzero_count == 0,
        "no_negative_state_cb": all(row.mean_cb >= 0
                                     for row in typed.state_statistics),
        "no_negative_state_ca": all(row.mean_ca >= 0
                                     for row in typed.state_statistics),
        "role_means_nonnegative": role_gate,
        "horizon_means_nonnegative": horizon_gate,
    }
    if dict(typed.gate_results) != expected_gates:
        raise PT1StatisticsError("statistics gate evaluation drift")
    expected_status = PASS_STATUS if all(value for _, value in typed.gate_results) else REFUSED_STATUS
    if typed.status != expected_status:
        raise PT1StatisticsError("statistics gate/status drift")
    return typed


run_pt1_statistics = reduce_pt1_statistics

__all__ = [
    "BOOTSTRAP_REPLICATES", "BOOTSTRAP_SEED", "PASS_STATUS", "POLICY_SEEDS",
    "PT1PopulationStateIdentity", "PT1StatisticsError", "PT1StatisticsReport",
    "PT1StateStatistic",
    "PT1StratumStatistic", "REFUSED_STATUS", "RECORDS_PER_STATE",
    "STATISTICS_REPORT_SCHEMA", "STATISTICS_SCHEMA", "TOTAL_RECORD_COUNT",
    "reduce_pt1_statistics", "reduce_reopened_pt1_statistics",
    "run_pt1_statistics", "validate_reopened_population",
    "verify_statistics_report",
]
