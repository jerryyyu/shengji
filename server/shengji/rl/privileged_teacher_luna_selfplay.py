"""Bounded, full-information Luna-vs-Luna self-play harness.

This is a diagnostic collector.  A single :class:`Round` is owned by the
engine boundary and two independent team controllers ask that boundary for
observations and commit legal plays.  The private trajectory is deliberately
an action/state source only; it has no model prose or value/outcome label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import random
import secrets
import threading
import time
from typing import Callable, Mapping, Sequence

from ..engine.cards import Ordering, RANKS
from ..engine.round import Round, Trick, TrickPlay
from . import privileged_teacher_c0 as c0
from . import privileged_teacher_full_ab as full
from . import privileged_teacher_sol0 as sol0
from .privileged_teacher_pt0 import canonical_json_bytes


SCHEMA = "privileged-teacher-luna-selfplay-v1"
COMPLETE_ROUTE = "COMPLETE_STATE_SOURCE_ACQUISITION"
INCOMPLETE_ROUTE = "INCOMPLETE_STATE_SOURCE_ACQUISITION"
DESIGN_SCHEMA = "privileged-teacher-luna-selfplay-design-v1"
GAME_SCHEMA = "privileged-teacher-luna-selfplay-game-v1"
PROGRESS_SCHEMA = "privileged-teacher-luna-selfplay-progress-v1"
TRAJECTORY_SCHEMA = "privileged-teacher-luna-selfplay-private-trajectory-v1"
TERMINAL_RECEIPT_SCHEMA = "privileged-teacher-luna-selfplay-terminal-receipt-v1"
ROOT_CENSUS_SCHEMA = "privileged-teacher-luna-selfplay-root-census-v1"
EXECUTION_BINDING_SCHEMA = "privileged-teacher-luna-selfplay-execution-binding-v1"
MODEL = "gpt-5.6-luna"
TEAMS = (0, 1)
BANKER_SEATS = (0, 1)
REPLICATES = 2
MIRRORS = (0, 1)
TRUMP_MODES = ("S", "H", "C", "D", "NT")
CANDIDATE_GAME_WORKERS = (1, 2, 4, 6, 8)
AUTHORITY = {
    "scientific_execution_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "merge_authorized": False,
    "retry_authorized": False,
    "value_label_authorized": False,
    "data_use_authorized": False,
    "model_process_launch_authorized": False,
}
_FORBIDDEN_TRAJECTORY_KEYS = frozenset({
    "value", "values", "utility", "signed_level_utility", "outcome",
    "model_output", "model_prose", "prose",
    "reasoning", "final_response",
})


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(key in _FORBIDDEN_TRAJECTORY_KEYS
                   or _contains_forbidden_key(child)
                   for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_key(child) for child in value)
    return False


class PrivilegedTeacherLunaSelfPlayError(ValueError):
    """The self-play boundary or private artifact is malformed."""


class LunaPlannerRequestError(PrivilegedTeacherLunaSelfPlayError):
    """A planner request was refused without changing engine state."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _seed(secret: bytes, *parts: object) -> int:
    if type(secret) is not bytes or len(secret) != 32:
        raise PrivilegedTeacherLunaSelfPlayError("seed secret identity drift")
    return int.from_bytes(hashlib.sha256(secret + canonical_json_bytes(
        [SCHEMA, *parts])).digest()[:8], "big") & ((1 << 63) - 1)


def validate_game_workers(workers: object) -> int:
    """Validate a candidate arm; this function never starts a worker."""
    if isinstance(workers, bool) or not isinstance(workers, int) \
            or workers not in CANDIDATE_GAME_WORKERS:
        raise PrivilegedTeacherLunaSelfPlayError(
            "game-worker arm must be one of 1/2/4/6/8")
    return workers


def validate_capacity(workers: object, *, games: int = 104) -> dict[str, int]:
    """Return a planning receipt for an arm without launching or computing."""
    count = validate_game_workers(workers)
    if isinstance(games, bool) or not isinstance(games, int) or games < 0:
        raise PrivilegedTeacherLunaSelfPlayError("capacity game count drift")
    return {"game_workers": count, "games": games,
            "minimum_workers": count, "launches": 0}


def candidate_worker_arms() -> tuple[int, ...]:
    return CANDIDATE_GAME_WORKERS


def fresh_coordinates() -> tuple[tuple[str, int, int], ...]:
    """The immutable 52-cluster coordinate schedule."""
    return LunaDesign().root_coordinates


def mirrored_assignments() -> tuple[tuple[tuple[str, int, int], int], ...]:
    """The immutable 104-game schedule (two assignments per cluster)."""
    return LunaDesign().mirror_assignments


def agent_team_assignment(mirror: int) -> tuple[int, int]:
    """Return (agent-A team, agent-B team) for one mirrored game."""
    if isinstance(mirror, bool) or mirror not in MIRRORS:
        raise PrivilegedTeacherLunaSelfPlayError("mirror identity drift")
    return (0, 1) if mirror == 0 else (1, 0)


def agent_for_team(mirror: int, team: int) -> int:
    if team not in TEAMS:
        raise PrivilegedTeacherLunaSelfPlayError("team identity drift")
    return agent_team_assignment(mirror)[team]


def _execution_binding(coordinate: Sequence[object], mirror: int,
                       root_sha256: str) -> dict[str, object]:
    """Deterministic identity receipt for both model/session boundaries."""
    coord = LunaCoordinate(*coordinate)
    assignment = agent_team_assignment(mirror)
    sessions = []
    for team in TEAMS:
        agent = assignment[team]
        session = _sha({"root_sha256": root_sha256,
                        "coordinate": coord.payload(), "mirror": mirror,
                        "team": team, "agent_identity": agent})
        sessions.append({"team": team, "agent_identity": agent,
                         "session_id": session,
                         "model_process_id": _sha({"session": session,
                                                   "model": MODEL})})
    return {"schema": EXECUTION_BINDING_SCHEMA,
            "agent_team_assignment": list(assignment), "sessions": sessions}


@dataclass(frozen=True)
class LunaCoordinate:
    trump_rank: str
    banker: int
    replicate: int

    def __post_init__(self) -> None:
        if (type(self.trump_rank) is not str or self.trump_rank not in RANKS
                or isinstance(self.banker, bool)
                or self.banker not in BANKER_SEATS) \
                or isinstance(self.replicate, bool) \
                or not isinstance(self.replicate, int) \
                or not 0 <= self.replicate < REPLICATES:
            raise PrivilegedTeacherLunaSelfPlayError("deal coordinate drift")

    def payload(self) -> list[object]:
        return [self.trump_rank, self.banker, self.replicate]

    @property
    def rank(self) -> str:
        return self.trump_rank

    @property
    def cluster_key(self) -> tuple[str, int, int]:
        return (self.trump_rank, self.banker, self.replicate)


@dataclass(frozen=True)
class LunaDesign:
    """Fresh population: 13 ranks x 2 bankers x 2 replicates."""

    seed_commitment_sha256: str = "0" * 64
    execution_git: str = "0" * 40
    native_sha256: str = "0" * 64
    hostname: str = full.MINI_HOSTNAME
    namespace: str = SCHEMA

    def __post_init__(self) -> None:
        for value, size, label in (
                (self.seed_commitment_sha256, 64, "seed commitment"),
                (self.execution_git, 40, "execution Git"),
                (self.native_sha256, 64, "native identity")):
            if type(value) is not str or len(value) != size \
                    or any(c not in "0123456789abcdef" for c in value):
                raise PrivilegedTeacherLunaSelfPlayError(f"{label} drift")
        if self.namespace != SCHEMA:
            raise PrivilegedTeacherLunaSelfPlayError("namespace drift")

    @property
    def root_coordinates(self) -> tuple[tuple[str, int, int], ...]:
        return tuple((rank, banker, replicate) for rank in RANKS
                     for banker in BANKER_SEATS for replicate in range(REPLICATES))

    @property
    def coordinates(self) -> tuple[LunaCoordinate, ...]:
        return tuple(LunaCoordinate(*row) for row in self.root_coordinates)

    @property
    def deal_clusters(self) -> tuple[tuple[str, int, int], ...]:
        return self.root_coordinates

    @property
    def mirror_assignments(self) -> tuple[tuple[tuple[str, int, int], int], ...]:
        return tuple((coordinate, mirror) for coordinate in self.root_coordinates
                     for mirror in MIRRORS)

    def payload(self) -> dict[str, object]:
        return {
            "schema": DESIGN_SCHEMA,
            "namespace": self.namespace,
            "seed_commitment_sha256": self.seed_commitment_sha256,
            "execution_git": self.execution_git,
            "native_sha256": self.native_sha256,
            "hostname": self.hostname,
            "trump_ranks": list(RANKS),
            "banker_seats": list(BANKER_SEATS),
            "replicates": REPLICATES,
            "deal_cluster_count": len(self.deal_clusters),
            "game_count": len(self.mirror_assignments),
            "mirror_count_per_cluster": len(MIRRORS),
            "candidate_game_workers": list(CANDIDATE_GAME_WORKERS),
            "authority": dict(AUTHORITY),
        }


def root_seed(seed_secret: bytes, coordinate: LunaCoordinate | tuple,
              mirror: int = 0) -> int:
    """Deterministic fresh root hook; mirror changes team identity only."""
    coord = coordinate if isinstance(coordinate, LunaCoordinate) \
        else LunaCoordinate(*coordinate)
    if isinstance(mirror, bool) or mirror not in MIRRORS:
        raise PrivilegedTeacherLunaSelfPlayError("mirror identity drift")
    return _seed(seed_secret, "deal", *coord.payload())


