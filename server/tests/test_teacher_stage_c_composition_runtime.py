from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teacher_stage_c_composition_runtime as RUNTIME  # noqa: E402


def _packet():
    return {
        "producer": {"git": "a" * 40},
        "packet_sha256": "b" * 64,
        "selected_capability": {
            "surface": "play", "head": "ranking", "epoch": 8,
        },
        "model_exports_sha256": "c" * 64,
        "runtime_contract": {
            "python_executable": "/reviewed/python",
            "python_executable_sha256": "f" * 64,
        },
    }


def _review(tmp_path: Path) -> Path:
    path = tmp_path / "review.txt"
    path.write_text("review\n")
    return path


def _capacity_args(tmp_path: Path) -> dict:
    capacity_review = tmp_path / "capacity-review.txt"
    capacity_review.write_text("capacity review\n")
    return {
        "capacity_result_path": tmp_path / "capacity.json",
        "expected_capacity_result_sha256": "6" * 64,
        "capacity_review_record": capacity_review,
    }


def _supervisor_args(tmp_path: Path) -> dict:
    supervisor_review = tmp_path / "supervisor-review.txt"
    supervisor_review.write_text("supervisor review\n")
    return {
        "supervisor_admission_path":
            tmp_path / RUNTIME.CTRL.SUPERVISOR_ADMISSION_PATH,
        "expected_supervisor_admission_sha256": "7" * 64,
        "supervisor_final_path":
            tmp_path / RUNTIME.CTRL.SUPERVISOR_FINAL_PATH,
        "expected_supervisor_final_sha256": "8" * 64,
        "supervisor_review_record": supervisor_review,
    }


def test_attempt_slots_are_consumed_before_work_and_cannot_retry(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    logical, digest = RUNTIME._consume_attempt_slot(
        packet=packet, packet_sha256="d" * 64,
        receipt_sha256="e" * 64, review_record=review,
        kind="shard", index=3)
    assert logical == RUNTIME.CTRL.SHARD_ADMISSION_PATHS[3]
    assert len(digest) == 64
    slot = tmp_path / logical
    assert json.loads(slot.read_text())["consumed_before_outcome_access"] is True
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="existing output"):
        RUNTIME._consume_attempt_slot(
            packet=packet, packet_sha256="d" * 64,
            receipt_sha256="e" * 64, review_record=review,
            kind="shard", index=3)


def test_review_marker_requires_one_exact_narrow_claim(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    expected = {
        "schema": "review", "one_screen_execution_authorized": True,
        "confirmation_launch_authorized": False,
    }
    monkeypatch.setattr(
        RUNTIME.CTRL, "expected_review_claim",
        lambda *_args, **_kw: expected)
    path = tmp_path / "review.txt"
    path.write_text(
        RUNTIME.CTRL.REVIEW_MARKER + json.dumps(expected) + "\n")
    assert RUNTIME._review_claim(path, packet, "d" * 64) == expected
    path.write_text(
        RUNTIME.CTRL.REVIEW_MARKER + json.dumps(expected) + "\n"
        + RUNTIME.CTRL.REVIEW_MARKER + json.dumps(expected) + "\n")
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="exactly one"):
        RUNTIME._review_claim(path, packet, "d" * 64)


def test_child_command_uses_packet_pinned_python_not_verifier_python(
        tmp_path: Path) -> None:
    packet = _packet()
    command = RUNTIME._child_command(
        index=0, packet=packet, packet_sha256="d" * 64,
        controller_review_record=tmp_path / "review.txt",
        receipt_path=tmp_path / "receipt.json",
        receipt_sha256="e" * 64,
        capacity_result_path=tmp_path / "capacity.json",
        capacity_result_sha256="6" * 64,
        capacity_review_record=tmp_path / "capacity-review.txt",
        supervisor_slot_sha256="7" * 64)
    assert command[0] == "/reviewed/python"
    assert command[0] != sys.executable


def _exact_work(searches: int = 1, rollouts: int = 660,
                accepted: int = 330) -> dict:
    return {
        "rollouts": rollouts,
        "searches": searches,
        "sample_attempts": accepted,
        "accepted_worlds": accepted,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "void_fallbacks": 0,
        "short_searches": 0,
        "zero_world": 0,
    }


