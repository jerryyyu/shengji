from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).parents[1] / "scripts" /
          "teacher_stage_c_capture_controller.py")
SPEC = importlib.util.spec_from_file_location("stage_c_capture_controller", SCRIPT)
assert SPEC and SPEC.loader
ctrl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctrl)


def _repo() -> Path:
    return Path(__file__).parents[2]


def _base() -> dict:
    return ctrl.load_json(
        _repo() / "server/runs/logs/teacher-v3-hard-tail-stage-c-design-v1/"
        "design_packet.json")


def _paths() -> tuple[Path, Path, Path, Path, list[Path]]:
    repo = _repo()
    return (
        repo / "server/runs/logs/teacher-v3-hard-tail-stage-c-design-v1/"
        "design_packet.json",
        repo / "server/runs/logs/"
        "teacher-v3-hard-tail-stage-c-controller-rebind-v1/rebind_packet.json",
        repo / "server/runs/logs/"
        "human-v8-h0-counterfactual-controller-v3/controller_packet.json",
        repo / "server/runs/logs/"
        "s3c-one-card-capacity-controller-v2/controller_packet.json",
        [repo / logical for logical in ctrl.EVALUATION_ASSET_PATHS],
    )


def test_schedule_is_exactly_split_safe_and_finite() -> None:
    schedule = ctrl.build_schedule(_base())
    assert schedule["shard_count"] == 24
    assert schedule["scan_deals"] == 750_000
    assert schedule["max_uncertainty_candidate_worlds"] == 9_216_000
    assert schedule["max_uncertainty_attempts"] == 4_608_000
    assert [item["split"] for item in schedule["shards"][:8]] == ["DESIGN"] * 8
    assert [item["split"] for item in schedule["shards"][8:16]] == ["CALIB"] * 8
    assert [item["split"] for item in schedule["shards"][16:]] == ["REPORT"] * 8
    assert sum(item["seed_count"] for item in schedule["shards"]) == 750_000
    assert len({(item["split"], item["local_shard"])
                for item in schedule["shards"]}) == 24
    assert schedule["schedule_sha256"] == ctrl.sha256_bytes(
        ctrl.canonical_json({key: value for key, value in schedule.items()
                             if key != "schedule_sha256"}))


def test_quota_cells_reproduce_every_stage_c_commitment() -> None:
    base = _base()
    cells = ctrl.quota_cells(base)
    expected = {"DESIGN": 1024, "CALIB": 512, "REPORT": 512}
    assert {split: sum(cell["quota"] for cell in values)
            for split, values in cells.items()} == expected
    for split, values in cells.items():
        by_stratum = {}
        for cell in values:
            key = (cell["surface_type"], cell["stratum"])
            by_stratum[key] = by_stratum.get(key, 0) + cell["quota"]
            assert cell["pre_candidate_limit"] >= cell["quota"]
        definition = base["population_contract"]["splits"][split]
        assert {name: by_stratum[("play", name)]
                for name in definition["play"]} == definition["play"]
        assert {name: by_stratum[("bury", name)]
                for name in definition["bury"]} == definition["bury"]
        point = [cell for cell in values
                 if cell["stratum"] == "point_banking_opportunity"]
        assert {cell["surface"] for cell in point} == {"follow"}
        exact = [cell for cell in values
                 if cell["stratum"] == "exact_late_eligible"]
        assert {cell["phase"] for cell in exact} == {"late"}


def test_evaluation_manifest_binds_all_assets_and_has_zero_overlap() -> None:
    manifest = ctrl.evaluation_exclusion_manifest(_paths()[4])
    assert manifest["asset_count"] == len(ctrl.EVALUATION_ASSET_PATHS)
    assert manifest["known_seed_identities"] > 0
    assert manifest["capture_seed_overlap"] == 0
    assert manifest["manifest_sha256"] == ctrl.sha256_bytes(
        ctrl.canonical_json({key: value for key, value in manifest.items()
                             if key != "manifest_sha256"}))


def test_evaluation_overlap_refuses(tmp_path: Path) -> None:
    paths = list(_paths()[4])
    mutated = tmp_path / "overlap.json"
    mutated.write_text(json.dumps({"assign": {"170000000": "report"}}))
    paths[0] = mutated
    with pytest.raises(ctrl.ControllerRefused, match="overlaps evaluation"):
        ctrl.evaluation_exclusion_manifest(paths)