def root_identity(rnd: Round) -> str:
    if type(rnd) is not Round or rnd.phase != "play":
        raise PrivilegedTeacherLunaSelfPlayError("root requires play Round")
    return _root_identity_snapshot(_state_snapshot(rnd))


def _root_identity_snapshot(snapshot: Mapping[str, object]) -> str:
    return _sha({"schema": "luna-selfplay-root-v1",
                 "hands": snapshot["hands_by_seat"],
                 "buried": snapshot["hidden_burial"],
                 "banker": snapshot["banker"],
                 "trump_rank": snapshot["trump_rank"],
                 "trump_suit": snapshot["trump_suit"],
                 "trump_is_nt": snapshot["trump_is_nt"]})


def build_root(seed_secret: bytes, coordinate: LunaCoordinate | tuple,
               mirror: int = 0) -> Round:
    """Deal/declaration/bury a deterministic fresh full-information root."""
    coord = coordinate if isinstance(coordinate, LunaCoordinate) \
        else LunaCoordinate(*coordinate)
    if isinstance(mirror, bool) or mirror not in MIRRORS:
        raise PrivilegedTeacherLunaSelfPlayError("mirror identity drift")
    rnd = Round(coord.trump_rank, banker=coord.banker,
                rng=random.Random(root_seed(seed_secret, coord)))
    setup = [full._Production(seed=_seed(seed_secret, "setup", *coord.payload(), seat))
             for seat in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = setup[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = setup[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(coord.banker, setup[coord.banker].decide_bury(rnd, coord.banker))
    if rnd.phase != "play" or rnd.turn != coord.banker:
        raise PrivilegedTeacherLunaSelfPlayError("fresh root mechanics drift")
    return rnd


def root_trump_mode(rnd: Round) -> str:
    if type(rnd) is not Round or rnd.phase not in ("play", "round_end"):
        raise PrivilegedTeacherLunaSelfPlayError("root mode requires Round")
    mode = "NT" if rnd.trump_is_nt else rnd.trump_suit
    if mode not in TRUMP_MODES:
        raise PrivilegedTeacherLunaSelfPlayError("root trump mode drift")
    return mode


def validate_root_population(roots: Mapping[tuple, Round] | Sequence[Round],
                             *, design: LunaDesign | None = None) -> None:
    """Validate the frozen 52-root census; never replace a missing root."""
    expected = (design or LunaDesign()).root_coordinates
    if isinstance(roots, Mapping):
        if set(roots) != set(expected):
            raise PrivilegedTeacherLunaSelfPlayError("root population coordinate drift")
        rows = [(key, roots[key]) for key in expected]
    else:
        if not isinstance(roots, Sequence) or len(roots) != len(expected):
            raise PrivilegedTeacherLunaSelfPlayError("root population count drift")
        rows = list(zip(expected, roots))
    modes = set()
    hashes = {}
    for coordinate, rnd in rows:
        coord = LunaCoordinate(*coordinate)
        if (rnd.trump_rank, rnd.banker) != (coord.trump_rank, coord.banker):
            raise PrivilegedTeacherLunaSelfPlayError("root coordinate identity drift")
        if (type(rnd) is not Round or rnd.phase != "play" or rnd.turn is None
                or rnd.ordering is None or len(rnd.buried) != 8
                or any(len(hand) != 25 for hand in rnd.hands)):
            raise PrivilegedTeacherLunaSelfPlayError("root legality drift")
        modes.add(root_trump_mode(rnd))
        hashes[coordinate] = root_identity(rnd)
    if len(set(hashes.values())) != len(expected):
        raise PrivilegedTeacherLunaSelfPlayError("root hash uniqueness drift")
    if modes != set(TRUMP_MODES):
        raise PrivilegedTeacherLunaSelfPlayError("root trump mode coverage drift")


def _card_action(cards: Sequence[str]) -> tuple[str, ...]:
    if isinstance(cards, (str, bytes)) or not isinstance(cards, Sequence) \
            or not cards or any(type(card) is not str for card in cards):
        raise LunaPlannerRequestError("action shape drift")
    return tuple(sorted(cards))


def _strict_sha(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise PrivilegedTeacherLunaSelfPlayError(f"{label} drift")
    return value


def _validate_snapshot(snapshot: object) -> None:
    if type(snapshot) is not dict:
        raise PrivilegedTeacherLunaSelfPlayError("trajectory snapshot type drift")
    if snapshot.get("terminal_redacted") is True:
        if set(snapshot) != {"phase", "terminal_redacted"} \
                or snapshot.get("phase") != "round_end":
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory terminal redaction drift")
        return
    required = {"phase", "turn", "hands_by_seat", "hidden_burial", "banker",
                "trump_rank", "trump_suit", "trump_is_nt", "attacker_points",
                "kitty_bonus", "declaration", "passed", "last_trick_winner",
                "history", "current_trick", "last_trick"}
    if set(snapshot) != required:
        raise PrivilegedTeacherLunaSelfPlayError("trajectory snapshot schema drift")
    if (snapshot["phase"] != "play"
            or (snapshot["turn"] is not None and
                (isinstance(snapshot["turn"], bool)
                 or not isinstance(snapshot["turn"], int)
                 or snapshot["turn"] not in range(4)))
            or snapshot["turn"] is None
            or isinstance(snapshot["banker"], bool)
            or snapshot["banker"] not in range(4)
            or type(snapshot["trump_rank"]) is not str
            or snapshot["trump_rank"] not in RANKS
            or (snapshot["trump_suit"] is not None
                and (type(snapshot["trump_suit"]) is not str
                     or snapshot["trump_suit"] not in ("S", "H", "C", "D")))
            or type(snapshot["trump_is_nt"]) is not bool
            or (snapshot["trump_is_nt"] and snapshot["trump_suit"] is not None)
            or (not snapshot["trump_is_nt"] and snapshot["trump_suit"] is None)
            or type(snapshot["hands_by_seat"]) is not list
            or len(snapshot["hands_by_seat"]) != 4
            or any(type(hand) is not list or
                   any(type(card) is not str for card in hand)
                   for hand in snapshot["hands_by_seat"])
            or type(snapshot["hidden_burial"]) is not list
            or any(type(card) is not str for card in snapshot["hidden_burial"])
            or type(snapshot["history"]) is not list
            or type(snapshot["current_trick"]) not in (dict, type(None))
            or type(snapshot["last_trick"]) not in (dict, type(None))
            or (snapshot["last_trick_winner"] is not None
                and (isinstance(snapshot["last_trick_winner"], bool)
                     or snapshot["last_trick_winner"] not in range(4)))
            or type(snapshot["passed"]) is not list
            or any(isinstance(seat, bool) or not isinstance(seat, int)
                   or seat not in range(4) for seat in snapshot["passed"])
            or isinstance(snapshot["attacker_points"], bool)
            or not isinstance(snapshot["attacker_points"], int)
            or snapshot["attacker_points"] < 0
            or isinstance(snapshot["kitty_bonus"], bool)
            or not isinstance(snapshot["kitty_bonus"], int)
            or snapshot["kitty_bonus"] < 0):
        raise PrivilegedTeacherLunaSelfPlayError("trajectory snapshot type drift")
    if snapshot["declaration"] is not None:
        declaration = snapshot["declaration"]
        if (type(declaration) is not dict
                or set(declaration) != {"seat", "cards", "strength"}
                or isinstance(declaration["seat"], bool)
                or declaration["seat"] not in range(4)
                or type(declaration["cards"]) is not list
                or any(type(card) is not str for card in declaration["cards"])
                or isinstance(declaration["strength"], bool)
                or not isinstance(declaration["strength"], int)):
            raise PrivilegedTeacherLunaSelfPlayError("trajectory declaration drift")

    def trick(value: object, label: str) -> None:
        if value is None:
            return
        if type(value) is not dict or set(value) != {"leader", "plays", "winner", "points"}:
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} drift")
        if (isinstance(value["leader"], bool) or value["leader"] not in range(4)
                or (value["winner"] is not None
                    and (isinstance(value["winner"], bool)
                         or value["winner"] not in range(4)))
                or isinstance(value["points"], bool) or not isinstance(value["points"], int)
                or value["points"] < 0
                or type(value["plays"]) is not list):
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} drift")
        seats = []
        for play in value["plays"]:
            if (type(play) is not dict or set(play) != {"seat", "cards"}
                    or isinstance(play["seat"], bool) or play["seat"] not in range(4)
                    or type(play["cards"]) is not list or not play["cards"]
                    or any(type(card) is not str for card in play["cards"])):
                raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} play drift")
            seats.append(play["seat"])
        if len(seats) != len(set(seats)):
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} seat drift")
        if label.startswith("history[") and len(seats) != 4:
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} incomplete")
        if label.startswith("history[") and value["winner"] is None:
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} winner drift")
        if label == "current trick" and len(seats) >= 4:
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} incomplete")
        if label == "current trick" and value["winner"] is not None:
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} winner drift")
        if label == "last trick" and len(seats) != 4:
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} incomplete")
        if label == "last trick" and value["winner"] is None:
            raise PrivilegedTeacherLunaSelfPlayError(f"trajectory {label} winner drift")
    for index, value in enumerate(snapshot["history"]):
        trick(value, f"history[{index}]")
    trick(snapshot["current_trick"], "current trick")
    trick(snapshot["last_trick"], "last trick")
    if (snapshot["current_trick"] is not None
            and len(snapshot["current_trick"]["plays"]) >= 4):
        raise PrivilegedTeacherLunaSelfPlayError("trajectory current trick complete")
    if snapshot["history"]:
        if snapshot["last_trick"] != snapshot["history"][-1]:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory last trick mismatch")
        if (snapshot["last_trick_winner"] is not None
                and snapshot["last_trick_winner"] != snapshot["last_trick"]["winner"]):
            raise PrivilegedTeacherLunaSelfPlayError("trajectory winner mismatch")
    elif snapshot["last_trick"] is not None or snapshot["last_trick_winner"] is not None:
        raise PrivilegedTeacherLunaSelfPlayError("trajectory last trick presence drift")


