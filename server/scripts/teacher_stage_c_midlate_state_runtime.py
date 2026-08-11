#!/usr/bin/env python3
"""Run the two one-shot phases of the fresh mid/late state screen.

``select`` consumes its admission before scanning natural games and publishes
only replay states plus protected policy decisions.  ``evaluate`` requires an
independent review of that immutable population, consumes a distinct admission
before sampling, and then opens exactly 300 common worlds for each of the
treatment, matched-null and literal-live logical actions.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_midlate_state_capture_runtime as CAPTURE_ADAPTER  # noqa: E402
import teacher_stage_c_midlate_state_controller as CTRL  # noqa: E402
import teacher_stage_c_midlate_state_screen_runtime as FOLD_ADAPTER  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.rl import stage_c_candidates as CANDIDATES  # noqa: E402
from shengji.rl import stage_c_composition as COMPOSITION  # noqa: E402
from shengji.rl import stage_c_npnet as NPNET  # noqa: E402
from shengji.rl import stage_c_state_capture as CAPTURE  # noqa: E402
from shengji.rl import stage_c_state_screen as SCREEN  # noqa: E402
from shengji.rl.npnet import NpNet as V11NpNet  # noqa: E402


SELECTION_SCHEMA = "teacher-stage-c-midlate-state-selection-result-v1"
RESULT_SCHEMA = "teacher-stage-c-midlate-state-screen-result-v1"
SELECTION_ADMISSION_SCHEMA = \
    "teacher-stage-c-midlate-state-selection-admission-v1"
EVALUATION_ADMISSION_SCHEMA = \
    "teacher-stage-c-midlate-state-evaluation-admission-v1"


class MidlateStateRuntimeRefused(RuntimeError):
    """A packet, review, admission, selection, or evaluation drifted."""


canonical_json = CTRL.canonical_json
sha256_file = CTRL.sha256_file
self_hash = CTRL.self_hash


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise MidlateStateRuntimeRefused(
            f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise MidlateStateRuntimeRefused(
            f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MidlateStateRuntimeRefused(
            f"JSON root is not an object: {path}")
    return value


def require_publishable(path: Path, label: str) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise MidlateStateRuntimeRefused(
            f"refusing existing {label}: {path}")


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
        raise MidlateStateRuntimeRefused(
            f"refusing raced output: {path}") from exc
    partial.unlink()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _external_path(ref: Mapping[str, object], label: str) -> Path:
    path = Path(str(ref.get("absolute_path", ""))).resolve()
    expected = ref.get("external_sha256")
    if (not CTRL.is_sha256(expected) or not is_regular_unlinked(path)
            or sha256_file(path) != expected):
        raise MidlateStateRuntimeRefused(f"{label} path/SHA drift")
    return path


def _load_ensemble(packet: Mapping[str, object]):
    exports = packet.get("model_exports")
    if (not isinstance(exports, list)
            or len(exports) != len(CTRL.MODEL_PATHS)
            or [item.get("logical_path") for item in exports]
            != list(CTRL.MODEL_PATHS)
            or packet.get("model_exports_sha256")
            != CTRL.manifest_hash(exports)):
        raise MidlateStateRuntimeRefused(
            "mid/late model-export manifest drift")
    members = []
    for item in exports:
        path = (REPO / str(item["logical_path"])).resolve()
        try:
            member = NPNET.StageCNpNet(
                path, expected_sha256=str(item["sha256"]),
                expected_metadata=item["metadata"])
        except NPNET.StageCNumpyError as exc:
            raise MidlateStateRuntimeRefused(str(exc)) from exc
        members.append(member)
    selected = packet["selected_capability"]
    try:
        return NPNET.StageCEnsemble(
            members, surface=str(selected["surface"]),
            head=str(selected["head"]), epoch=int(selected["epoch"]))
    except NPNET.StageCNumpyError as exc:
        raise MidlateStateRuntimeRefused(str(exc)) from exc


def _rebuild_packet(packet: Mapping[str, object]) -> tuple[dict, list[int]]:
    parents = packet.get("parents")
    if not isinstance(parents, Mapping):
        raise MidlateStateRuntimeRefused("mid/late packet parents drift")
    source_ref = parents.get("source_review")
    capability_ref = parents.get("capability_packet")
    training_ref = parents.get("training_evidence")
    capture_ref = parents.get("capture_evidence")
    if any(not isinstance(value, Mapping) for value in (
            source_ref, capability_ref, training_ref, capture_ref)):
        raise MidlateStateRuntimeRefused("mid/late packet parent population drift")
    source_review = _external_path(source_ref, "source review")
    capability_path = _external_path(capability_ref, "capability packet")
    capability_review = _external_path(
        capability_ref.get("review_record", {}), "capability review")
    training_review = _external_path(
        training_ref.get("training_result_review", {}), "training review")
    state_review = _external_path(
        capture_ref.get("state_set_review", {}), "state-set review")
    fresh_review = _external_path(
        capture_ref.get("fresh_report_review", {}), "fresh REPORT review")
    bury_review = _external_path(
        capture_ref.get("bury_result_review", {}), "bury result review")
    training_repo = Path(str(training_ref.get("absolute_path", ""))).resolve()
    capture_repo = Path(str(capture_ref.get("absolute_path", ""))).resolve()
    capability = CTRL._rebuild_capability(
        capability_packet_path=capability_path,
        capability_review_record=capability_review,
        training_evidence_repo=training_repo,
        training_result_review_record=training_review,
        capture_evidence_repo=capture_repo,
        state_set_review_record=state_review,
        fresh_report_review_record=fresh_review,
        bury_result_review_record=bury_review)
    forbidden = CTRL.forbidden_deal_seeds(
        capture_evidence_repo=capture_repo,
        state_set_review_record=state_review,
        fresh_report_review_record=fresh_review)
    rebuilt = CTRL.build_packet(
        git=str(packet.get("producer", {}).get("git", "")),
        source_review_record=source_review,
        capability_packet_path=capability_path,
        capability_review_record=capability_review,
        training_result_review_record=training_review,
        capture_evidence_repo=capture_repo,
        state_set_review_record=state_review,
        fresh_report_review_record=fresh_review,
        bury_result_review_record=bury_review,
        capability=capability, forbidden=forbidden,
        exports=packet.get("model_exports", []))
    return rebuilt, forbidden


def _packet(path: Path, expected_sha256: str, expected_git: str):
    if (_git("rev-parse", "HEAD") != expected_git
            or _git("status", "--porcelain", "--untracked-files=all")):
        raise MidlateStateRuntimeRefused(
            "mid/late runtime requires exact clean Git head")
    expected_path = (REPO / CTRL.PACKET_PATH).resolve()
    if (path.resolve() != expected_path or not CTRL.is_sha256(expected_sha256)
            or not is_regular_unlinked(path.resolve())
            or sha256_file(path.resolve()) != expected_sha256):
        raise MidlateStateRuntimeRefused(
            "mid/late controller packet path/SHA drift")
    packet = load_json(path.resolve())
    expected_authority = {
        "controller_review_authorized": True,
        "selection_execution_authorized": False,
        "evaluation_open_authorized": False,
        "whole_game_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    if (packet.get("schema") != CTRL.SCHEMA
            or packet.get("packet_id") != CTRL.PACKET_ID
            or packet.get("run_id") != CTRL.RUN_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("producer", {}).get("git") != expected_git
            or packet.get("producer", {}).get("tree_dirty") is not False
            or packet.get("producer", {}).get("sources")
            != CTRL._source_sha256s()
            or packet.get("runtime_contract") != CTRL.runtime_contract()
            or packet.get("candidate_contract") != CTRL.candidate_contract()
            or packet.get("commands") != CTRL.commands()
            or packet.get("result_contract") != CTRL.result_contract()
            or packet.get("authority") != expected_authority):
        raise MidlateStateRuntimeRefused(
            "mid/late controller packet identity/authority drift")
    rebuilt, forbidden = _rebuild_packet(packet)
    if rebuilt != packet:
        raise MidlateStateRuntimeRefused(
            "mid/late controller packet full recomputation drift")
    ensemble = _load_ensemble(packet)
    try:
        live = make_bot("mc-s0-report-lcb", seed=0)
        COMPOSITION._require_live_report_lcb(live)
    except Exception as exc:
        raise MidlateStateRuntimeRefused(
            f"literal live champion cannot reopen: {exc}") from exc
    return packet, forbidden, ensemble


def _controller_review(
    path: Path, packet: Mapping[str, object], packet_sha256: str,
) -> dict:
    claim = CTRL.marker_claim(
        path.resolve(), CTRL.REVIEW_MARKER, "mid/late controller review")
    if claim != CTRL.expected_review_claim(packet, packet_sha256):
        raise MidlateStateRuntimeRefused(
            "mid/late controller-review authority drift")
    return claim


def _factories(packet: Mapping[str, object], ensemble):
    v11_path = (REPO / CTRL.V11_PATH).resolve()
    if (not is_regular_unlinked(v11_path)
            or sha256_file(v11_path) != CTRL.V11_SHA256):
        raise MidlateStateRuntimeRefused("V11 proposer artifact drift")
    v11 = V11NpNet(str(v11_path))
    for value in v11.w.values():
        value.flags.writeable = False
    source = CANDIDATES.make_play_candidate_source(
        v11, novel_model_source="v11pair")

    def treatment(seed: int):
        return COMPOSITION.make_play_report_lcb_bot(
            ensemble, source, arm="treatment", seed=seed,
            min_completed_tricks=SCREEN.MIN_COMPLETED_TRICKS)

    def matched_null(seed: int):
        return COMPOSITION.make_play_report_lcb_bot(
            ensemble, source, arm="matched-null", seed=seed,
            min_completed_tricks=SCREEN.MIN_COMPLETED_TRICKS)

    def champion(seed: int):
        return make_bot("mc-s0-report-lcb", seed=seed)

    return treatment, matched_null, champion


def _admission_payload(
    *, schema: str, kind: str, packet: Mapping[str, object],
    packet_sha256: str, controller_review: Path,
    selection_population_sha256: str | None = None,
    selection_review: Path | None = None,
) -> dict:
    value = {
        "schema": schema,
        "kind": kind,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_record_sha256": sha256_file(controller_review),
        "selection_population_sha256": selection_population_sha256,
        "selection_review_record_sha256": (
            None if selection_review is None else sha256_file(selection_review)),
        "consumed_before_fresh_evidence": True,
        "retry_or_extension_authorized": False,
    }
    value["admission_sha256"] = self_hash(value, "admission_sha256")
    return value


def _consume_admission(path: Path, payload: Mapping[str, object]) -> str:
    require_publishable(path, "one-shot admission")
    publish_exclusive(path, payload)
    return sha256_file(path)


def _validate_admission(
    path: Path, payload: Mapping[str, object], expected_sha256: str,
) -> None:
    if (not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256
            or load_json(path) != dict(payload)):
        raise MidlateStateRuntimeRefused("one-shot admission drift")


def _progress(kind: str, **values: object) -> None:
    print(json.dumps({
        "event": "progress", "kind": kind,
        "time_unix": round(time.time(), 3), **values,
    }, sort_keys=True), flush=True)


def select_population(
    *, packet_path: Path, expected_packet_sha256: str,
    expected_git: str, controller_review_record: Path, out: Path,
) -> dict:
    expected_out = (REPO / CTRL.POPULATION_PATH).resolve()
    slot_path = (REPO / CTRL.SELECTION_ADMISSION_PATH).resolve()
    if out.resolve() != expected_out:
        raise MidlateStateRuntimeRefused("selection output path drift")
    require_publishable(out.resolve(), "selection population")
    require_publishable(slot_path, "selection admission")
    packet, forbidden, ensemble = _packet(
        packet_path, expected_packet_sha256, expected_git)
    review = _controller_review(
        controller_review_record, packet, expected_packet_sha256)
    if review.get("one_selection_execution_authorized") is not True:
        raise MidlateStateRuntimeRefused(
            "controller review did not authorize selection")
    admission = _admission_payload(
        schema=SELECTION_ADMISSION_SCHEMA, kind="selection",
        packet=packet, packet_sha256=expected_packet_sha256,
        controller_review=controller_review_record)
    admission_sha256 = _consume_admission(slot_path, admission)
    treatment, matched_null, champion = _factories(packet, ensemble)
    attempts = {"candidate": 0, "selector": 0}

    def candidate(seed: int, phase: str, role: str):
        attempts["candidate"] += 1
        if attempts["candidate"] % CTRL.PROGRESS_EVERY_SCANNED == 0:
            _progress("selection-scan", seed=seed,
                      candidate_calls=attempts["candidate"],
                      selector_calls=attempts["selector"])
        return CAPTURE_ADAPTER.candidate_state(
            seed, phase, role, experiment_id=CTRL.RUN_ID,
            capture_packet_id=CTRL.PACKET_ID)

    def selector(state: Mapping[str, object]):
        attempts["selector"] += 1
        return SCREEN.select_state(
            state, replay=CAPTURE_ADAPTER.CAPTURE.replay_state,
            treatment_factory=treatment,
            matched_null_factory=matched_null,
            champion_factory=champion)

    def selected_progress(scanned: int, counts: Mapping[str, int]) -> None:
        _progress("selection-accepted", scanned=scanned,
                  selected=sum(counts.values()), cell_counts=dict(counts),
                  selector_calls=attempts["selector"])

    population = CAPTURE.scan_population(
        seed0=CTRL.SEED0, scan_deals=CTRL.SCAN_DEALS,
        forbidden_deal_seeds=forbidden, candidate=candidate,
        selector=selector, progress=selected_progress)
    CAPTURE.validate_population(
        population, forbidden_deal_seeds=forbidden)
    result = {
        "schema": SELECTION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "controller_review_record_sha256": sha256_file(
            controller_review_record),
        "selection_admission_slot": CTRL.SELECTION_ADMISSION_PATH,
        "selection_admission_sha256": admission_sha256,
        "population": population,
        "evaluation_opened": False,
        "evaluation_execution_authorized": False,
        "retry_or_extension_authorized": False,
        "whole_game_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["selection_result_sha256"] = self_hash(
        result, "selection_result_sha256")
    _validate_admission(slot_path, admission, admission_sha256)
    if (sha256_file(packet_path) != expected_packet_sha256
            or packet["producer"]["sources"] != CTRL._source_sha256s()):
        raise MidlateStateRuntimeRefused(
            "controller changed during selection")
    publish_exclusive(out.resolve(), result)
    _progress("selection-complete", selected=population["selected_states"],
              deals_scanned=population["deals_scanned"],
              complete=population["complete"])
    return result


def _selection_population(
    *, path: Path, expected_sha256: str, packet: Mapping[str, object],
    packet_sha256: str, forbidden: list[int],
) -> dict:
    if (path.resolve() != (REPO / CTRL.POPULATION_PATH).resolve()
            or not CTRL.is_sha256(expected_sha256)
            or not is_regular_unlinked(path.resolve())
            or sha256_file(path.resolve()) != expected_sha256):
        raise MidlateStateRuntimeRefused(
            "selection population path/SHA drift")
    result = load_json(path.resolve())
    population = result.get("population")
    if (result.get("schema") != SELECTION_SCHEMA
            or result.get("run_id") != CTRL.RUN_ID
            or result.get("git") != packet["producer"]["git"]
            or result.get("controller_packet_sha256") != packet_sha256
            or result.get("controller_packet_internal_sha256")
            != packet["packet_sha256"]
            or result.get("selection_result_sha256")
            != self_hash(result, "selection_result_sha256")
            or not isinstance(population, Mapping)
            or result.get("evaluation_opened") is not False
            or result.get("evaluation_execution_authorized") is not False
            or result.get("retry_or_extension_authorized") is not False
            or result.get("whole_game_launch_authorized") is not False
            or result.get("strength_claim") is not False
            or result.get("production_promotion") is not False
            or result.get("production_deployment") is not False):
        raise MidlateStateRuntimeRefused(
            "selection population identity/authority drift")
    try:
        CAPTURE.validate_population(population,
                                    forbidden_deal_seeds=forbidden)
    except CAPTURE.StageCStateCaptureError as exc:
        raise MidlateStateRuntimeRefused(str(exc)) from exc
    if population.get("complete") is not True:
        raise MidlateStateRuntimeRefused(
            "incomplete selection cannot open evaluation")
    slot = (REPO / CTRL.SELECTION_ADMISSION_PATH).resolve()
    if (not is_regular_unlinked(slot)
            or sha256_file(slot) != result.get("selection_admission_sha256")):
        raise MidlateStateRuntimeRefused(
            "selection admission unavailable")
    return result


def _selection_review(
    path: Path, *, packet: Mapping[str, object], packet_sha256: str,
    population: Mapping[str, object], population_sha256: str,
) -> dict:
    claim = CTRL.marker_claim(
        path.resolve(), CTRL.SELECTION_REVIEW_MARKER,
        "mid/late selection review")
    expected = CTRL.expected_selection_review_claim(
        packet, packet_sha256, population, population_sha256)
    if claim != expected or claim.get(
            "one_evaluation_execution_authorized") is not True:
        raise MidlateStateRuntimeRefused(
            "selection-review evaluation authority drift")
    return claim


def evaluate_population(
    *, packet_path: Path, expected_packet_sha256: str,
    expected_git: str, controller_review_record: Path,
    selection_population_path: Path,
    expected_selection_population_sha256: str,
    selection_review_record: Path, out: Path,
) -> dict:
    expected_out = (REPO / CTRL.RESULT_PATH).resolve()
    slot_path = (REPO / CTRL.EVALUATION_ADMISSION_PATH).resolve()
    if out.resolve() != expected_out:
        raise MidlateStateRuntimeRefused("evaluation output path drift")
    require_publishable(out.resolve(), "state-screen result")
    require_publishable(slot_path, "evaluation admission")
    packet, forbidden, _ensemble = _packet(
        packet_path, expected_packet_sha256, expected_git)
    _controller_review(
        controller_review_record, packet, expected_packet_sha256)
    selection = _selection_population(
        path=selection_population_path,
        expected_sha256=expected_selection_population_sha256,
        packet=packet, packet_sha256=expected_packet_sha256,
        forbidden=forbidden)
    review = _selection_review(
        selection_review_record, packet=packet,
        packet_sha256=expected_packet_sha256, population=selection,
        population_sha256=expected_selection_population_sha256)
    admission = _admission_payload(
        schema=EVALUATION_ADMISSION_SCHEMA, kind="evaluation",
        packet=packet, packet_sha256=expected_packet_sha256,
        controller_review=controller_review_record,
        selection_population_sha256=
            expected_selection_population_sha256,
        selection_review=selection_review_record)
    admission_sha256 = _consume_admission(slot_path, admission)
    records = []
    entries = selection["population"]["entries"]
    for index, entry in enumerate(entries, start=1):
        record = SCREEN.evaluate_selected(
            entry["state"], entry["selection"],
            replay=CAPTURE_ADAPTER.CAPTURE.replay_state,
            evaluation_fold=FOLD_ADAPTER.evaluation_fold)
        records.append(record)
        if index % CTRL.PROGRESS_EVERY_EVALUATED == 0 or index == len(entries):
            _progress("evaluation", completed=index, total=len(entries),
                      candidate_worlds=index * 3 * SCREEN.EVALUATION_WORLDS)
    aggregate = SCREEN.aggregate(
        records, forbidden_deal_seeds=forbidden)
    result = {
        "schema": RESULT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "controller_review_record_sha256": sha256_file(
            controller_review_record),
        "selection_population_sha256":
            expected_selection_population_sha256,
        "selection_population_internal_sha256": selection[
            "selection_result_sha256"],
        "selection_review_record_sha256": sha256_file(
            selection_review_record),
        "selection_review_claim": review,
        "evaluation_admission_slot": CTRL.EVALUATION_ADMISSION_PATH,
        "evaluation_admission_sha256": admission_sha256,
        "records": records,
        "aggregate": aggregate,
        "complete": True,
        "retry_or_extension_authorized": False,
        "whole_game_screen_design_authorized": aggregate[
            "whole_game_screen_design_authorized"],
        "whole_game_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["result_sha256"] = self_hash(result, "result_sha256")
    _validate_admission(slot_path, admission, admission_sha256)
    if (sha256_file(packet_path) != expected_packet_sha256
            or sha256_file(selection_population_path)
            != expected_selection_population_sha256):
        raise MidlateStateRuntimeRefused(
            "screen parent changed during evaluation")
    publish_exclusive(out.resolve(), result)
    _progress("evaluation-complete", decision=aggregate["decision"],
              result_sha256=result["result_sha256"])
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("select", "evaluate"):
        command = sub.add_parser(name)
        command.add_argument("--expected-git", required=True)
        command.add_argument("--controller-packet", type=Path, required=True)
        command.add_argument("--expected-controller-packet-sha256",
                             required=True)
        command.add_argument("--controller-review-record", type=Path,
                             required=True)
        command.add_argument("--out", type=Path, required=True)
        if name == "evaluate":
            command.add_argument("--selection-population", type=Path,
                                 required=True)
            command.add_argument(
                "--expected-selection-population-sha256", required=True)
            command.add_argument("--selection-review-record", type=Path,
                                 required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "select":
        result = select_population(
            packet_path=args.controller_packet,
            expected_packet_sha256=
                args.expected_controller_packet_sha256,
            expected_git=args.expected_git,
            controller_review_record=args.controller_review_record,
            out=args.out)
    else:
        result = evaluate_population(
            packet_path=args.controller_packet,
            expected_packet_sha256=
                args.expected_controller_packet_sha256,
            expected_git=args.expected_git,
            controller_review_record=args.controller_review_record,
            selection_population_path=args.selection_population,
            expected_selection_population_sha256=
                args.expected_selection_population_sha256,
            selection_review_record=args.selection_review_record,
            out=args.out)
    print(json.dumps({
        "status": "COMPLETE",
        "schema": result["schema"],
        "output_sha256": sha256_file(args.out.resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
