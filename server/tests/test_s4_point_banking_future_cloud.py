"""Fail-closed tests for the automatic future S4 Cloud controller."""
from __future__ import annotations

import copy
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import s4_point_banking_future as CORE  # noqa: E402
import s4_point_banking_future_cloud as CTRL  # noqa: E402


DATA = Path(__file__).parent / "data"
CLOUD_PREFLIGHT = DATA / "s4_point_banking_future_cloud_preflight.v1.json"
CLOUD_PREFLIGHT_SHA256 = (
    "70a15405c7edb94ecfdd89fb8c86d158ba64d8161eeba82c57851b67d513413e"
)
CLOUD_PREFLIGHT_ADMISSION = (
    DATA / "s4_point_banking_future_cloud_preflight_admission.v1.json")
CLOUD_PREFLIGHT_ADMISSION_SHA256 = (
    "8332404e8ff4f97c4cdbaea232f9cdf695a83a2ceb121151923f2c99610fb9ca"
)


def _config() -> CTRL.Config:
    return CTRL.Config(
        expected_git="a" * 40,
        expected_runner_sha256="b" * 64,
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0)


def _design_review() -> dict:
    return {
        "path": "server/runs/logs/x/design-review-record.txt",
        "sha256": "4" * 64,
        "git": CTRL.DESIGN_REVIEW_GIT,
        "verdict": "PASS_TO_IMPLEMENT",
    }


def _review_claim(packet_sha256: str = "d" * 64,
                  preflight_sha256: str = "e" * 64,
                  design_review_sha256: str = "4" * 64) -> dict:
    return CTRL._expected_review_claim(
        packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256,
        design_review_sha256=design_review_sha256,
        config=_config())


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        payload, sort_keys=True, separators=(",", ":")) + "\n")
    return CORE.sha256(path)


