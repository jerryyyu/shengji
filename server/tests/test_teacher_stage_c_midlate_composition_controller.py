from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teacher_stage_c_composition_runtime as RUNTIME  # noqa: E402
import teacher_stage_c_midlate_composition_controller as CTRL  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402


def test_contract_is_the_narrow_passed_midlate_policy() -> None:
    candidate = CTRL.candidate_contract()
    screen = CTRL.screen_contract()
    assert candidate["live_parent"] == "mc-s0-report-lcb"
    assert candidate["model_min_completed_tricks"] == 5
    assert candidate["fresh_report_lcb_required"] is True
    assert candidate["direct_model_override_authorized"] is False
    assert CTRL.SCREEN_CLUSTERS == 2_048
    assert CTRL.SHARD_COUNT == 8
    assert CTRL.CLUSTERS_PER_SHARD == 256
    assert screen["fixed_look"] is True
    assert screen["screen_is_exploratory_not_confirmation"] is True
    assert screen["positive_unresolved_result_does_not_reject_mechanism"] \
        is True
    assert screen["one_sided_primary_critical"] == 1.645
    assert screen["two_sided_null_critical"] == 1.96
    assert 0.047 < screen["planning_fixed_look_boundary_effect"] < 0.048
    assert CTRL.PREFLIGHT_SEED0 not in range(
        CTRL.SCREEN_SEED0, CTRL.SCREEN_SEED0 + CTRL.SCREEN_CLUSTERS)


def test_parent_review_snapshot_has_one_canonical_marker_per_gate() -> None:
    claims = {
        "controller": {"schema": "controller", "verdict": "PASS"},
        "selection": {"schema": "selection", "verdict": "PASS"},
        "result": {"schema": "result", "verdict": "PASS"},
    }
    value = CTRL._review_snapshot_bytes(claims).decode().splitlines()
    assert len(value) == 3
    for line, marker, name in zip(value, (
            CTRL.PARENT.REVIEW_MARKER,
            CTRL.PARENT.SELECTION_REVIEW_MARKER,
            CTRL.PARENT.RESULT_REVIEW_MARKER),
            ("controller", "selection", "result"), strict=True):
        assert line.startswith(marker)
        assert json.loads(line[len(marker):]) == claims[name]


def _exports() -> list[dict]:
    return [{
        "logical_path": CTRL.MODEL_PATHS[index],
        "sha256": f"{seed + 100:064x}",
        "metadata": {
            "surface": "play", "head": "ranking",
            "epoch": 32, "seed": seed,
        },
    } for index, seed in enumerate(MODEL.TRAINING_SEEDS)]


def test_packet_binds_parent_models_screen_and_narrow_authority(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    monkeypatch.setattr(CTRL, "_source_sha256s",
                        lambda: {"source": "1" * 64})
    monkeypatch.setattr(CTRL, "runtime_contract",
                        lambda: {"host": "mini", "python": "3.14"})
    monkeypatch.setattr(CTRL, "candidate_contract",
                        lambda: {"model_min_completed_tricks": 5})
    monkeypatch.setattr(CTRL, "capacity_contract", lambda: {"clusters": 4})
    monkeypatch.setattr(CTRL, "screen_contract",
                        lambda: {"clusters": 2_048})
    monkeypatch.setattr(CTRL, "_commands", lambda: {"run": ["python"]})
    monkeypatch.setattr(CTRL, "result_contract",
                        lambda: {"aggregate": "aggregate.json"})

    parent_root = tmp_path / "parent"
    paths = {}
    for name in ("controller_packet", "selection_population",
                 "state_result", "evaluation_admission"):
        path = parent_root / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
        paths[name] = path
    snapshot = tmp_path / CTRL.PARENT_REVIEW_SNAPSHOT_PATH
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("reviews\n")
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "2" * 64)
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(CTRL, "_external_ref", lambda path, digest: {
        "absolute_path": str(path.resolve()), "external_sha256": digest})

    selected = {"surface": "play", "head": "ranking", "epoch": 32}
    source_exports = [{"logical_path": "old", "sha256": "3" * 64}]
    data = {
        "paths": paths,
        "packet": {
            "selected_capability": selected,
            "model_exports": source_exports,
            "model_exports_sha256": "4" * 64,
        },
        "summary": {"aggregate_sha256": "5" * 64},
    }
    packet = CTRL.build_packet(
        git="a" * 40, parent_root=parent_root, data=data,
        review_snapshot=snapshot, exports=_exports())
    assert packet["parents"]["kind"] == CTRL.PARENT_KIND
    assert packet["parents"]["state_result"]["external_sha256"] \
        == CTRL.PARENT_RESULT_SHA256
    assert packet["parent_validation"] == data["summary"]
    assert packet["selected_capability"] == selected
    assert packet["source_model_exports"] == source_exports
    assert packet["model_exports"] == _exports()
    assert packet["authority"] == {
        "capacity_preflight_review_authorized": True,
        "capacity_preflight_launch_authorized": False,
        "screen_packet_review_authorized": False,
        "screen_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "v11_inference_authorized": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert packet["packet_sha256"] == CTRL.self_hash(
        packet, "packet_sha256")


