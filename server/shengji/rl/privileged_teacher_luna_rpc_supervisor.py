"""Durable population supervisor for the PT-Luna turn-RPC collector.

The supervisor is deliberately boring: it authenticates the frozen schedule,
publishes launch facts before opening a provider, and then only coordinates
independent :class:`RPCGameAttemptRunner` calls.  Game contents and outcomes
remain below the private boundary; public progress contains hashes, counts,
and resource telemetry only.
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
import subprocess
import tempfile
import threading
import time
from typing import Callable, Mapping, Sequence

from . import privileged_teacher_luna_selfplay as selfplay
from .privileged_teacher_luna_rpc_capacity import (
    RPCCapacityError, ROUTE_FULL as FULL_104_ELIGIBLE,
    ROUTE_PILOT as PILOT_32_ELIGIBLE,
    SCHEMA as CAPACITY_SCHEMA, SOURCE_PATHS,
    validate_capacity_receipt,
)
from .privileged_teacher_luna_rpc_collection import (
    AttemptReopen, ResourceBoundaryError, RPCCollectionError,
    RPCGameAttemptRunner,
    SCIENTIFIC_BINDING_SCHEMA,
    ScientificBudgetLedger, reopen_attempt,
)
from .privileged_teacher_luna_rpc_io import (
    AtomicPublishError, publish_exclusive_bytes, recover_linked_partial,
)
from .privileged_teacher_luna_turn_rpc import TurnRPCError, TurnValidationError
from .privileged_teacher_pt0 import canonical_json_bytes


SCHEMA = "pt-luna-turn-rpc-supervisor-v3"
ADMISSION_SCHEMA = "pt-luna-turn-rpc-admission-v3"
LAUNCH_SCHEMA = "pt-luna-turn-rpc-launch-v3"
PROGRESS_SCHEMA = "pt-luna-turn-rpc-progress-v3"
TERMINAL_SCHEMA = "pt-luna-turn-rpc-terminal-v2"
CASUAL_TERMINAL_SCHEMA = "pt-luna-turn-rpc-casual-terminal-v2"
CONTROLLER_REFUSAL_SCHEMA = "pt-luna-turn-rpc-controller-refusal-v1"
CASUAL_COMPLETE_ROUTE = "CASUAL_PROBE_COMPLETE"
CASUAL_INCOMPLETE_ROUTE = "CASUAL_PROBE_INCOMPLETE"
FREEZE_SCHEMA = "pt-luna-turn-rpc-launch-freeze-v3"
SOURCE_REVIEW_SCHEMA = "pt-luna-turn-rpc-source-review-v3"
FREEZE_REVIEW_SCHEMA = "pt-luna-turn-rpc-freeze-review-v3"
SOURCE_REVIEW_PREFIX = "PT_LUNA_RPC_SOURCE_REVIEW:"
FREEZE_REVIEW_PREFIX = "PT_LUNA_RPC_FREEZE_REVIEW:"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CAPACITY_ELIGIBLE_ROUTES = (FULL_104_ELIGIBLE, PILOT_32_ELIGIBLE)
PILOT_SCIENTIFIC_GAME_DEADLINE_NS = 1_800 * 1_000_000_000
PILOT_SCIENTIFIC_WALL_NS = 12_000 * 1_000_000_000
PILOT_SCIENTIFIC_TOKEN_BUDGET = 26_404_925
PILOT_CAPACITY_RECEIPT_SHA256 = \
    "1ba204ee855b0842a6388f243bb86a02eba6a22163b91cce9ac570b936470364"
PILOT_CAPACITY_SOURCE_EXECUTION_GIT = \
    "d126ad019e1175cd6fe7d0a296c911bf28ae8883"
PILOT_CAPACITY_SOURCE_CLAIM_SHA256 = \
    "882d436c7b572928582da6063f4b5d343d43f6c1750b3147f1e781cfb9088901"
PILOT_ATTEMPT_LINEAGE = {
    "schema": "pt-luna-resilient-acquisition-lineage-v1",
    "route_ordinal": 1,
    "maximum_route_ordinal": 1,
    "retry_after_this_attempt_authorized": False,
    "closed_predecessor_attempts": [
        {
            "attempt_ordinal": 1,
            "terminal_file_sha256":
                "2e72102914bcf1e9ff262756aa33fad45a03f6213098a1982680ebc67f8fe7b6",
            "terminal_receipt_sha256":
                "4a53e4d28a4ffcc8230a88db95510265f493665627b0084a374e99fe8a319766",
            "ledger_spent_tokens": 3_674_786,
            "completed_games": 4,
        },
        {
            "attempt_ordinal": 2,
            "terminal_file_sha256":
                "d1cc5c135e6cbda02e58849e3cd420b10d34a42b3ef5a78498dca70bf2251f25",
            "terminal_receipt_sha256":
                "c5034c2006f9f49355c29ee92debc6360a6f958cc23d573ecdf8dd95d43cad6c",
            "ledger_spent_tokens": 3_520_281,
            "completed_games": 3,
        },
        {
            "attempt_ordinal": 3,
            "terminal_file_sha256":
                "eefa49c6031122822bfc4547206349972b7a33265a19ef2528fe67cf3efa3d53",
            "terminal_receipt_sha256":
                "c76dedfc02de7001b791de77a1304303f82d97db25e03d51660063891153a7e9",
            "ledger_spent_tokens": 2_734_638,
            "completed_games": 3,
        },
    ],
    "prior_spent_tokens": 9_929_705,
    "prior_completed_games": 10,
}
DESIGN_PATHS = (
    "PRIVILEGED_TEACHER_LUNA_SELFPLAY_DESIGN.md",
    "PRIVILEGED_TEACHER_LUNA_PLAY_ONLY_DESIGN.md",
)
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
    """A frozen supervisor input or durable receipt is invalid."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise RPCSupervisorError(f"{label} drift")
    return value


def _pilot_attempt_lineage() -> dict[str, object]:
    """Return a fresh copy of the closed attempts plus the new-route identity."""
    return json.loads(json.dumps(PILOT_ATTEMPT_LINEAGE))


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-C", str(repo), *args), check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RPCSupervisorError("Git provenance unavailable") from exc
    return result.stdout.decode("utf-8").strip()