def _trick_from_snapshot(value: Mapping[str, object]) -> Trick:
    return Trick(leader=value["leader"],
                 plays=[TrickPlay(seat=play["seat"], cards=list(play["cards"]))
                        for play in value["plays"]],
                 winner=value["winner"], points=value["points"])


def _round_from_snapshot(snapshot: Mapping[str, object]) -> Round:
    """Rebuild the public engine state needed to replay one recorded action."""
    _validate_snapshot(dict(snapshot))
    if snapshot.get("terminal_redacted"):
        raise PrivilegedTeacherLunaSelfPlayError("cannot replay redacted state")
    rnd = Round(snapshot["trump_rank"], banker=snapshot["banker"])
    rnd.phase = "play"
    rnd.turn = snapshot["turn"]
    rnd.hands = [list(hand) for hand in snapshot["hands_by_seat"]]
    rnd.buried = list(snapshot["hidden_burial"])
    rnd.trump_suit = snapshot["trump_suit"]
    rnd.trump_is_nt = snapshot["trump_is_nt"]
    rnd.ordering = Ordering(rnd.trump_suit, rnd.trump_rank)
    rnd.declaration = (None if snapshot["declaration"] is None
                       else dict(snapshot["declaration"]))
    rnd.passed = set(snapshot["passed"])
    rnd.attacker_points = snapshot["attacker_points"]
    rnd.kitty_bonus = snapshot["kitty_bonus"]
    rnd.history = [_trick_from_snapshot(value) for value in snapshot["history"]]
    rnd.last_trick = (None if snapshot["last_trick"] is None
                      else _trick_from_snapshot(snapshot["last_trick"]))
    rnd.last_trick_winner = snapshot["last_trick_winner"]
    rnd.trick = (None if snapshot["current_trick"] is None
                 else _trick_from_snapshot(snapshot["current_trick"]))
    return rnd


def _validate_transition(event: Mapping[str, object]) -> None:
    before = event["state_before"]
    after = event["state_after"]
    if not before:
        raise PrivilegedTeacherLunaSelfPlayError("trajectory transition state drift")
    replay = _round_from_snapshot(before)
    try:
        replay.play(event["seat"], list(event["action"]))
    except Exception as exc:
        raise PrivilegedTeacherLunaSelfPlayError(
            "trajectory transition engine drift") from exc
    replayed = _state_snapshot(replay)
    if after.get("terminal_redacted"):
        if replayed.get("phase") != "round_end":
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory terminal transition drift")
        return
    if replayed != after:
        raise PrivilegedTeacherLunaSelfPlayError(
            "trajectory transition mechanics drift")


def _replay_trajectory(trajectory: "SealedTrajectory") -> Round:
    """Replay every recorded action through a reconstructed engine Round."""
    events = trajectory.body["events"]
    if type(events) is not list or not events:
        raise PrivilegedTeacherLunaSelfPlayError("trajectory is not complete")
    first = events[0]
    if first["state_before"] in ({}, None) or first["state_before"].get(
            "terminal_redacted"):
        raise PrivilegedTeacherLunaSelfPlayError("trajectory root state absent")
    if _root_identity_snapshot(first["state_before"]) != trajectory.body[
            "root_sha256"]:
        raise PrivilegedTeacherLunaSelfPlayError("trajectory root replay drift")
    rnd = _round_from_snapshot(first["state_before"])
    for index, event in enumerate(events):
        if _state_digest(rnd, event["team"]) != event["state_sha256"]:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory state replay drift")
        if _state_snapshot(rnd) != event["state_before"]:
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory state-before replay drift")
        try:
            rnd.play(event["seat"], list(event["action"]))
        except Exception as exc:
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory action replay drift") from exc
        actual = _state_snapshot(rnd)
        recorded = event["state_after"]
        if recorded.get("terminal_redacted"):
            if actual.get("phase") != "round_end" or index != len(events) - 1:
                raise PrivilegedTeacherLunaSelfPlayError(
                    "trajectory terminal replay drift")
        elif actual != recorded:
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory state-after replay drift")
    return rnd
    seat = event["seat"]
    action = event["action"]
    hands_before = before["hands_by_seat"]
    hands_after = after["hands_by_seat"]
    if before["turn"] != seat or len(hands_before) != len(hands_after):
        raise PrivilegedTeacherLunaSelfPlayError("trajectory transition turn drift")
    for index, (old, new) in enumerate(zip(hands_before, hands_after)):
        expected = list(old)
        if index == seat:
            for card in action:
                if card not in expected:
                    raise PrivilegedTeacherLunaSelfPlayError(
                        "trajectory transition action absent")
                expected.remove(card)
        if sorted(expected) != sorted(new):
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory transition hand drift")


@dataclass
class PrivateTrajectory:
    """Append-only sealed state/action evidence; never a value target."""

    coordinate: tuple[str, int, int]
    mirror: int
    root_sha256: str = "0" * 64
    execution_binding: Mapping[str, object] | None = None
    _events: list[dict[str, object]] = field(default_factory=list, repr=False)
    _sealed: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        LunaCoordinate(*self.coordinate)
        if isinstance(self.mirror, bool) or self.mirror not in MIRRORS:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory mirror drift")
        _strict_sha(self.root_sha256, "trajectory root SHA")
        expected = _execution_binding(self.coordinate, self.mirror,
                                      self.root_sha256)
        if self.execution_binding is None:
            self.execution_binding = expected
        elif self.execution_binding != expected:
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory execution binding drift")

    def append(self, *, team: int, seat: int, state_sha256: str,
               action: Sequence[str], candidate_index: int,
               state_before: Mapping[str, object] | None = None,
               state_after: Mapping[str, object] | None = None,
               legal_ballot: Sequence[Sequence[str]] | None = None,
               production_prior: Sequence[Sequence[str]] | None = None) -> None:
        if self._sealed:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory already sealed")
        if state_before is None or state_after is None:
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory snapshots are required")
        if (isinstance(team, bool) or team not in TEAMS
                or isinstance(seat, bool) or seat not in range(4)
                or seat % 2 != team
                or isinstance(candidate_index, bool)
                or not isinstance(candidate_index, int)
                or candidate_index < 0):
            raise PrivilegedTeacherLunaSelfPlayError("trajectory identity drift")
        _strict_sha(state_sha256, "trajectory state SHA")
        if legal_ballot is not None:
            if isinstance(legal_ballot, (str, bytes)) \
                    or not isinstance(legal_ballot, Sequence) \
                    or candidate_index >= len(legal_ballot):
                raise PrivilegedTeacherLunaSelfPlayError(
                    "trajectory candidate index drift")
        if legal_ballot is None:
            legal_ballot = [action]
        if production_prior is None:
            production_prior = [action]
        _card_action(action)
        _card_action(legal_ballot[candidate_index])
        if list(action) != list(legal_ballot[candidate_index]):
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory action ballot mismatch")
        event = {"index": len(self._events), "team": team, "seat": seat,
                 "state_sha256": state_sha256, "action": list(action),
                 "candidate_index": candidate_index,
                 "state_before": dict(state_before),
                 "state_after": dict(state_after),
                 "legal_ballot": [list(row) for row in legal_ballot],
                 "production_prior": [list(row)
                                      for row in production_prior]}
        if _contains_forbidden_key(event):
            raise PrivilegedTeacherLunaSelfPlayError("trajectory value label drift")
        _validate_snapshot(event["state_before"])
        _validate_snapshot(event["state_after"])
        self._events.append(event)

    def record_model_text(self, text: object) -> None:
        del text
        raise PrivilegedTeacherLunaSelfPlayError(
            "model prose is not part of trajectory")

    @property
    def events(self) -> tuple[Mapping[str, object], ...]:
        return tuple(dict(event) for event in self._events)

    def seal(self) -> "SealedTrajectory":
        if self._sealed:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory already sealed")
        self._sealed = True
        body = {"schema": TRAJECTORY_SCHEMA, "private": True,
                "coordinate": list(self.coordinate), "mirror": self.mirror,
                "root_sha256": self.root_sha256,
                "execution_binding": dict(self.execution_binding),
                "events": list(self._events)}
        return SealedTrajectory(body=body, sha256=_sha(body))


