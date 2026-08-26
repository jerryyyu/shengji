"""Open-DEV full-play search-consumer ladder over sealed PT-Full roots.

The parent A/B report already established that the current production search
does not turn an exact hidden world into stronger play.  This module reopens
that population and varies only the decision objective, ballot and named
public-style continuation.  It contains no learned or deployable policy.
"""

from __future__ import annotations

import copy
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import time
from typing import Callable, Mapping

from ..ai.smart import SmartBot
from ..engine.cards import RANKS, total_points
from ..engine.combos import decompose
from ..engine.round import Round
from . import privileged_teacher_full_ab as full
from .privileged_teacher_pt0 import canonical_json_bytes, signed_level_utility


SCHEMA = "privileged-teacher-c0-full-play-dev-v1"
RECORD_SCHEMA = "privileged-teacher-c0-full-play-record-v1"
DESIGN_SCHEMA = "privileged-teacher-c0-full-play-design-v1"
DEV_NAMESPACE = "privileged-teacher-c0-full-play-open-dev-v1"
ARMS = ("C0-P", "C0-H", "C0-S")
ROLES = full.ROLES
MINI_HOSTNAME = full.MINI_HOSTNAME
AUTHORITY = dict(full.AUTHORITY)
TELEMETRY_FIELDS = (
    "treatment_decisions",
    "contested_decisions",
    "candidate_count_sum",
    "selected_differs_from_candidate_zero",
    "selected_outside_production_ballot",
    "bare_point_avoidance",
    "bare_point_introduction",
    "positive_exact_gap",
    "zero_exact_gap",
    "negative_exact_gap",
)


class PrivilegedTeacherC0Error(ValueError):
    """The parent binding, exact work, mechanism or result drifted."""


def _sha(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _strict_sha(value: object, label: str, *, length: int = 64) -> str:
    if (type(value) is not str or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)):
        raise PrivilegedTeacherC0Error(f"{label} drift")
    return value


@dataclass(frozen=True)
class C0Design:
    seed_commitment_sha256: str
    execution_git: str
    native_sha256: str
    hostname: str
    parent_external_sha256: str
    parent_report_sha256: str
    parent_execution_git: str
    namespace: str = DEV_NAMESPACE

    def __post_init__(self) -> None:
        _strict_sha(self.seed_commitment_sha256, "seed commitment")
        _strict_sha(self.execution_git, "execution Git", length=40)
        _strict_sha(self.native_sha256, "native identity")
        _strict_sha(self.parent_external_sha256, "parent external identity")
        _strict_sha(self.parent_report_sha256, "parent report identity")
        _strict_sha(self.parent_execution_git, "parent execution Git", length=40)
        if self.hostname != MINI_HOSTNAME:
            raise PrivilegedTeacherC0Error("execution hostname drift")
        if self.namespace != DEV_NAMESPACE:
            raise PrivilegedTeacherC0Error("C0 namespace drift")

    @property
    def root_coordinates(self) -> tuple[tuple[str, int, int], ...]:
        return tuple((rank, banker, 0)
                     for rank in RANKS for banker in full.BANKER_SEATS)

    def payload(self) -> dict[str, object]:
        return {
            "schema": DESIGN_SCHEMA,
            "namespace": self.namespace,
            "seed_commitment_sha256": self.seed_commitment_sha256,
            "execution_git": self.execution_git,
            "native_sha256": self.native_sha256,
            "hostname": self.hostname,
            "parent_external_sha256": self.parent_external_sha256,
            "parent_report_sha256": self.parent_report_sha256,
            "parent_execution_git": self.parent_execution_git,
            "parent_root_count": len(self.root_coordinates),
            "record_count": len(self.root_coordinates) * len(ROLES),
            "played_round_count": (
                len(self.root_coordinates) * len(ROLES) * len(ARMS)),
            "trump_ranks": list(RANKS),
            "banker_seats": list(full.BANKER_SEATS),
            "roles": list(ROLES),
            "arms": list(ARMS),
            "authority": dict(AUTHORITY),
        }