def _acquire_scientific_run_lock(private_root: Path) -> int:
    path = Path(private_root) / "run.lock"
    descriptor = os.open(
        path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise RPCSupervisorError("scientific run lock identity drift")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RPCSupervisorError(
                "scientific namespace already active") from exc
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def source_review_claim(repo_root: Path) -> dict[str, object]:
    """Build the exact claim for the consolidated final-pilot review."""
    repo = Path(repo_root).resolve()
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RPCSupervisorError("source review requires exact-clean tree")
    server = repo / "server"
    sources = {name: _sha_bytes((server / name).read_bytes())
               for name in SOURCE_PATHS}
    design_sha256s = {
        name: _sha_bytes((repo / name).read_bytes())
        for name in DESIGN_PATHS
    }
    body = {
        "schema": SOURCE_REVIEW_SCHEMA,
        "execution_git": _git(repo, "rev-parse", "HEAD"),
        "source_set_sha256": _sha(sources),
        "design_sha256s": design_sha256s,
        "design_sha256": _sha(design_sha256s),
        "capacity_carry_forward": {
            "receipt_sha256": PILOT_CAPACITY_RECEIPT_SHA256,
            "source_execution_git": PILOT_CAPACITY_SOURCE_EXECUTION_GIT,
            "source_claim_sha256": PILOT_CAPACITY_SOURCE_CLAIM_SHA256,
        },
        "pilot_attempt_lineage": _pilot_attempt_lineage(),
        "score_free_canary_authorized": False,
        "score_free_capacity_authorized": False,
        "scientific_execution_authorized": False,
        "outcome_opening_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "strength_claim_authorized": False,
        "authority": dict(selfplay.AUTHORITY),
    }
    return {**body, "claim_sha256": _sha(body)}


def freeze_review_claim(freeze: Mapping[str, object]) -> dict[str, object]:
    validate_launch_freeze_shape(freeze)
    body = {
        "schema": FREEZE_REVIEW_SCHEMA,
        "execution_git": freeze["execution_git"],
        "freeze_sha256": freeze["freeze_sha256"],
        "source_set_sha256": freeze["source_set_sha256"],
        "capacity_receipt_sha256": freeze["capacity_receipt_sha256"],
        "capacity_route": freeze["capacity_route"],
        "selected_game_count": freeze["selected_game_count"],
        "selected_deal_cluster_count": freeze[
            "selected_deal_cluster_count"],
        "capacity_measurement_game_deadline_nanoseconds": freeze[
            "capacity_measurement_game_deadline_nanoseconds"],
        "scientific_game_deadline_nanoseconds": freeze[
            "per_game_deadline_nanoseconds"],
        "pilot_attempt_lineage": freeze["pilot_attempt_lineage"],
        "scientific_execution_authorized": True,
        "outcome_opening_authorized": True,
        "merge_authorized": False,
        "deployment_authorized": False,
        "strength_claim_authorized": False,
        "authority": dict(selfplay.AUTHORITY),
    }
    return {**body, "claim_sha256": _sha(body)}


def authenticate_review_claim(*, claim: Mapping[str, object], prefix: str,
                              review_commit: str) -> dict[str, object]:
    """Authenticate one append-only marker fetched from canonical GitHub main."""
    if type(claim) is not dict or type(prefix) is not str or not prefix \
            or type(review_commit) is not str or len(review_commit) != 40 \
            or any(char not in "0123456789abcdef" for char in review_commit):
        raise RPCSupervisorError("review authentication input drift")
    claim_body = {key: value for key, value in claim.items()
                  if key != "claim_sha256"}
    if set(claim) != {*claim_body, "claim_sha256"} \
            or claim.get("claim_sha256") != _sha(claim_body):
        raise RPCSupervisorError("review claim seal drift")
    with tempfile.TemporaryDirectory(prefix="pt-luna-rpc-review-") as temp:
        bare = Path(temp) / "review.git"
        try:
            subprocess.run(("git", "init", "--bare", str(bare)), check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run((
                "git", "-C", str(bare), "fetch", "--no-tags",
                CANONICAL_REMOTE_URL,
                "main:refs/remotes/review/main"), check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RPCSupervisorError(
                "canonical review remote unavailable") from exc
        if subprocess.run((
                "git", "-C", str(bare), "merge-base", "--is-ancestor",
                review_commit, "refs/remotes/review/main"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0:
            raise RPCSupervisorError("review commit is not on canonical main")
        parents = _git(bare, "rev-list", "--parents", "-n", "1",
                       review_commit).split()
        if len(parents) != 2:
            raise RPCSupervisorError("review commit parent drift")
        try:
            current = subprocess.check_output((
                "git", "-C", str(bare), "show",
                f"{review_commit}:HANDOFF_REVIEW.md"))
            previous = subprocess.check_output((
                "git", "-C", str(bare), "show",
                f"{parents[1]}:HANDOFF_REVIEW.md"))
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RPCSupervisorError("review ledger unavailable") from exc
    marker = (prefix.encode("ascii") + b" "
              + canonical_json_bytes(claim))
    if current != previous + marker or marker in previous.splitlines(
            keepends=True):
        raise RPCSupervisorError("review marker commit drift")
    return {"review_commit": review_commit,
            "review_marker_sha256": _sha_bytes(marker),
            "review_claim": dict(claim)}


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


def validate_schedule(
        schedule: Sequence[tuple[tuple[str, int, int], int]] | None = None,
        *, expected: Sequence[tuple[tuple[str, int, int], int]] | None = None,
        require_full_population: bool = True,
) -> tuple[tuple[tuple[str, int, int], int], ...]:
    """Validate the ordered cluster/mirror schedule before any provider call."""
    actual = tuple(schedule if schedule is not None
                   else selfplay.mirrored_assignments())
    canonical = tuple(expected if expected is not None
                      else selfplay.mirrored_assignments())
    if require_full_population and actual != canonical:
        raise RPCSupervisorError("exact formal schedule drift")
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
    if require_full_population and len(actual) not in (32, 104):
        raise RPCSupervisorError("exact formal schedule count drift")
    if expected is not None and actual != canonical:
        raise RPCSupervisorError("ordered schedule drift")
    return actual


def schedule_for_capacity_route(
        seed_secret: bytes, route: object,
) -> tuple[tuple[tuple[str, int, int], int], ...]:
    """Derive the only formal schedule admitted by a capacity route."""
    if type(seed_secret) is not bytes or len(seed_secret) != 32:
        raise RPCSupervisorError("seed secret drift")
    if route == FULL_104_ELIGIBLE:
        return validate_schedule()
    if route != PILOT_32_ELIGIBLE:
        raise RPCSupervisorError("capacity route is not execution eligible")
    census = selfplay.root_census(seed_secret).serialized()
    rows = census.get("coordinates")
    if type(rows) is not list or len(rows) != 52:
        raise RPCSupervisorError("pilot root census population drift")
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("root_sha256") if type(row) is dict else "",
            tuple(row.get("coordinate", ())) if type(row) is dict else ()),
    )
    coordinates: list[tuple[str, int, int]] = []
    for row in ordered[:16]:
        if type(row) is not dict:
            raise RPCSupervisorError("pilot root census row drift")
        root_sha = row.get("root_sha256")
        mirror_sha = row.get("mirror_root_sha256")
        coordinate = row.get("coordinate")
        _strict_sha(root_sha, "pilot root")
        if root_sha != mirror_sha or type(coordinate) is not list \
                or len(coordinate) != 3:
            raise RPCSupervisorError("pilot root census row drift")
        try:
            parsed = selfplay.LunaCoordinate(*coordinate)
        except Exception as exc:
            raise RPCSupervisorError("pilot root census row drift") from exc
        coordinates.append(parsed.cluster_key)
    schedule = tuple((coordinate, mirror)
                     for coordinate in coordinates for mirror in (0, 1))
    return validate_schedule(
        schedule, expected=schedule, require_full_population=True)


def build_root_census(
        seed_secret: bytes,
        schedule: Sequence[tuple[tuple[str, int, int], int]],
) -> dict[str, object]:
    """Build a score-free root census for exactly the admitted clusters."""
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
    body = {"schema": "pt-luna-turn-rpc-supervisor-census-v1",
            "seed_commitment_sha256": _sha_bytes(seed_secret),
            "coordinates": clusters, "coordinate_count": len(clusters),
            "game_count": len(schedule), "authority": dict(selfplay.AUTHORITY)}
    return {**body, "census_sha256": _sha(body)}


def validate_root_census(
        census: Mapping[str, object], seed_secret: bytes,
        schedule: Sequence[tuple[tuple[str, int, int], int]],
) -> str:
    if type(census) is not dict:
        raise RPCSupervisorError("root census schema drift")
    # The canonical 52-cluster census is produced by the self-play module.
    # Accept it directly, while retaining a small injected census shape for
    # unit tests that use a deliberately tiny schedule.
    if census.get("schema") == selfplay.ROOT_CENSUS_SCHEMA:
        try:
            selfplay.validate_root_census(census)
        except Exception as exc:
            raise RPCSupervisorError("root census schema drift") from exc
        expected = [list(coordinate) for coordinate, _ in schedule]
        expected = list(dict.fromkeys(tuple(row) for row in expected))
        actual = [tuple(row["coordinate"]) for row in census["coordinates"]]
        if actual != expected:
            raise RPCSupervisorError("root census coverage drift")
        return census["census_sha256"]
    if census.get("schema") != "pt-luna-turn-rpc-supervisor-census-v1":
        raise RPCSupervisorError("root census schema drift")
    body = {key: value for key, value in census.items() if key != "census_sha256"}
    _strict_sha(census.get("census_sha256"), "root census")
    if census["census_sha256"] != _sha(body):
        raise RPCSupervisorError("root census hash drift")
    if census.get("seed_commitment_sha256") != _sha_bytes(seed_secret):
        raise RPCSupervisorError("root census seed drift")
    coordinates = tuple(coordinate for coordinate, _ in schedule)
    expected = []
    for coordinate in coordinates:
        if coordinate not in expected:
            expected.append(coordinate)
    rows = census.get("coordinates")
    if (type(rows) is not list or census.get("coordinate_count") != len(rows)
            or census.get("game_count") != len(schedule)
            or census.get("authority") != selfplay.AUTHORITY
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


def validate_capacity_source_for_freeze(
        capacity_receipt: Mapping[str, object],
        current_source_claim: Mapping[str, object]) -> None:
    """Accept current-source capacity or the one exact Pilot-2 carry-forward."""
    source_review = capacity_receipt.get("source_review")
    reviewed_claim = (source_review.get("review_claim")
                      if isinstance(source_review, Mapping) else None)
    if reviewed_claim == current_source_claim:
        return
    exact_carry_forward = (
        capacity_receipt.get("route") == PILOT_32_ELIGIBLE
        and capacity_receipt.get("receipt_sha256")
        == PILOT_CAPACITY_RECEIPT_SHA256
        and isinstance(reviewed_claim, Mapping)
        and reviewed_claim.get("execution_git")
        == PILOT_CAPACITY_SOURCE_EXECUTION_GIT
        and reviewed_claim.get("claim_sha256")
        == PILOT_CAPACITY_SOURCE_CLAIM_SHA256)
    if not exact_carry_forward:
        raise RPCSupervisorError("freeze source review binding drift")


def validate_capacity_runtime_for_freeze(
        capacity_receipt: Mapping[str, object],
        current_runtime: Mapping[str, object]) -> None:
    """Permit only reviewed source-identity drift on the carried receipt."""
    measured_runtime = capacity_receipt.get("runtime")
    if measured_runtime == current_runtime:
        return
    if (capacity_receipt.get("route") != PILOT_32_ELIGIBLE
            or capacity_receipt.get("receipt_sha256")
            != PILOT_CAPACITY_RECEIPT_SHA256
            or type(measured_runtime) is not dict
            or type(current_runtime) is not dict
            or set(measured_runtime) != set(current_runtime)):
        raise RPCSupervisorError("freeze capacity/runtime drift")
    source_fields = {
        "execution_git", "git_tree", "sources", "source_set_sha256"}
    measured_stable = {
        key: value for key, value in measured_runtime.items()
        if key not in source_fields}
    current_stable = {
        key: value for key, value in current_runtime.items()
        if key not in source_fields}
    if measured_stable != current_stable:
        raise RPCSupervisorError("freeze capacity/runtime drift")


def _selected_scientific_token_budget(
        capacity_receipt: Mapping[str, object]) -> int:
    """Bind the final pilot to its approved 25%-headroom projection."""
    if (capacity_receipt.get("route") == PILOT_32_ELIGIBLE
            and capacity_receipt.get("receipt_sha256")
            == PILOT_CAPACITY_RECEIPT_SHA256):
        value = capacity_receipt.get("projected_pilot_token_count")
    else:
        value = capacity_receipt.get("scientific_token_budget")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RPCSupervisorError("scientific token budget drift")
    return value


def launch_freeze_payload(
        *, repo_root: Path, seed_secret: bytes,
        census: Mapping[str, object], capacity_receipt: Mapping[str, object],
        runtime: Mapping[str, object], private_root: Path, public_root: Path,
        namespace: str) -> dict[str, object]:
    """Build the immutable candidate later authenticated by freeze review."""
    try:
        validate_capacity_receipt(capacity_receipt)
    except RPCCapacityError as exc:
        raise RPCSupervisorError("capacity receipt refused") from exc
    capacity_route = capacity_receipt.get("route")
    if capacity_route not in CAPACITY_ELIGIBLE_ROUTES:
        raise RPCSupervisorError("freeze capacity/runtime drift")
    validate_capacity_runtime_for_freeze(capacity_receipt, runtime)
    schedule = schedule_for_capacity_route(seed_secret, capacity_route)
    census_sha = validate_root_census(census, seed_secret, schedule)
    expected_game_count = 104 if capacity_route == FULL_104_ELIGIBLE else 32
    expected_cluster_count = expected_game_count // 2
    if capacity_receipt.get("selected_game_count") != expected_game_count \
            or capacity_receipt.get("selected_deal_cluster_count") \
            != expected_cluster_count:
        raise RPCSupervisorError("freeze capacity population drift")
    workers = capacity_receipt["selected_workers"]
    arm = next((row for row in capacity_receipt["arms"]
                if row["workers"] == workers), None)
    if arm is None or not arm.get("passed"):
        raise RPCSupervisorError("freeze selected arm drift")
    if type(namespace) is not str or not namespace or len(namespace) > 256:
        raise RPCSupervisorError("freeze namespace drift")
    source_claim = source_review_claim(repo_root)
    validate_capacity_source_for_freeze(capacity_receipt, source_claim)
    scientific_game_deadline_ns = (
        PILOT_SCIENTIFIC_GAME_DEADLINE_NS
        if capacity_route == PILOT_32_ELIGIBLE
        else capacity_receipt["per_game_deadline_nanoseconds"])
    body = {
        "schema": FREEZE_SCHEMA,
        "execution_git": source_claim["execution_git"],
        "source_set_sha256": source_claim["source_set_sha256"],
        "design_sha256": source_claim["design_sha256"],
        "seed_commitment_sha256": _sha_bytes(seed_secret),
        "schedule_sha256": _schedule_sha(schedule),
        "census_sha256": census_sha,
        "capacity_receipt_sha256": capacity_receipt["receipt_sha256"],
        "runtime_sha256": _sha(runtime),
        "capacity_route": capacity_route,
        "selected_game_count": expected_game_count,
        "selected_deal_cluster_count": expected_cluster_count,
        "selected_workers": workers,
        "capacity_measurement_game_deadline_nanoseconds": capacity_receipt[
            "per_game_deadline_nanoseconds"],
        "per_game_deadline_nanoseconds": scientific_game_deadline_ns,
        "per_game_token_cap": arm["per_game_token_cap"],
        "per_call_token_reserve": arm["per_call_token_reserve"],
        "per_call_wall_reserve_milliseconds": arm[
            "per_call_wall_reserve_milliseconds"],
        "scientific_wall_nanoseconds": capacity_receipt[
            "selected_population_wall_nanoseconds"],
        "scientific_token_budget": _selected_scientific_token_budget(
            capacity_receipt),
        "private_root": str(Path(private_root).resolve()),
        "public_root": str(Path(public_root).resolve()),
        "namespace": namespace,
        "pilot_attempt_lineage": (
            _pilot_attempt_lineage()
            if capacity_route == PILOT_32_ELIGIBLE else None),
        "authenticated": False,
        "scientific_execution_authorized": False,
        "outcome_opening_authorized": False,
        "authority": dict(selfplay.AUTHORITY),
    }
    return {**body, "freeze_sha256": _sha(body)}


def validate_launch_freeze_shape(freeze: Mapping[str, object]) -> None:
    keys = {"schema", "execution_git", "source_set_sha256",
            "design_sha256", "seed_commitment_sha256", "schedule_sha256",
            "census_sha256", "capacity_receipt_sha256", "runtime_sha256",
            "capacity_route", "selected_game_count",
            "selected_deal_cluster_count", "selected_workers",
            "capacity_measurement_game_deadline_nanoseconds",
            "per_game_deadline_nanoseconds",
            "per_game_token_cap", "per_call_token_reserve",
            "per_call_wall_reserve_milliseconds",
            "scientific_wall_nanoseconds", "scientific_token_budget",
            "private_root", "public_root", "namespace",
            "pilot_attempt_lineage", "authenticated",
            "scientific_execution_authorized", "outcome_opening_authorized",
            "authority", "freeze_sha256"}
    if type(freeze) is not dict or set(freeze) != keys \
            or freeze.get("schema") != FREEZE_SCHEMA \
            or freeze.get("authority") != selfplay.AUTHORITY \
            or freeze.get("authenticated") is not False \
            or freeze.get("scientific_execution_authorized") is not False \
            or freeze.get("outcome_opening_authorized") is not False:
        raise RPCSupervisorError("launch freeze schema drift")
    body = {key: value for key, value in freeze.items()
            if key != "freeze_sha256"}
    if freeze["freeze_sha256"] != _sha(body):
        raise RPCSupervisorError("launch freeze seal drift")
    execution_git = freeze["execution_git"]
    if type(execution_git) is not str or len(execution_git) != 40 \
            or any(char not in "0123456789abcdef" for char in execution_git):
        raise RPCSupervisorError("freeze execution Git drift")
    for key in ("source_set_sha256", "design_sha256",
                "seed_commitment_sha256", "schedule_sha256",
                "census_sha256", "capacity_receipt_sha256",
                "runtime_sha256", "freeze_sha256"):
        _strict_sha(freeze[key], f"freeze {key}")
    for key in ("selected_workers",
                "capacity_measurement_game_deadline_nanoseconds",
                "per_game_deadline_nanoseconds",
                "per_game_token_cap", "per_call_token_reserve",
                "per_call_wall_reserve_milliseconds",
                "scientific_wall_nanoseconds", "scientific_token_budget",
                "selected_game_count", "selected_deal_cluster_count"):
        value = freeze[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RPCSupervisorError(f"freeze {key} drift")
    if freeze["per_game_deadline_nanoseconds"] % 1_000_000_000:
        raise RPCSupervisorError("freeze per-game deadline granularity drift")
    if freeze["capacity_route"] not in CAPACITY_ELIGIBLE_ROUTES \
            or (freeze["capacity_route"] == FULL_104_ELIGIBLE
                and (freeze["selected_game_count"],
                     freeze["selected_deal_cluster_count"]) != (104, 52)) \
            or (freeze["capacity_route"] == PILOT_32_ELIGIBLE
                and (freeze["selected_game_count"],
                     freeze["selected_deal_cluster_count"]) != (32, 16)):
        raise RPCSupervisorError("freeze capacity route population drift")
    if freeze["capacity_route"] == PILOT_32_ELIGIBLE:
        if freeze["capacity_measurement_game_deadline_nanoseconds"] \
                != 1_200 * 1_000_000_000 \
                or freeze["per_game_deadline_nanoseconds"] \
                != PILOT_SCIENTIFIC_GAME_DEADLINE_NS \
                or freeze["scientific_wall_nanoseconds"] \
                != PILOT_SCIENTIFIC_WALL_NS \
                or freeze["scientific_token_budget"] \
                != PILOT_SCIENTIFIC_TOKEN_BUDGET \
                or freeze["pilot_attempt_lineage"] \
                != _pilot_attempt_lineage():
            raise RPCSupervisorError("pilot resilient-route binding drift")
    elif freeze["pilot_attempt_lineage"] is not None:
        raise RPCSupervisorError("non-pilot attempt lineage drift")
    if type(freeze["namespace"]) is not str or not freeze["namespace"] \
            or type(freeze["private_root"]) is not str \
            or type(freeze["public_root"]) is not str:
        raise RPCSupervisorError("freeze path/namespace drift")


def validate_launch_freeze(
        freeze: Mapping[str, object], *, repo_root: Path, seed_secret: bytes,
        census: Mapping[str, object], capacity_receipt: Mapping[str, object],
        runtime: Mapping[str, object], private_root: Path, public_root: Path,
        namespace: str) -> None:
    validate_launch_freeze_shape(freeze)
    expected = launch_freeze_payload(
        repo_root=repo_root, seed_secret=seed_secret, census=census,
        capacity_receipt=capacity_receipt, runtime=runtime,
        private_root=private_root, public_root=public_root,
        namespace=namespace)
    if freeze != expected:
        raise RPCSupervisorError("launch freeze binding drift")


def _failure_class(exc: BaseException) -> str:
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if any(marker in text or marker in name for marker in (
            "resource", "provider", "budget", "deadline", "timeout",
            "capacity", "disposition")):
        return "resource-provider"
    if isinstance(exc, (TurnRPCError, TurnValidationError)):
        return "mechanics-privacy"
    # The collection wrapper uses RPCCollectionError for an already-sealed
    # provider/resource refusal.  Unknown controller death remains an
    # incomplete source acquisition, not a mechanics verdict.
    if isinstance(exc, RPCCollectionError):
        return "resource-provider"
    if isinstance(exc, KeyboardInterrupt):
        return "resource-provider"
    return "mechanics-privacy"


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
                         "admission_sha256", "attempt_manifest", "completed_games",
                         "completed_deal_clusters", "failed_games", "pending_games",
                         "resource_totals", "pilot_attempt_lineage",
                         "ledger_terminal_accept_sha256",
                         "authority", "receipt_sha256"}
            or receipt.get("schema") != TERMINAL_SCHEMA
            or receipt.get("route") not in ROUTES
            or receipt.get("authority") != selfplay.AUTHORITY
            or receipt.get("receipt_sha256") != _sha(body)
            or _forbidden(receipt)):
        raise RPCSupervisorError("terminal receipt schema drift")
    lineage = receipt["pilot_attempt_lineage"]
    if lineage is not None and lineage != _pilot_attempt_lineage():
        raise RPCSupervisorError("terminal pilot attempt lineage drift")
    terminal_accept = receipt["ledger_terminal_accept_sha256"]
    if terminal_accept is not None:
        _strict_sha(terminal_accept, "terminal ledger acceptance")
    for key in ("schedule_sha256", "census_sha256", "admission_sha256",
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


def _validate_casual_terminal_receipt(receipt: Mapping[str, object]) -> None:
    if type(receipt) is not dict:
        raise RPCSupervisorError("casual terminal receipt schema drift")
    body = {key: value for key, value in receipt.items()
            if key != "receipt_sha256"}
    if (receipt.get("schema") != CASUAL_TERMINAL_SCHEMA
            or receipt.get("scientific") is not False
            or receipt.get("route") not in {
                CASUAL_COMPLETE_ROUTE, CASUAL_INCOMPLETE_ROUTE}
            or receipt.get("receipt_sha256") != _sha(body)):
        raise RPCSupervisorError("casual terminal receipt schema drift")
    converted = dict(receipt)
    converted.pop("scientific")
    converted["schema"] = TERMINAL_SCHEMA
    converted["route"] = (
        selfplay.COMPLETE_ROUTE
        if receipt["route"] == CASUAL_COMPLETE_ROUTE
        else selfplay.INCOMPLETE_ROUTE)
    converted_body = {key: value for key, value in converted.items()
                      if key != "receipt_sha256"}
    converted["receipt_sha256"] = _sha(converted_body)
    validate_terminal_receipt(converted)


@dataclass(frozen=True)
class SupervisorResult:
    route: str
    receipt: Mapping[str, object]


class PTLunaRPCSupervisor:
    """Coordinate one immutable 104-game admission and its restartable run."""

    def __init__(
            self, *, seed_secret: bytes, private_root: Path, public_root: Path,
            runtime: Mapping[str, object], admission: Mapping[str, object],
            capacity_receipt: Mapping[str, object],
            runner: RPCGameAttemptRunner | None = None,
            codex_binary: Path | None = None,
            launch_freeze: Mapping[str, object] | None = None,
            schedule: Sequence[tuple[tuple[str, int, int], int]] | None = None,
            expected_schedule: Sequence[tuple[tuple[str, int, int], int]] | None = None,
            require_full_population: bool = True,
            root_census: Mapping[str, object] | None = None,
            ledger: ScientificBudgetLedger | None = None,
            per_call_token_reserve: int | None = None,
            per_call_wall_reserve_milliseconds: int | None = None,
            ledger_namespace: str = SCHEMA,
            workers: int | None = None):
        if type(seed_secret) is not bytes or len(seed_secret) != 32:
            raise RPCSupervisorError("seed secret drift")
        if type(runtime) is not dict or not runtime:
            raise RPCSupervisorError("runtime admission drift")
        if type(admission) is not dict or not admission:
            raise RPCSupervisorError("explicit admission required")
        if type(capacity_receipt) is not dict:
            raise RPCSupervisorError("capacity receipt required")
        if capacity_receipt.get("schema") == CAPACITY_SCHEMA:
            try:
                validate_capacity_receipt(capacity_receipt)
            except RPCCapacityError as exc:
                raise RPCSupervisorError("capacity receipt refused") from exc
        elif capacity_receipt.get("schema") == "pt-luna-turn-rpc-capacity-v2":
            raise RPCSupervisorError("capacity receipt schema drift")
        capacity_route = capacity_receipt.get("route")
        if require_full_population and capacity_route not in CAPACITY_ELIGIBLE_ROUTES:
            raise RPCSupervisorError("capacity route is not execution eligible")
        if require_full_population:
            validate_capacity_runtime_for_freeze(capacity_receipt, runtime)
        selected = capacity_receipt.get("selected_workers")
        if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
            raise RPCSupervisorError("selected worker count drift")
        if workers is not None and workers != selected:
            raise RPCSupervisorError("worker selection drift")
        freeze = None
        if require_full_population:
            if type(launch_freeze) is not dict:
                raise RPCSupervisorError("authenticated launch freeze required")
            freeze = dict(launch_freeze)
            validate_launch_freeze_shape(freeze)
            claim = freeze_review_claim(freeze)
            authenticated = authenticate_review_claim(
                claim=claim, prefix=FREEZE_REVIEW_PREFIX,
                review_commit=admission.get("review_commit", ""))
            if dict(admission) != authenticated:
                raise RPCSupervisorError("freeze review authentication drift")
            if (freeze["capacity_receipt_sha256"]
                    != capacity_receipt.get("receipt_sha256")
                    or freeze["runtime_sha256"] != _sha(runtime)
                    or freeze["source_set_sha256"]
                    != runtime.get("source_set_sha256")
                    or freeze["capacity_route"] != capacity_route
                    or freeze["selected_workers"] != selected
                    or freeze["seed_commitment_sha256"]
                    != _sha_bytes(seed_secret)
                    or freeze["private_root"]
                    != str(Path(private_root).resolve())
                    or freeze["public_root"]
                    != str(Path(public_root).resolve())
                    or freeze["namespace"] != ledger_namespace):
                raise RPCSupervisorError("scientific launch freeze drift")
        self.seed_secret = seed_secret
        self.private_root = Path(private_root)
        self.public_root = Path(public_root)
        self.runtime = dict(runtime)
        self.admission = dict(admission)
        self.capacity_receipt = dict(capacity_receipt)
        self.capacity_route = capacity_route
        self.scientific = require_full_population
        self.pilot_attempt_lineage = (
            None if freeze is None else freeze["pilot_attempt_lineage"])
        if require_full_population:
            formal_schedule = schedule_for_capacity_route(
                seed_secret, capacity_route)
            if expected_schedule is not None \
                    and tuple(expected_schedule) != formal_schedule:
                raise RPCSupervisorError("formal expected schedule injection refused")
            self.schedule = validate_schedule(
                formal_schedule if schedule is None else schedule,
                expected=formal_schedule, require_full_population=True)
        else:
            self.schedule = validate_schedule(
                schedule, expected=expected_schedule,
                require_full_population=False)
        if root_census is None:
            census = (selfplay.root_census(seed_secret).serialized()
                      if require_full_population
                      and capacity_route == FULL_104_ELIGIBLE else
                      build_root_census(seed_secret, self.schedule))
        elif isinstance(root_census, selfplay.RootCensus):
            census = root_census.serialized()
        else:
            census = dict(root_census)
        self.census_sha256 = validate_root_census(census, seed_secret, self.schedule)
        self.census = census
        self._run_lock_fd: int | None = None
        if require_full_population:
            if runner is not None or ledger is not None or codex_binary is None:
                raise RPCSupervisorError(
                    "scientific execution objects must be internally owned")
            _mkdir_private(Path(private_root), "private supervisor root")
            ledger = ScientificBudgetLedger.open_or_create(
                root=Path(private_root) / "ledger",
                wall_nanoseconds=freeze["scientific_wall_nanoseconds"],
                token_cap=freeze["scientific_token_budget"],
                per_call_token_reserve=freeze["per_call_token_reserve"],
                per_call_wall_reserve_milliseconds=
                    freeze["per_call_wall_reserve_milliseconds"],
                boot_identity_sha256=runtime["boot_identity_sha256"],
                runtime_sha256=_sha(runtime),
                capacity_receipt_sha256=
                    capacity_receipt["receipt_sha256"],
                namespace=ledger_namespace)
            scientific_binding = {
                "schema": SCIENTIFIC_BINDING_SCHEMA,
                "freeze_sha256": freeze["freeze_sha256"],
                "admission_sha256": _sha(admission),
                "capacity_receipt_sha256":
                    capacity_receipt["receipt_sha256"],
                "runtime_sha256": _sha(runtime),
                "ledger_genesis_sha256":
                    ledger.payload()["genesis_sha256"],
                "namespace": ledger_namespace,
            }
            runner = RPCGameAttemptRunner(
                seed_secret=seed_secret,
                attempts_root=Path(private_root) / "attempts",
                codex_binary=codex_binary, runtime=runtime,
                per_game_deadline_seconds=
                    freeze["per_game_deadline_nanoseconds"]
                    // 1_000_000_000,
                per_game_token_cap=freeze["per_game_token_cap"],
                per_call_token_reserve=freeze["per_call_token_reserve"],
                per_call_wall_reserve_milliseconds=
                    freeze["per_call_wall_reserve_milliseconds"],
                scientific_binding=scientific_binding,
                stop_event=threading.Event())
        elif runner is None:
            raise RPCSupervisorError("injected runner required")
        self.runner = runner
        if require_full_population:
            if type(runner) is not RPCGameAttemptRunner \
                    or type(ledger) is not ScientificBudgetLedger:
                raise RPCSupervisorError(
                    "scientific runner or ledger implementation drift")
            expected_attempts_root = Path(private_root).resolve() / "attempts"
            if (runner.codex_binary is None
                    or runner.attempts_root.resolve() != expected_attempts_root
                    or runner.seed_secret != seed_secret
                    or runner.runtime != dict(runtime)
                    or runner.runtime_sha256 != _sha(runtime)
                    or runner.scientific_binding != scientific_binding
                    or runner.scientific_binding_sha256
                    != _sha(scientific_binding)):
                raise RPCSupervisorError("scientific runner binding drift")
        selected_arm = next((arm for arm in capacity_receipt.get("arms", [])
                             if arm.get("workers") == selected), None)
        if require_full_population:
            if selected_arm is None:
                raise RPCSupervisorError("selected capacity arm absent")
            expected_token_reserve = selected_arm.get(
                "per_call_token_reserve")
            expected_wall_reserve = selected_arm.get(
                "per_call_wall_reserve_milliseconds")
            if per_call_token_reserve is None:
                per_call_token_reserve = expected_token_reserve
            if per_call_wall_reserve_milliseconds is None:
                per_call_wall_reserve_milliseconds = expected_wall_reserve
            if per_call_token_reserve != expected_token_reserve \
                    or per_call_wall_reserve_milliseconds \
                    != expected_wall_reserve:
                raise RPCSupervisorError("scientific per-call reserve drift")
            if getattr(runner, "per_call_token_reserve", None) \
                    != expected_token_reserve \
                    or getattr(
                        runner, "per_call_wall_reserve_milliseconds", None) \
                    != expected_wall_reserve:
                raise RPCSupervisorError("runner per-call reserve drift")
            if (freeze["schedule_sha256"] != _schedule_sha(self.schedule)
                    or freeze["census_sha256"] != self.census_sha256
                    or freeze["per_game_deadline_nanoseconds"]
                    != getattr(runner, "per_game_deadline_ns", None)
                    or freeze["per_game_token_cap"]
                    != getattr(runner, "per_game_token_cap", None)
                    or freeze["per_call_token_reserve"]
                    != expected_token_reserve
                    or freeze["per_call_wall_reserve_milliseconds"]
                    != expected_wall_reserve
                    or freeze["scientific_wall_nanoseconds"]
                    != capacity_receipt.get(
                        "selected_population_wall_nanoseconds")
                    or freeze["scientific_token_budget"]
                    != _selected_scientific_token_budget(capacity_receipt)):
                raise RPCSupervisorError("scientific freeze execution drift")
        if per_call_token_reserve is None:
            per_call_token_reserve = 1
        if per_call_wall_reserve_milliseconds is None:
            per_call_wall_reserve_milliseconds = 91_000
        self.ledger = ledger
        if require_full_population and self.ledger is None:
            raise RPCSupervisorError("scientific global ledger required")
        if self.ledger is not None and (
                self.ledger.boot_identity_sha256
                != self.runtime["boot_identity_sha256"]
                or self.ledger.runtime_sha256 != _sha(self.runtime)
                or self.ledger.capacity_receipt_sha256
                != self.capacity_receipt.get("receipt_sha256")
                or self.ledger.namespace != ledger_namespace
                or self.ledger.reserve_tokens != per_call_token_reserve
                or self.ledger.reserve_wall_ms
                != per_call_wall_reserve_milliseconds
                or self.ledger.wall_ns != self.capacity_receipt.get(
                    "selected_population_wall_nanoseconds")
                or self.ledger.token_cap \
                != _selected_scientific_token_budget(self.capacity_receipt)
                or self.ledger.root.resolve()
                != (self.private_root.resolve() / "ledger")):
            raise RPCSupervisorError("scientific ledger binding drift")
        _mkdir_private(self.private_root, "private supervisor root")
        self.public_root.mkdir(mode=0o755, parents=True, exist_ok=True)
        if self.public_root.is_symlink() or not self.public_root.is_dir():
            raise RPCSupervisorError("public supervisor root drift")
        self.workers = selected
        self.stop_event = getattr(runner, "stop_event", None) or threading.Event()
        if hasattr(runner, "stop_event"):
            runner.stop_event = self.stop_event
        self._lock = threading.Lock()
        self._progress_lock = threading.Lock()
        # Construction is deliberately side-effect-compatible with restart,
        # but execution is one-shot.  Acquire the cross-process lock only when
        # run() starts: a constructor refusal must never leak a descriptor and
        # poison a valid fresh-process restart.  The local guard also prevents
        # two threads from dispatching the same pending population through one
        # supervisor instance.
        self._run_state_lock = threading.Lock()
        self._run_claimed = False
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

    def _admission_body(self) -> dict[str, object]:
        claim = self.admission.get("review_claim")
        freeze_sha = (claim.get("freeze_sha256")
                      if isinstance(claim, Mapping) else None)
        if freeze_sha is None:
            freeze_sha = _sha(self.admission)
        return {"schema": ADMISSION_SCHEMA,
                "capacity_route": self.capacity_route,
                "schedule_sha256": _schedule_sha(self.schedule),
                "census_sha256": self.census_sha256,
                "capacity_receipt_sha256": self.capacity_receipt.get(
                    "receipt_sha256", _sha(self.capacity_receipt)),
                "runtime_sha256": _sha(self.runtime),
                "freeze_sha256": freeze_sha,
                "game_count": len(self.schedule),
                "cluster_count": len({item[0] for item in self.schedule}),
                "authority": dict(selfplay.AUTHORITY)}

    def _publish_launch(self) -> None:
        body = self._admission_body()
        admission = {**body, "receipt_sha256": _sha(body)}
        _publish(self.private_root / "census.json", self.census)
        _publish(self.public_root / "admission.json", admission)
        launch_body = {"schema": LAUNCH_SCHEMA,
                        "capacity_route": self.capacity_route,
                        "planned_games": len(self.schedule),
                        "planned_deal_clusters": len({
                            coordinate for coordinate, _ in self.schedule}),
                        "selected_workers": self.workers,
                        "attempt_namespace_sha256": _sha(str(self.attempts_root)),
                        "authority": dict(selfplay.AUTHORITY)}
        _publish(self.public_root / "launch.json",
                 {**launch_body, "receipt_sha256": _sha(launch_body)})

    def _reopen_one(self, coordinate, mirror) -> AttemptReopen | None:
        path = _attempt_path(self.attempts_root, coordinate, mirror)
        if not path.exists():
            return None
        try:
            return reopen_attempt(path, seed_secret=self.seed_secret,
                                  expected_runtime_sha256=getattr(
                                      self.runner, "runtime_sha256", None),
                                  expected_scientific_binding_sha256=getattr(
                                      self.runner,
                                      "scientific_binding_sha256", None),
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
            "authority": dict(selfplay.AUTHORITY),
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
        terminal_route = route
        terminal_schema = TERMINAL_SCHEMA
        if not self.scientific:
            terminal_schema = CASUAL_TERMINAL_SCHEMA
            terminal_route = (CASUAL_COMPLETE_ROUTE
                              if route == selfplay.COMPLETE_ROUTE
                              else CASUAL_INCOMPLETE_ROUTE)
        body = {"schema": terminal_schema, "route": terminal_route,
                "schedule_sha256": self._admission_body()["schedule_sha256"],
                "census_sha256": self.census_sha256,
                "admission_sha256": _sha(self._admission_body()),
                "attempt_manifest": rows,
                "completed_games": sum(row["status"] == "complete" for row in rows),
                "completed_deal_clusters": sum(
                    all(row["status"] == "complete" for row in rows
                        if row["coordinate"] == list(coordinate))
                    for coordinate in {item[0] for item in self.schedule}),
                "failed_games": sum(row["status"] == "incomplete" for row in rows),
                "pending_games": sum(row["status"] is None for row in rows),
                "resource_totals": self._resource_totals(),
                "pilot_attempt_lineage": self.pilot_attempt_lineage,
                "ledger_terminal_accept_sha256":
                    ledger_terminal_accept_sha256,
                "authority": dict(selfplay.AUTHORITY)}
        if not self.scientific:
            body["scientific"] = False
        if _forbidden(body):
            raise RPCSupervisorError("public terminal privacy drift")
        return {**body, "receipt_sha256": _sha(body)}

    def _derive_route(self) -> str:
        invalid_sealed_slots = [
            (coordinate, mirror)
            for coordinate, mirror in self.schedule
            if self._statuses.get((coordinate, mirror)) is None
            and (((manifest := _attempt_path(
                self.attempts_root, coordinate, mirror) / "manifest.json"
            ).exists() or manifest.is_symlink())
                 or self._has_controller_refusal(coordinate, mirror))
        ]
        if invalid_sealed_slots:
            return REFUSE_MECHANICS_OR_PRIVACY
        if self.scientific and self.ledger is not None:
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
            if result is not None and result.status == "incomplete"
            and result.failure_class is not None]
        if any(item == "mechanics-privacy" for item in classes):
            return REFUSE_MECHANICS_OR_PRIVACY
        if any(item == "resource-provider" for item in classes):
            return REFUSE_RESOURCE_OR_PROVIDER
        if any(result is None or result.status == "incomplete"
               for result in self._statuses.values()):
            return selfplay.INCOMPLETE_ROUTE
        return selfplay.COMPLETE_ROUTE

    def _pre_dispatch_refusal_route(self) -> str | None:
        """Refuse durable occupied-slot/ledger defects before any new call."""
        invalid_sealed = any(
            self._statuses.get((coordinate, mirror)) is None
            and (((manifest := _attempt_path(
                self.attempts_root, coordinate, mirror) / "manifest.json"
            ).exists() or manifest.is_symlink())
                 or self._has_controller_refusal(coordinate, mirror))
            for coordinate, mirror in self.schedule)
        if invalid_sealed:
            return REFUSE_MECHANICS_OR_PRIVACY
        if self.scientific and self.ledger is not None:
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

    def _run_locked(self) -> SupervisorResult:
        terminal_path = self.public_root / "terminal.json"
        try:
            recover_linked_partial(terminal_path)
        except AtomicPublishError as exc:
            raise RPCSupervisorError("terminal recovery drift") from exc
        if terminal_path.exists():
            try:
                descriptor = os.open(
                    terminal_path,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    before = os.fstat(descriptor)
                    if before.st_size > 16 << 20:
                        raise RPCSupervisorError("terminal size drift")
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
                receipt = json.loads(raw.decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RPCSupervisorError("terminal reopen failed") from exc
            identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns",
                        "st_ctime_ns")
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != 0o400
                    or any(getattr(before, key) != getattr(after, key)
                           for key in identity)
                    or canonical_json_bytes(receipt) != raw):
                raise RPCSupervisorError("terminal canonical bytes drift")
            if self.scientific:
                validate_terminal_receipt(receipt)
            else:
                _validate_casual_terminal_receipt(receipt)
            self._publish_launch()
            self._load_existing()
            for coordinate, mirror in self.schedule:
                if (coordinate, mirror) not in self._statuses:
                    self._statuses[(coordinate, mirror)] = self._reopen_one(
                        coordinate, mirror)
            stored_accept = receipt["ledger_terminal_accept_sha256"]
            attempt_route = self._derive_route()
            if self.ledger is not None \
                    and attempt_route == selfplay.COMPLETE_ROUTE:
                if stored_accept is None:
                    try:
                        self.ledger.assert_within_limits()
                    except ResourceBoundaryError:
                        expected_route = REFUSE_RESOURCE_OR_PROVIDER
                    else:
                        raise RPCSupervisorError(
                            "terminal ledger acceptance absent")
                else:
                    if self.ledger.terminal_acceptance_sha256() \
                            != stored_accept:
                        raise RPCSupervisorError(
                            "terminal ledger acceptance drift")
                    expected_route = attempt_route
            else:
                if stored_accept is not None:
                    raise RPCSupervisorError(
                        "non-complete terminal acceptance drift")
                expected_route = attempt_route
            expected = self._terminal(
                expected_route,
                ledger_terminal_accept_sha256=stored_accept)
            if receipt != expected:
                raise RPCSupervisorError(
                    "terminal independent reconstruction drift")
            return SupervisorResult(receipt["route"], receipt)
        self._publish_launch()
        self._load_existing()
        pre_dispatch_refusal = self._pre_dispatch_refusal_route()
        if pre_dispatch_refusal is not None:
            for coordinate, mirror in self.schedule:
                self._statuses.setdefault((coordinate, mirror), None)
            self._progress(active_workers=0, active_rpcs=0)
            receipt = self._terminal(pre_dispatch_refusal)
            if self.scientific:
                validate_terminal_receipt(receipt)
            else:
                _validate_casual_terminal_receipt(receipt)
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
        if self.scientific:
            validate_terminal_receipt(receipt)
        else:
            _validate_casual_terminal_receipt(receipt)
        _publish(terminal_path, receipt)
        return SupervisorResult(receipt["route"], receipt)

    def run(self) -> SupervisorResult:
        if not self._run_state_lock.acquire(blocking=False):
            raise RPCSupervisorError("supervisor run already active")
        try:
            if self.scientific:
                if self._run_claimed:
                    raise RPCSupervisorError("scientific run already claimed")
                self._run_claimed = True
                self._run_lock_fd = _acquire_scientific_run_lock(
                    self.private_root)
            try:
                return self._run_locked()
            finally:
                if self._run_lock_fd is not None:
                    descriptor = self._run_lock_fd
                    self._run_lock_fd = None
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    finally:
                        os.close(descriptor)
        finally:
            self._run_state_lock.release()


def run_population(**kwargs) -> dict[str, object]:
    """Formal public entry; injected casual probes use the class directly."""
    if kwargs.get("require_full_population", True) is not True \
            or kwargs.get("runner") is not None \
            or kwargs.get("ledger") is not None \
            or kwargs.get("schedule") is not None \
            or kwargs.get("expected_schedule") is not None:
        raise RPCSupervisorError("formal population entry injection refused")
    kwargs["require_full_population"] = True
    result = PTLunaRPCSupervisor(**kwargs).run()
    return dict(result.receipt)


Supervisor = PTLunaRPCSupervisor
PopulationSupervisor = PTLunaRPCSupervisor
run_collection = run_population


__all__ = ["ADMISSION_SCHEMA", "FREEZE_SCHEMA", "FREEZE_REVIEW_PREFIX",
           "FREEZE_REVIEW_SCHEMA", "LAUNCH_SCHEMA", "PROGRESS_SCHEMA",
           "FULL_104_ELIGIBLE", "PILOT_32_ELIGIBLE",
           "ROUTES", "COMPLETE_STATE_SOURCE_ACQUISITION",
           "REFUSE_MECHANICS_OR_PRIVACY", "REFUSE_RESOURCE_OR_PROVIDER",
           "INCOMPLETE_STATE_SOURCE_ACQUISITION", "RPCSupervisorError",
           "SupervisorResult", "TERMINAL_SCHEMA",
           "SOURCE_REVIEW_PREFIX", "SOURCE_REVIEW_SCHEMA",
           "PTLunaRPCSupervisor", "Supervisor", "build_root_census",
           "authenticate_review_claim", "freeze_review_claim",
           "launch_freeze_payload", "source_review_claim",
           "validate_capacity_runtime_for_freeze",
           "validate_capacity_source_for_freeze",
           "validate_launch_freeze", "validate_launch_freeze_shape",
           "validate_root_census", "validate_schedule",
           "schedule_for_capacity_route",
           "validate_terminal_receipt", "run_population", "run_collection",
           "PopulationSupervisor"]
