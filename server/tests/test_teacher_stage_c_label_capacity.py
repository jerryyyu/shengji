from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).parents[1] / "scripts" /
          "teacher_stage_c_label_capacity.py")
SPEC = importlib.util.spec_from_file_location("stage_c_label_capacity", SCRIPT)
assert SPEC and SPEC.loader
capacity = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capacity
SPEC.loader.exec_module(capacity)


def _state_set() -> dict:
    states = []
    split_offsets = {"DESIGN": 0, "CALIB": 10_000, "REPORT": 20_000}
    bury_counts = {"DESIGN": 64, "CALIB": 32, "REPORT": 32}
    for split, total in capacity.CTRL.EXPECTED_SPLITS.items():
        for index in range(total):
            surface = "bury" if index < bury_counts[split] else "play"
            count = 1 + index % 5
            states.append({
                "state_id": f"{split}:{index:04d}",
                "split": split,
                "surface_type": surface,
                "stratum": ("ordinary_anchor" if index % 3 == 0
                            else "proposal_disagreement"),
                "ply": 0 if surface == "bury" else (index % 11),
                "seat": index % 4,
                "seed": split_offsets[split] + index,
                "candidates": [
                    {"cards": [f"C{candidate + 2}"], "sources": []}
                    for candidate in range(count)
                ],
            })
    audit_ids = [state["state_id"] for state in states
                 if state["split"] == "REPORT"][:capacity.CTRL.EXPECTED_AUDIT]
    return {"states": states, "report_audit_state_ids": audit_ids}


def _complete_samples(state_set: dict) -> tuple[list[dict], dict]:
    schedule = capacity.build_capacity_schedule(state_set)
    samples = []
    for descriptor in schedule["samples"]:
        work = int(descriptor["expected_candidate_worlds"])
        samples.append({
            **descriptor,
            "status": "COMPLETE_OUTCOMES_DISCARDED",
            "candidate_worlds_attempted": work,
            "candidate_worlds_completed": work,
            "sampler": {
                "sampler_attempts": 1,
                "accepted_worlds": 1,
                "failed_worlds": 0,
                "rejected_worlds": 0,
                "impossible_worlds": 0,
                "overlap_discarded": 0,
                "duplicate_discarded": 0,
            },
            "elapsed_seconds": work / 1_000.0,
            "v11_load_seconds": 1.0,
            "reason_class": None,
            "reason_sha256": None,
            "outcome_tensor_returned": False,
            "outcomes_retained": False,
        })
    return samples, capacity.CTRL.build_schedule(state_set)


def _packet(schedule: dict, label_schedule: dict) -> dict:
    value = {
        "producer": {"git": "a" * 40},
        "parents": {"state_set": {"external_sha256": "b" * 64}},
        "label_schedule": {
            "schedule_sha256": label_schedule["schedule_sha256"]},
        "preflight_schedule": schedule,
    }
    value["packet_sha256"] = capacity.self_hash(value, "packet_sha256")
    return value


def _all_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


def test_schedule_selects_two_unique_witnesses_from_every_label_shard() -> None:
    state_set = _state_set()
    schedule = capacity.build_capacity_schedule(state_set)
    assert schedule["sample_states"] == 32
    assert schedule["workers"] == 8
    assert len({sample["state_id"] for sample in schedule["samples"]}) == 32
    assert {sample["sample_role"] for sample in schedule["samples"]} == {
        "earliest_ply", "max_candidate_worlds"}
    for shard in range(16):
        selected = [sample for sample in schedule["samples"]
                    if sample["shard_index"] == shard]
        assert len(selected) == 2
        assert len({sample["state_id"] for sample in selected}) == 2
    assert schedule["selection_rule"]["selection_uses_no_outcomes"] is True