class C0ProductionBallotBot(full.TrueWorldProductionBot):
    """One exact-world evaluation per production candidate."""

    N_DETERMINIZATIONS = 1
    REQUIRE_EXACT_WORK = True
    EXTRA_SELECTION_WORK = 0
    CONFIDENCE_OVERRIDE = False
    ADAPTIVE_ALLOCATION = False
    RANDOM_ALLOCATION = False
    REPORT_FOLD_WORLDS = 0
    REPORT_RULE = "none"
    REPORT_MIN_GAIN = 0.0
    MARGIN = 0.0
    LEVEL_OBJECTIVE = True
    POINT_SHY_EPS = 0.0
    EXACT_ENDGAME = False

    def _score(self, attacker_pts: float) -> float:
        """Exact signed one-round level utility from the attacker side."""
        if (isinstance(attacker_pts, bool)
                or not isinstance(attacker_pts, (int, float))
                or not math.isfinite(attacker_pts)
                or attacker_pts < 0):
            raise PrivilegedTeacherC0Error("C0 terminal score drift")
        if isinstance(attacker_pts, float) and not attacker_pts.is_integer():
            raise PrivilegedTeacherC0Error("C0 terminal score drift")
        points = int(attacker_pts)
        if points >= 80:
            return float(max(1, (points - 80) // 40))
        return float(-(3 if points == 0 else 2 if points < 40 else 1))


class C0WideHeuristicBot(C0ProductionBallotBot):
    """One exact world, expanded bounded ballot, current continuation."""

    TRACTOR_LOCK = False
    RETAIN_ALL_LEAD_PAIRS = True
    V3_LEAD_SINGLES = True
    V3_LEAD_RANDOM = False
    RISKY_THROWS = True
    TRUMP_BALLOT = True
    LEAD_MAX_CANDIDATES = 64
    FOLLOW_MAX_CANDIDATES = 64


class C0WideSmartBot(C0WideHeuristicBot):
    """C0-H ballot and objective with the named SmartBot continuation."""

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        self.rollout_policy = SmartBot()


ARM_CLASSES = {
    "C0-P": C0ProductionBallotBot,
    "C0-H": C0WideHeuristicBot,
    "C0-S": C0WideSmartBot,
}


@dataclass(frozen=True)
class C0Outcome:
    arm: str
    attacker_points: int
    signed_level_utility: int
    decision_count: int
    work: Mapping[str, int]
    telemetry: Mapping[str, int]

    def payload(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "attacker_points": self.attacker_points,
            "signed_level_utility": self.signed_level_utility,
            "decision_count": self.decision_count,
            "work": dict(self.work),
            "telemetry": dict(self.telemetry),
        }


def _parent_design(report: Mapping[str, object]) -> full.FullABDesign:
    payload = report.get("design")
    if type(payload) is not dict:
        raise PrivilegedTeacherC0Error("parent design drift")
    try:
        return full.FullABDesign(
            seed_commitment_sha256=payload["seed_commitment_sha256"],
            execution_git=payload["execution_git"],
            native_sha256=payload["native_sha256"],
            hostname=payload["hostname"],
            replicates=payload["replicates"],
            production_policy=payload["production_policy"],
            namespace=payload["namespace"],
        )
    except (KeyError, TypeError, full.PrivilegedTeacherFullABError) as exc:
        raise PrivilegedTeacherC0Error("parent design drift") from exc


def validate_parent(report: dict[str, object], design: C0Design) \
        -> full.FullABDesign:
    parent_design = _parent_design(report)
    try:
        full.validate_report(report, parent_design)
    except full.PrivilegedTeacherFullABError as exc:
        raise PrivilegedTeacherC0Error("parent report refused") from exc
    if (hashlib.sha256(canonical_json_bytes(report)).hexdigest() !=
            design.parent_external_sha256
            or report.get("report_sha256") != design.parent_report_sha256
            or parent_design.execution_git != design.parent_execution_git
            or parent_design.seed_commitment_sha256 !=
            design.seed_commitment_sha256
            or parent_design.hostname != design.hostname
            or parent_design.root_coordinates != design.root_coordinates):
        raise PrivilegedTeacherC0Error("parent report identity drift")
    return parent_design


def _parent_records(report: Mapping[str, object]) \
        -> dict[tuple[str, int, int, str], dict[str, object]]:
    rows = report.get("records")
    if type(rows) is not list:
        raise PrivilegedTeacherC0Error("parent record population drift")
    result = {}
    for row in rows:
        if type(row) is not dict:
            raise PrivilegedTeacherC0Error("parent record population drift")
        key = (row.get("trump_rank"), row.get("banker"),
               row.get("replicate"), row.get("role"))
        if key in result:
            raise PrivilegedTeacherC0Error("parent record population drift")
        result[key] = row
    return result


def _production_ballot(rnd: Round, seat: int) -> set[tuple[str, ...]]:
    probe = full._Production(seed=0)
    if probe.TRACTOR_LOCK and not rnd.trick.plays:
        pick = probe.canonical_lead(rnd, seat)
        dec = decompose(pick, rnd.ordering)
        if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
            return {tuple(sorted(pick))}
    return {tuple(sorted(action)) for action in probe._candidates(rnd, seat)}


def _verify_c0_decision_work(bot: object) -> int:
    record = getattr(bot, "last_decision_record", None)
    if record is None:
        return 0
    work = record.get("work")
    allocation = record.get("alloc")
    sampler = record.get("sampler_counters", {}).get("delta")
    n_by = allocation.get("n_by_candidate") if type(allocation) is dict \
        else None
    candidate_count = len(n_by) if type(n_by) is list else 0
    if (type(work) is not dict
            or type(allocation) is not dict
            or type(sampler) is not dict
            or type(n_by) is not list
            or candidate_count < 2
            or any(type(value) is not int or value != 1 for value in n_by)
            or set(sampler) != {
                "sample_attempts", "accepted_worlds", "failed_worlds",
                "rejected_worlds", "impossible_worlds"}
            or any(type(value) is not int or value < 0
                   for value in sampler.values())
            or record.get("n_determinizations") != 1
            or record.get("report_worlds_requested") != 0
            or record.get("report_rule") != "none"
            or record.get("margin") != 0.0
            or allocation.get("mode") != "uniform"
            or allocation.get("worlds") != 1
            or allocation.get("short") is not False
            or work.get("selection_budget") != candidate_count
            or work.get("selection_rollouts") != candidate_count
            or work.get("report_budget") != 0
            or work.get("report_rollouts") != 0
            or work.get("total_budget") != candidate_count
            or work.get("total_rollouts") != candidate_count
            or work.get("complete") is not True
            or sampler.get("sample_attempts") != 1
            or sampler.get("accepted_worlds") != 1
            or sampler.get("failed_worlds") != 0
            or sampler.get("rejected_worlds") != 0):
        raise PrivilegedTeacherC0Error("C0 contested decision exact work drift")
    return candidate_count


def _bots(seed_secret: bytes, rank: str, banker: int, replicate: int, *,
          arm: str, treatment_team: int) -> list[object]:
    if arm not in ARMS or treatment_team not in (0, 1):
        raise PrivilegedTeacherC0Error("C0 arm or treatment identity drift")
    cls = ARM_CLASSES[arm]
    return [
        (cls if seat % 2 == treatment_team else full._Production)(
            seed=full._policy_seed(
                seed_secret, rank, banker, replicate, seat))
        for seat in range(4)
    ]


def _telemetry() -> dict[str, int]:
    return {field: 0 for field in TELEMETRY_FIELDS}


def _observe_decision(telemetry: dict[str, int], bot: object, *,
                      was_lead: bool,
                      production_ballot: set[tuple[str, ...]]) -> int:
    telemetry["treatment_decisions"] += 1
    record = getattr(bot, "last_decision_record", None)
    if record is None:
        return 0
    verified = _verify_c0_decision_work(bot)
    candidates = record.get("candidates")
    means = record.get("means")
    played_index = record.get("played_index")
    if (type(candidates) is not list or len(candidates) != verified
            or type(means) is not list or len(means) != verified
            or isinstance(played_index, bool)
            or not isinstance(played_index, int)
            or not 0 <= played_index < verified
            or any(not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in means)):
        raise PrivilegedTeacherC0Error("C0 decision telemetry drift")
    telemetry["contested_decisions"] += 1
    telemetry["candidate_count_sum"] += verified
    selected = tuple(sorted(candidates[played_index]))
    incumbent = tuple(sorted(candidates[0]))
    changed = selected != incumbent
    telemetry["selected_differs_from_candidate_zero"] += int(changed)
    telemetry["selected_outside_production_ballot"] += int(
        selected not in production_ballot)
    selected_points = total_points(selected)
    incumbent_points = total_points(incumbent)
    single_swap = len(incumbent) == len(selected) == 1
    telemetry["bare_point_avoidance"] += int(
        was_lead and single_swap and changed
        and incumbent_points > 0 and selected_points == 0)
    telemetry["bare_point_introduction"] += int(
        was_lead and single_swap and changed
        and incumbent_points == 0 and selected_points > 0)
    gap = means[played_index] - means[0]
    telemetry["positive_exact_gap"] += int(gap > 0)
    telemetry["zero_exact_gap"] += int(gap == 0)
    telemetry["negative_exact_gap"] += int(gap < 0)
    return verified


def _play_arm(root: Round, *, rank: str, banker: int, replicate: int,
              arm: str, treatment_team: int,
              seed_secret: bytes) -> C0Outcome:
    rnd = copy.deepcopy(root)
    rnd._ptfull_true_world = True
    bots = _bots(seed_secret, rank, banker, replicate, arm=arm,
                 treatment_team=treatment_team)
    telemetry = _telemetry()
    decisions = 0
    validated_searches = 0
    verified_rollouts = 0
    while rnd.phase == "play":
        seat = rnd.turn
        if seat is None:
            raise PrivilegedTeacherC0Error("C0 play round lost turn")
        treatment = seat % 2 == treatment_team
        was_lead = not rnd.trick.plays
        production_ballot = (_production_ballot(rnd, seat)
                             if treatment else set())
        cards = bots[seat].decide_play(rnd, seat)
        if treatment:
            verified = _observe_decision(
                telemetry, bots[seat], was_lead=was_lead,
                production_ballot=production_ballot)
        else:
            try:
                verified = full._verify_decision_work(bots[seat])
            except full.PrivilegedTeacherFullABError as exc:
                raise PrivilegedTeacherC0Error(
                    "C0 opponent exact work drift") from exc
        validated_searches += int(verified > 0)
        verified_rollouts += verified
        rnd.play(seat, cards)
        decisions += 1
    if rnd.phase != "round_end" or rnd.banker is None:
        raise PrivilegedTeacherC0Error("C0 arm did not complete round")
    work = full._work(bots)
    work["verified_rollouts"] = verified_rollouts
    production_searches = work["search_calls"] - telemetry["contested_decisions"]
    if (production_searches < 0
            or validated_searches != work["search_calls"]
            or telemetry["candidate_count_sum"] > verified_rollouts
            or work["short_search_decisions"] != 0
            or work["zero_world_decisions"] != 0
            or work["sample_attempts"] != (
                work["accepted_worlds"] + work["failed_worlds"])
            or work["accepted_worlds"] != (
                telemetry["contested_decisions"] + 330 * production_searches)
            or work["rejected_worlds"] > work["failed_worlds"]
            or work["rollouts"] != verified_rollouts
            or work["rollouts"] < (
                telemetry["candidate_count_sum"] +
                660 * production_searches)):
        raise PrivilegedTeacherC0Error("C0 arm exact work receipt drift")
    return C0Outcome(
        arm=arm,
        attacker_points=rnd.attacker_points,
        signed_level_utility=signed_level_utility(
            rnd.attacker_points, banker_seat=rnd.banker,
            perspective_seat=treatment_team),
        decision_count=decisions,
        work=work,
        telemetry=telemetry,
    )


def _anchor(parent: Mapping[str, object], arm: str) -> dict[str, int]:
    arms = parent.get("arms")
    row = arms.get(arm) if type(arms) is dict else None
    if type(row) is not dict:
        raise PrivilegedTeacherC0Error("parent anchor drift")
    return {
        "attacker_points": row["attacker_points"],
        "signed_level_utility": row["signed_level_utility"],
    }


def _record_payload(*, coordinate: tuple[str, int, int], role: str,
                    parent: Mapping[str, object],
                    outcomes: tuple[C0Outcome, ...]) -> dict[str, object]:
    rank, banker, replicate = coordinate
    if role not in ROLES or tuple(row.arm for row in outcomes) != ARMS:
        raise PrivilegedTeacherC0Error("C0 comparison arm drift")
    anchors = {arm: _anchor(parent, arm) for arm in ("A", "B")}
    arms = {row.arm: row.payload() for row in outcomes}
    utilities = {**{key: row["signed_level_utility"]
                    for key, row in anchors.items()},
                 **{key: row["signed_level_utility"]
                    for key, row in arms.items()}}
    contrasts = {
        "c0_p_minus_a": utilities["C0-P"] - utilities["A"],
        "c0_p_minus_b": utilities["C0-P"] - utilities["B"],
        "c0_h_minus_a": utilities["C0-H"] - utilities["A"],
        "c0_h_minus_b": utilities["C0-H"] - utilities["B"],
        "c0_h_minus_c0_p": utilities["C0-H"] - utilities["C0-P"],
        "c0_s_minus_a": utilities["C0-S"] - utilities["A"],
        "c0_s_minus_b": utilities["C0-S"] - utilities["B"],
        "c0_s_minus_c0_h": utilities["C0-S"] - utilities["C0-H"],
    }
    body = {
        "schema": RECORD_SCHEMA,
        "trump_rank": rank,
        "banker": banker,
        "replicate": replicate,
        "role": role,
        "treatment_team": parent["treatment_team"],
        "root_sha256": parent["root_sha256"],
        "parent_record_sha256": parent["record_sha256"],
        "anchors": anchors,
        "arms": arms,
        "contrasts": contrasts,
        "authority": dict(AUTHORITY),
    }
    return {**body, "record_sha256": _sha(body)}


def _run_root(design: C0Design, parent_design: full.FullABDesign,
              parent_records: Mapping[
                  tuple[str, int, int, str], dict[str, object]],
              seed_secret: bytes, coordinate: tuple[str, int, int]) \
        -> tuple[dict[str, object], ...]:
    rank, banker, replicate = coordinate
    root = full._build_root(
        parent_design, seed_secret, rank, banker, replicate)
    root_sha256 = full._root_sha256(root)
    records = []
    for role in ROLES:
        parent = parent_records.get((*coordinate, role))
        if type(parent) is not dict or parent.get("root_sha256") != root_sha256:
            raise PrivilegedTeacherC0Error("reconstructed parent root drift")
        banker_team = banker % 2
        treatment = banker_team if role == "banker-team" else 1 - banker_team
        outcomes = tuple(_play_arm(
            root, rank=rank, banker=banker, replicate=replicate, arm=arm,
            treatment_team=treatment, seed_secret=seed_secret) for arm in ARMS)
        records.append(_record_payload(
            coordinate=coordinate, role=role, parent=parent,
            outcomes=outcomes))
    return tuple(records)


CONTRASTS = (
    "c0_p_minus_a", "c0_p_minus_b",
    "c0_h_minus_a", "c0_h_minus_b", "c0_h_minus_c0_p",
    "c0_s_minus_a", "c0_s_minus_b", "c0_s_minus_c0_h",
)


def _fraction(values: list[int]) -> dict[str, int]:
    if not values:
        raise PrivilegedTeacherC0Error("empty C0 contrast population")
    value = Fraction(sum(values), len(values))
    return {"numerator": value.numerator, "denominator": value.denominator}


def _contrast_summary(records: list[dict[str, object]],
                      name: str) -> dict[str, object]:
    values = [row["contrasts"][name] for row in records]
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in values):
        raise PrivilegedTeacherC0Error("C0 contrast value drift")
    return {
        "mean": _fraction(values),
        "positive_count": sum(value > 0 for value in values),
        "zero_count": sum(value == 0 for value in values),
        "negative_count": sum(value < 0 for value in values),
    }


def _summaries(records: list[dict[str, object]]) -> dict[str, object]:
    result = {name: _contrast_summary(records, name) for name in CONTRASTS}
    result["by_role"] = {
        role: {name: _contrast_summary(
            [row for row in records if row["role"] == role], name)
               for name in CONTRASTS}
        for role in ROLES
    }
    result["by_rank"] = {
        rank: {name: _contrast_summary(
            [row for row in records if row["trump_rank"] == rank], name)
               for name in CONTRASTS}
        for rank in RANKS
    }
    result["telemetry_totals"] = {
        arm: {field: sum(row["arms"][arm]["telemetry"][field]
                        for row in records)
              for field in TELEMETRY_FIELDS}
        for arm in ARMS
    }
    return result


def run_dev(design: C0Design, *, parent_report: dict[str, object],
            seed_secret: bytes, workers: int = 1,
            progress_sink: Callable[[dict[str, object]], object] | None = None,
            parent_external_sha256: str) -> dict[str, object]:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise PrivilegedTeacherC0Error("workers must be positive integer")
    if (hashlib.sha256(seed_secret).hexdigest() !=
            design.seed_commitment_sha256):
        raise PrivilegedTeacherC0Error("seed secret commitment drift")
    if parent_external_sha256 != design.parent_external_sha256:
        raise PrivilegedTeacherC0Error("parent external identity drift")
    parent_design = validate_parent(parent_report, design)
    parent_records = _parent_records(parent_report)
    started = time.monotonic()
    coordinates = design.root_coordinates
    completed: dict[tuple[str, int, int], tuple[dict[str, object], ...]] = {}

    def publish() -> None:
        done = len(completed)
        elapsed = time.monotonic() - started
        eta = None if done == 0 else max(
            0.0, elapsed * (len(coordinates) - done) / done)
        if progress_sink is not None:
            progress_sink({
                "completed_roots": done,
                "total_roots": len(coordinates),
                "percent_basis_points": done * 10_000 // len(coordinates),
                "elapsed_seconds": elapsed,
                "eta_seconds": eta,
            })

    if workers == 1:
        for coordinate in coordinates:
            completed[coordinate] = _run_root(
                design, parent_design, parent_records,
                seed_secret, coordinate)
            publish()
    else:
        with ProcessPoolExecutor(max_workers=min(workers, len(coordinates))) as pool:
            futures = {
                pool.submit(_run_root, design, parent_design, parent_records,
                            seed_secret, coordinate): coordinate
                for coordinate in coordinates
            }
            for future in as_completed(futures):
                coordinate = futures[future]
                completed[coordinate] = future.result()
                publish()
    records = [row for coordinate in coordinates
               for row in completed[coordinate]]
    body = {
        "schema": SCHEMA,
        "status": "COMPLETE",
        "design": design.payload(),
        "completed_roots": len(completed),
        "record_count": len(records),
        "played_round_count": (
            len(coordinates) * len(ROLES) * len(ARMS)),
        "records": records,
        "summaries": _summaries(records),
        "elapsed_seconds": time.monotonic() - started,
        "authority": dict(AUTHORITY),
    }
    return {**body, "report_sha256": _sha(body)}


def _validate_telemetry(arm: str, telemetry: object) -> None:
    if (type(telemetry) is not dict
            or tuple(telemetry) != TELEMETRY_FIELDS
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in telemetry.values())):
        raise PrivilegedTeacherC0Error("C0 telemetry shape drift")
    contested = telemetry["contested_decisions"]
    changed = telemetry["selected_differs_from_candidate_zero"]
    if (contested > telemetry["treatment_decisions"]
            or telemetry["candidate_count_sum"] < 2 * contested
            or changed > contested
            or telemetry["selected_outside_production_ballot"] > changed
            or telemetry["bare_point_avoidance"] > changed
            or telemetry["bare_point_introduction"] > changed
            or sum(telemetry[name] for name in (
                "positive_exact_gap", "zero_exact_gap",
                "negative_exact_gap")) != contested
            or (arm == "C0-P" and
                telemetry["selected_outside_production_ballot"] != 0)):
        raise PrivilegedTeacherC0Error("C0 telemetry accounting drift")


