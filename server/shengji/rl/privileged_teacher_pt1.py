"""Bounded, search-first privileged-teacher PT1 mechanics.

This module is deliberately an offline boundary.  It contains three paired
arms (public production, perfect-information production, and exact search),
but no policy registration or gameplay authority.  Hidden cards are accepted
only through :class:`TrueWorld`; records contain hashes and work receipts, not
the world itself.
"""

from __future__ import annotations

import copy
import hashlib
import time
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

from .privileged_teacher_pt0 import (
    PrivilegedTeacherPT0Error,
    canonical_json_bytes,
    exact_world_action_values,
    pt0_public_state_sha256,
    signed_level_utility,
)

PT1_SCHEMA = "privileged-teacher-pt1-search-packet-v1"
PT1_RECORD_SCHEMA = "privileged-teacher-pt1-search-record-v1"
PT1_CHECKPOINT_SCHEMA = "privileged-teacher-pt1-search-checkpoint-v1"
PT1_MANIFEST_SCHEMA = "privileged-teacher-pt1-search-manifest-v1"
PRODUCTION_POLICY = "mc-s0-report-lcb"
N_DETERMINIZATIONS = 30
REPORT_WORLDS = 300
MAX_EXACT_NODES = 250_000
ARM_NAMES = ("A", "B", "C")
AUTHORITY = {
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "training_authorized": False,
    "retry_authorized": False,
    "merge_authorized": False,
}


class PrivilegedTeacherPT1Error(PrivilegedTeacherPT0Error):
    """PT1 refused an identity, leakage, integrity, or authority violation."""


def _sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value):
        raise PrivilegedTeacherPT1Error(f"{label} must be a lowercase SHA-256")
    return value