def _install_receipt_chain(tmp_path: Path, monkeypatch, *,
                           packet_mutator=None,
                           duplicate_review_marker: bool = False):
    expected_git = "a" * 40
    parent = {"champion_policy": CORE.DUEL.CHAMPION}
    runtime = {"git": expected_git, "future": True}
    monkeypatch.setattr(CORE, "REPO", tmp_path)
    monkeypatch.setattr(
        CORE, "require_runtime", lambda git: (parent, runtime)
        if git == expected_git else (_ for _ in ()).throw(
            CORE.ProtocolRefused("git drift")))

    controller_path = tmp_path / "server/scripts/s4_point_banking_future_cloud.py"
    controller_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(CTRL.__file__), controller_path)
    config = CTRL.Config(
        expected_git=expected_git,
        expected_runner_sha256=CORE.sha256(CORE.SCRIPT),
        expected_controller_sha256=CORE.sha256(controller_path),
        heartbeat_seconds=30.0)
    namespace = tmp_path / CORE.NAMESPACE
    design_review_path = namespace / CTRL.DESIGN_REVIEW_NAME
    design_review_path.parent.mkdir(parents=True, exist_ok=True)
    design_review_path.write_text("reviewed design\n")
    design_review = {
        "path": str(CORE.NAMESPACE / CTRL.DESIGN_REVIEW_NAME),
        "sha256": CORE.sha256(design_review_path),
        "git": CORE.DESIGN_REVIEW_GIT,
        "verdict": "PASS_TO_IMPLEMENT",
    }
    preflight_path = tmp_path / CORE.PREFLIGHT_NAMESPACE / "preflight.json"
    preflight_sha = _write_json(preflight_path, {"score_free": True})
    preflight = {
        "path": str(CORE.PREFLIGHT_NAMESPACE / "preflight.json"),
        "sha256": preflight_sha,
        "score_free": True,
        "outcomes_published": False,
        "status": "AUTHORIZE_SEQUENTIAL_PACKET_REVIEW",
    }
    packet = CTRL.packet_contract(
        config, CTRL.paths_for(), parent=parent, runtime=runtime,
        preflight=preflight, design_review=design_review)
    if packet_mutator:
        packet_mutator(packet)
    packet_path = namespace / CTRL.PACKET_NAME
    packet_sha = _write_json(packet_path, packet)
    claim = CORE.expected_review_claim(
        expected_git=expected_git, packet_sha256=packet_sha,
        preflight_sha256=preflight_sha,
        design_review_sha256=design_review["sha256"])
    marker = CORE.PACKET_REVIEW_MARKER + json.dumps(claim, sort_keys=True)
    review_path = namespace / CTRL.REVIEW_NAME
    review_path.write_text(
        marker + "\n" + (marker + "\n" if duplicate_review_marker else ""))
    admission = {
        "schema": CORE.ADMISSION_SCHEMA,
        "run_id": CORE.RUN_ID,
        "packet": {"path": str(CORE.NAMESPACE / CTRL.PACKET_NAME),
                   "sha256": packet_sha},
        "review": {"path": str(CORE.NAMESPACE / CTRL.REVIEW_NAME),
                   "sha256": CORE.sha256(review_path)},
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    admission_path = namespace / CTRL.ADMISSION_NAME
    admission_sha = _write_json(admission_path, admission)
    receipt = {
        "schema": CORE.RECEIPT_SCHEMA,
        "run_id": CORE.RUN_ID,
        "complete": True,
        "git": expected_git,
        "runner_sha256": CORE.sha256(CORE.SCRIPT),
        "controller_sha256": CORE.sha256(controller_path),
        "design_sha256": CORE.sha256(Path(CORE.DESIGN.__file__)),
        "created_time_ns": 1,
        "nonce": "f" * 64,
        "packet_sha256": packet_sha,
        "admission_sha256": admission_sha,
        "preflight_sha256": preflight_sha,
        "design_review_sha256": design_review["sha256"],
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    receipt_path = namespace / CTRL.RECEIPT_NAME
    receipt_sha = _write_json(receipt_path, receipt)
    return receipt_path, receipt_sha, expected_git


def _small_aggregate(*, look: int, status: str) -> dict:
    integrity = {"fixed": True, "all": True}
    efficacy = status in ("STOP_PASS", "PASS")
    if status in ("STOP_HOLD", "HOLD"):
        integrity = {"fixed": False, "all": False}
        efficacy = True
    return {
        "schema": CORE.AGGREGATE_SCHEMA,
        "look": look,
        "clusters": CORE.LOOK_CLUSTERS[look - 1],
        "integrity": integrity,
        "efficacy_pass": efficacy,
        "stats": {"treatment_champion": {"lcb": 0.1 if efficacy else -0.1}},
        "status": status,
    }


def test_controller_is_cloud_only_and_uses_reviewed_two_look_contract():
    assert CTRL.EXPECTED_HOST == "ubuntu-32gb-hel1-1"
    assert CTRL.EXPECTED_PYTHON == "3.14.4"
    assert CORE.LOOK_CLUSTERS == (8_192, 16_384)
    assert CORE.NULL_SENTINEL_CLUSTERS == 2_048
    assert CORE.LOOK1_TRANSITION == {
        "efficacy_pass_and_integrity_pass": "STOP_PASS",
        "efficacy_nonpass_and_integrity_pass": "CONTINUE_AUTOMATICALLY",
        "any_integrity_nonpass": "STOP_HOLD",
    }


@pytest.mark.parametrize(("field", "value"), [
    ("host", "Jerrys-MacBook-Air.local"),
    ("host", "Jerrys-Mac-mini.local"),
    ("python", "3.14.6"),
    ("fast_binary_sha256", "0" * 64),
])
def test_identity_context_refuses_noncloud_runtime(
        monkeypatch, field, value):
    config = _config()
    paths = CTRL.paths_for()
    parent = {"champion_policy": CORE.DUEL.CHAMPION}
    runtime = {
        "host": CTRL.EXPECTED_HOST,
        "python": CTRL.EXPECTED_PYTHON,
        "fast_binary_sha256": CTRL.EXPECTED_FAST_SHA256,
        "future_runner_sha256": config.expected_runner_sha256,
    }
    runtime[field] = value

    def fake_git(*args):
        return config.expected_git if args == ("rev-parse", "HEAD") else ""

    def fake_sha(path):
        if path == paths.runner:
            return config.expected_runner_sha256
        if path == paths.controller:
            return config.expected_controller_sha256
        raise AssertionError(f"unexpected identity path: {path}")

    monkeypatch.setattr(CTRL, "_git", fake_git)
    monkeypatch.setattr(CTRL, "sha256_file", fake_sha)
    monkeypatch.setattr(
        CORE, "require_runtime", lambda _git: (parent, runtime))
    with pytest.raises(CTRL.SupervisorRefused, match="exact Cloud runtime"):
        CTRL._identity_context(config, paths)


def test_identity_context_accepts_exact_cloud_runtime(monkeypatch):
    config = _config()
    paths = CTRL.paths_for()
    parent = {"champion_policy": CORE.DUEL.CHAMPION}
    runtime = {
        "host": CTRL.EXPECTED_HOST,
        "python": CTRL.EXPECTED_PYTHON,
        "fast_binary_sha256": CTRL.EXPECTED_FAST_SHA256,
        "future_runner_sha256": config.expected_runner_sha256,
    }

    def fake_git(*args):
        return config.expected_git if args == ("rev-parse", "HEAD") else ""

    def fake_sha(path):
        return (config.expected_runner_sha256 if path == paths.runner
                else config.expected_controller_sha256)

    monkeypatch.setattr(CTRL, "_git", fake_git)
    monkeypatch.setattr(CTRL, "sha256_file", fake_sha)
    monkeypatch.setattr(
        CORE, "require_runtime", lambda _git: (parent, runtime))
    assert CTRL._identity_context(config, paths) == (parent, runtime)


def test_command_templates_are_path_neutral_complete_and_disjoint():
    commands = [CTRL.command_template(tranche, index)
                for tranche in (1, 2)
                for index in range(CTRL.SHARD_COUNT)]
    assert all(command[0] == "{python}" for command in commands)
    assert [command[command.index("--tranche") + 1]
            for command in commands[:8]] == ["1"] * 8
    assert [command[command.index("--tranche") + 1]
            for command in commands[8:]] == ["2"] * 8
    assert len({command[-1] for command in commands}) == 16
    assert all(not item.startswith("/Users/")
               for command in commands for item in command)
    first = CTRL.aggregate_template(1)
    final = CTRL.aggregate_template(2)
    assert first[first.index("--look") + 1] == "1"
    assert final[final.index("--look") + 1] == "2"
    assert len(first[first.index("--shards") + 1:
                     first.index("--execution-receipt")]) == 8
    assert len(final[final.index("--shards") + 1:
                     final.index("--execution-receipt")]) == 16


def test_packet_embeds_verbatim_transition_and_pre_authorizes_tranche_two():
    packet = CTRL.packet_contract(
        _config(), CTRL.paths_for(),
        parent={"champion_policy": CORE.DUEL.CHAMPION},
        runtime={"git": "a" * 40},
        preflight={"sha256": "e" * 64, "score_free": True,
                   "outcomes_published": False,
                   "status": "AUTHORIZE_SEQUENTIAL_PACKET_REVIEW"},
        design_review=_design_review())
    assert packet["design"] == CORE.DESIGN_RECORD
    assert packet["transition_table"] == {
        "look_1": CORE.LOOK1_TRANSITION,
        "final": CORE.FINAL_TRANSITION,
    }
    assert packet["sequential_launch_authorized"] is False
    assert packet["tranche_2_pre_authorized"] is True
    assert packet["tranches"][1]["execution_gate"] == \
        "look_1_status_exactly_CONTINUE_AUTOMATICALLY"
    assert len(packet["tranches"][0]["jobs"]) == 8
    assert len(packet["tranches"][1]["jobs"]) == 8


def _preflight_payload(*, parent: dict, runtime: dict,
                       status: str, within_caps: bool) -> dict:
    fleet_hours = (CORE.MAX_PROJECTED_FLEET_HOURS / 2 if within_caps
                   else CORE.MAX_PROJECTED_FLEET_HOURS + 1)
    shard_hours = (CORE.MAX_PROJECTED_SHARD_HOURS / 2 if within_caps
                   else CORE.MAX_PROJECTED_SHARD_HOURS + 1)
    criteria = {
        "records_valid": True,
        "stream_populations_disjoint": True,
        "treatment_triggered_both_roles": True,
        "matched_null_triggered_both_roles": True,
        "treatment_dose_exact": True,
        "matched_null_dose_exact": True,
        "champion_feature_off": True,
        "fleet_hours_le_cap": within_caps,
        "max_shard_hours_le_cap": within_caps,
        "all": within_caps,
    }
    return {
        "schema": CORE.PREFLIGHT_SCHEMA,
        "complete": True,
        "score_free": True,
        "outcomes_published": False,
        "outcomes_discarded": True,
        "run_id": CORE.PREFLIGHT_RUN_ID,
        "clusters": CORE.PREFLIGHT_CLUSTERS,
        "seed0": CORE.PREFLIGHT_SEED0,
        "stream_stride": CORE.DUEL.STREAM_STRIDE,
        "parent": parent,
        "runtime": runtime,
        "design": CORE.DESIGN_RECORD,
        "controller_review": {"path": "review", "sha256": "1" * 64},
        "preflight_admission": {"path": "admission", "sha256": "2" * 64},
        "elapsed_seconds": 1.0,
        "throughput_safety_factor": CORE.THROUGHPUT_SAFETY_FACTOR,
        "counter_totals": {},
        "point_banking_telemetry": {},
        "projection": {
            "fleet_hours": fleet_hours,
            "max_shard_hours": shard_hours,
            "target_arm_clusters": 1,
            "preflight_arm_clusters": 1,
            "look_1_fleet_hours": fleet_hours / 2,
            "look_1_max_shard_hours": shard_hours / 2,
        },
        "criteria": criteria,
        "status": status,
        "sequential_launch_authorized": False,
        "tranche_2_pre_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }


@pytest.mark.parametrize(("within_caps", "status"), [
    (True, "AUTHORIZE_SEQUENTIAL_PACKET_REVIEW"),
    (False, "HOLD"),
])
def test_preflight_evidence_accepts_coherent_pass_or_hold(
        tmp_path, monkeypatch, within_caps, status):
    parent = {"champion_policy": CORE.DUEL.CHAMPION}
    runtime = {"host": CTRL.EXPECTED_HOST}
    paths = replace(
        CTRL.paths_for(),
        preflight=tmp_path / "preflight.json",
        preflight_review_copy=tmp_path / "review.txt",
        preflight_admission=tmp_path / "admission.json")
    payload = _preflight_payload(
        parent=parent, runtime=runtime, status=status,
        within_caps=within_caps)
    _write_json(paths.preflight, payload)
    paths.preflight_review_copy.write_text("review\n")
    paths.preflight_admission.write_text("admission\n")
    refs = {
        paths.preflight: {"path": str(paths.preflight),
                          "sha256": CORE.sha256(paths.preflight)},
        paths.preflight_review_copy: {"path": "review", "sha256": "1" * 64},
        paths.preflight_admission: {"path": "admission", "sha256": "2" * 64},
    }
    monkeypatch.setattr(CTRL, "_require_preflight_chain",
                        lambda _config, _paths: ({}, {}))
    monkeypatch.setattr(
        CTRL, "_artifact_ref",
        lambda path, _expected, _label: refs[path])
    evidence = CTRL.preflight_evidence(
        _config(), paths, parent=parent, runtime=runtime)
    assert evidence["status"] == status


def test_preflight_hold_cannot_freeze_a_packet():
    with pytest.raises(CTRL.SupervisorRefused,
                       match="did not authorize packet review"):
        CTRL.packet_contract(
            _config(), CTRL.paths_for(),
            parent={"champion_policy": CORE.DUEL.CHAMPION},
            runtime={"git": "a" * 40},
            preflight={"status": "HOLD"},
            design_review=_design_review())


def test_preserved_cloud_capacity_hold_is_exact_and_reopens(
        tmp_path, monkeypatch):
    assert CORE.sha256(CLOUD_PREFLIGHT) == CLOUD_PREFLIGHT_SHA256
    assert CORE.sha256(CLOUD_PREFLIGHT_ADMISSION) == \
        CLOUD_PREFLIGHT_ADMISSION_SHA256
    payload = json.loads(CLOUD_PREFLIGHT.read_bytes())
    assert payload["status"] == "HOLD"
    assert payload["criteria"]["all"] is False
    assert payload["criteria"]["fleet_hours_le_cap"] is False
    assert payload["criteria"]["max_shard_hours_le_cap"] is False
    assert payload["preflight_admission"]["sha256"] == \
        CLOUD_PREFLIGHT_ADMISSION_SHA256

    review = tmp_path / "controller-review.txt"
    review.write_text("review bytes are authenticated by the artifact ref\n")
    paths = replace(
        CTRL.paths_for(), preflight=CLOUD_PREFLIGHT,
        preflight_review_copy=review,
        preflight_admission=CLOUD_PREFLIGHT_ADMISSION)
    refs = {
        CLOUD_PREFLIGHT: {
            "path": str(CORE.PREFLIGHT_NAMESPACE / "preflight.json"),
            "sha256": CLOUD_PREFLIGHT_SHA256,
        },
        review: payload["controller_review"],
        CLOUD_PREFLIGHT_ADMISSION: payload["preflight_admission"],
    }
    monkeypatch.setattr(CTRL, "_require_preflight_chain",
                        lambda _config, _paths: ({}, {}))
    monkeypatch.setattr(
        CTRL, "_artifact_ref",
        lambda path, _expected, _label: refs[path])
    evidence = CTRL.preflight_evidence(
        _config(), paths, parent=payload["parent"],
        runtime=payload["runtime"])
    assert evidence["status"] == "HOLD"
    assert evidence["projection"] == payload["projection"]


def test_design_equivalence_allows_only_derived_platform_roundoff():
    x86 = json.loads(CLOUD_PREFLIGHT.read_bytes())["design"]
    assert x86 != CORE.DESIGN_RECORD
    assert CTRL._equivalent_design_record(x86, CORE.DESIGN_RECORD)
    structural = copy.deepcopy(x86)
    structural["design"]["shard_count"] = 16
    assert not CTRL._equivalent_design_record(structural, CORE.DESIGN_RECORD)
    large_float_drift = copy.deepcopy(x86)
    large_float_drift["looks"][0]["critical"] += 1e-8
    assert not CTRL._equivalent_design_record(
        large_float_drift, CORE.DESIGN_RECORD)


def test_review_marker_is_one_exact_narrow_claim():
    claim = _review_claim()
    raw = ("review\n" + CORE.PACKET_REVIEW_MARKER
           + json.dumps(claim, sort_keys=True) + "\n").encode()
    assert CTRL._review_claim(
        raw, packet_sha256="d" * 64, preflight_sha256="e" * 64,
        design_review_sha256="4" * 64, config=_config()) == claim
    for key, value in (
            ("strength_claim", True),
            ("tranche_2_pre_authorized", False),
            ("look_clusters", [8_192]),
            ("production_deployment", True),
            ("verdict", "HOLD")):
        broken = dict(claim)
        broken[key] = value
        with pytest.raises(CTRL.SupervisorRefused, match="wrong authority"):
            CTRL._review_claim(
                (CORE.PACKET_REVIEW_MARKER
                 + json.dumps(broken, sort_keys=True)).encode(),
                packet_sha256="d" * 64, preflight_sha256="e" * 64,
                design_review_sha256="4" * 64, config=_config())
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one"):
        CTRL._review_claim(
            raw + raw, packet_sha256="d" * 64,
            preflight_sha256="e" * 64,
            design_review_sha256="4" * 64, config=_config())


def test_controller_review_authorizes_only_one_score_free_preflight(
        monkeypatch):
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "9" * 64)
    claim = CTRL.controller_review_claim(_config())
    assert claim["one_score_free_preflight_authorized"] is True
    assert claim["sequential_packet_design_authorized"] is True
    assert claim["sequential_execution_authorized"] is False
    assert claim["strength_claim"] is False
    raw = (CTRL.CONTROLLER_REVIEW_MARKER
           + json.dumps(claim, sort_keys=True)).encode()
    assert CTRL._controller_review_claim(raw, _config()) == claim
    broken = dict(claim)
    broken["sequential_execution_authorized"] = True
    with pytest.raises(CTRL.SupervisorRefused, match="wrong authority"):
        CTRL._controller_review_claim(
            (CTRL.CONTROLLER_REVIEW_MARKER
             + json.dumps(broken, sort_keys=True)).encode(), _config())


def test_preflight_admission_is_pinned_and_cannot_grant_screen_execution(
        monkeypatch):
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "9" * 64)
    claim = CTRL.controller_review_claim(_config())
    admission = CTRL.preflight_admission_payload(
        config=_config(), review_sha256="4" * 64,
        review_claim=claim, nonce="f" * 64, created_time_ns=1)
    assert admission["one_score_free_preflight_authorized"] is True
    assert admission["sequential_execution_authorized"] is False
    assert admission["production_deployment"] is False


def test_receipt_is_narrow_nonretryable_and_pre_authorizes_second_tranche(
        monkeypatch):
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "9" * 64)
    receipt = {
        "schema": CORE.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "complete": True,
        "git": "a" * 40,
        "runner_sha256": "b" * 64,
        "controller_sha256": "c" * 64,
        "design_sha256": "9" * 64,
        "created_time_ns": 1,
        "nonce": "f" * 64,
        "packet_sha256": "1" * 64,
        "admission_sha256": "2" * 64,
        "preflight_sha256": "3" * 64,
        "design_review_sha256": "4" * 64,
        "sequential_launch_authorized": True,
        "tranche_2_pre_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    assert CTRL.receipt_problems(
        receipt, config=_config(), packet_sha256="1" * 64,
        admission_sha256="2" * 64, preflight_sha256="3" * 64,
        design_review_sha256="4" * 64) == []
    receipt["retry_or_extension_authorized"] = True
    assert CTRL.receipt_problems(
        receipt, config=_config(), packet_sha256="1" * 64,
        admission_sha256="2" * 64, preflight_sha256="3" * 64,
        design_review_sha256="4" * 64)


