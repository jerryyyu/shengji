from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / \
    "teacher_stage_c_controller_rebind.py"
SPEC = importlib.util.spec_from_file_location("stage_c_rebind", SCRIPT)
assert SPEC and SPEC.loader
rebind = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rebind)


def _paths() -> tuple[Path, Path, Path]:
    repo = Path(__file__).parents[2]
    return (
        repo / "server/runs/logs/teacher-v3-hard-tail-stage-c-design-v1/"
        "design_packet.json",
        repo / "server/runs/logs/"
        "human-v8-h0-counterfactual-controller-v3/controller_packet.json",
        repo / "server/runs/logs/"
        "s3c-one-card-capacity-controller-v2/controller_packet.json",
    )


def _claims() -> tuple[dict, dict, dict]:
    base_path, h0_path, s3c_path = _paths()
    base = rebind.load_json(base_path)
    h0 = rebind.load_json(h0_path)
    s3c = rebind.load_json(s3c_path)
    return (
        rebind.BASE.expected_review_claim(base, rebind.BASE_PACKET_SHA256),
        rebind.expected_h0_review_claim(h0),
        rebind.expected_s3c_review_claim(s3c),
    )


def _review_record(tmp_path: Path, *, h0_mutation: bool = False) -> Path:
    base_claim, h0_claim, s3c_claim = _claims()
    if h0_mutation:
        h0_claim = dict(h0_claim, packet_sha256="0" * 64)
    path = tmp_path / "review.md"
    path.write_text("\n".join([
        rebind.BASE.REVIEW_MARKER + json.dumps(
            base_claim, sort_keys=True, separators=(",", ":")),
        rebind.H0.REVIEW_MARKER + json.dumps(
            h0_claim, sort_keys=True, separators=(",", ":")),
        rebind.S3C.REVIEW_MARKER + json.dumps(
            s3c_claim, sort_keys=True, separators=(",", ":")),
        "",
    ]))
    return path


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(rebind, "producer_identity", lambda **_kwargs: {
        "git": "a" * 40,
        "tree_dirty": False,
        "promotable": False,
        "script_sha256": "b" * 64,
    })
    return rebind.build_packet(
        *_paths(), _review_record(tmp_path), smoke=True)


def test_rebind_consumes_exact_passed_packets_without_copying_curriculum(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _build(tmp_path, monkeypatch)
    base_path, _, _ = _paths()
    base = rebind.load_json(base_path)

    assert packet["base_stage_c"]["external_sha256"] == \
        rebind.BASE_PACKET_SHA256
    assert packet["base_stage_c"]["curriculum_commitments"] == \
        rebind.curriculum_commitments(base)
    assert packet["replacement_bindings"]["h0"]["external_sha256"] == \
        rebind.H0_PACKET_SHA256
    assert packet["replacement_bindings"]["s3c"]["external_sha256"] == \
        rebind.S3C_PACKET_SHA256
    assert packet["delta_contract"]["state_count"] == 2048
    assert packet["delta_contract"]["play_candidate_cap"] == 20
    assert packet["delta_contract"]["bury_candidate_cap"] == 33
    assert packet["delta_contract"]["max_candidate_worlds"] == 10_494_720
    assert packet["delta_contract"][
        "recursive_mc_continuation_rollouts"] == 0
    assert packet["delta_contract"][
        "curriculum_fields_copied_or_rewritten"] is False
    assert "population_contract" not in packet
    assert "label_contract" not in packet
    assert packet["packet_sha256"] == rebind.self_hash(packet)


def test_rebind_is_score_free_and_grants_no_capture_or_training(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _build(tmp_path, monkeypatch)
    assert packet["authority"] == {
        "score_free": True,
        "worlds_sampled": False,
        "exact_solver_invoked": False,
        "outcomes_computed": False,
        "curriculum_changed": False,
        "rebind_review_authorized": True,
        "capture_controller_implementation_authorized": False,
        "state_capture_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    assert packet["consumer_contract"][
        "state_capture_requires_separate_packet_review"] is True
    assert packet["consumer_contract"][
        "labels_require_separate_packet_review"] is True


def test_rebind_refuses_h0_review_marker_drift(tmp_path: Path) -> None:
    _, h0_path, _ = _paths()
    with pytest.raises(rebind.RebindRefused, match="H0-v3 PASS marker drift"):
        rebind.validate_h0(
            h0_path, _review_record(tmp_path, h0_mutation=True))


def test_rebind_refuses_duplicate_review_marker(tmp_path: Path) -> None:
    review = _review_record(tmp_path)
    review.write_text(
        review.read_text() + rebind.H0.REVIEW_MARKER + "{}\n")
    with pytest.raises(rebind.RebindRefused, match="exactly one"):
        rebind.marker_claim(review, rebind.H0.REVIEW_MARKER)


def test_rebind_refuses_authority_or_curriculum_delta_widening(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _build(tmp_path, monkeypatch)
    widened = json.loads(json.dumps(expected))
    widened["authority"]["state_capture_authorized"] = True
    assert "Stage-C rebind authority widened" in \
        rebind.packet_problems(widened, expected)

    widened = json.loads(json.dumps(expected))
    widened["delta_contract"]["label_contract_changed"] = True
    assert "Stage-C curriculum delta widened" in \
        rebind.packet_problems(widened, expected)


def test_review_claim_authorizes_implementation_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packet = _build(tmp_path, monkeypatch)
    packet["producer"]["promotable"] = True
    claim = rebind.expected_review_claim(packet, "c" * 64)
    assert claim["base_stage_c_sha256"] == rebind.BASE_PACKET_SHA256
    assert claim["h0_controller_sha256"] == rebind.H0_PACKET_SHA256
    assert claim["s3c_controller_sha256"] == rebind.S3C_PACKET_SHA256
    assert claim["curriculum_changed"] is False
    assert claim["capture_controller_implementation_authorized"] is True
    assert claim["state_capture_authorized"] is False
    assert claim["labels_authorized"] is False
    assert claim["training_authorized"] is False


def test_publication_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "rebind.json"
    rebind.publish_exclusive(path, {"schema": rebind.SCHEMA})
    original = path.read_bytes()
    with pytest.raises(rebind.RebindRefused, match="existing"):
        rebind.publish_exclusive(path, {"schema": "changed"})
    assert path.read_bytes() == original


def test_real_cli_requires_exact_git_before_packet_access(tmp_path: Path) -> None:
    args = [
        "freeze",
        "--base-stage-c", str(tmp_path / "missing-base"),
        "--h0-controller", str(tmp_path / "missing-h0"),
        "--s3c-controller", str(tmp_path / "missing-s3c"),
        "--review-record", str(tmp_path / "missing-review"),
        "--packet", str(tmp_path / "packet.json"),
    ]
    with pytest.raises(rebind.RebindRefused, match="requires --expected-git"):
        old_argv = rebind.sys.argv
        try:
            rebind.sys.argv = [str(SCRIPT), *args]
            rebind.main()
        finally:
            rebind.sys.argv = old_argv
