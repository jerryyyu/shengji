"""Progressive capacity and receipt rederivation witnesses."""

from __future__ import annotations

import copy
import hashlib
import inspect
from pathlib import Path
import threading
import time

import pytest

from shengji.rl import privileged_teacher_luna_rpc_capacity as capacity
from shengji.rl.privileged_teacher_luna_rpc_transport import (
    CodexTurnTransportError,
    DISABLED_FEATURES,
    MODEL,
    PINNED_CODEX_VERSION,
    REASONING_EFFORT,
)
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
from shengji.rl.privileged_teacher_luna_rpc_capacity import (
    GameMetric,
    RPCCapacityError,
    RPCConcurrency,
    ROUTE_PASS,
    ROUTE_REFUSE,
    validate_canary_receipt,
    validate_capacity_receipt,
)


def runtime():
    sources = {name: "1" * 64 for name in capacity.SOURCE_PATHS}
    catalog = {"schema": "pt-luna-codex-tool-catalog-v1",
               "version": PINNED_CODEX_VERSION,
               "binary_sha256": "2" * 64,
               "disabled_features": list(DISABLED_FEATURES),
               "feature_catalog_sha256": "3" * 64}
    return {"schema": "pt-luna-turn-rpc-runtime-v1",
            "python_executable": "/test/python",
            "python_sha256": "4" * 64, "python_version": "test",
            "platform": "test", "execution_git": "a" * 40,
            "engine_mode": "pure-python", "strict_voids": True,
            "python_dont_write_bytecode": True,
            "required_environment": dict(
                capacity.REQUIRED_ENGINE_ENVIRONMENT),
            "native_extension": None,
            "git_tree": "b" * 40, "codex_binary": "/test/codex",
            "boot_identity_sha256": "9" * 64,
            "codex_binary_sha256": "2" * 64,
            "codex_version": PINNED_CODEX_VERSION,
            "codex_tool_catalog": catalog,
            "model": MODEL, "reasoning_effort": REASONING_EFFORT,
            "sources": sources,
            "source_set_sha256": hashlib.sha256(
                canonical_json_bytes(sources)).hexdigest()}


def source_review_auth(source_set_sha256: str):
    claim_body = {
        "schema": capacity.SOURCE_REVIEW_SCHEMA,
        "execution_git": "a" * 40,
        "source_set_sha256": source_set_sha256,
        "design_sha256": "d" * 64,
        "score_free_canary_authorized": True,
        "score_free_capacity_authorized": True,
        "scientific_execution_authorized": False,
        "outcome_opening_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "strength_claim_authorized": False,
        "authority": dict(capacity.selfplay.AUTHORITY),
    }
    claim = {**claim_body, "claim_sha256": hashlib.sha256(
        canonical_json_bytes(claim_body)).hexdigest()}
    return {"review_commit": "b" * 40,
            "review_marker_sha256": "c" * 64,
            "review_claim": claim}


def canary_receipt(*, play_teams=(0, 1, 1, 0)):
    def row(name, *, plays, rpcs, rollouts, teams):
        return {
            "schema": "pt-luna-turn-rpc-real-canary-row-v1",
            "name": name, "completed_contested_decisions": plays,
            "planner_rpc_count": rpcs, "rollout_rpc_count": rollouts,
            "play_rpc_count": plays, "play_teams": list(teams),
            "provider_request_sha256s": ["5" * 64] * rpcs,
            "provider_response_sha256s": ["6" * 64] * rpcs,
            "tool_event_count": 0, "input_tokens": rpcs * 100,
            "cached_input_tokens": 0, "cache_write_input_tokens": 0,
            "output_tokens": rpcs * 10, "reasoning_output_tokens": 0,
            "total_tokens": rpcs * 110,
            "rpc_wall_milliseconds": rpcs,
            "wall_nanoseconds": 1_000_000, "engine_complete": False,
            "engine_failed": False, "state_changed": True,
            "journal_summary_sha256": "7" * 64}
    active_runtime = runtime()
    body = {
        "schema": capacity.CANARY_SCHEMA, "scientific": False,
        "seed_commitment_sha256": "8" * 64,
        "rows": [
            row("nonterminal", plays=1, rpcs=2, rollouts=1, teams=(0,)),
            row("alternation", plays=4, rpcs=4, rollouts=0,
                teams=play_teams)],
        "runtime": active_runtime,
        "source_review": source_review_auth(
            active_runtime["source_set_sha256"]),
        "authority": dict(capacity.selfplay.AUTHORITY)}
    return {**body, "receipt_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}


def test_canary_requires_both_team_identities_not_strict_turn_alternation():
    result = canary_receipt(play_teams=(0, 1, 1, 0))
    assert validate_canary_receipt(result) == result["receipt_sha256"]

    forged = canary_receipt(play_teams=(0, 0, 0, 0))
    with pytest.raises(RPCCapacityError, match="contract derivation drift"):
        validate_canary_receipt(forged)


def test_canary_source_review_cannot_be_coordinately_rehashed_to_other_source():
    forged = canary_receipt()
    forged["source_review"]["review_claim"]["source_set_sha256"] = "e" * 64
    claim = forged["source_review"]["review_claim"]
    claim_body = {key: value for key, value in claim.items()
                  if key != "claim_sha256"}
    claim["claim_sha256"] = hashlib.sha256(
        canonical_json_bytes(claim_body)).hexdigest()
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="claim seal"):
        validate_canary_receipt(forged)


