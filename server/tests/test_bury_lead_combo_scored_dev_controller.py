"""Fail-closed tests for the scored-DEV one-shot controller."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bury_lead_combo_scored_dev_controller as CTRL  # noqa: E402
import bury_lead_combo_scored_dev_design as DESIGN  # noqa: E402


def _sampler_receipt(prefix="a"):
    return {
        "worlds": 30, "attempts": 30, "attempt_cap": 600,
        "pre_rng_sha256": prefix * 64,
        "post_rng_sha256": "b" * 64,
        "sampler_before_sha256": "c" * 64,
        "sampler_after_sha256": "d" * 64,
        "sampler_delta": {
            "sample_attempts": 30, "accepted_worlds": 30,
            "failed_worlds": 0, "rejected_worlds": 0,
            "impossible_worlds": 0,
        },
        "world_commitments_sha256": "e" * 64,
    }


def _dose(mode):
    if mode == "baseline":
        return {
            "schema": "s6-throw-rollout-dose-v1", "mode": mode,
            "deterministic": True, "actor_visible": True,
            "recursive_mc": False, "exploration_only": True,
            "before": None, "after": None, "delta": None,
        }
    return {
        "schema": "s6-throw-rollout-dose-v1", "mode": mode,
        "deterministic": True, "actor_visible": True,
        "recursive_mc": False, "exploration_only": True,
        "before": {"play_calls": 0}, "after": {"play_calls": 1},
        "delta": {"play_calls": 1},
    }


def _runtime(git):
    native = "/runtime/_fast.so"
    return {
        "git": git, "tree_dirty": False,
        "source_sha256s": {"server/a.py": "1" * 64},
        "source_manifest_sha256": CTRL.digest(
            {"server/a.py": "1" * 64}),
        "native": {"path": native, "sha256": "2" * 64},
        "python": {
            "executable": "/usr/bin/python3.14",
            "resolved": "/usr/bin/python3.14", "sha256": "3" * 64,
            "version": "3.14.4", "implementation": "CPython",
            "machine": "x86_64", "cache_tag": "cpython-314",
        },
        "host": {
            "hostname": "test", "architecture": "x86_64",
            "platform": "Linux", "cpu_online": 16,
            "memory_bytes": CTRL.MIN_MEMORY_BYTES,
        },
        "environment": dict(CTRL.REQUIRED_ENVIRONMENT),
        "probe": {
            "have_fast": True, "native": native,
            "bot": "MCS0ReportLCB", "exact_endgame": False,
            "level_objective": False,
        },
        "systemd_unit": {
            "name": CTRL.SYSTEMD_UNIT, "path": "/runtime/unit",
            "sha256": "4" * 64,
        },
        "host_profile": {"path": "/runtime/host", "sha256": "5" * 64},
        "serial_state_execution": True,
        "maximum_wall_seconds": CTRL.MAXIMUM_WALL_SECONDS,
    }


def _review(claim):
    return {
        "commit": "6" * 40, "parent_commit": "7" * 40,
        "ledger_sha256": "8" * 64, "marker_sha256": "9" * 64,
        "claim": claim,
    }


@pytest.fixture
def packet(monkeypatch):
    git = "a" * 40
    monkeypatch.setattr(
        CTRL, "source_sha256s", lambda: {"server/a.py": "1" * 64})
    claim = CTRL.implementation_review_claim(expected_git=git)
    value = CTRL.packet_payload(
        expected_git=git, runtime=_runtime(git),
        implementation_review=_review(claim))
    assert CTRL.packet_problems(value, expected_git=git) == []
    return value


def _receipt(index, seed, count):
    value = {
        "schema": CTRL.STATE_RECEIPT_SCHEMA,
        "state_index": index, "deal_seed": seed,
        "state_id": f"state:{seed}", "source_state_id": f"source:{seed}",
        "record_file": f"state-{index:02d}-of-{CTRL.STATE_COUNT}.json",
        "record_sha256": f"{index + 1:064x}",
        "record_internal_sha256": f"{index + 101:064x}",
        "record_bytes": 1000 + index,
        "source_input_sha256": "a" * 64,
        "source_replay_sha256": "b" * 64,
        "ballot_sha256": "c" * 64,
        "candidate_count": count,
        "selection": {
            "sampler": _sampler_receipt("a"),
            "selected_slots_sha256": "d" * 64,
            "candidate_rollouts": count * 30,
        },
        "report": {
            "sampler": _sampler_receipt("f"),
            "candidate_rollouts_per_mode": 90,
            "modes": [
                {"mode": mode, "world_commitments_sha256": "e" * 64,
                 "continuation_dose": _dose(mode)}
                for mode in ("baseline", "all_boss", "boss_near")
            ],
        },
        "work": {
            "selection_candidate_rollouts": count * 30,
            "report_candidate_rollouts_per_mode": 90,
            "total_candidate_rollouts": count * 30 + 270,
            "exact_complete": True,
        },
        "elapsed_ns": index + 1,
    }
    value["internal_sha256"] = CTRL.digest(value)
    return value


def _all_receipts():
    return [
        _receipt(index, row[0], row[1])
        for index, row in enumerate(DESIGN.SELECTION_ROWS)
    ]


def _record(seed, count):
    sampler = {
        "worlds": 30, "attempts": 30, "attempt_cap": 600,
        "pre_rng_sha256": "a" * 64, "post_rng_sha256": "b" * 64,
        "sampler_before_sha256": "c" * 64,
        "sampler_after_sha256": "d" * 64,
        "sampler_delta": {
            "sample_attempts": 30, "accepted_worlds": 30,
            "failed_worlds": 0, "rejected_worlds": 0,
            "impossible_worlds": 0},
        "world_commitments": [f"{index + 1:064x}" for index in range(30)],
    }
    value = {
        "deal_seed": seed, "state_id": f"state:{seed}",
        "source_state_id": f"source:{seed}", "internal_sha256": "f" * 64,
        "source_input_sha256": "a" * 64,
        "source_replay_sha256": "b" * 64, "ballot_sha256": "c" * 64,
        "candidate_count": count,
        "selection": {
            "sampler": copy.deepcopy(sampler),
            "selected_candidates": {"a": 1},
            "candidate_rollouts": count * 30,
        },
        "report": {
            "sampler": copy.deepcopy(sampler),
            "candidate_rollouts_per_mode": 90,
            "modes": {
                mode: {
                    "world_commitments": list(sampler["world_commitments"]),
                    "continuation_dose": _dose(mode)}
                for mode in ("baseline", "all_boss", "boss_near")
            },
        },
        "work": {
            "selection_candidate_rollouts": count * 30,
            "report_candidate_rollouts_per_mode": 90,
            "total_candidate_rollouts": count * 30 + 270,
            "exact_complete": True,
        },
    }
    return value


def _rehash(value):
    material = dict(value)
    material.pop("internal_sha256", None)
    value["internal_sha256"] = CTRL.digest(material)
    return value


def test_design_review_and_source_identities_are_exact():
    assert CTRL.sha256_file(CTRL.DESIGN_PATH) == CTRL.DESIGN_SOURCE_SHA256
    assert CTRL.sha256_bytes(CTRL.canonical(DESIGN.build_design())) \
        == CTRL.DESIGN_CANONICAL_SHA256
    CTRL.require_design_review()
    sources = CTRL.source_sha256s()
    assert CTRL.REQUIRED_SCRIPT_PATHS <= set(sources)
    assert all(CTRL.is_sha256(value) for value in sources.values())


def test_review_namespaces_are_distinct_and_request_text_cannot_authorize(
        monkeypatch):
    claim = {"schema": "test", "value": 1}
    marker = CTRL._canonical_marker(CTRL.IMPLEMENTATION_REVIEW_PREFIX, claim)
    parent = b"old\n"
    current = parent + marker
    monkeypatch.setattr(
        CTRL.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
            returncode=0))

    def fake_git(*args):
        if any("%P" in arg for arg in args):
            return "1" * 40
        if any(any(field in arg for field in ("%an", "%cn"))
               for arg in args):
            return CTRL.REVIEWER_NAME
        if any(any(field in arg for field in ("%ae", "%ce"))
               for arg in args):
            return CTRL.REVIEWER_EMAIL
        if any("%B" in arg for arg in args):
            return CTRL.REVIEWER_SESSION_TRAILER
        if "diff-tree" in args:
            return CTRL.REVIEW_LEDGER
        raise AssertionError(args)

    monkeypatch.setattr(CTRL, "git", fake_git)
    monkeypatch.setattr(
        CTRL, "git_bytes",
        lambda *args: parent if f"{'1' * 40}:" in args[-1] else current)
    review, observed = CTRL.canonical_review_record(
        commit="2" * 40, prefix=CTRL.IMPLEMENTATION_REVIEW_PREFIX,
        expected=claim, label="test")
    assert observed == marker
    assert review["claim"] == claim
    assert CTRL.IMPLEMENTATION_REVIEW_PREFIX != CTRL.PACKET_REVIEW_PREFIX
    monkeypatch.setattr(
        CTRL, "git_bytes", lambda *args: parent +
        CTRL._canonical_marker("BURY_LEAD_COMBO_SCORED_DEV_REQUEST_V1 ", claim))
    with pytest.raises(CTRL.ControllerRefused, match="marker"):
        CTRL.canonical_review_record(
            commit="2" * 40, prefix=CTRL.IMPLEMENTATION_REVIEW_PREFIX,
            expected=claim, label="test")


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value["authority"].update(execution_authorized=True),
     "authority"),
    (lambda value: value["work"].update(total_candidate_rollouts=1),
     "work"),
    (lambda value: value["runtime"].update(tree_dirty=True), "runtime"),
    (lambda value: value["population"].update(states=63), "identity"),
])
def test_rehashed_packet_mutations_refuse(packet, mutation, expected):
    value = copy.deepcopy(packet)
    mutation(value)
    _rehash(value)
    assert any(expected in problem for problem in CTRL.packet_problems(
        value, expected_git=packet["git"]))


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value["runtime"]["host"].update(extra="forged"), "host"),
    (lambda value: value["runtime"]["python"].update(resolved="relative"),
     "Python"),
    (lambda value: value["runtime"]["source_sha256s"].clear(), "source"),
])
def test_rehashed_nested_runtime_and_source_weakening_refuses(
        packet, mutation, expected):
    value = copy.deepcopy(packet)
    mutation(value)
    value["runtime"]["source_manifest_sha256"] = CTRL.digest(
        value["runtime"]["source_sha256s"])
    value["runtime_profile_sha256"] = CTRL.digest(value["runtime"])
    _rehash(value)
    assert any(expected in problem for problem in CTRL.packet_problems(
        value, expected_git=packet["git"]))


def test_state_receipts_are_score_free_and_exact_work():
    receipts = _all_receipts()
    assert sum(item["work"]["total_candidate_rollouts"]
               for item in receipts) == CTRL.TOTAL_CANDIDATE_ROLLOUTS
    for index, (receipt, row) in enumerate(
            zip(receipts, DESIGN.SELECTION_ROWS, strict=True)):
        assert CTRL.state_receipt_problems(
            receipt, expected_index=index, expected_seed=row[0]) == []
    raw = CTRL.canonical(receipts)
    for forbidden in (b"attacker_points", b"banker_value", b"attempted_lead",
                      b"actual_lead", b"candidate_values", b"actions"):
        assert forbidden not in raw


def test_state_receipt_projects_only_hashes_work_sampler_dose():
    seed, count, _, _ = DESIGN.SELECTION_ROWS[0]
    record = _record(seed, count)
    scorer = SimpleNamespace(record_problems=lambda *args, **kwargs: [],
                             canonical=lambda value: json.dumps(value).encode())
    raw = scorer.canonical(record) + b"\n"
    receipt = CTRL.state_receipt(
        record, state_index=0, elapsed_ns=5, raw=raw, scorer=scorer)
    assert CTRL.state_receipt_problems(
        receipt, expected_index=0, expected_seed=seed) == []
    assert b"attacker_points" not in CTRL.canonical(receipt)


def test_final_closes_all_states_and_authority(packet):
    review = _review(CTRL.packet_review_claim(
        packet=packet, packet_sha256="d" * 64))
    final = CTRL.final_payload(
        packet=packet, packet_sha256="d" * 64,
        packet_review=review, admission_sha256="e" * 64,
        invocation_id="invocation", state_receipts=_all_receipts(),
        started_ns=1, finished_ns=100)
    assert CTRL.final_problems(
        final, packet=packet, packet_sha256="d" * 64) == []
    assert final["authority"] == CTRL.AUTHORITY_FIELDS
    assert all(value is False for value in final["authority"].values())

    admission = CTRL.admission_payload(
        packet=packet, packet_sha256="d" * 64,
        packet_review=review, invocation_id="invocation")
    assert CTRL.admission_problems(
        admission, packet=packet, packet_sha256="d" * 64,
        final=final) == []


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value.update(resume_authorized=True), "authority"),
    (lambda value: value.update(packet_sha256="0" * 64), "identity"),
    (lambda value: value.update(nonce="not-a-sha"), "identity"),
    (lambda value: value.update(extra_authority=True), "field"),
])
def test_rehashed_admission_mutations_refuse(packet, mutation, expected):
    review = _review(CTRL.packet_review_claim(
        packet=packet, packet_sha256="d" * 64))
    final = CTRL.final_payload(
        packet=packet, packet_sha256="d" * 64,
        packet_review=review, admission_sha256="e" * 64,
        invocation_id="invocation", state_receipts=_all_receipts(),
        started_ns=1, finished_ns=100)
    admission = CTRL.admission_payload(
        packet=packet, packet_sha256="d" * 64,
        packet_review=review, invocation_id="invocation")
    mutation(admission)
    _rehash(admission)
    assert any(expected in problem for problem in CTRL.admission_problems(
        admission, packet=packet, packet_sha256="d" * 64, final=final))


@pytest.mark.parametrize("mutate, expected", [
    (lambda value: value["state_receipts"].pop(), "population"),
    (lambda value: value.update(total_candidate_rollouts=1), "work"),
    (lambda value: value["authority"].update(aggregation_authorized=True),
     "authority"),
    (lambda value: value["state_receipts"][0].update(
        record_sha256=value["state_receipts"][1]["record_sha256"]),
     "record"),
])
def test_rehashed_final_mutations_refuse(packet, mutate, expected):
    review = _review(CTRL.packet_review_claim(
        packet=packet, packet_sha256="d" * 64))
    final = CTRL.final_payload(
        packet=packet, packet_sha256="d" * 64,
        packet_review=review, admission_sha256="e" * 64,
        invocation_id="invocation", state_receipts=_all_receipts(),
        started_ns=1, finished_ns=100)
    mutate(final)
    _rehash(final)
    assert any(expected in problem for problem in CTRL.final_problems(
        final, packet=packet, packet_sha256="d" * 64))


def test_malformed_receipt_refuses_without_validator_crash(packet):
    review = _review(CTRL.packet_review_claim(
        packet=packet, packet_sha256="d" * 64))
    final = CTRL.final_payload(
        packet=packet, packet_sha256="d" * 64,
        packet_review=review, admission_sha256="e" * 64,
        invocation_id="invocation", state_receipts=_all_receipts(),
        started_ns=1, finished_ns=100)
    final["state_receipts"][0] = {"work": None}
    _rehash(final)
    problems = CTRL.final_problems(
        final, packet=packet, packet_sha256="d" * 64)
    assert any("receipt" in problem or "closure" in problem
               for problem in problems)


def test_strict_json_rejects_duplicate_and_nonfinite_values():
    with pytest.raises(ValueError, match="duplicate"):
        CTRL.strict_json(b'{"value":1,"value":2}')
    with pytest.raises(ValueError, match="nonfinite"):
        CTRL.strict_json(b'{"value":NaN}')


def test_exclusive_publication_refuses_existing_and_hardlinked_inputs(tmp_path):
    target = tmp_path / "value.json"
    CTRL.write_exclusive(target, {"value": 1})
    assert target.stat().st_mode & 0o222 == 0
    with pytest.raises(CTRL.ControllerRefused, match="existing"):
        CTRL.write_exclusive(target, {"value": 2})
    linked = tmp_path / "linked.json"
    os.link(target, linked)
    with pytest.raises(CTRL.ControllerRefused, match="linked"):
        CTRL.stable_bytes(target, label="linked")


def test_parser_exposes_no_resume_retry_aggregate_or_open_command():
    parser = CTRL.parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction))
    commands = set(subparsers.choices)
    assert commands == {
        "implementation-review-claim", "freeze-packet", "verify-packet",
        "packet-review-claim", "run", "verify-final",
    }


def _patch_run(monkeypatch, tmp_path, packet, *, fail_index=None):
    paths = {
        "PACKET_PATH": tmp_path / "packet.json",
        "IMPLEMENTATION_REVIEW_PATH": tmp_path / "implementation.md",
        "PACKET_REVIEW_PATH": tmp_path / "packet-review.md",
        "ADMISSION_PATH": tmp_path / "locks/admission.json",
        "RECORDS_DIR": tmp_path / "records",
        "FINAL_PATH": tmp_path / "final.json",
    }
    for name, path in paths.items():
        monkeypatch.setattr(CTRL, name, path)
    monkeypatch.setattr(CTRL, "require_fresh_process", lambda: None)
    monkeypatch.setattr(CTRL, "require_clean_exact_git", lambda value: None)
    monkeypatch.setattr(CTRL, "require_frozen_runtime_inputs", lambda value: None)
    monkeypatch.setattr(CTRL, "runtime_snapshot", lambda *args, **kwargs:
                        packet["runtime"])
    monkeypatch.setattr(CTRL, "require_systemd", lambda value: "invocation")
    monkeypatch.setattr(CTRL, "load_packet", lambda *args, **kwargs: packet)
    review = _review(CTRL.packet_review_claim(
        packet=packet, packet_sha256="d" * 64))
    monkeypatch.setattr(
        CTRL, "canonical_review_record",
        lambda **kwargs: (review, b"PACKET REVIEW\n"))
    rows = [{"deal_seed": row[0]} for row in DESIGN.SELECTION_ROWS]
    design = SimpleNamespace(_selection_rows=lambda: rows)
    counts = {row[0]: row[1] for row in DESIGN.SELECTION_ROWS}

    class Scorer:
        @staticmethod
        def score_state(seed):
            index = [row[0] for row in DESIGN.SELECTION_ROWS].index(seed)
            if fail_index is not None and index == fail_index:
                raise RuntimeError("synthetic interruption")
            return _record(seed, counts[seed])

        @staticmethod
        def canonical(value):
            return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

        @staticmethod
        def record_problems(value, *, expected_seed):
            return []

    monkeypatch.setattr(CTRL, "_load_scorer", lambda value: (design, Scorer))
    args = argparse.Namespace(
        expected_git=packet["git"], packet=str(paths["PACKET_PATH"]),
        expected_packet_sha256="d" * 64,
        packet_review_commit="6" * 40,
        admission=str(paths["ADMISSION_PATH"]),
        records=str(paths["RECORDS_DIR"]), final=str(paths["FINAL_PATH"]),
    )
    return paths, args


def test_one_shot_run_writes_64_records_and_score_free_final(
        monkeypatch, tmp_path, packet):
    paths, args = _patch_run(monkeypatch, tmp_path, packet)
    CTRL.run_command(args)
    assert len(list(paths["RECORDS_DIR"].glob("state-*.json"))) == 64
    final = CTRL.strict_json(paths["FINAL_PATH"].read_bytes())
    assert CTRL.final_problems(
        final, packet=packet, packet_sha256="d" * 64) == []
    assert b"attacker_points" not in paths["FINAL_PATH"].read_bytes()
    with pytest.raises(CTRL.ControllerRefused, match="consumed"):
        CTRL.run_command(args)


def test_interruption_spends_admission_preserves_records_and_cannot_resume(
        monkeypatch, tmp_path, packet):
    paths, args = _patch_run(
        monkeypatch, tmp_path, packet, fail_index=2)
    with pytest.raises(RuntimeError, match="interruption"):
        CTRL.run_command(args)
    assert paths["ADMISSION_PATH"].exists()
    assert len(list(paths["RECORDS_DIR"].glob("state-*.json"))) == 2
    assert not paths["FINAL_PATH"].exists()
    with pytest.raises(CTRL.ControllerRefused, match="consumed"):
        CTRL.run_command(args)