def test_schedule_is_deterministic_and_covers_early_and_heavy_geometry() -> None:
    state_set = _state_set()
    first = capacity.build_capacity_schedule(state_set)
    second = capacity.build_capacity_schedule(copy.deepcopy(state_set))
    assert first == second
    label = capacity.CTRL.build_schedule(state_set)
    states = {state["state_id"]: state for state in state_set["states"]}
    for shard in label["shards"]:
        rows = [states[state_id] for state_id in shard["state_ids"]]
        chosen = [sample for sample in first["samples"]
                  if sample["shard_index"] == shard["index"]]
        early = next(value for value in chosen
                     if value["sample_role"] == "earliest_ply")
        assert early["ply"] == min(state["ply"] for state in rows)
        heavy = next(value for value in chosen
                     if value["sample_role"] == "max_candidate_worlds")
        remaining = [state for state in rows
                     if state["state_id"] != early["state_id"]]
        audit_ids = set(shard["audit_state_ids"])
        expected = max(capacity.CTRL._label_candidate_worlds(
            state, state["state_id"] in audit_ids) for state in remaining)
        assert heavy["expected_candidate_worlds"] == expected


def test_projection_uses_slower_sample_and_adds_model_load_per_shard() -> None:
    state_set = _state_set()
    samples, label_schedule = _complete_samples(state_set)
    # Give every shard one fast and one slow witness.  This must stay
    # outcome-free, but the unequal rates are essential: a min(rates)
    # regression would otherwise pass when both synthetic samples run at the
    # same candidate-world rate.
    for sample in samples:
        seconds_per_world = (
            0.001 if sample["sample_role"] == "earliest_ply" else 0.002
        )
        sample["elapsed_seconds"] = (
            int(sample["candidate_worlds_completed"]) * seconds_per_world
        )
    projection = capacity.capacity_projection(samples, label_schedule)
    assert projection["throughput_safety_factor"] == 2.0
    assert projection["max_observed_v11_load_seconds"] == 1.0
    first = projection["shards"][0]
    expected_seconds = (
        label_schedule["shards"][0]["candidate_worlds"] * 0.002 + 1.0
    ) * 2.0
    assert first["projected_seconds"] == pytest.approx(expected_seconds)
    fast_only_seconds = (
        label_schedule["shards"][0]["candidate_worlds"] * 0.001 + 1.0
    ) * 2.0
    assert first["projected_seconds"] != pytest.approx(fast_only_seconds)
    assert len(projection["eight_worker_lpt_assignment"]) == 8
    assert sorted(shard for worker in projection["eight_worker_lpt_assignment"]
                  for shard in worker["shards"]) == list(range(16))


def test_projection_refuses_incomplete_or_missing_sample() -> None:
    samples, label_schedule = _complete_samples(_state_set())
    with pytest.raises(capacity.CapacityRefused, match="sample count"):
        capacity.capacity_projection(samples[:-1], label_schedule)
    samples[0]["status"] = "REFUSED_NO_OUTCOME_RETAINED"
    with pytest.raises(capacity.CapacityRefused, match="incomplete"):
        capacity.capacity_projection(samples, label_schedule)


def test_sampler_telemetry_counts_discarded_accepted_draws_in_attempt_identity() -> None:
    work = {"samplers": {"selection": {
        "attempts": 3,
        "accepted": 1,
        "counters": {
            "accepted_worlds": 2, "failed_worlds": 1,
            "rejected_worlds": 0, "impossible_worlds": 0,
        },
        "overlap_discarded": 0,
        "duplicate_discarded": 1,
    }}}
    telemetry = capacity._aggregate_sampler_telemetry(work)
    assert telemetry["accepted_worlds"] == 2
    assert telemetry["accepted_worlds"] + telemetry["failed_worlds"] == \
        telemetry["sampler_attempts"]