def _action(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise PrivilegedTeacherPT1Error("action must be a nonempty card sequence")
    if any(type(card) is not str or not card for card in value):
        raise PrivilegedTeacherPT1Error("action cards must be strings")
    return tuple(sorted(value))


def _world_hash(rnd: object) -> str:
    """Hash complete hidden state for internal pairing only."""
    payload = {"hands": [sorted(h) for h in rnd.hands],
               "buried": sorted(rnd.buried), "banker": rnd.banker,
               "trump_rank": rnd.trump_rank, "turn": rnd.turn}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _evaluator_identity(public: str, world: str, utilities, points,
                        nodes: int, cache_hits: int) -> str:
    return hashlib.sha256(canonical_json_bytes({
        "schema": "privileged-teacher-pt1-shared-exact-evaluator-v1",
        "world_sha256": world, "public_state_sha256": public,
        "action_utilities": [[list(a), v] for a, v in utilities],
        "final_attacker_points": [[list(a), p] for a, p in points],
        "nodes": nodes, "cache_hits": cache_hits,
    })).hexdigest()


@dataclass(frozen=True)
class TrueWorld:
    """Explicit capability proving that a Round is the sealed true world."""

    round: object
    token: str

    @classmethod
    def seal(cls, rnd: object) -> "TrueWorld":
        from shengji.engine.round import Round
        if type(rnd) is not Round:
            raise PrivilegedTeacherPT1Error("true world requires exact Round")
        token = hashlib.sha256(canonical_json_bytes(
            ["pt1-true-world", _world_hash(rnd)])).hexdigest()
        return cls(round=rnd, token=token)

    def verify(self) -> object:
        from shengji.engine.round import Round
        if type(self.round) is not Round:
            raise PrivilegedTeacherPT1Error("true world requires exact Round")
        expected = hashlib.sha256(canonical_json_bytes(
            ["pt1-true-world", _world_hash(self.round)])).hexdigest()
        if self.token != expected:
            raise PrivilegedTeacherPT1Error("true-world capability drift")
        return self.round


def seal_true_world(rnd: object) -> TrueWorld:
    return TrueWorld.seal(rnd)


@dataclass(frozen=True)
class WorkReceipt:
    """Typed work accounting shared by A and B and reported by C."""

    n_determinizations: int
    report_worlds: int
    selection_attempts: int
    selection_worlds: int
    report_attempts: int
    report_worlds_accepted: int
    searches: int
    attempted_rollouts: int
    completed_rollouts: int
    exact_nodes: int
    exact_cache_hits: int
    wall_time_ns: int

    def payload(self) -> dict[str, object]:
        return {"n_determinizations": self.n_determinizations,
                "report_worlds": self.report_worlds,
                "selection_attempts": self.selection_attempts,
                "selection_worlds": self.selection_worlds,
                "report_attempts": self.report_attempts,
                "report_worlds_accepted": self.report_worlds_accepted,
                "searches": self.searches,
                "attempted_rollouts": self.attempted_rollouts,
                "completed_rollouts": self.completed_rollouts,
                "exact_nodes": self.exact_nodes,
                "exact_cache_hits": self.exact_cache_hits,
                "wall_time_ns": self.wall_time_ns}


@dataclass(frozen=True)
class ArmDecision:
    arm: str
    selected_action: tuple[str, ...]
    ballot: tuple[tuple[str, ...], ...]
    public_state_sha256: str
    true_world_sha256: str
    policy: str
    seed: int
    work: WorkReceipt
    evaluator_schema: str = "privileged-teacher-pt1-shared-exact-evaluator-v1"
    production_ballot: tuple[tuple[str, ...], ...] | None = None

    def payload(self) -> dict[str, object]:
        return {"arm": self.arm, "selected_action": list(self.selected_action),
                "ballot": [list(a) for a in self.ballot],
                "public_state_sha256": self.public_state_sha256,
                "true_world_sha256": self.true_world_sha256,
                "policy": self.policy, "seed": self.seed,
                "work": self.work.payload(),
                "evaluator_schema": self.evaluator_schema,
                "production_ballot": [list(a) for a in
                    (self.production_ballot or self.ballot)]}


@dataclass(frozen=True)
class PT1Record:
    """Immutable result for one state and one policy seed."""

    capture_id_sha256: str
    public_state_sha256: str
    true_world_sha256: str
    legal_ballot: tuple[tuple[str, ...], ...]
    arms: tuple[ArmDecision, ...]
    selected_utilities: tuple[tuple[str, int], ...]
    selected_points: tuple[tuple[str, int], ...]
    evaluation_action_utilities: tuple[tuple[tuple[str, ...], int], ...]
    evaluation_final_points: tuple[tuple[tuple[str, ...], int], ...]
    evaluator_identity: str
    c_regret: int
    authority: Mapping[str, bool]
    schema: str = PT1_RECORD_SCHEMA

    def _body(self) -> dict[str, object]:
        return {"schema": self.schema,
                "capture_id_sha256": self.capture_id_sha256,
                "public_state_sha256": self.public_state_sha256,
                "true_world_sha256": self.true_world_sha256,
                "legal_ballot": [list(a) for a in self.legal_ballot],
                "arms": [a.payload() for a in self.arms],
                "selected_utilities": [list(x) for x in self.selected_utilities],
                "selected_points": [list(x) for x in self.selected_points],
                "evaluation_action_utilities": [[list(a), v]
                    for a, v in self.evaluation_action_utilities],
                "evaluation_final_points": [[list(a), p]
                    for a, p in self.evaluation_final_points],
                "evaluator_identity": self.evaluator_identity,
                "c_regret": self.c_regret,
                "authority": dict(self.authority)}

    def payload(self) -> dict[str, object]:
        body = self._body()
        return {**body, "record_sha256": hashlib.sha256(
            canonical_json_bytes(body)).hexdigest()}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())


@dataclass(frozen=True)
class PT1Run:
    records: tuple[PT1Record, ...]
    total_units: int
    status: str
    truncated_by_deadline: bool
    progress: Mapping[str, int]
    checkpoint: bytes
    authority: Mapping[str, bool]

    def payload(self) -> dict[str, object]:
        packet = {"schema": PT1_SCHEMA, "records": [r.payload() for r in self.records],
                  "record_count": len(self.records), "total_record_count": self.total_units,
                  "status": self.status,
                  "truncated_by_deadline": self.truncated_by_deadline,
                  "progress": dict(self.progress), "authority": dict(self.authority)}
        packet["packet_sha256"] = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
        return packet


def _round_check(rnd: object, *, public: object | None = None) -> tuple[int, str]:
    from shengji.engine.round import Round
    if type(rnd) is not Round or rnd.phase != "play" or rnd.turn is None:
        raise PrivilegedTeacherPT1Error("PT1 requires an active exact Round")
    if public is not None and pt0_public_state_sha256(rnd, perspective_seat=rnd.turn) != public:
        raise PrivilegedTeacherPT1Error("public state fingerprint drift")
    return rnd.turn, pt0_public_state_sha256(rnd, perspective_seat=rnd.turn)


