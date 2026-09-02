"""Score-free progressive capacity census for the PT-Luna turn-RPC route."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Mapping, Sequence

from . import privileged_teacher_luna_selfplay as selfplay
from . import privileged_teacher_luna_selfplay_execution as legacy_execution
from .privileged_teacher_luna_rpc_journal import (
    FileTurnJournal,
    TurnJournalError,
)
from .privileged_teacher_luna_rpc_transport import (
    CodexExecPlannerTransport,
    CodexProviderResourceError,
    CodexToolEventError,
    CodexTurnTransportError,
    DISABLED_FEATURES,
    InvocationResult,
    MODEL,
    REASONING_EFFORT,
    ActiveCallManager,
    _start_contained_process,
    attest_codex_runtime,
)
from .privileged_teacher_luna_turn_rpc import (
    TurnDriver,
    TurnRPCError,
    TurnValidationError,
)
from .privileged_teacher_pt0 import canonical_json_bytes


SCHEMA = "pt-luna-turn-rpc-capacity-v2"
CANARY_SCHEMA = "pt-luna-turn-rpc-real-canaries-v1"
SOURCE_REVIEW_SCHEMA = "pt-luna-turn-rpc-source-review-v1"
ARM_SCHEMA = "pt-luna-turn-rpc-capacity-arm-v2"
METRIC_SCHEMA = "pt-luna-turn-rpc-capacity-game-v2"
ROUTE_PASS = "CAPACITY_PASS"
ROUTE_REFUSE = "REFUSE_RESOURCE_OR_PROVIDER"
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
    "shengji/rl/privileged_teacher_luna_selfplay_execution.py",
    "shengji/rl/privileged_teacher_luna_turn_rpc.py",
    "shengji/rl/privileged_teacher_luna_rpc_transport.py",
    "shengji/rl/privileged_teacher_luna_rpc_watchdog.py",
    "shengji/rl/privileged_teacher_luna_rpc_io.py",
    "shengji/rl/privileged_teacher_luna_rpc_journal.py",
    "shengji/rl/privileged_teacher_luna_rpc_capacity.py",
    "shengji/rl/privileged_teacher_luna_rpc_collection.py",
    "shengji/rl/privileged_teacher_luna_rpc_supervisor.py",
    "scripts/privileged_teacher_luna_rpc_canary.py",
    "scripts/privileged_teacher_luna_rpc_capacity.py",
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

    def __post_init__(self) -> None:
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
                              "committed decision")):
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


class MeteredCodexRun:
    """Popen runner that exposes each process group to the reviewed meter."""

    def __init__(self, meter: legacy_execution.ProcessTreeResourceMeter,
                 concurrency: RPCConcurrency,
                 event_callback: Callable[[str], object] | None = None):
        self.meter = meter
        self.concurrency = concurrency
        self.active_calls = ActiveCallManager()
        self.invocation_count = 0
        self.invocation_wall_nanoseconds: list[int] = []
        self.event_callback = event_callback

    def __call__(self, command: tuple[str, ...], prompt: bytes,
                 workspace: Path, timeout_seconds: int) -> InvocationResult:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        started = time.monotonic_ns()
        process, watchdog_fd = _start_contained_process(
            command, workspace=workspace, env=env,
            active_calls=self.active_calls)
        self.invocation_count += 1
        registered = entered = False
        try:
            self.meter.register(process.pid)
            registered = True
            self.concurrency.enter()
            entered = True
            if self.event_callback is not None:
                self.event_callback("rpc-start")
            try:
                stdout, stderr = process.communicate(
                    input=prompt, timeout=timeout_seconds)
                returncode = int(process.returncode or 0)
            except subprocess.TimeoutExpired as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise CodexTurnTransportError(
                    "Codex turn deadline exceeded") from exc
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                process.communicate()
            try:
                if entered:
                    self.concurrency.leave()
                    if self.event_callback is not None:
                        self.event_callback("rpc-end")
            finally:
                if registered:
                    self.meter.unregister(process.pid)
            self.invocation_wall_nanoseconds.append(
                max(1, time.monotonic_ns() - started))
            self.active_calls.release(process.pid, watchdog_fd)
        wall_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
        return InvocationResult(returncode, stdout, stderr, wall_ms)


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
            "design_sha256", "score_free_canary_authorized",
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
    for key in ("source_set_sha256", "design_sha256", "claim_sha256"):
        _strict_sha(claim[key], f"source review {key}")
    body = {key: item for key, item in claim.items()
            if key != "claim_sha256"}
    if claim["claim_sha256"] != _sha(body) \
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


class RealGameRunner:
    """Run one full score-free capacity game and discard all outcome bytes."""

    def __init__(self, *, capacity_secret: bytes, codex_binary: Path,
                 temp_root: Path, per_call_timeout_seconds: int,
                 per_game_deadline_seconds: int,
                 concurrency: RPCConcurrency,
                 runtime: Mapping[str, object],
                 progress_sink: Callable[[Mapping[str, object]], object]
                 | None = None):
        if type(capacity_secret) is not bytes or len(capacity_secret) != 32:
            raise RPCCapacityError("capacity secret drift")
        self.secret = capacity_secret
        self.codex_binary = Path(codex_binary)
        self.temp_root = Path(temp_root)
        self.timeout = per_call_timeout_seconds
        self.game_deadline_ns = _positive(
            per_game_deadline_seconds, "capacity game deadline") * 1_000_000_000
        self.concurrency = concurrency
        if type(runtime) is not dict \
                or type(runtime.get("codex_tool_catalog")) is not dict:
            raise RPCCapacityError("capacity runtime drift")
        self.runtime = dict(runtime)
        self.catalog = dict(runtime["codex_tool_catalog"])
        self.mechanics = mechanics_sha256()
        if progress_sink is not None and not callable(progress_sink):
            raise RPCCapacityError("capacity progress sink drift")
        self.progress_sink = progress_sink

    def _emit_progress(self, event: str, *, workers: int, worker: int,
                       game: int, journal: FileTurnJournal,
                       absolute_deadline_ns: int) -> None:
        if self.progress_sink is None:
            return
        self._emit_progress_snapshot(
            event, workers=workers, worker=worker, game=game,
            summary=journal.summary(),
            absolute_deadline_ns=absolute_deadline_ns)

    def _emit_progress_snapshot(self, event: str, *, workers: int,
                                worker: int, game: int,
                                summary: Mapping[str, object],
                                absolute_deadline_ns: int) -> None:
        if self.progress_sink is None:
            return
        self.progress_sink({
            "schema": "pt-luna-rpc-capacity-progress-v1",
            "event": event, "arm_workers": workers,
            "worker": worker, "game": game,
            "opened_rpc_count": summary["opened_rpc_count"],
            "committed_decision_count": summary[
                "committed_decision_count"],
            "remaining_game_deadline_seconds": max(
                0, absolute_deadline_ns - time.monotonic_ns())
                // 1_000_000_000,
            "active_model_rpcs": self.concurrency.active,
        })

    def __call__(self, workers: int, worker: int, game_index: int) -> GameMetric:
        started = time.monotonic_ns()
        absolute_deadline_ns = started + self.game_deadline_ns
        meter = legacy_execution.ProcessTreeResourceMeter()
        evidence_sha = _sha({"workers": workers, "worker": worker,
                             "game": game_index, "status": "incomplete"})
        complete = verified = False
        process_errors = 0
        evidence = ()
        driver = None
        journal = None
        usage_snapshot = None
        refusal_tool_event_snapshot = None
        journal_summary_snapshot = None
        tool_event_count = 0
        stage = "dispatch"
        failure = None
        metered = MeteredCodexRun(meter, self.concurrency)
        try:
            key = canonical_json_bytes({"schema": "pt-luna-rpc-capacity-seed-v1",
                                        "workers": workers, "worker": worker,
                                        "game": game_index})
            secret = hashlib.sha256(self.secret + key).digest()
            coordinate = selfplay.LunaDesign().root_coordinates[
                (workers * 7 + worker * 2 + game_index) % 52]
            shared = selfplay.LunaSelfPlayGame(
                selfplay.build_root(secret, coordinate),
                coordinate=coordinate, mirror=game_index,
                seed_secret=secret)
            with tempfile.TemporaryDirectory(
                    prefix=f"pt-luna-cap-{workers}-{worker}-{game_index}-",
                    dir=self.temp_root) as directory:
                journal = FileTurnJournal(Path(directory) / "journal")
                metered.event_callback = lambda event: self._emit_progress(
                    event, workers=workers, worker=worker, game=game_index,
                    journal=journal,
                    absolute_deadline_ns=absolute_deadline_ns)
                try:
                    transport = CodexExecPlannerTransport(
                        codex_binary=self.codex_binary,
                        timeout_seconds=self.timeout, temp_root=Path(directory),
                        run_command=metered,
                        runtime_attestor=lambda _: dict(self.catalog),
                        deadline_provider=lambda: absolute_deadline_ns)
                    driver = TurnDriver(shared, transport, journal=journal)
                    while not shared.complete and shared.failed is None:
                        if time.monotonic_ns() >= absolute_deadline_ns:
                            shared.fail("capacity game deadline exceeded")
                            raise CodexTurnTransportError(
                                "capacity game deadline exceeded")
                        stage = "dispatch"
                        driver.step()
                        stage = "journal-commit"
                        self._emit_progress(
                            "transition-commit", workers=workers,
                            worker=worker, game=game_index, journal=journal,
                            absolute_deadline_ns=absolute_deadline_ns)
                    stage = "terminal-verification"
                    evidence = tuple(driver.evidence)
                    artifacts = shared.completed_artifacts()
                    reopened = selfplay.SealedTrajectory.reopen(
                        artifacts.trajectory.private_bytes())
                    selfplay.CompletedGameArtifacts(
                        reopened, artifacts.terminal_receipt)
                    evidence_sha = _sha({
                        "trajectory_sha256": artifacts.trajectory.sha256,
                        "terminal_receipt_sha256":
                            artifacts.terminal_receipt.receipt_sha256,
                        "journal": journal.summary(),
                        "provider_response_sha256s": [
                            row.provider_response_sha256 for row in evidence],
                    })
                    complete = verified = True
                    self._emit_progress(
                        "game-complete", workers=workers, worker=worker,
                        game=game_index, journal=journal,
                        absolute_deadline_ns=absolute_deadline_ns)
                finally:
                    usage_snapshot = journal.usage_totals()
                    journal_summary_snapshot = journal.summary()
                    refusal_tool_event_snapshot = \
                        journal.pending_refusal_tool_event_count()
        except Exception as exc:
            process_errors = 1
            failure = _failure_disposition(exc, stage=stage)
            tool_event_count = (
                int(isinstance(exc, CodexToolEventError))
                if refusal_tool_event_snapshot is None
                else refusal_tool_event_snapshot)
            if driver is not None:
                evidence = tuple(driver.evidence)
            if journal_summary_snapshot is not None:
                self._emit_progress_snapshot(
                    "game-failure", workers=workers, worker=worker,
                    game=game_index, summary=journal_summary_snapshot,
                    absolute_deadline_ns=absolute_deadline_ns)
        observed_process_count = 0
        try:
            resource = meter.close()
            observed_process_count = meter.observed_process_count()
        except Exception as exc:
            process_errors = 1
            complete = verified = False
            failure = _failure_disposition(exc, stage="resource-meter")
            failure = ("resource-meter", "resource-meter", *failure[2:])
            resource = {"busy_cpu_nanoseconds": 0, "peak_rss_bytes": 0,
                        "swap_bytes": 0}
        wall = max(1, time.monotonic_ns() - started)
        usage = usage_snapshot
        input_tokens = (sum(row.usage.input_tokens for row in evidence)
                        if usage is None else usage["input_tokens"])
        cached_tokens = (sum(row.usage.cached_input_tokens for row in evidence)
                         if usage is None else usage["cached_input_tokens"])
        cache_write = (sum(
            row.usage.cache_write_input_tokens for row in evidence)
            if usage is None else usage["cache_write_input_tokens"])
        output_tokens = (sum(row.usage.output_tokens for row in evidence)
                         if usage is None else usage["output_tokens"])
        reasoning_tokens = (sum(
            row.usage.reasoning_output_tokens for row in evidence)
            if usage is None else usage["reasoning_output_tokens"])
        rpc_walls = metered.invocation_wall_nanoseconds
        p95_rpc_wall = _p95(rpc_walls) if rpc_walls else 0
        max_rpc_wall = max(rpc_walls, default=0)
        max_rpc_tokens = max(
            (row.usage.total_tokens for row in evidence), default=0)
        total_tokens = input_tokens + output_tokens
        token_rate = total_tokens * 1_000_000_000_000 // wall
        if failure is None:
            failure = ("none", "none", False, False, "none",
                       NO_FAILURE_MESSAGE_SHA256)
        opened = (metered.invocation_count if journal_summary_snapshot is None
                  else int(journal_summary_snapshot["call_count"]))
        committed = int(getattr(driver, "decision_index", 0))
        return GameMetric(
            workers, worker, game_index, complete, verified, wall,
            int(resource["busy_cpu_nanoseconds"]),
            int(resource["peak_rss_bytes"]), int(resource["swap_bytes"]),
            process_errors, tool_event_count,
            max(metered.invocation_count, opened),
            observed_process_count,
            p95_rpc_wall, max_rpc_wall, max_rpc_tokens,
            input_tokens, cached_tokens,
            cache_write, output_tokens, reasoning_tokens, token_rate,
            self.mechanics, evidence_sha,
            failure_stage=failure[0], failure_kind=failure[1],
            game_deadline_fired=failure[2], call_timeout_fired=failure[3],
            exception_type=failure[4], failure_message_sha256=failure[5],
            last_opened_rpc_count=opened,
            last_committed_decision_count=committed)


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
    deadline_passed = p95 * 100 <= per_game_deadline_ns * 75
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
    max_game_token_count = max(row.token_count for row in metrics)
    per_game_token_cap = math.ceil(max_game_token_count * 125 / 100)
    max_rpc_token_count = max(row.max_rpc_token_count for row in metrics)
    per_call_token_reserve = math.ceil(max_rpc_token_count * 125 / 100)
    max_rpc_wall_nanoseconds = max(
        row.max_rpc_wall_nanoseconds for row in metrics)
    per_call_wall_reserve_milliseconds = max(
        1, math.ceil(max_rpc_wall_nanoseconds * 125
                     / (100 * 1_000_000)))
    projected_tokens = math.ceil(tokens * 104 * 125 / (len(metrics) * 100))
    batches = math.ceil(104 / workers)
    projected_wall = math.ceil(p95 * batches * 125 / 100)
    projection_passed = (projected_tokens <= scientific_token_budget
                         and projected_wall <= scientific_wall_ns)
    projection_required = workers == 4
    passed = (complete and process_passed and mechanics_passed and rss_passed
              and swap_passed and deadline_passed and parallelism_passed
              and scaling_passed
              and (projection_passed or not projection_required))
    return {"schema": ARM_SCHEMA, "workers": workers,
            "metrics": [row.payload() for row in sorted(
                metrics, key=lambda row: (row.worker, row.game))],
            "completed_games": sum(row.complete for row in metrics),
            "verified_games": sum(row.verified for row in metrics),
            "arm_wall_nanoseconds": arm_wall,
            "p95_game_wall_nanoseconds": p95,
            "aggregate_peak_rss_bytes": rss,
            "aggregate_token_count": tokens,
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
            "projection_required": projection_required,
            "projection_passed": projection_passed, "passed": passed}


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
    selected = (4 if len(arms) == len(WORKER_ARMS)
                and arms[-1]["workers"] == 4 and arms[-1]["passed"]
                else None)
    if stop_reason in {"capacity-token-overrun", "capacity-wall-overrun",
                       "capacity-wall-before-arm"}:
        selected = None
    body = {"schema": SCHEMA,
            "route": ROUTE_PASS if selected is not None else ROUTE_REFUSE,
            "selected_workers": selected, "stop_reason": stop_reason,
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
            "total_token_count": total_tokens, "arms": arms,
            "runtime": dict(runtime), "authority": dict(selfplay.AUTHORITY)}
    receipt = {**body, "receipt_sha256": _sha(body)}
    validate_capacity_receipt(receipt)
    return receipt


def run_capacity(*, canary_receipt: Mapping[str, object],
                 capacity_secret: bytes, codex_binary: Path,
                 temp_root: Path, per_call_timeout_seconds: int,
                 runtime: Mapping[str, object],
                 secret_commitment_sha256: str,
                 source_review: Mapping[str, object],
                 per_game_deadline_ns: int, physical_memory_bytes: int,
                 capacity_wall_ns: int, capacity_token_budget: int,
                 scientific_wall_ns: int, scientific_token_budget: int,
                 progress_sink: Callable[[Mapping[str, object]], object] | None = None,
                 arm_sink: Callable[[Mapping[str, object]], object] | None = None) \
        -> dict[str, object]:
    """Authenticated public capacity entry point used by the official CLI."""
    canary_sha = validate_canary_receipt(
        canary_receipt, expected_runtime=runtime)
    if (type(capacity_secret) is not bytes or len(capacity_secret) != 32
            or hashlib.sha256(capacity_secret).hexdigest()
            != secret_commitment_sha256
            or source_identity(Path(codex_binary)) != dict(runtime)):
        raise RPCCapacityError("capacity real runner binding drift")
    from .privileged_teacher_luna_rpc_supervisor import (
        SOURCE_REVIEW_PREFIX, authenticate_review_claim,
        source_review_claim,
    )
    repo_root = Path(__file__).resolve().parents[3]
    current_claim = source_review_claim(repo_root)
    authenticated = authenticate_review_claim(
        claim=current_claim, prefix=SOURCE_REVIEW_PREFIX,
        review_commit=source_review.get("review_commit", ""))
    if dict(source_review) != authenticated \
            or canary_receipt.get("source_review") != authenticated:
        raise RPCCapacityError("capacity source review authentication drift")
    concurrency = RPCConcurrency()
    game_runner = RealGameRunner(
        capacity_secret=capacity_secret, codex_binary=codex_binary,
        temp_root=temp_root,
        per_call_timeout_seconds=per_call_timeout_seconds,
        per_game_deadline_seconds=per_game_deadline_ns // 1_000_000_000,
        concurrency=concurrency, runtime=runtime,
        progress_sink=progress_sink)
    receipt = _derive_capacity(
        game_runner=game_runner, runtime=runtime,
        secret_commitment_sha256=secret_commitment_sha256,
        canary_receipt_sha256=canary_sha, source_review=authenticated,
        per_game_deadline_ns=per_game_deadline_ns,
        physical_memory_bytes=physical_memory_bytes,
        capacity_wall_ns=capacity_wall_ns,
        capacity_token_budget=capacity_token_budget,
        scientific_wall_ns=scientific_wall_ns,
        scientific_token_budget=scientific_token_budget,
        progress_sink=progress_sink, arm_sink=arm_sink,
        concurrency=concurrency)
    if source_identity(Path(codex_binary)) != dict(runtime):
        raise RPCCapacityError("capacity terminal runtime drift")
    return receipt


def validate_capacity_receipt(receipt: object) -> None:
    keys = {"schema", "route", "selected_workers", "stop_reason",
            "secret_commitment_sha256", "canary_receipt_sha256",
            "source_review",
            "per_game_deadline_nanoseconds",
            "physical_memory_bytes", "capacity_wall_nanoseconds",
            "capacity_token_budget", "scientific_wall_nanoseconds",
            "scientific_token_budget", "elapsed_nanoseconds",
            "total_token_count", "arms", "runtime", "authority",
            "receipt_sha256"}
    if type(receipt) is not dict or set(receipt) != keys \
            or receipt.get("schema") != SCHEMA:
        raise RPCCapacityError("capacity receipt schema drift")
    body = {key: value for key, value in receipt.items()
            if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != _sha(body):
        raise RPCCapacityError("capacity receipt seal drift")
    if receipt["authority"] != selfplay.AUTHORITY \
            or receipt["route"] not in (ROUTE_PASS, ROUTE_REFUSE):
        raise RPCCapacityError("capacity receipt authority drift")
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
        if arm["passed"]:
            previous = arm
        elif arm is not arms[-1]:
            raise RPCCapacityError("capacity continued after failed arm")
    if receipt["elapsed_nanoseconds"] < sum(
            arm["arm_wall_nanoseconds"] for arm in arms):
        raise RPCCapacityError("capacity elapsed derivation drift")
    selected = (4 if len(arms) == len(WORKER_ARMS)
                and arms[-1]["workers"] == 4 and arms[-1]["passed"]
                else None)
    if receipt["stop_reason"] in {"capacity-token-overrun",
                                  "capacity-wall-overrun",
                                  "capacity-wall-before-arm"}:
        selected = None
    if receipt["selected_workers"] != selected \
            or (receipt["route"] == ROUTE_PASS) != (selected is not None) \
            or receipt["total_token_count"] != total_tokens:
        raise RPCCapacityError("capacity terminal derivation drift")
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


__all__ = ["GameMetric", "MeteredCodexRun", "RPCCapacityError",
           "RPCConcurrency", "RealGameRunner", "ROUTE_PASS", "ROUTE_REFUSE",
           "SCHEMA", "WORKER_ARMS", "mechanics_sha256", "run_capacity",
           "source_identity", "validate_canary_receipt",
           "validate_capacity_receipt", "validate_source_review_auth"]