def test_pass_result_contains_only_capacity_telemetry_and_exact_review_claim() -> None:
    state_set = _state_set()
    schedule = capacity.build_capacity_schedule(state_set)
    samples, label_schedule = _complete_samples(state_set)
    packet = _packet(schedule, label_schedule)
    result = capacity.build_pass_or_hold_result(
        packet, "c" * 64, "d" * 64, samples, 60.0, label_schedule)
    assert result["capacity_pass"] is True
    assert result["status"] == "AUTHORIZE_LABEL_CONTROLLER_PACKET_REVIEW"
    assert result["outcomes_retained"] is False
    assert result["labels_authorized"] is False
    assert capacity.forbidden_outcome_paths(result) == []
    assert not (_all_keys(result) & capacity.FORBIDDEN_OUTCOME_KEYS)
    claim = capacity.expected_result_review_claim(result, "e" * 64)
    assert claim["label_controller_freeze_authorized"] is True
    assert claim["labels_authorized"] is False
    assert claim["verdict"] == "PASS"


def test_result_semantics_recompute_projection_and_sample_identity() -> None:
    state_set = _state_set()
    schedule = capacity.build_capacity_schedule(state_set)
    samples, label_schedule = _complete_samples(state_set)
    packet = _packet(schedule, label_schedule)
    result = capacity.build_pass_or_hold_result(
        packet, "c" * 64, "d" * 64, samples, 60.0, label_schedule)
    capacity.validate_pass_result_semantics(result, packet, state_set)

    changed = copy.deepcopy(result)
    changed["projection"]["projected_fleet_hours"] += 1.0
    with pytest.raises(capacity.CapacityRefused, match="projection"):
        capacity.validate_pass_result_semantics(changed, packet, state_set)

    changed = copy.deepcopy(result)
    changed["samples"][0]["state_id"] = "DESIGN:forged"
    with pytest.raises(capacity.CapacityRefused, match="sample identity"):
        capacity.validate_pass_result_semantics(changed, packet, state_set)


def test_outcome_or_world_identity_mutation_is_detected_recursively() -> None:
    assert capacity.forbidden_outcome_paths({
        "safe": [{"label_action": {"cards": ["HA"]}}]}) == [
            "$.safe[0].label_action", "$.safe[0].label_action.cards"]
    assert capacity.forbidden_outcome_paths({
        "samples": [{"sampler": {"world_key_sha256s": ["a" * 64]}}]}) == [
            "$.samples[0].sampler.world_key_sha256s"]