def _true_world_check(public_rnd: object, true_world: TrueWorld) -> tuple[object, int, str]:
    if type(true_world) is not TrueWorld:
        raise PrivilegedTeacherPT1Error("B/C require a sealed TrueWorld")
    world = true_world.verify()
    seat, public = _round_check(world)
    if public != pt0_public_state_sha256(public_rnd, perspective_seat=seat):
        raise PrivilegedTeacherPT1Error("true world is not a public-state twin")
    if sorted(world.hands[seat]) != sorted(public_rnd.hands[seat]):
        raise PrivilegedTeacherPT1Error("true world actor hand drift")
    return world, seat, public


def _production_bot(seed: int, *, true_world: object | None = None):
    from shengji.ai.mcbot import MCBot, DeterminizationContractError

    class TrueWorldMC(MCBot):
        N_DETERMINIZATIONS = N_DETERMINIZATIONS
        REPORT_FOLD_WORLDS = REPORT_WORLDS
        REPORT_RULE = "lcb"
        REQUIRE_EXACT_WORK = True

        def _sample_hands(self, rnd, seat, memory):
            if true_world is None:
                raise DeterminizationContractError("true-world sampler not configured")
            if not getattr(true_world, "_pt1_marked", False):
                raise DeterminizationContractError("unsealed determinization refused")
            return ({s: list(true_world.hands[s]) for s in range(4) if s != seat},
                    list(true_world.buried))

    if true_world is None:
        from shengji.ai.registry import make_bot
        bot = make_bot(PRODUCTION_POLICY, seed=seed)
    else:
        bot = TrueWorldMC(seed=seed)
    # Bind the frozen controls even if a registry class drifts.
    bot.N_DETERMINIZATIONS = N_DETERMINIZATIONS
    bot.REPORT_FOLD_WORLDS = REPORT_WORLDS
    bot.REPORT_RULE = "lcb"
    bot.REQUIRE_EXACT_WORK = True
    return bot


def _mark_world(world: object) -> object:
    clone = copy.copy(world)
    clone.hands = [list(h) for h in world.hands]
    clone.buried = list(world.buried)
    clone._pt1_marked = True
    return clone


def _select_production(rnd: object, *, seed: int, arm: str,
                       true_world: object | None = None,
                       world_identity: str | None = None) -> ArmDecision:
    seat, public = _round_check(rnd)
    started_ns = time.perf_counter_ns()
    bot = _production_bot(seed, true_world=_mark_world(true_world) if true_world is not None else None)
    selected = _action(bot.decide_play(copy.deepcopy(rnd), seat))
    record = bot.last_decision_record
    if not isinstance(record, Mapping):
        raise PrivilegedTeacherPT1Error(
            "production route did not expose decision telemetry")
    candidates = record.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise PrivilegedTeacherPT1Error("production route ballot telemetry missing")
    ballot = tuple(_action(a) for a in candidates)
    allocation = record.get("alloc")
    report = record.get("report_fold")
    work = record.get("work")
    if not isinstance(allocation, Mapping) or not isinstance(report, Mapping) \
            or not isinstance(work, Mapping):
        raise PrivilegedTeacherPT1Error(
            "production route work telemetry missing selection/report receipt")
    if any(key not in allocation for key in ("attempts", "worlds", "rollouts", "budget")) \
            or any(key not in report for key in ("attempts", "worlds")):
        raise PrivilegedTeacherPT1Error("production route work telemetry incomplete")
    if record.get("n_determinizations") != N_DETERMINIZATIONS \
            or record.get("report_worlds_requested") != REPORT_WORLDS:
        raise PrivilegedTeacherPT1Error("production route frozen N/R drift")
    if not all(type(allocation[key]) is int and allocation[key] >= 0
               for key in ("attempts", "worlds", "rollouts", "budget")):
        raise PrivilegedTeacherPT1Error("production selection telemetry is not integer")
    if not all(type(report[key]) is int and report[key] >= 0
               for key in ("attempts", "worlds")):
        raise PrivilegedTeacherPT1Error("production report telemetry is not integer")
    if allocation["worlds"] > N_DETERMINIZATIONS * len(ballot):
        raise PrivilegedTeacherPT1Error("production selection worlds exceed N budget")
    if report["worlds"] > REPORT_WORLDS:
        raise PrivilegedTeacherPT1Error("production report worlds exceed R budget")
    # A first-run underfill is a refusal, never a record with a short-search
    # receipt. The frozen uniform route exposes the exact identities: N
    # common worlds, N*K selection rollouts, and 2*R report rollouts.
    if allocation.get("short") is not False \
            or allocation["worlds"] != N_DETERMINIZATIONS \
            or allocation["budget"] != N_DETERMINIZATIONS * len(ballot) \
            or allocation["rollouts"] != allocation["budget"]:
        raise PrivilegedTeacherPT1Error("production selection work incomplete")
    n_by_candidate = allocation.get("n_by_candidate")
    if (not isinstance(n_by_candidate, list)
            or n_by_candidate != [N_DETERMINIZATIONS] * len(ballot)):
        raise PrivilegedTeacherPT1Error("production candidate work incomplete")
    if report.get("complete") is not True or report["worlds"] != REPORT_WORLDS:
        raise PrivilegedTeacherPT1Error("production report work incomplete")
    if (work.get("selection_budget") != allocation["budget"]
            or work.get("selection_rollouts") != allocation["rollouts"]
            or work.get("report_budget") != 2 * REPORT_WORLDS
            or work.get("report_rollouts") != 2 * report["worlds"]
            or work.get("total_budget") != allocation["budget"] + 2 * REPORT_WORLDS
            or work.get("total_rollouts")
            != allocation["rollouts"] + 2 * report["worlds"]):
        raise PrivilegedTeacherPT1Error("production rollout identity drift")
    elapsed_ns = time.perf_counter_ns() - started_ns
    receipt = WorkReceipt(
        N_DETERMINIZATIONS, REPORT_WORLDS, int(allocation["attempts"]),
        int(allocation["worlds"]), int(report["attempts"]), int(report["worlds"]),
        int(bot.search_calls),
        int(work.get("total_budget", allocation["budget"] + 2 * REPORT_WORLDS)),
        int(work.get("total_rollouts", 0)), 0, 0, elapsed_ns)
    return ArmDecision(arm, selected, ballot, public,
                       world_identity or _world_hash(true_world or rnd),
                       PRODUCTION_POLICY, seed, receipt,
                       production_ballot=ballot)