def test_build_packet_is_score_free_and_review_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
    base_path, rebind, h0, s3c, assets = _paths()
    monkeypatch.setattr(ctrl, "producer_identity", lambda **_kwargs: {
        "git": "a" * 40, "tree_dirty": False, "promotable": False,
        "controller_script_sha256": "b" * 64,
    })
    monkeypatch.setattr(ctrl, "runtime_sources", lambda: {
        "server/scripts/teacher_stage_c_capture_runtime.py": "c" * 64,
    })
    monkeypatch.setattr(ctrl, "_live_parent", lambda _base: {
        **ctrl.LIVE_PARENT.expected_parent(),
    })
    monkeypatch.setattr(ctrl, "require_runtime_mode", lambda: {
        "environment": {"SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"},
        "experimental_sampler_flags": [], "fast_engine": True,
        "fast_router_sha256": "d" * 64,
        "compiled_fast_binary_sha256": "e" * 64,
    })
    packet = ctrl.build_packet(
        base_path, rebind, h0, s3c, _repo() / "HANDOFF_REVIEW.md", assets,
        smoke=True)
    assert packet["authority"] == {
        "score_free": True,
        "states_captured": False,
        "worlds_sampled": False,
        "outcomes_computed": False,
        "capture_controller_review_authorized": True,
        "state_capture_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert packet["result_contract"]["required_states"] == 2048
    assert packet["result_contract"]["required_play_states"] == 1920
    assert packet["result_contract"]["required_bury_states"] == 128
    assert len(packet["commands"]["run_shards"]) == 24
    assert packet["packet_sha256"] == ctrl.self_hash(packet)
    widened = json.loads(json.dumps(packet))
    widened["authority"]["labels_authorized"] = True
    assert "capture-controller authority widened" in ctrl.packet_problems(
        widened, packet)


def test_review_claim_authorizes_capture_only(
        monkeypatch: pytest.MonkeyPatch) -> None:
    base = _base()
    schedule = ctrl.build_schedule(base)
    packet = {
        "schema": ctrl.SCHEMA,
        "producer": {
            "git": "a" * 40, "promotable": True,
            "controller_script_sha256": "b" * 64,
        },
        "runtime_sources": {
            "server/scripts/teacher_stage_c_capture_runtime.py": "c" * 64,
        },
        "inputs": {"v11pair": {"sha256": "f" * 64}},
        "evaluation_exclusions": {"manifest_sha256": "d" * 64},
        "schedule": schedule,
        "result_contract": {
            "required_states": 2048,
            "required_split_states": {"DESIGN": 1024, "CALIB": 512,
                                      "REPORT": 512},
            "required_play_states": 1920,
            "required_bury_states": 128,
        },
    }
    claim = ctrl.expected_review_claim(packet, "e" * 64)
    assert tuple(claim) == ctrl.REVIEW_FIELDS
    assert claim["one_capture_execution_authorized"] is True
    assert claim["labels_authorized"] is False
    assert claim["training_authorized"] is False
    assert claim["states_captured_before_review"] == 0


def test_duplicate_review_marker_and_publication_refuse(tmp_path: Path) -> None:
    review = tmp_path / "review.md"
    review.write_text(ctrl.REVIEW_MARKER + "{}\n" + ctrl.REVIEW_MARKER + "{}\n")
    with pytest.raises(ctrl.ControllerRefused, match="exactly one"):
        ctrl.marker_claim(review, ctrl.REVIEW_MARKER)
    out = tmp_path / "packet.json"
    ctrl.publish_exclusive(out, {"schema": ctrl.SCHEMA})
    with pytest.raises(ctrl.ControllerRefused, match="overwrite"):
        ctrl.publish_exclusive(out, {"schema": "changed"})


def test_real_cli_requires_git_before_inputs(tmp_path: Path) -> None:
    with pytest.raises(ctrl.ControllerRefused, match="requires --expected-git"):
        ctrl.main([
            "freeze", "--base-stage-c", str(tmp_path / "missing"),
            "--rebind", str(tmp_path / "missing"),
            "--h0-controller", str(tmp_path / "missing"),
            "--s3c-controller", str(tmp_path / "missing"),
            "--review-record", str(tmp_path / "missing"),
            "--evaluation-asset", str(tmp_path / "missing"),
            "--packet", str(tmp_path / "packet"),
        ])