@dataclass(frozen=True)
class SealedTrajectory:
    body: Mapping[str, object]
    sha256: str
    raw_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (type(self.body) is not dict
                or set(self.body) != {"schema", "private", "coordinate",
                                      "mirror", "root_sha256",
                                      "execution_binding", "events"}
                or self.body.get("schema") != TRAJECTORY_SCHEMA \
                or self.body.get("private") is not True \
                or self.sha256 != _sha(self.body)):
            raise PrivilegedTeacherLunaSelfPlayError("trajectory seal drift")
        object.__setattr__(self, "raw_bytes", canonical_json_bytes(self.body))
        coordinate = self.body.get("coordinate")
        mirror = self.body.get("mirror")
        if (type(coordinate) is not list or len(coordinate) != 3
                or type(mirror) is not int or isinstance(mirror, bool)):
            raise PrivilegedTeacherLunaSelfPlayError("trajectory identity drift")
        LunaCoordinate(*coordinate)
        if mirror not in MIRRORS:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory mirror drift")
        _strict_sha(self.body.get("root_sha256"), "trajectory root SHA")
        if self.body["execution_binding"] != _execution_binding(
                coordinate, mirror, self.body["root_sha256"]):
            raise PrivilegedTeacherLunaSelfPlayError(
                "trajectory execution binding drift")
        events = self.body.get("events")
        if type(events) is not list:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory event drift")
        for index, event in enumerate(events):
            if type(event) is not dict \
                    or set(event) != {"index", "team", "seat", "state_sha256",
                                     "action", "candidate_index", "state_before",
                                     "state_after", "legal_ballot",
                                     "production_prior"} \
                    or _contains_forbidden_key(event):
                raise PrivilegedTeacherLunaSelfPlayError("trajectory value label drift")
            if (event.get("index") != index
                    or isinstance(event.get("team"), bool)
                    or event.get("team") not in TEAMS
                    or isinstance(event.get("seat"), bool)
                    or event.get("seat") not in range(4)
                    or event.get("seat") % 2 != event.get("team")
                    or type(event.get("action")) is not list
                    or not event.get("action")
                    or any(type(card) is not str for card in event["action"])
                    or isinstance(event.get("candidate_index"), bool)
                    or not isinstance(event.get("candidate_index"), int)
                    or event.get("candidate_index") < 0):
                raise PrivilegedTeacherLunaSelfPlayError("trajectory event identity drift")
            _strict_sha(event.get("state_sha256"), "trajectory state SHA")
            _validate_snapshot(event.get("state_before"))
            _validate_snapshot(event.get("state_after"))
            if event["state_before"]:
                expected_state = _sha({"team": event["team"],
                                       "snapshot": event["state_before"]})
                if event["state_sha256"] != expected_state:
                    raise PrivilegedTeacherLunaSelfPlayError(
                        "trajectory state binding drift")
                if index == 0 and _root_identity_snapshot(
                        event["state_before"]) != self.body["root_sha256"]:
                    raise PrivilegedTeacherLunaSelfPlayError(
                        "trajectory root binding drift")
            if index and events[index - 1]["state_after"] != event["state_before"]:
                raise PrivilegedTeacherLunaSelfPlayError(
                    "trajectory state continuity drift")
            ballot = event.get("legal_ballot")
            prior = event.get("production_prior")
            if (type(ballot) is not list or not ballot
                    or event["candidate_index"] >= len(ballot)
                    or any(type(action) is not list or not action
                           or any(type(card) is not str for card in action)
                           for action in ballot)
                    or type(prior) is not list or not prior
                    or any(type(action) is not list or not action
                           or any(type(card) is not str for card in action)
                           for action in prior)
                    or ballot[0] not in prior
                    or event["action"] != ballot[event["candidate_index"]]):
                raise PrivilegedTeacherLunaSelfPlayError(
                    "trajectory ballot/action drift")

    def payload(self) -> dict[str, object]:
        self._assert_intact()
        return {"schema": TRAJECTORY_SCHEMA, "private": True,
                "trajectory_sha256": self.sha256}

    def private_bytes(self) -> bytes:
        self._assert_intact()
        return self.raw_bytes

    def _assert_intact(self) -> None:
        if (canonical_json_bytes(self.body) != self.raw_bytes
                or _sha(self.body) != self.sha256):
            raise PrivilegedTeacherLunaSelfPlayError("trajectory post-seal tamper")

    @classmethod
    def reopen(cls, raw: bytes) -> "SealedTrajectory":
        if type(raw) is not bytes:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory raw type drift")
        try:
            body = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory raw JSON drift") from exc
        if type(body) is not dict or canonical_json_bytes(body) != raw:
            raise PrivilegedTeacherLunaSelfPlayError("trajectory raw canonical drift")
        return cls(body=body, sha256=_sha(body))


@dataclass(frozen=True)
class TerminalReceipt:
    """Separate terminal truth receipt; never part of a trajectory."""

    coordinate: tuple[str, int, int]
    mirror: int
    root_sha256: str
    trajectory_sha256: str
    final_attacker_points: int
    signed_level_utility: int
    completion: bool
    receipt_sha256: str = ""
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def __post_init__(self) -> None:
        if not self.receipt_sha256:
            object.__setattr__(self, "receipt_sha256",
                               _sha({key: value for key, value in self.payload().items()
                                     if key != "receipt_sha256"}))
        validate_terminal_receipt(self.payload())

    def payload(self) -> dict[str, object]:
        return {"schema": TERMINAL_RECEIPT_SCHEMA,
                "coordinate": list(self.coordinate), "mirror": self.mirror,
                "root_sha256": self.root_sha256,
                "trajectory_sha256": self.trajectory_sha256,
                "final_attacker_points": self.final_attacker_points,
                "signed_level_utility": self.signed_level_utility,
                "completion": self.completion,
                "receipt_sha256": self.receipt_sha256,
                "authority": dict(self.authority)}


def validate_terminal_receipt(receipt: Mapping[str, object], *,
                              root_sha256: str | None = None,
                              trajectory_sha256: str | None = None,
                              coordinate: Sequence[object] | None = None,
                              mirror: int | None = None) -> None:
    expected = {"schema", "coordinate", "mirror", "root_sha256",
                "trajectory_sha256", "final_attacker_points",
                "signed_level_utility", "completion", "receipt_sha256",
                "authority"}
    if type(receipt) is not dict or set(receipt) != expected:
        raise PrivilegedTeacherLunaSelfPlayError("terminal receipt schema drift")
    receipt_coordinate = receipt["coordinate"]
    if type(receipt_coordinate) is not list or len(receipt_coordinate) != 3:
        raise PrivilegedTeacherLunaSelfPlayError("terminal receipt coordinate drift")
    LunaCoordinate(*receipt_coordinate)
    if (isinstance(receipt["mirror"], bool)
            or receipt["mirror"] not in MIRRORS
            or type(receipt["completion"]) is not bool
            or receipt["completion"] is not True
            or isinstance(receipt["final_attacker_points"], bool)
            or not isinstance(receipt["final_attacker_points"], int)
            or isinstance(receipt["signed_level_utility"], bool)
            or not isinstance(receipt["signed_level_utility"], int)
            or receipt["authority"] != AUTHORITY
            or receipt["schema"] != TERMINAL_RECEIPT_SCHEMA):
        raise PrivilegedTeacherLunaSelfPlayError("terminal receipt identity drift")
    _strict_sha(receipt["root_sha256"], "terminal root SHA")
    _strict_sha(receipt["trajectory_sha256"], "terminal trajectory SHA")
    _strict_sha(receipt["receipt_sha256"], "terminal receipt SHA")
    receipt_body = {key: value for key, value in receipt.items()
                    if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != _sha(receipt_body):
        raise PrivilegedTeacherLunaSelfPlayError("terminal receipt hash drift")
    if (root_sha256 is not None and receipt["root_sha256"] != root_sha256
            or trajectory_sha256 is not None
            and receipt["trajectory_sha256"] != trajectory_sha256
            or coordinate is not None and receipt["coordinate"] != list(coordinate)
            or mirror is not None and receipt["mirror"] != mirror):
        raise PrivilegedTeacherLunaSelfPlayError("terminal receipt cross-binding drift")
    expected_utility = sol0.signed_level_utility(
        receipt["final_attacker_points"], banker_seat=receipt_coordinate[1],
        perspective_seat=0)
    if receipt["signed_level_utility"] != expected_utility:
        raise PrivilegedTeacherLunaSelfPlayError("terminal utility drift")


@dataclass(frozen=True)
class CompletedGameArtifacts:
    trajectory: SealedTrajectory
    terminal_receipt: TerminalReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.trajectory, SealedTrajectory) \
                or not isinstance(self.terminal_receipt, TerminalReceipt):
            raise PrivilegedTeacherLunaSelfPlayError(
                "completed artifact type drift")
        self.trajectory._assert_intact()
        if not self.trajectory.body["events"]:
            raise PrivilegedTeacherLunaSelfPlayError(
                "completed trajectory must be nonempty")
        binding = self.trajectory.body["execution_binding"]
        if binding != _execution_binding(
                self.trajectory.body["coordinate"],
                self.trajectory.body["mirror"],
                self.trajectory.body["root_sha256"]):
            raise PrivilegedTeacherLunaSelfPlayError(
                "completed execution binding drift")
        final_round = _replay_trajectory(self.trajectory)
        if final_round.phase != "round_end":
            raise PrivilegedTeacherLunaSelfPlayError(
                "completed trajectory is not terminal")
        validate_terminal_receipt(self.terminal_receipt.payload(),
                                  root_sha256=self.trajectory.body["root_sha256"],
                                  trajectory_sha256=self.trajectory.sha256,
                                  coordinate=self.trajectory.body["coordinate"],
                                  mirror=self.trajectory.body["mirror"])
        if self.terminal_receipt.final_attacker_points != final_round.attacker_points:
            raise PrivilegedTeacherLunaSelfPlayError(
                "completed terminal points drift")

    def payload(self) -> dict[str, object]:
        return {"trajectory_sha256": self.trajectory.sha256,
                "terminal_receipt_sha256": self.terminal_receipt.receipt_sha256}