def _choose_exact(evaluation, *, seat: int, banker: int) -> tuple[str, ...]:
    rows = evaluation.values.action_utilities
    return min((cards for cards, value in rows if value == max(v for _, v in rows)),
               key=lambda cards: (len(cards), cards))


def evaluate_state(public_rnd: object, true_world: TrueWorld, *, seed: int = 0,
                   max_hand_cards: int | None = None,
                   max_nodes: int = MAX_EXACT_NODES) -> PT1Record:
    """Select A/B/C and score all selected actions using one exact evaluator."""
    world, seat, public = _true_world_check(public_rnd, true_world)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise PrivilegedTeacherPT1Error("policy seed must be nonnegative")
    threshold = max_hand_cards or max(len(h) for h in world.hands)
    world_identity = _world_hash(world)
    a = _select_production(public_rnd, seed=seed, arm="A",
                            world_identity=world_identity)
    b = _select_production(public_rnd, seed=seed, arm="B", true_world=world,
                            world_identity=world_identity)
    # C uses PT0's exact-world evaluator, which enumerates every root action
    # and shares one ExactWorldSession transposition table.
    evaluation = exact_world_action_values(
        world, world_sha256=_world_hash(world), perspective_seat=seat,
        max_hand_cards=threshold, max_nodes=max_nodes)
    ballot = tuple(cards for cards, _ in evaluation.values.action_utilities)
    c_selected = _choose_exact(evaluation, seat=seat, banker=world.banker)
    evaluator_identity = _evaluator_identity(
        public, world_identity, evaluation.values.action_utilities,
        evaluation.final_attacker_points, evaluation.nodes, evaluation.cache_hits)
    a = replace(a, ballot=ballot, evaluator_schema=evaluator_identity)
    b = replace(b, ballot=ballot, evaluator_schema=evaluator_identity)
    c = ArmDecision("C", c_selected, ballot, public, world_identity,
                    "ExactWorldSession", seed,
                    WorkReceipt(0, 0, 0, 0, 0, 0, 1, len(ballot), len(ballot),
                                evaluation.nodes, evaluation.cache_hits, 0),
                    evaluator_identity)
    decisions = (a, b, c)
    values = dict(evaluation.values.action_utilities)
    points = dict(evaluation.final_attacker_points)
    if any(d.selected_action not in values for d in decisions):
        raise PrivilegedTeacherPT1Error("selected action is outside exact ballot")
    best = max(values.values())
    c_regret = best - values[c.selected_action]
    capture = hashlib.sha256(canonical_json_bytes(
        [PT1_RECORD_SCHEMA, public, world_identity, seed])).hexdigest()
    return PT1Record(capture, public, world_identity, ballot, decisions,
                     tuple((d.arm, values[d.selected_action]) for d in decisions),
                     tuple((d.arm, points[d.selected_action]) for d in decisions),
                     evaluation.values.action_utilities,
                     evaluation.final_attacker_points, evaluator_identity,
                     c_regret, AUTHORITY)


