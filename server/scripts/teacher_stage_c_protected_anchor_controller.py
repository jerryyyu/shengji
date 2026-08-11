#!/usr/bin/env python3
"""Freeze the post-terminal Stage-C protected-anchor capability.

The reviewed V11-free Stage-C training run completed with ``SELECT_NONE``:
unconditionally taking the model's top-ranked action did not beat candidate
zero on CALIB.  This controller does not reinterpret that terminal decision.
It reopens the exact completed run and asks a narrower, production-shaped
question on DESIGN/CALIB only: does the same play-ranking ensemble help when
candidate zero remains the incumbent and an alternative is used only when its
mean rank-logit margin clears a fixed threshold?

The threshold grid was explored after the V1 terminal result.  Consequently,
CALIB is diagnostic here, not fresh confirmation.  Threshold selection is
recomputed from DESIGN only, the untouched fresh REPORT population remains
sealed, and the resulting packet authorizes neither REPORT access nor another
training run.  A separate independent review is required before a downstream
controller may freeze one REPORT evaluation for this exact capability.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import stat
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_training_controller as TRAIN_CTRL  # noqa: E402
import teacher_stage_c_training_runtime as TRAIN_RUNTIME  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-protected-anchor-capability-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-protected-anchor-capability-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-protected-anchor-v1"
PACKET_PATH = f"server/runs/logs/{RUN_ID}/capability_packet.json"
REVIEW_SCHEMA = "teacher-stage-c-protected-anchor-capability-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_PROTECTED_ANCHOR_CAPABILITY_V1_REVIEW "

PARENT_GIT = "18a6fa133c16973206b9f19cccba493476714bee"
PARENT_RUN_ID = "teacher-v3-hard-tail-stage-c-v11-free-training-v1"
PARENT_RUN_ROOT = f"server/runs/logs/{PARENT_RUN_ID}"
PARENT_CONTROLLER_ROOT = (
    "server/runs/logs/"
    "teacher-v3-hard-tail-stage-c-v11-free-training-controller-v1"
)
TRAINING_PACKET_PATH = f"{PARENT_CONTROLLER_ROOT}/controller_packet.json"
MODEL_DATASET_PATH = f"{PARENT_CONTROLLER_ROOT}/model-dataset.json"
TRAINING_RECEIPT_PATH = f"{PARENT_RUN_ROOT}/training-receipt.json"
TRAINING_AGGREGATE_PATH = f"{PARENT_RUN_ROOT}/training-aggregate.json"
TRAINING_FINAL_PATH = f"{PARENT_RUN_ROOT}/training-supervisor-final.json"

TRAINING_PACKET_SHA256 = \
    "fbc72afac862bb0335a151e88021f27b28fc1554aea4e8d1130498dce775ac81"
MODEL_DATASET_SHA256 = \
    "8cd782d39d80af2919961d098c3f1a3acc2c6cbf1e4d47a79637a1193d66722b"
MODEL_DATASET_INTERNAL_SHA256 = \
    "db7a212231cfeaaea5a5a950fefe9cc297f62f471406b7caa4579ee8ba278124"
TRAINING_RECEIPT_SHA256 = \
    "2c846489b8c9818cb18a8dc6c69fc2dc7adcfc9285f76cb719ac6300d806ce38"
TRAINING_AGGREGATE_SHA256 = \
    "7023b3aa08f399d582576b9998e5078db56d82a91eb2a41db228b4e2572fc4fb"
TRAINING_AGGREGATE_INTERNAL_SHA256 = \
    "b8dc1bf9a14fb7b55b888243e8878361a57ee854692c595f1bc79a901927b0a7"
TRAINING_FINAL_SHA256 = \
    "e38a3f42bee94459cd9d5cb19e53aeec9ccf29d3c97a09c0cc68ba0298376221"
TRAINING_FINAL_INTERNAL_SHA256 = \
    "64558a1ce42737d74a75699242c78ba88811baf7a8c5524470be1f3aae66d7d8"
TRAINING_REVIEW_RECORD_SHA256 = \
    "d5aae938a86c5ce461bb3a8b3a5bffe745f635bca5b3aa4ed2b6b2a30d300d52"

SURFACE = "play"
HEAD = "ranking"
EPOCH = 32
CURVE_FRACTION = 1.0
THRESHOLD_GRID = (0.0, 0.001, 0.002, 0.005, 0.01, 0.02,
                  0.05, 0.1, 0.2, 0.5, 1.0)
EXPECTED_SELECTED_THRESHOLD = 0.2
MIN_POSITIVE_SEEDS = 6

SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_protected_anchor_controller.py",
    "server/scripts/teacher_stage_c_training_controller.py",
    "server/scripts/teacher_stage_c_training_runtime.py",
    "server/shengji/rl/stage_c_model.py",
    "server/shengji/rl/stage_c_training.py",
    "server/shengji/rl/encode.py",
)


class ProtectedAnchorRefused(RuntimeError):
    """A parent, checkpoint, metric, policy, or authority identity drifted."""


canonical_json = TRAIN_CTRL.canonical_json
sha256_bytes = TRAIN_CTRL.sha256_bytes
sha256_file = TRAIN_CTRL.sha256_file
self_hash = TRAIN_CTRL.self_hash


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ProtectedAnchorRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ProtectedAnchorRefused(f"cannot read JSON {path}: {exc}") \
            from exc
    if not isinstance(value, dict):
        raise ProtectedAnchorRefused(f"JSON root is not an object: {path}")
    return value


def _git(*args: str, repo: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _require_clean_tree(expected_git: str) -> None:
    if _git("rev-parse", "HEAD") != expected_git:
        raise ProtectedAnchorRefused("protected-anchor producer git drift")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ProtectedAnchorRefused("protected-anchor freeze refuses dirty tree")


def _source_sha256s() -> dict[str, str]:
    result = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise ProtectedAnchorRefused(
                f"protected-anchor source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return result


def _require_exact(path: Path, expected_sha256: str, label: str) -> None:
    if (not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ProtectedAnchorRefused(f"{label} path/SHA drift")


def _require_parent_runtime_identity(evidence_repo: Path) -> None:
    """Ensure the code executing V1 replay is byte-identical to V1 source."""
    for logical in TRAIN_CTRL.SOURCE_PATHS:
        current = REPO / logical
        parent = evidence_repo / logical
        if (not is_regular_unlinked(current)
                or not is_regular_unlinked(parent)
                or sha256_file(current) != sha256_file(parent)):
            raise ProtectedAnchorRefused(
                f"training replay source drift: {logical}")


@contextlib.contextmanager
def _training_repo_scope(evidence_repo: Path):
    """Point the already-reviewed V1 validators at an immutable evidence tree."""
    old_ctrl_repo = TRAIN_CTRL.REPO
    old_runtime_repo = TRAIN_RUNTIME.REPO
    try:
        TRAIN_CTRL.REPO = evidence_repo
        TRAIN_RUNTIME.REPO = evidence_repo
        yield
    finally:
        TRAIN_CTRL.REPO = old_ctrl_repo
        TRAIN_RUNTIME.REPO = old_runtime_repo


def _parent_paths(evidence_repo: Path) -> dict[str, Path]:
    return {
        "packet": evidence_repo / TRAINING_PACKET_PATH,
        "dataset": evidence_repo / MODEL_DATASET_PATH,
        "receipt": evidence_repo / TRAINING_RECEIPT_PATH,
        "aggregate": evidence_repo / TRAINING_AGGREGATE_PATH,
        "final": evidence_repo / TRAINING_FINAL_PATH,
    }


def validate_parent(
    *, evidence_repo: Path, training_review_record: Path,
) -> tuple[dict, dict, dict, list[dict]]:
    """Fully replay the terminal V1 aggregate and return its exact play cells."""
    if (not evidence_repo.is_dir()
            or _git("rev-parse", "HEAD", repo=evidence_repo) != PARENT_GIT):
        raise ProtectedAnchorRefused("training evidence repo/git drift")
    _require_parent_runtime_identity(evidence_repo)
    _require_exact(training_review_record, TRAINING_REVIEW_RECORD_SHA256,
                   "training review record")
    paths = _parent_paths(evidence_repo)
    for key, expected in (
        ("packet", TRAINING_PACKET_SHA256),
        ("dataset", MODEL_DATASET_SHA256),
        ("receipt", TRAINING_RECEIPT_SHA256),
        ("aggregate", TRAINING_AGGREGATE_SHA256),
        ("final", TRAINING_FINAL_SHA256),
    ):
        _require_exact(paths[key], expected, f"training {key}")

    with _training_repo_scope(evidence_repo):
        packet, dataset = TRAIN_RUNTIME._packet(
            paths["packet"], TRAINING_PACKET_SHA256)
        packet["external_sha256"] = TRAINING_PACKET_SHA256
        TRAIN_RUNTIME._receipt(
            paths["receipt"], TRAINING_RECEIPT_SHA256, packet,
            TRAINING_PACKET_SHA256, training_review_record)
        cell_paths = [evidence_repo / str(value["result"])
                      for value in packet["schedule"]["cells"]]
        recomputed = TRAIN_RUNTIME.recompute_aggregate(
            packet_path=paths["packet"],
            expected_packet_sha256=TRAINING_PACKET_SHA256,
            receipt_path=paths["receipt"],
            expected_receipt_sha256=TRAINING_RECEIPT_SHA256,
            review_record=training_review_record,
            cell_paths=cell_paths,
        )

    aggregate = load_json(paths["aggregate"])
    final = load_json(paths["final"])
    if aggregate != recomputed:
        raise ProtectedAnchorRefused("training aggregate full replay drift")
    if (dataset.get("dataset_sha256") != MODEL_DATASET_INTERNAL_SHA256
            or aggregate.get("aggregate_sha256")
            != TRAINING_AGGREGATE_INTERNAL_SHA256
            or aggregate.get("decision") != "SELECT_NONE"
            or aggregate.get("report_rows_opened") != 0
            or aggregate.get("report_open_authorized") is not False
            or aggregate.get("strength_claim") is not False):
        raise ProtectedAnchorRefused("terminal training identity/authority drift")
    if (final.get("final_sha256") != TRAINING_FINAL_INTERNAL_SHA256
            or final.get("final_sha256") != self_hash(final, "final_sha256")
            or final.get("aggregate_sha256") != TRAINING_AGGREGATE_SHA256
            or final.get("decision") != "SELECT_NONE"
            or final.get("cells_complete") != 48
            or final.get("report_rows_opened") != 0
            or final.get("report_open_authorized") is not False
            or final.get("report_packet_review_authorized") is not False
            or final.get("retry_authorized") is not False):
        raise ProtectedAnchorRefused("training supervisor terminal drift")

    play_cells = [value for value in packet["schedule"]["cells"]
                  if value.get("surface") == SURFACE
                  and value.get("curve_fraction") == CURVE_FRACTION]
    if (len(play_cells) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in play_cells]
            != list(MODEL.TRAINING_SEEDS)):
        raise ProtectedAnchorRefused("full-curve play cell population drift")
    return packet, dataset, aggregate, play_cells


def protected_metrics(
    examples: Sequence[Mapping[str, object]],
    rank_rows: Sequence[Sequence[float]], *, threshold: float,
) -> dict:
    """Evaluate strict-margin override with candidate zero as the fallback."""
    if (isinstance(threshold, bool) or not math.isfinite(threshold)
            or threshold < 0
            or len(examples) != len(rank_rows) or not examples):
        raise ProtectedAnchorRefused("protected metric population/threshold drift")
    improvements = []
    margins = []
    overrides = 0
    helpful = 0
    harmful = 0
    neutral = 0
    for example, ranks in zip(examples, rank_rows, strict=True):
        target = example.get("target", {})
        means = target.get("ranking_mean_signed_level_utility")
        count = target.get("candidate_count")
        if (isinstance(count, bool) or not isinstance(count, int) or count < 1
                or not isinstance(means, list) or len(means) != count
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value)) for value in means)
                or len(ranks) != count
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value)) for value in ranks)):
            raise ProtectedAnchorRefused("protected metric candidate drift")
        selected = 0
        margin = 0.0
        if count > 1:
            alternative = max(
                range(1, count), key=lambda index: (float(ranks[index]), -index))
            margin = float(ranks[alternative]) - float(ranks[0])
            if margin > threshold:
                selected = alternative
        improvement = float(means[selected]) - float(means[0])
        improvements.append(improvement)
        margins.append(margin)
        if selected:
            overrides += 1
            if improvement > 0:
                helpful += 1
            elif improvement < 0:
                harmful += 1
            else:
                neutral += 1
    return {
        "states": len(examples),
        "threshold": threshold,
        "strict_greater_than_threshold": True,
        "overrides": overrides,
        "override_rate": overrides / len(examples),
        "helpful_overrides": helpful,
        "harmful_overrides": harmful,
        "neutral_overrides": neutral,
        "helpful_override_rate": helpful / overrides if overrides else 0.0,
        "mean_teacher_improvement_vs_candidate0":
            statistics.fmean(improvements),
        "mean_available_alternative_margin": statistics.fmean(margins),
    }


def ensemble_rank_rows(
    rows_by_seed: Sequence[Sequence[Sequence[float]]],
) -> list[list[float]]:
    if not rows_by_seed:
        raise ProtectedAnchorRefused("protected ensemble is empty")
    states = len(rows_by_seed[0])
    if states == 0 or any(len(rows) != states for rows in rows_by_seed):
        raise ProtectedAnchorRefused("protected ensemble state population drift")
    result = []
    for state_index in range(states):
        count = len(rows_by_seed[0][state_index])
        if count == 0 or any(len(rows[state_index]) != count
                             for rows in rows_by_seed):
            raise ProtectedAnchorRefused(
                "protected ensemble candidate population drift")
        result.append([
            statistics.fmean(float(rows[state_index][candidate])
                             for rows in rows_by_seed)
            for candidate in range(count)
        ])
    return result


def cohort_summary(seed_metrics: Sequence[Mapping[str, object]]) -> dict:
    if (len(seed_metrics) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in seed_metrics]
            != list(MODEL.TRAINING_SEEDS)):
        raise ProtectedAnchorRefused("protected cohort seed identity drift")
    gains = [float(value["metrics"][
        "mean_teacher_improvement_vs_candidate0"]) for value in seed_metrics]
    return {
        "seed_count": len(gains),
        "positive_seeds": sum(value > 0 for value in gains),
        "median_teacher_improvement_vs_candidate0": statistics.median(gains),
        "mean_teacher_improvement_vs_candidate0": statistics.fmean(gains),
        "seed_metrics": list(seed_metrics),
    }


def choose_design_threshold(rows: Sequence[Mapping[str, object]]) -> float:
    if ([float(value.get("threshold")) for value in rows]
            != list(THRESHOLD_GRID)):
        raise ProtectedAnchorRefused("protected threshold grid drift")
    selected = max(
        rows,
        key=lambda value: (
            float(value["cohort"][
                "median_teacher_improvement_vs_candidate0"]),
            int(value["cohort"]["positive_seeds"]),
            -float(value["threshold"]),
        ),
    )
    return float(selected["threshold"])


def _checkpoint_manifest(
    *, evidence_repo: Path, packet: Mapping[str, object],
    play_cells: Sequence[Mapping[str, object]],
) -> tuple[list[dict], list[object]]:
    manifest = []
    nets = []
    for cell in play_cells:
        cell_path = evidence_repo / str(cell["result"])
        value = load_json(cell_path)
        snapshot = next((item for item in value.get("snapshots", [])
                         if item.get("epoch") == EPOCH), None)
        if not isinstance(snapshot, dict):
            raise ProtectedAnchorRefused("protected checkpoint epoch missing")
        checkpoint_path = evidence_repo / str(snapshot.get("checkpoint_path"))
        _require_exact(checkpoint_path, str(snapshot.get("checkpoint_sha256")),
                       "protected checkpoint")
        contract = TRAIN_RUNTIME._snapshot_contract(
            packet, cell, EPOCH, str(snapshot.get("model_state_sha256")))
        if snapshot.get("checkpoint_contract") != contract:
            raise ProtectedAnchorRefused("protected checkpoint contract drift")
        reopened = TRAIN.load_snapshot(
            checkpoint_path, expected_contract=contract)
        net = MODEL.StageCRankingOutcomeNet(hidden=TRAIN.HIDDEN)
        net.load_state_dict(reopened["state_dict"], strict=True)
        nets.append(net)
        manifest.append({
            "surface": SURFACE,
            "head": HEAD,
            "seed": cell["seed"],
            "curve_fraction": CURVE_FRACTION,
            "epoch": EPOCH,
            "checkpoint_path": snapshot["checkpoint_path"],
            "checkpoint_sha256": snapshot["checkpoint_sha256"],
            "model_state_sha256": snapshot["model_state_sha256"],
            "checkpoint_contract": contract,
        })
    return manifest, nets


def _split_diagnostics(
    examples: Sequence[Mapping[str, object]], nets: Sequence[object],
) -> tuple[list[dict], dict[str, list[list[float]]]]:
    ordered = sorted(examples, key=lambda value: str(value["state_id"]))
    ranks_by_seed = []
    for net in nets:
        ranks, _outcomes = TRAIN.predict_examples(net, ordered)
        ranks_by_seed.append(ranks)
    rows = []
    for threshold in THRESHOLD_GRID:
        seed_metrics = [{
            "seed": seed,
            "metrics": protected_metrics(ordered, ranks, threshold=threshold),
        } for seed, ranks in zip(
            MODEL.TRAINING_SEEDS, ranks_by_seed, strict=True)]
        rows.append({
            "threshold": threshold,
            "cohort": cohort_summary(seed_metrics),
            "ensemble": protected_metrics(
                ordered, ensemble_rank_rows(ranks_by_seed),
                threshold=threshold),
        })
    return rows, {str(seed): ranks for seed, ranks in zip(
        MODEL.TRAINING_SEEDS, ranks_by_seed, strict=True)}


def build_packet(
    *, evidence_repo: Path, training_review_record: Path,
    expected_git: str,
) -> dict:
    _require_clean_tree(expected_git)
    packet, dataset, aggregate, play_cells = validate_parent(
        evidence_repo=evidence_repo,
        training_review_record=training_review_record,
    )
    manifest, nets = _checkpoint_manifest(
        evidence_repo=evidence_repo, packet=packet, play_cells=play_cells)
    design_rows, _design_predictions = _split_diagnostics(
        dataset["examples"]["DESIGN"][SURFACE], nets)
    selected_threshold = choose_design_threshold(design_rows)
    if selected_threshold != EXPECTED_SELECTED_THRESHOLD:
        raise ProtectedAnchorRefused(
            "DESIGN no longer selects the diagnosed 0.2 threshold")
    calib_rows, _calib_predictions = _split_diagnostics(
        dataset["examples"]["CALIB"][SURFACE], nets)
    design_selected = next(value for value in design_rows
                           if value["threshold"] == selected_threshold)
    calib_selected = next(value for value in calib_rows
                          if value["threshold"] == selected_threshold)
    design_cohort = design_selected["cohort"]
    calib_cohort = calib_selected["cohort"]
    screen_pass = (
        design_cohort["positive_seeds"] >= MIN_POSITIVE_SEEDS
        and design_cohort["median_teacher_improvement_vs_candidate0"] > 0
        and design_selected["ensemble"][
            "mean_teacher_improvement_vs_candidate0"] > 0
        and calib_cohort["positive_seeds"] >= MIN_POSITIVE_SEEDS
        and calib_cohort["median_teacher_improvement_vs_candidate0"] > 0
        and calib_selected["ensemble"][
            "mean_teacher_improvement_vs_candidate0"] > 0
    )
    if not screen_pass:
        raise ProtectedAnchorRefused(
            "protected-anchor DESIGN/CALIB diagnostic no longer passes")

    value = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": {
            "git": expected_git,
            "tree_dirty": False,
            "sources": _source_sha256s(),
        },
        "parent": {
            "git": PARENT_GIT,
            "run_id": PARENT_RUN_ID,
            "training_packet_sha256": TRAINING_PACKET_SHA256,
            "model_dataset_sha256": MODEL_DATASET_SHA256,
            "model_dataset_internal_sha256":
                MODEL_DATASET_INTERNAL_SHA256,
            "training_receipt_sha256": TRAINING_RECEIPT_SHA256,
            "training_aggregate_sha256": TRAINING_AGGREGATE_SHA256,
            "training_aggregate_internal_sha256":
                TRAINING_AGGREGATE_INTERNAL_SHA256,
            "training_supervisor_final_sha256": TRAINING_FINAL_SHA256,
            "training_supervisor_final_internal_sha256":
                TRAINING_FINAL_INTERNAL_SHA256,
            "training_review_record_sha256":
                TRAINING_REVIEW_RECORD_SHA256,
            "terminal_decision": aggregate["decision"],
            "report_rows_opened": 0,
        },
        "capability": {
            "surface": SURFACE,
            "head": HEAD,
            "epoch": EPOCH,
            "curve_fraction": CURVE_FRACTION,
            "seeds": list(MODEL.TRAINING_SEEDS),
            "ensemble": "arithmetic mean of per-seed rank logits",
            "incumbent": "candidate0",
            "alternative": (
                "highest ensemble-mean rank logit among candidate indices 1+; "
                "ties choose the lowest index"
            ),
            "activation": (
                "override candidate0 iff alternative ensemble rank logit minus "
                "candidate0 ensemble rank logit is strictly greater than 0.2"
            ),
            "threshold": selected_threshold,
            "strict_greater_than_threshold": True,
            "fallback": "candidate0",
            "bury_behavior": "unchanged incumbent",
        },
        "checkpoint_manifest": manifest,
        "threshold_selection": {
            "grid": list(THRESHOLD_GRID),
            "selection_split": "DESIGN",
            "criterion": (
                "maximum median per-seed mean Teacher improvement versus "
                "candidate0; then positive-seed count; then lower threshold"
            ),
            "selected_threshold": selected_threshold,
            "post_terminal_exploration": True,
            "calib_was_inspected_during_diagnosis": True,
            "calib_role": "diagnostic screen only, not fresh confirmation",
            "fresh_report_role": "only untouched final offline confirmation",
        },
        "diagnostics": {
            "design_thresholds": design_rows,
            "calib_thresholds": calib_rows,
            "selected_design": design_selected,
            "selected_calib": calib_selected,
            "screen_gate": {
                "minimum_positive_seeds": MIN_POSITIVE_SEEDS,
                "requires_positive_cohort_median": True,
                "requires_positive_ensemble_mean": True,
                "design_pass": True,
                "calib_diagnostic_pass": True,
                "decision": "REQUEST_EXTERNAL_CAPABILITY_REVIEW",
            },
        },
        "authority": {
            "new_training_authorized": False,
            "training_retry_authorized": False,
            "report_rows_opened": 0,
            "report_open_authorized": False,
            "one_report_controller_freeze_authorized": False,
            "report_execution_authorized": False,
            "composition_authorized": False,
            "whole_game_screen_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    value["checkpoint_manifest_sha256"] = sha256_bytes(
        canonical_json(manifest))
    value["diagnostics_sha256"] = sha256_bytes(
        canonical_json(value["diagnostics"]))
    value["packet_sha256"] = self_hash(value, "packet_sha256")
    return value


def expected_review_claim(packet: Mapping[str, object],
                          packet_external_sha256: str) -> dict:
    capability = packet.get("capability", {})
    diagnostics = packet.get("diagnostics", {})
    selected_design = diagnostics.get("selected_design", {})
    selected_calib = diagnostics.get("selected_calib", {})
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet.get("producer", {}).get("git"),
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet.get("packet_sha256"),
        "parent_training_aggregate_sha256": packet.get("parent", {}).get(
            "training_aggregate_sha256"),
        "parent_terminal_decision": packet.get("parent", {}).get(
            "terminal_decision"),
        "checkpoint_manifest_sha256": packet.get(
            "checkpoint_manifest_sha256"),
        "diagnostics_sha256": packet.get("diagnostics_sha256"),
        "surface": capability.get("surface"),
        "head": capability.get("head"),
        "epoch": capability.get("epoch"),
        "threshold": capability.get("threshold"),
        "seeds": capability.get("seeds"),
        "design_positive_seeds": selected_design.get("cohort", {}).get(
            "positive_seeds"),
        "design_median_improvement": selected_design.get("cohort", {}).get(
            "median_teacher_improvement_vs_candidate0"),
        "design_ensemble_improvement": selected_design.get(
            "ensemble", {}).get("mean_teacher_improvement_vs_candidate0"),
        "calib_positive_seeds": selected_calib.get("cohort", {}).get(
            "positive_seeds"),
        "calib_median_improvement": selected_calib.get("cohort", {}).get(
            "median_teacher_improvement_vs_candidate0"),
        "calib_ensemble_improvement": selected_calib.get(
            "ensemble", {}).get("mean_teacher_improvement_vs_candidate0"),
        "calib_is_diagnostic_not_fresh_confirmation": True,
        "fresh_report_rows_opened": 0,
        "independent_review": True,
        "one_protected_report_controller_freeze_authorized": True,
        "report_open_authorized": False,
        "report_execution_authorized": False,
        "composition_authorized": False,
        "whole_game_screen_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ProtectedAnchorRefused(f"refusing existing output: {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise ProtectedAnchorRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def freeze(*, evidence_repo: Path, training_review_record: Path,
           expected_git: str, out: Path) -> dict:
    expected_out = (REPO / PACKET_PATH).resolve()
    if out.resolve() != expected_out:
        raise ProtectedAnchorRefused("protected-anchor output path drift")
    value = build_packet(
        evidence_repo=evidence_repo,
        training_review_record=training_review_record,
        expected_git=expected_git,
    )
    _publish_exclusive(out, value)
    return value


def verify(*, evidence_repo: Path, training_review_record: Path,
           expected_git: str, packet_path: Path,
           expected_packet_sha256: str) -> dict:
    expected_path = (REPO / PACKET_PATH).resolve()
    if packet_path.resolve() != expected_path:
        raise ProtectedAnchorRefused("protected-anchor packet path drift")
    _require_exact(packet_path, expected_packet_sha256,
                   "protected-anchor packet")
    actual = load_json(packet_path)
    expected = build_packet(
        evidence_repo=evidence_repo,
        training_review_record=training_review_record,
        expected_git=expected_git,
    )
    if actual != expected:
        raise ProtectedAnchorRefused(
            "protected-anchor packet full recomputation drift")
    return {
        "verified": True,
        "packet_sha256": expected_packet_sha256,
        "packet_internal_sha256": actual["packet_sha256"],
        "selected_threshold": actual["capability"]["threshold"],
        "decision": actual["diagnostics"]["screen_gate"]["decision"],
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
    }


def _add_parent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-repo", type=Path, required=True)
    parser.add_argument("--training-review-record", type=Path, required=True)
    parser.add_argument("--expected-git", required=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    _add_parent_args(freeze_parser)
    freeze_parser.add_argument("--out", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    _add_parent_args(verify_parser)
    verify_parser.add_argument("--packet", type=Path, required=True)
    verify_parser.add_argument("--expected-packet-sha256", required=True)
    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("--packet", type=Path, required=True)
    claim_parser.add_argument("--expected-packet-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            result = freeze(
                evidence_repo=args.evidence_repo,
                training_review_record=args.training_review_record,
                expected_git=args.expected_git,
                out=args.out,
            )
        elif args.command == "verify":
            result = verify(
                evidence_repo=args.evidence_repo,
                training_review_record=args.training_review_record,
                expected_git=args.expected_git,
                packet_path=args.packet,
                expected_packet_sha256=args.expected_packet_sha256,
            )
        else:
            _require_exact(args.packet, args.expected_packet_sha256,
                           "protected-anchor packet")
            packet = load_json(args.packet)
            if (packet.get("schema") != SCHEMA
                    or packet.get("packet_sha256")
                    != self_hash(packet, "packet_sha256")):
                raise ProtectedAnchorRefused(
                    "protected-anchor packet identity drift")
            result = expected_review_claim(packet,
                                           args.expected_packet_sha256)
    except (ProtectedAnchorRefused,
            TRAIN_RUNTIME.TrainingRuntimeRefused,
            TRAIN_CTRL.TrainingControllerRefused,
            TRAIN.StageCTrainingError,
            MODEL.StageCModelError,
            OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"error": str(exc), "status": "REFUSED"},
                         sort_keys=True), file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