def test_runtime_parent_adapter_recomputes_summary_and_refuses_drift(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(CTRL, "REPO", tmp_path)
    root = tmp_path / "parent"
    paths = {name: root / f"{name}.json" for name in (
        "controller_packet", "selection_population", "state_result",
        "evaluation_admission")}
    snapshot = tmp_path / CTRL.PARENT_REVIEW_SNAPSHOT_PATH
    summary = {"aggregate_sha256": "a" * 64}
    source_models = [{"sha256": "b" * 64}]
    data = {
        "summary": summary,
        "packet": {
            "selected_capability": {"surface": "play"},
            "model_exports": source_models,
            "model_exports_sha256": "c" * 64,
        },
    }
    refs = {
        name: {"absolute_path": str(path), "external_sha256": digest}
        for (name, path), digest in zip(paths.items(), (
            CTRL.PARENT_PACKET_SHA256, CTRL.PARENT_SELECTION_SHA256,
            CTRL.PARENT_RESULT_SHA256,
            CTRL.PARENT_EVALUATION_ADMISSION_SHA256), strict=True)
    }
    packet = {
        "parents": {
            "kind": CTRL.PARENT_KIND,
            "evidence_root": {"absolute_path": str(root),
                              "git": CTRL.PARENT_GIT},
            **refs,
            "review_snapshot": {
                "logical_path": CTRL.PARENT_REVIEW_SNAPSHOT_PATH,
                "external_sha256": "d" * 64,
            },
        },
        "parent_validation": summary,
        "selected_capability": {"surface": "play"},
        "source_model_exports": source_models,
        "source_model_exports_sha256": "c" * 64,
    }
    monkeypatch.setattr(CTRL, "_parent_paths", lambda _root: paths)
    monkeypatch.setattr(
        CTRL, "_path_from_ref",
        lambda ref, _label: (tmp_path / ref["logical_path"]).resolve()
        if "logical_path" in ref else Path(ref["absolute_path"]).resolve())
    monkeypatch.setattr(CTRL, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(CTRL, "sha256_file", lambda _path: "d" * 64)
    monkeypatch.setattr(CTRL, "_validate_parent_fast",
                        lambda _root, _review: data)
    CTRL.validate_runtime_parent(packet)
    broken = copy.deepcopy(packet)
    broken["parent_validation"] = {"aggregate_sha256": "e" * 64}
    with pytest.raises(CTRL.CompositionControllerRefused,
                       match="reconstructed summary"):
        CTRL.validate_runtime_parent(broken)


def test_shared_runtime_uses_custom_parent_adapter_before_ensemble(
        monkeypatch, tmp_path: Path) -> None:
    called = []

    class ParentError(RuntimeError):
        pass

    authority = {
        "capacity_preflight_review_authorized": True,
        "capacity_preflight_launch_authorized": False,
        "screen_packet_review_authorized": False,
        "screen_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "v11_inference_authorized": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    packet = {
        "schema": "schema", "packet_id": "packet", "run_id": "run",
        "packet_sha256": "internal", "producer": {
            "git": "g", "tree_dirty": False, "sources": {"s": "h"}},
        "runtime_contract": {"runtime": True},
        "candidate_contract": {"candidate": True},
        "capacity_contract": {"capacity": True},
        "screen_contract": {"screen": True},
        "commands": {"commands": True},
        "result_contract": {"result": True},
        "authority": authority,
    }
    fake = SimpleNamespace(
        SCHEMA="schema", PACKET_ID="packet", RUN_ID="run",
        CompositionControllerRefused=ParentError,
        _source_sha256s=lambda: {"s": "h"},
        runtime_contract=lambda: {"runtime": True},
        candidate_contract=lambda: {"candidate": True},
        capacity_contract=lambda: {"capacity": True},
        screen_contract=lambda: {"screen": True},
        _commands=lambda: {"commands": True},
        result_contract=lambda: {"result": True},
        validate_runtime_parent=lambda value: called.append(value),
    )
    packet_path = tmp_path / "packet.json"
    packet_path.write_text("packet")
    sentinel = object()
    monkeypatch.setattr(RUNTIME, "CTRL", fake)
    monkeypatch.setattr(RUNTIME, "_require_clean_tree", lambda: None)
    monkeypatch.setattr(RUNTIME, "_expected_packet_path",
                        lambda: packet_path.resolve())
    monkeypatch.setattr(RUNTIME, "is_regular_unlinked", lambda _path: True)
    monkeypatch.setattr(RUNTIME, "sha256_file", lambda _path: "external")
    monkeypatch.setattr(RUNTIME, "load_json", lambda _path: packet)
    monkeypatch.setattr(RUNTIME, "self_hash",
                        lambda _value, _field: "internal")
    monkeypatch.setattr(RUNTIME, "_git", lambda *_args: "g")
    monkeypatch.setattr(RUNTIME, "_ensemble_from_packet",
                        lambda _packet: sentinel)
    reopened, ensemble = RUNTIME._packet(packet_path, "external")
    assert reopened is packet
    assert ensemble is sentinel
    assert called == [packet]
