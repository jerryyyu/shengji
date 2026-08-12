#!/usr/bin/env python3
"""Freeze the first whole-round screen for the passed mid/late Teacher.

The independently reviewed parent established a narrow capability: after
trick five, the eight-seed ranking ensemble can offer one useful challenger
inside the live report-LCB decision, and fresh Monte Carlo still protects the
incumbent.  This controller authenticates that exact terminal state result,
copies its exact NumPy models into a new immutable namespace, and freezes one
fresh three-arm complete-round screen:

* treatment: the model proposes one challenger and fresh report-LCB decides;
* matched null: identical trigger and search work with a deterministic random
  non-incumbent proposal; and
* champion: literal ``mc-s0-report-lcb`` against itself.

Freezing authorizes independent packet review only.  It does not launch the
capacity preflight, screen, confirmation, promotion, or production change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_midlate_state_controller as PARENT  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine import combos, fast, legal  # noqa: E402
from shengji.rl import stage_c_candidates as CANDIDATES  # noqa: E402
from shengji.rl import stage_c_composition as COMPOSITION  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_npnet as NPNET  # noqa: E402
from shengji.rl import stage_c_screen as SCREEN  # noqa: E402


PARENT_KIND = "midlate-state-screen"
PARENT_GIT = "ee5e9ecf71df1291f352d6c039f4dfea5fbc8804"
PARENT_PACKET_SHA256 = \
    "017209a3c5a1f5daba59a5c66d4276ce921f7d52a4a67bcee9164cc82ffb32f8"
PARENT_SELECTION_SHA256 = \
    "a79be3f623252bf4a97c562ed658ebf90505aa05113f8e0c0267a9b5e5eaa092"
PARENT_RESULT_SHA256 = \
    "f18c2e424e423a269110e4e281ff5772da8d64e7d1db3c9f1dfe299a7de948f6"
PARENT_EVALUATION_ADMISSION_SHA256 = \
    "cec47ad6b91e633d625f49e062f8f72ff51070d414d44228aa71800236f77e54"
PARENT_CONTROLLER_REVIEW_SHA256 = \
    "865e224665878d40fe2c1d4d0425f6dc6649499b5e823ae4abd13372a1a44aad"
PARENT_SELECTION_REVIEW_SHA256 = \
    "6c6c2b2be8e36d4e4158d48e50b2ced12f884b009009344b55ec5a730f363dc3"

SCHEMA = "teacher-stage-c-midlate-composition-screen-controller-v1"
PACKET_ID = "teacher-v3-stage-c-midlate-composition-screen-v1"
RUN_ID = PACKET_ID
PACKET_PATH = f"server/runs/logs/{RUN_ID}/controller-packet.json"
PARENT_REVIEW_SNAPSHOT_PATH = \
    f"server/runs/logs/{RUN_ID}/parent-review-snapshot.md"
REVIEW_SCHEMA = \
    "teacher-stage-c-midlate-composition-screen-controller-review-v1"
REVIEW_MARKER = \
    "TEACHER_STAGE_C_MIDLATE_COMPOSITION_SCREEN_CONTROLLER_V1_REVIEW "
CAPACITY_RESULT_SCHEMA = \
    "teacher-stage-c-midlate-composition-capacity-v1"
CAPACITY_REVIEW_SCHEMA = \
    "teacher-stage-c-midlate-composition-capacity-review-v1"
CAPACITY_REVIEW_MARKER = \
    "TEACHER_STAGE_C_MIDLATE_COMPOSITION_CAPACITY_V1_REVIEW "
SUPERVISOR_REVIEW_SCHEMA = \
    "teacher-stage-c-midlate-composition-supervisor-final-review-v1"
SUPERVISOR_REVIEW_MARKER = \
    "TEACHER_STAGE_C_MIDLATE_COMPOSITION_SUPERVISOR_FINAL_V1_REVIEW "
RUNTIME_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_midlate_composition_runtime.py"
RUNTIME_ADMISSION_SCHEMA = \
    "teacher-stage-c-midlate-composition-screen-admission-v1"
RUNTIME_CAPACITY_ADMISSION_SCHEMA = \
    "teacher-stage-c-midlate-composition-capacity-admission-v1"
RUNTIME_SUPERVISOR_ADMISSION_SCHEMA = \
    "teacher-stage-c-midlate-composition-supervisor-admission-v1"
RUNTIME_SUPERVISOR_FINAL_SCHEMA = \
    "teacher-stage-c-midlate-composition-supervisor-final-v1"
RUNTIME_RECEIPT_SCHEMA = \
    "teacher-stage-c-midlate-composition-screen-receipt-v1"
RUNTIME_SHARD_SCHEMA = \
    "teacher-stage-c-midlate-composition-screen-shard-v1"
RUNTIME_AGGREGATE_SCHEMA = \
    "teacher-stage-c-midlate-composition-screen-result-v1"

PREFLIGHT_SEED0 = 192_000_000
PREFLIGHT_CLUSTERS = 4
PREFLIGHT_MAX_SECONDS = 3_600.0
THROUGHPUT_SAFETY_FACTOR = 2.0
SCREEN_FLEET_HOUR_CAP = 384.0
SCREEN_MAX_SHARD_HOUR_CAP = 48.0
SCREEN_SEED0 = 193_000_000
SCREEN_CLUSTERS = 2_048
SHARD_COUNT = 8
CLUSTERS_PER_SHARD = SCREEN_CLUSTERS // SHARD_COUNT
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")
PLANNING_CLUSTER_SD = 1.30
FIXED_LOOK_BOUNDARY_EFFECT = (
    SCREEN.ONE_SIDED_CRITICAL * PLANNING_CLUSTER_SD
    / math.sqrt(SCREEN_CLUSTERS))

MODEL_DIR = f"server/runs/logs/{RUN_ID}/models"
MODEL_PATHS = tuple(
    f"{MODEL_DIR}/seed-{seed}.npz" for seed in MODEL.TRAINING_SEEDS)
SHARD_PATHS = tuple(
    f"server/runs/logs/{RUN_ID}/shard-{index:02d}.json"
    for index in range(SHARD_COUNT))
SHARD_LOG_PATHS = tuple(
    f"server/runs/logs/{RUN_ID}/shard-{index:02d}.log"
    for index in range(SHARD_COUNT))
RESULT_PATH = f"server/runs/logs/{RUN_ID}/aggregate.json"
CAPACITY_RESULT_PATH = f"server/runs/logs/{RUN_ID}/capacity.json"
SUPERVISOR_FINAL_PATH = f"server/runs/logs/{RUN_ID}/supervisor-final.json"
RECEIPT_PATH = f"server/runs/logs/{RUN_ID}/screen-receipt.json"
CAPACITY_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.capacity.consumed.json"
ADMISSION_PATH = f"server/runs/locks/{RUN_ID}.consumed.json"
SUPERVISOR_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.supervisor.consumed.json"
SHARD_ADMISSION_PATHS = tuple(
    f"server/runs/locks/{RUN_ID}.shard-{index:02d}.consumed.json"
    for index in range(SHARD_COUNT))
AGGREGATE_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.aggregate.consumed.json"

SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_midlate_composition_controller.py",
    RUNTIME_SCRIPT_PATH,
    "server/scripts/teacher_stage_c_composition_runtime.py",
    "server/scripts/teacher_stage_c_midlate_state_controller.py",
    "server/shengji/rl/stage_c_candidates.py",
    "server/shengji/rl/stage_c_composition.py",
    "server/shengji/rl/stage_c_npnet.py",
    "server/shengji/rl/npnet.py",
    "server/shengji/rl/stage_c_screen.py",
)


class CompositionControllerRefused(RuntimeError):
    """A parent, review, model export, packet, or authority drifted."""


canonical_json = NPNET.canonical_json
sha256_file = NPNET.sha256_file


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def self_hash(value: Mapping[str, object], field: str) -> str:
    return sha256_bytes(canonical_json({
        key: item for key, item in value.items() if key != field
    }))


def manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def require_publishable(path: Path, label: str) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CompositionControllerRefused(
            f"refusing existing {label}: {path}")


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise CompositionControllerRefused(
            f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CompositionControllerRefused(
            f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompositionControllerRefused(
            f"JSON root is not an object: {path}")
    return value


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _source_sha256s() -> dict[str, str]:
    result = {}
    for logical in SOURCE_PATHS:
        path = (REPO / logical).resolve()
        if not is_regular_unlinked(path):
            raise CompositionControllerRefused(
                f"composition source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return result


def runtime_contract() -> dict:
    routed = (bool(fast.HAVE_FAST)
              and combos.decompose is fast.decompose
              and legal.beats is fast.beats)
    binary = getattr(fast, "_fast", None)
    binary_path = None if binary is None else Path(binary.__file__).resolve()
    python_path = Path(sys.executable)
    python_resolved = python_path.resolve()
    if (os.environ.get("SHENGJI_FAST") != "1" or not routed
            or binary_path is None or not is_regular_unlinked(binary_path)
            or not is_regular_unlinked(python_resolved)):
        raise CompositionControllerRefused(
            "composition packet requires compiled engine and regular Python")
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "python_executable": str(python_path),
        "python_executable_resolved": str(python_resolved),
        "python_executable_sha256": sha256_file(python_resolved),
        "numpy": str(NPNET.np.__version__),
        "fast_engine": True,
        "fast_routed": True,
        "fast_binary_sha256": sha256_file(binary_path),
        "workers": SHARD_COUNT,
        "progress_every_clusters": 50,
        "supervisor_heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
        "supervisor_signal_contract": {
            "handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_shards_authorized": False,
        },
    }


def _parent_paths(root: Path) -> dict[str, Path]:
    root = root.resolve()
    return {
        "controller_packet": (root / PARENT.PACKET_PATH).resolve(),
        "selection_population": (root / PARENT.POPULATION_PATH).resolve(),
        "state_result": (root / PARENT.RESULT_PATH).resolve(),
        "evaluation_admission":
            (root / PARENT.EVALUATION_ADMISSION_PATH).resolve(),
    }


def _review_claims(
    review_record: Path, *, parent_packet: Mapping[str, object],
    selection: Mapping[str, object], result: Mapping[str, object],
) -> dict:
    claims = {
        "controller": PARENT.marker_claim(
            review_record, PARENT.REVIEW_MARKER, "parent controller review"),
        "selection": PARENT.marker_claim(
            review_record, PARENT.SELECTION_REVIEW_MARKER,
            "parent selection review"),
        "result": PARENT.marker_claim(
            review_record, PARENT.RESULT_REVIEW_MARKER,
            "parent terminal-result review"),
    }
    expected = {
        "controller": PARENT.expected_review_claim(
            parent_packet, PARENT_PACKET_SHA256),
        "selection": PARENT.expected_selection_review_claim(
            parent_packet, PARENT_PACKET_SHA256,
            selection, PARENT_SELECTION_SHA256),
        "result": PARENT.expected_result_review_claim(
            parent_packet, PARENT_PACKET_SHA256,
            result, PARENT_RESULT_SHA256),
    }
    if claims != expected:
        raise CompositionControllerRefused(
            "parent review claims do not match reconstructed evidence")
    return claims


def _review_snapshot_bytes(claims: Mapping[str, object]) -> bytes:
    markers = {
        "controller": PARENT.REVIEW_MARKER,
        "selection": PARENT.SELECTION_REVIEW_MARKER,
        "result": PARENT.RESULT_REVIEW_MARKER,
    }
    return "".join(
        markers[name] + json.dumps(
            claims[name], sort_keys=True, separators=(",", ":")) + "\n"
        for name in ("controller", "selection", "result")
    ).encode()


def _check_parent_git_and_sources(
    root: Path, packet: Mapping[str, object],
) -> None:
    if (not root.is_dir()
            or _git("rev-parse", "HEAD", cwd=root) != PARENT_GIT
            or _git("status", "--porcelain", "--untracked-files=all",
                    cwd=root)):
        raise CompositionControllerRefused(
            "parent evidence worktree Git identity drift")
    producer = packet.get("producer")
    if (not isinstance(producer, Mapping)
            or producer.get("git") != PARENT_GIT
            or producer.get("tree_dirty") is not False
            or not isinstance(producer.get("sources"), Mapping)):
        raise CompositionControllerRefused("parent producer identity drift")
    for logical, expected in producer["sources"].items():
        path = (root / str(logical)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise CompositionControllerRefused(
                "parent source escapes evidence root") from exc
        if (not is_sha256(expected) or not is_regular_unlinked(path)
                or sha256_file(path) != expected):
            raise CompositionControllerRefused(
                f"parent source path/SHA drift: {logical}")


def _validate_parent_fast(root: Path, review_record: Path) -> dict:
    paths = _parent_paths(root)
    expected_external = {
        "controller_packet": PARENT_PACKET_SHA256,
        "selection_population": PARENT_SELECTION_SHA256,
        "state_result": PARENT_RESULT_SHA256,
        "evaluation_admission": PARENT_EVALUATION_ADMISSION_SHA256,
    }
    for name, path in paths.items():
        if (not is_regular_unlinked(path)
                or sha256_file(path) != expected_external[name]):
            raise CompositionControllerRefused(
                f"parent {name} path/SHA drift")
    packet = load_json(paths["controller_packet"])
    selection = load_json(paths["selection_population"])
    result = load_json(paths["state_result"])
    admission = load_json(paths["evaluation_admission"])
    _check_parent_git_and_sources(root, packet)
    aggregate = result.get("aggregate")
    population = selection.get("population")
    selected = packet.get("selected_capability")
    if (packet.get("schema") != PARENT.SCHEMA
            or packet.get("packet_id") != PARENT.PACKET_ID
            or packet.get("run_id") != PARENT.RUN_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or not isinstance(selected, Mapping)
            or selected.get("surface") != "play"
            or selected.get("head") != "ranking"
            or selected.get("epoch") != 32
            or selected.get("loss_recipe") != "all_pairs_v1"
            or selected.get("action_improvement_positive_seeds") != 8
            or selected.get("calibration_positive_seeds") != 8
            or packet.get("authority", {}).get(
                "whole_game_launch_authorized") is not False
            or packet.get("authority", {}).get("strength_claim") is not False
            or selection.get("schema")
            != "teacher-stage-c-midlate-state-selection-result-v1"
            or selection.get("selection_result_sha256")
            != self_hash(selection, "selection_result_sha256")
            or not isinstance(population, Mapping)
            or population.get("complete") is not True
            or population.get("selected_states") != 256
            or selection.get("evaluation_opened") is not False
            or selection.get("controller_review_record_sha256")
            != PARENT_CONTROLLER_REVIEW_SHA256
            or result.get("schema")
            != "teacher-stage-c-midlate-state-screen-result-v1"
            or result.get("result_sha256")
            != self_hash(result, "result_sha256")
            or not isinstance(aggregate, Mapping)
            or aggregate.get("aggregate_sha256")
            != self_hash(aggregate, "aggregate_sha256")
            or aggregate.get("decision")
            != "AUTHORIZE_WHOLE_GAME_SCREEN_DESIGN"
            or aggregate.get("whole_game_screen_design_authorized") is not True
            or result.get("whole_game_launch_authorized") is not False
            or result.get("strength_claim") is not False
            or result.get("controller_review_record_sha256")
            != PARENT_CONTROLLER_REVIEW_SHA256
            or result.get("selection_review_record_sha256")
            != PARENT_SELECTION_REVIEW_SHA256
            or admission.get("schema")
            != "teacher-stage-c-midlate-state-evaluation-admission-v1"
            or admission.get("admission_sha256")
            != self_hash(admission, "admission_sha256")
            or admission.get("controller_packet_sha256")
            != PARENT_PACKET_SHA256
            or admission.get("selection_population_sha256")
            != PARENT_SELECTION_SHA256
            or admission.get("controller_review_record_sha256")
            != PARENT_CONTROLLER_REVIEW_SHA256
            or admission.get("selection_review_record_sha256")
            != PARENT_SELECTION_REVIEW_SHA256
            or admission.get("retry_or_extension_authorized") is not False):
        raise CompositionControllerRefused(
            "parent terminal artifact identity/authority drift")
    claims = _review_claims(
        review_record, parent_packet=packet,
        selection=selection, result=result)
    if (result.get("selection_review_claim") != claims["selection"]
            or result.get("selection_population_sha256")
            != PARENT_SELECTION_SHA256
            or result.get("evaluation_admission_sha256")
            != PARENT_EVALUATION_ADMISSION_SHA256):
        raise CompositionControllerRefused(
            "parent terminal result/review/admission binding drift")
    exports = packet.get("model_exports")
    if (not isinstance(exports, list)
            or len(exports) != len(MODEL.TRAINING_SEEDS)
            or packet.get("model_exports_sha256") != manifest_hash(exports)
            or [item.get("metadata", {}).get("seed") for item in exports]
            != list(MODEL.TRAINING_SEEDS)):
        raise CompositionControllerRefused(
            "parent model-export manifest drift")
    for item in exports:
        source = (root / str(item.get("logical_path", ""))).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise CompositionControllerRefused(
                "parent model export escapes evidence root") from exc
        if (not is_regular_unlinked(source)
                or sha256_file(source) != item.get("sha256")):
            raise CompositionControllerRefused(
                "parent model export path/SHA drift")
    summary = {
        "parent_git": PARENT_GIT,
        "controller_packet_sha256": PARENT_PACKET_SHA256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "selection_population_sha256": PARENT_SELECTION_SHA256,
        "selection_population_internal_sha256": selection[
            "selection_result_sha256"],
        "state_result_sha256": PARENT_RESULT_SHA256,
        "state_result_internal_sha256": result["result_sha256"],
        "evaluation_admission_sha256":
            PARENT_EVALUATION_ADMISSION_SHA256,
        "admission_controller_review_sha256":
            PARENT_CONTROLLER_REVIEW_SHA256,
        "admission_selection_review_sha256":
            PARENT_SELECTION_REVIEW_SHA256,
        "aggregate_sha256": aggregate["aggregate_sha256"],
        "decision": aggregate["decision"],
        "selected_capability": packet["selected_capability"],
        "source_model_exports_sha256": packet["model_exports_sha256"],
        "review_claims_sha256": manifest_hash(claims),
        "whole_game_screen_design_authorized": True,
        "whole_game_launch_authorized": False,
        "strength_claim": False,
    }
    return {
        "paths": paths, "packet": packet, "selection": selection,
        "result": result, "admission": admission, "claims": claims,
        "summary": summary,
    }


_PARENT_REPLAY_PROGRAM = r"""
import json
import sys
from pathlib import Path

