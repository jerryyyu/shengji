#!/usr/bin/env python3
"""Freeze the existing expanded Stage-C normal-play capability for review.

The 7,040-state expanded training run produced two eligible epoch-32 ranking
surfaces.  Its global selector advanced only the larger CALIB number (bury),
so the independently eligible play ensemble never received a fresh REPORT
exam.  This controller reopens that already-trained eight-seed play cohort,
recomputes broad DESIGN/CALIB diagnostics, and binds it to a fifth score-free
play-only REPORT population after conservatively treating all four earlier
512-state populations as spent.

No REPORT label, model prediction, utility, composition, strength claim,
promotion, or deployment is produced here.  An independent raw review marker
is required before any downstream REPORT controller may be frozen.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_expanded_report_controller as BASE  # noqa: E402
import teacher_stage_c_expansion_controller as EXPANSION  # noqa: E402
from shengji.rl import stage_c_expansion as EXP  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-expanded-play-capability-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-expanded-play-capability-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-expanded-play-capability-v1"
PACKET_PATH = f"server/runs/logs/{RUN_ID}/capability_packet.json"
REVIEW_SCHEMA = "teacher-stage-c-expanded-play-capability-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_EXPANDED_PLAY_CAPABILITY_V1_REVIEW "
BURY_RESULT_REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_FRESH_REPORT_RESULT_V2_REVIEW "

SURFACE = "play"
HEAD = "ranking"
LOSS_RECIPE = "all_pairs_v1"
EPOCH = 32
CURVE_FRACTION = 1.0

EXPECTED_CAPABILITY = {
    "loss_recipe": LOSS_RECIPE,
    "surface": SURFACE,
    "head": HEAD,
    "epoch": EPOCH,
    "action_improvement_positive_seeds": 8,
    "calibration_positive_seeds": 8,
    "median_action_improvement_vs_candidate0": 0.008819580078125,
    "mean_teacher_regret": 0.08103599548339843,
    "median_outcome_nll_improvement": 0.4915486157138311,
}

EXPECTED_BURY_RESULT_REVIEW = {
    "candidate_world_ceiling": 264128,
    "candidate_world_ceiling_respected": True,
    "candidate_worlds_attempted": 264128,
    "candidate_worlds_completed": 264128,
    "controller_packet_sha256":
        "e856c02eb3d01840bf3ae2969743325cb840d4c5d7b3e75733bebd52909175e2",
    "decision": "SELECT_NONE",
    "evaluation_internal_sha256":
        "61387ca1576944e9c6eccace9aca01b8759d95808c638326c46891578ffd4147",
    "fresh_report_selection_sha256":
        "3c318da2c28feca7e7a4bb2698c3d0b82ae165bac367705f52773ca4b0aa41e4",
    "git": "564db02e58c91001c5ae7b929b42462eff430ffa",
    "independent_review": True,
    "one_composition_controller_freeze_authorized": False,
    "production_deployment": False,
    "production_promotion": False,
    "protected_policy": None,
    "report_label_refusals": 0,
    "report_label_shards": 8,
    "report_receipt_sha256":
        "463ba30c1b0132e6fce66402a75ab5a0b30293d4b52392da7286dca36b48ae98",
    "report_result_internal_sha256":
        "99f33ad88b5499fd2b7d9eaacdb1cf1d6756d540a1e3d6fabec4b5929dce00e9",
    "report_result_sha256":
        "2e21a9bf26ed20d97c2ff8b2c2c44a282e971a259a47bc2f941bb195f472ac4d",
    "report_reuse_authorized": False,
    "report_schedule_sha256":
        "b5397f5628091cd283b2057a6316b3cae71e9aa13ce826a7057301a09933394d",
    "run_id": "teacher-v3-hard-tail-stage-c-expanded-fresh-report-v2",
    "schema": "teacher-stage-c-expanded-fresh-report-result-review-v2",
    "selected_capability": {
        "action_improvement_positive_seeds": 8,
        "calibration_positive_seeds": 8,
        "epoch": 32,
        "head": "ranking",
        "loss_recipe": "all_pairs_v1",
        "mean_teacher_regret": 0.1615142822265625,
        "median_action_improvement_vs_candidate0": 0.01641845703125,
        "median_outcome_nll_improvement": 0.02034193337756174,
        "surface": "bury",
    },
    "selected_surface_rows_labeled": 32,
    "strength_claim": False,
    "supervisor_final_internal_sha256":
        "87d7e2e6e46159f2085180986dc3761ac0a87f4a7afe76c41cf3d05b9fe95bef",
    "supervisor_final_sha256":
        "126d73cd18fb667ad045c0d441b61bf43071473fe9588b72bf5a776beee58387",
    "terminal_full_recomputation_passed": True,
    "v11_checkpoint_loaded": False,
    "verdict": "PASS",
}

SOURCE_PATHS = tuple(dict.fromkeys((
    "server/scripts/teacher_stage_c_expanded_play_capability.py",
    "server/scripts/teacher_stage_c_expanded_report_controller.py",
    "server/shengji/rl/stage_c_expansion.py",
    "server/shengji/rl/stage_c_report.py",
    *BASE.TRAIN_CTRL.SOURCE_PATHS,
    *EXPANSION.SOURCE_PATHS,
)))


class ExpandedPlayCapabilityRefused(RuntimeError):
    """A parent, model, diagnostic, fresh selection, or authority drifted."""


canonical_json = BASE.canonical_json
sha256_bytes = BASE.sha256_bytes
sha256_file = BASE.sha256_file
self_hash = BASE.self_hash
is_regular_unlinked = BASE.is_regular_unlinked
load_json = BASE.load_json
marker_claim = BASE.marker_claim


def _manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _require_clean_tree(expected_git: str) -> None:
    if _git("rev-parse", "HEAD") != expected_git:
        raise ExpandedPlayCapabilityRefused(
            "expanded play capability producer Git drift")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ExpandedPlayCapabilityRefused(
            "expanded play capability refuses dirty tree")


def _source_sha256s() -> dict[str, str]:
    result = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise ExpandedPlayCapabilityRefused(
                f"expanded play source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return dict(sorted(result.items()))


def _play_capability(aggregate: Mapping[str, object]) -> dict:
    candidates = aggregate.get("selection", {}).get("candidates")
    if not isinstance(candidates, list):
        raise ExpandedPlayCapabilityRefused(
            "expanded play candidate population missing")
    matches = [value for value in candidates if isinstance(value, dict)
               and all(value.get(key) == expected
                       for key, expected in EXPECTED_CAPABILITY.items())]
    if (len(matches) != 1 or matches[0].get("eligible") is not True
            or matches[0].get("outcome_calibration_required") is not False):
        raise ExpandedPlayCapabilityRefused(
            "expanded play capability was not independently eligible")
    return dict(EXPECTED_CAPABILITY)


def _play_manifest(
    *, evidence_repo: Path, training_packet: Mapping[str, object],
    aggregate: Mapping[str, object], reopen: bool,
) -> tuple[list[dict], list[object]]:
    cells = [cell for cell in training_packet["schedule"]["cells"]
             if cell.get("surface") == SURFACE
             and cell.get("loss_recipe") == LOSS_RECIPE
             and cell.get("curve_fraction") == CURVE_FRACTION]
    if (len(cells) != len(MODEL.TRAINING_SEEDS)
            or [cell.get("seed") for cell in cells]
            != list(MODEL.TRAINING_SEEDS)):
        raise ExpandedPlayCapabilityRefused(
            "expanded full-data play cell population drift")
    summaries = aggregate.get("cells")
    if not isinstance(summaries, list):
        raise ExpandedPlayCapabilityRefused(
            "expanded aggregate cell population drift")
    manifest = []
    nets = []
    for cell in cells:
        summary = next((value for value in summaries
                        if value.get("index") == cell["index"]), None)
        if not isinstance(summary, dict):
            raise ExpandedPlayCapabilityRefused(
                "expanded play cell summary missing")
        path = BASE._evidence_path(
            evidence_repo, str(cell["result"]), str(summary["external_sha256"]))
        value = load_json(path)
        if (value.get("cell_sha256") != self_hash(value, "cell_sha256")
                or value.get("cell_id") != cell["cell_id"]
                or value.get("surface") != SURFACE
                or value.get("loss_recipe") != LOSS_RECIPE
                or value.get("seed") != cell["seed"]
                or value.get("curve_fraction") != CURVE_FRACTION):
            raise ExpandedPlayCapabilityRefused(
                "expanded play cell identity drift")
        snapshot = next((item for item in value.get("snapshots", [])
                         if item.get("epoch") == EPOCH), None)
        if not isinstance(snapshot, dict):
            raise ExpandedPlayCapabilityRefused(
                "expanded play checkpoint epoch missing")
        checkpoint = (evidence_repo
                      / str(snapshot["checkpoint_path"])).resolve()
        if (not is_regular_unlinked(checkpoint)
                or sha256_file(checkpoint) != snapshot["checkpoint_sha256"]):
            raise ExpandedPlayCapabilityRefused(
                "expanded play checkpoint external identity drift")
        contract = BASE._checkpoint_contract(
            training_packet, cell, snapshot)
        if snapshot.get("checkpoint_contract") != contract:
            raise ExpandedPlayCapabilityRefused(
                "expanded play checkpoint contract drift")
        reopened = TRAIN.load_snapshot(
            checkpoint, expected_contract=contract) if reopen else None
        if reopened is not None:
            net = MODEL.StageCRankingOutcomeNet(hidden=TRAIN.HIDDEN)
            net.load_state_dict(reopened["state_dict"], strict=True)
            nets.append(net)
        manifest.append({
            "surface": SURFACE,
            "head": HEAD,
            "loss_recipe": LOSS_RECIPE,
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
) -> dict:
    ordered = sorted(examples, key=lambda value: str(value["state_id"]))
    if not ordered or len(nets) != len(MODEL.TRAINING_SEEDS):
        raise ExpandedPlayCapabilityRefused(
            "expanded play diagnostic population drift")
    predictions = [TRAIN.predict_examples(net, ordered) for net in nets]
    ranks, outcomes = REPORT.average_ensemble(ordered, predictions)
    canonical = MODEL.evaluate_predictions(ordered, ranks, outcomes)
    improvements = []
    trigger_count = 0
    strata: dict[str, list[float]] = defaultdict(list)
    for example, rank_values, outcome_values in zip(
            ordered, ranks, outcomes, strict=True):
        selected = REPORT._selected_index(
            rank_values, outcome_values, HEAD)
        means = example["target"]["ranking_mean_signed_level_utility"]
        improvement = float(means[selected]) - float(means[0])
        improvements.append(improvement)
        strata[str(example["stratum"])].append(improvement)
        trigger_count += selected != 0
    primary = REPORT.one_sided_summary(improvements)
    return {
        "states": len(ordered),
        "proposal_triggers": trigger_count,
        "proposal_trigger_rate": trigger_count / len(ordered),
        "teacher_improvement_vs_candidate0": primary,
        "canonical_metrics": canonical,
        "stratum_diagnostics": {
            key: {"n": len(values),
                  "mean_teacher_improvement_vs_candidate0":
                      statistics.fmean(values)}
            for key, values in sorted(strata.items())
        },
    }


def _fresh_play_selection(
    *, capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path,
) -> dict:
    try:
        capture, original, _verification, _state_review, shards, current = \
            EXPANSION.validate_evidence(
                evidence_repo=capture_evidence_repo,
                state_set_review_record=state_set_review_record,
                fresh_report_review_record=fresh_report_review_record)
        selection = EXP.select_play_successor_report_states(
            capture_packet=capture,
            retained_states=[state for shard in shards
                             for state in shard["retained_states"]],
            original_states=original["states"],
            current_fresh_report_states=current)
    except (EXPANSION.ExpansionControllerRefused,
            EXP.ExpansionError) as exc:
        raise ExpandedPlayCapabilityRefused(
            f"expanded play selection refused: {exc}") from exc
    if (selection.get("schema") != EXP.PLAY_SUCCESSOR_REPORT_SCHEMA
            or selection.get("state_count") != EXP.PLAY_REPORT_STATES
            or selection.get("surface_counts") != {"play": 480}
            or selection.get("spent_report_populations") != 4
            or selection.get("spent_report_states") != 2_048
            or selection.get("spent_state_overlap") != 0
            or selection.get("spent_deal_seed_overlap") != 0
            or selection.get("labels_or_outcomes_opened") is not False
            or selection.get("report_labels_opened") is not False):
        raise ExpandedPlayCapabilityRefused(
            "expanded play selection contract drift")
    return selection


def _bury_result_review(path: Path) -> dict:
    claim = marker_claim(path, BURY_RESULT_REVIEW_MARKER)
    if claim != EXPECTED_BURY_RESULT_REVIEW:
        raise ExpandedPlayCapabilityRefused(
            "expanded bury terminal review drift")
    return claim


def _selection_summary(selection: Mapping[str, object]) -> dict:
    return {
        "schema": selection["schema"],
        "selection_rule": selection["selection_rule"],
        "selection_sha256": selection["selection_sha256"],
        "states_sha256": selection["states_sha256"],
        "state_ids_sha256": selection["state_ids_sha256"],
        "state_count": selection["state_count"],
        "surface_counts": selection["surface_counts"],
        "cell_manifest": selection["cell_manifest"],
        "cell_manifest_sha256": selection["cell_manifest_sha256"],
        "spent_report_populations": selection["spent_report_populations"],
        "spent_report_states": selection["spent_report_states"],
        "spent_report_state_ids_sha256":
            selection["spent_report_state_ids_sha256"],
        "spent_report_deal_seeds_sha256":
            selection["spent_report_deal_seeds_sha256"],
        "prior_fourth_report_selection_sha256":
            selection["prior_fourth_report_selection_sha256"],
        "spent_state_overlap": selection["spent_state_overlap"],
        "spent_deal_seed_overlap": selection["spent_deal_seed_overlap"],
        "remaining_report_supply_after_selection":
            selection["remaining_report_supply_after_selection"],
        "state_material_published": False,
        "labels_or_outcomes_opened": False,
        "report_labels_opened": False,
    }


def build_packet(
    *, evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, bury_result_review_record: Path,
    expected_git: str,
) -> dict:
    _require_clean_tree(expected_git)
    try:
        training_packet, dataset, _receipt, aggregate, _final, _bury = \
            BASE.validate_training_evidence(
                evidence_repo=evidence_repo,
                training_result_review_record=training_result_review_record,
                reopen_checkpoints=True)
    except BASE.ReportControllerRefused as exc:
        raise ExpandedPlayCapabilityRefused(str(exc)) from exc
    capability = _play_capability(aggregate)
    manifest, nets = _play_manifest(
        evidence_repo=evidence_repo, training_packet=training_packet,
        aggregate=aggregate, reopen=True)
    design = _split_diagnostics(
        dataset["examples"]["DESIGN"][SURFACE], nets)
    calib = _split_diagnostics(
        dataset["examples"]["CALIB"][SURFACE], nets)
    if (design["teacher_improvement_vs_candidate0"][
            "one_sided_95_lcb"] <= 0
            or calib["teacher_improvement_vs_candidate0"][
                "one_sided_95_lcb"] <= 0
            or design["proposal_triggers"] <= 0
            or calib["proposal_triggers"] <= 0):
        raise ExpandedPlayCapabilityRefused(
            "expanded broad play DESIGN/CALIB screen no longer passes")
    selection = _fresh_play_selection(
        capture_evidence_repo=capture_evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record)
    bury_claim = _bury_result_review(bury_result_review_record)
    value = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": {
            "git": expected_git,
            "tree_dirty": False,
            "sources": _source_sha256s(),
        },
        "parents": {
            "training_evidence": {
                "absolute_path": str(evidence_repo.resolve()),
                "git": BASE.TRAINING_GIT,
                "training_packet_sha256": BASE.TRAINING_PACKET_SHA256,
                "model_dataset_sha256": BASE.MODEL_DATASET_SHA256,
                "training_aggregate_sha256":
                    BASE.TRAINING_AGGREGATE_SHA256,
                "training_aggregate_internal_sha256":
                    aggregate["aggregate_sha256"],
                "training_result_review_record_sha256":
                    sha256_file(training_result_review_record),
            },
            "capture_evidence": {
                "absolute_path": str(capture_evidence_repo.resolve()),
                "git": EXPANSION.EVIDENCE_GIT,
                "state_set_review_record_sha256":
                    sha256_file(state_set_review_record),
                "fresh_report_review_record_sha256":
                    sha256_file(fresh_report_review_record),
            },
            "bury_terminal_result_review": {
                "absolute_path": str(bury_result_review_record.resolve()),
                "sha256": sha256_file(bury_result_review_record),
                "claim_sha256": _manifest_hash(bury_claim),
                "decision": "SELECT_NONE",
                "composition_authorized": False,
                "prior_population_fully_spent": True,
            },
        },
        "capability": capability,
        "checkpoint_manifest": manifest,
        "checkpoint_manifest_sha256": _manifest_hash(manifest),
        "diagnostics": {"DESIGN": design, "CALIB": calib},
        "fresh_play_selection": _selection_summary(selection),
        "authority": {
            "new_training_authorized": False,
            "training_retry_authorized": False,
            "report_rows_opened": 0,
            "report_open_authorized": False,
            "one_play_report_controller_freeze_authorized": False,
            "report_execution_authorized": False,
            "composition_authorized": False,
            "whole_game_screen_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    value["diagnostics_sha256"] = _manifest_hash(value["diagnostics"])
    value["packet_sha256"] = self_hash(value, "packet_sha256")
    return value


def expected_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
) -> dict:
    design = packet["diagnostics"]["DESIGN"]
    calib = packet["diagnostics"]["CALIB"]
    selection = packet["fresh_play_selection"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "training_aggregate_sha256": BASE.TRAINING_AGGREGATE_SHA256,
        "bury_terminal_result_review_claim_sha256": packet["parents"][
            "bury_terminal_result_review"]["claim_sha256"],
        "bury_terminal_decision": "SELECT_NONE",
        "capability": packet["capability"],
        "checkpoint_manifest_sha256":
            packet["checkpoint_manifest_sha256"],
        "ensemble_models": len(packet["checkpoint_manifest"]),
        "design_states": design["states"],
        "design_ensemble_improvement": design[
            "teacher_improvement_vs_candidate0"]["mean"],
        "design_ensemble_lcb": design[
            "teacher_improvement_vs_candidate0"]["one_sided_95_lcb"],
        "design_proposal_triggers": design["proposal_triggers"],
        "calib_states": calib["states"],
        "calib_ensemble_improvement": calib[
            "teacher_improvement_vs_candidate0"]["mean"],
        "calib_ensemble_lcb": calib[
            "teacher_improvement_vs_candidate0"]["one_sided_95_lcb"],
        "calib_proposal_triggers": calib["proposal_triggers"],
        "diagnostics_sha256": packet["diagnostics_sha256"],
        "fresh_play_selection_sha256": selection["selection_sha256"],
        "fresh_play_state_ids_sha256": selection["state_ids_sha256"],
        "fresh_play_states": selection["state_count"],
        "fresh_play_surface_counts": selection["surface_counts"],
        "prior_report_populations_spent":
            selection["spent_report_populations"],
        "prior_report_states_spent": selection["spent_report_states"],
        "prior_report_state_overlap": selection["spent_state_overlap"],
        "prior_report_deal_seed_overlap":
            selection["spent_deal_seed_overlap"],
        "remaining_report_supply_after_selection":
            selection["remaining_report_supply_after_selection"],
        "fresh_report_state_material_published": False,
        "report_rows_opened": 0,
        "independent_review": True,
        "one_play_report_controller_freeze_authorized": True,
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
        raise ExpandedPlayCapabilityRefused(
            f"refusing existing output: {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise ExpandedPlayCapabilityRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def freeze(*, out: Path, **kwargs) -> dict:
    if out.resolve() != (REPO / PACKET_PATH).resolve():
        raise ExpandedPlayCapabilityRefused(
            "expanded play capability output path drift")
    packet = build_packet(**kwargs)
    _publish_exclusive(out, packet)
    return packet


def verify(*, packet_path: Path, expected_packet_sha256: str,
           **kwargs) -> dict:
    if (packet_path.resolve() != (REPO / PACKET_PATH).resolve()
            or not is_regular_unlinked(packet_path)
            or sha256_file(packet_path) != expected_packet_sha256):
        raise ExpandedPlayCapabilityRefused(
            "expanded play capability packet path/SHA drift")
    actual = load_json(packet_path)
    expected = build_packet(**kwargs)
    if actual != expected or packet_path.read_bytes() != canonical_json(expected):
        raise ExpandedPlayCapabilityRefused(
            "expanded play capability packet recomputation drift")
    return actual


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--expected-git", required=True)
    root.add_argument("--evidence-repo", required=True)
    root.add_argument("--training-result-review-record", required=True)
    root.add_argument("--capture-evidence-repo", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--bury-result-review-record", required=True)
    root.add_argument("--out", default=PACKET_PATH)
    root.add_argument("--expected-packet-sha256")
    return root


def main() -> int:
    args = parser().parse_args()
    common = {
        "evidence_repo": Path(args.evidence_repo).resolve(),
        "training_result_review_record": Path(
            args.training_result_review_record).resolve(),
        "capture_evidence_repo": Path(args.capture_evidence_repo).resolve(),
        "state_set_review_record": Path(
            args.state_set_review_record).resolve(),
        "fresh_report_review_record": Path(
            args.fresh_report_review_record).resolve(),
        "bury_result_review_record": Path(
            args.bury_result_review_record).resolve(),
        "expected_git": args.expected_git,
    }
    out = Path(args.out).resolve()
    if args.command == "freeze":
        packet = freeze(out=out, **common)
        external = sha256_file(out)
    else:
        if not args.expected_packet_sha256:
            raise ExpandedPlayCapabilityRefused(
                "verify requires --expected-packet-sha256")
        packet = verify(
            packet_path=out,
            expected_packet_sha256=args.expected_packet_sha256, **common)
        external = args.expected_packet_sha256
    print(json.dumps({
        "status": "VERIFIED_NO_REPORT_OPEN" if args.command == "verify"
                  else "FROZEN_NO_REPORT_OPEN",
        "packet_sha256": external,
        "packet_internal_sha256": packet["packet_sha256"],
        "expected_review_claim": expected_review_claim(packet, external),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExpandedPlayCapabilityRefused,
            BASE.ReportControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