def test_runner_reopens_the_complete_reviewed_receipt_chain(
        tmp_path, monkeypatch):
    path, digest, git = _install_receipt_chain(tmp_path, monkeypatch)
    assert CORE.require_receipt(path, digest, expected_git=git) == {
        "path": str(CORE.NAMESPACE / CTRL.RECEIPT_NAME),
        "sha256": digest,
    }


@pytest.mark.parametrize("mutator", [
    lambda packet: packet.__setitem__("tranches", []),
    lambda packet: packet["transition_table"]["look_1"].update(
        {"efficacy_nonpass_and_integrity_pass": "STOP"}),
    lambda packet: packet["design_review"].update(
        {"git": "0" * 40}),
])
def test_runner_rejects_fully_rehashed_packet_contract_forgery(
        tmp_path, monkeypatch, mutator):
    path, digest, git = _install_receipt_chain(
        tmp_path, monkeypatch, packet_mutator=mutator)
    with pytest.raises(CORE.ProtocolRefused,
                       match="packet identity|authority drift"):
        CORE.require_receipt(path, digest, expected_git=git)


def test_runner_rejects_duplicate_packet_review_marker(tmp_path, monkeypatch):
    path, digest, git = _install_receipt_chain(
        tmp_path, monkeypatch, duplicate_review_marker=True)
    with pytest.raises(CORE.ProtocolRefused, match="one marker"):
        CORE.require_receipt(path, digest, expected_git=git)