import teacher_stage_c_midlate_state_controller as C
import teacher_stage_c_midlate_state_runtime as R
from shengji.rl import stage_c_state_screen as S

root = Path(sys.argv[1]).resolve()
review = Path(sys.argv[2]).resolve()
packet_path = (root / C.PACKET_PATH).resolve()
selection_path = (root / C.POPULATION_PATH).resolve()
result_path = (root / C.RESULT_PATH).resolve()
admission_path = (root / C.EVALUATION_ADMISSION_PATH).resolve()
packet_sha, selection_sha, result_sha, admission_sha = sys.argv[3:7]
packet, forbidden, _ensemble = R._packet(packet_path, packet_sha, sys.argv[7])
controller_claim = R._controller_review(review, packet, packet_sha)
selection = R._selection_population(
    path=selection_path, expected_sha256=selection_sha,
    packet=packet, packet_sha256=packet_sha, forbidden=forbidden)
selection_claim = R._selection_review(
    review, packet=packet, packet_sha256=packet_sha,
    population=selection, population_sha256=selection_sha)
result = R.load_json(result_path)
if R.sha256_file(result_path) != result_sha:
    raise RuntimeError("parent state-result external SHA drift")
aggregate = S.aggregate(result["records"], forbidden_deal_seeds=forbidden)
if aggregate != result.get("aggregate"):
    raise RuntimeError("parent state-result full recomputation drift")