def test_capacity_rechecks_live_runtime_after_all_game_arms(
        tmp_path, monkeypatch):
    from shengji.rl import privileged_teacher_luna_rpc_supervisor as sup

    expected = runtime()
    changed = copy.deepcopy(expected)
    changed["codex_binary_sha256"] = "f" * 64
    seen = iter((expected, changed))
    review = source_review_auth(expected["source_set_sha256"])
    canary = canary_receipt()
    monkeypatch.setattr(capacity, "source_identity", lambda _path: next(seen))
    monkeypatch.setattr(capacity, "RealGameRunner", lambda **_kwargs: object())
    monkeypatch.setattr(capacity, "_derive_capacity",
                        lambda **_kwargs: {"would_publish": True})
    monkeypatch.setattr(sup, "source_review_claim",
                        lambda _repo: review["review_claim"])
    monkeypatch.setattr(sup, "authenticate_review_claim",
                        lambda **_kwargs: review)

    with pytest.raises(RPCCapacityError,
                       match="capacity terminal runtime drift"):
        capacity.run_capacity(
            canary_receipt=canary, capacity_secret=b"x" * 32,
            codex_binary=Path("/test/codex"), temp_root=tmp_path,
            per_call_timeout_seconds=90, runtime=expected,
            secret_commitment_sha256=hashlib.sha256(b"x" * 32).hexdigest(),
            source_review=review,
            per_game_deadline_ns=10_000_000_000,
            physical_memory_bytes=16 << 30,
            capacity_wall_ns=20_000_000_000,
            capacity_token_budget=1_000_000,
            scientific_wall_ns=100_000_000_000,
            scientific_token_budget=10_000_000)


def test_canary_rechecks_live_runtime_before_receipt_publication(
        tmp_path, monkeypatch):
    from scripts import privileged_teacher_luna_rpc_canary as canary_cli

    expected = runtime()
    changed = copy.deepcopy(expected)
    changed["source_set_sha256"] = "e" * 64
    seen = iter((expected, changed))
    review = source_review_auth(expected["source_set_sha256"])
    monkeypatch.setattr(canary_cli, "source_review_claim",
                        lambda _repo: review["review_claim"])
    monkeypatch.setattr(canary_cli, "authenticate_review_claim",
                        lambda **_kwargs: review)
    monkeypatch.setattr(canary_cli, "source_identity",
                        lambda _path: next(seen))
    monkeypatch.setattr(canary_cli, "_run_one",
                        lambda **kwargs: {"name": kwargs["name"]})
    output = tmp_path / "canary.json"

    with pytest.raises(ValueError, match="canary terminal runtime drift"):
        canary_cli.main([
            "--repo-root", str(tmp_path),
            "--source-review-commit", "1" * 40,
            "--codex-binary", "/test/codex",
            "--work-root", str(tmp_path / "work"),
            "--output", str(output),
        ])
    assert not output.exists()


class PassingRunner:
    def __init__(self, tracker):
        self.tracker = tracker
        self.barriers = {workers: threading.Barrier(workers)
                         for workers in (1, 2, 4, 6, 8)}

    def __call__(self, workers, worker, game):
        started = time.monotonic_ns()
        self.tracker.enter()
        try:
            self.barriers[workers].wait(timeout=2)
            time.sleep(0.01)
        finally:
            self.tracker.leave()
        wall = max(1, time.monotonic_ns() - started)
        return GameMetric(
            workers, worker, game, True, True, wall,
            1_000_000, 1_000_000, 0, 0, 0, 3,
            3, 10_000_000, 10_000_000,
            150, 100, 10, 0, 20, 5, 6_000, "a" * 64,
            hashlib.sha256(f"{workers}-{worker}-{game}".encode()).hexdigest())


def receipt(*, runner=None, tracker=None, capacity_token_budget=1_000_000):
    tracker = tracker or RPCConcurrency()
    runner = runner or PassingRunner(tracker)
    return capacity._derive_capacity(
        game_runner=runner, runtime=runtime(),
        secret_commitment_sha256="b" * 64,
        canary_receipt_sha256="c" * 64,
        source_review=source_review_auth(
            runtime()["source_set_sha256"]),
        per_game_deadline_ns=10_000_000_000,
        physical_memory_bytes=16 << 30,
        capacity_wall_ns=10_000_000_000,
        capacity_token_budget=capacity_token_budget,
        scientific_wall_ns=1_000_000_000_000,
        scientific_token_budget=1_000_000_000,
        concurrency=tracker)


