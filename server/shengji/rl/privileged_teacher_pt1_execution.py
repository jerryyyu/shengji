"""Bounded, recoverable scientific PT1 execution boundary.

The execution lane owns orchestration only.  Capture is performed through the
natural PT1 provider and each worker invokes the existing shared evaluator
batch, while the filesystem contains hashes, records and receipts only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import platform
import resource
import socket
import stat
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, Sequence

from .privileged_teacher_pt0 import canonical_json_bytes
from .privileged_teacher_pt1 import (
    AUTHORITY as PT1_AUTHORITY, PT1Record, evaluate_state_batch, verify_record)
from .privileged_teacher_pt1_capacity import (
    CAPACITY_AUTHORITIES, CAPACITY_STATE_COUNT, CapacityDesign, PT1CapacityError,
    verify_capacity_report, verify_manifest)
from .privileged_teacher_pt1_natural import (
    NATURAL_PT1_STATE_SCHEMA, TARGET_STATE_COUNT, NaturalPT1Design,
    NaturalPT1State, _capture_id_sha256, _capture_round,
    _capture_round_seed, _cluster_sha256, _first_eligible, _state_from_round,
    capture_natural_states, validate_population)
from .privileged_teacher_pt1_statistics import (
    POLICY_SEEDS, PT1PopulationStateIdentity, PT1StatisticsReport,
    reduce_reopened_pt1_statistics,
    verify_statistics_report)


EXECUTION_SCHEMA = "privileged-teacher-pt1-execution-v1"
FREEZE_SCHEMA = "privileged-teacher-pt1-freeze-v3"
GROUP_SCHEMA = "privileged-teacher-pt1-execution-group-v1"
PROGRESS_SCHEMA = "privileged-teacher-pt1-execution-progress-v1"
MANIFEST_SCHEMA = "privileged-teacher-pt1-execution-manifest-v1"
POPULATION_MANIFEST_SCHEMA = "privileged-teacher-pt1-population-manifest-v1"
FAILURE_SCHEMA = "privileged-teacher-pt1-execution-failure-v2"
REVIEW_MARKER_SCHEMA = "privileged-teacher-pt1-execution-review-v2"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
GROUP_DIR = "groups"
FREEZE_NAME = "freeze.json"
PROGRESS_NAME = "progress.json"
DEADLINE_NAME = "deadline-receipt.json"
PACKET_NAME = "packet.json"
MANIFEST_NAME = "manifest.json"
FAILURE_NAME = "failure.json"
CAPACITY_RESERVE_KEYS = {"wall_nanoseconds", "cpu_nanoseconds",
                         "peak_rss_raw", "artifact_projection_bytes"}
SCIENTIFIC_CAP_KEYS = {"scientific_wall_nanoseconds", "scientific_cpu_nanoseconds",
                       "peak_rss_bytes", "scientific_artifact_bytes",
                       "exact_nodes_per_state", "scientific_exact_nodes"}
WORK_KEYS = {"n_determinizations", "report_worlds", "selection_attempts",
             "selection_worlds", "report_attempts", "report_worlds_accepted",
             "searches", "attempted_rollouts", "completed_rollouts",
             "exact_nodes", "exact_cache_hits"}
AUTHORITIES = {
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "training_authorized": False,
    "retry_authorized": False,
    "merge_authorized": False,
}


class PT1ExecutionError(PT1CapacityError):
    """Execution refused an identity, resource, privacy, or authority drift."""


def _sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            c not in "0123456789abcdef" for c in value):
        raise PT1ExecutionError(f"{label} must be a lowercase SHA-256")
    return value


def _git_sha(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 40 or any(
            c not in "0123456789abcdef" for c in value):
        raise PT1ExecutionError(f"{label} must be a Git SHA-1")
    return value


def _canonical_load(raw: bytes, label: str) -> object:
    try:
        value = json.loads(raw.decode("ascii"))
    except Exception as exc:
        raise PT1ExecutionError(f"{label} is not canonical JSON") from exc
    if canonical_json_bytes(value) != raw:
        raise PT1ExecutionError(f"{label} is not canonical JSON")
    return value


def _hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _authority(value: object) -> None:
    if value != AUTHORITIES or value != PT1_AUTHORITY:
        raise PT1ExecutionError("execution authorities must remain false")


def _source_identity(repo_root: Path | None = None) -> dict[str, object]:
    root = repo_root or Path(__file__).resolve().parents[3]
    try:
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain",
             "--untracked-files=all"], text=True,
            stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        raise PT1ExecutionError("execution source identity unavailable") from exc
    _git_sha(head, "execution source Git identity")
    if dirty:
        raise PT1ExecutionError("execution requires exact clean Git source")
    relatives = (
        "server/shengji/rl/privileged_teacher_pt1.py",
        "server/shengji/rl/privileged_teacher_pt1_natural.py",
        "server/shengji/rl/privileged_teacher_pt1_statistics.py",
        "server/shengji/rl/privileged_teacher_pt1_capacity.py",
        "server/shengji/rl/privileged_teacher_pt1_execution.py",
        "server/scripts/privileged_teacher_pt1_execution.py")
    server_root = root / "server"
    if any(path.is_file() for path in server_root.rglob("*.pyc")):
        raise PT1ExecutionError("importable bytecode shadow is present")
    files = []
    for relative in relatives:
        path = root / relative
        if not path.is_file():
            raise PT1ExecutionError("execution source file population incomplete")
        files.append({"path": relative, "sha256": _hash_bytes(path.read_bytes())})
    return {"git_head": head, "source_tree_dirty": False,
            "files": files,
            "files_sha256": _hash_bytes(canonical_json_bytes(files))}


def _boot_identity_bytes() -> bytes:
    if sys.platform == "darwin":
        try:
            boot = subprocess.check_output(
                ["sysctl", "-n", "kern.bootsessionuuid"],
                stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PT1ExecutionError("execution Darwin boot identity unavailable") from exc
    else:
        boot_path = Path("/proc/sys/kernel/random/boot_id")
        if not boot_path.is_file():
            raise PT1ExecutionError("execution boot identity unavailable")
        boot = boot_path.read_bytes().strip()
    if not boot:
        raise PT1ExecutionError("execution boot identity unavailable")
    return boot


def _runtime_identity(worker_count: int) -> dict[str, object]:
    if isinstance(worker_count, bool) or not isinstance(worker_count, int) \
            or worker_count <= 0:
        raise PT1ExecutionError("worker count must be positive")
    try:
        from ..engine import fast
        if (os.environ.get("SHENGJI_FAST") != "1"
                or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
                or not fast.activate()):
            raise PT1ExecutionError(
                "execution requires active compiled engine and strict voids")
        native = Path(getattr(getattr(fast, "_fast", None), "__file__", ""))
    except (ImportError, AttributeError, TypeError):
        native = Path()
    if not native.is_file():
        raise PT1ExecutionError("execution native identity unavailable")
    boot = _boot_identity_bytes()
    executable = Path(sys.executable).resolve()
    if not executable.is_file():
        raise PT1ExecutionError("execution Python identity unavailable")
    return {"hostname": socket.gethostname(),
            "boot_identity_sha256": _hash_bytes(boot),
            "python_version": platform.python_version(),
            "python_executable_sha256": _hash_bytes(executable.read_bytes()),
            "native_extension_sha256": _hash_bytes(native.read_bytes()),
            "compiled_engine": True, "strict_voids": True,
            "worker_count": worker_count}


def build_population_manifest(
        design: NaturalPT1Design,
        states: Mapping[tuple[str, int, str, int, int], NaturalPT1State]) \
        -> dict[str, object]:
    """Bind the complete score-free natural population before admission.

    The manifest intentionally contains identities only.  It exposes no
    action, score, arm, or teacher value, but makes the exact 416 natural
    cells reviewable before the one-shot execution namespace is created.
    """
    validate_population(design, states)
    records = []
    for key in design.state_keys:
        state = states[key]
        records.append({
            "state_key": list(key), "state_schema": state.schema,
            "round_seed": state.round_seed,
            "capture_round_cluster_sha256": state.capture_round_cluster_sha256,
            "capture_id_sha256": state.capture_id_sha256,
            "public_state_sha256": state.public_state_sha256,
            "true_world_sha256": state.true_world_sha256,
        })
    body = {
        "schema": POPULATION_MANIFEST_SCHEMA,
        "design_sha256": _hash_bytes(canonical_json_bytes(design.payload())),
        "capture_secret_sha256": design.capture_secret_sha256,
        "record_count": len(records), "records": records,
        "authority": dict(AUTHORITIES),
    }
    body["manifest_sha256"] = _hash_bytes(canonical_json_bytes(body))
    return body


def verify_population_manifest(
        manifest: Mapping[str, object] | bytes,
        design: NaturalPT1Design) -> dict[str, object]:
    value = (_canonical_load(manifest, "population manifest")
             if isinstance(manifest, bytes) else copy.deepcopy(dict(manifest)))
    fields = {"schema", "design_sha256", "capture_secret_sha256",
              "record_count", "records", "authority", "manifest_sha256"}
    if (not isinstance(value, dict) or set(value) != fields
            or value.get("schema") != POPULATION_MANIFEST_SCHEMA
            or value.get("design_sha256")
            != _hash_bytes(canonical_json_bytes(design.payload()))
            or value.get("capture_secret_sha256")
            != design.capture_secret_sha256
            or value.get("record_count") != TARGET_STATE_COUNT
            or value.get("authority") != AUTHORITIES):
        raise PT1ExecutionError("population manifest identity drift")
    claimed = value.get("manifest_sha256")
    _sha(claimed, "population manifest")
    body = dict(value); body.pop("manifest_sha256")
    if claimed != _hash_bytes(canonical_json_bytes(body)):
        raise PT1ExecutionError("population manifest hash drift")
    records = value.get("records")
    if not isinstance(records, list) or len(records) != TARGET_STATE_COUNT:
        raise PT1ExecutionError("population manifest record population drift")
    expected_fields = {"state_key", "state_schema", "round_seed",
                       "capture_round_cluster_sha256", "capture_id_sha256",
                       "public_state_sha256", "true_world_sha256"}
    seeds, clusters, capture_ids = set(), set(), set()
    for expected_key, record in zip(design.state_keys, records, strict=True):
        if (not isinstance(record, dict) or set(record) != expected_fields
                or record.get("state_key") != list(expected_key)
                or record.get("state_schema") != NATURAL_PT1_STATE_SCHEMA
                or isinstance(record.get("round_seed"), bool)
                or not isinstance(record.get("round_seed"), int)
                or record["round_seed"] < 0):
            raise PT1ExecutionError("population manifest record identity drift")
        for name in ("capture_round_cluster_sha256", "capture_id_sha256",
                     "public_state_sha256", "true_world_sha256"):
            _sha(record.get(name), f"population manifest {name}")
        if (record["capture_round_cluster_sha256"]
                != _cluster_sha256(record["round_seed"])
                or record["capture_id_sha256"] != _capture_id_sha256(
                    expected_key[0], expected_key[1], expected_key[2],
                    expected_key[3], expected_key[4],
                    record["public_state_sha256"])
                or record["round_seed"] in seeds
                or record["capture_round_cluster_sha256"] in clusters
                or record["capture_id_sha256"] in capture_ids):
            raise PT1ExecutionError("population manifest natural identity drift")
        seeds.add(record["round_seed"])
        clusters.add(record["capture_round_cluster_sha256"])
        capture_ids.add(record["capture_id_sha256"])
    return value


def _population_record(freeze: "PT1ExecutionFreeze", index: int) \
        -> Mapping[str, object]:
    records = freeze.population_manifest["records"]
    return records[index]


def _require_population_identity(state: object,
                                 record: Mapping[str, object]) -> None:
    def field(name: str) -> object:
        return (state.get(name) if isinstance(state, Mapping)
                else getattr(state, name, None))
    if any((
            (field("state_schema") if isinstance(state, Mapping)
             else field("schema")) != record["state_schema"],
            field("round_seed") != record["round_seed"],
            field("capture_round_cluster_sha256")
            != record["capture_round_cluster_sha256"],
            field("capture_id_sha256")
            != record["capture_id_sha256"],
            field("public_state_sha256")
            != record["public_state_sha256"],
            field("true_world_sha256")
            != record["true_world_sha256"])):
        raise PT1ExecutionError("execution state differs from frozen population")


def _review_marker_claim(marker: bytes) -> dict[str, object]:
    value = _canonical_load(marker, "review marker")
    if not isinstance(value, dict) or set(value) != {
            "schema", "source_git", "design_sha256", "capacity_report_sha256",
            "capacity_manifest_sha256", "population_manifest_sha256",
            "authority"}:
        raise PT1ExecutionError("review marker fields drift")
    if value["schema"] != REVIEW_MARKER_SCHEMA:
        raise PT1ExecutionError("review marker schema drift")
    _git_sha(value["source_git"], "review marker source")
    _sha(value["design_sha256"], "review marker design")
    _sha(value["capacity_report_sha256"], "review marker capacity")
    _sha(value["capacity_manifest_sha256"], "review marker manifest")
    _sha(value["population_manifest_sha256"],
         "review marker population manifest")
    _authority(value["authority"])
    return value


def authenticate_review_marker(marker: bytes, freeze: "PT1ExecutionFreeze",
                               *, review_commit: str,
                               repo_root: Path | None = None) -> dict[str, object]:
    """Admit only the exact marker added by one authentic review commit.

    The production path authenticates the real GitHub ``main`` tip and
    append-only review ledger.
    The review commit is deliberately external to the marker, avoiding an
    impossible self-referential commit-hash fixed point.
    """
    claim = _review_marker_claim(marker)
    if claim["design_sha256"] != freeze.design_sha256 \
            or claim["capacity_report_sha256"] != freeze.capacity_report_sha256 \
            or claim["capacity_manifest_sha256"] != freeze.capacity_manifest_sha256 \
            or claim["population_manifest_sha256"] \
            != freeze.population_manifest_sha256 \
            or claim["source_git"] != freeze.source.get("git_head") \
            or marker != canonical_json_bytes(dict(freeze.review_marker)) \
            or _hash_bytes(marker) != freeze.review_marker_sha256:
        raise PT1ExecutionError("review marker does not bind freeze/source")
    _git_sha(review_commit, "review commit")
    root = repo_root or Path(__file__).resolve().parents[3]
    _authenticate_review_provenance(root, review_commit, marker)
    return claim


def _authenticate_review_provenance(root: Path, review_commit: str,
                                    marker: bytes) -> None:
    """Authenticate the external review; tests replace this private seam."""
    try:
        probe = subprocess.run(
            ["git", "ls-remote", "--exit-code", CANONICAL_REMOTE_URL,
             CANONICAL_REMOTE_REF], cwd=root, check=True,
            capture_output=True, text=True)
        rows = probe.stdout.splitlines()
        if len(rows) != 1 or rows[0].split()[1:] != [CANONICAL_REMOTE_REF]:
            raise PT1ExecutionError("canonical remote population drift")
        remote_tip = rows[0].split()[0]
        _git_sha(remote_tip, "canonical remote tip")
        local_tip = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "origin/main"],
            text=True).strip()
        if local_tip != remote_tip:
            raise PT1ExecutionError("local canonical ref differs from real remote")
        if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                           review_commit, remote_tip],
                          capture_output=True).returncode != 0:
            raise PT1ExecutionError("review commit is not on canonical remote")
        parents = subprocess.check_output(
            ["git", "-C", str(root), "show", "-s", "--format=%P",
             review_commit], text=True).split()
        identity = tuple(subprocess.check_output(
            ["git", "-C", str(root), "show", "-s", f"--format={field}",
             review_commit], text=True).strip()
                         for field in ("%an", "%ae", "%cn", "%ce"))
        body = subprocess.check_output(
            ["git", "-C", str(root), "show", "-s", "--format=%B",
             review_commit], text=True)
        changed = subprocess.check_output(
            ["git", "-C", str(root), "diff-tree", "--no-commit-id",
             "--name-only", "-r", review_commit], text=True).splitlines()
        current = subprocess.check_output(
            ["git", "-C", str(root), "show", f"{review_commit}:{REVIEW_LEDGER}"])
        previous = subprocess.check_output(
            ["git", "-C", str(root), "show", f"{parents[0]}:{REVIEW_LEDGER}"])
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        raise PT1ExecutionError("review marker provenance unavailable") from exc
    if len(parents) != 1 \
            or identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                            REVIEWER_NAME, REVIEWER_EMAIL) \
            or REVIEWER_SESSION_TRAILER not in body \
            or changed != [REVIEW_LEDGER] \
            or not current.startswith(previous) \
            or [line for line in current.splitlines(keepends=True)
                if line == marker] != [marker] \
            or any(line == marker for line in previous.splitlines(keepends=True)):
        raise PT1ExecutionError("review marker reviewer provenance drift")
    return None


@dataclass(frozen=True)
class PT1ExecutionFreeze:
    design_sha256: str
    scientific_capture_secret_sha256: str
    capacity_report_sha256: str
    capacity_manifest_sha256: str
    population_manifest_sha256: str
    population_manifest: Mapping[str, object]
    capacity_caps: Mapping[str, int]
    capacity_runtime: Mapping[str, object]
    source: Mapping[str, object]
    runtime: Mapping[str, object]
    state_keys: tuple[tuple[str, int, str, int, int], ...]
    seeds: tuple[int, ...]
    deadline_nanoseconds: int | None
    evidence_root: str
    resume_allowed: bool
    review_marker_sha256: str
    review_marker: Mapping[str, object]
    worker_count: int = 10
    authority: Mapping[str, bool] = None  # type: ignore[assignment]
    schema: str = FREEZE_SCHEMA

    def __post_init__(self) -> None:
        _sha(self.design_sha256, "freeze design")
        _sha(self.scientific_capture_secret_sha256, "scientific secret commitment")
        _sha(self.capacity_report_sha256, "capacity report")
        _sha(self.capacity_manifest_sha256, "capacity manifest")
        _sha(self.population_manifest_sha256, "population manifest")
        natural = NaturalPT1Design(self.scientific_capture_secret_sha256)
        manifest = verify_population_manifest(self.population_manifest, natural)
        if (_hash_bytes(canonical_json_bytes(manifest))
                != self.population_manifest_sha256):
            raise PT1ExecutionError("freeze population manifest byte drift")
        if type(self.capacity_caps) is not dict:
            raise PT1ExecutionError("freeze capacity caps drift")
        if any(type(v) is not int or v < 0 for v in self.capacity_caps.values()):
            raise PT1ExecutionError("freeze capacity cap values drift")
        if type(self.capacity_runtime) is not dict:
            raise PT1ExecutionError("freeze capacity runtime drift")
        if tuple(self.seeds) != POLICY_SEEDS:
            raise PT1ExecutionError("freeze requires policy seeds 0,1,2,3")
        if self.deadline_nanoseconds is not None and (
                type(self.deadline_nanoseconds) is not int
                or self.deadline_nanoseconds <= 0):
            raise PT1ExecutionError("freeze deadline drift")
        if type(self.evidence_root) is not str or not os.path.isabs(self.evidence_root):
            raise PT1ExecutionError("freeze evidence root must be absolute")
        if type(self.resume_allowed) is not bool:
            raise PT1ExecutionError("freeze resume flag drift")
        _sha(self.review_marker_sha256, "freeze review marker")
        if tuple(self.state_keys) != natural.state_keys:
            raise PT1ExecutionError("freeze state-key population drift")
        if self.worker_count <= 0 or isinstance(self.worker_count, bool):
            raise PT1ExecutionError("freeze worker count drift")
        if type(self.runtime) is not dict \
                or self.runtime.get("worker_count") != self.worker_count \
                or self.runtime.get("compiled_engine") is not True \
                or self.runtime.get("strict_voids") is not True:
            raise PT1ExecutionError("freeze runtime identity drift")
        _authority(self.authority if self.authority is not None else AUTHORITIES)
        _review_marker_claim(canonical_json_bytes(dict(self.review_marker)))

    def payload(self) -> dict[str, object]:
        return {"schema": self.schema, "design_sha256": self.design_sha256,
                "scientific_capture_secret_sha256": self.scientific_capture_secret_sha256,
                "capacity_report_sha256": self.capacity_report_sha256,
                "capacity_manifest_sha256": self.capacity_manifest_sha256,
                "population_manifest_sha256": self.population_manifest_sha256,
                "population_manifest": copy.deepcopy(dict(
                    self.population_manifest)),
                "capacity_caps": dict(self.capacity_caps),
                "capacity_runtime": copy.deepcopy(dict(self.capacity_runtime)),
                "source": copy.deepcopy(dict(self.source)),
                "runtime": copy.deepcopy(dict(self.runtime)),
                "state_keys": [list(key) for key in self.state_keys],
                "seeds": list(self.seeds), "deadline_nanoseconds": self.deadline_nanoseconds,
                "evidence_root": self.evidence_root, "resume_allowed": self.resume_allowed,
                "review_marker_sha256": self.review_marker_sha256,
                "review_marker": copy.deepcopy(dict(self.review_marker)),
                "worker_count": self.worker_count, "authority": dict(AUTHORITIES)}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload())


def freeze_execution(
        *, design_sha256: str, scientific_capture_secret_sha256: str,
        capacity_report: Mapping[str, object] | bytes,
        capacity_manifest: Mapping[str, object],
        population_manifest: Mapping[str, object] | bytes,
        review_marker: bytes | None = None,
        evidence_root: str | os.PathLike[str], deadline_nanoseconds: int | None,
        worker_count: int = 10, resume_allowed: bool = False,
        source: Mapping[str, object] | None = None,
        runtime: Mapping[str, object] | None = None) -> PT1ExecutionFreeze:
    report = verify_capacity_report(capacity_report)
    manifest = dict(capacity_manifest)
    verify_manifest(manifest, report)
    report_bytes = report.canonical_bytes()
    manifest_bytes = canonical_json_bytes(manifest)
    report_payload = report.payload()
    if (report_payload.get("status") != "COMPLETE"
            or report_payload.get("record_count") != CAPACITY_STATE_COUNT
            or report_payload.get("total_record_count") != CAPACITY_STATE_COUNT
            or report_payload.get("truncated_by_deadline") is not False):
        raise PT1ExecutionError(
            f"capacity receipt must be complete {CAPACITY_STATE_COUNT}/"
            f"{CAPACITY_STATE_COUNT}")
    if report_payload.get("parallel_workers") != worker_count:
        raise PT1ExecutionError("capacity worker count does not match freeze")
    caps = report_payload.get("caps")
    if type(caps) is not dict or set(caps) != SCIENTIFIC_CAP_KEYS \
            or any(type(value) is not int or value < 0 for value in caps.values()):
        raise PT1ExecutionError("capacity report scientific cap contract drift")
    if (deadline_nanoseconds is None or type(deadline_nanoseconds) is not int
            or deadline_nanoseconds <= 0
            or deadline_nanoseconds > caps["scientific_wall_nanoseconds"]):
        raise PT1ExecutionError("freeze deadline must be positive and within capacity")
    capacity_commitment = report_payload["capture_secret_sha256"]
    _sha(scientific_capture_secret_sha256, "scientific secret commitment")
    if scientific_capture_secret_sha256 == capacity_commitment:
        raise PT1ExecutionError("scientific and capacity secret commitments must differ")
    natural = NaturalPT1Design(scientific_capture_secret_sha256)
    if design_sha256 != _hash_bytes(canonical_json_bytes(natural.payload())):
        raise PT1ExecutionError("freeze natural design identity drift")
    population_value = verify_population_manifest(population_manifest, natural)
    population_bytes = canonical_json_bytes(population_value)
    source_value = dict(source) if source is not None else _source_identity()
    runtime_value = dict(runtime) if runtime is not None else _runtime_identity(worker_count)
    _git_sha(source_value.get("git_head"), "freeze source")
    if source_value.get("source_tree_dirty") is not False:
        raise PT1ExecutionError("freeze source must be clean")
    expected_marker_claim = {
        "schema": REVIEW_MARKER_SCHEMA,
        "source_git": source_value["git_head"],
        "design_sha256": design_sha256,
        "capacity_report_sha256": _hash_bytes(report_bytes),
        "capacity_manifest_sha256": _hash_bytes(manifest_bytes),
        "population_manifest_sha256": _hash_bytes(population_bytes),
        "authority": dict(AUTHORITIES)}
    if review_marker is None:
        marker_claim = expected_marker_claim
        review_marker = canonical_json_bytes(marker_claim)
    else:
        marker_claim = _review_marker_claim(review_marker)
        if marker_claim != expected_marker_claim:
            raise PT1ExecutionError("review marker claim does not bind freeze inputs")
    _authority(AUTHORITIES)
    root = str(Path(evidence_root).expanduser().resolve())
    marker_claim = copy.deepcopy(marker_claim)
    return PT1ExecutionFreeze(
        design_sha256, scientific_capture_secret_sha256, _hash_bytes(report_bytes),
        _hash_bytes(manifest_bytes), _hash_bytes(population_bytes),
        population_value, dict(caps),
        dict(report_payload.get("runtime", {})), source_value,
        runtime_value, natural.state_keys, POLICY_SEEDS, deadline_nanoseconds,
        root, resume_allowed, _hash_bytes(review_marker), marker_claim,
        worker_count, dict(AUTHORITIES))


def verify_freeze(freeze: PT1ExecutionFreeze | Mapping[str, object] | bytes) -> PT1ExecutionFreeze:
    if isinstance(freeze, bytes):
        value = _canonical_load(freeze, "freeze")
    elif isinstance(freeze, PT1ExecutionFreeze):
        value = freeze.payload()
    elif isinstance(freeze, Mapping):
        value = copy.deepcopy(dict(freeze))
    else:
        raise PT1ExecutionError("freeze type refused")
    required = set(PT1ExecutionFreeze.__dataclass_fields__) - {"schema"}
    required |= {"schema"}
    if set(value) != required or value["schema"] != FREEZE_SCHEMA:
        raise PT1ExecutionError("freeze fields/schema drift")
    try:
        state_keys = tuple(tuple(key) for key in value["state_keys"])
        typed = PT1ExecutionFreeze(
            value["design_sha256"], value["scientific_capture_secret_sha256"],
            value["capacity_report_sha256"], value["capacity_manifest_sha256"],
            value["population_manifest_sha256"], value["population_manifest"],
            value["capacity_caps"], value["capacity_runtime"], value["source"],
            value["runtime"], state_keys,
            tuple(value["seeds"]), value["deadline_nanoseconds"], value["evidence_root"],
            value["resume_allowed"], value["review_marker_sha256"], value["review_marker"],
            value["worker_count"], value["authority"], value["schema"])
    except PT1ExecutionError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PT1ExecutionError("freeze values drift") from exc
    if canonical_json_bytes(typed.payload()) != canonical_json_bytes(value):
        raise PT1ExecutionError("freeze canonical round-trip drift")
    return typed


def _require_live_bindings(freeze: PT1ExecutionFreeze, output_root: Path,
                           *, repo_root: Path | None = None) -> None:
    if output_root.resolve() != Path(freeze.evidence_root).resolve():
        raise PT1ExecutionError("execution output root differs from frozen evidence root")
    live_source = _source_identity(repo_root)
    if live_source != dict(freeze.source):
        raise PT1ExecutionError("execution live source identity drift")
    live_runtime = _runtime_identity(freeze.worker_count)
    if live_runtime != dict(freeze.runtime):
        raise PT1ExecutionError("execution live runtime identity drift")
    try:
        from .privileged_teacher_pt1_capacity import _runtime_identity as capacity_runtime
        if dict(freeze.capacity_runtime) != capacity_runtime():
            raise PT1ExecutionError("execution capacity runtime identity drift")
    except ImportError as exc:
        raise PT1ExecutionError("execution capacity runtime unavailable") from exc


def _require_owned_directory(path: Path, label: str) -> None:
    """Refuse links and pre-existing directories outside the execution owner."""
    try:
        info = path.lstat()
    except OSError as exc:
        raise PT1ExecutionError(f"{label} unavailable") from exc
    if (path.is_symlink() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or (info.st_mode & 0o777) != 0o700):
        raise PT1ExecutionError(f"{label} is not a safe owned directory")


def _group_payload(index: int, key: tuple, state: NaturalPT1State,
                   records: Sequence[PT1Record], wall_ns: int,
                   cpu_ns: int, rss_bytes: int,
                   parallel_wall_ns: int | None = None,
                   parallel_cpu_ns: int | None = None,
                   parallel_rss_bytes: int | None = None) -> dict[str, object]:
    if tuple(key) != (state.rank, state.banker, state.role,
                      state.remaining_hand_threshold, state.replicate):
        raise PT1ExecutionError("execution state key drift")
    if len(records) != len(POLICY_SEEDS):
        raise PT1ExecutionError("execution group seed count drift")
    for record, seed in zip(records, POLICY_SEEDS):
        verify_record(record)
        if (record.public_state_sha256 != state.public_state_sha256
                or record.true_world_sha256 != state.true_world_sha256
                or any(arm.seed != seed for arm in record.arms)):
            raise PT1ExecutionError("execution group state/seed binding drift")
    artifact_bytes = len(canonical_json_bytes([record.payload()
                                                for record in records]))
    exact_nodes = max(getattr(getattr(record.arms[2], "work", None),
                              "exact_nodes", 0)
                      for record in records)
    return {"schema": GROUP_SCHEMA, "index": index, "state_key": list(key),
            "state_schema": getattr(state, "schema", ""),
            "round_seed": state.round_seed,
            "capture_round_cluster_sha256": state.capture_round_cluster_sha256,
            "capture_id_sha256": state.capture_id_sha256,
            "public_state_sha256": state.public_state_sha256,
            "true_world_sha256": state.true_world_sha256,
            "records": [record.payload() for record in records],
            "wall_nanoseconds": wall_ns, "cpu_nanoseconds": cpu_ns,
            "parallel_wave_wall_nanoseconds": (wall_ns if parallel_wall_ns is None
                                                else parallel_wall_ns),
            "parallel_wave_cpu_nanoseconds": (cpu_ns if parallel_cpu_ns is None
                                               else parallel_cpu_ns),
            "parallel_wave_peak_rss_bytes": (
                rss_bytes if parallel_rss_bytes is None else parallel_rss_bytes),
            "peak_rss_bytes": rss_bytes,
            "exact_nodes": exact_nodes,
            "artifact_projection_bytes": artifact_bytes,
            "authority": dict(AUTHORITIES)}


def _worker(payload: tuple[tuple, NaturalPT1State]) -> tuple[tuple, tuple[PT1Record, ...]]:
    key, state = payload
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    records = evaluate_state_batch(state.public_round, state.true_world, seeds=POLICY_SEEDS)
    return key, tuple(records), time.perf_counter_ns() - started, \
        time.process_time_ns() - cpu_started, \
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
        1 if sys.platform == "darwin" else 1024)


def _scientific_worker(payload: tuple[NaturalPT1Design, bytes, tuple]) -> tuple:
    """Capture and evaluate one state inside the same metered worker."""
    started = time.perf_counter_ns()
    cpu_started = time.process_time_ns()
    key, state = _capture_one_state(payload)
    records = evaluate_state_batch(
        state.public_round, state.true_world, seeds=POLICY_SEEDS)
    identity = PT1PopulationStateIdentity(
        state.rank, state.banker, state.role,
        state.remaining_hand_threshold, state.replicate, state.round_seed,
        state.capture_round_cluster_sha256, state.capture_id_sha256,
        state.public_state_sha256, state.true_world_sha256)
    return (key, identity, tuple(records), time.perf_counter_ns() - started,
            time.process_time_ns() - cpu_started,
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
                1 if sys.platform == "darwin" else 1024))


def _capture_one_state(payload: tuple[NaturalPT1Design, bytes, tuple]) -> tuple[tuple, NaturalPT1State]:
    design, secret, key = payload
    rank, banker, role, threshold, replicate = key
    for attempt in range(design.capture_attempts_per_state):
        round_seed = _capture_round_seed(secret, rank, banker, role,
                                         threshold, replicate, attempt)
        candidate = _capture_round(design, round_seed, rank, banker).get(
            (role, threshold))
        if candidate is None:
            continue
        eligible = _first_eligible(candidate, role=role, threshold=threshold)
        if eligible is not None:
            return key, _state_from_round(
                design, eligible, rank=rank, banker=banker, role=role,
                threshold=threshold, replicate=replicate, round_seed=round_seed)
    raise PT1ExecutionError(f"incomplete natural state cell: {key}")


def _capture_population_parallel(design: NaturalPT1Design, secret: bytes,
                                 workers: int,
                                 executor_factory: Callable[[int], object]) -> dict[tuple, NaturalPT1State]:
    population = {}
    with executor_factory(workers) as executor:
        futures = [executor.submit(_capture_one_state, (design, secret, key))
                   for key in design.state_keys]
        for future in futures:
            key, state = future.result()
            if key in population:
                raise PT1ExecutionError("duplicate captured state returned by worker")
            population[key] = state
    if len(population) != TARGET_STATE_COUNT:
        raise PT1ExecutionError("parallel capture dropped a state")
    return population


def capture_population_manifest(
        *, capture_secret: bytes, worker_count: int = 10,
        executor_factory: Callable[[int], object] | None = None) \
        -> dict[str, object]:
    """Capture and bind all natural cells before a scientific slot exists."""
    if type(capture_secret) is not bytes or len(capture_secret) != 32:
        raise PT1ExecutionError("population capture secret must be 32 bytes")
    if type(worker_count) is not int or isinstance(worker_count, bool) \
            or worker_count <= 0:
        raise PT1ExecutionError("population capture worker count drift")
    _source_identity()
    _runtime_identity(worker_count)
    design = NaturalPT1Design(hashlib.sha256(capture_secret).hexdigest())
    factory = (executor_factory if executor_factory is not None else
               lambda workers: ProcessPoolExecutor(max_workers=workers))
    states = _capture_population_parallel(
        design, capture_secret, worker_count, factory)
    return build_population_manifest(design, states)


def rehearse_process_pool_wave(
        *, capture_secret: bytes, worker_count: int = 10,
        executor_factory: Callable[[int], object] | None = None) \
        -> dict[str, object]:
    """Exercise one real natural-provider/evaluator wave, retaining no score."""
    if type(capture_secret) is not bytes or len(capture_secret) != 32:
        raise PT1ExecutionError("rehearsal secret must be 32 bytes")
    if type(worker_count) is not int or isinstance(worker_count, bool) \
            or worker_count <= 0:
        raise PT1ExecutionError("rehearsal worker count drift")
    source = _source_identity()
    runtime = _runtime_identity(worker_count)
    design = NaturalPT1Design(hashlib.sha256(capture_secret).hexdigest())
    keys = design.state_keys[:worker_count]
    factory = (executor_factory if executor_factory is not None else
               lambda workers: ProcessPoolExecutor(max_workers=workers))
    started = time.perf_counter_ns()
    with factory(worker_count) as executor:
        futures = [executor.submit(
            _scientific_worker, (design, capture_secret, key)) for key in keys]
        results = [future.result() for future in futures]
    identities = []
    total_cpu = 0
    peak_rss = 0
    for expected_key, result in zip(keys, results, strict=True):
        key, state, records, _wall, cpu, rss = result
        if key != expected_key or len(records) != len(POLICY_SEEDS):
            raise PT1ExecutionError("rehearsal worker population drift")
        for record in records:
            verify_record(record)
        identities.append([
            *key, state.round_seed, state.capture_id_sha256,
            state.public_state_sha256, state.true_world_sha256])
        total_cpu += int(cpu)
        peak_rss += int(rss)
    receipt = {
        "schema": "privileged-teacher-pt1-process-pool-rehearsal-v1",
        "source_git": source["git_head"], "runtime": runtime,
        "worker_count": worker_count, "state_count": len(results),
        "record_count": len(results) * len(POLICY_SEEDS),
        "wall_nanoseconds": time.perf_counter_ns() - started,
        "cpu_nanoseconds": total_cpu, "parallel_peak_rss_bytes": peak_rss,
        "identity_population_sha256": _hash_bytes(
            canonical_json_bytes(identities)),
        "score_or_action_bytes_persisted": False,
        "authority": dict(AUTHORITIES),
    }
    receipt["receipt_sha256"] = _hash_bytes(canonical_json_bytes(receipt))
    return receipt


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, data: bytes, *, mode: int = 0o400) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if (not path.is_file() or path.is_symlink() or path.read_bytes() != data
                or path.stat().st_nlink != 1 or (path.stat().st_mode & 0o777) != mode):
            raise PT1ExecutionError(f"immutable artifact mismatch: {path}")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.link(temporary, path); os.chmod(path, mode); _fsync_dir(path.parent)
    except FileExistsError:
        if path.read_bytes() != data:
            raise PT1ExecutionError(f"immutable artifact mismatch: {path}")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary); _fsync_dir(path.parent)


def _immutable_bytes(path: Path, label: str) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PT1ExecutionError(f"{label} is missing") from exc
    if (not path.is_file() or path.is_symlink() or info.st_nlink != 1
            or (info.st_mode & 0o777) != 0o400):
        raise PT1ExecutionError(f"{label} immutable-file drift")
    return path.read_bytes()


def _write_progress(path: Path, payload: Mapping[str, object]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(dict(payload))); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path); _fsync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary); _fsync_dir(path.parent)


def _discard_late_terminal_artifacts(root: Path) -> None:
    """Remove only invalid terminal files produced across the deadline."""
    changed = False
    for name in (PACKET_NAME, MANIFEST_NAME):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            info = path.lstat()
        except OSError as exc:
            raise PT1ExecutionError("late terminal artifact unavailable") from exc
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1 or (info.st_mode & 0o777) != 0o400):
            raise PT1ExecutionError("late terminal artifact is unsafe")
        path.unlink()
        changed = True
    if changed:
        _fsync_dir(root)


def _truncate_at_deadline(freeze: PT1ExecutionFreeze, root: Path,
                          completed: int) -> dict[str, object]:
    _discard_late_terminal_artifacts(root)
    _write_progress(root / PROGRESS_NAME, _progress_payload(
        freeze, completed, "TRUNCATED", 0))
    return {"status": "TRUNCATED", "completed_units": completed,
            "total_units": TARGET_STATE_COUNT,
            "authority": dict(AUTHORITIES)}


def _verify_group_bytes(raw: bytes, index: int,
                        state: NaturalPT1State | None = None, *,
                        key: tuple | None = None) -> dict[str, object]:
    """Verify the exact group bytes supplied by the caller."""
    value = _canonical_load(raw, f"execution group {index}")
    expected_fields = {"schema", "index", "state_key", "state_schema", "round_seed",
                       "capture_round_cluster_sha256", "capture_id_sha256",
                       "public_state_sha256",
                       "true_world_sha256", "records", "wall_nanoseconds",
                       "cpu_nanoseconds", "parallel_wave_wall_nanoseconds",
                       "parallel_wave_cpu_nanoseconds",
                       "parallel_wave_peak_rss_bytes", "peak_rss_bytes", "exact_nodes",
                       "artifact_projection_bytes", "authority"}
    expected_key = key if key is not None else (
        state.rank, state.banker, state.role,
        state.remaining_hand_threshold, state.replicate)
    if not isinstance(value, dict) or set(value) != expected_fields \
            or value.get("schema") != GROUP_SCHEMA \
            or value.get("index") != index \
            or value.get("state_key") != list(expected_key) \
            or value.get("state_schema") != NATURAL_PT1_STATE_SCHEMA \
            or value.get("authority") != AUTHORITIES:
        raise PT1ExecutionError("execution group identity drift")
    for name in ("capture_round_cluster_sha256", "capture_id_sha256",
                 "public_state_sha256", "true_world_sha256"):
        _sha(value.get(name), f"execution group {name}")
    if (isinstance(value.get("round_seed"), bool)
            or not isinstance(value.get("round_seed"), int)
            or value["round_seed"] < 0
            or value["capture_round_cluster_sha256"]
            != _cluster_sha256(value["round_seed"])
            or value["capture_id_sha256"] != _capture_id_sha256(
                expected_key[0], expected_key[1], expected_key[2],
                expected_key[3], expected_key[4],
                value["public_state_sha256"])):
        raise PT1ExecutionError("execution group natural identity drift")
    if state is not None and any((
            value["state_schema"] != state.schema,
            value["round_seed"] != state.round_seed,
            value["capture_round_cluster_sha256"]
            != state.capture_round_cluster_sha256,
            value["capture_id_sha256"] != state.capture_id_sha256,
            value["public_state_sha256"] != state.public_state_sha256,
            value["true_world_sha256"] != state.true_world_sha256)):
        raise PT1ExecutionError("execution group recapture identity drift")
    records = value.get("records")
    if not isinstance(records, list) or len(records) != len(POLICY_SEEDS):
        raise PT1ExecutionError("execution group record population drift")
    typed_records = []
    for record, seed in zip(records, POLICY_SEEDS):
        typed = verify_record(record)
        typed_records.append(typed)
        if typed.public_state_sha256 != value["public_state_sha256"] \
                or typed.true_world_sha256 != value["true_world_sha256"] \
                or any(arm.seed != seed for arm in typed.arms):
            raise PT1ExecutionError("execution group record binding drift")
    for name in ("wall_nanoseconds", "cpu_nanoseconds",
                 "parallel_wave_wall_nanoseconds", "parallel_wave_cpu_nanoseconds",
                 "parallel_wave_peak_rss_bytes",
                 "peak_rss_bytes",
                 "exact_nodes", "artifact_projection_bytes"):
        if type(value.get(name)) is not int or value[name] < 0:
            raise PT1ExecutionError("execution group resource drift")
    expected_artifact = len(canonical_json_bytes(records))
    expected_nodes = max(getattr(getattr(record.arms[2], "work", None),
                                 "exact_nodes", 0)
                         for record in typed_records)
    if value["artifact_projection_bytes"] != expected_artifact \
            or value["exact_nodes"] != expected_nodes:
        raise PT1ExecutionError("execution group resource identity drift")
    return value


def _verify_group(path: Path, index: int,
                  state: NaturalPT1State | None = None, *,
                  key: tuple | None = None) -> dict[str, object]:
    info = path.lstat()
    if (not path.is_file() or path.is_symlink() or info.st_nlink != 1
            or (info.st_mode & 0o777) != 0o400):
        raise PT1ExecutionError("execution group artifact missing or unsafe")
    return _verify_group_bytes(
        _immutable_bytes(path, f"execution group {index}"), index,
        state, key=key)


def _state_from_group(group: Mapping[str, object]) -> PT1PopulationStateIdentity:
    key = group["state_key"]
    return PT1PopulationStateIdentity(
        key[0], key[1], key[2], key[3], key[4], group["round_seed"],
        group["capture_round_cluster_sha256"], group["capture_id_sha256"],
        group["public_state_sha256"], group["true_world_sha256"])


def _resource_totals(groups: Sequence[Mapping[str, object]],
                     worker_count: int) -> dict[str, int]:
    waves = {int(group["index"]) // worker_count: group for group in groups}
    return {
        "scientific_wall_nanoseconds": sum(
            int(group["parallel_wave_wall_nanoseconds"])
            for group in waves.values()),
        "scientific_cpu_nanoseconds": sum(
            int(group["parallel_wave_cpu_nanoseconds"])
            for group in waves.values()),
        "peak_rss_bytes": max((
            int(group["parallel_wave_peak_rss_bytes"])
            for group in waves.values()), default=0),
        "scientific_artifact_bytes": sum(
            int(group["artifact_projection_bytes"]) for group in groups),
        "exact_nodes_per_state": max((
            int(group["exact_nodes"]) for group in groups), default=0),
        "scientific_exact_nodes": sum(
            int(group["exact_nodes"]) for group in groups),
    }


def _resource_cap_overages(
        resources: Mapping[str, int], caps: Mapping[str, int]) \
        -> tuple[dict[str, int | str], ...]:
    """Return the exact score-free resource dimensions above their caps."""
    if set(resources) != SCIENTIFIC_CAP_KEYS or set(caps) != SCIENTIFIC_CAP_KEYS:
        raise PT1ExecutionError("execution scientific cap population drift")
    rows = []
    for name in sorted(SCIENTIFIC_CAP_KEYS):
        observed, cap = resources[name], caps[name]
        if (type(observed) is not int or observed < 0
                or type(cap) is not int or cap < 0):
            raise PT1ExecutionError("execution scientific cap value drift")
        if observed > cap:
            rows.append({"name": name, "observed": observed, "cap": cap,
                         "excess": observed - cap})
    return tuple(rows)


def _validate_resource_overages(value: object) \
        -> tuple[dict[str, int | str], ...]:
    if not isinstance(value, (tuple, list)):
        raise PT1ExecutionError("execution failure resource detail drift")
    rows = []
    names = set()
    for row in value:
        if (type(row) is not dict
                or set(row) != {"name", "observed", "cap", "excess"}
                or row.get("name") not in SCIENTIFIC_CAP_KEYS
                or row["name"] in names
                or type(row.get("observed")) is not int
                or type(row.get("cap")) is not int
                or type(row.get("excess")) is not int
                or row["cap"] < 0 or row["observed"] <= row["cap"]
                or row["excess"] != row["observed"] - row["cap"]):
            raise PT1ExecutionError("execution failure resource detail drift")
        names.add(row["name"])
        rows.append(dict(row))
    if [row["name"] for row in rows] != sorted(names):
        raise PT1ExecutionError("execution failure resource detail drift")
    return tuple(rows)


def _validate_group_population(design: NaturalPT1Design,
                               groups: Sequence[Mapping[str, object]],
                               population_manifest: Mapping[str, object] | None = None) \
        -> dict[tuple, PT1PopulationStateIdentity]:
    if len(groups) != TARGET_STATE_COUNT:
        raise PT1ExecutionError("execution natural population incomplete")
    states = {}
    seeds, clusters, capture_ids = set(), set(), set()
    manifest_records = (population_manifest.get("records")
                        if population_manifest is not None else None)
    for index, (expected_key, group) in enumerate(
            zip(design.state_keys, groups, strict=True)):
        state = _state_from_group(group)
        key = (state.rank, state.banker, state.role,
               state.remaining_hand_threshold, state.replicate)
        if key != expected_key or key in states \
                or state.round_seed in seeds \
                or state.capture_round_cluster_sha256 in clusters \
                or state.capture_id_sha256 in capture_ids:
            raise PT1ExecutionError("execution natural population identity drift")
        if manifest_records is not None:
            _require_population_identity(state, manifest_records[index])
        states[key] = state
        seeds.add(state.round_seed)
        clusters.add(state.capture_round_cluster_sha256)
        capture_ids.add(state.capture_id_sha256)
    return states


def _progress_payload(freeze: PT1ExecutionFreeze, completed: int,
                      status: str, eta_nanoseconds: int = 0) -> dict[str, object]:
    if status not in {"RUNNING", "FINALIZING", "TRUNCATED", "COMPLETE",
                      "FAILED"}:
        raise PT1ExecutionError("execution progress status drift")
    return {"schema": PROGRESS_SCHEMA, "freeze_sha256": _hash_bytes(freeze.canonical_bytes()),
            "completed_units": completed, "total_units": TARGET_STATE_COUNT,
            "percent_basis_points": completed * 10_000 // TARGET_STATE_COUNT,
            "eta_nanoseconds": eta_nanoseconds,
            "status": status, "authority": dict(AUTHORITIES)}


def record_execution_failure(
        freeze: PT1ExecutionFreeze, root: str | os.PathLike[str], *,
        code: str, completed: int | None = None,
        wave_start: int | None = None, wave_stop: int | None = None,
        resource_overages: Sequence[Mapping[str, object]] = ()) \
        -> dict[str, object]:
    """Durably record a score-free terminal failure without child details."""
    typed = verify_freeze(freeze)
    evidence = Path(root).resolve()
    if not evidence.is_dir():
        raise PT1ExecutionError("failure receipt requires initialized evidence")
    published = evidence / FREEZE_NAME
    if (not published.is_file()
            or _immutable_bytes(published, "published freeze")
            != typed.canonical_bytes()):
        raise PT1ExecutionError("failure receipt requires initialized freeze")
    path = evidence / FAILURE_NAME
    if path.exists():
        value = _canonical_load(
            _immutable_bytes(path, "execution failure receipt"),
            "execution failure receipt")
        if (not isinstance(value, dict) or set(value) != {
                "schema", "freeze_sha256", "failure_code", "completed_units",
                "total_units", "wave_start", "wave_stop", "resource_overages",
                "score_or_action_bytes_persisted", "retry_authorized", "authority"}
                or value.get("schema") != FAILURE_SCHEMA
                or value.get("freeze_sha256")
                != _hash_bytes(typed.canonical_bytes())
                or value.get("authority") != AUTHORITIES):
            raise PT1ExecutionError("execution failure receipt drift")
        _validate_resource_overages(value.get("resource_overages"))
        _write_progress(evidence / PROGRESS_NAME, _progress_payload(
            typed, int(value["completed_units"]), "FAILED", 0))
        return value
    if completed is None:
        progress_path = evidence / PROGRESS_NAME
        progress = (_canonical_load(progress_path.read_bytes(), "progress")
                    if progress_path.is_file() else {})
        completed = (progress.get("completed_units", 0)
                     if isinstance(progress, dict) else 0)
    if (type(completed) is not int or not 0 <= completed <= TARGET_STATE_COUNT
            or type(code) is not str
            or code not in {"worker_failure", "cli_failure",
                            "resource_cap_exceeded"}
            or (wave_start is not None and
                (type(wave_start) is not int or wave_start < 0))
            or (wave_stop is not None and
                (type(wave_stop) is not int or wave_stop < 0))):
        raise PT1ExecutionError("execution failure receipt values drift")
    overages = _validate_resource_overages(resource_overages)
    if (code == "resource_cap_exceeded") is not bool(overages):
        raise PT1ExecutionError("execution failure resource detail drift")
    value = {
        "schema": FAILURE_SCHEMA,
        "freeze_sha256": _hash_bytes(typed.canonical_bytes()),
        "failure_code": code, "completed_units": completed,
        "total_units": TARGET_STATE_COUNT,
        "wave_start": wave_start, "wave_stop": wave_stop,
        "resource_overages": list(overages),
        "score_or_action_bytes_persisted": False,
        "retry_authorized": False, "authority": dict(AUTHORITIES),
    }
    _write_once(path, canonical_json_bytes(value))
    _write_progress(evidence / PROGRESS_NAME, _progress_payload(
        typed, completed, "FAILED", 0))
    return value


def _deadline_receipt(freeze: PT1ExecutionFreeze, root: Path,
                      monotonic: Callable[[], float]) -> dict[str, object]:
    path = root / DEADLINE_NAME
    if path.exists():
        value = _canonical_load(
            _immutable_bytes(path, "deadline receipt"), "deadline receipt")
        expected = {"schema": "privileged-teacher-pt1-deadline-v1",
                    "freeze_sha256": _hash_bytes(freeze.canonical_bytes()),
                    "boot_identity_sha256": freeze.runtime.get("boot_identity_sha256"),
                    "started_monotonic_nanoseconds": value.get("started_monotonic_nanoseconds"),
                    "deadline_monotonic_nanoseconds": value.get("deadline_monotonic_nanoseconds")}
        if value != expected or type(value["started_monotonic_nanoseconds"]) is not int \
                or type(value["deadline_monotonic_nanoseconds"]) is not int \
                or value["deadline_monotonic_nanoseconds"] \
                != value["started_monotonic_nanoseconds"] \
                + freeze.deadline_nanoseconds \
                or int(monotonic() * 1_000_000_000) \
                < value["started_monotonic_nanoseconds"]:
            raise PT1ExecutionError("deadline receipt drift")
        return value
    started = int(monotonic() * 1_000_000_000)
    value = {"schema": "privileged-teacher-pt1-deadline-v1",
             "freeze_sha256": _hash_bytes(freeze.canonical_bytes()),
             "boot_identity_sha256": freeze.runtime.get("boot_identity_sha256"),
             "started_monotonic_nanoseconds": started,
             "deadline_monotonic_nanoseconds": started + freeze.deadline_nanoseconds}
    _write_once(path, canonical_json_bytes(value))
    return value


def _verify_deadline_receipt(freeze: PT1ExecutionFreeze,
                             root: Path) -> dict[str, object]:
    value = _canonical_load(
        _immutable_bytes(root / DEADLINE_NAME, "deadline receipt"),
        "deadline receipt")
    if (not isinstance(value, dict)
            or value.get("schema") != "privileged-teacher-pt1-deadline-v1"
            or value.get("freeze_sha256")
            != _hash_bytes(freeze.canonical_bytes())
            or value.get("boot_identity_sha256")
            != freeze.runtime.get("boot_identity_sha256")
            or type(value.get("started_monotonic_nanoseconds")) is not int
            or type(value.get("deadline_monotonic_nanoseconds")) is not int
            or value["deadline_monotonic_nanoseconds"]
            != value["started_monotonic_nanoseconds"]
            + freeze.deadline_nanoseconds):
        raise PT1ExecutionError("deadline receipt drift")
    return value


def initialize_execution(freeze: PT1ExecutionFreeze | Mapping[str, object] | bytes,
                         output_root: str | os.PathLike[str], *,
                         review_marker: bytes | None = None,
                         review_commit: str,
                         repo_root: Path | None = None) -> PT1ExecutionFreeze:
    typed = verify_freeze(freeze)
    raw_root = Path(output_root).expanduser()
    if raw_root.is_symlink():
        raise PT1ExecutionError("execution output symlink refused")
    root = raw_root.absolute()
    _require_live_bindings(typed, root, repo_root=repo_root)
    if review_marker is None:
        raise PT1ExecutionError("initialize requires authenticated review marker")
    authenticate_review_marker(review_marker, typed, review_commit=review_commit,
                               repo_root=repo_root)
    if not root.parent.exists() or root.parent.is_symlink():
        raise PT1ExecutionError("execution evidence parent unavailable")
    if not root.exists():
        root.mkdir(mode=0o700)
    _require_owned_directory(root, "execution output")
    groups = root / GROUP_DIR
    if groups.is_symlink():
        raise PT1ExecutionError("execution group directory is not a safe owned directory")
    if not groups.exists():
        groups.mkdir(mode=0o700)
    _require_owned_directory(groups, "execution group directory")
    _write_once(root / FREEZE_NAME, typed.canonical_bytes())
    if not (root / PROGRESS_NAME).exists():
        _write_progress(root / PROGRESS_NAME, _progress_payload(typed, 0, "RUNNING"))
    return typed


def run_execution(
        freeze: PT1ExecutionFreeze | Mapping[str, object] | bytes,
        *, output_root: str | os.PathLike[str], capture_secret: bytes,
        population: Mapping[tuple[str, int, str, int, int], NaturalPT1State] | None = None,
        state_capture: Callable[..., object] | None = None,
        executor_factory: Callable[[int], object] | None = None,
        worker: Callable[[tuple[tuple, NaturalPT1State]],
                         tuple[tuple, Sequence[PT1Record]]] | None = None,
        review_marker: bytes | None = None,
        review_commit: str,
        repo_root: Path | None = None,
        deadline: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        progress_sink: Callable[[Mapping[str, object]], object] | None = None) -> dict[str, object]:
    typed = verify_freeze(freeze)
    _require_live_bindings(typed, Path(output_root).resolve(), repo_root=repo_root)
    if typed.resume_allowed is not True and (Path(output_root) / FREEZE_NAME).exists():
        # Initial execution may use the same initialized directory; the flag
        # governs recovery after a durable group exists.
        group_dir = Path(output_root) / GROUP_DIR
        if any(group_dir.glob("group-*.json")):
            raise PT1ExecutionError("freeze does not authorize resume")
    if type(capture_secret) is not bytes or len(capture_secret) != 32 \
            or hashlib.sha256(capture_secret).hexdigest() != typed.scientific_capture_secret_sha256:
        raise PT1ExecutionError("scientific capture secret commitment drift")
    natural = NaturalPT1Design(typed.scientific_capture_secret_sha256)
    if executor_factory is None:
        executor_factory = lambda workers: ProcessPoolExecutor(max_workers=workers)
    initialize_execution(typed, output_root, review_marker=review_marker,
                        review_commit=review_commit,
                        repo_root=repo_root)
    root = Path(output_root).resolve()
    if (root / FAILURE_NAME).exists():
        raise PT1ExecutionError("execution failure receipt is terminal")
    receipt = _deadline_receipt(typed, root, monotonic)
    frozen_deadline = receipt["deadline_monotonic_nanoseconds"] / 1e9
    supplied_states = (dict(population) if population is not None else
                       (capture_natural_states(
                           natural, capture_secret=capture_secret,
                           state_capture=state_capture)
                        if state_capture is not None else None))
    if supplied_states is not None:
        try:
            validate_population(natural, supplied_states)
            for index, key in enumerate(natural.state_keys):
                _require_population_identity(
                    supplied_states[key], _population_record(typed, index))
        except Exception as exc:
            raise PT1ExecutionError(
                "scientific natural population refused") from exc
    elif worker is not None:
        raise PT1ExecutionError(
            "custom execution worker requires an explicit test population")
    groups = root / GROUP_DIR
    existing = []
    for index, key in enumerate(natural.state_keys):
        path = groups / f"group-{index:04d}.json"
        if path.exists():
            value = _verify_group(
                path, index,
                supplied_states[key] if supplied_states is not None else None,
                key=key)
            _require_population_identity(value, _population_record(typed, index))
            existing.append(value)
        else:
            break
    if len(existing) and len(existing) != len(list(groups.glob("group-*.json"))):
        raise PT1ExecutionError("execution group prefix is not contiguous")
    completed = len(existing)
    execution_started = time.perf_counter_ns()
    resources = _resource_totals(existing, typed.worker_count)
    overages = _resource_cap_overages(resources, typed.capacity_caps)
    if overages:
        record_execution_failure(
            typed, root, code="resource_cap_exceeded", completed=completed,
            resource_overages=overages)
        raise PT1ExecutionError("execution scientific cap exceeded")
    if deadline is not None:
        raise PT1ExecutionError("caller deadline cannot override frozen deadline")
    deadline = frozen_deadline
    with executor_factory(typed.worker_count) as executor:
        while completed < TARGET_STATE_COUNT:
            if monotonic() >= deadline:
                break
            batch = [(index, natural.state_keys[index]) for index in range(
                completed, min(TARGET_STATE_COUNT,
                               completed + typed.worker_count))]
            try:
                batch_started = time.perf_counter_ns()
                if supplied_states is None:
                    futures = [executor.submit(
                        _scientific_worker, (natural, capture_secret, key))
                               for _, key in batch]
                else:
                    worker_fn = worker or _worker
                    futures = [executor.submit(
                        worker_fn, (key, supplied_states[key]))
                               for _, key in batch]
                results = [future.result() for future in futures]
                batch_wall_ns = time.perf_counter_ns() - batch_started
            except Exception as exc:
                record_execution_failure(
                    typed, root, code="worker_failure", completed=completed,
                    wave_start=batch[0][0], wave_stop=batch[-1][0] + 1)
                raise PT1ExecutionError(
                    "execution worker failure; durable groups retained") from exc
            # A wave that finishes after the frozen boundary consumed compute,
            # but none of its scientific rows may enter the durable population.
            if monotonic() >= deadline:
                break
            normalized = {}
            for item in results:
                if supplied_states is None:
                    key, state, records, worker_wall, worker_cpu, worker_rss = item
                else:
                    key, records = item[:2]
                    state = supplied_states[key]
                    worker_wall, worker_cpu, worker_rss = (
                        item[2:5] if len(item) >= 5 else
                        (0, 0, resource.getrusage(
                            resource.RUSAGE_SELF).ru_maxrss * (
                                1 if sys.platform == "darwin" else 1024)))
                if key in normalized:
                    raise PT1ExecutionError(
                        "execution worker duplicated a state group")
                normalized[key] = (state, tuple(records), worker_wall,
                                   worker_cpu, worker_rss)
            if set(normalized) != {key for _, key in batch}:
                raise PT1ExecutionError("execution worker dropped a state group")
            batch_cpu_ns = sum(int(row[3]) for row in normalized.values())
            batch_rss_bytes = sum(int(row[4]) for row in normalized.values())
            new_groups = []
            for index, key in batch:
                state, records, worker_wall, worker_cpu, worker_rss = normalized[key]
                _require_population_identity(
                    state, _population_record(typed, index))
                group = _group_payload(
                    index, key, state, records, worker_wall, worker_cpu,
                    worker_rss, batch_wall_ns, batch_cpu_ns,
                    batch_rss_bytes)
                new_groups.append(group)
            candidate_resources = _resource_totals(
                (*existing, *new_groups), typed.worker_count)
            overages = _resource_cap_overages(
                candidate_resources, typed.capacity_caps)
            if overages:
                record_execution_failure(
                    typed, root, code="resource_cap_exceeded",
                    completed=completed, wave_start=batch[0][0],
                    wave_stop=batch[-1][0] + 1,
                    resource_overages=overages)
                raise PT1ExecutionError("execution scientific cap exceeded")
            for group in new_groups:
                _write_once(
                    groups / f"group-{group['index']:04d}.json",
                    canonical_json_bytes(group))
                existing.append(group)
                completed += 1
                progress = _progress_payload(
                    typed, completed,
                    "FINALIZING" if completed == TARGET_STATE_COUNT else "RUNNING",
                    ((time.perf_counter_ns() - execution_started)
                     * (TARGET_STATE_COUNT - completed) // max(1, completed)))
                _write_progress(root / PROGRESS_NAME, progress)
                if progress_sink is not None:
                    progress_sink(progress)
            resources = candidate_resources
    complete = completed == TARGET_STATE_COUNT
    status = "FINALIZING" if complete else "TRUNCATED"
    _write_progress(root / PROGRESS_NAME, _progress_payload(typed, completed, status, 0))
    if not complete:
        return {"status": status, "completed_units": completed,
                "total_units": TARGET_STATE_COUNT,
                "authority": dict(AUTHORITIES)}
    all_groups = [_verify_group(
        groups / f"group-{index:04d}.json", index,
        supplied_states[natural.state_keys[index]]
        if supplied_states is not None else None,
        key=natural.state_keys[index])
                  for index in range(TARGET_STATE_COUNT)]
    states = _validate_group_population(
        natural, all_groups, typed.population_manifest)
    records = [record for group in all_groups for record in group["records"]]
    typed_records = tuple(verify_record(record) for record in records)
    statistics = reduce_reopened_pt1_statistics(
        natural, states, typed_records)
    verify_statistics_report(statistics, design=natural)
    if monotonic() >= deadline:
        return _truncate_at_deadline(typed, root, completed)
    status = "COMPLETE"
    packet = {"schema": EXECUTION_SCHEMA,
              "freeze_sha256": _hash_bytes(typed.canonical_bytes()),
              "status": status, "completed_units": completed,
              "total_units": TARGET_STATE_COUNT,
              "resources": resources,
              "statistics": statistics.payload(), "authority": dict(AUTHORITIES)}
    packet["packet_sha256"] = _hash_bytes(canonical_json_bytes(packet))
    packet_data = canonical_json_bytes(packet)
    _write_once(root / PACKET_NAME, packet_data)
    manifest = {"schema": MANIFEST_SCHEMA,
                "freeze_sha256": packet["freeze_sha256"],
                "packet_sha256": packet["packet_sha256"],
                "packet_bytes_sha256": _hash_bytes(packet_data),
                "group_count": TARGET_STATE_COUNT, "record_count": len(records),
                "group_hashes": [_hash_bytes((groups / f"group-{index:04d}.json").read_bytes())
                                 for index in range(TARGET_STATE_COUNT)],
                "status": status, "authority": dict(AUTHORITIES)}
    manifest["manifest_sha256"] = _hash_bytes(canonical_json_bytes(manifest))
    _write_once(root / MANIFEST_NAME, canonical_json_bytes(manifest))
    if monotonic() >= deadline:
        return _truncate_at_deadline(typed, root, completed)
    _write_progress(root / PROGRESS_NAME, _progress_payload(
        typed, completed, "COMPLETE", 0))
    if monotonic() >= deadline:
        return _truncate_at_deadline(typed, root, completed)
    return packet


def verify_execution(output_root: str | os.PathLike[str],
                     freeze: PT1ExecutionFreeze | Mapping[str, object] | bytes,
                     *, capture_secret: bytes | None = None,
                     population: Mapping[tuple[str, int, str, int, int], NaturalPT1State] | None = None,
                     state_capture: Callable[..., object] | None = None,
                     review_marker: bytes | None = None,
                     review_commit: str,
                     repo_root: Path | None = None,
                     statistics_design: NaturalPT1Design | None = None) -> dict[str, object]:
    typed = verify_freeze(freeze)
    raw_root = Path(output_root).expanduser()
    if raw_root.is_symlink():
        raise PT1ExecutionError("execution output symlink refused")
    root = raw_root.absolute()
    _require_live_bindings(typed, root, repo_root=repo_root)
    _require_owned_directory(root, "execution output")
    if review_marker is None:
        raise PT1ExecutionError("verify requires authenticated review marker")
    authenticate_review_marker(review_marker, typed, review_commit=review_commit,
                               repo_root=repo_root)
    if type(capture_secret) is not bytes or len(capture_secret) != 32 \
            or hashlib.sha256(capture_secret).hexdigest() != typed.scientific_capture_secret_sha256:
        raise PT1ExecutionError("scientific capture secret commitment drift")
    natural = NaturalPT1Design(typed.scientific_capture_secret_sha256)
    states = (dict(population) if population is not None else
              capture_natural_states(natural, capture_secret=capture_secret,
                                     state_capture=state_capture))
    validate_population(natural, states)
    for index, key in enumerate(natural.state_keys):
        _require_population_identity(
            states[key], _population_record(typed, index))
    if _canonical_load(
            _immutable_bytes(root / FREEZE_NAME, "published freeze"),
            "freeze") != typed.payload():
        raise PT1ExecutionError("published freeze bytes drift")
    _verify_deadline_receipt(typed, root)
    progress = _canonical_load((root / PROGRESS_NAME).read_bytes(), "progress")
    if not isinstance(progress, dict) or progress.get("authority") != AUTHORITIES:
        raise PT1ExecutionError("execution progress authority drift")
    groups = root / GROUP_DIR
    _require_owned_directory(groups, "execution group directory")
    count = progress.get("completed_units")
    if type(count) is not int or count < 0 or count > TARGET_STATE_COUNT:
        raise PT1ExecutionError("execution progress count drift")
    if progress != _progress_payload(typed, count, progress.get("status"),
                                    progress.get("eta_nanoseconds", 0)):
        raise PT1ExecutionError("execution progress identity drift")
    actual_names = sorted(path.name for path in groups.iterdir())
    expected_names = [f"group-{index:04d}.json" for index in range(count)]
    if actual_names != expected_names:
        raise PT1ExecutionError("execution group namespace is not closed")
    status = progress.get("status")
    if status not in {"RUNNING", "FINALIZING", "TRUNCATED", "COMPLETE",
                      "FAILED"}:
        raise PT1ExecutionError("execution progress status drift")
    expected_root = {FREEZE_NAME, PROGRESS_NAME, DEADLINE_NAME, GROUP_DIR}
    if status == "COMPLETE":
        expected_root |= {PACKET_NAME, MANIFEST_NAME}
    if status == "FAILED":
        expected_root |= {FAILURE_NAME}
    if {path.name for path in root.iterdir()} != expected_root:
        raise PT1ExecutionError("execution root namespace is not closed")
    if status == "COMPLETE" and count != TARGET_STATE_COUNT:
        raise PT1ExecutionError("execution completion drift")
    if status == "FAILED":
        failure = record_execution_failure(typed, root, code="cli_failure")
        for index in range(count):
            group = _verify_group(
                groups / f"group-{index:04d}.json", index,
                states[natural.state_keys[index]],
                key=natural.state_keys[index])
            _require_population_identity(group, _population_record(typed, index))
        return {"status": "FAILED", "completed_units": count,
                "total_units": TARGET_STATE_COUNT,
                "failure_code": failure["failure_code"],
                "authority": dict(AUTHORITIES)}
    if status == "TRUNCATED":
        for index in range(count):
            _verify_group(groups / f"group-{index:04d}.json", index,
                          states[natural.state_keys[index]],
                          key=natural.state_keys[index])
        if (root / PACKET_NAME).exists() or (root / MANIFEST_NAME).exists():
            raise PT1ExecutionError("truncated execution published a final packet")
        return {"status": "TRUNCATED", "completed_units": count,
                "total_units": TARGET_STATE_COUNT, "authority": dict(AUTHORITIES)}
    if count < TARGET_STATE_COUNT:
        raise PT1ExecutionError("unfinished execution is not terminal")
    verified_groups = []
    for index in range(TARGET_STATE_COUNT):
        if not (groups / f"group-{index:04d}.json").is_file():
            raise PT1ExecutionError("execution group population incomplete")
        verified_groups.append(_verify_group(
            groups / f"group-{index:04d}.json", index,
            states[natural.state_keys[index]], key=natural.state_keys[index]))
    reopened_states = _validate_group_population(
        natural, verified_groups, typed.population_manifest)
    packet_raw = _immutable_bytes(root / PACKET_NAME, "execution packet")
    manifest_raw = _immutable_bytes(root / MANIFEST_NAME, "execution manifest")
    packet = _canonical_load(packet_raw, "packet")
    manifest = _canonical_load(manifest_raw, "manifest")
    if (not isinstance(packet, dict)
            or set(packet) != {"schema", "freeze_sha256", "status",
                               "completed_units", "total_units", "resources",
                               "statistics", "authority", "packet_sha256"}
            or packet.get("schema") != EXECUTION_SCHEMA \
            or packet.get("authority") != AUTHORITIES):
        raise PT1ExecutionError("execution packet drift")
    packet_hash = packet.get("packet_sha256")
    body = dict(packet); body.pop("packet_sha256", None)
    if packet_hash != _hash_bytes(canonical_json_bytes(body)):
        raise PT1ExecutionError("execution packet hash drift")
    resources = _resource_totals(verified_groups, typed.worker_count)
    if packet.get("resources") != resources \
            or any(resources[name] > typed.capacity_caps[name]
                   for name in SCIENTIFIC_CAP_KEYS):
        raise PT1ExecutionError("execution resource reconstruction drift")
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA \
            or manifest.get("packet_sha256") != packet_hash \
            or manifest.get("packet_bytes_sha256") != _hash_bytes(packet_raw) \
            or manifest.get("freeze_sha256") != _hash_bytes(typed.canonical_bytes()) \
            or manifest.get("record_count") != TARGET_STATE_COUNT * len(POLICY_SEEDS) \
            or manifest.get("status") != "COMPLETE" \
            or manifest.get("authority") != AUTHORITIES:
        raise PT1ExecutionError("execution manifest drift")
    expected_group_hashes = [_hash_bytes(
        (groups / f"group-{index:04d}.json").read_bytes())
        for index in range(TARGET_STATE_COUNT)]
    if manifest.get("group_hashes") != expected_group_hashes \
            or manifest.get("group_count") != TARGET_STATE_COUNT:
        raise PT1ExecutionError("execution group hash population drift")
    claimed = manifest.get("manifest_sha256")
    manifest_body = dict(manifest); manifest_body.pop("manifest_sha256", None)
    if claimed != _hash_bytes(canonical_json_bytes(manifest_body)):
        raise PT1ExecutionError("execution manifest hash drift")
    if statistics_design is not None:
        verify_statistics_report(packet["statistics"], design=statistics_design)
    reconstructed = reduce_reopened_pt1_statistics(natural, reopened_states, tuple(
        verify_record(record) for group in verified_groups
        for record in group["records"]))
    if reconstructed.payload() != packet.get("statistics"):
        raise PT1ExecutionError("execution statistics reconstruction drift")
    return {"status": "COMPLETE", "completed_units": TARGET_STATE_COUNT,
            "total_units": TARGET_STATE_COUNT, "packet_sha256": packet_hash,
            "manifest_sha256": claimed, "authority": dict(AUTHORITIES)}


__all__ = ["AUTHORITIES", "EXECUTION_SCHEMA", "FAILURE_SCHEMA", "FREEZE_SCHEMA",
           "GROUP_SCHEMA", "MANIFEST_SCHEMA", "POLICY_SEEDS",
           "POPULATION_MANIFEST_SCHEMA", "PROGRESS_SCHEMA",
           "PT1ExecutionError", "PT1ExecutionFreeze",
           "authenticate_review_marker", "build_population_manifest",
           "capture_population_manifest", "freeze_execution",
           "initialize_execution", "record_execution_failure",
           "rehearse_process_pool_wave", "run_execution",
           "verify_execution", "verify_freeze", "verify_population_manifest"]