admission = R.load_json(admission_path)
if (R.sha256_file(admission_path) != admission_sha
        or admission.get("admission_sha256")
        != R.self_hash(admission, "admission_sha256")
        or admission.get("schema") != R.EVALUATION_ADMISSION_SCHEMA
        or admission.get("kind") != "evaluation"
        or admission.get("controller_packet_sha256") != packet_sha
        or admission.get("selection_population_sha256") != selection_sha
        or admission.get("controller_review_record_sha256") != sys.argv[8]
        or admission.get("selection_review_record_sha256") != sys.argv[9]
        or admission.get("consumed_before_fresh_evidence") is not True
        or admission.get("retry_or_extension_authorized") is not False):
    raise RuntimeError("parent one-shot evaluation admission drift")
result_claim = C.marker_claim(
    review, C.RESULT_REVIEW_MARKER, "parent terminal-result review")
if result_claim != C.expected_result_review_claim(
        packet, packet_sha, result, result_sha):
    raise RuntimeError("parent terminal-result review drift")
if (result.get("controller_packet_sha256") != packet_sha
        or result.get("selection_population_sha256") != selection_sha
        or result.get("selection_review_claim") != selection_claim
        or result.get("evaluation_admission_sha256") != admission_sha
        or result.get("complete") is not True
        or result.get("whole_game_screen_design_authorized") is not True
        or result.get("whole_game_launch_authorized") is not False
        or result.get("strength_claim") is not False
        or result.get("production_promotion") is not False
        or result.get("production_deployment") is not False
        or result.get("retry_or_extension_authorized") is not False
        or controller_claim != C.expected_review_claim(packet, packet_sha)):
    raise RuntimeError("parent terminal chain identity/authority drift")
