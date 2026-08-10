"""Fail-closed controller tests for the fixed-size S4 Air replication."""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import s4_point_banking_replication as CORE  # noqa: E402
import s4_point_banking_replication_air as CTRL  # noqa: E402


def _config() -> CTRL.Config:
    return CTRL.Config(
        expected_git="a" * 40,
        expected_runner_sha256="b" * 64,
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0,
    )


def _review_claim(packet_sha256: str = "d" * 64,
                  preflight_sha256: str = "e" * 64) -> dict:
    return CTRL._expected_review_claim(
        packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256,
        config=_config())


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        payload, sort_keys=True, separators=(",", ":")) + "\n")
    return CORE.sha256(path)


def _install_receipt_chain(tmp_path: Path, monkeypatch, *,
                           packet_mutator=None, receipt_mutator=None,
                           duplicate_review_marker: bool = False):
    """Build a self-consistent launch chain inside a fake repository.

    Mutators run before downstream digests are frozen.  The rejection tests
    therefore exercise semantic reopening, not merely stale-hash detection.
    """
    expected_git = "a" * 40
    parent = {"champion_policy": CORE.DUEL.CHAMPION}
    runtime = {"git": expected_git, "source_sha256s": {"runner": "1" * 64}}
    screen_parent = {
        "aggregate": {
            "path": str(CORE.SCREEN_NAMESPACE / "aggregate.json"),
            "sha256": CORE.SCREEN_AGGREGATE_SHA256,
        },
        "final": {
            "path": str(CORE.SCREEN_NAMESPACE / "supervisor-final.json"),
            "sha256": CORE.SCREEN_FINAL_SHA256,
        },
        "status": "AUTHORIZE_CONFIRM_PACKET_REVIEW",
        "clusters": 2_048,
    }
    monkeypatch.setattr(CORE, "REPO", tmp_path)

    def reopen_runtime(git: str):
        if git != expected_git:
            raise CORE.ProtocolRefused("git drift")
        return parent, runtime

    monkeypatch.setattr(CORE, "require_runtime", reopen_runtime)

    def reopen_screen(*, aggregate_path, final_path, parent: dict,
                      runtime: dict):
        assert aggregate_path == tmp_path / CORE.SCREEN_NAMESPACE / \
            "aggregate.json"
        assert final_path == tmp_path / CORE.SCREEN_NAMESPACE / \
            "supervisor-final.json"
        assert parent == {"champion_policy": CORE.DUEL.CHAMPION}
        assert runtime == {"git": expected_git,
                           "source_sha256s": {"runner": "1" * 64}}
        return screen_parent

    monkeypatch.setattr(CORE, "load_screen_parent", reopen_screen)
    controller_path = (tmp_path / "server/scripts"
                       / "s4_point_banking_replication_air.py")
    controller_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(CTRL.__file__), controller_path)
    controller_sha = CORE.sha256(controller_path)
    config = CTRL.Config(
        expected_git=expected_git,
        expected_runner_sha256=CORE.sha256(CORE.SCRIPT),
        expected_controller_sha256=controller_sha,
        heartbeat_seconds=30.0,
    )

    preflight_path = tmp_path / CORE.PREFLIGHT_NAMESPACE / "preflight.json"
    preflight_sha = _write_json(preflight_path, {
        "schema": CORE.PREFLIGHT_SCHEMA,
        "complete": True,
        "score_free": True,
        "outcomes_published": False,
        "outcomes_discarded": True,
    })
    preflight_ref = {
        "path": str(CORE.PREFLIGHT_NAMESPACE / "preflight.json"),
        "sha256": preflight_sha,
        "score_free": True,
        "outcomes_published": False,
        "status": "AUTHORIZE_REPLICATION_PACKET_REVIEW",
        "elapsed_seconds": 1.0,
        "projection": {"fleet_hours": 10.0, "max_shard_hours": 2.0},
    }
    packet = copy.deepcopy(CTRL.packet_contract(
        config, CTRL.paths_for(), parent=parent, runtime=runtime,
        preflight=preflight_ref, screen_parent=screen_parent))
    if packet_mutator is not None:
        packet_mutator(packet)
    namespace = tmp_path / CORE.NAMESPACE
    packet_path = namespace / CTRL.PACKET_NAME
    packet_sha = _write_json(packet_path, packet)
    claim = CTRL._expected_review_claim(
        packet_sha256=packet_sha,
        preflight_sha256=packet["score_free_preflight"]["sha256"],
        config=config)
    marker = CORE.PACKET_REVIEW_MARKER + json.dumps(claim, sort_keys=True)
    review_path = namespace / CTRL.REVIEW_NAME
    review_path.write_text(
        "external review\n" + marker + "\n"
        + ((marker + "\n") if duplicate_review_marker else ""))
    admission = {
        "schema": CORE.ADMISSION_SCHEMA,
        "run_id": CORE.RUN_ID,
        "packet": {"path": str(CORE.NAMESPACE / CTRL.PACKET_NAME),
                   "sha256": packet_sha},
        "review": {"path": str(CORE.NAMESPACE / CTRL.REVIEW_NAME),
                   "sha256": CORE.sha256(review_path)},
        "review_claim": claim,
        "operator_asserted_independent_review": True,
        "replication_launch_authorized": True,
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
        "controller_sha256": controller_sha,
        "created_time_ns": 1,
        "nonce": "f" * 64,
        "packet_sha256": packet_sha,
        "admission_sha256": admission_sha,
        "preflight_sha256": packet["score_free_preflight"]["sha256"],
        "screen_aggregate_sha256": CORE.SCREEN_AGGREGATE_SHA256,
        "screen_final_sha256": CORE.SCREEN_FINAL_SHA256,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    if receipt_mutator is not None:
        receipt_mutator(receipt)
    receipt_path = namespace / CTRL.RECEIPT_NAME
    receipt_sha = _write_json(receipt_path, receipt)
    return receipt_path, receipt_sha, expected_git


def test_controller_is_air_only_and_fixed_size():
    assert CTRL.EXPECTED_HOST == "Jerrys-MacBook-Air.local"
    assert CTRL.EXPECTED_PYTHON == "3.14.6"
    assert CORE.CLUSTERS == 2_048
    assert CORE.NULL_SENTINEL_CLUSTERS == 256
    assert CORE.schedule()["records"] == 8_704
    assert CORE.CLAIM_BOUNDARY.startswith("One fixed-look independent")
    assert "optional" in CORE.CLAIM_BOUNDARY


def test_command_templates_are_path_neutral_and_complete():
    commands = [CTRL.command_template(index)
                for index in range(CTRL.SHARD_COUNT)]
    assert all(command[0] == "{python}" for command in commands)
    assert [command[command.index("--shard-index") + 1]
            for command in commands] == \
        [str(index) for index in range(CTRL.SHARD_COUNT)]
    assert all(command[
        command.index("--expected-execution-receipt-sha256") + 1]
        == "{execution_receipt_sha256}" for command in commands)
    assert len({command[-1] for command in commands}) == CTRL.SHARD_COUNT
    assert all(not item.startswith("/Users/")
               for command in commands for item in command)
    aggregate = CTRL.aggregate_template()
    assert aggregate[aggregate.index("--screen-aggregate") + 1] == \
        str(CTRL.SCREEN_AGGREGATE_PATH)
    assert aggregate[aggregate.index("--screen-final") + 1] == \
        str(CTRL.SCREEN_FINAL_PATH)
    assert not any(item.startswith("/Users/") for item in aggregate)


def test_packet_contract_grants_review_not_execution():
    packet = CTRL.packet_contract(
        _config(), CTRL.paths_for(),
        parent={"champion_policy": CORE.DUEL.CHAMPION},
        runtime={"git": "a" * 40},
        preflight={"sha256": "e" * 64, "score_free": True,
                   "outcomes_published": False},
        screen_parent={"aggregate": {"sha256":
                                      CORE.SCREEN_AGGREGATE_SHA256},
                       "final": {"sha256": CORE.SCREEN_FINAL_SHA256}},
    )
    assert packet["packet_review_authorized"] is True
    assert packet["replication_launch_authorized"] is False
    assert packet["strength_claim"] is False
    assert packet["training_authorized"] is False
    assert packet["production_promotion"] is False
    assert packet["retry_or_extension_authorized"] is False
    assert len(packet["jobs"]) == 8
    assert {job["null_sentinel_clusters"] for job in packet["jobs"]} == {32}


def test_review_marker_must_be_one_exact_narrow_claim():
    claim = _review_claim()
    raw = ("review text\n" + CORE.PACKET_REVIEW_MARKER
           + json.dumps(claim, sort_keys=True) + "\n").encode()
    assert CTRL._review_claim(
        raw, packet_sha256="d" * 64, preflight_sha256="e" * 64,
        config=_config()) == claim

    for mutation in (
            lambda value: value.__setitem__("strength_claim", True),
            lambda value: value.__setitem__("training_authorized", True),
            lambda value: value.__setitem__("fixed_look_clusters", 1_024),
            lambda value: value.__setitem__("null_sentinel_clusters", 0),
            lambda value: value.__setitem__("verdict", "HOLD")):
        broken = dict(claim)
        mutation(broken)
        broken_raw = (CORE.PACKET_REVIEW_MARKER
                      + json.dumps(broken, sort_keys=True) + "\n").encode()
        with pytest.raises(CTRL.SupervisorRefused,
                           match="wrong authority"):
            CTRL._review_claim(
                broken_raw, packet_sha256="d" * 64,
                preflight_sha256="e" * 64, config=_config())

    duplicate = raw + CORE.PACKET_REVIEW_MARKER.encode() + \
        json.dumps(claim).encode() + b"\n"
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one"):
        CTRL._review_claim(
            duplicate, packet_sha256="d" * 64,
            preflight_sha256="e" * 64, config=_config())


def test_receipt_is_narrow_and_nonretryable():
    receipt = {
        "schema": CORE.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "complete": True,
        "git": "a" * 40,
        "runner_sha256": "b" * 64,
        "controller_sha256": "c" * 64,
        "created_time_ns": 1,
        "nonce": "f" * 64,
        "packet_sha256": "1" * 64,
        "admission_sha256": "2" * 64,
        "preflight_sha256": "3" * 64,
        "screen_aggregate_sha256": CORE.SCREEN_AGGREGATE_SHA256,
        "screen_final_sha256": CORE.SCREEN_FINAL_SHA256,
        "replication_launch_authorized": True,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    assert CTRL.receipt_problems(
        receipt, config=_config(), packet_sha256="1" * 64,
        admission_sha256="2" * 64,
        preflight_sha256="3" * 64) == []
    receipt["retry_or_extension_authorized"] = True
    assert CTRL.receipt_problems(
        receipt, config=_config(), packet_sha256="1" * 64,
        admission_sha256="2" * 64,
        preflight_sha256="3" * 64)


def test_runner_reopens_complete_reviewed_receipt_chain(tmp_path, monkeypatch):
    receipt_path, receipt_sha, expected_git = _install_receipt_chain(
        tmp_path, monkeypatch)
    assert CORE.require_receipt(
        receipt_path, receipt_sha, expected_git=expected_git) == {
            "path": str(CORE.NAMESPACE / CTRL.RECEIPT_NAME),
            "sha256": receipt_sha,
        }


@pytest.mark.parametrize(
    ("packet_mutator", "receipt_mutator", "duplicate", "match"),
    [
        (lambda packet: packet["runtime"].update({"forged": True}),
         None, False, "packet identity"),
        (lambda packet: packet["controller"].update({"sha256": "9" * 64}),
         lambda receipt: receipt.update({"controller_sha256": "9" * 64}),
         False, "packet identity"),
        (lambda packet: packet["score_free_preflight"].update(
            {"sha256": "8" * 64}),
         None, False, "packet identity"),
        (lambda packet: packet["screen_parent"].update({"clusters": 1_024}),
         None, False, "packet identity"),
        (None, None, True, "one marker"),
    ],
)
def test_runner_rejects_fully_rehashed_receipt_chain_forgery(
        tmp_path, monkeypatch, packet_mutator, receipt_mutator,
        duplicate, match):
    receipt_path, receipt_sha, expected_git = _install_receipt_chain(
        tmp_path, monkeypatch, packet_mutator=packet_mutator,
        receipt_mutator=receipt_mutator,
        duplicate_review_marker=duplicate)
    with pytest.raises(CORE.ProtocolRefused, match=match):
        CORE.require_receipt(
            receipt_path, receipt_sha, expected_git=expected_git)


def test_execution_collision_set_includes_every_partial():
    paths = CTRL.paths_for()
    targets = set(CTRL._execution_targets(paths))
    assert paths.receipt in targets
    assert CTRL.partial(paths.receipt) in targets
    assert paths.final in targets
    assert CTRL.partial(paths.final) in targets
    assert paths.aggregate in targets
    assert CTRL.partial(paths.aggregate) in targets
    assert all(CTRL.partial(path) in targets for path in paths.shards)


def test_status_heartbeat_reads_completed_final_log(tmp_path):
    log_final = tmp_path / "shard.log"
    log_final.write_text(json.dumps({
        "event": "s4-point-banking-replication-progress-v1",
        "shard_index": 3,
        "clusters_complete": 256,
        "clusters_total": 256,
    }, sort_keys=True) + "\n")
    job = SimpleNamespace(
        name="shard-03",
        log_partial=Path(str(log_final) + ".partial"),
        log_final=log_final,
        process=SimpleNamespace(poll=lambda: 0),
    )
    assert CTRL._job_progress(job) == {
        "job": "shard-03",
        "clusters_complete": 256,
        "clusters_total": 256,
        "finished": True,
    }


def test_exclusive_review_copy_never_overwrites(tmp_path):
    path = tmp_path / "review.txt"
    CTRL._write_bytes_exclusive(path, b"first\n")
    with pytest.raises(CTRL.SupervisorRefused, match="refusing to overwrite"):
        CTRL._write_bytes_exclusive(path, b"second\n")
    interrupted = tmp_path / "interrupted.txt"
    CTRL.partial(interrupted).write_bytes(b"partial")
    with pytest.raises(CTRL.SupervisorRefused, match="refusing to overwrite"):
        CTRL._write_bytes_exclusive(interrupted, b"second\n")


def test_final_never_promotes_or_extends(tmp_path, monkeypatch):
    paths = CTRL.paths_for()
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr(CTRL, "rel", lambda path: path.name)
    aggregate = {"status": "CONFIRM_S4_POINT_BANKING_REPLICATION"}
    final = CTRL.final_payload(
        paths=paths, packet_sha256="b" * 64,
        admission_sha256="c" * 64, aggregate=aggregate,
        job_evidence=[])
    assert final["replication_confirmed"] is True
    assert final["strength_claim"] is True
    assert final["production_promotion"] is False
    assert final["explicit_deployment_review_required"] is True
    assert final["retry_or_extension_authorized"] is False