def _triggered_stage() -> dict:
    value = RUNTIME.SCREEN.feature_off_telemetry()
    value.update({
        "focus_calls": 1,
        "model_triggers": 1,
        "report_rejections": 1,
    })
    return value


@pytest.mark.parametrize(
    "occupied", ("slot", "slot.partial", "receipt", "receipt.partial"),
)
def test_screen_admission_preflights_slot_and_receipt_before_packet_open(
        monkeypatch, tmp_path: Path, occupied: str) -> None:
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    slot = (tmp_path / RUNTIME.CTRL.ADMISSION_PATH).resolve()
    receipt = (tmp_path / RUNTIME.CTRL.RECEIPT_PATH).resolve()
    paths = {
        "slot": slot,
        "slot.partial": Path(str(slot) + ".partial"),
        "receipt": receipt,
        "receipt.partial": Path(str(receipt) + ".partial"),
    }
    paths[occupied].parent.mkdir(parents=True, exist_ok=True)
    paths[occupied].write_text("occupied\n")
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *args, **kwargs: pytest.fail(
            "composition packet opened before admission preflight"))

    with pytest.raises(
            RUNTIME.CompositionRuntimeRefused, match="existing"):
        RUNTIME.admit(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="d" * 64,
            review_record=tmp_path / "review.md",
            capacity_result_path=tmp_path / "capacity.json",
            expected_capacity_result_sha256="6" * 64,
            capacity_review_record=tmp_path / "capacity-review.md",
            out=receipt)
    if occupied in {"receipt", "receipt.partial"}:
        assert not slot.exists()


