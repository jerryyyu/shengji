from __future__ import annotations

import copy
import hashlib
import json

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_pipeline import (
    WorldAfterstateV1PipelineError, publish_pipeline_build,
    reopen_pipeline_build, reopen_pipeline_directory)
from shengji.rl.world_afterstate_v1_rehearsal import (
    build_non_scientific_rehearsal)


def test_full_path_rehearsal_reopens_every_file_and_terminal(tmp_path):
    build = build_non_scientific_rehearsal()
    reopened = reopen_pipeline_build(build)
    assert reopened == build
    assert build.manifest["non_scientific_rehearsal"] is True
    assert build.manifest["report_rows_opened"] is False
    assert set(build.manifest["authority"].values()) == {False}
    assert build.manifest["file_count"] == 50

    root = tmp_path / "pipeline"
    publish_pipeline_build(root, build)
    assert reopen_pipeline_directory(root) == build


def test_pipeline_wiring_refuses_coordinated_terminal_rewrite():
    build = build_non_scientific_rehearsal()
    files = dict(build.files)
    terminal = json.loads(files["p1/terminal.json"])
    terminal["control_action_gates_passed"] = {
        name: False for name in terminal["control_action_gates_passed"]}
    terminal["identical_predictions_exact_zero"] = True
    terminal["negative_controls_failed_on_demand"] = True
    terminal["world_signal_passed"] = False
    terminal["world_twin_packet_review_proposal_authorized"] = False
    if terminal["decision"] != "PASS_ACTION_ONLY_NO_WORLD_SIGNAL":
        terminal["natural_action_gates_passed"] = True
        terminal["decision"] = "PASS_ACTION_ONLY_NO_WORLD_SIGNAL"
        terminal["public_action_value_packet_review_proposal_authorized"] = True
    else:
        terminal["natural_action_gates_passed"] = False
        terminal["decision"] = "SELECT_NONE_NO_ACTION_ADVANTAGE"
        terminal["public_action_value_packet_review_proposal_authorized"] = False
    terminal_body = {
        key: value for key, value in terminal.items()
        if key != "result_sha256"}
    terminal["result_sha256"] = hashlib.sha256(
        canonical_json_bytes(terminal_body)).hexdigest()
    files["p1/terminal.json"] = canonical_json_bytes(terminal)

    manifest = copy.deepcopy(build.manifest)
    terminal_row = next(
        row for row in manifest["files"]
        if row["relative_path"] == "p1/terminal.json")
    terminal_row["byte_count"] = len(files["p1/terminal.json"])
    terminal_row["sha256"] = hashlib.sha256(
        files["p1/terminal.json"]).hexdigest()
    manifest["terminal_result_sha256"] = terminal["result_sha256"]
    manifest["terminal_decision"] = terminal["decision"]
    manifest_body = {
        key: value for key, value in manifest.items()
        if key != "manifest_sha256"}
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest_body)).hexdigest()
    forged = copy.copy(build)
    object.__setattr__(forged, "manifest", manifest)
    object.__setattr__(forged, "files", tuple(sorted(files.items())))
    with pytest.raises(
            WorldAfterstateV1PipelineError,
            match="terminal reconstruction drift"):
        reopen_pipeline_build(forged)
