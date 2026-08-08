"""Falsification tests for the frozen Suphx O0 launch/evidence boundary."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl import suphx_o0_screen as screen  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402
from shengji.rl.selfplay_contract import CheckpointRef  # noqa: E402
from shengji.rl.suphx_actor import publish_initial_actor  # noqa: E402
from shengji.rl.suphx_policy import new_from_scratch_model  # noqa: E402


@pytest.fixture(autouse=True)
def _strict_determinism():
    before = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    torch.use_deterministic_algorithms(True, warn_only=False)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(before, warn_only=warn_only)


@pytest.fixture(autouse=True)
def _bind_exact_test_run_root(tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "EXPECTED_RUN_ROOT", tmp_path.resolve())


def test_spec_names_fixed_ensemble_estimand_and_no_strength_authority():
    spec = screen._spec_payload()
    assert spec["screen_schema"] == screen.SCREEN_SCHEMA
    assert spec["artifact_root"] == screen.RUN_RELATIVE_ROOT
    assert spec["training"]["iterations_per_arm"] == 64
    assert spec["training"]["resume_boundary"] == 32
    assert spec["inference"] == {
        "unit": "DEV deal cluster after averaging two flips and 3 seeds",
        "one_sided_alpha_each": 0.05,
        "family_alpha_max": 0.10,
        "distribution": "Student t",
        "df": 127,
        "critical_value": screen.T_CRITICAL_DF127,
        "both_primary_lcbs_gt": 0.0,
        "every_seed_primary_mean_gt": 0.0,
    }
    assert spec["authority"]["strength"] is False
    assert spec["authority"]["production"] is False


def test_seed_and_deal_population_has_no_collision():
    proof = screen._deal_collision_proof()
    assert proof["training_deals_total"] == 3 * 64
    assert proof["within_seed_collisions"] == 0
    assert proof["between_seed_collisions"] == 0
    assert proof["training_dev_collisions"] == 0
    assert proof["training_reserved_namespace_collisions"] == 0
    assert proof["reserved_sequential_evidence_namespace"]["inclusive_hi"] \
        == screen.DEV_SEED0 + screen.DEV_DEALS - 1
    assert proof["oracle_public_share_deals_within_seed"] is True
    flattened = [
        value
        for values in proof["training_deals_by_seed"].values()
        for value in values
    ]
    assert len(flattened) == len(set(flattened))
    assert not set(flattened) & set(proof["dev_deals"])
    assert min(flattened) > screen.CURRENT_RESERVED_DEAL_SEED_CEILING


def test_first_four_dev_deals_target_every_surface_and_replay():
    entries = []
    for index, expected_surface in enumerate(screen.EXPECTED_SURFACES):
        first, captured = screen._capture_dev_state(
            screen.DEV_SEED0 + index, index)
        second, replayed = screen._capture_dev_state(
            screen.DEV_SEED0 + index, index)
        assert first == second
        assert first["surface"] == expected_surface
        assert first["ballot_sha256"] == state_digest(captured.ballot)
        assert captured.ballot == replayed.ballot
        entries.append(first)
    assert {entry["surface"] for entry in entries} == set(
        screen.EXPECTED_SURFACES)


def test_full_dev_asset_is_exactly_stratified_one_state_per_deal():
    payload = screen._dev_payload()
    assert payload["deals"] == 128
    assert len(payload["entries"]) == 128
    assert payload["surface_counts"] == {
        surface: 32 for surface in screen.EXPECTED_SURFACES}
    assert all(value > 0 for value in payload[
        "hidden_burial_witness_surface_counts"].values())
    assert len({entry["deal_seed"] for entry in payload["entries"]}) == 128
    assert payload["training_use"] is False


def test_hidden_swap_is_public_exact_and_oracle_nontrivial():
    _, captured = screen._capture_dev_state(screen.DEV_SEED0, 0)
    changed = screen._hidden_ownership_swap(captured.rnd, captured.seat)
    burial_changed = screen._legal_hidden_burial_neighbor(
        captured.rnd, captured.seat)
    assert screen.information_set_world_problems(
        captured.rnd, changed, captured.seat) == []
    assert screen.information_set_world_problems(
        captured.rnd, burial_changed, captured.seat) == []
    model = new_from_scratch_model(160_000_001)
    public = screen._score_state(
        model, captured.rnd, captured.seat, gamma=0.0)
    public_changed = screen._score_state(
        model, changed, captured.seat, gamma=0.0)
    oracle = screen._score_state(
        model, captured.rnd, captured.seat, gamma=1.0)
    oracle_changed = screen._score_state(
        model, changed, captured.seat, gamma=1.0)
    assert public["actions"] == public_changed["actions"]
    assert torch.equal(public["logits"], public_changed["logits"])
    assert public["value"] == public_changed["value"]
    assert public["greedy"] == public_changed["greedy"]
    assert not torch.equal(oracle["logits"], oracle_changed["logits"])
    public_burial = screen._score_state(
        model, burial_changed, captured.seat, gamma=0.0)
    oracle_burial = screen._score_state(
        model, burial_changed, captured.seat, gamma=1.0)
    assert torch.equal(public["logits"], public_burial["logits"])
    assert not torch.equal(oracle["logits"], oracle_burial["logits"])


def test_void_incompatible_hidden_swap_is_rejected():
    _, captured = screen._capture_dev_state(screen.DEV_SEED0 + 1, 1)
    rnd, seat = captured.rnd, captured.seat
    from shengji.ai.memory import Memory

    memory = Memory(rnd, seat, own_kitty=True)
    assert screen.information_set_world_problems(rnd, copy.deepcopy(rnd), seat) \
        == []
    witness = next(
        (target, donor, target_i, donor_i, suit)
        for target in range(4) if target != seat
        for suit in memory.voids[target]
        for donor in range(4) if donor not in (seat, target)
        for donor_i, donor_card in enumerate(rnd.hands[donor])
        if rnd.ordering.eff_suit(donor_card) == suit
        for target_i, target_card in enumerate(rnd.hands[target])
        if target_card != donor_card
    )
    target, donor, target_i, donor_i, suit = witness
    changed = copy.deepcopy(rnd)
    changed.hands[target][target_i], changed.hands[donor][donor_i] = (
        changed.hands[donor][donor_i], changed.hands[target][target_i])
    problems = screen.information_set_world_problems(rnd, changed, seat)
    assert f"seat {target} holds demonstrated-void suit {suit}" in problems


def test_same_model_two_flip_null_is_exact_zero(tmp_path):
    model = new_from_scratch_model(160_000_001)
    actor_ref = publish_initial_actor(model, tmp_path / "actor")
    rows = [
        screen._comparison_round(
            comparison="same_model_null",
            index=0,
            deal_seed=screen.DEV_SEED0,
            flip=flip,
            candidate_model=model,
            reference_model=model,
            candidate_ref=actor_ref,
            reference_ref=actor_ref,
            candidate_gamma=1.0,
            reference_gamma=1.0,
        )
        for flip in (0, 1)
    ]
    assert rows[0]["attacker_points"] == rows[1]["attacker_points"]
    assert rows[0]["candidate_signed_return"] \
        == -rows[1]["candidate_signed_return"]
    assert sum(row["candidate_signed_return"] for row in rows) == 0.0


def test_student_t_summary_uses_predeclared_one_sided_constant(monkeypatch):
    monkeypatch.setattr(screen, "DEV_DEALS", 4)
    summary = screen._student_t_summary([1.0, 2.0, 3.0, 4.0])
    assert summary["n"] == 4
    assert summary["mean"] == 2.5
    assert summary["df"] == 3
    assert summary["critical_value"] == screen.T_CRITICAL_DF127
    assert summary["lcb"] < summary["mean"]


def test_exclusive_publication_refuses_final_and_partial(tmp_path):
    target = tmp_path / "artifact.json"
    ref = screen._publish_json(target, {"a": 1})
    assert screen._load_json(ref) == {"a": 1}
    with pytest.raises(FileExistsError):
        screen._publish_json(target, {"a": 1})
    other = tmp_path / "other.json"
    screen._partial(other).write_text("stale")
    with pytest.raises(FileExistsError):
        screen._publish_json(other, {"a": 1})


def test_artifact_reopen_refuses_symlink_even_when_target_is_regular(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}\n")
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(screen.SuphxO0ScreenError, match="linked"):
        screen._require_regular_final(linked)


def test_freezer_refuses_a_nonpredeclared_artifact_root(tmp_path):
    wrong = tmp_path / "operator-chosen-alias"
    with pytest.raises(screen.SuphxO0ScreenError, match="artifact root"):
        screen.freeze_packet(wrong)
    assert not wrong.exists()


@pytest.mark.parametrize("command", (
    lambda root: screen.train_arm(root, 0, "oracle"),
    lambda root: screen.evaluate_seed(root, 0),
    lambda root: screen.run_gate(root),
))
def test_execution_commands_refuse_a_nonpredeclared_artifact_root(
        tmp_path, command):
    with pytest.raises(screen.SuphxO0ScreenError, match="artifact root"):
        command(tmp_path / "operator-chosen-alias")


def _packet_review_record(packet_sha256: str) -> str:
    claim = {
        "schema": screen.PACKET_REVIEW_SCHEMA,
        "verdict": "PASS",
        "packet_sha256": packet_sha256,
        "independent_review": True,
        "training_authorized": True,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    return screen.PACKET_REVIEW_MARKER + json.dumps(
        claim, sort_keys=True, separators=(",", ":")) + "\n"


def test_admission_binds_exact_packet_and_review_bytes(tmp_path, monkeypatch):
    packet_ref = screen._publish_json(tmp_path / "launch_packet.json", {})
    monkeypatch.setattr(
        screen, "verify_packet", lambda ref: {"runtime": {"frozen": True}})
    review = tmp_path.parent / f"{tmp_path.name}-independent-review.txt"
    review.write_text(_packet_review_record(packet_ref.sha256))
    review_sha = hashlib.sha256(review.read_bytes()).hexdigest()
    admission_ref = screen.admit_packet(
        packet_ref,
        expected_packet_sha256=packet_ref.sha256,
        review_record=review,
        expected_review_sha256=review_sha,
    )
    admission = screen._load_json(admission_ref)
    assert admission["training_authorized"] is True
    assert admission["o1_authorized"] is False
    assert admission["production_promotion"] is False
    copied = screen._ref(
        admission["review_record_ref"], label="test review copy")
    assert copied.sha256 == review_sha
    assert Path(copied.path).read_bytes() == review.read_bytes()


def test_admission_rejects_wrong_packet_or_review_hash(tmp_path, monkeypatch):
    packet_ref = screen._publish_json(tmp_path / "launch_packet.json", {})
    monkeypatch.setattr(
        screen, "verify_packet", lambda ref: {"runtime": {"frozen": True}})
    review = tmp_path.parent / f"{tmp_path.name}-review.txt"
    review.write_text(_packet_review_record(packet_ref.sha256))
    review_sha = hashlib.sha256(review.read_bytes()).hexdigest()
    with pytest.raises(screen.SuphxO0ScreenError, match="packet"):
        screen.admit_packet(
            packet_ref, expected_packet_sha256="0" * 64,
            review_record=review, expected_review_sha256=review_sha)
    with pytest.raises(screen.SuphxO0ScreenError, match="review"):
        screen.admit_packet(
            packet_ref, expected_packet_sha256=packet_ref.sha256,
            review_record=review, expected_review_sha256="0" * 64)


def test_admission_rejects_internal_or_nonpassing_review_record(
        tmp_path, monkeypatch):
    packet_ref = screen._publish_json(tmp_path / "launch_packet.json", {})
    monkeypatch.setattr(
        screen, "verify_packet", lambda ref: {"runtime": {"frozen": True}})
    internal = tmp_path / "self-authored-review.txt"
    internal.write_text(_packet_review_record(packet_ref.sha256))
    internal_sha = hashlib.sha256(internal.read_bytes()).hexdigest()
    with pytest.raises(screen.SuphxO0ScreenError, match="outside"):
        screen.admit_packet(
            packet_ref, expected_packet_sha256=packet_ref.sha256,
            review_record=internal, expected_review_sha256=internal_sha)

    hold = tmp_path.parent / f"{tmp_path.name}-hold-review.txt"
    hold.write_text("Independent review verdict: HOLD\n")
    hold_sha = hashlib.sha256(hold.read_bytes()).hexdigest()
    with pytest.raises(screen.SuphxO0ScreenError, match="review marker"):
        screen.admit_packet(
            packet_ref, expected_packet_sha256=packet_ref.sha256,
            review_record=hold, expected_review_sha256=hold_sha)


def test_training_refuses_without_packet_and_review_admission(tmp_path):
    with pytest.raises(screen.SuphxO0ScreenError):
        screen.train_arm(tmp_path, 0, "oracle")


def test_two_iteration_training_exercises_real_midpoint_resume(
        tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "ITERATIONS", 2)
    monkeypatch.setattr(screen, "RESUME_BOUNDARY", 1)
    identity = screen._seed_identity(0)
    packet_ref = screen._publish_json(tmp_path / "packet-parent.json", {})
    admission_ref = screen._publish_json(tmp_path / "admission-parent.json", {})
    monkeypatch.setattr(
        screen, "_require_admission",
        lambda root: (packet_ref, admission_ref, {}),
    )
    model = new_from_scratch_model(identity["model_seed"])
    initial_actor = publish_initial_actor(model, tmp_path / "initial-actor")
    initial_manifest = screen._publish_json(tmp_path / "initial-parent.json", {})
    initial_payload = {"model_state_sha256": state_digest(model.state_dict())}
    monkeypatch.setattr(
        screen, "_verify_initial",
        lambda root, index: (
            initial_manifest, initial_actor, initial_payload),
    )
    ref = screen.train_arm(tmp_path, 0, "oracle")
    payload = screen._load_json(ref)
    assert payload["iterations"] == 2
    assert payload["rounds"] == 2
    assert payload["updates"] == 2
    assert payload["exact_midpoint_resume_exercised"] is True
    assert payload["terminal_candidate_adopted"] is True
    assert all(value > 0 for value in payload["surface_counts"].values())
    screen._load_training(tmp_path, 0, "oracle")


def test_reduced_real_training_and_dev_evaluation_reopen_end_to_end(
        tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "ITERATIONS", 2)
    monkeypatch.setattr(screen, "RESUME_BOUNDARY", 1)
    monkeypatch.setattr(screen, "DEV_DEALS", 4)
    identity = screen._seed_identity(0)
    dev_ref = screen._publish_json(tmp_path / "dev.json", screen._dev_payload())
    packet_ref = screen._publish_json(
        screen._packet_path(tmp_path), {"dev_ref": dev_ref.as_dict()})
    admission_ref = screen._publish_json(tmp_path / "admission-parent.json", {})
    packet_payload = {"dev_ref": dev_ref.as_dict()}
    monkeypatch.setattr(screen, "verify_packet", lambda ref: packet_payload)
    monkeypatch.setattr(
        screen, "_require_admission",
        lambda root: (packet_ref, admission_ref, {}),
    )
    model = new_from_scratch_model(identity["model_seed"])
    initial_actor = publish_initial_actor(model, tmp_path / "initial-actor")
    initial_manifest = screen._publish_json(tmp_path / "initial-parent.json", {})
    initial_payload = {"model_state_sha256": state_digest(model.state_dict())}
    monkeypatch.setattr(
        screen, "_verify_initial",
        lambda root, index: (
            initial_manifest, initial_actor, initial_payload),
    )
    screen.train_arm(tmp_path, 0, "oracle")
    screen.train_arm(tmp_path, 0, "public")
    result_ref = screen.evaluate_seed(tmp_path, 0)
    result = screen._load_json(result_ref)
    assert result["rounds"] == 3 * 2 * 4
    assert result["comparison_rounds"] == {
        name: 8 for name in screen.COMPARISONS}
    assert result["diagnostics"]["dev_state_count"] == 4
    _, comparisons, _ = screen._load_dev_result(
        tmp_path, 0, semantic_replay=True)
    assert set(comparisons) == set(screen.COMPARISONS)
    assert all(value == 0.0 for value in comparisons[
        "same_model_null"].values())


def _fake_ref(tmp_path: Path, name: str) -> CheckpointRef:
    return screen._publish_json(tmp_path / name, {"name": name})


def _passing_diagnostics():
    return {
        "dev_state_count": 4,
        "entropy": {
            arm: {
                surface: {"states": 1, "median_normalized_entropy": 0.9}
                for surface in screen.EXPECTED_SURFACES
            }
            for arm in screen.ARMS
        },
        "oracle_hidden_hand_logit_max_abs_difference": {
            surface: 0.01 for surface in screen.EXPECTED_SURFACES},
        "public_hidden_hand_permutation_exact": {
            surface: True for surface in screen.EXPECTED_SURFACES},
        "oracle_hidden_burial_logit_max_abs_difference": {
            surface: 0.01 for surface in screen.EXPECTED_SURFACES},
        "public_hidden_burial_permutation_exact": {
            surface: True for surface in screen.EXPECTED_SURFACES},
        "hidden_burial_witness_counts": {
            surface: 1 for surface in screen.EXPECTED_SURFACES},
        "value_mse_diagnostic": {
            "oracle_initial": 1.0,
            "oracle_terminal": 0.5,
            "public_terminal": 0.8,
        },
        "greedy_action_change_rate_diagnostic": {
            "oracle": 0.5, "public": 0.25},
    }


def test_gate_is_conjunctive_and_never_authorizes_o1_training(
        tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "DEV_DEALS", 4)
    packet_ref = _fake_ref(tmp_path, "packet.json")
    admission_ref = _fake_ref(tmp_path, "admission.json")
    monkeypatch.setattr(
        screen, "_require_admission",
        lambda root: (packet_ref, admission_ref, {}),
    )
    training_refs = {
        (index, arm): _fake_ref(tmp_path, f"train-{index}-{arm}.json")
        for index in range(3) for arm in screen.ARMS
    }
    terminal_refs = {
        (index, arm): _fake_ref(tmp_path, f"model-{index}-{arm}.json")
        for index in range(3) for arm in screen.ARMS
    }

    def load_training(root, index, arm):
        return training_refs[index, arm], terminal_refs[index, arm], {
            "surface_counts": {
                surface: 10 for surface in screen.EXPECTED_SURFACES},
            "model_finite": True,
            "entropy_controller": {
                surface: 0.01 for surface in screen.EXPECTED_SURFACES},
        }

    monkeypatch.setattr(screen, "_load_training", load_training)
    dev_refs = {
        index: _fake_ref(tmp_path, f"dev-{index}.json")
        for index in range(3)}

    def load_dev(root, index, semantic_replay):
        comparisons = {
            "oracle_minus_initial": {deal: 1.0 for deal in range(4)},
            "oracle_minus_public": {deal: 0.5 for deal in range(4)},
            "same_model_null": {deal: 0.0 for deal in range(4)},
        }
        return dev_refs[index], comparisons, {
            "diagnostics": _passing_diagnostics()}

    monkeypatch.setattr(screen, "_load_dev_result", load_dev)
    monkeypatch.setattr(screen, "DEV_SEED0", 0)
    result = screen._compute_gate(tmp_path, semantic_replay=False)
    assert result["verdict"] == "PASS"
    assert result["authorizes_o1_freeze_and_independent_review"] is True
    assert result["authorizes_o1_training"] is False
    assert result["strength_claim"] is False
    assert result["production_promotion"] is False

    def failed_dev(root, index, semantic_replay):
        ref, comparisons, payload = load_dev(root, index, semantic_replay)
        comparisons["oracle_minus_public"] = {
            deal: -0.5 for deal in range(4)}
        return ref, comparisons, payload

    monkeypatch.setattr(screen, "_load_dev_result", failed_dev)
    failed = screen._compute_gate(tmp_path, semantic_replay=False)
    assert failed["verdict"] == "SELECT_NONE"
    assert failed["authorizes_o1_freeze_and_independent_review"] is False


def test_source_contract_includes_launcher_gate_and_engine_dependencies():
    assert "server/scripts/suphx_o0_screen.py" \
        in screen._MATERIAL_RELATIVE_PATHS
    assert "server/shengji/rl/suphx_o0_screen.py" \
        in screen._MATERIAL_RELATIVE_PATHS
    assert "server/shengji/engine/round.py" \
        in screen._MATERIAL_RELATIVE_PATHS
    assert "server/shengji/ai/smart.py" \
        in screen._MATERIAL_RELATIVE_PATHS
    assert "SUPHX_MICRO_SPEC.md" in screen._MATERIAL_RELATIVE_PATHS