def verify_record(record: PT1Record | Mapping[str, object] | bytes) -> PT1Record:
    """Reopen and fail closed on any record/manifest-style byte tamper."""
    if isinstance(record, bytes):
        import json
        try:
            payload = json.loads(record.decode("ascii"))
        except Exception as exc:
            raise PrivilegedTeacherPT1Error("record is not canonical") from exc
        if canonical_json_bytes(payload) != record:
            raise PrivilegedTeacherPT1Error("record is not canonical")
        record = payload
    if isinstance(record, PT1Record):
        payload = record.payload()
    elif isinstance(record, Mapping):
        payload = dict(record)
    else:
        raise PrivilegedTeacherPT1Error("record type refused")
    if payload.get("schema") != PT1_RECORD_SCHEMA:
        raise PrivilegedTeacherPT1Error("record schema drift")
    if payload.get("authority") != AUTHORITY:
        raise PrivilegedTeacherPT1Error("record authority drift")
    required = {"schema", "capture_id_sha256", "public_state_sha256", "true_world_sha256",
                "legal_ballot", "arms", "selected_utilities", "selected_points",
                "evaluation_action_utilities", "evaluation_final_points",
                "evaluator_identity", "c_regret", "authority", "record_sha256"}
    if set(payload) != required:
        raise PrivilegedTeacherPT1Error("record fields drift")
    _sha(payload["capture_id_sha256"], "capture id")
    _sha(payload["public_state_sha256"], "public state")
    _sha(payload["true_world_sha256"], "true world")
    record_hash = payload["record_sha256"]
    _sha(record_hash, "record")
    body = {k: payload[k] for k in required if k != "record_sha256"}
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != record_hash:
        raise PrivilegedTeacherPT1Error("record hash drift")
    if payload["c_regret"] != 0:
        raise PrivilegedTeacherPT1Error("C exact regret is nonzero")
    arms = payload["arms"]
    if not isinstance(arms, list) or {a.get("arm") for a in arms if isinstance(a, Mapping)} != set(ARM_NAMES):
        raise PrivilegedTeacherPT1Error("arm population drift")
    # A/B must carry the frozen equal-work contract; C must enumerate same ballot.
    parsed = []
    for arm in arms:
        if not isinstance(arm, Mapping) or set(arm) != {"arm", "selected_action", "ballot",
                "public_state_sha256", "true_world_sha256", "policy", "seed", "work",
                "evaluator_schema", "production_ballot"}:
            raise PrivilegedTeacherPT1Error("arm record drift")
        parsed.append(arm)
    a, b, c = (next(x for x in parsed if x["arm"] == name) for name in ARM_NAMES)
    if any(x["public_state_sha256"] != payload["public_state_sha256"]
           or x["true_world_sha256"] != payload["true_world_sha256"]
           for x in parsed):
        raise PrivilegedTeacherPT1Error("arm state identity drift")
    if len({x["seed"] for x in parsed}) != 1 or any(
            isinstance(x["seed"], bool) or not isinstance(x["seed"], int)
            or x["seed"] < 0 for x in parsed):
        raise PrivilegedTeacherPT1Error("arm policy seed drift")
    if a["policy"] != PRODUCTION_POLICY or b["policy"] != PRODUCTION_POLICY \
            or c["policy"] != "ExactWorldSession":
        raise PrivilegedTeacherPT1Error("arm policy identity drift")
    evaluator_ids = {x["evaluator_schema"] for x in parsed}
    if len(evaluator_ids) != 1 or any(type(x) is not str or len(x) != 64
                                      for x in evaluator_ids) \
            or payload["evaluator_identity"] not in evaluator_ids:
        raise PrivilegedTeacherPT1Error("shared evaluator identity drift")
    if a["ballot"] != b["ballot"] or a["public_state_sha256"] != b["public_state_sha256"]:
        raise PrivilegedTeacherPT1Error("A/B ballot or public-state drift")
    if a["ballot"] != payload["legal_ballot"]:
        raise PrivilegedTeacherPT1Error("A/B ballot is not exact legal ballot")
    for arm in (a, b):
        if not isinstance(arm["production_ballot"], list) \
                or not arm["production_ballot"]:
            raise PrivilegedTeacherPT1Error("production ballot telemetry missing")
        if _action(arm["selected_action"]) not in tuple(
                _action(action) for action in arm["production_ballot"]):
            raise PrivilegedTeacherPT1Error("selected action outside production ballot")
    if a["production_ballot"] != b["production_ballot"]:
        raise PrivilegedTeacherPT1Error("A/B production ballot drift")
    for arm in (a, b):
        w = arm["work"]
        if w.get("n_determinizations") != N_DETERMINIZATIONS or w.get("report_worlds") != REPORT_WORLDS:
            raise PrivilegedTeacherPT1Error("A/B work contract drift")
        if any(type(w.get(k)) is not int or w[k] < 0 for k in (
                "selection_attempts", "selection_worlds", "report_attempts",
                "report_worlds_accepted", "searches", "attempted_rollouts",
                "completed_rollouts", "exact_nodes", "exact_cache_hits", "wall_time_ns")):
            raise PrivilegedTeacherPT1Error("A/B work receipt type drift")
    a_work = a["work"]
    b_work = b["work"]
    # Rejection-sampling attempts are diagnostics, not parity gates: A's
    # public sampler and B's true-world sampler have structurally different
    # acceptance rates. The fixed budget and completed work below are the
    # causal same-work contract.
    if any(a_work.get(k) != b_work.get(k) for k in (
            "n_determinizations", "report_worlds", "searches",
            "attempted_rollouts", "completed_rollouts")):
        raise PrivilegedTeacherPT1Error("A/B work parity drift")
    if c["ballot"] != payload["legal_ballot"]:
        raise PrivilegedTeacherPT1Error("C incomplete or off-ballot evaluation")
    try:
        eval_utilities = tuple((_action(row[0]), row[1])
                               for row in payload["evaluation_action_utilities"])
        eval_points = tuple((_action(row[0]), row[1])
                            for row in payload["evaluation_final_points"])
    except (TypeError, KeyError, IndexError) as exc:
        raise PrivilegedTeacherPT1Error("shared evaluator result drift") from exc
    if tuple(a for a, _ in eval_utilities) != tuple(_action(a) for a in payload["legal_ballot"]) \
            or tuple(a for a, _ in eval_points) != tuple(a for a, _ in eval_utilities):
        raise PrivilegedTeacherPT1Error("shared evaluator result ballot drift")
    if any(type(v) is not int for _, v in (*eval_utilities, *eval_points)):
        raise PrivilegedTeacherPT1Error("shared evaluator result type drift")
    expected_identity = _evaluator_identity(
        payload["public_state_sha256"], payload["true_world_sha256"],
        eval_utilities, eval_points, c["work"]["exact_nodes"],
        c["work"]["exact_cache_hits"])
    if payload["evaluator_identity"] != expected_identity:
        raise PrivilegedTeacherPT1Error("shared evaluator result identity drift")
    utility_map = dict(eval_utilities)
    point_map = dict(eval_points)
    selected_utilities = payload["selected_utilities"]
    selected_points = payload["selected_points"]
    if (not isinstance(selected_utilities, list) or not isinstance(selected_points, list)
            or len(selected_utilities) != 3 or len(selected_points) != 3):
        raise PrivilegedTeacherPT1Error("arm/sign identity drift")
    for arm, util, points_row in zip(parsed, selected_utilities, selected_points):
        if (not isinstance(util, list) or len(util) != 2
                or util[0] != arm["arm"]
                or utility_map.get(_action(arm["selected_action"])) != util[1]
                or not isinstance(points_row, list) or len(points_row) != 2
                or points_row[0] != arm["arm"]
                or point_map.get(_action(arm["selected_action"])) != points_row[1]):
            raise PrivilegedTeacherPT1Error("arm/sign identity drift")
    best_utility = max(utility_map.values())
    c_action = _action(c["selected_action"])
    if c_action not in utility_map or utility_map[c_action] != best_utility \
            or payload["c_regret"] != best_utility - utility_map[c_action]:
        raise PrivilegedTeacherPT1Error("C exact argmax/regret drift")
    names = [x[0] for x in payload["selected_utilities"]]
    if names != list(ARM_NAMES) or [x[0] for x in payload["selected_points"]] != list(ARM_NAMES):
        raise PrivilegedTeacherPT1Error("arm/sign identity drift")
    for arm in parsed:
        if arm["selected_action"] not in arm["ballot"]:
            raise PrivilegedTeacherPT1Error("selected action outside arm ballot")
    return record if isinstance(record, PT1Record) else _record_from_payload(payload)