@dataclass(frozen=True)
class RootCensus:
    body: Mapping[str, object]
    census_sha256: str

    def __post_init__(self) -> None:
        if type(self.body) is not dict:
            raise PrivilegedTeacherLunaSelfPlayError("root census body drift")
        _strict_sha(self.census_sha256, "root census digest")
        if _sha(self.body) != self.census_sha256:
            raise PrivilegedTeacherLunaSelfPlayError("root census hash drift")

    def payload(self) -> dict[str, object]:
        if _sha(self.body) != self.census_sha256:
            raise PrivilegedTeacherLunaSelfPlayError("root census post-seal tamper")
        return {"schema": ROOT_CENSUS_SCHEMA, "census_sha256": self.census_sha256}

    def serialized(self) -> dict[str, object]:
        if _sha(self.body) != self.census_sha256:
            raise PrivilegedTeacherLunaSelfPlayError("root census post-seal tamper")
        return {**dict(self.body), "census_sha256": self.census_sha256}

    @classmethod
    def reopen(cls, serialized: Mapping[str, object],
               *, design: LunaDesign | None = None) -> "RootCensus":
        if type(serialized) is not dict or "census_sha256" not in serialized:
            raise PrivilegedTeacherLunaSelfPlayError("root census digest absent")
        digest = serialized["census_sha256"]
        body = {key: value for key, value in serialized.items()
                if key != "census_sha256"}
        _strict_sha(digest, "root census digest")
        result = cls(body=body, census_sha256=digest)
        validate_root_census(result, design=design)
        return result


def root_census(seed_secret: bytes, design: LunaDesign | None = None) -> RootCensus:
    design = design or LunaDesign()
    rows = []
    for coordinate in design.root_coordinates:
        root = build_root(seed_secret, coordinate)
        root_sha = root_identity(root)
        rows.append({"coordinate": list(coordinate), "root_sha256": root_sha,
                     "mode": root_trump_mode(root),
                     "mirror_root_sha256": root_identity(
                         build_root(seed_secret, coordinate, mirror=1))})
    body = {"schema": ROOT_CENSUS_SCHEMA,
            "seed_commitment_sha256": design.seed_commitment_sha256,
            "coordinates": rows,
            "coordinate_count": len(rows), "mode_count": len(TRUMP_MODES),
            "authority": dict(AUTHORITY)}
    result = RootCensus(body=body, census_sha256=_sha(body))
    validate_root_census(result, design=design)
    return result


def validate_root_census(census: RootCensus | Mapping[str, object],
                         *, design: LunaDesign | None = None) -> None:
    design = design or LunaDesign()
    body = census.body if isinstance(census, RootCensus) else census
    digest = census.census_sha256 if isinstance(census, RootCensus) else (
        body.get("census_sha256") if type(body) is dict else None)
    if not isinstance(census, RootCensus):
        if type(body) is not dict or "census_sha256" not in body:
            raise PrivilegedTeacherLunaSelfPlayError("root census digest absent")
        body = {key: value for key, value in body.items()
                if key != "census_sha256"}
    if type(body) is not dict or set(body) != {"schema", "seed_commitment_sha256",
            "coordinates", "coordinate_count", "mode_count", "authority"}:
        raise PrivilegedTeacherLunaSelfPlayError("root census schema drift")
    rows = body["coordinates"]
    if (body["schema"] != ROOT_CENSUS_SCHEMA
            or body["seed_commitment_sha256"] != design.seed_commitment_sha256
            or type(rows) is not list
            or len(rows) != len(design.root_coordinates)
            or body["coordinate_count"] != len(rows)
            or body["mode_count"] != len(TRUMP_MODES)
            or body["authority"] != AUTHORITY):
        raise PrivilegedTeacherLunaSelfPlayError("root census identity drift")
    expected = list(design.root_coordinates)
    hashes = set()
    modes = set()
    for row, coordinate in zip(rows, expected):
        if type(row) is not dict or set(row) != {"coordinate", "root_sha256",
                "mode", "mirror_root_sha256"} or row["coordinate"] != list(coordinate):
            raise PrivilegedTeacherLunaSelfPlayError("root census coordinate drift")
        _strict_sha(row["root_sha256"], "root census SHA")
        _strict_sha(row["mirror_root_sha256"], "mirror root SHA")
        if row["root_sha256"] != row["mirror_root_sha256"] \
                or row["mode"] not in TRUMP_MODES:
            raise PrivilegedTeacherLunaSelfPlayError("root census mirror/mode drift")
        hashes.add(row["root_sha256"])
        modes.add(row["mode"])
    if len(hashes) != len(expected) or modes != set(TRUMP_MODES):
        raise PrivilegedTeacherLunaSelfPlayError("root census coverage drift")
    if digest != _sha(body):
        raise PrivilegedTeacherLunaSelfPlayError("root census hash drift")


def _state_digest(rnd: Round, team: int) -> str:
    return _sha({"team": team, "snapshot": _state_snapshot(rnd)})


def _state_snapshot(rnd: Round) -> dict[str, object]:
    """Complete private mechanics state, excluding terminal value labels."""
    if rnd.phase == "round_end":
        return {"phase": "round_end", "terminal_redacted": True}
    return {"phase": rnd.phase, "turn": rnd.turn,
            "hands_by_seat": [sorted(hand) for hand in rnd.hands],
            "hidden_burial": sorted(rnd.buried), "banker": rnd.banker,
            "trump_rank": rnd.trump_rank, "trump_suit": rnd.trump_suit,
            "trump_is_nt": rnd.trump_is_nt,
            "attacker_points": rnd.attacker_points,
            "kitty_bonus": rnd.kitty_bonus,
            "declaration": (None if rnd.declaration is None else
                            dict(rnd.declaration)),
            "passed": sorted(rnd.passed),
            "last_trick_winner": rnd.last_trick_winner,
            "last_trick": (None if rnd.last_trick is None else {
                "leader": rnd.last_trick.leader,
                "plays": [{"seat": p.seat, "cards": list(p.cards)}
                          for p in rnd.last_trick.plays],
                "winner": rnd.last_trick.winner,
                "points": rnd.last_trick.points,
            }),
            "history": [{"leader": trick.leader,
                         "plays": [{"seat": p.seat, "cards": list(p.cards)}
                                   for p in trick.plays],
                         "winner": trick.winner, "points": trick.points}
                        for trick in rnd.history],
            "current_trick": None if rnd.trick is None else {
                "leader": rnd.trick.leader,
                "plays": [{"seat": p.seat, "cards": list(p.cards)}
                          for p in rnd.trick.plays],
                "winner": rnd.trick.winner,
                "points": rnd.trick.points,
            }}