def validate_report(report: dict[str, object], design: C0Design,
                    parent_report: dict[str, object], *,
                    parent_external_sha256: str) -> None:
    if parent_external_sha256 != design.parent_external_sha256:
        raise PrivilegedTeacherC0Error("parent external identity drift")
    validate_parent(parent_report, design)
    parent_records = _parent_records(parent_report)
    if type(report) is not dict or set(report) != {
            "schema", "status", "design", "completed_roots", "record_count",
            "played_round_count", "records", "summaries", "elapsed_seconds",
            "authority", "report_sha256"}:
        raise PrivilegedTeacherC0Error("C0 report schema drift")
    body = {key: value for key, value in report.items()
            if key != "report_sha256"}
    records = report["records"]
    elapsed = report["elapsed_seconds"]
    if (report["schema"] != SCHEMA or report["status"] != "COMPLETE"
            or report["design"] != design.payload()
            or report["completed_roots"] != len(design.root_coordinates)
            or report["record_count"] != len(design.root_coordinates) * 2
            or report["played_round_count"] != (
                len(design.root_coordinates) * len(ROLES) * len(ARMS))
            or type(records) is not list
            or report["summaries"] != _summaries(records)
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed) or elapsed < 0
            or report["authority"] != AUTHORITY
            or report["report_sha256"] != _sha(body)):
        raise PrivilegedTeacherC0Error("C0 report identity drift")
    expected = {(*coordinate, role) for coordinate in design.root_coordinates
                for role in ROLES}
    actual = set()
    roots: dict[tuple[str, int, int], str] = {}
    for record in records:
        if type(record) is not dict or set(record) != {
                "schema", "trump_rank", "banker", "replicate", "role",
                "treatment_team", "root_sha256", "parent_record_sha256",
                "anchors", "arms", "contrasts", "authority",
                "record_sha256"}:
            raise PrivilegedTeacherC0Error("C0 record schema drift")
        key = (record["trump_rank"], record["banker"],
               record["replicate"], record["role"])
        coordinate = key[:3]
        parent = parent_records.get(key)
        record_body = {name: value for name, value in record.items()
                       if name != "record_sha256"}
        if (key not in expected or key in actual or type(parent) is not dict
                or record["schema"] != RECORD_SCHEMA
                or record["treatment_team"] != parent["treatment_team"]
                or record["root_sha256"] != parent["root_sha256"]
                or record["parent_record_sha256"] != parent["record_sha256"]
                or record["anchors"] != {
                    arm: _anchor(parent, arm) for arm in ("A", "B")}
                or record["authority"] != AUTHORITY
                or record["record_sha256"] != _sha(record_body)):
            raise PrivilegedTeacherC0Error("C0 record identity drift")
        roots.setdefault(coordinate, record["root_sha256"])
        if roots[coordinate] != record["root_sha256"]:
            raise PrivilegedTeacherC0Error("C0 root role binding drift")
        arms = record["arms"]
        if type(arms) is not dict or tuple(arms) != ARMS:
            raise PrivilegedTeacherC0Error("C0 arm population drift")
        for arm in ARMS:
            row = arms[arm]
            if (type(row) is not dict or set(row) != {
                    "arm", "attacker_points", "signed_level_utility",
                    "decision_count", "work", "telemetry"}
                    or row["arm"] != arm
                    or isinstance(row["attacker_points"], bool)
                    or not isinstance(row["attacker_points"], int)
                    or row["attacker_points"] < 0
                    or isinstance(row["decision_count"], bool)
                    or not isinstance(row["decision_count"], int)
                    or row["decision_count"] < 1
                    or type(row["work"]) is not dict
                    or set(row["work"]) != set(full._WORK_FIELDS)
                    or any(isinstance(value, bool)
                           or not isinstance(value, int) or value < 0
                           for value in row["work"].values())):
                raise PrivilegedTeacherC0Error("C0 arm receipt drift")
            _validate_telemetry(arm, row["telemetry"])
            telemetry = row["telemetry"]
            work = row["work"]
            production_searches = (
                work["search_calls"] - telemetry["contested_decisions"])
            expected_utility = signed_level_utility(
                row["attacker_points"], banker_seat=record["banker"],
                perspective_seat=record["treatment_team"])
            if (production_searches < 0
                    or row["signed_level_utility"] != expected_utility
                    or work["short_search_decisions"] != 0
                    or work["zero_world_decisions"] != 0
                    or work["sample_attempts"] != (
                        work["accepted_worlds"] + work["failed_worlds"])
                    or work["accepted_worlds"] != (
                        telemetry["contested_decisions"] +
                        330 * production_searches)
                    or work["rejected_worlds"] > work["failed_worlds"]
                    or work["rollouts"] != work["verified_rollouts"]
                    or work["rollouts"] < (
                        telemetry["candidate_count_sum"] +
                        660 * production_searches)):
                raise PrivilegedTeacherC0Error("C0 arm work drift")
        expected_record = _record_payload(
            coordinate=coordinate, role=record["role"], parent=parent,
            outcomes=tuple(C0Outcome(
                arm=arm,
                attacker_points=arms[arm]["attacker_points"],
                signed_level_utility=arms[arm]["signed_level_utility"],
                decision_count=arms[arm]["decision_count"],
                work=arms[arm]["work"], telemetry=arms[arm]["telemetry"])
                           for arm in ARMS))
        if record != expected_record:
            raise PrivilegedTeacherC0Error("C0 record reconstruction drift")
        actual.add(key)
    if actual != expected or len(roots) != len(design.root_coordinates):
        raise PrivilegedTeacherC0Error("C0 record population drift")


def report_bytes(report: dict[str, object], design: C0Design,
                 parent_report: dict[str, object], *,
                 parent_external_sha256: str) -> bytes:
    validate_report(report, design, parent_report,
                    parent_external_sha256=parent_external_sha256)
    return canonical_json_bytes(report)


__all__ = [
    "ARMS", "AUTHORITY", "C0Design", "C0ProductionBallotBot",
    "C0WideHeuristicBot", "C0WideSmartBot", "PrivilegedTeacherC0Error",
    "report_bytes", "run_dev", "validate_parent", "validate_report",
]