def test_screen_admission_publishes_a_reopenable_slot_receipt_pair(
        monkeypatch, tmp_path: Path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    capacity_args = _capacity_args(tmp_path)
    capacity = {
        "result_sha256": "7" * 64,
        "screen_max_shard_seconds": 600.0,
    }
    controller_claim = {"verdict": "PASS"}
    capacity_claim = {"verdict": "PASS"}
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet", lambda *args, **kwargs: (packet, object()))
    monkeypatch.setattr(
        RUNTIME, "_review_claim",
        lambda *args, **kwargs: controller_claim)
    monkeypatch.setattr(
        RUNTIME, "_validated_capacity_evidence",
        lambda **kwargs: (capacity, capacity_claim))
    receipt_path = (tmp_path / RUNTIME.CTRL.RECEIPT_PATH).resolve()

    receipt = RUNTIME.admit(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="d" * 64,
        review_record=review, out=receipt_path, **capacity_args)
    slot_path = (tmp_path / RUNTIME.CTRL.ADMISSION_PATH).resolve()

    assert RUNTIME.is_regular_unlinked(slot_path)
    assert RUNTIME.is_regular_unlinked(receipt_path)
    assert receipt["admission_slot_sha256"] == RUNTIME.sha256_file(slot_path)
    assert receipt["receipt_sha256"] \
        == RUNTIME.self_hash(receipt, "receipt_sha256")
    reopened, reopened_capacity = RUNTIME._receipt(
        receipt_path, RUNTIME.sha256_file(receipt_path), packet,
        "d" * 64, review,
        capacity_args["capacity_result_path"],
        capacity_args["expected_capacity_result_sha256"],
        capacity_args["capacity_review_record"])
    assert reopened == receipt
    assert reopened_capacity == capacity


def _capacity_validation() -> dict:
    off = _exact_work()
    focused = _exact_work()
    return {
        "record_counts": {
            label: 2 * RUNTIME.CTRL.PREFLIGHT_CLUSTERS
            for label in RUNTIME.SCREEN.LABELS},
        "stage_c_telemetry": {
            "treatment": _triggered_stage(),
            "matched_null": _triggered_stage(),
        },
        "work_totals": {
            label: {
                "arm": dict(focused if label != "champion" else off),
                "opp": dict(off),
            } for label in RUNTIME.SCREEN.LABELS
        },
        "all_records_exact_work": True,
    }


def test_capacity_preflight_is_score_free_and_precedes_screen_authority(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(RUNTIME, "_packet",
                        lambda *_args, **_kw: (packet, object()))
    monkeypatch.setattr(RUNTIME, "_review_claim", lambda *_args: {})
    monkeypatch.setattr(
        RUNTIME, "_factories", lambda *_args: (object(), object(), object()))
    monkeypatch.setattr(
        RUNTIME.SCREEN, "run_arm_factories",
        lambda label, *_args, **_kw: [{"label": label}])
    monkeypatch.setattr(
        RUNTIME.SCREEN, "validate_screen_records",
        lambda *_args, **_kw: _capacity_validation())
    ticks = iter((100.0, 102.0))
    monkeypatch.setattr(RUNTIME.time, "monotonic", lambda: next(ticks))
    out = tmp_path / RUNTIME.CTRL.CAPACITY_RESULT_PATH
    value = RUNTIME.capacity_preflight(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="d" * 64,
        review_record=review, out=out)
    assert value["capacity_pass"] is True
    assert value["score_free"] is True
    assert value["outcomes_published"] is False
    assert value["screen_execution_authorized"] is False
    assert value["decision"] == "AUTHORIZE_SCREEN_EXECUTION_REVIEW"
    assert not ({"records", "stats", "won", "level_utility"} & set(value))
    assert out.is_file()
    reopened = RUNTIME._capacity_result(
        out, RUNTIME.sha256_file(out), packet, "d" * 64, review)
    assert reopened == value


def test_capacity_summary_rejects_rehashed_zero_work() -> None:
    value = {
        "surface": "play",
        **_capacity_validation(),
    }
    value["work_totals"]["treatment"]["arm"] = _exact_work(
        searches=0, rollouts=0, accepted=0)
    problems = RUNTIME._capacity_summary_problems(value)
    assert any("work drift" in problem or "differ" in problem
               for problem in problems)


def _row(label: str, seed: int, flip: int):
    return {
        "run": RUNTIME.CTRL.RUN_ID,
        "label": label,
        "seed": seed,
        "flip": flip,
    }


def test_run_shard_executes_all_three_arms_on_same_population(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(RUNTIME, "_packet",
                        lambda *_args, **_kw: (packet, object()))
    monkeypatch.setattr(
        RUNTIME, "_receipt",
        lambda *_args, **_kw: ({}, {"screen_max_shard_seconds": 3_600.0}))
    monkeypatch.setattr(
        RUNTIME, "_consume_attempt_slot",
        lambda **_kw: (RUNTIME.CTRL.SHARD_ADMISSION_PATHS[2], "f" * 64))
    monkeypatch.setattr(RUNTIME, "_validate_attempt_slot",
                        lambda **_kw: None)
    monkeypatch.setattr(RUNTIME, "_validate_supervisor_slot",
                        lambda **_kw: None)
    factories = (lambda _seed: object(),) * 3
    monkeypatch.setattr(RUNTIME, "_factories", lambda *_args: factories)
    calls = []

    def run(label, _policy, _opponent, **kwargs):
        calls.append((label, kwargs["seed0"], kwargs["clusters"],
                      kwargs["policy_has_stage_c"]))
        return [_row(label, kwargs["seed0"] + local // 2, local % 2)
                for local in range(2 * kwargs["clusters"])]

    monkeypatch.setattr(RUNTIME.SCREEN, "run_arm_factories", run)
    monkeypatch.setattr(RUNTIME.SCREEN, "aggregate_screen",
                        lambda *_args, **_kw: {})
    out = tmp_path / RUNTIME.CTRL.SHARD_PATHS[2]
    value = RUNTIME.run_shard(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="d" * 64, review_record=review,
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="e" * 64, **_capacity_args(tmp_path),
        supervisor_admission_path=(
            tmp_path / RUNTIME.CTRL.SUPERVISOR_ADMISSION_PATH),
        expected_supervisor_admission_sha256="7" * 64,
        shard_index=2, out=out)
    seed0 = RUNTIME.CTRL.SCREEN_SEED0 + 2 * RUNTIME.CTRL.CLUSTERS_PER_SHARD
    assert calls == [
        ("treatment", seed0, 256, True),
        ("matched_null", seed0, 256, True),
        ("champion", seed0, 256, False),
    ]
    assert value["record_counts"] == {
        label: 512 for label in RUNTIME.SCREEN.LABELS}
    assert value["attempt_admission_slot"] \
        == RUNTIME.CTRL.SHARD_ADMISSION_PATHS[2]
    assert out.is_file()


def test_run_shard_refuses_output_collision_before_consuming_attempt(
        monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    out = tmp_path / RUNTIME.CTRL.SHARD_PATHS[0]
    out.parent.mkdir(parents=True)
    out.write_text("old shard")
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *_args, **_kw: pytest.fail(
            "packet opened after known output collision"))
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="existing composition screen shard output"):
        RUNTIME.run_shard(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="d" * 64,
            review_record=_review(tmp_path),
            receipt_path=tmp_path / "receipt.json",
            expected_receipt_sha256="e" * 64,
            **_capacity_args(tmp_path),
            supervisor_admission_path=(
                tmp_path / RUNTIME.CTRL.SUPERVISOR_ADMISSION_PATH),
            expected_supervisor_admission_sha256="7" * 64,
            shard_index=0, out=out)


def test_shard_identity_binds_run_and_attempt_slot(monkeypatch, tmp_path) -> None:
    packet = _packet()
    records = {label: [_row(label, 1, 0)]
               for label in RUNTIME.SCREEN.LABELS}
    shard = {
        "schema": RUNTIME.SHARD_SCHEMA,
        "run_id": RUNTIME.CTRL.RUN_ID,
        "git": "a" * 40,
        "controller_packet_sha256": "d" * 64,
        "screen_receipt_sha256": "e" * 64,
        "supervisor_admission_slot":
            RUNTIME.CTRL.SUPERVISOR_ADMISSION_PATH,
        "supervisor_admission_slot_sha256": "7" * 64,
        "attempt_admission_slot": RUNTIME.CTRL.SHARD_ADMISSION_PATHS[0],
        "attempt_admission_slot_sha256": "f" * 64,
        "shard_index": 0,
        "seed0": RUNTIME.CTRL.SCREEN_SEED0,
        "clusters": RUNTIME.CTRL.CLUSTERS_PER_SHARD,
        "records": records,
        "record_counts": {label: 512 for label in RUNTIME.SCREEN.LABELS},
        "complete": True,
        "strength_claim": False,
        "confirmation_launch_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    shard["shard_sha256"] = RUNTIME.self_hash(shard, "shard_sha256")
    monkeypatch.setattr(RUNTIME.SCREEN, "aggregate_screen",
                        lambda *_args, **_kw: {})
    monkeypatch.setattr(RUNTIME, "_validate_attempt_slot",
                        lambda **_kw: None)
    RUNTIME.validate_shard(
        shard, packet=packet, packet_sha256="d" * 64,
        receipt_sha256="e" * 64, review_record=_review(tmp_path), index=0,
        supervisor_slot_sha256="7" * 64)
    broken = json.loads(json.dumps(shard))
    broken["records"]["treatment"][0]["run"] = "other"
    broken["shard_sha256"] = RUNTIME.self_hash(broken, "shard_sha256")
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="identity drift"):
        RUNTIME.validate_shard(
            broken, packet=packet, packet_sha256="d" * 64,
            receipt_sha256="e" * 64,
            review_record=_review(tmp_path), index=0,
            supervisor_slot_sha256="7" * 64)


def test_factories_route_selected_surface_and_keep_champion_literal(
        monkeypatch) -> None:
    packet = _packet()
    source = object()
    ensemble = object()
    seen_source = []
    monkeypatch.setattr(
        RUNTIME.CANDIDATES, "make_play_candidate_source",
        lambda net, **kwargs: seen_source.append((net, kwargs)) or source)
    created = []

    def make_stage(_ensemble, actual_source, *, arm, seed):
        created.append((actual_source, arm, seed))
        return SimpleNamespace(arm=arm, seed=seed)

    monkeypatch.setattr(
        RUNTIME.COMPOSITION, "make_play_report_lcb_bot", make_stage)
    champions = []
    monkeypatch.setattr(
        RUNTIME, "make_bot",
        lambda name, seed: champions.append((name, seed)) or object())
    treatment, null, champion = RUNTIME._factories(packet, ensemble)
    assert treatment(1).arm == "treatment"
    assert null(2).arm == "matched-null"
    champion(3)
    assert created == [(source, "treatment", 1),
                       (source, "matched-null", 2)]
    assert seen_source == [(ensemble, {
        "novel_model_source": "stage_c_mc_teacher",
    })]
    assert champions == [("mc-s0-report-lcb", 3)]


def test_aggregate_consumes_slot_before_opening_shards(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(RUNTIME, "_packet",
                        lambda *_args, **_kw: (packet, object()))
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *_args, **_kw: {})
    monkeypatch.setattr(
        RUNTIME, "_capacity_result",
        lambda *_args, **_kw: {"screen_max_shard_seconds": 3_600.0})
    order = []

    def consume(**_kwargs):
        order.append("slot")
        return RUNTIME.CTRL.AGGREGATE_ADMISSION_PATH, "f" * 64

    monkeypatch.setattr(RUNTIME, "_consume_attempt_slot", consume)
    validations = []
    monkeypatch.setattr(
        RUNTIME, "_validate_attempt_slot",
        lambda **kwargs: validations.append(
            (kwargs["kind"], kwargs.get("index"))))
    shards = []
    values = {}
    for index, logical in enumerate(RUNTIME.CTRL.SHARD_PATHS):
        path = tmp_path / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("shard")
        shards.append(path)
        values[str(path)] = {
            "records": {label: [_row(label, index, 0)]
                        for label in RUNTIME.SCREEN.LABELS},
            "shard_sha256": f"{index + 1:064x}",
            "attempt_admission_slot":
                RUNTIME.CTRL.SHARD_ADMISSION_PATHS[index],
            "attempt_admission_slot_sha256": f"{index + 101:064x}",
        }
        log_path = tmp_path / RUNTIME.CTRL.SHARD_LOG_PATHS[index]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("log")
    supervisor = {
        "final_sha256": "a" * 64,
        "supervisor_admission_slot_sha256": "7" * 64,
        "shards": [{
            "index": index,
            "logical_path": RUNTIME.CTRL.SHARD_PATHS[index],
            "external_sha256": "9" * 64,
            "internal_sha256": f"{index + 1:064x}",
            "log_logical_path": RUNTIME.CTRL.SHARD_LOG_PATHS[index],
            "log_sha256": "9" * 64,
            "exit_code": 0,
        } for index in range(RUNTIME.CTRL.SHARD_COUNT)],
    }
    monkeypatch.setattr(RUNTIME, "_supervisor_final",
                        lambda **_kw: supervisor)
    monkeypatch.setattr(RUNTIME, "_supervisor_review_claim",
                        lambda *_args, **_kw: {"verdict": "PASS"})
    monkeypatch.setattr(RUNTIME, "load_json",
                        lambda path: order.append("open") or values[str(path)])
    monkeypatch.setattr(RUNTIME, "validate_shard", lambda *_args, **_kw: None)
    monkeypatch.setattr(RUNTIME, "sha256_file", lambda _path: "9" * 64)
    result = {
        "status": "SELECT_NONE", "strength_claim": False,
    }
    monkeypatch.setattr(RUNTIME.SCREEN, "aggregate_screen",
                        lambda *_args, **_kw: result)
    out = tmp_path / RUNTIME.CTRL.RESULT_PATH
    value = RUNTIME.aggregate(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="d" * 64, review_record=review,
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="e" * 64,
        **_capacity_args(tmp_path),
        supervisor_final_path=(
            tmp_path / RUNTIME.CTRL.SUPERVISOR_FINAL_PATH),
        expected_supervisor_final_sha256="8" * 64,
        supervisor_review_record=(
            _supervisor_args(tmp_path)["supervisor_review_record"]),
        shard_paths=shards, out=out)
    assert order[0] == "slot"
    assert value["decision"] == "SELECT_NONE"
    assert value["confirmation_packet_review_authorized"] is False
    assert validations == [
        *(('shard', index) for index in range(RUNTIME.CTRL.SHARD_COUNT)),
        ('aggregate', None),
    ]
    assert out.is_file()


def test_aggregate_refuses_missing_shard_before_consuming_attempt(
        monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    shards = [tmp_path / logical for logical in RUNTIME.CTRL.SHARD_PATHS]
    for path in shards[:-1]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("sealed shard")
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *_args, **_kw: pytest.fail(
            "packet opened before score-free shard readiness"))
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="shard population is incomplete"):
        RUNTIME.aggregate(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="d" * 64,
            review_record=_review(tmp_path),
            receipt_path=tmp_path / "receipt.json",
            expected_receipt_sha256="e" * 64,
            **_capacity_args(tmp_path),
            supervisor_final_path=(
                tmp_path / RUNTIME.CTRL.SUPERVISOR_FINAL_PATH),
            expected_supervisor_final_sha256="8" * 64,
            supervisor_review_record=(
                _supervisor_args(tmp_path)["supervisor_review_record"]),
            shard_paths=shards,
            out=tmp_path / RUNTIME.CTRL.RESULT_PATH)


def _sealed_supervisor(
        packet, review: Path, capacity_review: Path, *,
        external_sha256: str = "9" * 64) -> dict:
    slot_sha256 = "7" * 64
    commands = [["child", str(index)]
                for index in range(RUNTIME.CTRL.SHARD_COUNT)]
    shards = [{
        "index": index,
        "logical_path": RUNTIME.CTRL.SHARD_PATHS[index],
        "external_sha256": external_sha256,
        "internal_sha256": f"{index + 1:064x}",
        "log_logical_path": RUNTIME.CTRL.SHARD_LOG_PATHS[index],
        "log_sha256": "a" * 64,
        "exit_code": 0,
    } for index in range(RUNTIME.CTRL.SHARD_COUNT)]
    value = {
        "schema": RUNTIME.SUPERVISOR_FINAL_SCHEMA,
        "run_id": RUNTIME.CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": "d" * 64,
        "controller_review_record_sha256": RUNTIME.sha256_file(review),
        "screen_receipt_sha256": "e" * 64,
        "capacity_result_sha256": "6" * 64,
        "capacity_review_record_sha256": RUNTIME.sha256_file(
            capacity_review),
        "supervisor_admission_slot":
            RUNTIME.CTRL.SUPERVISOR_ADMISSION_PATH,
        "supervisor_admission_slot_sha256": slot_sha256,
        "commands": commands,
        "shards": shards,
        "shard_manifest_sha256": RUNTIME.manifest_hash(shards),
        "elapsed_seconds": 12.5,
        "all_children_exit_zero": True,
        "outcomes_published": False,
        "statistics_published": False,
        "aggregate_execution_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["final_sha256"] = RUNTIME.self_hash(value, "final_sha256")
    return value


def test_supervisor_final_is_outcome_free_and_binds_exact_manifest(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    capacity_review = tmp_path / "capacity-review.txt"
    capacity_review.write_text("capacity review\n")
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    for index in range(RUNTIME.CTRL.SHARD_COUNT):
        for logical in (RUNTIME.CTRL.SHARD_PATHS[index],
                        RUNTIME.CTRL.SHARD_LOG_PATHS[index]):
            path = tmp_path / logical
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("sealed")
    value = _sealed_supervisor(packet, review, capacity_review)
    out = tmp_path / RUNTIME.CTRL.SUPERVISOR_FINAL_PATH
    out.write_bytes(RUNTIME.canonical_json(value))
    monkeypatch.setattr(
        RUNTIME, "_child_command",
        lambda *, index, **_kw: ["child", str(index)])
    monkeypatch.setattr(RUNTIME, "_validate_supervisor_slot",
                        lambda **_kw: None)
    reopened = RUNTIME._supervisor_final(
        path=out, expected_sha256=RUNTIME.sha256_file(out),
        packet=packet, packet_sha256="d" * 64,
        receipt_sha256="e" * 64, controller_review_record=review,
        capacity_result={"screen_max_shard_seconds": 3_600.0},
        capacity_result_sha256="6" * 64,
        capacity_review_record=capacity_review)
    assert reopened == value
    assert not ({"records", "stats", "won", "level_utility"} & set(reopened))

    tampered = json.loads(json.dumps(value))
    tampered["stats"] = {"peek": 1}
    tampered["final_sha256"] = RUNTIME.self_hash(
        tampered, "final_sha256")
    out.write_bytes(RUNTIME.canonical_json(tampered))
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="identity/authority"):
        RUNTIME._supervisor_final(
            path=out, expected_sha256=RUNTIME.sha256_file(out),
            packet=packet, packet_sha256="d" * 64,
            receipt_sha256="e" * 64, controller_review_record=review,
            capacity_result={"screen_max_shard_seconds": 3_600.0},
            capacity_result_sha256="6" * 64,
            capacity_review_record=capacity_review)


def test_supervisor_consumes_one_slot_before_children_and_seals_hashes(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    packet["commands"] = {
        "supervisor_child_shards": RUNTIME.CTRL._commands()[
            "supervisor_child_shards"],
    }
    review = _review(tmp_path)
    capacity = _capacity_args(tmp_path)
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(RUNTIME, "_packet",
                        lambda *_args, **_kw: (packet, object()))
    monkeypatch.setattr(
        RUNTIME, "_receipt",
        lambda *_args, **_kw: ({}, {"screen_max_shard_seconds": 3_600.0}))
    monkeypatch.setattr(RUNTIME, "validate_shard", lambda *_args, **_kw: None)
    ticks = iter((10.0, 10.5))
    monkeypatch.setattr(RUNTIME.time, "monotonic", lambda: next(ticks))
    spawned = []

    class Child:
        def __init__(self, command, *, cwd, stdout, stderr):
            assert cwd == tmp_path
            assert stderr == RUNTIME.subprocess.STDOUT
            slot = tmp_path / RUNTIME.CTRL.SUPERVISOR_ADMISSION_PATH
            assert slot.is_file(), "supervisor slot must precede child launch"
            index = int(command[command.index("--shard-index") + 1])
            shard = tmp_path / RUNTIME.CTRL.SHARD_PATHS[index]
            shard.parent.mkdir(parents=True, exist_ok=True)
            shard.write_bytes(RUNTIME.canonical_json({
                "shard_sha256": f"{index + 1:064x}"}))
            stdout.write(f"shard {index} complete\n".encode())
            stdout.flush()
            spawned.append(index)

        def poll(self):
            return 0

        def terminate(self):
            raise AssertionError("completed child was terminated")

        def kill(self):
            raise AssertionError("completed child was killed")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(RUNTIME.subprocess, "Popen", Child)
    out = tmp_path / RUNTIME.CTRL.SUPERVISOR_FINAL_PATH
    value = RUNTIME.supervise(
        packet_path=tmp_path / RUNTIME.CTRL.PACKET_PATH,
        expected_packet_sha256="d" * 64,
        review_record=review,
        receipt_path=tmp_path / RUNTIME.CTRL.RECEIPT_PATH,
        expected_receipt_sha256="e" * 64,
        capacity_result_path=capacity["capacity_result_path"],
        expected_capacity_result_sha256=capacity[
            "expected_capacity_result_sha256"],
        capacity_review_record=capacity["capacity_review_record"],
        out=out)
    assert spawned == list(range(RUNTIME.CTRL.SHARD_COUNT))
    assert value["all_children_exit_zero"] is True
    assert value["outcomes_published"] is False
    assert value["statistics_published"] is False
    assert len(value["shards"]) == RUNTIME.CTRL.SHARD_COUNT
    assert out.is_file()
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="existing composition supervisor final"):
        RUNTIME.supervise(
            packet_path=tmp_path / RUNTIME.CTRL.PACKET_PATH,
            expected_packet_sha256="d" * 64,
            review_record=review,
            receipt_path=tmp_path / RUNTIME.CTRL.RECEIPT_PATH,
            expected_receipt_sha256="e" * 64,
            capacity_result_path=capacity["capacity_result_path"],
            expected_capacity_result_sha256=capacity[
                "expected_capacity_result_sha256"],
            capacity_review_record=capacity["capacity_review_record"],
            out=out)


def test_supervisor_heartbeat_reads_only_outcome_free_child_progress(
        tmp_path: Path) -> None:
    path = tmp_path / "shard.log"
    path.write_text(
        "unrelated output\n"
        "    treatment: 100/512 rounds\n"
        "not-json and no outcome bytes\n"
        "    matched_null: 200/512 rounds\n")
    assert RUNTIME._latest_shard_progress(3, path) == {
        "shard_index": 3,
        "arm": "matched_null",
        "rounds_complete": 200,
        "rounds_total": 512,
    }
    assert RUNTIME._latest_shard_progress(4, tmp_path / "missing") is None


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_supervisor_signal_owner_terminates_registered_real_child(
        signum: int) -> None:
    process = None
    with pytest.raises(RUNTIME.CompositionSupervisorInterrupted) as caught:
        with RUNTIME.SupervisorSignalOwner() as owner:
            process = subprocess.Popen([
                sys.executable, "-c", "import time; time.sleep(60)"])
            owner.register(process)
            os.kill(os.getpid(), signum)
    assert caught.value.signum == signum
    assert process is not None
    process.wait(timeout=2.0)
    assert process.poll() is not None


def test_supervisor_signal_during_spawn_is_deferred_until_registration(
        monkeypatch) -> None:
    real_popen = subprocess.Popen
    spawned = []

    def signal_before_popen_returns(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        os.kill(os.getpid(), signal.SIGTERM)
        return process

    monkeypatch.setattr(
        RUNTIME.subprocess, "Popen", signal_before_popen_returns)
    try:
        with pytest.raises(RUNTIME.CompositionSupervisorInterrupted):
            with RUNTIME.SupervisorSignalOwner() as owner:
                with owner.deferred_until_registered():
                    process = RUNTIME.subprocess.Popen([
                        sys.executable, "-c", "import time; time.sleep(60)"])
                    owner.register(process)
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2.0)
    assert len(spawned) == 1
    assert spawned[0].poll() is not None


def test_aggregate_rejects_rehashed_shard_after_external_seal_before_open(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    capacity = _capacity_args(tmp_path)
    supervisor_args = _supervisor_args(tmp_path)
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    shards = []
    for index in range(RUNTIME.CTRL.SHARD_COUNT):
        shard = tmp_path / RUNTIME.CTRL.SHARD_PATHS[index]
        log = tmp_path / RUNTIME.CTRL.SHARD_LOG_PATHS[index]
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text("rewritten-and-self-rehashed")
        log.write_text("log")
        shards.append(shard)
    sealed = _sealed_supervisor(
        packet, review, capacity["capacity_review_record"],
        external_sha256="1" * 64)
    monkeypatch.setattr(RUNTIME, "_packet",
                        lambda *_args, **_kw: (packet, object()))
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *_args, **_kw: {})
    monkeypatch.setattr(
        RUNTIME, "_capacity_result",
        lambda *_args, **_kw: {"screen_max_shard_seconds": 3_600.0})
    monkeypatch.setattr(RUNTIME, "_supervisor_final",
                        lambda **_kw: sealed)
    monkeypatch.setattr(RUNTIME, "_supervisor_review_claim",
                        lambda *_args, **_kw: {"verdict": "PASS"})
    monkeypatch.setattr(
        RUNTIME, "_consume_attempt_slot",
        lambda **_kw: (RUNTIME.CTRL.AGGREGATE_ADMISSION_PATH, "f" * 64))
    real_sha = RUNTIME.sha256_file

    def digest(path):
        if Path(path).resolve() == shards[0].resolve():
            return "2" * 64
        if Path(path).suffix == ".log":
            return "a" * 64
        return real_sha(Path(path))

    monkeypatch.setattr(RUNTIME, "sha256_file", digest)
    monkeypatch.setattr(
        RUNTIME, "load_json",
        lambda _path: pytest.fail("changed shard opened before seal check"))
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="supervisor seal mismatch"):
        RUNTIME.aggregate(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="d" * 64, review_record=review,
            receipt_path=tmp_path / "receipt.json",
            expected_receipt_sha256="e" * 64,
            **capacity,
            supervisor_final_path=supervisor_args["supervisor_final_path"],
            expected_supervisor_final_sha256="8" * 64,
            supervisor_review_record=supervisor_args[
                "supervisor_review_record"],
            shard_paths=shards, out=tmp_path / RUNTIME.CTRL.RESULT_PATH)