def manifest_for(packet: PT1Run | Mapping[str, object]) -> dict[str, object]:
    """Create a closed manifest binding packet and every immutable record."""
    value = packet.payload() if isinstance(packet, PT1Run) else dict(packet)
    records = value.get("records")
    if not isinstance(records, list):
        raise PrivilegedTeacherPT1Error("manifest packet records drift")
    return {"schema": PT1_MANIFEST_SCHEMA,
            "packet_sha256": hashlib.sha256(canonical_json_bytes(value)).hexdigest(),
            "record_sha256s": [hashlib.sha256(canonical_json_bytes(r)).hexdigest()
                               for r in records],
            "authority": dict(AUTHORITY)}


def verify_manifest(manifest: Mapping[str, object], packet: PT1Run | Mapping[str, object]) -> None:
    if not isinstance(manifest, Mapping) or set(manifest) != {
            "schema", "packet_sha256", "record_sha256s", "authority"}:
        raise PrivilegedTeacherPT1Error("manifest fields drift")
    expected = manifest_for(packet)
    if dict(manifest) != expected:
        raise PrivilegedTeacherPT1Error("manifest tamper or packet drift")


def _record_from_payload(p: Mapping[str, object]) -> PT1Record:
    # Reopen as an immutable typed shell; semantic integrity is checked above.
    def work(v):
        return WorkReceipt(**{k: v[k] for k in ("n_determinizations", "report_worlds",
            "selection_attempts", "selection_worlds", "report_attempts",
            "report_worlds_accepted", "searches", "attempted_rollouts",
            "completed_rollouts", "exact_nodes", "exact_cache_hits", "wall_time_ns")})
    arms = tuple(ArmDecision(a["arm"], _action(a["selected_action"]),
        tuple(_action(x) for x in a["ballot"]), a["public_state_sha256"], a["true_world_sha256"],
        a["policy"], a["seed"], work(a["work"]), a["evaluator_schema"],
        tuple(_action(x) for x in a["production_ballot"])) for a in p["arms"])
    return PT1Record(p["capture_id_sha256"], p["public_state_sha256"], p["true_world_sha256"],
        tuple(_action(x) for x in p["legal_ballot"]), arms,
        tuple((x[0], x[1]) for x in p["selected_utilities"]), tuple((x[0], x[1]) for x in p["selected_points"]),
        tuple((_action(x[0]), x[1]) for x in p["evaluation_action_utilities"]),
        tuple((_action(x[0]), x[1]) for x in p["evaluation_final_points"]),
        p["evaluator_identity"],
        p["c_regret"], dict(p["authority"]), p["schema"])


