from __future__ import annotations

import json
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
    }


def _review(tmp_path: Path) -> Path:
    path = tmp_path / "review.txt"
    path.write_text("review\n")
    return path


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
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *_args, **_kw: {})
    monkeypatch.setattr(
        RUNTIME, "_consume_attempt_slot",
        lambda **_kw: (RUNTIME.CTRL.SHARD_ADMISSION_PATHS[2], "f" * 64))
    monkeypatch.setattr(RUNTIME, "_validate_attempt_slot",
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
        expected_receipt_sha256="e" * 64, shard_index=2, out=out)
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
        receipt_sha256="e" * 64, review_record=_review(tmp_path), index=0)
    broken = json.loads(json.dumps(shard))
    broken["records"]["treatment"][0]["run"] = "other"
    broken["shard_sha256"] = RUNTIME.self_hash(broken, "shard_sha256")
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="identity drift"):
        RUNTIME.validate_shard(
            broken, packet=packet, packet_sha256="d" * 64,
            receipt_sha256="e" * 64,
            review_record=_review(tmp_path), index=0)


def test_factories_route_selected_surface_and_keep_champion_literal(
        monkeypatch) -> None:
    packet = _packet()
    source = object()
    monkeypatch.setattr(RUNTIME, "_load_npnet", lambda _path: object())
    monkeypatch.setattr(
        RUNTIME.CANDIDATES, "make_play_candidate_source",
        lambda _net: source)
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
    treatment, null, champion = RUNTIME._factories(packet, object())
    assert treatment(1).arm == "treatment"
    assert null(2).arm == "matched-null"
    champion(3)
    assert created == [(source, "treatment", 1),
                       (source, "matched-null", 2)]
    assert champions == [("mc-s0-report-lcb", 3)]


def test_aggregate_consumes_slot_before_opening_shards(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    review = _review(tmp_path)
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(RUNTIME, "_packet",
                        lambda *_args, **_kw: (packet, object()))
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *_args, **_kw: {})
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
            shard_paths=shards,
            out=tmp_path / RUNTIME.CTRL.RESULT_PATH)