print(json.dumps({
    "aggregate_sha256": aggregate["aggregate_sha256"],
    "decision": aggregate["decision"],
    "forbidden_deal_count": len(forbidden),
    "models": len(packet["model_exports"]),
    "selected_capability": packet["selected_capability"],
    "states": aggregate["states"],
    "verified": True,
}, sort_keys=True))
"""


def _full_parent_replay(root: Path, review_record: Path,
                        data: Mapping[str, object]) -> dict:
    packet = data["packet"]
    python = Path(str(packet.get("runtime_contract", {}).get(
        "python_executable", "")))
    if not is_regular_unlinked(python.resolve()):
        raise CompositionControllerRefused(
            "parent reviewed Python executable is unavailable")
    env = dict(os.environ)
    env["SHENGJI_FAST"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((
        str((root / "server").resolve()),
        str((root / "server/scripts").resolve())))
    completed = subprocess.run(
        [str(python), "-c", _PARENT_REPLAY_PROGRAM,
         str(root), str(review_record), PARENT_PACKET_SHA256,
         PARENT_SELECTION_SHA256, PARENT_RESULT_SHA256,
         PARENT_EVALUATION_ADMISSION_SHA256, PARENT_GIT,
         PARENT_CONTROLLER_REVIEW_SHA256,
         PARENT_SELECTION_REVIEW_SHA256],
        cwd=root, env=env, check=False, capture_output=True, text=True,
        timeout=300)
    if completed.returncode != 0:
        raise CompositionControllerRefused(
            "parent full replay refused:\n" + completed.stderr.strip())
    try:
        summary = json.loads(completed.stdout.strip())
    except ValueError as exc:
        raise CompositionControllerRefused(
            "parent full replay emitted invalid summary") from exc
    aggregate = data["result"]["aggregate"]
    expected = {
        "aggregate_sha256": aggregate["aggregate_sha256"],
        "decision": "AUTHORIZE_WHOLE_GAME_SCREEN_DESIGN",
        "forbidden_deal_count": data["packet"]["screen_contract"][
            "forbidden_deal_count"],
        "models": len(MODEL.TRAINING_SEEDS),
        "selected_capability": data["packet"]["selected_capability"],
        "states": 256,
        "verified": True,
    }
    if summary != expected:
        raise CompositionControllerRefused(
            "parent full replay summary drift")
    return summary


def _path_from_ref(ref: Mapping[str, object], label: str) -> Path:
    absolute = ref.get("absolute_path")
    logical = ref.get("logical_path")
    if absolute is not None:
        if logical is not None:
            raise CompositionControllerRefused(f"{label} reference drift")
        path = Path(str(absolute)).resolve()
        if str(path) != absolute:
            raise CompositionControllerRefused(
                f"{label} absolute path is not canonical")
        return path
    logical_path = Path(str(logical))
    if logical_path.is_absolute() or ".." in logical_path.parts:
        raise CompositionControllerRefused(f"{label} logical path drift")
    return (REPO / logical_path).resolve()


def validate_runtime_parent(packet: Mapping[str, object]) -> None:
    parents = packet.get("parents")
    if not isinstance(parents, Mapping) or set(parents) != {
            "kind", "evidence_root", "controller_packet",
            "selection_population", "state_result",
            "evaluation_admission", "review_snapshot"}:
        raise CompositionControllerRefused(
            "mid/late composition parent population drift")
    root_ref = parents["evidence_root"]
    if (parents.get("kind") != PARENT_KIND
            or not isinstance(root_ref, Mapping)
            or root_ref.get("git") != PARENT_GIT):
        raise CompositionControllerRefused(
            "mid/late composition parent identity drift")
    root = Path(str(root_ref.get("absolute_path", ""))).resolve()
    if str(root) != root_ref.get("absolute_path"):
        raise CompositionControllerRefused(
            "mid/late parent root is not canonical")
    expected = {
        "controller_packet": PARENT_PACKET_SHA256,
        "selection_population": PARENT_SELECTION_SHA256,
        "state_result": PARENT_RESULT_SHA256,
        "evaluation_admission": PARENT_EVALUATION_ADMISSION_SHA256,
    }
    paths = _parent_paths(root)
    for name, external in expected.items():
        ref = parents[name]
        if (not isinstance(ref, Mapping)
                or _path_from_ref(ref, f"parent {name}") != paths[name]
                or ref.get("external_sha256") != external):
            raise CompositionControllerRefused(
                f"parent {name} reference drift")
    review_ref = parents["review_snapshot"]
    if not isinstance(review_ref, Mapping):
        raise CompositionControllerRefused("parent review snapshot drift")
    review = _path_from_ref(review_ref, "parent review snapshot")
    if (review != (REPO / PARENT_REVIEW_SNAPSHOT_PATH).resolve()
            or not is_regular_unlinked(review)
            or sha256_file(review) != review_ref.get("external_sha256")):
        raise CompositionControllerRefused(
            "parent review snapshot path/SHA drift")
    data = _validate_parent_fast(root, review)
    if (packet.get("parent_validation") != data["summary"]
            or packet.get("selected_capability")
            != data["packet"]["selected_capability"]
            or packet.get("source_model_exports")
            != data["packet"]["model_exports"]
            or packet.get("source_model_exports_sha256")
            != data["packet"]["model_exports_sha256"]):
        raise CompositionControllerRefused(
            "mid/late parent reconstructed summary drift")


def _copy_models(data: Mapping[str, object], *, verify: bool) -> list[dict]:
    packet = data["packet"]
    root = data["paths"]["controller_packet"]
    for _part in Path(PARENT.PACKET_PATH).parts:
        root = root.parent
    root = root.resolve()
    targets = [(REPO / logical).resolve() for logical in MODEL_PATHS]
    if verify:
        if any(not is_regular_unlinked(path) for path in targets):
            raise CompositionControllerRefused(
                "mid/late copied model export is missing")
    else:
        for path in targets:
            require_publishable(path, "mid/late model export")
    exports = []
    for source_item, logical, target in zip(
            packet["model_exports"], MODEL_PATHS, targets, strict=True):
        source = (root / str(source_item["logical_path"])).resolve()
        if not verify:
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as source_handle, target.open("xb") as out:
                shutil.copyfileobj(source_handle, out)
                out.flush()
                os.fsync(out.fileno())
        if (not is_regular_unlinked(target)
                or sha256_file(target) != source_item["sha256"]):
            raise CompositionControllerRefused(
                "copied model export differs from reviewed parent")
        loaded = NPNET.StageCNpNet(
            target, expected_sha256=str(source_item["sha256"]),
            expected_metadata=source_item["metadata"])
        exports.append({
            "logical_path": logical,
            "sha256": source_item["sha256"],
            "metadata": loaded.metadata,
        })
    return exports


def candidate_contract() -> dict:
    return {
        "experiment_id": CANDIDATES.INFERENCE_EXPERIMENT_ID,
        "split": CANDIDATES.INFERENCE_SPLIT,
        "surface": "play",
        "play_candidate_cap": CANDIDATES.PLAY_CANDIDATE_CAP,
        "live_parent": "mc-s0-report-lcb",
        "literal_live_policy_is_incumbent": True,
        "complete_live_ballot_preserved": True,
        "novel_model_proposer": "v11pair_ep07_value",
        "v11_artifact_loaded": True,
        "v11_artifact_path": "server/snapshots_v11pair/ep07.npz",
        "v11_artifact_sha256": PARENT.V11_SHA256,
        "proposal_sources": [
            "v11pair_top_proposal",
            "named_structured_lead_or_follow_mechanism",
            "same_budget_random_diversifier",
        ],
        "public_scope_predicate": {
            "policy": "mc-strong",
            "common_worlds": COMPOSITION.SCOPE_WORLDS,
            "attempt_factor": COMPOSITION.SCOPE_ATTEMPT_FACTOR,
            "production_margin_points": 5.0,
            "absolute_gap_to_margin_at_most_points":
                COMPOSITION.SCOPE_MARGIN_WINDOW,
            "raw_best_index_nonzero": True,
            "precedes_stage_c_inference": True,
        },
        "model_min_completed_tricks": 5,
        "phase_gate_precedes_candidate_source_scope_and_model": True,
        "model_proposes_at_most_one_challenger": True,
        "fresh_report_lcb_required": True,
        "direct_model_override_authorized": False,
    }


def screen_contract() -> dict:
    return {
        "seed0": SCREEN_SEED0,
        "clusters": SCREEN_CLUSTERS,
        "shards": SHARD_COUNT,
        "clusters_per_shard": CLUSTERS_PER_SHARD,
        "rounds_per_cluster_per_arm": 2,
        "arms": list(SCREEN.LABELS),
        "paired_unit": "deal seed with both team flips",
        "fixed_look": True,
        "one_sided_primary_critical": SCREEN.ONE_SIDED_CRITICAL,
        "two_sided_null_critical": SCREEN.TWO_SIDED_CRITICAL,
        "planning_cluster_standard_deviation": PLANNING_CLUSTER_SD,
        "planning_fixed_look_boundary_effect":
            FIXED_LOOK_BOUNDARY_EFFECT,
        "screen_is_exploratory_not_confirmation": True,
        "positive_unresolved_result_does_not_reject_mechanism": True,
        "primary_gates": [
            "treatment-minus-champion one-sided 95% LCB > 0",
            "treatment-minus-matched-null one-sided 95% LCB > 0",
            "matched-null-minus-champion two-sided 95% interval contains zero",
        ],
        "diagnostics": [
            "overall clustered round win rate",
            "paired round-win-rate differences",
            "champion-reference attacker and defender utility",
            "level-change win/loss tails",
        ],
        "nonzero_model_trigger_required": True,
        "zero_fallback_and_exact_work_required": True,
        "reviewed_capacity_result_required_before_screen_admission": True,
        "per_shard_timeout_from_reviewed_capacity_required": True,
        "supervisor_owns_all_shards_and_logs": True,
        "supervisor_heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
        "supervisor_signal_contract": {
            "handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_shards_authorized": False,
        },
        "external_supervisor_final_review_required_before_aggregate": True,
        "aggregate_slot_precedes_outcome_open": True,
        "pass_authority": "confirmation packet review only",
        "retry_or_extension_authorized": False,
    }


def capacity_contract() -> dict:
    return {
        "seed0": PREFLIGHT_SEED0,
        "clusters": PREFLIGHT_CLUSTERS,
        "arms": list(SCREEN.LABELS),
        "score_free_output": True,
        "preflight_max_seconds": PREFLIGHT_MAX_SECONDS,
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "screen_fleet_hour_cap": SCREEN_FLEET_HOUR_CAP,
        "screen_max_shard_hour_cap": SCREEN_MAX_SHARD_HOUR_CAP,
        "nonzero_treatment_and_null_trigger_required": True,
        "zero_fallback_and_exact_work_required": True,
        "pass_authority": "screen execution review only",
        "retry_or_extension_authorized": False,
    }


def result_contract() -> dict:
    return {
        "capacity_admission_slot": CAPACITY_ADMISSION_PATH,
        "capacity_result": CAPACITY_RESULT_PATH,
        "admission_slot": ADMISSION_PATH,
        "supervisor_admission_slot": SUPERVISOR_ADMISSION_PATH,
        "supervisor_final": SUPERVISOR_FINAL_PATH,
        "shard_logs": list(SHARD_LOG_PATHS),
        "shard_admission_slots": list(SHARD_ADMISSION_PATHS),
        "aggregate_admission_slot": AGGREGATE_ADMISSION_PATH,
        "receipt": RECEIPT_PATH,
        "shards": list(SHARD_PATHS),
        "aggregate": RESULT_PATH,
        "one_shot_no_overwrite": True,
    }


def _commands() -> dict:
    shared = [
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
    ]
    capacity = [
        "--capacity-result", CAPACITY_RESULT_PATH,
        "--expected-capacity-result-sha256", "{capacity_result_sha256}",
        "--capacity-review-record", "{capacity_review_record}",
    ]
    receipt = [
        "--screen-receipt", RECEIPT_PATH,
        "--expected-screen-receipt-sha256", "{receipt_sha256}",
    ]
    supervisor = [
        "--supervisor-admission", SUPERVISOR_ADMISSION_PATH,
        "--expected-supervisor-admission-sha256",
        "{supervisor_admission_sha256}",
    ]
    return {
        "capacity_preflight": [
            "{python}", RUNTIME_SCRIPT_PATH, "capacity-preflight", *shared,
            "--out", CAPACITY_RESULT_PATH,
        ],
        "admit": [
            "{python}", RUNTIME_SCRIPT_PATH, "admit", *shared, *capacity,
            "--out", RECEIPT_PATH,
        ],
        "supervise": [
            "{python}", RUNTIME_SCRIPT_PATH, "supervise", *shared,
            *receipt, *capacity, "--out", SUPERVISOR_FINAL_PATH,
        ],
        "supervisor_child_shards": [[
            "{python}", RUNTIME_SCRIPT_PATH, "run-shard", *shared,
            *receipt, *capacity, *supervisor,
            "--shard-index", str(index), "--out", SHARD_PATHS[index],
        ] for index in range(SHARD_COUNT)],
        "aggregate": [
            "{python}", RUNTIME_SCRIPT_PATH, "aggregate", *shared,
            *receipt, *capacity,
            "--supervisor-final", SUPERVISOR_FINAL_PATH,
            "--expected-supervisor-final-sha256",
            "{supervisor_final_sha256}",
            "--supervisor-review-record", "{supervisor_review_record}",
            "--shards", *SHARD_PATHS, "--out", RESULT_PATH,
        ],
    }


def _external_ref(path: Path, expected_sha256: str) -> dict:
    path = path.resolve()
    if (not is_sha256(expected_sha256) or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise CompositionControllerRefused("external parent path/SHA drift")
    return {"absolute_path": str(path), "external_sha256": expected_sha256}


def _logical_ref(path: Path) -> dict:
    path = path.resolve()
    try:
        logical = str(path.relative_to(REPO.resolve()))
    except ValueError as exc:
        raise CompositionControllerRefused(
            "logical artifact escapes repository") from exc
    return {"logical_path": logical, "external_sha256": sha256_file(path)}


def build_packet(
    *, git: str, parent_root: Path, data: Mapping[str, object],
    review_snapshot: Path, exports: Sequence[Mapping[str, object]],
) -> dict:
    paths = data["paths"]
    parent_packet = data["packet"]
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": {
            "git": git, "tree_dirty": False,
            "sources": _source_sha256s(),
        },
        "runtime_contract": runtime_contract(),
        "parents": {
            "kind": PARENT_KIND,
            "evidence_root": {
                "absolute_path": str(parent_root.resolve()),
                "git": PARENT_GIT,
            },
            "controller_packet": _external_ref(
                paths["controller_packet"], PARENT_PACKET_SHA256),
            "selection_population": _external_ref(
                paths["selection_population"], PARENT_SELECTION_SHA256),
            "state_result": _external_ref(
                paths["state_result"], PARENT_RESULT_SHA256),
            "evaluation_admission": _external_ref(
                paths["evaluation_admission"],
                PARENT_EVALUATION_ADMISSION_SHA256),
            "review_snapshot": _logical_ref(review_snapshot),
        },
        "parent_validation": data["summary"],
        "selected_capability": parent_packet["selected_capability"],
        "source_model_exports": parent_packet["model_exports"],
        "source_model_exports_sha256": parent_packet["model_exports_sha256"],
        "model_exports": [dict(item) for item in exports],
        "model_exports_sha256": manifest_hash(exports),
        "candidate_contract": candidate_contract(),
        "capacity_contract": capacity_contract(),
        "screen_contract": screen_contract(),
        "commands": _commands(),
        "result_contract": result_contract(),
        "authority": {
            "capacity_preflight_review_authorized": True,
            "capacity_preflight_launch_authorized": False,
            "screen_packet_review_authorized": False,
            "screen_launch_authorized": False,
            "confirmation_launch_authorized": False,
            "v11_inference_authorized": True,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_review_claim(packet: Mapping[str, object],
                          external_sha256: str) -> dict:
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "parent_state_result_sha256": PARENT_RESULT_SHA256,
        "parent_aggregate_sha256": packet["parent_validation"][
            "aggregate_sha256"],
        "parent_review_snapshot_sha256": packet["parents"][
            "review_snapshot"]["external_sha256"],
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "ensemble_models": len(packet["model_exports"]),
        "preflight_seed0": PREFLIGHT_SEED0,
        "preflight_clusters": PREFLIGHT_CLUSTERS,
        "screen_seed0": SCREEN_SEED0,
        "screen_clusters": SCREEN_CLUSTERS,
        "screen_shards": SHARD_COUNT,
        "planning_fixed_look_boundary_effect":
            FIXED_LOOK_BOUNDARY_EFFECT,
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "python_executable": packet["runtime_contract"][
            "python_executable"],
        "python_executable_sha256": packet["runtime_contract"][
            "python_executable_sha256"],
        "v11_inference_authorized": True,
        "independent_review": True,
        "one_capacity_preflight_authorized": True,
        "one_screen_execution_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def expected_capacity_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
    capacity_result: Mapping[str, object], capacity_external_sha256: str,
) -> dict:
    return {
        "schema": CAPACITY_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": packet_external_sha256,
        "capacity_result_sha256": capacity_external_sha256,
        "capacity_result_internal_sha256": capacity_result["result_sha256"],
        "preflight_seed0": PREFLIGHT_SEED0,
        "preflight_clusters": PREFLIGHT_CLUSTERS,
        "elapsed_seconds": capacity_result["elapsed_seconds"],
        "screen_fleet_hours": capacity_result["projection"][
            "screen_fleet_hours"],
        "screen_max_shard_hours": capacity_result["projection"][
            "screen_max_shard_hours"],
        "screen_max_shard_seconds": capacity_result[
            "screen_max_shard_seconds"],
        "capacity_pass": True,
        "score_free": True,
        "independent_review": True,
        "one_screen_execution_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def expected_supervisor_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
    supervisor_final: Mapping[str, object], supervisor_external_sha256: str,
) -> dict:
    return {
        "schema": SUPERVISOR_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": packet_external_sha256,
        "screen_receipt_sha256": supervisor_final["screen_receipt_sha256"],
        "supervisor_final_sha256": supervisor_external_sha256,
        "supervisor_final_internal_sha256": supervisor_final["final_sha256"],
        "shard_manifest_sha256": supervisor_final[
            "shard_manifest_sha256"],
        "shards": len(supervisor_final["shards"]),
        "all_children_exit_zero": True,
        "outcomes_or_statistics_read_by_reviewer": False,
        "independent_review": True,
        "one_aggregate_execution_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    require_publishable(path, "output")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise CompositionControllerRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def _publish_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    require_publishable(path, "review snapshot")
    with partial.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path, follow_symlinks=False)
    partial.unlink()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--parent-repo", required=True, type=Path)
    root.add_argument("--parent-review-record", type=Path)
    root.add_argument("--out", required=True, type=Path)
    root.add_argument("--expected-out-sha256")
    return root


def main() -> int:
    args = parser().parse_args()
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise CompositionControllerRefused(
            "composition packet freeze/verify refuses dirty tree")
    out = args.out.resolve()
    snapshot = (REPO / PARENT_REVIEW_SNAPSHOT_PATH).resolve()
    targets = [out, snapshot, *((REPO / item).resolve()
                                for item in MODEL_PATHS)]
    if out != (REPO / PACKET_PATH).resolve():
        raise CompositionControllerRefused(
            "composition packet output path drift")
    if args.command == "freeze":
        if args.parent_review_record is None:
            raise CompositionControllerRefused(
                "freeze requires the reviewed parent ledger")
        for path in targets:
            require_publishable(path, "composition frozen artifact")
        review = args.parent_review_record.resolve()
    else:
        if (not is_sha256(args.expected_out_sha256)
                or not all(is_regular_unlinked(path) for path in targets)
                or sha256_file(out) != args.expected_out_sha256):
            raise CompositionControllerRefused(
                "composition verification artifact drift")
        review = snapshot
    parent_root = args.parent_repo.resolve()
    data = _validate_parent_fast(parent_root, review)
    _full_parent_replay(parent_root, review, data)
    snapshot_bytes = _review_snapshot_bytes(data["claims"])
    if args.command == "freeze":
        _publish_bytes(snapshot, snapshot_bytes)
    elif snapshot.read_bytes() != snapshot_bytes:
        raise CompositionControllerRefused(
            "parent review snapshot content drift")
    exports = _copy_models(data, verify=args.command == "verify")
    output = build_packet(
        git=_git("rev-parse", "HEAD"), parent_root=parent_root, data=data,
        review_snapshot=snapshot, exports=exports)
    if args.command == "freeze":
        publish_exclusive(out, output)
    elif load_json(out) != output:
        raise CompositionControllerRefused(
            "composition packet full verification drift")
    print(json.dumps({
        "status": "FROZEN" if args.command == "freeze" else "VERIFIED",
        "packet_sha256": sha256_file(out),
        "packet_internal_sha256": output["packet_sha256"],
        "parent_state_result_sha256": PARENT_RESULT_SHA256,
        "selected_capability": output["selected_capability"],
        "model_exports": len(output["model_exports"]),
        "screen_clusters": SCREEN_CLUSTERS,
        "screen_launch_authorized": False,
        "strength_claim": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CompositionControllerRefused, PARENT.MidlateStateControllerRefused,
            NPNET.StageCNumpyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