def _replay_semantics(record: PT1Record) -> dict[str, object]:
    """Normalize only wall time for deterministic checkpoint replay."""
    payload = record.payload()
    payload.pop("record_sha256", None)
    for arm in payload["arms"]:
        arm["work"].pop("wall_time_ns", None)
    return payload


def run_pt1(states: Sequence[tuple[object, TrueWorld]], *, seeds: Sequence[int] = (0, 1, 2, 3),
            deadline: float | None = None, monotonic: Callable[[], float] = time.monotonic,
            record_sink: Callable[[int, bytes], object] | None = None,
            checkpoint: bytes | None = None,
            checkpoint_sink: Callable[[bytes], object] | None = None) -> PT1Run:
    if not isinstance(states, Sequence) or isinstance(states, (str, bytes)):
        raise PrivilegedTeacherPT1Error("states must be a sequence")
    if (not callable(monotonic)
            or (record_sink is not None and not callable(record_sink))
            or (checkpoint_sink is not None and not callable(checkpoint_sink))):
        raise PrivilegedTeacherPT1Error("invalid progress callback")
    total = len(states) * len(seeds)
    records = []
    seen = set()
    seen_public_states = set()
    resume_count = 0
    if checkpoint is not None:
        import json
        try:
            checkpoint_payload = json.loads(checkpoint.decode("ascii"))
        except Exception as exc:
            raise PrivilegedTeacherPT1Error("checkpoint is not canonical") from exc
        if canonical_json_bytes(checkpoint_payload) != checkpoint \
                or not isinstance(checkpoint_payload, Mapping) \
                or set(checkpoint_payload) != {"schema", "completed_units", "records",
                                               "truncated_by_deadline"} \
                or checkpoint_payload["schema"] != PT1_CHECKPOINT_SCHEMA:
            raise PrivilegedTeacherPT1Error("checkpoint is not canonical PT1")
        prefix = checkpoint_payload["records"]
        if not isinstance(prefix, list) or checkpoint_payload["completed_units"] != len(prefix) \
                or len(prefix) > total:
            raise PrivilegedTeacherPT1Error("checkpoint progress drift")
        if checkpoint_payload["truncated_by_deadline"] is not (len(prefix) < total):
            raise PrivilegedTeacherPT1Error("checkpoint completion drift")
        for row in prefix:
            records.append(verify_record(canonical_json_bytes(row)))
        resume_count = len(records)
    for state_index, pair in enumerate(states):
        if not isinstance(pair, Sequence) or len(pair) != 2:
            raise PrivilegedTeacherPT1Error("state must be a public/true-world pair")
        candidate_public = pt0_public_state_sha256(pair[0], perspective_seat=pair[0].turn)
        if candidate_public in seen_public_states:
            raise PrivilegedTeacherPT1Error("state reuse or cross-split reuse")
        seen_public_states.add(candidate_public)
        for seed_index, seed in enumerate(seeds):
            flat_index = state_index * len(seeds) + seed_index
            if flat_index < resume_count:
                prior = records[flat_index]
                if prior.public_state_sha256 != candidate_public \
                        or any(a.seed != seed for a in prior.arms):
                    raise PrivilegedTeacherPT1Error("checkpoint state/seed identity drift")
                current_world = pair[1].verify()
                if prior.true_world_sha256 != _world_hash(current_world):
                    raise PrivilegedTeacherPT1Error("checkpoint true-world identity drift")
                replayed = evaluate_state(pair[0], pair[1], seed=seed)
                if _replay_semantics(replayed) != _replay_semantics(prior):
                    raise PrivilegedTeacherPT1Error("checkpoint replay semantic drift")
                seen.add((prior.public_state_sha256, seed))
                continue
            if deadline is not None and monotonic() >= deadline:
                break
            rec = evaluate_state(pair[0], pair[1], seed=seed)
            # Validate before exposing bytes to checkpoint sinks or any
            # persistence boundary. A malformed/underfilled first-run result
            # therefore leaves no durable prefix.
            verify_record(rec)
            key = (rec.public_state_sha256, seed)
            if key in seen:
                raise PrivilegedTeacherPT1Error("state reuse or cross-split reuse")
            seen.add(key)
            records.append(rec)
            if record_sink is not None:
                record_sink(len(records) - 1, rec.canonical_bytes())
            if checkpoint_sink is not None:
                checkpoint_sink(canonical_json_bytes({
                    "schema": PT1_CHECKPOINT_SCHEMA,
                    "completed_units": len(records),
                    "records": [r.payload() for r in records],
                    "truncated_by_deadline": len(records) < total,
                }))
        if deadline is not None and len(records) < (state_index + 1) * len(seeds) and monotonic() >= deadline:
            break
    complete = len(records) == total
    progress = {"completed_units": len(records), "total_units": total,
                "percent_basis_points": 10_000 if total == 0 else (len(records) * 10_000) // total}
    checkpoint = canonical_json_bytes({"schema": PT1_CHECKPOINT_SCHEMA,
        "completed_units": len(records), "records": [r.payload() for r in records],
        "truncated_by_deadline": not complete})
    return PT1Run(tuple(records), total, "COMPLETE" if complete else "TRUNCATED",
                  not complete, progress, checkpoint, AUTHORITY)


run_privileged_teacher_pt1 = run_pt1

__all__ = ["ARM_NAMES", "AUTHORITY", "MAX_EXACT_NODES", "N_DETERMINIZATIONS",
           "PRODUCTION_POLICY", "PT1_RECORD_SCHEMA", "PT1_SCHEMA", "PT1Run",
           "PT1Record", "PrivilegedTeacherPT1Error", "TrueWorld", "WorkReceipt",
           "evaluate_state", "run_pt1", "run_privileged_teacher_pt1",
           "seal_true_world", "verify_manifest", "verify_record", "manifest_for"]