@pytest.mark.parametrize("status", [
    "STOP_PASS", "CONTINUE_AUTOMATICALLY", "STOP_HOLD", "PASS",
    "SELECT_NONE", "HOLD"])
def test_transition_is_pure_and_rejects_status_forgery(status):
    look = 1 if status.startswith("STOP") or status == \
        "CONTINUE_AUTOMATICALLY" else 2
    aggregate = _small_aggregate(look=look, status=status)
    assert CTRL.mechanical_transition(aggregate, look=look) == status
    forged = copy.deepcopy(aggregate)
    forged["status"] = "PASS"
    if status != "PASS":
        with pytest.raises(CTRL.SupervisorRefused,
                           match="not mechanical"):
            CTRL.mechanical_transition(forged, look=look)


def test_tranche_two_release_requires_exact_continue(tmp_path):
    base = CTRL.paths_for()
    paths = replace(
        base,
        packet=tmp_path / "launch_packet.json",
        receipt=tmp_path / "receipt.json",
        tranche2_preauthorization=tmp_path / "preauth.json",
        tranche2_release=tmp_path / "release.json",
        aggregates=(tmp_path / "look1.json", tmp_path / "look2.json"))
    paths.packet.write_text("packet\n")
    paths.receipt.write_text("receipt\n")
    preauth = CTRL.tranche2_preauthorization_payload(
        packet_sha256=CTRL.sha256_file(paths.packet),
        receipt_sha256=CTRL.sha256_file(paths.receipt))
    _write_json(paths.tranche2_preauthorization, preauth)
    look1 = _small_aggregate(look=1, status="CONTINUE_AUTOMATICALLY")
    _write_json(paths.aggregates[0], look1)
    release = CTRL.tranche2_release_payload(paths=paths, look1=look1)
    assert release["tranche_2_execution_authorized"] is True
    assert release["mechanical_transition_only"] is True
    with pytest.raises(CTRL.SupervisorRefused, match="does not mechanically"):
        CTRL.tranche2_release_payload(
            paths=paths, look1=_small_aggregate(
                look=1, status="STOP_PASS"))


