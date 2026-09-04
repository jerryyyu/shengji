"""Durable population supervisor for the PT-Luna turn-RPC collector.

The supervisor is deliberately boring: it derives the schedule and census
from the seed secret, publishes those facts before opening a provider, and
then only coordinates independent :class:`RPCGameAttemptRunner` calls.  Game
contents and outcomes remain below the private boundary; public progress
contains hashes, counts, and resource telemetry only.
"""

from __future__ import annotations

from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import time
from typing import Mapping, Sequence

from . import game as selfplay
from .attempt import (
    AttemptReopen, RPCGameAttemptRunner, reopen_attempt,
)
from .ledger import (
    ResourceBoundaryError, RPCCollectionError, ScientificBudgetLedger,
)
from .atomic_io import (
    AtomicPublishError, publish_exclusive_bytes, recover_linked_partial,
)
from .turn import TurnRPCError
from .canonical import canonical_json_bytes


SCHEMA = "pt-luna-turn-rpc-supervisor-v4"
CENSUS_SCHEMA = "pt-luna-turn-rpc-supervisor-census-v2"
PROGRESS_SCHEMA = "pt-luna-turn-rpc-progress-v3"
TERMINAL_SCHEMA = "pt-luna-turn-rpc-terminal-v3"
CONTROLLER_REFUSAL_SCHEMA = "pt-luna-turn-rpc-controller-refusal-v2"
DEFAULT_WORKERS = 4
DEFAULT_GAME_DEADLINE_SECONDS = 1_800
DEFAULT_WALL_SECONDS = 12_000
DEFAULT_PER_CALL_WALL_RESERVE_MS = 91_000
DEFAULT_PER_CALL_TOKEN_RESERVE = 100_000
DEFAULT_PER_GAME_TOKEN_CAP = 2_000_000
ROUTES = (
    selfplay.COMPLETE_ROUTE,
    "REFUSE_MECHANICS_OR_PRIVACY",
    "REFUSE_RESOURCE_OR_PROVIDER",
    selfplay.INCOMPLETE_ROUTE,
)
COMPLETE_STATE_SOURCE_ACQUISITION = selfplay.COMPLETE_ROUTE
REFUSE_MECHANICS_OR_PRIVACY = "REFUSE_MECHANICS_OR_PRIVACY"
REFUSE_RESOURCE_OR_PROVIDER = "REFUSE_RESOURCE_OR_PROVIDER"
INCOMPLETE_STATE_SOURCE_ACQUISITION = selfplay.INCOMPLETE_ROUTE
_PUBLIC_FORBIDDEN = frozenset({
    "score", "scores", "outcome", "outcomes", "utility",
    "signed_level_utility", "attacker_points", "kitty_bonus", "winner",
    "winners", "trajectory", "hands", "burial", "prompt", "response",
    "model_output", "model_prose", "prose", "reasoning",
})


