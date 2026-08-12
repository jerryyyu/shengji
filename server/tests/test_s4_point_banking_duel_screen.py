"""Fail-closed packet/supervisor tests for the S4 complete-round screen."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import s4_point_banking_duel as DUEL  # noqa: E402
import s4_point_banking_duel_screen as CTRL  # noqa: E402


def _config() -> CTRL.Config:
    return CTRL.Config(
        expected_git="a" * 40,
        expected_runner_sha256="b" * 64,
        expected_controller_sha256="c" * 64,
        heartbeat_seconds=30.0,
    )


def _review_claim(packet_sha256: str = "d" * 64) -> dict:
    return {
        "schema": CTRL.PACKET_REVIEW_SCHEMA,
        "git": "a" * 40,
        "run_id": CTRL.RUN_ID,
        "packet_sha256": packet_sha256,
        "preflight_sha256": CTRL.PREFLIGHT_SHA256,
        "mechanism_screen_sha256": CTRL.MECHANISM_SCREEN_SHA256,
        "independent_review": True,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "verdict": "PASS",
    }


def test_packet_constants_bind_fresh_screen_and_exact_parents():
    assert CTRL.RUN_ID == "s4-point-banking-duel-screen-100b-v2"
    assert CTRL.EXPECTED_HOST == "Jerrys-Mac-mini.local"
    assert CTRL.EXPECTED_PYTHON == "3.14.3"
    assert CTRL.PREFLIGHT_GIT == \
        "57ab02dbe7632d59f97ee16967df39dc829848ae"
    assert CTRL.PREFLIGHT_SHA256 == \
        "fcc8b8913d80db5b1fe4bb7d6b727dc722bb7d0f4ec9c8806842535fc43ee060"
    assert CTRL.MECHANISM_SCREEN_SHA256 == \
        "abd9f36fa3e84c81b90e22f1c827f828a549f7fd6a9420ffbdb7c168974cdc00"
    assert DUEL.PHASES["screen"]["clusters"] == 2_048
    assert DUEL.PHASES["screen"]["clusters_per_shard"] == 256


def test_command_templates_are_path_neutral_and_complete():
    commands = [CTRL.command_template(index)
                for index in range(CTRL.SHARD_COUNT)]
    assert all(command[0] == "{python}" for command in commands)
    assert all(command[command.index("--phase") + 1] == "screen"
               for command in commands)
    assert [command[command.index("--shard-index") + 1]
            for command in commands] == \
        [str(index) for index in range(CTRL.SHARD_COUNT)]
    assert all(command[command.index("--execution-receipt") + 1]
               == str(CTRL.NAMESPACE / CTRL.RECEIPT_NAME)
               for command in commands)
    assert all(command[
        command.index("--expected-execution-receipt-sha256") + 1]
        == "{execution_receipt_sha256}" for command in commands)
    assert len({command[-1] for command in commands}) == CTRL.SHARD_COUNT
    assert all(not item.startswith("/Users/")
               for command in commands for item in command)
    aggregate = CTRL.aggregate_template()
    assert aggregate[0] == "{python}"
    assert all(str(CTRL.NAMESPACE / name) in aggregate
               for name in CTRL.SHARD_NAMES)
    assert aggregate[aggregate.index("--execution-receipt") + 1] == \
        str(CTRL.NAMESPACE / CTRL.RECEIPT_NAME)
    assert aggregate[
        aggregate.index("--expected-execution-receipt-sha256") + 1] == \
        "{execution_receipt_sha256}"
    assert not any(item.startswith("/Users/") for item in aggregate)


def test_resolved_shard_command_binds_exact_preexisting_receipt():
    paths = CTRL.paths_for()
    command = CTRL.shard_argv(
        _config(), 3, paths.shards[3], "e" * 64)
    assert command[command.index("--execution-receipt") + 1] == \
        str(paths.receipt)
    assert command[
        command.index("--expected-execution-receipt-sha256") + 1] == \
        "e" * 64
    assert not any(item.startswith("{") for item in command)


def test_packet_contract_grants_review_not_launch():
    packet = CTRL.packet_contract(
        _config(), CTRL.paths_for(),
        parent={"champion_policy": DUEL.CHAMPION},
        runtime={"git": "a" * 40},
        preflight={"sha256": CTRL.PREFLIGHT_SHA256},
        mechanism={"screen": {"sha256": CTRL.MECHANISM_SCREEN_SHA256}},
    )
    assert packet["packet_review_authorized"] is True
    assert packet["screen_launch_authorized"] is False
    assert packet["confirmation_launch_authorized"] is False
    assert packet["strength_claim"] is False
    assert packet["training_authorized"] is False
    assert packet["production_promotion"] is False
    assert packet["retry_or_extension_authorized"] is False
    assert len(packet["jobs"]) == CTRL.SHARD_COUNT


def test_review_marker_must_be_one_exact_narrow_claim():
    claim = _review_claim()
    raw = ("review text\n" + CTRL.PACKET_REVIEW_MARKER
           + json.dumps(claim, sort_keys=True) + "\n").encode()
    assert CTRL._review_claim(
        raw, packet_sha256="d" * 64, config=_config()) == claim

    for mutation in (
            lambda value: value.__setitem__("strength_claim", True),
            lambda value: value.__setitem__("training_authorized", True),
            lambda value: value.__setitem__("packet_sha256", "0" * 64),
            lambda value: value.__setitem__("verdict", "HOLD")):
        broken = dict(claim)
        mutation(broken)
        broken_raw = (CTRL.PACKET_REVIEW_MARKER
                      + json.dumps(broken, sort_keys=True) + "\n").encode()
        with pytest.raises(CTRL.SupervisorRefused, match="wrong S4 authority"):
            CTRL._review_claim(
                broken_raw, packet_sha256="d" * 64, config=_config())

    duplicate = raw + CTRL.PACKET_REVIEW_MARKER.encode() + \
        json.dumps(claim).encode() + b"\n"
    with pytest.raises(CTRL.SupervisorRefused, match="exactly one"):
        CTRL._review_claim(
            duplicate, packet_sha256="d" * 64, config=_config())


def test_receipt_consumes_one_screen_without_broadening_authority():
    receipt = {
        "schema": CTRL.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "phase": "screen",
        "complete": True,
        "git": "a" * 40,
        "runner_sha256": "b" * 64,
        "created_time_ns": 1,
        "nonce": "e" * 64,
        "packet_sha256": "f" * 64,
        "admission_sha256": "1" * 64,
        "preflight_sha256": CTRL.PREFLIGHT_SHA256,
        "mechanism_screen_sha256": CTRL.MECHANISM_SCREEN_SHA256,
        "screen_launch_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    assert CTRL.receipt_problems(
        receipt, config=_config(), packet_sha256="f" * 64,
        admission_sha256="1" * 64) == []
    receipt["retry_or_resume_authorized"] = True
    assert CTRL.receipt_problems(
        receipt, config=_config(), packet_sha256="f" * 64,
        admission_sha256="1" * 64)


def test_execution_collision_set_includes_partials():
    paths = CTRL.paths_for()
    targets = set(CTRL._execution_targets(paths))
    assert paths.receipt in targets
    assert CTRL.partial(paths.receipt) in targets
    assert paths.final in targets
    assert CTRL.partial(paths.final) in targets
    assert paths.aggregate in targets
    assert CTRL.partial(paths.aggregate) in targets
    assert len(paths.shards) == CTRL.SHARD_COUNT


def test_status_heartbeat_reads_completed_final_log(tmp_path):
    log_final = tmp_path / "shard.log"
    log_final.write_text(json.dumps({
        "event": "s4-point-banking-duel-progress-v1",
        "phase": "screen", "shard_index": 3,
        "clusters_complete": 256, "clusters_total": 256,
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


def test_exclusive_review_copy_never_overwrites_or_resumes(tmp_path):
    path = tmp_path / "review.txt"
    CTRL._write_bytes_exclusive(path, b"first\n")
    assert path.read_bytes() == b"first\n"
    with pytest.raises(CTRL.SupervisorRefused, match="refusing to overwrite"):
        CTRL._write_bytes_exclusive(path, b"second\n")
    partial_target = tmp_path / "interrupted.txt"
    CTRL.partial(partial_target).write_bytes(b"partial")
    with pytest.raises(CTRL.SupervisorRefused, match="refusing to overwrite"):
        CTRL._write_bytes_exclusive(partial_target, b"second\n")
