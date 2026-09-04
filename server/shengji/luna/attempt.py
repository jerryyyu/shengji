"""Durable per-game execution for supervisor-owned PT-Luna collection.

This module owns no population choice.  It turns one already-scheduled
game into either a fully reopenable private game artifact or one terminal,
non-retryable refusal artifact, charging the shared ledger exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import time
from typing import Callable, Mapping

from . import game as selfplay
from .journal import (
    FileTurnJournal,
    SealedTurnRefusal,
    TurnJournalError,
)
from .ledger import (
    REDISPATCH_ELIGIBILITIES,
    RPCCollectionError,
    ResourceBoundaryError,
    ScientificBudgetLedger,
    SettledResourceBoundaryError,
    _fsync_dir,
    _publish,
    _read,
    _sha,
    _sha_bytes,
    _strict_sha,
    _validate_private_dir,
)
from .runtime import (
    FAILURE_KINDS,
    FAILURE_STAGES,
    NO_FAILURE_MESSAGE_SHA256,
    RPCConcurrency,
    RUNTIME_SCHEMA,
    source_identity,
)
from .transport import (
    CodexExecPlannerTransport,
    CodexProviderResourceError,
    CodexToolEventError,
    CodexTurnTransportError,
    _default_run,
)
from .turn import (
    AttemptRef,
    DecisionPacket,
    PlannerTransport,
    TurnDriver,
    TurnRPCError,
    TurnValidationError,
)
from .canonical import canonical_json_bytes


ATTEMPT_SCHEMA = "pt-luna-turn-rpc-game-attempt-v2"
EVIDENCE_SCHEMA = "pt-luna-turn-rpc-game-evidence-v1"
FAILURE_SCHEMA = "pt-luna-turn-rpc-game-failure-v2"
MANIFEST_SCHEMA = "pt-luna-turn-rpc-game-manifest-v2"


@dataclass(frozen=True)
class FailureDisposition:
    stage: str
    kind: str
    game_deadline_fired: bool
    call_timeout_fired: bool
    exception_type: str
    message_sha256: str
    last_opened_rpc_count: int
    last_committed_decision_count: int

    def __post_init__(self) -> None:
        if self.stage not in FAILURE_STAGES or self.stage == "none" \
                or self.kind not in FAILURE_KINDS or self.kind == "none" \
                or type(self.game_deadline_fired) is not bool \
                or type(self.call_timeout_fired) is not bool \
                or type(self.exception_type) is not str \
                or not self.exception_type \
                or type(self.message_sha256) is not str \
                or len(self.message_sha256) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in self.message_sha256) \
                or self.message_sha256 == NO_FAILURE_MESSAGE_SHA256:
            raise RPCCollectionError("game failure disposition drift")
        for value in (self.last_opened_rpc_count,
                      self.last_committed_decision_count):
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value < 0:
                raise RPCCollectionError("game failure progress drift")
        if self.last_committed_decision_count > self.last_opened_rpc_count:
            raise RPCCollectionError("game failure progress drift")

    def payload(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: object) -> "FailureDisposition":
        fields = set(cls.__dataclass_fields__)
        if type(value) is not dict or set(value) != fields:
            raise RPCCollectionError("game failure disposition schema drift")
        return cls(**{name: value[name] for name in fields})


def _failure_disposition(exc: BaseException, *, stage: str,
                         journal: FileTurnJournal) -> FailureDisposition:
    message = str(exc) or type(exc).__name__
    lowered = message.lower()
    summary = journal.summary()
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
        stage, kind = "validation", "forbidden-tool"
    elif isinstance(exc, ResourceBoundaryError):
        stage, kind = "provider-response", "provider-process"
    elif isinstance(exc, CodexProviderResourceError):
        stage, kind = "provider-response", "provider-process"
    elif isinstance(exc, TurnJournalError):
        stage, kind = "journal-commit", "journal-io"
    elif isinstance(exc, TurnValidationError):
        engine = "engine" in lowered or "candidate" in lowered
        stage, kind = (("engine-apply", "engine-validation") if engine
                       else ("validation", "transport-validation"))
    elif isinstance(exc, CodexTurnTransportError):
        stage, kind = "provider-response", "provider-schema"
    elif isinstance(exc, TurnRPCError):
        stage, kind = "validation", "transport-validation"
    elif isinstance(exc, RPCCollectionError):
        kind = "engine-validation"
    else:
        kind = "unknown"
    return FailureDisposition(
        stage, kind, game_deadline, call_timeout, type(exc).__name__,
        hashlib.sha256(message.encode(
            "utf-8", errors="replace")).hexdigest(),
        int(summary["opened_rpc_count"]),
        int(summary["committed_decision_count"]))


def _publish_or_verify(path: Path, payload: object) -> None:
    """Resume a deterministic post-game publish without overwriting bytes."""
    raw = canonical_json_bytes(payload)
    if path.exists():
        if canonical_json_bytes(_read(path)) != raw:
            raise RPCCollectionError("resumed game publication drift")
        return
    _publish(path, payload, repair_partial=True)


def _attempt_name(coordinate: tuple[str, int, int], mirror: int) -> str:
    selfplay.LunaCoordinate(*coordinate)
    if mirror not in (0, 1):
        raise RPCCollectionError("game mirror drift")
    return f"{coordinate[0]}-{coordinate[1]}-{coordinate[2]}-mirror-{mirror}"


def _terminal(payload: Mapping[str, object]) -> selfplay.TerminalReceipt:
    if type(payload) is not dict or payload.get("schema") \
            != selfplay.TERMINAL_RECEIPT_SCHEMA:
        raise RPCCollectionError("terminal receipt schema drift")
    return selfplay.TerminalReceipt(
        tuple(payload["coordinate"]), payload["mirror"],
        payload["root_sha256"], payload["trajectory_sha256"],
        payload["final_attacker_points"], payload["signed_level_utility"],
        payload["completion"], payload["receipt_sha256"],
        payload["authority"])


def _journal_hashes(root: Path) -> dict[str, str]:
    try:
        root_stat = root.stat(follow_symlinks=False)
    except OSError as exc:
        raise RPCCollectionError("journal directory drift") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink() \
            or root_stat.st_uid != os.getuid() \
            or stat.S_IMODE(root_stat.st_mode) != 0o700:
        raise RPCCollectionError("journal directory drift")
    rows: dict[str, str] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        item = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(item.st_mode) or path.is_symlink() \
                or item.st_uid != os.getuid() or item.st_nlink != 1 \
                or stat.S_IMODE(item.st_mode) != 0o400:
            raise RPCCollectionError("journal file population drift")
        rows[path.name] = _sha_bytes(canonical_json_bytes(_read(path)))
    return rows


@dataclass(frozen=True)
class AttemptReopen:
    status: str
    manifest_sha256: str
    artifacts: selfplay.CompletedGameArtifacts | None
    failure_kind: str | None
    failure_class: str | None
    usage: Mapping[str, int]
    failure_disposition: FailureDisposition | None = None


def runtime_stable_view(runtime: Mapping[str, object]) -> dict[str, object]:
    """Runtime identity minus the working-tree dirtiness flag.

    ``git_dirty`` is stamped at launch for the record, but a tree flipping
    clean<->dirty while a run is in flight is not a change of the executing
    runtime and must not refuse the next game.
    """
    return {key: value for key, value in runtime.items() if key != "git_dirty"}


class _Never:
    def call(self, packet):
        del packet
        raise AssertionError("reopen invoked a provider")


def reopen_attempt(
        path: Path, *, seed_secret: bytes,
        expected_runtime_sha256: str | None = None,
        expected_coordinate: tuple[str, int, int] | None = None,
        expected_mirror: int | None = None) \
        -> AttemptReopen:
    """Reopen one complete/refused game without a provider call."""
    path = Path(path)
    _validate_private_dir(path, "game attempt directory")
    attempt = _read(path / "attempt.json")
    manifest = _read(path / "manifest.json")
    if set(attempt) != {"schema", "coordinate", "mirror", "root_sha256",
                       "seed_commitment_sha256", "runtime_sha256",
                       "boot_identity_sha256",
                       "started_monotonic_nanoseconds",
                       "per_game_deadline_nanoseconds", "per_game_token_cap",
                       "per_call_token_reserve",
                       "per_call_wall_reserve_milliseconds",
                       "authority", "attempt_sha256"} \
            or attempt["schema"] != ATTEMPT_SCHEMA:
        raise RPCCollectionError("game attempt schema drift")
    attempt_body = {key: value for key, value in attempt.items()
                    if key != "attempt_sha256"}
    if attempt["attempt_sha256"] != _sha(attempt_body) \
            or hashlib.sha256(seed_secret).hexdigest() \
            != attempt["seed_commitment_sha256"]:
        raise RPCCollectionError("game attempt seal drift")
    _strict_sha(attempt["boot_identity_sha256"], "game boot identity")
    if isinstance(attempt["started_monotonic_nanoseconds"], bool) \
            or not isinstance(attempt["started_monotonic_nanoseconds"], int) \
            or attempt["started_monotonic_nanoseconds"] <= 0:
        raise RPCCollectionError("game start clock drift")
    coordinate = tuple(attempt["coordinate"])
    mirror = attempt["mirror"]
    selfplay.LunaCoordinate(*coordinate)
    if (expected_coordinate is None) != (expected_mirror is None):
        raise RPCCollectionError("game expected identity population drift")
    if expected_coordinate is not None:
        if type(expected_coordinate) is not tuple \
                or tuple(expected_coordinate) != coordinate \
                or type(expected_mirror) is not int \
                or expected_mirror != mirror:
            raise RPCCollectionError("game scheduled identity drift")
    if expected_runtime_sha256 is not None \
            and attempt["runtime_sha256"] != expected_runtime_sha256:
        raise RPCCollectionError("game runtime binding drift")
    root = selfplay.build_root(seed_secret, coordinate, mirror=mirror)
    if selfplay.root_identity(root) != attempt["root_sha256"]:
        raise RPCCollectionError("game root binding drift")
    manifest_keys = {"schema", "status", "coordinate", "mirror",
                     "attempt_sha256", "runtime_sha256", "files",
                     "journal_files", "journal_summary", "usage",
                     "failure_kind", "failure_class",
                     "failure_disposition", "authority",
                     "manifest_sha256"}
    if set(manifest) != manifest_keys or manifest["schema"] != MANIFEST_SCHEMA:
        raise RPCCollectionError("game manifest schema drift")
    manifest_body = {key: value for key, value in manifest.items()
                     if key != "manifest_sha256"}
    if manifest["manifest_sha256"] != _sha(manifest_body) \
            or manifest["coordinate"] != list(coordinate) \
            or manifest["mirror"] != mirror \
            or manifest["attempt_sha256"] != attempt["attempt_sha256"] \
            or manifest["runtime_sha256"] != attempt["runtime_sha256"] \
            or manifest["authority"] != selfplay.AUTHORITY:
        raise RPCCollectionError("game manifest binding drift")
    files = manifest["files"]
    if type(files) is not dict:
        raise RPCCollectionError("game file manifest drift")
    expected_entries = {"attempt.json", "journal", "manifest.json", *files}
    if {item.name for item in path.iterdir()} != expected_entries:
        raise RPCCollectionError("game artifact population drift")
    opened_files: dict[str, dict[str, object]] = {}
    for name, digest in files.items():
        _strict_sha(digest, "game file SHA")
        opened = _read(path / name)
        opened_files[name] = opened
        if _sha_bytes(canonical_json_bytes(opened)) != digest:
            raise RPCCollectionError("game file hash drift")
    journal = FileTurnJournal(path / "journal")
    if _journal_hashes(path / "journal") != manifest["journal_files"] \
            or journal.summary() != manifest["journal_summary"] \
            or journal.usage_totals() != manifest["usage"]:
        raise RPCCollectionError("game journal manifest drift")
    game = selfplay.LunaSelfPlayGame(
        root, coordinate=coordinate, mirror=mirror, seed_secret=seed_secret)
    driver = TurnDriver(game, _Never(), journal=journal)
    if manifest["status"] == "complete":
        if set(files) != {"attempt.json", "evidence.json", "trajectory.json",
                         "terminal.json"} \
                or manifest["failure_kind"] is not None \
                or manifest["failure_class"] is not None \
                or manifest["failure_disposition"] is not None \
                or not game.complete or game.failed is not None:
            raise RPCCollectionError("complete game manifest drift")
        evidence = opened_files["evidence.json"]
        if set(evidence) != {"schema", "rows", "evidence_sha256"} \
                or evidence["schema"] != EVIDENCE_SCHEMA \
                or evidence["evidence_sha256"] != _sha({
                    "schema": EVIDENCE_SCHEMA, "rows": evidence["rows"]}) \
                or evidence["rows"] != [row.payload()
                                         for row in driver.evidence]:
            raise RPCCollectionError("game evidence derivation drift")
        trajectory = selfplay.SealedTrajectory.reopen(
            canonical_json_bytes(opened_files["trajectory.json"]))
        terminal = _terminal(opened_files["terminal.json"])
        artifacts = selfplay.CompletedGameArtifacts(trajectory, terminal)
        if artifacts.trajectory.body["coordinate"] != list(coordinate) \
                or artifacts.trajectory.body["mirror"] != mirror:
            raise RPCCollectionError("game artifact coordinate drift")
        return AttemptReopen(
            "complete", manifest["manifest_sha256"], artifacts, None, None,
            dict(manifest["usage"]))
    if manifest["status"] != "incomplete" \
            or not {"attempt.json", "failure.json"}.issubset(files) \
            or set(files) - {"attempt.json", "failure.json", "evidence.json",
                             "trajectory.json", "terminal.json"} \
            or type(manifest["failure_kind"]) is not str \
            or manifest["failure_class"] not in {
                "mechanics-privacy", "resource-provider"} \
            or type(manifest["failure_disposition"]) is not dict:
        raise RPCCollectionError("incomplete game manifest drift")
    disposition = FailureDisposition.from_mapping(
        manifest["failure_disposition"])
    failure = opened_files["failure.json"]
    if set(failure) != {"schema", "coordinate", "mirror", "failure_kind",
                       "failure_class", "failure_fingerprint_sha256",
                       "failure_disposition",
                       "journal_summary_sha256",
                       "authority", "artifact_sha256"} \
            or failure["schema"] != FAILURE_SCHEMA \
            or failure["coordinate"] != list(coordinate) \
            or failure["mirror"] != mirror \
            or failure["failure_kind"] != manifest["failure_kind"] \
            or failure["failure_class"] != manifest["failure_class"] \
            or failure["failure_disposition"] != disposition.payload() \
            or failure["failure_fingerprint_sha256"] != _sha({
                "failure_kind": failure["failure_kind"],
                "failure_class": failure["failure_class"],
                "failure_disposition": disposition.payload()}) \
            or failure["journal_summary_sha256"] \
            != _sha(manifest["journal_summary"]) \
            or failure["authority"] != selfplay.AUTHORITY:
        raise RPCCollectionError("game failure binding drift")
    failure_body = {key: value for key, value in failure.items()
                    if key != "artifact_sha256"}
    if failure["artifact_sha256"] != _sha(failure_body):
        raise RPCCollectionError("game failure seal drift")
    return AttemptReopen(
        "incomplete", manifest["manifest_sha256"], None,
        manifest["failure_kind"], manifest["failure_class"],
        dict(manifest["usage"]), disposition)


class _CountingRun:
    def __init__(self, concurrency: RPCConcurrency):
        self.concurrency = concurrency
        from .transport import ActiveCallManager
        self.active_calls = ActiveCallManager()

    def __call__(self, command, prompt, workspace, timeout_seconds):
        self.concurrency.enter()
        try:
            return _default_run(
                command, prompt, workspace, timeout_seconds,
                _active_call_manager=self.active_calls)
        finally:
            self.concurrency.leave()


TransportFactory = Callable[[Path], PlannerTransport]


class _DeadlineTransport:
    """Game-owned absolute boundary around both real and injected transports."""

    def __init__(self, inner: PlannerTransport,
                 deadline_provider: Callable[[], int],
                 event_callback: Callable[[str], object] | None = None,
                 configure_inner_deadline: bool = True):
        self.inner = inner
        self.deadline_provider = deadline_provider
        self.event_callback = event_callback
        if configure_inner_deadline and hasattr(inner, "deadline_provider"):
            setattr(inner, "deadline_provider", deadline_provider)

    def call(self, packet: DecisionPacket):
        deadline = self.deadline_provider()
        if time.monotonic_ns() >= deadline:
            raise ResourceBoundaryError(
                "game deadline exceeded before dispatch")
        if self.event_callback is not None:
            self.event_callback("rpc-start")
        try:
            response = self.inner.call(packet)
        finally:
            if self.event_callback is not None:
                self.event_callback("rpc-end")
        if time.monotonic_ns() >= deadline:
            raise ResourceBoundaryError(
                "game deadline exceeded after provider response")
        return response

    def take_private_evidence(self, packet, response):
        take = getattr(self.inner, "take_private_evidence", None)
        return None if take is None else take(packet, response)

    def take_private_refusal_evidence(self, packet):
        take = getattr(self.inner, "take_private_refusal_evidence", None)
        return None if take is None else take(packet)


class RPCGameAttemptRunner:
    """Run/resume one schedule item and seal it exactly once."""

    def __init__(
            self, *, seed_secret: bytes, attempts_root: Path,
            codex_binary: Path | None, runtime: Mapping[str, object],
            per_game_deadline_seconds: int, per_game_token_cap: int,
            concurrency: RPCConcurrency | None = None,
            stop_event: threading.Event | None = None,
            scientific_budget_provider: Callable[[], Mapping[str, int]] | None = None,
            scientific_response_acceptor: Callable[[object], object] | None = None,
            scientific_dispatch_reserver: Callable[[DecisionPacket], object] | None = None,
            scientific_attempt_reserver: Callable[[DecisionPacket, object], object]
            | None = None,
            scientific_refusal_settler: Callable[[object, Mapping[str, object]], object]
            | None = None,
            scientific_journal_response_acceptor: Callable[[object, object], object]
            | None = None,
            scientific_refusal_acceptor: Callable[[Mapping[str, object]], object] | None = None,
            scientific_terminal_acceptor: Callable[[], object] | None = None,
            per_call_token_reserve: int = 1,
            per_call_wall_reserve_milliseconds: int = 91_000,
            transport_factory: TransportFactory | None = None,
            progress_callback: Callable[[Mapping[str, object]], object]
            | None = None):
        if type(seed_secret) is not bytes or len(seed_secret) != 32:
            raise RPCCollectionError("collection seed secret drift")
        if isinstance(per_game_deadline_seconds, bool) \
                or not isinstance(per_game_deadline_seconds, int) \
                or per_game_deadline_seconds <= 90 \
                or isinstance(per_game_token_cap, bool) \
                or not isinstance(per_game_token_cap, int) \
                or per_game_token_cap <= 0 \
                or isinstance(per_call_token_reserve, bool) \
                or not isinstance(per_call_token_reserve, int) \
                or not 0 < per_call_token_reserve <= per_game_token_cap \
                or isinstance(per_call_wall_reserve_milliseconds, bool) \
                or not isinstance(per_call_wall_reserve_milliseconds, int) \
                or not 1_000 <= per_call_wall_reserve_milliseconds \
                <= 1_200_999 \
                or per_call_wall_reserve_milliseconds * 1_000_000 \
                >= per_game_deadline_seconds * 1_000_000_000:
            raise RPCCollectionError("collection game budget drift")
        if type(runtime) is not dict \
                or runtime.get("schema") != RUNTIME_SCHEMA \
                or _strict_sha(runtime.get("boot_identity_sha256"),
                               "collection boot identity") \
                != runtime.get("boot_identity_sha256"):
            raise RPCCollectionError("collection runtime drift")
        self.seed_secret = seed_secret
        self.attempts_root = Path(attempts_root)
        self.attempts_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _validate_private_dir(self.attempts_root, "collection attempt root")
        self.runtime = dict(runtime)
        self.runtime_sha256 = _sha(runtime)
        self.per_game_deadline_ns = per_game_deadline_seconds * 1_000_000_000
        self.per_game_token_cap = per_game_token_cap
        self.per_call_token_reserve = per_call_token_reserve
        self.per_call_wall_reserve_milliseconds = \
            per_call_wall_reserve_milliseconds
        self.per_call_timeout_seconds = (
            per_call_wall_reserve_milliseconds // 1_000)
        self.concurrency = concurrency or RPCConcurrency()
        self.stop_event = stop_event or threading.Event()
        if progress_callback is not None and not callable(progress_callback):
            raise RPCCollectionError("collection progress callback drift")
        self.progress_callback = progress_callback
        self.scientific_budget_provider = scientific_budget_provider
        if scientific_response_acceptor is not None \
                and not callable(scientific_response_acceptor):
            raise RPCCollectionError("scientific response acceptor drift")
        if scientific_dispatch_reserver is not None \
                and not callable(scientific_dispatch_reserver):
            raise RPCCollectionError("scientific dispatch reserver drift")
        for callback, label in (
                (scientific_attempt_reserver, "attempt reserver"),
                (scientific_refusal_settler, "refusal settler"),
                (scientific_journal_response_acceptor,
                 "journal response acceptor")):
            if callback is not None and not callable(callback):
                raise RPCCollectionError(f"scientific {label} drift")
        if scientific_refusal_acceptor is not None \
                and not callable(scientific_refusal_acceptor):
            raise RPCCollectionError("scientific refusal acceptor drift")
        if scientific_terminal_acceptor is not None \
                and not callable(scientific_terminal_acceptor):
            raise RPCCollectionError("scientific terminal acceptor drift")
        supplied = (scientific_budget_provider is not None,
                    scientific_response_acceptor is not None,
                    scientific_dispatch_reserver is not None,
                    scientific_refusal_acceptor is not None,
                    scientific_terminal_acceptor is not None)
        if any(supplied) and not all(supplied):
            raise RPCCollectionError("scientific budget callback population drift")
        attempt_hooks = (scientific_attempt_reserver,
                         scientific_refusal_settler,
                         scientific_journal_response_acceptor)
        if any(hook is not None for hook in attempt_hooks) \
                and not all(hook is not None for hook in attempt_hooks):
            raise RPCCollectionError("scientific attempt callback population drift")
        if all(hook is not None for hook in attempt_hooks) and not all(supplied):
            raise RPCCollectionError("scientific budget callback population drift")
        self.scientific_response_acceptor = scientific_response_acceptor
        self.scientific_dispatch_reserver = scientific_dispatch_reserver
        self.scientific_attempt_reserver = scientific_attempt_reserver
        self.scientific_refusal_settler = scientific_refusal_settler
        self.scientific_journal_response_acceptor = \
            scientific_journal_response_acceptor
        self.scientific_refusal_acceptor = scientific_refusal_acceptor
        self.scientific_terminal_acceptor = scientific_terminal_acceptor
        self.codex_binary: Path | None = None
        self.active_call_manager = None
        if transport_factory is None:
            if codex_binary is None \
                    or runtime_stable_view(source_identity(Path(codex_binary))) \
                    != runtime_stable_view(dict(runtime)):
                raise RPCCollectionError("collection live runtime drift")
            self.codex_binary = Path(codex_binary).resolve()
            catalog = dict(runtime["codex_tool_catalog"])
            counted = _CountingRun(self.concurrency)
            self.active_call_manager = counted.active_calls
            self.transport_factory = lambda temp: CodexExecPlannerTransport(
                codex_binary=Path(codex_binary), temp_root=temp,
                timeout_seconds=self.per_call_timeout_seconds,
                run_command=counted, runtime_attestor=lambda _: dict(catalog),
                policy_mode="play-only")
        else:
            self.transport_factory = transport_factory

    def terminate_active_calls(self) -> None:
        if self.active_call_manager is not None:
            self.active_call_manager.terminate()

    def _emit_progress(self, event: str, journal: FileTurnJournal,
                       absolute_deadline_ns: int) -> None:
        if self.progress_callback is None:
            return
        summary = journal.summary()
        self.progress_callback({
            "event": event,
            "opened_rpc_count": summary["opened_rpc_count"],
            "committed_decision_count": summary[
                "committed_decision_count"],
            "remaining_game_deadline_seconds": max(
                0, absolute_deadline_ns - time.monotonic_ns())
                // 1_000_000_000,
        })

    def _attempt_body(self, coordinate, mirror, root_sha, started):
        body = {"schema": ATTEMPT_SCHEMA, "coordinate": list(coordinate),
                "mirror": mirror, "root_sha256": root_sha,
                "seed_commitment_sha256": hashlib.sha256(
                    self.seed_secret).hexdigest(),
                "runtime_sha256": self.runtime_sha256,
                "boot_identity_sha256": self.runtime["boot_identity_sha256"],
                "started_monotonic_nanoseconds": started,
                "per_game_deadline_nanoseconds": self.per_game_deadline_ns,
                "per_game_token_cap": self.per_game_token_cap,
                "per_call_token_reserve": self.per_call_token_reserve,
                "per_call_wall_reserve_milliseconds":
                    self.per_call_wall_reserve_milliseconds,
                "authority": dict(selfplay.AUTHORITY)}
        return {**body, "attempt_sha256": _sha(body)}

    def _model_budget(self, journal: FileTurnJournal,
                      started: int) -> dict[str, int]:
        usage = journal.usage_totals()
        elapsed = max(0, time.monotonic_ns() - started)
        scientific = (self.scientific_budget_provider()
                      if self.scientific_budget_provider is not None else {
                          "remaining_scientific_wall_ms": max(
                              0, (self.per_game_deadline_ns - elapsed)
                              // 1_000_000),
                          "remaining_scientific_tokens": max(
                              0, self.per_game_token_cap
                              - usage["total_tokens"])})
        return {
            "remaining_game_wall_ms": max(
                0, (self.per_game_deadline_ns - elapsed) // 1_000_000),
            "remaining_game_tokens": max(
                0, self.per_game_token_cap - usage["total_tokens"]),
            "remaining_scientific_wall_ms": int(
                scientific["remaining_scientific_wall_ms"]),
            "remaining_scientific_tokens": int(
                scientific["remaining_scientific_tokens"]),
        }

    def _manifest(self, path: Path, *, status: str,
                  failure_kind: str | None,
                  failure_class: str | None,
                  failure_disposition: FailureDisposition | None = None) \
            -> dict[str, object]:
        attempt = _read(path / "attempt.json")
        files = {
            item.name: _sha_bytes(canonical_json_bytes(_read(item)))
            for item in path.iterdir()
            if item.name != "manifest.json" and not item.is_dir()}
        journal = FileTurnJournal(path / "journal")
        body = {"schema": MANIFEST_SCHEMA, "status": status,
                "coordinate": attempt["coordinate"],
                "mirror": attempt["mirror"],
                "attempt_sha256": attempt["attempt_sha256"],
                "runtime_sha256": attempt["runtime_sha256"],
                "files": files,
                "journal_files": _journal_hashes(path / "journal"),
                "journal_summary": journal.summary(),
                "usage": journal.usage_totals(),
                "failure_kind": failure_kind,
                "failure_class": failure_class,
                "failure_disposition": (None if failure_disposition is None
                                        else failure_disposition.payload()),
                "authority": dict(selfplay.AUTHORITY)}
        return {**body, "manifest_sha256": _sha(body)}

    def _seal_failure(self, path: Path, coordinate, mirror,
                      exc: Exception, *, stage: str) -> None:
        if (path / "manifest.json").exists():
            return
        journal = FileTurnJournal(path / "journal")
        refusal = journal.pending_refusal_disposition()
        persisted_disposition = \
            journal.pending_refusal_failure_disposition()
        if persisted_disposition is None:
            disposition = _failure_disposition(
                exc, stage=stage, journal=journal)
        else:
            progress = journal.summary()
            disposition = FailureDisposition.from_mapping({
                **persisted_disposition,
                "last_opened_rpc_count": int(
                    progress["opened_rpc_count"]),
                "last_committed_decision_count": int(
                    progress["committed_decision_count"]),
            })
        if refusal is not None:
            kind = refusal["failure_kind"]
            failure_class = refusal["failure_class"]
        elif isinstance(exc, SealedTurnRefusal):
            kind = exc.failure_kind
            failure_class = exc.failure_class
        else:
            kind = type(exc).__name__
            failure_class = ("resource-provider"
                             if isinstance(exc, ResourceBoundaryError)
                             or isinstance(exc, CodexProviderResourceError)
                             else "mechanics-privacy")
        if refusal is None:
            refusal = journal.pending_rejected_response_disposition(
                failure_kind=kind, failure_class=failure_class)
        if refusal is None:
            refusal = journal.seal_unknown_disposition()
            if refusal is not None:
                kind = refusal["failure_kind"]
                failure_class = refusal["failure_class"]
        response_acceptor_owner = getattr(
            self.scientific_response_acceptor, "__self__", None)
        ledger_state = None
        if refusal is not None and isinstance(
                response_acceptor_owner, ScientificBudgetLedger):
            try:
                refusal_attempt = AttemptRef.from_mapping(refusal["attempt"])
                ledger_state = response_acceptor_owner.attempt_state(
                    refusal_attempt)
            except Exception as exc:
                raise RPCCollectionError(
                    "scientific refusal attempt drift") from exc
        already_settled = (
            isinstance(exc, SettledResourceBoundaryError)
            or (ledger_state is not None and ledger_state != "reserved"))
        if refusal is not None and self.scientific_refusal_acceptor is not None \
                and not already_settled:
            self.scientific_refusal_acceptor(refusal)
        body = {"schema": FAILURE_SCHEMA, "coordinate": list(coordinate),
                "mirror": mirror, "failure_kind": kind,
                "failure_class": failure_class,
                "failure_disposition": disposition.payload(),
                "failure_fingerprint_sha256": _sha({
                    "failure_kind": kind, "failure_class": failure_class,
                    "failure_disposition": disposition.payload()}),
                "journal_summary_sha256": _sha(journal.summary()),
                "authority": dict(selfplay.AUTHORITY)}
        _publish_or_verify(path / "failure.json",
                           {**body, "artifact_sha256": _sha(body)})
        _publish_or_verify(path / "manifest.json", self._manifest(
            path, status="incomplete", failure_kind=kind,
            failure_class=failure_class,
            failure_disposition=disposition))

    def _finish_interrupted_failure(self, path: Path, coordinate, mirror) \
            -> None:
        """Finish only the manifest half of an already sealed failure."""
        failure = _read(path / "failure.json")
        keys = {"schema", "coordinate", "mirror", "failure_kind",
                "failure_class", "failure_fingerprint_sha256",
                "failure_disposition",
                "journal_summary_sha256", "authority", "artifact_sha256"}
        body = {key: value for key, value in failure.items()
                if key != "artifact_sha256"}
        if set(failure) != keys or failure.get("schema") != FAILURE_SCHEMA \
                or failure.get("coordinate") != list(coordinate) \
                or failure.get("mirror") != mirror \
                or failure.get("authority") != selfplay.AUTHORITY \
                or failure.get("failure_class") not in {
                    "mechanics-privacy", "resource-provider"} \
                or FailureDisposition.from_mapping(
                    failure.get("failure_disposition")).payload() \
                    != failure.get("failure_disposition") \
                or failure.get("failure_fingerprint_sha256") != _sha({
                    "failure_kind": failure.get("failure_kind"),
                    "failure_class": failure.get("failure_class"),
                    "failure_disposition": failure.get(
                        "failure_disposition")}) \
                or failure.get("artifact_sha256") != _sha(body) \
                or failure.get("journal_summary_sha256") != _sha(
                    FileTurnJournal(path / "journal").summary()):
            raise RPCCollectionError("interrupted game failure drift")
        _publish_or_verify(path / "manifest.json", self._manifest(
            path, status="incomplete",
            failure_kind=failure["failure_kind"],
            failure_class=failure["failure_class"],
            failure_disposition=FailureDisposition.from_mapping(
                failure["failure_disposition"])))

    def __call__(self, coordinate: tuple[str, int, int], mirror: int) \
            -> selfplay.CompletedGameArtifacts:
        # A game-level refusal belongs to this schedule item.  The population
        # supervisor decides whether queued work should start; it must not use
        # this shared event to abort independent games that are already in
        # flight.  The event is reserved for controller/global cancellation.
        return self._run_game(coordinate, mirror)

    def _run_game(self, coordinate: tuple[str, int, int], mirror: int) \
            -> selfplay.CompletedGameArtifacts:
        name = _attempt_name(coordinate, mirror)
        path = self.attempts_root / name
        if path.exists() or path.is_symlink():
            _validate_private_dir(path, "game attempt directory")
        if (path / "manifest.json").is_file():
            result = reopen_attempt(
                path, seed_secret=self.seed_secret,
                expected_runtime_sha256=self.runtime_sha256,
                expected_coordinate=coordinate, expected_mirror=mirror)
            if result.artifacts is None:
                raise RPCCollectionError("sealed game attempt is incomplete")
            return result.artifacts
        if self.stop_event.is_set() and not path.exists():
            raise RPCCollectionError("collection stopped before game attempt")
        root = selfplay.build_root(self.seed_secret, coordinate, mirror=mirror)
        root_sha = selfplay.root_identity(root)
        if not path.exists():
            path.mkdir(mode=0o700)
            _fsync_dir(self.attempts_root)
            started = time.monotonic_ns()
            _publish(path / "attempt.json", self._attempt_body(
                coordinate, mirror, root_sha, started))
        else:
            attempt = _read(path / "attempt.json")
            started = attempt.get("started_monotonic_nanoseconds")
            if attempt != self._attempt_body(
                    coordinate, mirror, root_sha, started):
                raise RPCCollectionError("resumed game attempt drift")
        if self.runtime.get("boot_identity_sha256") \
                != _read(path / "attempt.json")["boot_identity_sha256"]:
            raise RPCCollectionError("resumed game boot identity drift")
        journal = FileTurnJournal(path / "journal")
        if (path / "failure.json").is_file():
            self._finish_interrupted_failure(path, coordinate, mirror)
            raise RPCCollectionError("sealed game attempt is incomplete")
        pending_refusal = journal.pending_refusal_disposition()
        if pending_refusal is not None:
            refusal = SealedTurnRefusal(
                pending_refusal["failure_kind"],
                pending_refusal["failure_class"])
            try:
                pending_attempt = AttemptRef.from_mapping(
                    pending_refusal["attempt"])
            except Exception as exc:
                raise RPCCollectionError(
                    "sealed refusal attempt drift") from exc
            # An eligible refusal is deliberately left resumable: the next
            # driver step settles that exact physical attempt idempotently
            # and opens only ordinal + 1.  Unknown, ineligible, and exhausted
            # refusals remain terminal and never redispatch.
            if (pending_refusal["redispatch_eligibility"]
                    not in REDISPATCH_ELIGIBILITIES
                    or pending_attempt.attempt_ordinal >= 2):
                self._seal_failure(
                    path, coordinate, mirror, refusal,
                    stage="provider-response")
                raise RPCCollectionError("sealed game attempt is incomplete") \
                    from refusal
        game = selfplay.LunaSelfPlayGame(
            root, coordinate=coordinate, mirror=mirror,
            seed_secret=self.seed_secret)
        absolute_deadline_ns = started + self.per_game_deadline_ns
        stage = "dispatch"
        try:
            if self.codex_binary is not None \
                    and runtime_stable_view(source_identity(self.codex_binary)) \
                    != runtime_stable_view(self.runtime):
                raise RPCCollectionError("collection live runtime drift")
            transport = _DeadlineTransport(
                self.transport_factory(path),
                lambda: absolute_deadline_ns,
                lambda event: self._emit_progress(
                    event, journal, absolute_deadline_ns),
                configure_inner_deadline=self.codex_binary is not None)
        except Exception as exc:
            game.fail(type(exc).__name__)
            self._seal_failure(
                path, coordinate, mirror, exc, stage="dispatch")
            raise RPCCollectionError("game attempt refused") from exc
        budget = lambda: (journal.pending_model_budget()
                          or self._model_budget(journal, started))
        def accept_usage(_usage) -> None:
            current = journal.usage_totals()
            if current["total_tokens"] > self.per_game_token_cap:
                raise ResourceBoundaryError("game token cap crossed")
            if time.monotonic_ns() - started > self.per_game_deadline_ns:
                raise ResourceBoundaryError("game deadline crossed")
            remaining = self._model_budget(journal, started)
            if remaining["remaining_scientific_tokens"] < 0 \
                    or remaining["remaining_scientific_wall_ms"] < 0:
                raise ResourceBoundaryError("scientific budget crossed")
        def reserve_dispatch(packet: DecisionPacket) -> None:
            owner = getattr(
                self.scientific_dispatch_reserver, "__self__", None)
            try:
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped before provider dispatch")
                if self.scientific_dispatch_reserver is not None:
                    self.scientific_dispatch_reserver(packet)
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped during provider admission")
            except Exception:
                if isinstance(owner, ScientificBudgetLedger):
                    owner.cancel(packet)
                raise
        def reserve_attempt(packet: DecisionPacket, attempt: AttemptRef) -> None:
            owner = getattr(
                self.scientific_attempt_reserver, "__self__", None)
            try:
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped before provider dispatch")
                if self.scientific_attempt_reserver is None:
                    raise ResourceBoundaryError(
                        "scientific attempt reserver absent")
                self.scientific_attempt_reserver(packet, attempt)
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped during provider admission")
            except Exception:
                if isinstance(owner, ScientificBudgetLedger):
                    owner.cancel(packet, attempt)
                raise
        try:
            driver = TurnDriver(
                game, transport, journal=journal,
                budget_provider=budget, usage_acceptor=accept_usage,
                response_acceptor=self.scientific_response_acceptor,
                dispatch_reserver=(reserve_dispatch
                                   if self.scientific_dispatch_reserver
                                   is not None else None),
                attempt_reserver=(reserve_attempt
                                  if self.scientific_attempt_reserver is not None
                                  else None),
                refusal_settler=self.scientific_refusal_settler,
                journal_response_acceptor=
                    self.scientific_journal_response_acceptor)
            while not game.complete and game.failed is None:
                if self.stop_event.is_set():
                    raise ResourceBoundaryError(
                        "collection stopped after peer failure")
                remaining = self.per_game_deadline_ns - (
                    time.monotonic_ns() - started)
                if remaining <= \
                        self.per_call_wall_reserve_milliseconds * 1_000_000:
                    raise ResourceBoundaryError(
                        "game deadline admission refused")
                if journal.pending_model_budget() is None \
                        and journal.usage_totals()["total_tokens"] \
                        + self.per_call_token_reserve > self.per_game_token_cap:
                    raise ResourceBoundaryError("game token admission refused")
                stage = "dispatch"
                driver.step()
                stage = "journal-commit"
                self._emit_progress(
                    "transition-commit", journal, absolute_deadline_ns)
                if time.monotonic_ns() >= absolute_deadline_ns:
                    raise ResourceBoundaryError(
                        "game terminal deadline crossed")
                if self.scientific_terminal_acceptor is not None:
                    self.scientific_terminal_acceptor()
            if not game.complete or game.failed is not None:
                raise RPCCollectionError("game did not complete")
            stage = "terminal-verification"
            if time.monotonic_ns() >= absolute_deadline_ns:
                raise ResourceBoundaryError("game terminal deadline crossed")
            if self.scientific_terminal_acceptor is not None:
                self.scientific_terminal_acceptor()
            artifacts = game.completed_artifacts()
            summary = journal.summary()
            if summary["private_evidence_count"] != summary["call_count"] \
                    or summary["committed_call_count"] != summary["call_count"]:
                raise RPCCollectionError("game provider evidence incomplete")
            evidence_body = {"schema": EVIDENCE_SCHEMA,
                             "rows": [row.payload()
                                      for row in driver.evidence]}
            _publish_or_verify(path / "evidence.json", {**evidence_body,
                               "evidence_sha256": _sha(evidence_body)})
            _publish_or_verify(path / "trajectory.json",
                               json.loads(artifacts.trajectory.private_bytes()))
            _publish_or_verify(path / "terminal.json",
                               artifacts.terminal_receipt.payload())
            if self.codex_binary is not None \
                    and source_identity(self.codex_binary) != self.runtime:
                raise RPCCollectionError("collection terminal runtime drift")
            _publish(path / "manifest.json", self._manifest(
                path, status="complete", failure_kind=None,
                failure_class=None))
            self._emit_progress(
                "game-complete", journal, absolute_deadline_ns)
            reopened = reopen_attempt(
                path, seed_secret=self.seed_secret,
                expected_runtime_sha256=self.runtime_sha256,
                expected_coordinate=coordinate, expected_mirror=mirror)
            if reopened.artifacts is None:
                raise RPCCollectionError("completed game failed reopen")
            return reopened.artifacts
        except Exception as exc:
            game.fail(type(exc).__name__)
            self._seal_failure(
                path, coordinate, mirror, exc, stage=stage)
            self._emit_progress(
                "game-failure", journal, absolute_deadline_ns)
            raise RPCCollectionError("game attempt refused") from exc


__all__ = ["ATTEMPT_SCHEMA", "AttemptReopen", "EVIDENCE_SCHEMA",
           "FAILURE_SCHEMA", "MANIFEST_SCHEMA", "RPCCollectionError",
           "RPCGameAttemptRunner", "ResourceBoundaryError",
           "SettledResourceBoundaryError",
           "ScientificBudgetLedger", "reopen_attempt"]