class RPCSupervisorError(ValueError):
    """A supervisor input or durable receipt is invalid."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise RPCSupervisorError(f"{label} drift")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RPCSupervisorError(f"{label} drift")
    return value


def _acquire_run_lock(private_root: Path) -> int:
    """Hold one exclusive controller per private root for the run's duration."""
    path = Path(private_root) / "run.lock"
    descriptor = os.open(
        path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise RPCSupervisorError("run lock identity drift")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RPCSupervisorError("run root already active") from exc
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _private_dir(path: Path, label: str) -> None:
    try:
        value = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RPCSupervisorError(f"{label} drift") from exc
    if (path.is_symlink() or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.getuid() or stat.S_IMODE(value.st_mode) != 0o700):
        raise RPCSupervisorError(f"{label} drift")


def _mkdir_private(path: Path, label: str) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_dir(path, label)


def _publish(path: Path, value: object, *, mode: int = 0o400) -> None:
    raw = canonical_json_bytes(value)
    try:
        publish_exclusive_bytes(
            path, raw, mode=mode, existing_equal_ok=True,
            repair_incomplete_partial=True)
    except AtomicPublishError as exc:
        raise RPCSupervisorError("immutable supervisor receipt drift") from exc


def _attempt_path(root: Path, coordinate: tuple[str, int, int], mirror: int) -> Path:
    return root / f"{coordinate[0]}-{coordinate[1]}-{coordinate[2]}-mirror-{mirror}"


def _read_sealed(path: Path, *, label: str) -> dict[str, object]:
    """Read one immutable canonical JSON artifact (0o400, single link)."""
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            if before.st_size > 16 << 20:
                raise RPCSupervisorError(f"{label} size drift")
            chunks = []
            while True:
                chunk = os.read(descriptor, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RPCSupervisorError(f"{label} reopen failed") from exc
    identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o400
            or any(getattr(before, key) != getattr(after, key)
                   for key in identity)
            or type(value) is not dict
            or canonical_json_bytes(value) != raw):
        raise RPCSupervisorError(f"{label} canonical bytes drift")
    return value


def validate_schedule(
        schedule: Sequence[tuple[tuple[str, int, int], int]],
) -> tuple[tuple[tuple[str, int, int], int], ...]:
    """Validate an ordered, duplicate-free cluster/mirror schedule."""
    actual = tuple(schedule)
    if not actual or len(actual) != len(set(actual)):
        raise RPCSupervisorError("schedule uniqueness drift")
    for coordinate, mirror in actual:
        try:
            if type(coordinate) is not tuple or len(coordinate) != 3 \
                    or isinstance(mirror, bool):
                raise RPCSupervisorError("schedule coordinate drift")
            selfplay.LunaCoordinate(*coordinate)
            selfplay.agent_team_assignment(mirror)
        except Exception as exc:
            raise RPCSupervisorError("schedule coordinate drift") from exc
    return actual


def schedule_for_games(
        seed_secret: bytes, games: int,
) -> tuple[tuple[tuple[str, int, int], int], ...]:
    """Select ``games // 2`` clusters by ascending root hash, both mirrors each.

    The census of all 52 fresh roots is derived from the seed secret, sorted
    by root identity (so the selection is unpredictable without the secret
    yet fully deterministic given it), and the first ``games // 2`` clusters
    are scheduled with mirror 0 then mirror 1.
    """
    if type(seed_secret) is not bytes or len(seed_secret) != 32:
        raise RPCSupervisorError("seed secret drift")
    population = len(selfplay.mirrored_assignments())
    if isinstance(games, bool) or not isinstance(games, int) \
            or games <= 0 or games % 2 or games > population:
        raise RPCSupervisorError(
            f"game count must be even and within 2..{population}")
    rows = selfplay.root_census(seed_secret).serialized()["coordinates"]
    ordered = sorted(
        rows, key=lambda row: (row["root_sha256"], tuple(row["coordinate"])))
    coordinates = [selfplay.LunaCoordinate(*row["coordinate"]).cluster_key
                   for row in ordered[:games // 2]]
    return validate_schedule(tuple(
        (coordinate, mirror)
        for coordinate in coordinates for mirror in selfplay.MIRRORS))


def build_root_census(
        seed_secret: bytes,
        schedule: Sequence[tuple[tuple[str, int, int], int]],
) -> dict[str, object]:
    """Build a score-free root census for exactly the scheduled clusters."""
    if type(seed_secret) is not bytes or len(seed_secret) != 32:
        raise RPCSupervisorError("seed secret drift")
    clusters = []
    seen: set[tuple[str, int, int]] = set()
    for coordinate, _mirror in schedule:
        if coordinate in seen:
            continue
        seen.add(coordinate)
        root = selfplay.build_root(seed_secret, coordinate)
        mirror = selfplay.build_root(seed_secret, coordinate, mirror=1)
        root_sha = selfplay.root_identity(root)
        mirror_sha = selfplay.root_identity(mirror)
        if root_sha != mirror_sha:
            raise RPCSupervisorError("mirror root identity drift")
        clusters.append({"coordinate": list(coordinate), "root_sha256": root_sha,
                         "mirror_root_sha256": mirror_sha,
                         "mode": selfplay.root_trump_mode(root)})
    body = {"schema": CENSUS_SCHEMA,
            "seed_commitment_sha256": _sha_bytes(seed_secret),
            "coordinates": clusters, "coordinate_count": len(clusters),
            "game_count": len(schedule)}
    return {**body, "census_sha256": _sha(body)}


def validate_root_census(
        census: Mapping[str, object], seed_secret: bytes,
        schedule: Sequence[tuple[tuple[str, int, int], int]],
) -> str:
    if type(census) is not dict or census.get("schema") != CENSUS_SCHEMA:
        raise RPCSupervisorError("root census schema drift")
    body = {key: value for key, value in census.items() if key != "census_sha256"}
    _strict_sha(census.get("census_sha256"), "root census")
    if census["census_sha256"] != _sha(body):
        raise RPCSupervisorError("root census hash drift")
    if census.get("seed_commitment_sha256") != _sha_bytes(seed_secret):
        raise RPCSupervisorError("root census seed drift")
    expected = list(dict.fromkeys(coordinate for coordinate, _ in schedule))
    rows = census.get("coordinates")
    if (type(rows) is not list or census.get("coordinate_count") != len(rows)
            or census.get("game_count") != len(schedule)
            or [tuple(row.get("coordinate", ())) for row in rows] != expected):
        raise RPCSupervisorError("root census coverage drift")
    for row, coordinate in zip(rows, expected):
        if (set(row) != {"coordinate", "root_sha256", "mirror_root_sha256", "mode"}
                or tuple(row["coordinate"]) != coordinate
                or row["root_sha256"] != row["mirror_root_sha256"]):
            raise RPCSupervisorError("root census row drift")
        _strict_sha(row["root_sha256"], "root census root")
    return census["census_sha256"]


def _schedule_sha(
        schedule: Sequence[tuple[tuple[str, int, int], int]]) -> str:
    return _sha([[list(coordinate), mirror]
                 for coordinate, mirror in schedule])


def _forbidden(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(str(key).lower() in _PUBLIC_FORBIDDEN or _forbidden(child)
                   for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_forbidden(child) for child in value)
    return False


def validate_terminal_receipt(receipt: Mapping[str, object]) -> None:
    """Validate a public terminal receipt without opening private artifacts."""
    if type(receipt) is not dict:
        raise RPCSupervisorError("terminal receipt schema drift")
    body = {key: value for key, value in receipt.items()
            if key != "receipt_sha256"}
    if (set(receipt) != {"schema", "route", "schedule_sha256", "census_sha256",
                         "runtime_sha256", "attempt_manifest",
                         "completed_games", "completed_deal_clusters",
                         "failed_games", "pending_games", "resource_totals",
                         "ledger_terminal_accept_sha256", "receipt_sha256"}
            or receipt.get("schema") != TERMINAL_SCHEMA
            or receipt.get("route") not in ROUTES
            or receipt.get("receipt_sha256") != _sha(body)
            or _forbidden(receipt)):
        raise RPCSupervisorError("terminal receipt schema drift")
    terminal_accept = receipt["ledger_terminal_accept_sha256"]
    if terminal_accept is not None:
        _strict_sha(terminal_accept, "terminal ledger acceptance")
    for key in ("schedule_sha256", "census_sha256", "runtime_sha256",
                "receipt_sha256"):
        _strict_sha(receipt[key], f"terminal {key}")
    rows = receipt["attempt_manifest"]
    if type(rows) is not list:
        raise RPCSupervisorError("terminal attempt manifest drift")
    for index, row in enumerate(rows):
        if (type(row) is not dict
                or set(row) != {"index", "coordinate", "mirror", "status",
                                 "manifest_sha256"}
                or row["index"] != index
                or row["status"] not in {None, "complete", "incomplete"}):
            raise RPCSupervisorError("terminal attempt manifest drift")
        if row["manifest_sha256"] is not None:
            _strict_sha(row["manifest_sha256"], "terminal manifest SHA")
    if any(isinstance(receipt[key], bool) or not isinstance(receipt[key], int)
           or receipt[key] < 0 for key in (
               "completed_games", "completed_deal_clusters", "failed_games",
               "pending_games")):
        raise RPCSupervisorError("terminal count drift")
    if receipt["completed_games"] + receipt["failed_games"] \
            + receipt["pending_games"] != len(rows):
        raise RPCSupervisorError("terminal count derivation drift")
    if receipt["route"] == COMPLETE_STATE_SOURCE_ACQUISITION \
            and (receipt["completed_games"] != len(rows)
                 or receipt["failed_games"] or receipt["pending_games"]):
        raise RPCSupervisorError("complete terminal count drift")
    if receipt["route"] == INCOMPLETE_STATE_SOURCE_ACQUISITION \
            and not (receipt["failed_games"] or receipt["pending_games"]):
        raise RPCSupervisorError("incomplete terminal count drift")


@dataclass(frozen=True)
class SupervisorResult:
    route: str
    receipt: Mapping[str, object]


class PTLunaRPCSupervisor:
    """Coordinate one seeded schedule of games and its restartable run.

    Two construction modes exist.  A live run passes ``codex_binary`` plus
    plain budget arguments and the supervisor owns its ledger and runner
    under ``private_root``.  Tests inject ``runner`` (and optionally
    ``ledger``) instead; the two modes are mutually exclusive.
    """

    def __init__(
            self, *, seed_secret: bytes, private_root: Path, public_root: Path,
            runtime: Mapping[str, object],
            schedule: Sequence[tuple[tuple[str, int, int], int]],
            root_census: Mapping[str, object] | None = None,
            runner: RPCGameAttemptRunner | None = None,
            ledger: ScientificBudgetLedger | None = None,
            codex_binary: Path | None = None,
            workers: int = DEFAULT_WORKERS,
            token_cap: int | None = None,
            per_game_token_cap: int = DEFAULT_PER_GAME_TOKEN_CAP,
            per_call_token_reserve: int = DEFAULT_PER_CALL_TOKEN_RESERVE,
            per_call_wall_reserve_milliseconds: int =
                DEFAULT_PER_CALL_WALL_RESERVE_MS,
            per_game_deadline_seconds: int = DEFAULT_GAME_DEADLINE_SECONDS,
            wall_seconds: int = DEFAULT_WALL_SECONDS,
            ledger_namespace: str = SCHEMA):
        if type(seed_secret) is not bytes or len(seed_secret) != 32:
            raise RPCSupervisorError("seed secret drift")
        if type(runtime) is not dict or not runtime:
            raise RPCSupervisorError("runtime identity drift")
        if type(ledger_namespace) is not str or not ledger_namespace \
                or len(ledger_namespace) > 256:
            raise RPCSupervisorError("ledger namespace drift")
        self.seed_secret = seed_secret
        self.private_root = Path(private_root)
        self.public_root = Path(public_root)
        self.runtime = dict(runtime)
        self.schedule = validate_schedule(schedule)
        census = (build_root_census(seed_secret, self.schedule)
                  if root_census is None else dict(root_census))
        self.census_sha256 = validate_root_census(census, seed_secret, self.schedule)
        self.census = census
        self.workers = _positive(workers, "worker count")
        self._run_lock_fd: int | None = None
        if codex_binary is not None:
            if runner is not None or ledger is not None:
                raise RPCSupervisorError(
                    "a live run owns its runner and ledger internally")
            for value, label in (
                    (token_cap, "token cap"),
                    (per_game_token_cap, "per-game token cap"),
                    (per_call_token_reserve, "per-call token reserve"),
                    (per_call_wall_reserve_milliseconds,
                     "per-call wall reserve"),
                    (per_game_deadline_seconds, "per-game deadline"),
                    (wall_seconds, "wall")):
                _positive(value, label)
            _mkdir_private(self.private_root, "private supervisor root")
            ledger = ScientificBudgetLedger.open_or_create(
                root=self.private_root / "ledger",
                wall_nanoseconds=wall_seconds * 1_000_000_000,
                token_cap=token_cap,
                per_call_token_reserve=per_call_token_reserve,
                per_call_wall_reserve_milliseconds=
                    per_call_wall_reserve_milliseconds,
                boot_identity_sha256=runtime["boot_identity_sha256"],
                runtime_sha256=_sha(runtime),
                namespace=ledger_namespace)
            runner = RPCGameAttemptRunner(
                seed_secret=seed_secret,
                attempts_root=self.private_root / "attempts",
                codex_binary=codex_binary, runtime=runtime,
                per_game_deadline_seconds=per_game_deadline_seconds,
                per_game_token_cap=per_game_token_cap,
                per_call_token_reserve=per_call_token_reserve,
                per_call_wall_reserve_milliseconds=
                    per_call_wall_reserve_milliseconds,
                stop_event=threading.Event())
        elif runner is None:
            raise RPCSupervisorError("injected runner required")
        self.runner = runner
        self.ledger = ledger
        if self.ledger is not None and (
                self.ledger.root.resolve()
                != self.private_root.resolve() / "ledger"
                or self.ledger.namespace != ledger_namespace):
            raise RPCSupervisorError("ledger binding drift")
        _mkdir_private(self.private_root, "private supervisor root")
        self.public_root.mkdir(mode=0o755, parents=True, exist_ok=True)
        if self.public_root.is_symlink() or not self.public_root.is_dir():
            raise RPCSupervisorError("public supervisor root drift")
        self.stop_event = getattr(runner, "stop_event", None) or threading.Event()
        if hasattr(runner, "stop_event"):
            runner.stop_event = self.stop_event
        self._lock = threading.Lock()
        self._progress_lock = threading.Lock()
        # Construction is deliberately side-effect-compatible with restart.
        # The cross-process lock is acquired only when run() starts: a
        # constructor refusal must never leak a descriptor and poison a valid
        # fresh-process restart.  The local guard also prevents two threads
        # from dispatching the same pending population through one instance.
        self._run_state_lock = threading.Lock()
        self._started_ns = time.monotonic_ns()
        self._statuses: dict[tuple[tuple[str, int, int], int], AttemptReopen | None] = {}
        self._errors: dict[tuple[tuple[str, int, int], int], BaseException] = {}
        progress_dir = self.private_root / "progress"
        if progress_dir.is_dir():
            names = [item.name[:-5] for item in progress_dir.iterdir()
                     if item.is_file() and item.name.endswith(".json")]
            if any(not name.isdigit() for name in names):
                raise RPCSupervisorError("progress file population drift")
            self._progress_index = (max((int(name) for name in names),
                                        default=-1) + 1)
        else:
            self._progress_index = 0
        self._active_games = 0
        self._wire_ledger()
        self._wire_progress()

    def _wire_ledger(self) -> None:
        if self.ledger is None:
            return
        callbacks = {
            "scientific_budget_provider": self.ledger.snapshot,
            "scientific_response_acceptor": self.ledger.accept,
            "scientific_dispatch_reserver": self.ledger.reserve,
            "scientific_attempt_reserver": self.ledger.reserve,
            "scientific_refusal_settler": self.ledger.refuse,
            "scientific_journal_response_acceptor":
                self.ledger.accept_attempt,
            "scientific_terminal_acceptor": self.ledger.assert_within_limits,
        }
        refusal = getattr(self.ledger, "refuse", None)
        if callable(refusal):
            callbacks["scientific_refusal_acceptor"] = refusal
        for name, callback in callbacks.items():
            current = getattr(self.runner, name, None)
            same_ledger = (getattr(current, "__self__", None) is self.ledger
                           and getattr(current, "__func__", None)
                           is getattr(callback, "__func__", None))
            if current is not None and not same_ledger:
                # A runner with a different global ledger is unsafe to admit.
                raise RPCSupervisorError("global ledger hook drift")
            else:
                setattr(self.runner, name, callback)

    def _wire_progress(self) -> None:
        current = getattr(self.runner, "progress_callback", None)
        if current is not None:
            same = (getattr(current, "__self__", None) is self
                    and getattr(current, "__func__", None)
                    is getattr(self._runner_progress, "__func__", None))
            if not same:
                raise RPCSupervisorError("runner progress hook drift")
        setattr(self.runner, "progress_callback", self._runner_progress)

    def _runner_progress(self, row: Mapping[str, object]) -> None:
        expected = {"event", "opened_rpc_count", "committed_decision_count",
                    "remaining_game_deadline_seconds"}
        if type(row) is not dict or set(row) != expected \
                or row["event"] not in {
                    "rpc-start", "rpc-end", "transition-commit",
                    "game-complete", "game-failure"}:
            raise RPCSupervisorError("runner progress event drift")
        with self._lock:
            active_games = self._active_games
        self._progress(
            active_workers=active_games, active_rpcs=self._active_rpcs(),
            opened_rpc_count=int(row["opened_rpc_count"]),
            committed_decision_count=int(row["committed_decision_count"]),
            remaining_game_deadline_seconds=int(
                row["remaining_game_deadline_seconds"]))

    def _terminate_active_calls(self) -> None:
        terminate = getattr(self.runner, "terminate_active_calls", None)
        if callable(terminate):
            terminate()

    @property
    def attempts_root(self) -> Path:
        root = getattr(self.runner, "attempts_root", None)
        return Path(root) if root is not None else self.private_root / "attempts"

    def _publish_launch(self) -> None:
        """Publish the seed-derived launch facts before any provider call."""
        _publish(self.private_root / "census.json", self.census)
        _publish(self.private_root / "runtime.json", self.runtime)

    def _reopen_one(self, coordinate, mirror) -> AttemptReopen | None:
        path = _attempt_path(self.attempts_root, coordinate, mirror)
        if not path.exists():
            return None
        try:
            return reopen_attempt(path, seed_secret=self.seed_secret,
                                  expected_runtime_sha256=getattr(
                                      self.runner, "runtime_sha256", None),
                                  expected_coordinate=coordinate,
                                  expected_mirror=mirror)
        except Exception as exc:
            self._errors[(coordinate, mirror)] = exc
            return None

    def _controller_refusal_path(self, coordinate, mirror) -> Path:
        return (_attempt_path(self.attempts_root, coordinate, mirror)
                / "controller-refusal.json")

    def _record_preseal_mechanics_refusal(
            self, coordinate, mirror, exc: BaseException) -> None:
        """Seal deterministic attempt corruption that no game manifest can bind."""
        if not isinstance(exc, (RPCCollectionError, TurnRPCError)):
            return
        attempt = _attempt_path(self.attempts_root, coordinate, mirror)
        manifest = attempt / "manifest.json"
        if not attempt.is_dir() or attempt.is_symlink() \
                or manifest.exists() or manifest.is_symlink():
            return
        body = {
            "schema": CONTROLLER_REFUSAL_SCHEMA,
            "coordinate": list(coordinate), "mirror": mirror,
            "failure_kind": type(exc).__name__,
            "failure_class": "mechanics-privacy",
            "failure_fingerprint_sha256": _sha({
                "failure_kind": type(exc).__name__,
                "failure_class": "mechanics-privacy"}),
        }
        _publish(self._controller_refusal_path(coordinate, mirror), {
            **body, "artifact_sha256": _sha(body)})

    def _has_controller_refusal(self, coordinate, mirror) -> bool:
        path = self._controller_refusal_path(coordinate, mirror)
        return path.exists() or path.is_symlink()

    def _load_existing(self) -> None:
        for coordinate, mirror in self.schedule:
            path = _attempt_path(self.attempts_root, coordinate, mirror)
            if not path.exists():
                continue
            # A durable partial without a manifest is resumable by the
            # per-game journal.  A present but invalid manifest is not retried.
            manifest = path / "manifest.json"
            if not (manifest.exists() or manifest.is_symlink()):
                continue
            self._statuses[(coordinate, mirror)] = self._reopen_one(
                coordinate, mirror)

    def _resource_totals(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for result in self._statuses.values():
            if result is None:
                continue
            for key, value in result.usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[f"total_{key}"] = totals.get(f"total_{key}", 0) + value
        if self.ledger is not None:
            payload = self.ledger.payload()
            for key in ("spent_tokens", "reserved_call_count", "accepted_response_count"):
                totals[f"ledger_{key}"] = int(payload[key])
        return totals

    def _progress(self, *, active_workers: int, active_rpcs: int,
                  opened_rpc_count: int = 0,
                  committed_decision_count: int = 0,
                  remaining_game_deadline_seconds: int | None = None) -> None:
        with self._progress_lock:
            self._publish_progress(
                active_workers=active_workers, active_rpcs=active_rpcs,
                opened_rpc_count=opened_rpc_count,
                committed_decision_count=committed_decision_count,
                remaining_game_deadline_seconds=
                    remaining_game_deadline_seconds)

    def _publish_progress(self, *, active_workers: int, active_rpcs: int,
                          opened_rpc_count: int,
                          committed_decision_count: int,
                          remaining_game_deadline_seconds: int | None) -> None:
        completed = sum(result is not None and result.status == "complete"
                        for result in self._statuses.values())
        failed = sum(result is not None and result.status == "incomplete"
                     for result in self._statuses.values())
        clusters = {coordinate for coordinate, _ in self.schedule}
        completed_clusters = sum(
            all(self._statuses.get((coordinate, mirror)) is not None
                and self._statuses[(coordinate, mirror)].status == "complete"
                for item_coordinate, mirror in self.schedule
                if item_coordinate == coordinate)
            for coordinate in clusters)
        elapsed = max(1, time.monotonic_ns() - self._started_ns)
        throughput = completed * 3_600_000 * 1_000_000_000 // elapsed
        remaining = max(0, len(self.schedule) - completed - failed)
        body = {"schema": PROGRESS_SCHEMA, "sequence": self._progress_index,
                "completed_games": completed,
                "completed_deal_clusters": completed_clusters,
                "planned_games": len(self.schedule),
                "planned_deal_clusters": len({coordinate for coordinate, _ in self.schedule}),
                "failed_games": failed,
                "active_games": active_workers,
                "pending_games": remaining,
                "percent_basis_points": (completed * 10_000 // len(self.schedule)),
                "elapsed_seconds": elapsed // 1_000_000_000,
                "recent_throughput": throughput,
                "eta_seconds": (None if not throughput else
                                (remaining * 3_600_000 + throughput - 1)
                                // throughput),
                "active_game_workers": active_workers,
                "active_model_rpcs": active_rpcs,
                "opened_rpc_count": opened_rpc_count,
                "committed_decision_count": committed_decision_count,
                "remaining_game_deadline_seconds":
                    remaining_game_deadline_seconds,
                "failure_count": failed,
                "resource_totals": self._resource_totals()}
        if _forbidden(body):
            raise RPCSupervisorError("public progress privacy drift")
        progress_dir = self.private_root / "progress"
        _mkdir_private(progress_dir, "private progress root")
        _publish(progress_dir / f"{self._progress_index:012d}.json", body)
        public_dir = self.public_root / "progress"
        public_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
        _publish(public_dir / f"{self._progress_index:012d}.json", body)
        self._progress_index += 1

    def _run_one(self, coordinate, mirror):
        with self._lock:
            self._active_games += 1
        try:
            return self.runner(coordinate, mirror)
        finally:
            with self._lock:
                self._active_games -= 1

    def _active_rpcs(self) -> int:
        concurrency = getattr(self.runner, "concurrency", None)
        return int(getattr(concurrency, "active", 0))

    def _global_budget_exhausted(self) -> bool:
        """Detect a population-wide boundary without parsing error text."""
        if self.ledger is None:
            return False
        payload = self.ledger.payload()
        remaining = self.ledger.snapshot()
        return bool(payload["crossed"]) or (
            remaining["remaining_scientific_tokens"]
            < self.ledger.reserve_tokens
            or remaining["remaining_scientific_wall_ms"]
            < self.ledger.reserve_wall_ms)

    def _manifest_rows(self) -> list[dict[str, object]]:
        rows = []
        for index, (coordinate, mirror) in enumerate(self.schedule):
            result = self._statuses.get((coordinate, mirror))
            rows.append({"index": index, "coordinate": list(coordinate),
                         "mirror": mirror,
                         "status": None if result is None else result.status,
                         "manifest_sha256": None if result is None
                         else result.manifest_sha256})
        return rows

    def _terminal(self, route: str, *,
                  ledger_terminal_accept_sha256: str | None = None) \
            -> dict[str, object]:
        if route not in ROUTES:
            raise RPCSupervisorError("terminal route drift")
        rows = self._manifest_rows()
        body = {"schema": TERMINAL_SCHEMA, "route": route,
                "schedule_sha256": _schedule_sha(self.schedule),
                "census_sha256": self.census_sha256,
                "runtime_sha256": _sha(self.runtime),
                "attempt_manifest": rows,
                "completed_games": sum(row["status"] == "complete" for row in rows),
                "completed_deal_clusters": sum(
                    all(row["status"] == "complete" for row in rows
                        if row["coordinate"] == list(coordinate))
                    for coordinate in {item[0] for item in self.schedule}),
                "failed_games": sum(row["status"] == "incomplete" for row in rows),
                "pending_games": sum(row["status"] is None for row in rows),
                "resource_totals": self._resource_totals(),
                "ledger_terminal_accept_sha256":
                    ledger_terminal_accept_sha256}
        if _forbidden(body):
            raise RPCSupervisorError("public terminal privacy drift")
        return {**body, "receipt_sha256": _sha(body)}

    def _occupied_without_status(self, coordinate, mirror) -> bool:
        """An unreadable sealed slot (manifest or controller refusal)."""
        if self._statuses.get((coordinate, mirror)) is not None:
            return False
        manifest = _attempt_path(
            self.attempts_root, coordinate, mirror) / "manifest.json"
        return (manifest.exists() or manifest.is_symlink()
                or self._has_controller_refusal(coordinate, mirror))

    def _sealed_defect_route(self) -> str | None:
        """Route durable occupied-slot or ledger defects without a new call."""
        if any(self._occupied_without_status(coordinate, mirror)
               for coordinate, mirror in self.schedule):
            return REFUSE_MECHANICS_OR_PRIVACY
        if self.ledger is not None:
            try:
                self.ledger.reconcile_attempt_journals([
                    _attempt_path(self.attempts_root, coordinate, mirror)
                    for coordinate, mirror in self.schedule
                    if _attempt_path(
                        self.attempts_root, coordinate, mirror).exists()
                ])
            except (RPCCollectionError, OSError):
                return REFUSE_MECHANICS_OR_PRIVACY
        classes = [
            result.failure_class for result in self._statuses.values()
            if result is not None and result.status == "incomplete"]
        if "mechanics-privacy" in classes:
            return REFUSE_MECHANICS_OR_PRIVACY
        if "resource-provider" in classes:
            return REFUSE_RESOURCE_OR_PROVIDER
        return None

    def _derive_route(self) -> str:
        defect = self._sealed_defect_route()
        if defect is not None:
            return defect
        if any(result is None or result.status == "incomplete"
               for result in self._statuses.values()):
            return selfplay.INCOMPLETE_ROUTE
        return selfplay.COMPLETE_ROUTE

    def _reopen_terminal(self, receipt: Mapping[str, object]) \
            -> SupervisorResult:
        """Rebuild the terminal from private artifacts; require equality."""
        validate_terminal_receipt(receipt)
        self._publish_launch()
        self._load_existing()
        for coordinate, mirror in self.schedule:
            if (coordinate, mirror) not in self._statuses:
                self._statuses[(coordinate, mirror)] = self._reopen_one(
                    coordinate, mirror)
        stored_accept = receipt["ledger_terminal_accept_sha256"]
        route = self._derive_route()
        if self.ledger is not None and route == selfplay.COMPLETE_ROUTE:
            if stored_accept is None:
                # Every game completed but the ledger refused terminal
                # acceptance: the run sealed a resource refusal, stably.
                try:
                    self.ledger.assert_within_limits()
                except ResourceBoundaryError:
                    route = REFUSE_RESOURCE_OR_PROVIDER
                else:
                    raise RPCSupervisorError(
                        "terminal ledger acceptance absent")
            elif self.ledger.terminal_acceptance_sha256() != stored_accept:
                raise RPCSupervisorError("terminal ledger acceptance drift")
        elif stored_accept is not None:
            raise RPCSupervisorError("non-complete terminal acceptance drift")
        expected = self._terminal(
            route, ledger_terminal_accept_sha256=stored_accept)
        if receipt != expected:
            raise RPCSupervisorError("terminal reconstruction drift")
        return SupervisorResult(receipt["route"], receipt)

    def _recover_terminal(self) -> Path:
        terminal_path = self.public_root / "terminal.json"
        try:
            recover_linked_partial(terminal_path)
        except AtomicPublishError as exc:
            raise RPCSupervisorError("terminal recovery drift") from exc
        return terminal_path

    def _verify_locked(self) -> SupervisorResult:
        terminal_path = self._recover_terminal()
        if not terminal_path.exists():
            raise RPCSupervisorError("run has no sealed terminal")
        return self._reopen_terminal(
            _read_sealed(terminal_path, label="terminal"))

    def _run_locked(self) -> SupervisorResult:
        terminal_path = self._recover_terminal()
        if terminal_path.exists():
            return self._reopen_terminal(
                _read_sealed(terminal_path, label="terminal"))
        self._publish_launch()
        self._load_existing()
        pre_dispatch_refusal = self._sealed_defect_route()
        if pre_dispatch_refusal is not None:
            for coordinate, mirror in self.schedule:
                self._statuses.setdefault((coordinate, mirror), None)
            self._progress(active_workers=0, active_rpcs=0)
            receipt = self._terminal(pre_dispatch_refusal)
            validate_terminal_receipt(receipt)
            _publish(terminal_path, receipt)
            return SupervisorResult(receipt["route"], receipt)
        pending = [(coordinate, mirror) for coordinate, mirror in self.schedule
                   if (coordinate, mirror) not in self._statuses]
        self._progress(active_workers=0, active_rpcs=0)
        if pending:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {}
                try:
                    next_pending = iter(pending)

                    def submit_one() -> bool:
                        try:
                            coordinate, mirror = next(next_pending)
                        except StopIteration:
                            return False
                        future = executor.submit(
                            self._run_one, coordinate, mirror)
                        futures[future] = (coordinate, mirror)
                        return True

                    for _ in range(min(self.workers, len(pending))):
                        submit_one()
                    while futures:
                        future = next(as_completed(tuple(futures)))
                        coordinate, mirror = futures.pop(future)
                        if future.cancelled():
                            continue
                        try:
                            future.result()
                        except CancelledError:
                            continue
                        except BaseException as exc:
                            self._errors[(coordinate, mirror)] = exc
                            self._record_preseal_mechanics_refusal(
                                coordinate, mirror, exc)
                            # A game-level refusal still makes the terminal
                            # route incomplete, but it must not erase the
                            # independently predeclared games that remain.
                            # Only shared budget exhaustion is population-wide.
                            global_abort = self._global_budget_exhausted()
                            if global_abort and not self.stop_event.is_set():
                                self.stop_event.set()
                                self._terminate_active_calls()
                            if global_abort:
                                for other in tuple(futures):
                                    other.cancel()
                        # The runner has sealed before returning/raising.  Read it
                        # now so every game contributes durable progress.
                        reopened = self._reopen_one(coordinate, mirror)
                        self._statuses[(coordinate, mirror)] = reopened
                        self._progress(active_workers=self._active_games,
                                       active_rpcs=self._active_rpcs())
                        if not self.stop_event.is_set():
                            submit_one()
                except BaseException:
                    self.stop_event.set()
                    self._terminate_active_calls()
                    for future in tuple(futures):
                        future.cancel()
        # Exactly one terminal reopen pass.  It is also the restart path: no
        # provider call is made for either complete or already-incomplete work.
        for coordinate, mirror in self.schedule:
            if (coordinate, mirror) not in self._statuses:
                path = _attempt_path(self.attempts_root, coordinate, mirror)
                manifest = path / "manifest.json"
                if (manifest.exists() or manifest.is_symlink()
                        or self._has_controller_refusal(coordinate, mirror)):
                    self._statuses[(coordinate, mirror)] = self._reopen_one(
                        coordinate, mirror)
                else:
                    self._statuses[(coordinate, mirror)] = None
        self._progress(active_workers=self._active_games,
                       active_rpcs=self._active_rpcs())
        terminal_accept = None
        route = self._derive_route()
        if self.ledger is not None and route == selfplay.COMPLETE_ROUTE:
            try:
                terminal_accept = self.ledger.seal_terminal_acceptance()
            except ResourceBoundaryError:
                route = REFUSE_RESOURCE_OR_PROVIDER
        receipt = self._terminal(
            route, ledger_terminal_accept_sha256=terminal_accept)
        validate_terminal_receipt(receipt)
        _publish(terminal_path, receipt)
        return SupervisorResult(receipt["route"], receipt)

    def _with_run_lock(self, body) -> SupervisorResult:
        if not self._run_state_lock.acquire(blocking=False):
            raise RPCSupervisorError("supervisor run already active")
        try:
            self._run_lock_fd = _acquire_run_lock(self.private_root)
            try:
                return body()
            finally:
                descriptor = self._run_lock_fd
                self._run_lock_fd = None
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        finally:
            self._run_state_lock.release()

    def run(self) -> SupervisorResult:
        """Collect every pending game, or reopen an already sealed run."""
        return self._with_run_lock(lambda: self._run_locked())

    def verify(self) -> SupervisorResult:
        """Reopen a sealed run without dispatching; refuse an unsealed one."""
        return self._with_run_lock(self._verify_locked)


class _ReopenOnlyRunner:
    """Runner stand-in for verification: it can reopen but never dispatch."""

    def __init__(self, attempts_root: Path, runtime: Mapping[str, object]):
        self.attempts_root = Path(attempts_root)
        self.runtime_sha256 = _sha(runtime)

    def __call__(self, coordinate, mirror):
        raise RPCSupervisorError("verification never dispatches a game")


def verify_run(root: Path, *, seed_secret: bytes) -> SupervisorResult:
    """Reopen ``root/private`` and ``root/public`` and rebuild the terminal.

    The seed secret is the only input besides the run root: the schedule
    and census are re-derived from it, every attempt is reopened and
    replayed against its rebuilt root, the ledger event chain is replayed
    from its genesis, and the public terminal must equal the reconstruction.
    """
    private_root = Path(root) / "private"
    public_root = Path(root) / "public"
    _private_dir(private_root, "private supervisor root")
    runtime = _read_sealed(private_root / "runtime.json", label="runtime")
    census = _read_sealed(private_root / "census.json", label="census")
    games = census.get("game_count")
    if isinstance(games, bool) or not isinstance(games, int):
        raise RPCSupervisorError("root census schema drift")
    schedule = schedule_for_games(seed_secret, games)
    ledger = None
    namespace = SCHEMA
    genesis_path = private_root / "ledger" / "genesis.json"
    if genesis_path.exists():
        genesis = _read_sealed(genesis_path, label="ledger genesis")
        try:
            namespace = genesis["namespace"]
            ledger = ScientificBudgetLedger.open_or_create(
                root=private_root / "ledger",
                wall_nanoseconds=genesis["wall_nanoseconds"],
                token_cap=genesis["token_cap"],
                per_call_token_reserve=genesis["per_call_token_reserve"],
                per_call_wall_reserve_milliseconds=genesis[
                    "per_call_wall_reserve_milliseconds"],
                boot_identity_sha256=genesis["boot_identity_sha256"],
                runtime_sha256=genesis["runtime_sha256"],
                namespace=namespace)
        except (KeyError, TypeError, RPCCollectionError) as exc:
            raise RPCSupervisorError("ledger genesis drift") from exc
        if ledger.runtime_sha256 != _sha(runtime):
            raise RPCSupervisorError("ledger runtime binding drift")
    instance = PTLunaRPCSupervisor(
        seed_secret=seed_secret, private_root=private_root,
        public_root=public_root, runtime=runtime, schedule=schedule,
        root_census=census,
        runner=_ReopenOnlyRunner(private_root / "attempts", runtime),
        ledger=ledger, ledger_namespace=namespace)
    return instance.verify()


__all__ = ["CENSUS_SCHEMA", "PROGRESS_SCHEMA", "TERMINAL_SCHEMA", "ROUTES",
           "COMPLETE_STATE_SOURCE_ACQUISITION",
           "REFUSE_MECHANICS_OR_PRIVACY", "REFUSE_RESOURCE_OR_PROVIDER",
           "INCOMPLETE_STATE_SOURCE_ACQUISITION", "RPCSupervisorError",
           "SupervisorResult", "PTLunaRPCSupervisor", "build_root_census",
           "schedule_for_games", "validate_root_census", "validate_schedule",
           "validate_terminal_receipt", "verify_run"]
