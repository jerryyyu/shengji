"""Score-free progressive capacity census for the PT-Luna turn-RPC route."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time
from typing import Callable, Mapping, Sequence

from . import privileged_teacher_luna_selfplay as selfplay
from .privileged_teacher_luna_rpc_journal import TurnJournalError
from .privileged_teacher_luna_rpc_transport import (
    CodexProviderResourceError,
    CodexToolEventError,
    CodexTurnTransportError,
    DISABLED_FEATURES,
    MODEL,
    REASONING_EFFORT,
    attest_codex_runtime,
)
from .privileged_teacher_luna_turn_rpc import (
    TurnRPCError,
    TurnValidationError,
)
from .privileged_teacher_pt0 import canonical_json_bytes


SCHEMA = "pt-luna-turn-rpc-capacity-v4"
CANARY_SCHEMA = "pt-luna-turn-rpc-real-canaries-v1"
SOURCE_REVIEW_SCHEMA = "pt-luna-turn-rpc-source-review-v2"
ARM_SCHEMA = "pt-luna-turn-rpc-capacity-arm-v4"
METRIC_SCHEMA = "pt-luna-turn-rpc-capacity-game-v4"
ROUTE_FULL = "FULL_104_ELIGIBLE"
ROUTE_PILOT = "PILOT_32_ELIGIBLE"
ROUTE_REFUSE = "REFUSE_RESOURCE_OR_PROVIDER"
# Descriptive aliases retain the route labels in code that imports constants
# directly, while the receipt vocabulary remains exactly the three strings.
ROUTE_FULL_104_ELIGIBLE = ROUTE_FULL
ROUTE_PILOT_32_ELIGIBLE = ROUTE_PILOT
PER_GAME_DEADLINE_NS = 1_200 * 1_000_000_000
FULL_GAME_COUNT = 104
PILOT_GAME_COUNT = 32
FULL_DEAL_CLUSTER_COUNT = 52
PILOT_DEAL_CLUSTER_COUNT = 16
FULL_POPULATION_WALL_NS = 28_800 * 1_000_000_000
PILOT_POPULATION_WALL_NS = 12_000 * 1_000_000_000
FULL_P95_LIMIT_NS = 886_153_846_153
PILOT_P95_LIMIT_NS = 1_200_000_000_000
WORKER_ARMS = (1, 4)
FAILURE_STAGES = (
    "none", "dispatch", "provider-response", "validation", "engine-apply",
    "journal-commit", "terminal-verification", "resource-meter",
)
FAILURE_KINDS = (
    "none", "game-deadline", "call-timeout", "provider-process",
    "provider-schema", "forbidden-tool", "transport-validation",
    "engine-validation", "journal-io", "resource-meter", "unknown",
)
NO_FAILURE_MESSAGE_SHA256 = hashlib.sha256(b"").hexdigest()
REQUIRED_ENGINE_ENVIRONMENT = {
    "SHENGJI_FAST": None,
    "SHENGJI_REQUIRE_VOIDS": "1",
}
LOADABLE_SHADOW_SUFFIXES = (".pyc", ".pyo", ".so", ".dylib", ".pyd")
SOURCE_PATHS = (
    "shengji/rl/privileged_teacher_luna_selfplay.py",
    "shengji/rl/privileged_teacher_luna_turn_rpc.py",
    "shengji/rl/privileged_teacher_luna_rpc_transport.py",
    "shengji/rl/privileged_teacher_luna_rpc_watchdog.py",
    "shengji/rl/privileged_teacher_luna_rpc_io.py",
    "shengji/rl/privileged_teacher_luna_rpc_journal.py",
    "shengji/rl/privileged_teacher_luna_rpc_capacity.py",
    "shengji/rl/privileged_teacher_luna_rpc_collection.py",
    "shengji/rl/privileged_teacher_luna_rpc_supervisor.py",
    "scripts/privileged_teacher_luna_rpc_canary.py",
    "scripts/privileged_teacher_luna_rpc_collection.py",
    "tests/test_privileged_teacher_luna_turn_rpc.py",
    "tests/test_privileged_teacher_luna_rpc_transport.py",
    "tests/test_privileged_teacher_luna_rpc_io.py",
    "tests/test_privileged_teacher_luna_rpc_journal.py",
    "tests/test_privileged_teacher_luna_rpc_capacity.py",
    "tests/test_privileged_teacher_luna_rpc_collection.py",
    "tests/test_privileged_teacher_luna_rpc_supervisor.py",
)


class RPCCapacityError(ValueError):
    """Capacity inputs, telemetry, or receipt derivation drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _nonnegative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RPCCapacityError(f"{label} drift")
    return value


def _positive(value: object, label: str) -> int:
    result = _nonnegative(value, label)
    if result <= 0:
        raise RPCCapacityError(f"{label} must be positive")
    return result


def _strict_sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise RPCCapacityError(f"{label} drift")
    return value