def test_execution_collision_set_covers_preauthorization_and_partials():
    paths = CTRL.paths_for()
    targets = set(CTRL._execution_targets(paths))
    for path in (
            paths.receipt, paths.tranche2_preauthorization,
            paths.tranche2_release, paths.final, *paths.aggregates,
            *paths.shards):
        assert path in targets
        assert CTRL.partial(path) in targets


def test_status_heartbeat_reads_completed_final_log(tmp_path):
    log_final = tmp_path / "shard.log"
    log_final.write_text(json.dumps({
        "event": "s4-point-banking-future-progress-v1",
        "tranche": 1,
        "shard_index": 3,
        "clusters_complete": 1_024,
        "clusters_total": 1_024,
    }, sort_keys=True) + "\n")
    job = SimpleNamespace(
        name="tranche-1-shard-03",
        log_partial=Path(str(log_final) + ".partial"),
        log_final=log_final,
        process=SimpleNamespace(poll=lambda: 0))
    assert CTRL._job_progress(job) == {
        "job": "tranche-1-shard-03",
        "clusters_complete": 1_024,
        "clusters_total": 1_024,
        "finished": True,
    }


def test_final_never_promotes_or_retries(monkeypatch):
    paths = CTRL.paths_for()
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr(CTRL, "rel", lambda path: path.name)
    final = CTRL.final_payload(
        paths=paths, packet_sha256="b" * 64,
        admission_sha256="c" * 64,
        aggregate={"status": "STOP_PASS"},
        job_evidence=[], terminal_look=1)
    assert final["strength_claim"] is True
    assert final["production_promotion"] is False
    assert final["explicit_deployment_review_required"] is True
    assert final["retry_or_extension_authorized"] is False
    assert final["tranche_2_release"] is None


def test_exclusive_review_copy_never_overwrites(tmp_path):
    path = tmp_path / "review.txt"
    CTRL._write_bytes_exclusive(path, b"first\n")
    with pytest.raises(CTRL.SupervisorRefused, match="refusing to overwrite"):
        CTRL._write_bytes_exclusive(path, b"second\n")