class LunaSelfPlayGame:
    """One shared engine Round and two team-scoped planner sessions."""

    def __init__(self, root: Round, *, coordinate: tuple[str, int, int] | None = None,
                 mirror: int = 0, seed_secret: bytes = b"0" * 32):
        if type(root) is not Round or root.phase != "play" or root.turn is None \
                or root.ordering is None or root.banker is None:
            raise PrivilegedTeacherLunaSelfPlayError("game root drift")
        if isinstance(mirror, bool) or mirror not in MIRRORS:
            raise PrivilegedTeacherLunaSelfPlayError("mirror identity drift")
        coordinate = coordinate or (root.trump_rank, root.banker, 0)
        LunaCoordinate(*coordinate)
        self.rnd = root
        self.coordinate = coordinate
        self.mirror = mirror
        self.root_sha256 = root_identity(root)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._failed: str | None = None
        self._sealed_result: SealedTrajectory | None = None
        self._sessions: dict[int, LunaTeamSession] = {}
        self.trajectory = PrivateTrajectory(coordinate, mirror,
                                            root_sha256=self.root_sha256)
        self._ballots = [c0.C0WideHeuristicBot(seed=_seed(seed_secret, "ballot", *coordinate, seat))
                         for seat in range(4)]
        self._advance_forced()

    @property
    def failed(self) -> str | None:
        return self._failed

    @property
    def complete(self) -> bool:
        return self.rnd.phase == "round_end" and self._failed is None

    @property
    def acting_team(self) -> int | None:
        return None if self.rnd.turn is None else self.rnd.turn % 2

    def session(self, team: int) -> "LunaTeamSession":
        if team not in TEAMS:
            raise PrivilegedTeacherLunaSelfPlayError("team identity drift")
        if team not in self._sessions:
            self._sessions[team] = LunaTeamSession(self, team)
        return self._sessions[team]

    def sealed_trajectory(self) -> SealedTrajectory:
        if not self.complete and self.failed is None:
            raise PrivilegedTeacherLunaSelfPlayError(
                "cannot seal unfinished game")
        if self._sealed_result is None:
            self._sealed_result = self.trajectory.seal()
        return self._sealed_result

    def terminal_receipt(self) -> TerminalReceipt:
        if not self.complete:
            raise PrivilegedTeacherLunaSelfPlayError(
                "cannot receipt unfinished game")
        trajectory = self.sealed_trajectory()
        assert self.rnd.banker is not None
        receipt = TerminalReceipt(
            coordinate=self.coordinate, mirror=self.mirror,
            root_sha256=self.root_sha256, trajectory_sha256=trajectory.sha256,
            final_attacker_points=self.rnd.attacker_points,
            signed_level_utility=sol0.signed_level_utility(
                self.rnd.attacker_points, banker_seat=self.rnd.banker,
                perspective_seat=0), completion=True)
        validate_terminal_receipt(receipt.payload())
        return receipt

    def completed_artifacts(self) -> CompletedGameArtifacts:
        if not self.complete:
            raise PrivilegedTeacherLunaSelfPlayError(
                "cannot artifact unfinished game")
        return CompletedGameArtifacts(self.sealed_trajectory(),
                                      self.terminal_receipt())

    def fail(self, reason: str) -> None:
        with self._condition:
            if self._failed is None:
                self._failed = str(reason)
            self._condition.notify_all()

    def wait_for_turn(self, team: int, timeout: float | None = 0.0) -> bool:
        if team not in TEAMS:
            raise LunaPlannerRequestError("team identity drift")
        with self._condition:
            if timeout is not None and (isinstance(timeout, bool) or timeout < 0):
                raise LunaPlannerRequestError("wait timeout drift")
            if self._failed is not None or self.complete:
                return False
            if self.acting_team == team:
                return True
            self._condition.wait(timeout)
            return self._failed is None and self.acting_team == team

    def _candidates(self, seat: int) -> list[list[str]]:
        result = self._ballots[seat]._candidates(self.rnd, seat)
        if not result:
            raise PrivilegedTeacherLunaSelfPlayError("empty production ballot")
        # Card order is canonicalized before it reaches the engine so the
        # sealed action and the engine's recorded TrickPlay are identical.
        return [list(_card_action(cards)) for cards in result]

    def _advance_forced(self) -> None:
        while self.rnd.phase == "play":
            seat = self.rnd.turn
            if seat is None:
                self.fail("engine turn absent")
                return
            candidates = self._candidates(seat)
            if len(candidates) != 1:
                return
            cards = candidates[0]
            state_sha = _state_digest(self.rnd, seat % 2)
            before = _state_snapshot(self.rnd)
            prior = sorted(c0._production_ballot(self.rnd, seat))
            self.rnd.play(seat, cards)
            self.trajectory.append(team=seat % 2, seat=seat,
                                  state_sha256=state_sha,
                                  action=cards, candidate_index=0,
                                  state_before=before,
                                  state_after=_state_snapshot(self.rnd),
                                  legal_ballot=candidates,
                                  production_prior=prior)

    def observe(self, team: int) -> dict[str, object]:
        with self._condition:
            if self._failed is not None:
                return {"schema": GAME_SCHEMA, "status": "failed",
                        "error": self._failed}
            if self.complete:
                return {"schema": GAME_SCHEMA, "status": "round_end"}
            if self.acting_team != team:
                return {"schema": GAME_SCHEMA, "status": "waiting",
                        "acting_team": self.acting_team,
                        "banker": self.rnd.banker,
                        "trump_rank": self.rnd.trump_rank,
                        "hands_by_seat": [sorted(hand) for hand in self.rnd.hands],
                        "hidden_burial": sorted(self.rnd.buried),
                        "current_state": _state_snapshot(self.rnd)}
            seat = self.rnd.turn
            assert seat is not None
            candidates = self._candidates(seat)
            return {"schema": GAME_SCHEMA, "status": "decision",
                    "decision_sha256": _state_digest(self.rnd, team),
                    "team": team, "acting_seat": seat,
                    "banker": self.rnd.banker, "trump_rank": self.rnd.trump_rank,
                    "hands_by_seat": [sorted(hand) for hand in self.rnd.hands],
                    "hidden_burial": sorted(self.rnd.buried),
                    "current_state": _state_snapshot(self.rnd),
                    "candidates": [list(cards) for cards in candidates],
                    "candidate_zero_is_production_prior": True,
                    "budget": self.session(team).budget_payload()}

    def evaluate(self, team: int, index: int, continuation: str) -> dict[str, object]:
        with self._condition:
            if self._failed is not None:
                raise PrivilegedTeacherLunaSelfPlayError(self._failed)
            if self.acting_team != team:
                raise LunaPlannerRequestError("non-acting planner cannot rollout")
            if continuation not in sol0.CONTINUATIONS:
                raise LunaPlannerRequestError("continuation drift")
            seat = self.rnd.turn
            if seat is None:
                raise PrivilegedTeacherLunaSelfPlayError("engine turn absent")
            candidates = self._candidates(seat)
            if isinstance(index, bool) or not isinstance(index, int) \
                    or not 0 <= index < len(candidates):
                raise LunaPlannerRequestError("candidate outside ballot")
            # Evaluate a copy: the live Round remains the sole state authority.
            evaluator = c0.C0ProductionBallotBot(seed=0)
            policy, exact = sol0._continuation(continuation, team)
            evaluator.rollout_policy = policy
            evaluator.EXACT_ENDGAME = exact
            clone = self.rnd
            sampled = {seat: list(clone.hands[seat]) for seat in range(4)
                       if seat != clone.turn}
            exact_session = evaluator._new_exact_world_session(clone, list(clone.buried))
            points = evaluator._rollout(clone, clone.turn, sampled,
                                        list(clone.buried), candidates[index],
                                        exact_session=exact_session)
            if isinstance(points, bool) or not isinstance(points, (int, float)) \
                    or not math.isfinite(points) or not float(points).is_integer():
                raise PrivilegedTeacherLunaSelfPlayError("rollout result drift")
            return {"candidate_index": index, "continuation": continuation,
                    "rollout_points": int(points)}

    def commit(self, team: int, decision_sha256: str, index: int) -> dict[str, object]:
        with self._condition:
            if self._failed is not None:
                raise PrivilegedTeacherLunaSelfPlayError(self._failed)
            if self.complete:
                raise LunaPlannerRequestError("round already ended")
            if self.acting_team != team:
                raise LunaPlannerRequestError("non-acting planner cannot play")
            seat = self.rnd.turn
            assert seat is not None
            state_sha = _state_digest(self.rnd, team)
            if decision_sha256 != state_sha:
                raise LunaPlannerRequestError("decision binding drift")
            candidates = self._candidates(seat)
            if isinstance(index, bool) or not isinstance(index, int) \
                    or not 0 <= index < len(candidates):
                raise LunaPlannerRequestError("candidate outside ballot")
            cards = candidates[index]
            before = _state_snapshot(self.rnd)
            prior = sorted(c0._production_ballot(self.rnd, seat))
            self.rnd.play(seat, cards)
            self.trajectory.append(team=team, seat=seat, state_sha256=state_sha,
                                  action=cards, candidate_index=index,
                                  state_before=before,
                                  state_after=_state_snapshot(self.rnd),
                                  legal_ballot=candidates,
                                  production_prior=prior)
            self._advance_forced()
            self._condition.notify_all()
            return {"schema": GAME_SCHEMA,
                    "status": "round_end" if self.complete else
                    ("failed" if self._failed else "waiting"),
                    "acting_team": self.acting_team}


class LunaTeamSession:
    """Independent team identity, memory, and PT-Sol0-style budget."""

    def __init__(self, game: LunaSelfPlayGame, team: int):
        self.game = game
        self.team = team
        self.controlled_seats = (team, team + 2)
        self.model = MODEL
        self.memory: dict[str, object] = {}
        self.agent_identity = agent_for_team(game.mirror, team)
        execution = game.trajectory.execution_binding
        session_record = next(row for row in execution["sessions"]
                              if row["team"] == team)
        self.session_id = session_record["session_id"]
        # This is an identity receipt for the process boundary.  The harness
        # intentionally does not launch a model process during unit tests.
        self.model_process_id = session_record["model_process_id"]
        # The token is disclosed only after the shared engine reaches
        # round_end.  It proves that this specific planner stayed attached to
        # its mailbox until completion instead of emitting an early generic
        # success response.
        self._completion_token = secrets.token_hex(32)
        self._cache: dict[tuple[int, str], dict[str, object]] = {}
        self._calls = 0
        self._used = 0
        self._round_used = 0
        self._decision_key: str | None = None

    def _sync_decision(self) -> None:
        """Reset Sol0's per-decision cache after a committed engine action."""
        if self.game.acting_team != self.team or self.game.rnd.turn is None:
            return
        key = _state_digest(self.game.rnd, self.team)
        if key != self._decision_key:
            self._decision_key = key
            self._cache.clear()
            self._calls = 0
            self._used = 0

    @property
    def failed(self) -> str | None:
        return self.game.failed

    @property
    def planner_identity(self) -> dict[str, str | int]:
        return {"team": self.team, "model": self.model,
                "agent_identity": self.agent_identity,
                "model_process_id": self.model_process_id,
                "session_id": self.session_id}

    @property
    def complete(self) -> bool:
        return self.game.complete

    def budget_payload(self) -> dict[str, int]:
        self._sync_decision()
        return {"rollout_calls": self._calls,
                "rollout_calls_limit": sol0.MAX_ROLLOUT_CALLS_PER_DECISION,
                "used": self._used,
                "round_used": self._round_used,
                "decision_limit": sol0.MAX_EVALUATIONS_PER_DECISION,
                "round_limit": sol0.MAX_EVALUATIONS_PER_ROUND}

    def observe(self) -> dict[str, object]:
        self._sync_decision()
        response = self.game.observe(self.team)
        if response.get("status") == "round_end":
            response = {**response, "completion_token": self._completion_token}
        return response

    def wait(self, timeout: float | None = 0.0) -> bool:
        return self.game.wait_for_turn(self.team, timeout)

    def rollout(self, request: Mapping[str, object]) -> dict[str, object]:
        self._sync_decision()
        expected = {"op", "decision_sha256", "candidate_indices", "continuations"}
        if type(request) is not dict or set(request) != expected \
                or request.get("op") != "rollout":
            raise LunaPlannerRequestError("rollout request shape drift")
        observed = self.observe()
        if observed.get("status") != "decision" \
                or request["decision_sha256"] != observed["decision_sha256"]:
            raise LunaPlannerRequestError("rollout decision binding drift")
        candidates = request["candidate_indices"]
        continuations = request["continuations"]
        if (type(candidates) is not list or not candidates
                or type(continuations) is not list or not continuations
                or any(isinstance(index, bool) or not isinstance(index, int)
                       for index in candidates)
                or any(type(name) is not str for name in continuations)
                or len(set(candidates)) != len(candidates)
                or len(set(continuations)) != len(continuations)):
            raise LunaPlannerRequestError("rollout request shape drift")
        keys = [(index, name) for index in candidates for name in continuations]
        if len(keys) > sol0.MAX_NEW_EVALUATIONS_PER_CALL:
            raise LunaPlannerRequestError("rollout per-call budget exceeded")
        new = [key for key in keys if key not in self._cache]
        if self._calls >= sol0.MAX_ROLLOUT_CALLS_PER_DECISION:
            raise LunaPlannerRequestError("rollout call budget exceeded")
        if self._used + len(new) > sol0.MAX_EVALUATIONS_PER_DECISION:
            raise LunaPlannerRequestError("rollout decision budget exceeded")
        if self._round_used + len(new) > sol0.MAX_EVALUATIONS_PER_ROUND:
            raise LunaPlannerRequestError("rollout round budget exceeded")
        for index, name in new:
            self._cache[(index, name)] = self.game.evaluate(self.team, index, name)
        self._calls += 1
        self._used += len(new)
        self._round_used += len(new)
        return {"schema": GAME_SCHEMA, "status": "rollout_complete",
                "new_evaluations": len(new),
                "cached_evaluations": len(keys) - len(new),
                "results": [dict(self._cache[key]) for key in keys],
                "budget": self.budget_payload()}

    def play(self, request: Mapping[str, object]) -> dict[str, object]:
        if type(request) is not dict or set(request) != {
                "op", "decision_sha256", "candidate_index", "confidence"} \
                or request.get("op") != "play":
            raise LunaPlannerRequestError("play request shape drift")
        if request["confidence"] not in sol0.CONFIDENCE_LEVELS:
            raise LunaPlannerRequestError("confidence drift")
        response = self.game.commit(self.team, request["decision_sha256"],
                                    request["candidate_index"])
        if response.get("status") == "round_end":
            response = {**response, "completion_token": self._completion_token}
        return response