def test_all_arms_pass_and_next_larger_rule_selects_a_supported_arm():
    result = receipt()
    assert result["route"] == ROUTE_PASS
    assert result["selected_workers"] in (1, 2, 4, 6)
    assert len(result["arms"]) == 5
    assert all(arm["passed"] for arm in result["arms"])
    validate_capacity_receipt(result)


def test_public_capacity_entry_refuses_unproven_canary_before_runner():
    calls = 0
    def runner(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("runner must not open")
    with pytest.raises(RPCCapacityError, match="canary receipt schema"):
        capacity.run_capacity(
            canary_receipt={}, capacity_secret=b"x" * 32,
            codex_binary=Path("/not/opened"), temp_root=Path("/not/opened"),
            per_call_timeout_seconds=90, runtime=runtime(),
            secret_commitment_sha256="b" * 64,
            source_review=source_review_auth(
                runtime()["source_set_sha256"]),
            per_game_deadline_ns=10_000_000_000,
            physical_memory_bytes=16 << 30,
            capacity_wall_ns=10_000_000_000,
            capacity_token_budget=1_000_000,
            scientific_wall_ns=1_000_000_000_000,
            scientific_token_budget=1_000_000_000)
    assert calls == 0


def test_public_capacity_entry_has_no_injected_runner_or_tracker_seam():
    parameters = inspect.signature(capacity.run_capacity).parameters
    assert "game_runner" not in parameters
    assert "concurrency" not in parameters


def test_tool_event_fails_first_arm_and_routes_resource_refusal():
    tracker = RPCConcurrency()
    passing = PassingRunner(tracker)
    def bad(workers, worker, game):
        row = passing(workers, worker, game)
        return GameMetric(**{
            **{name: getattr(row, name) for name in row.__dataclass_fields__},
            "tool_event_count": 1})
    result = receipt(runner=bad, tracker=tracker)
    assert result["route"] == ROUTE_REFUSE
    assert result["selected_workers"] is None
    assert len(result["arms"]) == 1
    assert result["arms"][0]["process_passed"] is False


def test_capacity_token_overrun_cannot_publish_a_passing_route():
    result = receipt(capacity_token_budget=300)
    assert result["stop_reason"] == "capacity-token-overrun"
    assert result["total_token_count"] > result["capacity_token_budget"]
    assert result["route"] == ROUTE_REFUSE
    assert result["selected_workers"] is None


def test_real_runner_snapshots_failed_journal_before_temp_cleanup(
        tmp_path, monkeypatch):
    seen_catalogs = []
    class RefusingTransport:
        def __init__(self, **kwargs):
            seen_catalogs.append(kwargs["runtime_attestor"](
                Path("/never-probed")))
        def call(self, _packet):
            raise CodexTurnTransportError("synthetic provider refusal")
    monkeypatch.setattr(
        capacity, "CodexExecPlannerTransport", RefusingTransport)
    tracker = RPCConcurrency()
    runner = capacity.RealGameRunner(
        capacity_secret=b"capacity-test-secret-32-bytes!!!",
        codex_binary=Path("/usr/bin/true"),
        temp_root=tmp_path, per_call_timeout_seconds=90,
        per_game_deadline_seconds=600, concurrency=tracker,
        runtime=runtime())
    metric = runner(1, 0, 0)
    assert metric.complete is False
    assert metric.process_errors == 1
    assert metric.input_tokens == metric.output_tokens == 0
    assert seen_catalogs == [runtime()["codex_tool_catalog"]]


@pytest.mark.parametrize("field", ["selected_workers", "total_token_count"])
def test_terminal_fields_cannot_be_rehashed_without_rederivation(field):
    result = receipt()
    forged = copy.deepcopy(result)
    forged[field] = 999
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        __import__("shengji.rl.privileged_teacher_pt0", fromlist=["canonical_json_bytes"])
        .canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="terminal derivation"):
        validate_capacity_receipt(forged)


def test_stop_reason_cannot_be_rehashed_around_the_wiring():
    result = receipt()
    forged = copy.deepcopy(result)
    forged["stop_reason"] = "arm-condition-failed"
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        __import__("shengji.rl.privileged_teacher_pt0", fromlist=["canonical_json_bytes"])
        .canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="stop-reason derivation"):
        validate_capacity_receipt(forged)


@pytest.mark.parametrize("field,value,match", [
    ("capacity_wall_nanoseconds", 1, "terminal derivation|stop-reason"),
    ("elapsed_nanoseconds", 1, "elapsed derivation"),
])
def test_scalar_budget_and_elapsed_forgery_refuses(field, value, match):
    result = receipt()
    forged = copy.deepcopy(result)
    forged[field] = value
    body = {key: item for key, item in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match=match):
        validate_capacity_receipt(forged)


def test_nonproduction_runtime_schema_cannot_be_rehashed_in():
    result = receipt()
    forged = copy.deepcopy(result)
    forged["runtime"] = {"schema": "test-runtime-v1"}
    body = {key: item for key, item in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="runtime drift"):
        validate_capacity_receipt(forged)