def _p95(values: Sequence[int]) -> int:
    if not values:
        raise RPCCapacityError("capacity p95 absent")
    ordered = sorted(values)
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def _ceil_ratio(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise RPCCapacityError("capacity ratio drift")
    return (numerator + denominator - 1) // denominator


def _population_projection(p95: int, game_count: int, workers: int,
                           token_count: int, sampled_games: int) \
        -> tuple[int, int]:
    """Return integer nanosecond and token projections with 25% headroom."""
    batches = math.ceil(game_count / workers)
    wall = _ceil_ratio(p95 * batches * 125, 100)
    tokens = _ceil_ratio(token_count * game_count * 125,
                         sampled_games * 100)
    return wall, tokens


def _failure_disposition(exc: BaseException, *, stage: str) \
        -> tuple[str, str, bool, bool, str, str]:
    """Reduce a private exception to the closed public failure vocabulary."""
    exception_type = type(exc).__name__
    message = str(exc) or type(exc).__name__
    lowered = message.lower()
    game_deadline = "game deadline" in lowered
    call_timeout = ("turn deadline" in lowered or "call timeout" in lowered)
    if game_deadline:
        kind = "game-deadline"
        if "after" in lowered:
            stage = "provider-response"
    elif call_timeout:
        kind = "call-timeout"
        stage = "provider-response"
    elif isinstance(exc, CodexToolEventError):
        kind = "forbidden-tool"
        stage = "validation"
    elif isinstance(exc, CodexProviderResourceError):
        kind = "provider-process"
        stage = "provider-response"
    elif isinstance(exc, TurnJournalError):
        kind = "journal-io"
        stage = "journal-commit"
    elif isinstance(exc, TurnValidationError):
        kind = "engine-validation" if "engine" in lowered else \
            "transport-validation"
        stage = "engine-apply" if "engine" in lowered else "validation"
    elif isinstance(exc, CodexTurnTransportError):
        kind = "provider-schema"
        stage = "provider-response"
    elif isinstance(exc, TurnRPCError):
        kind = "transport-validation"
        stage = "validation"
    else:
        kind = "unknown"
    return (stage, kind, game_deadline, call_timeout, exception_type,
            hashlib.sha256(message.encode("utf-8", errors="replace")).hexdigest())


@dataclass(frozen=True)
class GameMetric:
    workers: int
    worker: int
    game: int
    complete: bool
    verified: bool
    wall_nanoseconds: int
    busy_cpu_nanoseconds: int
    peak_rss_bytes: int
    swap_bytes: int
    process_errors: int
    tool_event_count: int
    rpc_count: int
    process_count: int
    p95_rpc_wall_nanoseconds: int
    max_rpc_wall_nanoseconds: int
    max_rpc_token_count: int
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    token_rate_milli: int
    mechanics_sha256: str
    evidence_sha256: str
    failure_stage: str = "none"
    failure_kind: str = "none"
    game_deadline_fired: bool = False
    call_timeout_fired: bool = False
    exception_type: str = "none"
    failure_message_sha256: str = NO_FAILURE_MESSAGE_SHA256
    last_opened_rpc_count: int = 0
    last_committed_decision_count: int = 0
    # Retry accounting is journal-derived.  ``None`` is retained only as a
    # compatibility default for old injected witnesses; explicit zeroes are
    # never repaired and therefore fail the wiring checks below.
    physical_attempt_count: int | None = None
    first_attempt_failure_by_class: dict[str, int] | None = None
    redispatch_count: int = 0
    exhaustion_count: int = 0
    retry_wall_nanoseconds: int = 0
    retry_token_count: int = 0

    def __post_init__(self) -> None:
        if self.physical_attempt_count is None:
            object.__setattr__(self, "physical_attempt_count", self.rpc_count)
        if self.first_attempt_failure_by_class is None:
            object.__setattr__(self, "first_attempt_failure_by_class", {})
        if self.workers not in WORKER_ARMS:
            raise RPCCapacityError("capacity metric worker-arm drift")
        for field, label in ((self.worker, "worker"), (self.game, "game"),
                             (self.wall_nanoseconds, "wall"),
                             (self.busy_cpu_nanoseconds, "CPU"),
                             (self.peak_rss_bytes, "RSS"),
                             (self.swap_bytes, "swap"),
                             (self.process_errors, "process error"),
                             (self.tool_event_count, "tool event"),
                             (self.rpc_count, "RPC"),
                             (self.process_count, "process"),
                             (self.p95_rpc_wall_nanoseconds, "RPC p95 wall"),
                             (self.max_rpc_wall_nanoseconds, "RPC max wall"),
                             (self.max_rpc_token_count, "RPC max token"),
                             (self.input_tokens, "input token"),
                             (self.cached_input_tokens, "cached token"),
                             (self.cache_write_input_tokens, "cache-write token"),
                             (self.output_tokens, "output token"),
                             (self.reasoning_output_tokens, "reasoning token"),
                             (self.token_rate_milli, "token rate"),
                             (self.last_opened_rpc_count, "opened RPC"),
                             (self.last_committed_decision_count,
                              "committed decision"),
                             (self.physical_attempt_count,
                              "physical attempt"),
                             (self.redispatch_count, "redispatch"),
                             (self.exhaustion_count, "exhaustion"),
                             (self.retry_wall_nanoseconds, "retry wall"),
                             (self.retry_token_count, "retry token")):
            _nonnegative(field, f"capacity {label}")
        if self.worker >= self.workers or self.game not in (0, 1):
            raise RPCCapacityError("capacity metric coordinate drift")
        if type(self.complete) is not bool or type(self.verified) is not bool:
            raise RPCCapacityError("capacity completion drift")
        _positive(self.wall_nanoseconds, "capacity game wall")
        _strict_sha(self.mechanics_sha256, "capacity mechanics SHA")
        _strict_sha(self.evidence_sha256, "capacity evidence SHA")
        _strict_sha(self.failure_message_sha256,
                    "capacity failure message SHA")
        if self.failure_stage not in FAILURE_STAGES \
                or self.failure_kind not in FAILURE_KINDS \
                or type(self.game_deadline_fired) is not bool \
                or type(self.call_timeout_fired) is not bool \
                or type(self.exception_type) is not str \
                or not self.exception_type:
            raise RPCCapacityError("capacity failure disposition drift")
        if self.complete:
            if (self.failure_stage, self.failure_kind, self.exception_type,
                    self.failure_message_sha256,
                    self.game_deadline_fired, self.call_timeout_fired) != (
                        "none", "none", "none", NO_FAILURE_MESSAGE_SHA256,
                        False, False):
                raise RPCCapacityError("complete game has failure disposition")
        elif self.failure_stage == "none" or self.failure_kind == "none" \
                or self.exception_type == "none" \
                or self.failure_message_sha256 == NO_FAILURE_MESSAGE_SHA256:
            raise RPCCapacityError("incomplete game lacks failure disposition")
        if self.last_opened_rpc_count > self.rpc_count \
                or self.last_committed_decision_count > self.rpc_count:
            raise RPCCapacityError("capacity failure progress drift")
        if self.cached_input_tokens > self.input_tokens \
                or self.reasoning_output_tokens > self.output_tokens:
            raise RPCCapacityError("capacity token subset drift")
        if (self.process_errors == 0 and self.process_count < self.rpc_count) \
                or self.p95_rpc_wall_nanoseconds > self.max_rpc_wall_nanoseconds:
            raise RPCCapacityError("capacity RPC process telemetry drift")
        if type(self.first_attempt_failure_by_class) is not dict \
                or any(type(key) is not str or not key or
                       isinstance(value, bool) or not isinstance(value, int)
                       or value < 0
                       for key, value in self.first_attempt_failure_by_class.items()) \
                or self.redispatch_count > self.physical_attempt_count \
                or self.exhaustion_count > self.physical_attempt_count \
                or self.retry_token_count > self.token_count:
            raise RPCCapacityError("capacity retry accounting drift")

    @property
    def token_count(self) -> int:
        return self.input_tokens + self.output_tokens

    def payload(self) -> dict[str, object]:
        return {"schema": METRIC_SCHEMA, **{
            name: getattr(self, name) for name in self.__dataclass_fields__}}

    @classmethod
    def from_mapping(cls, value: object) -> "GameMetric":
        fields = set(cls.__dataclass_fields__)
        if type(value) is not dict or set(value) != {"schema", *fields} \
                or value.get("schema") != METRIC_SCHEMA:
            raise RPCCapacityError("capacity metric schema drift")
        return cls(**{name: value[name] for name in fields})


class RPCConcurrency:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.maximum = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def leave(self) -> None:
        with self._lock:
            if self.active <= 0:
                raise RPCCapacityError("capacity RPC concurrency underflow")
            self.active -= 1

    def reset_maximum(self) -> None:
        with self._lock:
            if self.active != 0:
                raise RPCCapacityError("capacity RPC reset while active")
            self.maximum = 0


def _source_hashes() -> dict[str, str]:
    server_root = Path(__file__).resolve().parents[2]
    return {name: _sha_bytes((server_root / name).read_bytes())
            for name in SOURCE_PATHS}


def _boot_identity_bytes() -> bytes:
    source = Path("/proc/sys/kernel/random/boot_id")
    try:
        if source.is_file():
            value = source.read_bytes().strip()
        elif sys.platform == "darwin":
            value = subprocess.check_output(
                ["sysctl", "-n", "kern.bootsessionuuid"],
                stderr=subprocess.DEVNULL).strip()
        else:
            raise RPCCapacityError("capacity boot identity unavailable")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RPCCapacityError("capacity boot identity unavailable") from exc
    if not value:
        raise RPCCapacityError("capacity boot identity unavailable")
    return value


def source_identity(codex_binary: Path) -> dict[str, object]:
    binary = Path(codex_binary).resolve()
    repo = Path(__file__).resolve().parents[3]
    try:
        status = subprocess.check_output(
            ("git", "-C", str(repo), "status", "--porcelain=v1",
             "--untracked-files=all"), stderr=subprocess.PIPE,
            text=True)
        execution_git = subprocess.check_output(
            ("git", "-C", str(repo), "rev-parse", "HEAD"),
            stderr=subprocess.PIPE, text=True).strip()
        git_tree = subprocess.check_output(
            ("git", "-C", str(repo), "rev-parse", "HEAD^{tree}"),
            stderr=subprocess.PIPE, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RPCCapacityError("capacity Git identity unavailable") from exc
    if status or len(execution_git) != 40 or len(git_tree) != 40:
        raise RPCCapacityError("capacity execution tree is not exact-clean")
    if ({name: os.environ.get(name)
         for name in REQUIRED_ENGINE_ENVIRONMENT}
            != REQUIRED_ENGINE_ENVIRONMENT
            or not sys.dont_write_bytecode):
        raise RPCCapacityError(
            "capacity requires pure engine, strict voids, and -B")
    fast_module = sys.modules.get("shengji.engine.fast")
    if fast_module is not None and bool(getattr(fast_module, "_saved", {})):
        raise RPCCapacityError("capacity compiled engine is active")
    package_root = repo / "server" / "shengji"
    shadows = sorted(
        path.relative_to(repo).as_posix()
        for path in package_root.rglob("*")
        if (path.is_file() or path.is_symlink())
        and path.suffix.lower() in LOADABLE_SHADOW_SUFFIXES)
    if shadows:
        raise RPCCapacityError("capacity loadable source shadow is present")
    try:
        codex = attest_codex_runtime(binary)
    except CodexTurnTransportError as exc:
        raise RPCCapacityError("capacity Codex runtime refused") from exc
    sources = _source_hashes()
    return {"schema": "pt-luna-turn-rpc-runtime-v1",
            "python_executable": str(Path(sys.executable).resolve()),
            "python_sha256": _sha_bytes(Path(sys.executable).read_bytes()),
            "python_version": sys.version,
            "platform": platform.platform(),
            "engine_mode": "pure-python", "strict_voids": True,
            "python_dont_write_bytecode": True,
            "required_environment": dict(REQUIRED_ENGINE_ENVIRONMENT),
            "native_extension": None,
            "execution_git": execution_git, "git_tree": git_tree,
            "boot_identity_sha256": _sha_bytes(_boot_identity_bytes()),
            "codex_binary": str(binary),
            "codex_binary_sha256": codex["binary_sha256"],
            "codex_version": codex["version"],
            "codex_tool_catalog": codex,
            "model": MODEL, "reasoning_effort": REASONING_EFFORT,
            "sources": sources, "source_set_sha256": _sha(sources)}


def validate_source_review_auth(
        value: object, *, expected_source_set_sha256: str | None = None,
) -> str:
    """Validate the exact authenticated source-review bundle in receipts."""
    if type(value) is not dict or set(value) != {
            "review_commit", "review_marker_sha256", "review_claim"}:
        raise RPCCapacityError("source review authentication drift")
    commit = value["review_commit"]
    if type(commit) is not str or len(commit) != 40 \
            or any(char not in "0123456789abcdef" for char in commit):
        raise RPCCapacityError("source review commit drift")
    _strict_sha(value["review_marker_sha256"], "source review marker")
    claim = value["review_claim"]
    keys = {"schema", "execution_git", "source_set_sha256",
            "design_sha256s", "design_sha256", "score_free_canary_authorized",
            "score_free_capacity_authorized",
            "scientific_execution_authorized", "outcome_opening_authorized",
            "merge_authorized", "deployment_authorized",
            "strength_claim_authorized", "authority", "claim_sha256"}
    if type(claim) is not dict or set(claim) != keys \
            or claim.get("schema") != SOURCE_REVIEW_SCHEMA \
            or claim.get("authority") != selfplay.AUTHORITY \
            or claim.get("score_free_canary_authorized") is not True \
            or claim.get("score_free_capacity_authorized") is not True \
            or any(claim.get(key) is not False for key in (
                "scientific_execution_authorized", "outcome_opening_authorized",
                "merge_authorized", "deployment_authorized",
                "strength_claim_authorized")):
        raise RPCCapacityError("source review claim drift")
    execution = claim["execution_git"]
    if type(execution) is not str or len(execution) != 40 \
            or any(char not in "0123456789abcdef" for char in execution):
        raise RPCCapacityError("source review execution Git drift")
    design_hashes = claim["design_sha256s"]
    if type(design_hashes) is not dict or set(design_hashes) != {
            "PRIVILEGED_TEACHER_LUNA_SELFPLAY_DESIGN.md",
            "PRIVILEGED_TEACHER_LUNA_PLAY_ONLY_DESIGN.md"}:
        raise RPCCapacityError("source review design hash population drift")
    for key in ("source_set_sha256", "design_sha256", "claim_sha256"):
        _strict_sha(claim[key], f"source review {key}")
    for digest in design_hashes.values():
        _strict_sha(digest, "source review design SHA")
    body = {key: item for key, item in claim.items()
            if key != "claim_sha256"}
    if claim["design_sha256"] != _sha(design_hashes) \
            or claim["claim_sha256"] != _sha(body) \
            or (expected_source_set_sha256 is not None
                and claim["source_set_sha256"]
                != expected_source_set_sha256):
        raise RPCCapacityError("source review claim seal drift")
    return value["review_marker_sha256"]


def mechanics_sha256() -> str:
    return _sha(_source_hashes())


def validate_canary_receipt(receipt: object, *,
                            expected_runtime: Mapping[str, object] | None = None) -> str:
    keys = {"schema", "scientific", "seed_commitment_sha256", "rows",
            "runtime", "source_review", "authority", "receipt_sha256"}
    if type(receipt) is not dict or set(receipt) != keys \
            or receipt.get("schema") != CANARY_SCHEMA \
            or receipt.get("scientific") is not False \
            or receipt.get("authority") != selfplay.AUTHORITY:
        raise RPCCapacityError("canary receipt schema drift")
    body = {key: value for key, value in receipt.items()
            if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != _sha(body):
        raise RPCCapacityError("canary receipt seal drift")
    _strict_sha(receipt["seed_commitment_sha256"], "canary seed commitment")
    _strict_sha(receipt["receipt_sha256"], "canary receipt SHA")
    if type(receipt["runtime"]) is not dict \
            or receipt["runtime"].get("schema") != "pt-luna-turn-rpc-runtime-v1" \
            or (expected_runtime is not None
                and receipt["runtime"] != dict(expected_runtime)):
        raise RPCCapacityError("canary runtime binding drift")
    validate_source_review_auth(
        receipt["source_review"],
        expected_source_set_sha256=receipt["runtime"].get(
            "source_set_sha256"))
    if receipt["source_review"]["review_claim"]["execution_git"] \
            != receipt["runtime"].get("execution_git"):
        raise RPCCapacityError("canary execution Git drift")
    row_keys = {"schema", "name", "completed_contested_decisions",
                "planner_rpc_count", "rollout_rpc_count", "play_rpc_count",
                "play_teams", "provider_request_sha256s",
                "provider_response_sha256s", "tool_event_count",
                "input_tokens", "cached_input_tokens",
                "cache_write_input_tokens", "output_tokens",
                "reasoning_output_tokens", "total_tokens",
                "rpc_wall_milliseconds",
                "wall_nanoseconds", "engine_complete", "engine_failed",
                "state_changed", "journal_summary_sha256"}
    rows = receipt["rows"]
    if type(rows) is not list or len(rows) != 2 \
            or [row.get("name") if type(row) is dict else None
                for row in rows] != ["nonterminal", "alternation"]:
        raise RPCCapacityError("canary row population drift")
    for row in rows:
        if set(row) != row_keys \
                or row.get("schema") != "pt-luna-turn-rpc-real-canary-row-v1":
            raise RPCCapacityError("canary row schema drift")
        for field in ("completed_contested_decisions", "planner_rpc_count",
                      "rollout_rpc_count", "play_rpc_count", "tool_event_count",
                      "input_tokens", "cached_input_tokens", "output_tokens"):
            _nonnegative(row[field], f"canary {field}")
        for field in ("cache_write_input_tokens", "reasoning_output_tokens",
                      "total_tokens", "rpc_wall_milliseconds"):
            _nonnegative(row[field], f"canary {field}")
        _positive(row["wall_nanoseconds"], "canary wall")
        if row["cached_input_tokens"] > row["input_tokens"] \
                or row["tool_event_count"] != 0 \
                or row["engine_failed"] is not False \
                or row["state_changed"] is not True \
                or type(row["engine_complete"]) is not bool \
                or type(row["play_teams"]) is not list \
                or row["planner_rpc_count"] != (row["rollout_rpc_count"]
                                                  + row["play_rpc_count"]) \
                or row["total_tokens"] \
                != row["input_tokens"] + row["output_tokens"] \
                or row["reasoning_output_tokens"] > row["output_tokens"]:
            raise RPCCapacityError("canary row invariant drift")
        requests = row["provider_request_sha256s"]
        responses = row["provider_response_sha256s"]
        if type(requests) is not list or type(responses) is not list \
                or len(requests) != row["planner_rpc_count"] \
                or len(responses) != row["planner_rpc_count"]:
            raise RPCCapacityError("canary provider population drift")
        for value in [*requests, *responses, row["journal_summary_sha256"]]:
            _strict_sha(value, "canary evidence SHA")
    nonterminal, alternation = rows
    if (nonterminal["completed_contested_decisions"] != 1
            or nonterminal["planner_rpc_count"] != 2
            or nonterminal["rollout_rpc_count"] != 1
            or nonterminal["play_rpc_count"] != 1
            or nonterminal["play_teams"] != [0]
            or nonterminal["engine_complete"] is not False
            or alternation["completed_contested_decisions"] != 4
            or alternation["play_rpc_count"] != 4
            or sorted(set(alternation["play_teams"])) != [0, 1]
            or alternation["engine_complete"] is not False):
        raise RPCCapacityError("canary contract derivation drift")
    return receipt["receipt_sha256"]


def _arm(workers: int, metrics: Sequence[GameMetric], *,
         arm_wall: int, previous: Mapping[str, object] | None,
         per_game_deadline_ns: int, physical_memory_bytes: int,
         scientific_wall_ns: int, scientific_token_budget: int,
         max_active_rpcs: int) -> dict[str, object]:
    if len(metrics) != workers * 2:
        raise RPCCapacityError("capacity arm game population drift")
    expected = {(worker, game) for worker in range(workers) for game in (0, 1)}
    if {(row.worker, row.game) for row in metrics} != expected \
            or any(row.workers != workers for row in metrics):
        raise RPCCapacityError("capacity arm coordinate population drift")
    if any(row.physical_attempt_count != row.rpc_count
           or row.physical_attempt_count < 0
           or row.redispatch_count > row.physical_attempt_count
           for row in metrics):
        raise RPCCapacityError("capacity retry wiring drift")
    if all(row.complete and row.verified for row in metrics) \
            and any(row.physical_attempt_count <= 0 for row in metrics):
        raise RPCCapacityError("capacity retry aggregation absent")
    walls = [row.wall_nanoseconds for row in metrics]
    p95 = _p95(walls)
    complete = all(row.complete and row.verified for row in metrics)
    process_passed = all(row.process_errors == 0 and row.tool_event_count == 0
                         for row in metrics)
    mechanics = {row.mechanics_sha256 for row in metrics}
    mechanics_passed = len(mechanics) == 1
    rss = sum(sorted((row.peak_rss_bytes for row in metrics), reverse=True)[:workers])
    rss_passed = rss * 100 <= physical_memory_bytes * 85
    swap_passed = all(row.swap_bytes == 0 for row in metrics)
    # The provider/game execution deadline is an execution safety bound.  The
    # route-specific population projections below apply their own headroom.
    deadline_passed = p95 <= per_game_deadline_ns
    observed_parallelism_milli = sum(walls) * 1000 // max(1, arm_wall)
    parallelism_passed = (complete and max_active_rpcs * 100 >= workers * 70
                          and observed_parallelism_milli >= workers * 700)
    scaling_efficiency_milli = None
    scaling_passed = True
    if previous is not None:
        previous_throughput_num = previous["completed_games"]
        previous_throughput_den = previous["arm_wall_nanoseconds"]
        scaling_efficiency_milli = (
            len(metrics) * previous_throughput_den * previous["workers"] * 1000
            // (arm_wall * previous_throughput_num * workers))
        scaling_passed = scaling_efficiency_milli >= 700
    tokens = sum(row.token_count for row in metrics)
    physical_attempts = sum(row.physical_attempt_count for row in metrics)
    redispatches = sum(row.redispatch_count for row in metrics)
    exhaustions = sum(row.exhaustion_count for row in metrics)
    retry_wall = sum(row.retry_wall_nanoseconds for row in metrics)
    retry_tokens = sum(row.retry_token_count for row in metrics)
    first_failures: dict[str, int] = {}
    for row in metrics:
        for key, value in row.first_attempt_failure_by_class.items():
            first_failures[key] = first_failures.get(key, 0) + value
    max_game_token_count = max(row.token_count for row in metrics)
    per_game_token_cap = math.ceil(max_game_token_count * 125 / 100)
    max_rpc_token_count = max(row.max_rpc_token_count for row in metrics)
    per_call_token_reserve = math.ceil(max_rpc_token_count * 125 / 100)
    max_rpc_wall_nanoseconds = max(
        row.max_rpc_wall_nanoseconds for row in metrics)
    per_call_wall_reserve_milliseconds = max(
        1, math.ceil(max_rpc_wall_nanoseconds * 125
                     / (100 * 1_000_000)))
    projected_wall, projected_tokens = _population_projection(
        p95, FULL_GAME_COUNT, workers, tokens, len(metrics))
    projection_passed = (projected_tokens <= scientific_token_budget
                         and projected_wall <= scientific_wall_ns)
    # Population projections are route gates, not arm health.  In particular,
    # a full-lane miss must still permit the pilot lane to be considered.
    projection_required = False
    passed = (complete and process_passed and mechanics_passed and rss_passed
              and swap_passed and parallelism_passed and scaling_passed
              and exhaustions == 0)
    return {"schema": ARM_SCHEMA, "workers": workers,
            "metrics": [row.payload() for row in sorted(
                metrics, key=lambda row: (row.worker, row.game))],
            "completed_games": sum(row.complete for row in metrics),
            "verified_games": sum(row.verified for row in metrics),
            "arm_wall_nanoseconds": arm_wall,
            "p95_game_wall_nanoseconds": p95,
            "aggregate_peak_rss_bytes": rss,
            "aggregate_token_count": tokens,
            "physical_attempt_count": physical_attempts,
            "first_attempt_failure_by_class": first_failures,
            "redispatch_count": redispatches,
            "exhaustion_count": exhaustions,
            "retry_wall_nanoseconds": retry_wall,
            "retry_token_count": retry_tokens,
            "max_game_token_count": max_game_token_count,
            "per_game_token_cap": per_game_token_cap,
            "max_rpc_token_count": max_rpc_token_count,
            "per_call_token_reserve": per_call_token_reserve,
            "per_call_wall_reserve_milliseconds":
                per_call_wall_reserve_milliseconds,
            "observed_parallelism_milli": observed_parallelism_milli,
            "max_active_model_rpcs": max_active_rpcs,
            "scaling_efficiency_milli": scaling_efficiency_milli,
            "projected_104_wall_nanoseconds": projected_wall,
            "projected_104_token_count": projected_tokens,
            "complete_passed": complete, "process_passed": process_passed,
            "mechanics_passed": mechanics_passed,
            "rss_passed": rss_passed, "swap_passed": swap_passed,
            "deadline_passed": deadline_passed,
            "parallelism_passed": parallelism_passed,
            "scaling_passed": scaling_passed,
            "exhaustion_passed": exhaustions == 0,
            "projection_required": projection_required,
            "projection_passed": projection_passed, "passed": passed}


def _route_decision(*, arms: Sequence[Mapping[str, object]],
                    total_tokens: int, capacity_token_budget: int,
                    stop_reason: str,
                    scientific_token_budget: int) -> dict[str, object]:
    """Derive the closed route and all receipt-bound route facts."""
    full_wall = full_tokens = pilot_wall = pilot_tokens = None
    if (len(arms) >= 2 and arms[-1].get("workers") == 4):
        arm = arms[-1]
        p95 = int(arm["p95_game_wall_nanoseconds"])
        token_count = int(arm["aggregate_token_count"])
        full_wall, full_tokens = _population_projection(
            p95, FULL_GAME_COUNT, 4, token_count, 8)
        pilot_wall, pilot_tokens = _population_projection(
            p95, PILOT_GAME_COUNT, 4, token_count, 8)
    healthy_four = (len(arms) == len(WORKER_ARMS)
                    and arms[-1].get("workers") == 4
                    and arms[-1].get("passed") is True)
    capacity_ok = (total_tokens <= capacity_token_budget
                   and stop_reason not in {
                       "capacity-token-overrun", "capacity-wall-overrun",
                       "capacity-wall-before-arm"})
    full_ok = (healthy_four and capacity_ok
               and full_wall is not None and full_tokens is not None
               and arms[-1]["p95_game_wall_nanoseconds"] <= FULL_P95_LIMIT_NS
               and full_wall <= FULL_POPULATION_WALL_NS
               and full_tokens <= scientific_token_budget)
    pilot_ok = (healthy_four and capacity_ok
                and pilot_wall is not None and pilot_tokens is not None
                and arms[-1]["p95_game_wall_nanoseconds"] <= PILOT_P95_LIMIT_NS
                and pilot_wall <= PILOT_POPULATION_WALL_NS
                and pilot_tokens <= scientific_token_budget)
    route = ROUTE_FULL if full_ok else ROUTE_PILOT if pilot_ok else ROUTE_REFUSE
    selected = 4 if route in (ROUTE_FULL, ROUTE_PILOT) else None
    return {
        "route": route,
        "selected_workers": selected,
        "selected_game_count": (FULL_GAME_COUNT if route == ROUTE_FULL
                                 else PILOT_GAME_COUNT if route == ROUTE_PILOT
                                 else None),
        "selected_deal_cluster_count": (
            FULL_DEAL_CLUSTER_COUNT if route == ROUTE_FULL
            else PILOT_DEAL_CLUSTER_COUNT if route == ROUTE_PILOT else None),
        "selected_population_wall_nanoseconds": (
            FULL_POPULATION_WALL_NS if route == ROUTE_FULL
            else PILOT_POPULATION_WALL_NS if route == ROUTE_PILOT else None),
        "projected_full_wall_nanoseconds": full_wall,
        "projected_full_token_count": full_tokens,
        "projected_pilot_wall_nanoseconds": pilot_wall,
        "projected_pilot_token_count": pilot_tokens,
    }


def _derive_capacity(*, game_runner: Callable[[int, int, int], GameMetric],
                 runtime: Mapping[str, object], secret_commitment_sha256: str,
                 canary_receipt_sha256: str,
                 source_review: Mapping[str, object],
                 per_game_deadline_ns: int, physical_memory_bytes: int,
                 capacity_wall_ns: int, capacity_token_budget: int,
                 scientific_wall_ns: int, scientific_token_budget: int,
                 progress_sink: Callable[[Mapping[str, object]], object] | None = None,
                 arm_sink: Callable[[Mapping[str, object]], object] | None = None,
                 concurrency: RPCConcurrency | None = None) -> dict[str, object]:
    for value, label in (
            (per_game_deadline_ns, "per-game deadline"),
            (physical_memory_bytes, "physical memory"),
            (capacity_wall_ns, "capacity wall"),
            (capacity_token_budget, "capacity tokens"),
            (scientific_wall_ns, "scientific wall"),
            (scientific_token_budget, "scientific tokens")):
        _positive(value, label)
    _strict_sha(secret_commitment_sha256, "capacity secret commitment")
    _strict_sha(canary_receipt_sha256, "capacity canary receipt SHA")
    if type(runtime) is not dict:
        raise RPCCapacityError("capacity runtime drift")
    validate_source_review_auth(
        source_review,
        expected_source_set_sha256=runtime.get("source_set_sha256"))
    tracker = concurrency or RPCConcurrency()
    started = time.monotonic_ns()
    arms: list[dict[str, object]] = []
    total_tokens = 0
    total_physical_attempts = 0
    total_redispatches = 0
    total_exhaustions = 0
    total_retry_wall = 0
    total_retry_tokens = 0
    total_first_failures: dict[str, int] = {}
    previous = None
    stop_reason = "all-arms-complete"
    for workers in WORKER_ARMS:
        if time.monotonic_ns() - started >= capacity_wall_ns:
            stop_reason = "capacity-wall-before-arm"
            break
        arm_started = time.monotonic_ns()
        tracker.reset_maximum()
        metrics: list[GameMetric] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(game_runner, workers, worker, game):
                       (worker, game) for worker in range(workers)
                       for game in (0, 1)}
            for future in as_completed(futures):
                metric = future.result()
                if type(metric) is not GameMetric:
                    raise RPCCapacityError("capacity runner result drift")
                metrics.append(metric)
                if progress_sink is not None:
                    progress_sink({"schema": "pt-luna-rpc-capacity-arm-progress-v1",
                                   "arm_workers": workers,
                                   "completed_games": len(metrics),
                                   "total_games": workers * 2})
        arm_wall = max(1, time.monotonic_ns() - arm_started)
        total_tokens += sum(row.token_count for row in metrics)
        summary = _arm(
            workers, metrics, arm_wall=arm_wall, previous=previous,
            per_game_deadline_ns=per_game_deadline_ns,
            physical_memory_bytes=physical_memory_bytes,
            scientific_wall_ns=scientific_wall_ns,
            scientific_token_budget=scientific_token_budget,
            max_active_rpcs=tracker.maximum)
        arms.append(summary)
        total_physical_attempts += summary["physical_attempt_count"]
        total_redispatches += summary["redispatch_count"]
        total_exhaustions += summary["exhaustion_count"]
        total_retry_wall += summary["retry_wall_nanoseconds"]
        total_retry_tokens += summary["retry_token_count"]
        for key, value in summary["first_attempt_failure_by_class"].items():
            total_first_failures[key] = total_first_failures.get(key, 0) + value
        if arm_sink is not None:
            arm_sink(summary)
        if total_tokens > capacity_token_budget:
            stop_reason = "capacity-token-overrun"
            break
        if time.monotonic_ns() - started > capacity_wall_ns:
            stop_reason = "capacity-wall-overrun"
            break
        if not summary["passed"]:
            stop_reason = "arm-condition-failed"
            break
        previous = summary
    route = _route_decision(
        arms=arms, total_tokens=total_tokens,
        capacity_token_budget=capacity_token_budget,
        stop_reason=stop_reason,
        scientific_token_budget=scientific_token_budget)
    body = {"schema": SCHEMA,
            **route, "stop_reason": stop_reason,
            "secret_commitment_sha256": secret_commitment_sha256,
            "canary_receipt_sha256": canary_receipt_sha256,
            "source_review": dict(source_review),
            "per_game_deadline_nanoseconds": per_game_deadline_ns,
            "physical_memory_bytes": physical_memory_bytes,
            "capacity_wall_nanoseconds": capacity_wall_ns,
            "capacity_token_budget": capacity_token_budget,
            "scientific_wall_nanoseconds": scientific_wall_ns,
            "scientific_token_budget": scientific_token_budget,
            "elapsed_nanoseconds": max(1, time.monotonic_ns() - started),
            "total_token_count": total_tokens,
            "physical_attempt_count": total_physical_attempts,
            "first_attempt_failure_by_class": total_first_failures,
            "redispatch_count": total_redispatches,
            "exhaustion_count": total_exhaustions,
            "retry_wall_nanoseconds": total_retry_wall,
            "retry_token_count": total_retry_tokens,
            "arms": arms,
            "runtime": dict(runtime), "authority": dict(selfplay.AUTHORITY)}
    receipt = {**body, "receipt_sha256": _sha(body)}
    validate_capacity_receipt(receipt)
    return receipt


def validate_capacity_receipt(receipt: object) -> None:
    keys = {"schema", "route", "selected_workers", "selected_game_count",
            "selected_deal_cluster_count",
            "selected_population_wall_nanoseconds", "stop_reason",
            "projected_full_wall_nanoseconds", "projected_full_token_count",
            "projected_pilot_wall_nanoseconds", "projected_pilot_token_count",
            "secret_commitment_sha256", "canary_receipt_sha256",
            "source_review",
            "per_game_deadline_nanoseconds",
            "physical_memory_bytes", "capacity_wall_nanoseconds",
            "capacity_token_budget", "scientific_wall_nanoseconds",
            "scientific_token_budget", "elapsed_nanoseconds",
            "total_token_count", "physical_attempt_count",
            "first_attempt_failure_by_class", "redispatch_count",
            "exhaustion_count", "retry_wall_nanoseconds",
            "retry_token_count", "arms", "runtime", "authority",
            "receipt_sha256"}
    if type(receipt) is not dict or set(receipt) != keys \
            or receipt.get("schema") != SCHEMA:
        raise RPCCapacityError("capacity receipt schema drift")
    body = {key: value for key, value in receipt.items()
            if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != _sha(body):
        raise RPCCapacityError("capacity receipt seal drift")
    if receipt["authority"] != selfplay.AUTHORITY \
            or receipt["route"] not in (ROUTE_FULL, ROUTE_PILOT, ROUTE_REFUSE):
        raise RPCCapacityError("capacity receipt authority drift")
    for field in ("selected_game_count", "selected_deal_cluster_count",
                  "selected_population_wall_nanoseconds",
                  "projected_full_wall_nanoseconds",
                  "projected_full_token_count",
                  "projected_pilot_wall_nanoseconds",
                  "projected_pilot_token_count"):
        value = receipt[field]
        if value is not None and (isinstance(value, bool)
                                  or not isinstance(value, int)
                                  or value < 0):
            raise RPCCapacityError("capacity route projection drift")
    selected_workers = receipt["selected_workers"]
    if selected_workers is not None and (isinstance(selected_workers, bool)
                                         or not isinstance(selected_workers, int)
                                         or selected_workers < 0):
        raise RPCCapacityError("capacity selected worker drift")
    _strict_sha(receipt["secret_commitment_sha256"],
                "capacity secret commitment")
    _strict_sha(receipt["canary_receipt_sha256"],
                "capacity canary receipt SHA")
    for field, label in (
            ("per_game_deadline_nanoseconds", "per-game deadline"),
            ("physical_memory_bytes", "physical memory"),
            ("capacity_wall_nanoseconds", "capacity wall"),
            ("capacity_token_budget", "capacity tokens"),
            ("scientific_wall_nanoseconds", "scientific wall"),
            ("scientific_token_budget", "scientific tokens"),
            ("elapsed_nanoseconds", "capacity elapsed")):
        _positive(receipt[field], label)
    _nonnegative(receipt["total_token_count"], "capacity total tokens")
    for field_name, label in (("physical_attempt_count", "physical attempts"),
                              ("redispatch_count", "redispatches"),
                              ("exhaustion_count", "exhaustions"),
                              ("retry_wall_nanoseconds", "retry wall"),
                              ("retry_token_count", "retry tokens")):
        _nonnegative(receipt[field_name], f"capacity {label}")
    if type(receipt["first_attempt_failure_by_class"]) is not dict \
            or any(type(key) is not str or isinstance(value, bool)
                   or not isinstance(value, int) or value < 0
                   for key, value in receipt[
                       "first_attempt_failure_by_class"].items()):
        raise RPCCapacityError("capacity retry failure accounting drift")
    runtime = receipt["runtime"]
    if type(runtime) is not dict \
            or runtime.get("schema") != "pt-luna-turn-rpc-runtime-v1":
        raise RPCCapacityError("capacity runtime drift")
    runtime_keys = {"schema", "python_executable", "python_sha256",
                    "python_version", "platform", "boot_identity_sha256",
                    "engine_mode", "strict_voids",
                    "python_dont_write_bytecode", "required_environment",
                    "native_extension",
                    "execution_git", "git_tree",
                    "codex_binary",
                    "codex_binary_sha256", "codex_version", "model",
                    "reasoning_effort", "codex_tool_catalog", "sources",
                    "source_set_sha256"}
    catalog = runtime.get("codex_tool_catalog")
    catalog_keys = {"schema", "version", "binary_sha256",
                    "disabled_features", "feature_catalog_sha256"}
    if set(runtime) != runtime_keys or runtime.get("model") != MODEL \
            or runtime.get("reasoning_effort") != REASONING_EFFORT \
            or runtime.get("engine_mode") != "pure-python" \
            or runtime.get("strict_voids") is not True \
            or runtime.get("python_dont_write_bytecode") is not True \
            or runtime.get("required_environment") \
            != REQUIRED_ENGINE_ENVIRONMENT \
            or runtime.get("native_extension") is not None \
            or type(runtime.get("sources")) is not dict \
            or type(catalog) is not dict or set(catalog) != catalog_keys \
            or type(runtime.get("execution_git")) is not str \
            or len(runtime["execution_git"]) != 40 \
            or type(runtime.get("git_tree")) is not str \
            or len(runtime["git_tree"]) != 40 \
            or catalog.get("schema") != "pt-luna-codex-tool-catalog-v1" \
            or catalog.get("disabled_features") != list(DISABLED_FEATURES) \
            or catalog.get("binary_sha256") \
            != runtime.get("codex_binary_sha256") \
            or catalog.get("version") != runtime.get("codex_version") \
            or runtime.get("source_set_sha256") != _sha(runtime["sources"]):
        raise RPCCapacityError("capacity runtime derivation drift")
    _strict_sha(runtime.get("boot_identity_sha256"),
                "capacity boot identity")
    _strict_sha(runtime["python_sha256"], "capacity Python SHA")
    _strict_sha(runtime["codex_binary_sha256"], "capacity Codex SHA")
    _strict_sha(runtime["source_set_sha256"], "capacity source-set SHA")
    _strict_sha(catalog["feature_catalog_sha256"],
                "capacity feature-catalog SHA")
    if set(runtime["sources"]) != set(SOURCE_PATHS):
        raise RPCCapacityError("capacity runtime source population drift")
    for value in runtime["sources"].values():
        _strict_sha(value, "capacity source SHA")
    validate_source_review_auth(
        receipt["source_review"],
        expected_source_set_sha256=runtime["source_set_sha256"])
    previous = None
    total_tokens = 0
    total_physical_attempts = 0
    total_redispatches = 0
    total_exhaustions = 0
    total_retry_wall = 0
    total_retry_tokens = 0
    total_first_failures: dict[str, int] = {}
    arms = receipt["arms"]
    if type(arms) is not list or not arms \
            or len(arms) > len(WORKER_ARMS):
        raise RPCCapacityError("capacity arm population drift")
    for expected_workers, arm in zip(WORKER_ARMS, arms):
        if type(arm) is not dict or arm.get("schema") != ARM_SCHEMA \
                or arm.get("workers") != expected_workers:
            raise RPCCapacityError("capacity arm identity drift")
        metrics = [GameMetric.from_mapping(row) for row in arm.get("metrics", [])]
        expected = _arm(
            expected_workers, metrics,
            arm_wall=arm["arm_wall_nanoseconds"], previous=previous,
            per_game_deadline_ns=receipt["per_game_deadline_nanoseconds"],
            physical_memory_bytes=receipt["physical_memory_bytes"],
            scientific_wall_ns=receipt["scientific_wall_nanoseconds"],
            scientific_token_budget=receipt["scientific_token_budget"],
            max_active_rpcs=arm["max_active_model_rpcs"])
        if arm != expected:
            raise RPCCapacityError("capacity arm derivation drift")
        total_tokens += arm["aggregate_token_count"]
        total_physical_attempts += arm["physical_attempt_count"]
        total_redispatches += arm["redispatch_count"]
        total_exhaustions += arm["exhaustion_count"]
        total_retry_wall += arm["retry_wall_nanoseconds"]
        total_retry_tokens += arm["retry_token_count"]
        for key, value in arm["first_attempt_failure_by_class"].items():
            total_first_failures[key] = total_first_failures.get(key, 0) + value
        if arm["passed"]:
            previous = arm
        elif arm is not arms[-1]:
            raise RPCCapacityError("capacity continued after failed arm")
    if receipt["elapsed_nanoseconds"] < sum(
            arm["arm_wall_nanoseconds"] for arm in arms):
        raise RPCCapacityError("capacity elapsed derivation drift")
    expected_route = _route_decision(
        arms=arms, total_tokens=total_tokens,
        capacity_token_budget=receipt["capacity_token_budget"],
        stop_reason=receipt["stop_reason"],
        scientific_token_budget=receipt["scientific_token_budget"])
    if any(receipt[field] != expected_route[field] for field in expected_route) \
            or receipt["total_token_count"] != total_tokens:
        raise RPCCapacityError("capacity terminal derivation drift")
    if (receipt["physical_attempt_count"] != total_physical_attempts
            or receipt["redispatch_count"] != total_redispatches
            or receipt["exhaustion_count"] != total_exhaustions
            or receipt["retry_wall_nanoseconds"] != total_retry_wall
            or receipt["retry_token_count"] != total_retry_tokens
            or receipt["first_attempt_failure_by_class"] != total_first_failures):
        raise RPCCapacityError("capacity retry terminal derivation drift")
    stop_reason = receipt["stop_reason"]
    allowed_stop_reasons = {"all-arms-complete", "capacity-wall-before-arm",
                            "capacity-token-overrun", "capacity-wall-overrun",
                            "arm-condition-failed"}
    if stop_reason not in allowed_stop_reasons:
        raise RPCCapacityError("capacity stop-reason drift")
    elapsed_over = (receipt["elapsed_nanoseconds"]
                    > receipt["capacity_wall_nanoseconds"])
    token_over = total_tokens > receipt["capacity_token_budget"]
    last_failed = not arms[-1]["passed"]
    if token_over:
        compatible = stop_reason == "capacity-token-overrun"
    elif elapsed_over:
        compatible = stop_reason in {"capacity-wall-before-arm",
                                     "capacity-wall-overrun"}
    elif len(arms) == len(WORKER_ARMS) and not last_failed:
        compatible = stop_reason == "all-arms-complete"
    elif last_failed:
        compatible = stop_reason == "arm-condition-failed"
    else:
        compatible = False
    if not compatible:
        raise RPCCapacityError("capacity stop-reason derivation drift")


__all__ = ["GameMetric", "RPCCapacityError",
           "RPCConcurrency", "ROUTE_FULL", "ROUTE_PILOT",
           "ROUTE_FULL_104_ELIGIBLE", "ROUTE_PILOT_32_ELIGIBLE",
           "ROUTE_REFUSE",
           "SCHEMA", "WORKER_ARMS", "mechanics_sha256",
           "source_identity", "validate_canary_receipt",
           "validate_capacity_receipt", "validate_source_review_auth"]