def test_worker_returns_work_not_transient_outcome(
        monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = {
        "shard_index": 0, "sample_role": "earliest_ply",
        "state_id": "DESIGN:0", "split": "DESIGN",
        "surface_type": "play", "stratum": "ordinary_anchor", "ply": 0,
        "candidate_count": 1, "audit_expected": False,
        "expected_candidate_worlds": 5, "sampler_attempt_cap": 10,
    }
    work = {
        "total_candidate_worlds_attempted": 5,
        "total_candidate_worlds_completed": 5,
        "samplers": {},
    }
    transient = {
        "label_action": {"index": 0, "cards": ["HA"]},
        "raw_attacker_points": [100], "work": work,
    }
    monkeypatch.setattr(capacity.LABEL, "label_state",
                        lambda *_args, **_kwargs: transient)
    monkeypatch.setattr(capacity.CAPTURE, "replay_state", lambda _state: object())
    monkeypatch.setattr(capacity.LABEL, "validate_label_row",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(capacity, "_WORKER_NET", object())
    monkeypatch.setattr(capacity, "_WORKER_V11_LOAD_SECONDS", 0.5)
    telemetry = capacity._run_sample((descriptor, {"state_id": "DESIGN:0"}))
    assert telemetry["status"] == "COMPLETE_OUTCOMES_DISCARDED"
    assert telemetry["candidate_worlds_completed"] == 5
    assert capacity.forbidden_outcome_paths(telemetry) == []


def test_worker_v11_load_failure_returns_safe_terminal_refusal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = {
        "shard_index": 0, "sample_role": "earliest_ply",
        "state_id": "DESIGN:0", "split": "DESIGN",
        "surface_type": "play", "stratum": "ordinary_anchor", "ply": 0,
        "candidate_count": 1, "audit_expected": False,
        "expected_candidate_worlds": 5, "sampler_attempt_cap": 10,
    }
    monkeypatch.setattr(capacity, "_WORKER_NET", None)
    monkeypatch.setattr(capacity, "_WORKER_INIT_ERROR_CLASS", "LoadError")
    monkeypatch.setattr(capacity, "_WORKER_INIT_ERROR_SHA256", "a" * 64)
    monkeypatch.setattr(capacity, "_WORKER_V11_LOAD_SECONDS", 0.5)
    telemetry = capacity._run_sample((descriptor, {
        "state_id": "DESIGN:0", "split": "DESIGN",
        "surface_type": "play", "stratum": "ordinary_anchor",
    }))
    assert telemetry["status"] == "REFUSED_NO_OUTCOME_RETAINED"
    assert telemetry["candidate_worlds_attempted"] == 0
    assert telemetry["reason_class"] == "CapacityRefused"
    assert capacity.forbidden_outcome_paths(telemetry) == []


def test_admission_is_durable_and_one_shot(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capacity, "REPO", tmp_path)
    packet = {"producer": {"git": "a" * 40}}
    review = {"verdict": "PASS"}
    first = capacity._consume_admission(packet, "b" * 64, review)
    assert len(first) == 64
    with pytest.raises(capacity.CapacityRefused, match="already consumed"):
        capacity._consume_admission(packet, "b" * 64, review)


def test_postcompute_identity_reopens_every_reviewed_input(
        monkeypatch: pytest.MonkeyPatch) -> None:
    packet = {"packet": "frozen"}
    state_set = {"states": ["frozen"]}
    review = {"verdict": "PASS"}
    calls = []

    def reopen(*args):
        calls.append(args)
        return packet, state_set, review

    monkeypatch.setattr(capacity, "_reopen_packet", reopen)
    capacity._require_postcompute_identity(
        Path("packet.json"), "a" * 64,
        Path("controller-review.md"), Path("state-review.md"),
        packet, state_set, review)
    assert len(calls) == 1

    changed = {"packet": "changed"}
    monkeypatch.setattr(
        capacity, "_reopen_packet",
        lambda *_args: (changed, state_set, review))
    with pytest.raises(capacity.CapacityRefused, match="changed during"):
        capacity._require_postcompute_identity(
            Path("packet.json"), "a" * 64,
            Path("controller-review.md"), Path("state-review.md"),
            packet, state_set, review)


def test_packet_and_result_review_markers_are_exact(tmp_path: Path) -> None:
    state_set = _state_set()
    schedule = capacity.build_capacity_schedule(state_set)
    samples, label_schedule = _complete_samples(state_set)
    packet = _packet(schedule, label_schedule)
    packet_claim = capacity.expected_packet_review_claim(packet, "c" * 64)
    packet_review = tmp_path / "packet-review.txt"
    packet_review.write_text(capacity.PACKET_REVIEW_MARKER + json.dumps(
        packet_claim, sort_keys=True, separators=(",", ":")) + "\n")
    assert capacity.validate_packet_review(
        packet_review, packet, "c" * 64) == packet_claim
    forged = copy.deepcopy(packet_claim)
    forged["labels_authorized"] = True
    packet_review.write_text(capacity.PACKET_REVIEW_MARKER + json.dumps(
        forged, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(capacity.CapacityRefused, match="marker drift"):
        capacity.validate_packet_review(packet_review, packet, "c" * 64)

    result = capacity.build_pass_or_hold_result(
        packet, "c" * 64, "d" * 64, samples, 60.0, label_schedule)
    result_claim = capacity.expected_result_review_claim(result, "e" * 64)
    result_review = tmp_path / "result-review.txt"
    result_review.write_text(capacity.RESULT_REVIEW_MARKER + json.dumps(
        result_claim, sort_keys=True, separators=(",", ":")) + "\n")
    assert capacity.validate_result_review(
        result_review, result, "e" * 64) == result_claim


def test_cli_refuses_invalid_run_instead_of_succeeding_silently() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "--definitely-invalid"],
        cwd=SCRIPT.parents[2], capture_output=True, text=True)
    assert result.returncode != 0
    assert "required" in result.stderr or "unrecognized" in result.stderr