def progress(*, completed_games: int, total_games: int,
             completed_deal_clusters: int, total_deal_clusters: int,
             elapsed_seconds: float, eta_seconds: float | None = None,
             successful_games: int | None = None, failure_count: int = 0,
             active_game_workers: int = 0, active_model_processes: int = 0,
             recent_games_per_second: float | None = None) \
        -> dict[str, object]:
    for value, label in ((completed_games, "completed games"),
                         (total_games, "total games"),
                         (completed_deal_clusters, "completed clusters"),
                         (total_deal_clusters, "total clusters")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PrivilegedTeacherLunaSelfPlayError(f"{label} drift")
    if total_games <= 0 or total_deal_clusters <= 0 \
            or completed_games > total_games \
            or completed_deal_clusters > total_deal_clusters:
        raise PrivilegedTeacherLunaSelfPlayError("progress population drift")
    if isinstance(elapsed_seconds, bool) or not isinstance(elapsed_seconds, (int, float)) \
            or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
        raise PrivilegedTeacherLunaSelfPlayError("progress elapsed drift")
    if eta_seconds is not None and (isinstance(eta_seconds, bool)
                                    or not isinstance(eta_seconds, (int, float))
                                    or not math.isfinite(eta_seconds)
                                    or eta_seconds < 0):
        raise PrivilegedTeacherLunaSelfPlayError("progress ETA drift")
    if eta_seconds is None:
        eta_seconds = (0.0 if completed_games == total_games else
                       (None if completed_games == 0 else
                        elapsed_seconds * (total_games - completed_games) /
                        completed_games))
    if successful_games is None:
        successful_games = completed_games
    for value, label in ((successful_games, "successful games"),
                         (failure_count, "failure count"),
                         (active_game_workers, "active game workers"),
                         (active_model_processes, "active model processes")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PrivilegedTeacherLunaSelfPlayError(f"{label} drift")
    if (successful_games > completed_games
            or failure_count != completed_games - successful_games):
        raise PrivilegedTeacherLunaSelfPlayError("progress completion drift")
    if recent_games_per_second is None:
        recent_games_per_second = (completed_games / elapsed_seconds
                                   if elapsed_seconds > 0 else 0.0)
    if (isinstance(recent_games_per_second, bool)
            or not isinstance(recent_games_per_second, (int, float))
            or not math.isfinite(recent_games_per_second)
            or recent_games_per_second < 0):
        raise PrivilegedTeacherLunaSelfPlayError("progress throughput drift")
    return {"schema": PROGRESS_SCHEMA, "completed_games": completed_games,
            "processed_games": completed_games,
            "successful_games": successful_games,
            "total_games": total_games,
            "completed_deal_clusters": completed_deal_clusters,
            "total_deal_clusters": total_deal_clusters,
            "percent_basis_points": completed_games * 10_000 // total_games,
            "elapsed_seconds": elapsed_seconds, "eta_seconds": eta_seconds,
            "failure_count": failure_count,
            "active_game_workers": active_game_workers,
            "active_model_processes": active_model_processes,
            "recent_games_per_second": recent_games_per_second}


def validate_progress(payload: Mapping[str, object]) -> None:
    """Reject progress additions or arithmetic drift at a receipt boundary."""
    expected = {"schema", "completed_games", "processed_games",
                "successful_games", "total_games",
                "completed_deal_clusters", "total_deal_clusters",
                "percent_basis_points", "elapsed_seconds", "eta_seconds",
                "failure_count", "active_game_workers",
                "active_model_processes", "recent_games_per_second"}
    if type(payload) is not dict or set(payload) != expected:
        raise PrivilegedTeacherLunaSelfPlayError("progress schema drift")
    row = progress(completed_games=payload["completed_games"],
                   total_games=payload["total_games"],
                   completed_deal_clusters=payload["completed_deal_clusters"],
                   total_deal_clusters=payload["total_deal_clusters"],
                   elapsed_seconds=payload["elapsed_seconds"],
                   eta_seconds=payload["eta_seconds"],
                   successful_games=payload["successful_games"],
                   failure_count=payload["failure_count"],
                   active_game_workers=payload["active_game_workers"],
                   active_model_processes=payload["active_model_processes"],
                   recent_games_per_second=payload["recent_games_per_second"])
    if payload["processed_games"] != payload["completed_games"]:
        raise PrivilegedTeacherLunaSelfPlayError("progress processed count drift")
    if payload != row or payload["schema"] != PROGRESS_SCHEMA:
        raise PrivilegedTeacherLunaSelfPlayError("progress arithmetic drift")


def validate_design(payload: Mapping[str, object],
                    design: LunaDesign | None = None) -> None:
    expected = set((design or LunaDesign()).payload())
    if type(payload) is not dict or set(payload) != expected:
        raise PrivilegedTeacherLunaSelfPlayError("design schema drift")
    if payload != (design or LunaDesign()).payload():
        raise PrivilegedTeacherLunaSelfPlayError("design identity drift")
    if payload["authority"] != AUTHORITY:
        raise PrivilegedTeacherLunaSelfPlayError("design authority drift")


def _complete_cluster_count(rows: Sequence[Mapping[str, object]],
                            design: LunaDesign) -> int:
    return sum(
        sum(tuple(row["cluster_key"]) == key
            and row.get("status") == "complete" for row in rows) == 2
        for key in design.deal_clusters)


def run_population(design: LunaDesign, *, seed_secret: bytes,
                   census: RootCensus | Mapping[str, object],
                   game_runner: Callable[[tuple[str, int, int], int], object] | None = None,
                   worker_count: int = 1,
                   progress_sink: Callable[[dict[str, object]], object] | None = None,
                   active_model_processes: int | Callable[[], int] = 0
                   ) -> dict[str, object]:
    """Collect each mirror once, retaining incomplete rows and never retrying."""
    validate_game_workers(worker_count)
    if not callable(game_runner):
        raise PrivilegedTeacherLunaSelfPlayError("game runner is required")
    if isinstance(census, RootCensus):
        validate_root_census(census, design=design)
    else:
        census = RootCensus.reopen(census, design=design)
    if not callable(active_model_processes) and (
            isinstance(active_model_processes, bool)
            or not isinstance(active_model_processes, int)
            or active_model_processes < 0):
        raise PrivilegedTeacherLunaSelfPlayError(
            "active model process count drift")

    def measured_model_processes() -> int:
        value = (active_model_processes() if callable(active_model_processes)
                 else active_model_processes)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PrivilegedTeacherLunaSelfPlayError(
                "active model process count drift")
        return value
    if hashlib.sha256(seed_secret).hexdigest() != design.seed_commitment_sha256:
        raise PrivilegedTeacherLunaSelfPlayError("seed commitment drift")
    schedule = tuple(design.mirror_assignments)
    expected_roots = {tuple(row["coordinate"]): row["root_sha256"]
                      for row in census.body["coordinates"]}
    started = time.monotonic()
    rows: list[dict[str, object] | None] = [None] * len(schedule)
    completed = 0
    active_workers = 0
    lock = threading.Lock()

    def one(index: int, item: tuple[tuple[str, int, int], int]) -> None:
        nonlocal completed
        nonlocal active_workers
        coord_tuple, mirror = item
        coord = LunaCoordinate(*coord_tuple)
        with lock:
            active_workers += 1
        try:
            # Keep the schedule's tuple coordinate as the callback contract;
            # the dataclass above is only for validation and root helpers.
            result = game_runner(coord_tuple, mirror)
            if not isinstance(result, CompletedGameArtifacts):
                raise PrivilegedTeacherLunaSelfPlayError(
                    "game runner did not return completed artifacts")
            if (result.trajectory.body["coordinate"] != list(coord_tuple)
                    or result.trajectory.body["mirror"] != mirror
                    or result.trajectory.body["root_sha256"] != expected_roots[coord_tuple]
                    or result.terminal_receipt.coordinate != coord_tuple
                    or result.terminal_receipt.mirror != mirror
                    or result.terminal_receipt.root_sha256 != expected_roots[coord_tuple]):
                raise PrivilegedTeacherLunaSelfPlayError(
                    "completed artifact root binding drift")
            row = {"coordinate": coord.payload(), "mirror": mirror,
                   "cluster_key": coord.payload(), "status": "complete",
                   "trajectory_sha256": result.trajectory.sha256,
                   "terminal_receipt_sha256": result.terminal_receipt.receipt_sha256,
                   "incomplete_artifact_sha256": None,
                   "error": None}
        except Exception as exc:  # retained as incomplete; no second attempt
            incomplete = PrivateTrajectory(
                coord_tuple, mirror, root_sha256=expected_roots[coord_tuple]).seal()
            row = {"coordinate": coord.payload(), "mirror": mirror,
                   "cluster_key": coord.payload(), "status": "incomplete",
                   "trajectory_sha256": None, "terminal_receipt_sha256": None,
                   "incomplete_artifact_sha256": incomplete.sha256,
                   "error": type(exc).__name__}
        with lock:
            active_workers -= 1
            rows[index] = row
            completed += 1
            processed = completed
            successful = sum(r is not None and r["status"] == "complete"
                              for r in rows)
            # A cluster is successful only when both immutable mirror rows are.
            complete_clusters = _complete_cluster_count(
                [r for r in rows if r is not None], design)
            elapsed = time.monotonic() - started
            eta = (None if processed == 0 else
                   max(0.0, elapsed * (len(schedule) - processed) / processed))
            if progress_sink:
                progress_sink(progress(
                    completed_games=processed, successful_games=successful,
                    total_games=len(schedule),
                    completed_deal_clusters=complete_clusters,
                    total_deal_clusters=len(design.deal_clusters),
                    elapsed_seconds=elapsed, eta_seconds=eta,
                    failure_count=processed - successful,
                    active_game_workers=active_workers,
                    active_model_processes=measured_model_processes(),
                    recent_games_per_second=(processed / elapsed
                                             if elapsed > 0 else 0.0)))
    # executor.map would preserve ordering but cannot report completion
    # progress; futures retain one immutable schedule index instead.
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(one, index, item)
                   for index, item in enumerate(schedule)]
        for future in futures:
            future.result()
    final_rows = [row for row in rows if row is not None]
    successful = sum(row["status"] == "complete" for row in final_rows)
    body = {"schema": SCHEMA, "design": design.payload(), "rows": final_rows,
            "completed_games": len(final_rows),
            "processed_games": len(final_rows), "successful_games": successful,
            "total_games": len(schedule), "failure_count": len(final_rows) - successful,
            "completed_deal_clusters": _complete_cluster_count(final_rows, design),
            "total_deal_clusters": len(design.deal_clusters),
            "terminal_route": (COMPLETE_ROUTE if successful == len(schedule)
                               else INCOMPLETE_ROUTE),
            "authority": dict(AUTHORITY)}
    return {**body, "report_sha256": _sha(body)}


def validate_population_report(report: Mapping[str, object],
                               design: LunaDesign) -> None:
    """Reconstruct final counts/routes without opening private trajectories."""
    expected = {"schema", "design", "rows", "completed_games", "processed_games", "successful_games",
                "total_games", "failure_count", "completed_deal_clusters",
                "total_deal_clusters", "terminal_route", "authority",
                "report_sha256"}
    if type(report) is not dict or set(report) != expected:
        raise PrivilegedTeacherLunaSelfPlayError("population report schema drift")
    body = {key: value for key, value in report.items()
            if key != "report_sha256"}
    rows = report["rows"]
    if type(rows) is not list or len(rows) != len(design.mirror_assignments):
        raise PrivilegedTeacherLunaSelfPlayError("population report rows drift")
    schedule = list(design.mirror_assignments)
    for index, row in enumerate(rows):
        if type(row) is not dict or set(row) != {"coordinate", "mirror",
                "cluster_key", "status", "trajectory_sha256",
                "terminal_receipt_sha256", "incomplete_artifact_sha256",
                "error"}:
            raise PrivilegedTeacherLunaSelfPlayError("population row schema drift")
        coordinate, mirror = schedule[index]
        if (row["coordinate"] != list(coordinate)
                or row["cluster_key"] != list(coordinate)
                or row["mirror"] != mirror
                or row["status"] not in ("complete", "incomplete")):
            raise PrivilegedTeacherLunaSelfPlayError("population row identity drift")
        if row["status"] == "complete":
            _strict_sha(row["trajectory_sha256"], "population trajectory SHA")
            _strict_sha(row["terminal_receipt_sha256"],
                        "population terminal receipt SHA")
            if row["error"] is not None:
                raise PrivilegedTeacherLunaSelfPlayError("population row error drift")
            if row["incomplete_artifact_sha256"] is not None:
                raise PrivilegedTeacherLunaSelfPlayError(
                    "population complete artifact drift")
        elif (row["trajectory_sha256"] is not None
              or row["terminal_receipt_sha256"] is not None
              or not isinstance(row["incomplete_artifact_sha256"], str)
              or type(row["error"]) is not str):
            raise PrivilegedTeacherLunaSelfPlayError("population incomplete row drift")
        if row["status"] == "incomplete":
            _strict_sha(row["incomplete_artifact_sha256"],
                        "population incomplete artifact SHA")
    successful = sum(row["status"] == "complete" for row in rows)
    clusters = _complete_cluster_count(rows, design)
    if (report["schema"] != SCHEMA or report["design"] != design.payload()
            or report["processed_games"] != len(rows)
            or report["completed_games"] != len(rows)
            or report["successful_games"] != successful
            or report["total_games"] != len(schedule)
            or report["failure_count"] != len(rows) - successful
            or report["completed_deal_clusters"] != clusters
            or report["total_deal_clusters"] != len(design.deal_clusters)
            or report["terminal_route"] != (COMPLETE_ROUTE if successful == len(rows)
                                             else INCOMPLETE_ROUTE)
            or report["authority"] != AUTHORITY
            or report["report_sha256"] != _sha(body)):
        raise PrivilegedTeacherLunaSelfPlayError("population report accounting drift")


def run_game(game: LunaSelfPlayGame,
             planners: Mapping[int, Callable[[LunaTeamSession,
                                               Mapping[str, object]], Mapping[str, object]]] | None = None
             ) -> CompletedGameArtifacts | None:
    """Drive a game with bounded callbacks, without starting model processes.

    A production runner supplies one callback per independent model process.
    Tests may omit callbacks, in which case candidate zero is used as the
    mechanical proposal.  Any callback or engine failure aborts the shared
    game and wakes both waiting sessions; no retry is attempted here.
    """
    if type(game) is not LunaSelfPlayGame:
        raise PrivilegedTeacherLunaSelfPlayError("game identity drift")
    callbacks = planners or {}
    if type(callbacks) is not dict or set(callbacks) - set(TEAMS):
        raise PrivilegedTeacherLunaSelfPlayError("planner identity drift")
    def worker(team: int) -> None:
        try:
            session = game.session(team)
            while not game.complete and game.failed is None:
                if not session.wait(timeout=None):
                    return
                observation = session.observe()
                if observation.get("status") != "decision":
                    if game.complete or game.failed is not None:
                        return
                    raise PrivilegedTeacherLunaSelfPlayError(
                        "planner turn stalled")
                callback = callbacks.get(team)
                request = ({"op": "play", "decision_sha256":
                            observation["decision_sha256"],
                            "candidate_index": 0, "confidence": "low"}
                           if callback is None
                           else callback(session, observation))
                session.play(request)
        except Exception as exc:
            game.fail(type(exc).__name__ + ": " + str(exc))

    threads = [threading.Thread(target=worker, args=(team,), daemon=True)
               for team in TEAMS]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return game.completed_artifacts() if game.complete else None

__all__ = ["AUTHORITY", "BANKER_SEATS", "CANDIDATE_GAME_WORKERS", "GAME_SCHEMA",
           "TRUMP_MODES", "PrivilegedTeacherLunaSelfPlayError",
           "LunaPlannerRequestError",
           "TerminalReceipt", "CompletedGameArtifacts", "RootCensus",
           "TERMINAL_RECEIPT_SCHEMA",
           "ROOT_CENSUS_SCHEMA",
           "LunaCoordinate", "LunaDesign",
           "LunaSelfPlayGame", "LunaTeamSession", "MODEL", "MIRRORS",
           "PrivateTrajectory", "PROGRESS_SCHEMA", "SCHEMA", "SealedTrajectory",
           "build_root", "candidate_worker_arms", "fresh_coordinates",
           "mirrored_assignments", "progress", "root_identity",
           "root_seed", "run_population", "validate_capacity",
           "validate_game_workers", "agent_team_assignment", "agent_for_team",
           "validate_progress", "validate_design",
           "run_game", "validate_root_population",
           "validate_population_report", "validate_terminal_receipt",
           "validate_root_census", "root_census", "root_trump_mode", "COMPLETE_ROUTE",
           "INCOMPLETE_ROUTE"]
