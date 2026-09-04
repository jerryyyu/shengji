"""Progressive capacity and receipt rederivation witnesses."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import threading
import time

import pytest

from shengji.rl import privileged_teacher_luna_rpc_capacity as capacity
from shengji.rl.privileged_teacher_luna_rpc_transport import (
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
    ROUTE_FULL,
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
        "design_sha256s": {
            "PRIVILEGED_TEACHER_LUNA_SELFPLAY_DESIGN.md": "d" * 64,
            "PRIVILEGED_TEACHER_LUNA_PLAY_ONLY_DESIGN.md": "e" * 64,
        },
        "score_free_canary_authorized": True,
        "score_free_capacity_authorized": True,
        "scientific_execution_authorized": False,
        "outcome_opening_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "strength_claim_authorized": False,
        "authority": dict(capacity.selfplay.AUTHORITY),
    }
    claim_body["design_sha256"] = hashlib.sha256(canonical_json_bytes(
        claim_body["design_sha256s"])).hexdigest()
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
                         for workers in capacity.WORKER_ARMS}

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


def receipt(*, runner=None, tracker=None, capacity_token_budget=1_000_000,
            scientific_token_budget=1_000_000_000,
            per_game_deadline_ns=1_200_000_000_000):
    tracker = tracker or RPCConcurrency()
    runner = runner or PassingRunner(tracker)
    return capacity._derive_capacity(
        game_runner=runner, runtime=runtime(),
        secret_commitment_sha256="b" * 64,
        canary_receipt_sha256="c" * 64,
        source_review=source_review_auth(
            runtime()["source_set_sha256"]),
        per_game_deadline_ns=per_game_deadline_ns,
        physical_memory_bytes=16 << 30,
        capacity_wall_ns=10_000_000_000,
        capacity_token_budget=capacity_token_budget,
        scientific_wall_ns=1_000_000_000_000,
        scientific_token_budget=scientific_token_budget,
        concurrency=tracker)


class FixedMetricRunner(PassingRunner):
    def __init__(self, tracker, *, wall_nanoseconds, token_count=250,
                 mutate=None):
        super().__init__(tracker)
        self.wall_nanoseconds = wall_nanoseconds
        self.token_count = token_count
        self.mutate = mutate

    def __call__(self, workers, worker, game):
        row = super().__call__(workers, worker, game)
        output_tokens = self.token_count // 2
        row = replace(
            row, wall_nanoseconds=self.wall_nanoseconds,
            input_tokens=self.token_count - output_tokens,
            output_tokens=output_tokens)
        if self.mutate is not None:
            row = self.mutate(row, workers, worker, game)
        return row


def route_decision(*, wall_nanoseconds, token_count=2_000,
                   arm_four_passed=True, scientific_token_budget=1_000_000_000):
    """Exercise the pure route boundary without timing-sensitive arm setup."""
    arms = [
        {"workers": 1, "passed": True,
         "p95_game_wall_nanoseconds": wall_nanoseconds,
         "aggregate_token_count": token_count // 4},
        {"workers": 4, "passed": arm_four_passed,
         "p95_game_wall_nanoseconds": wall_nanoseconds,
         "aggregate_token_count": token_count},
    ]
    return capacity._route_decision(
        arms=arms, total_tokens=token_count,
        capacity_token_budget=1_000_000,
        stop_reason="none",
        scientific_token_budget=scientific_token_budget)


@pytest.mark.parametrize("wall,expected", [
    (capacity.FULL_P95_LIMIT_NS, capacity.ROUTE_FULL),
    (capacity.FULL_P95_LIMIT_NS + 1, capacity.ROUTE_PILOT),
])
def test_full_p95_boundary_uses_integer_route_threshold(wall, expected):
    result = route_decision(wall_nanoseconds=wall)
    assert result["route"] == expected
    assert result["projected_full_wall_nanoseconds"] == \
        capacity._population_projection(wall, 104, 4, 2_000, 8)[0]


@pytest.mark.parametrize("wall,expected", [
    (capacity.PILOT_P95_LIMIT_NS, capacity.ROUTE_PILOT),
    (capacity.PILOT_P95_LIMIT_NS + 1, capacity.ROUTE_REFUSE),
])
def test_pilot_p95_boundary_and_projection_use_integer_nanoseconds(wall,
                                                                    expected):
    result = route_decision(wall_nanoseconds=wall)
    assert result["route"] == expected
    assert result["projected_pilot_wall_nanoseconds"] == \
        capacity._population_projection(wall, 32, 4, 2_000, 8)[0]


@pytest.mark.parametrize("budget,expected", [
    (10_000, capacity.ROUTE_PILOT),
    (9_999, capacity.ROUTE_REFUSE),
])
def test_pilot_token_projection_boundary_is_route_gating(budget, expected):
    result = route_decision(
        wall_nanoseconds=900_000_000_000,
        scientific_token_budget=budget)
    assert result["route"] == expected
    assert result["projected_pilot_token_count"] == 10_000


def test_route_never_falls_back_to_pilot_when_arm_four_health_fails():
    result = route_decision(
        wall_nanoseconds=900_000_000_000,
        arm_four_passed=False)
    assert result["route"] == capacity.ROUTE_REFUSE
    assert result["selected_workers"] is None


def test_exhausted_packet_fails_arm_health_before_any_route_selection():
    tracker = RPCConcurrency()
    passing = PassingRunner(tracker)

    def exhausted(workers, worker, game):
        return replace(passing(workers, worker, game), exhaustion_count=1)

    result = receipt(runner=exhausted, tracker=tracker)
    assert result["route"] == capacity.ROUTE_REFUSE
    assert len(result["arms"]) == 1
    assert result["arms"][0]["exhaustion_passed"] is False
    assert result["arms"][0]["passed"] is False
    validate_capacity_receipt(result)


@pytest.mark.parametrize("field", [
    "route", "selected_game_count", "selected_deal_cluster_count",
    "selected_population_wall_nanoseconds",
    "projected_full_wall_nanoseconds", "projected_full_token_count",
    "projected_pilot_wall_nanoseconds", "projected_pilot_token_count",
])
def test_route_fields_cannot_be_rehashed_without_rederivation(field):
    result = receipt()
    forged = copy.deepcopy(result)
    forged[field] = capacity.ROUTE_REFUSE if field == "route" else 1
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="terminal derivation"):
        validate_capacity_receipt(forged)


def test_old_capacity_schema_cannot_reopen_after_rehash():
    result = receipt()
    forged = copy.deepcopy(result)
    forged["schema"] = "pt-luna-turn-rpc-capacity-v3"
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="receipt schema"):
        validate_capacity_receipt(forged)


def test_source_review_design_hashes_are_sealed():
    result = receipt()
    forged = copy.deepcopy(result)
    claim = forged["source_review"]["review_claim"]
    claim["design_sha256s"]["PRIVILEGED_TEACHER_LUNA_PLAY_ONLY_DESIGN.md"] = \
        "f" * 64
    claim_body = {key: value for key, value in claim.items()
                  if key != "claim_sha256"}
    claim["claim_sha256"] = hashlib.sha256(
        canonical_json_bytes(claim_body)).hexdigest()
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="claim seal"):
        validate_capacity_receipt(forged)


def test_retry_receipt_aggregation_is_derived_and_zeroing_it_refuses():
    result = receipt()
    expected_physical = sum(
        row["physical_attempt_count"]
        for arm in result["arms"] for row in arm["metrics"])
    assert result["physical_attempt_count"] == expected_physical
    assert result["redispatch_count"] == 0
    assert result["exhaustion_count"] == 0
    forged = copy.deepcopy(result)
    forged["physical_attempt_count"] = 0
    body = {key: value for key, value in forged.items()
            if key != "receipt_sha256"}
    forged["receipt_sha256"] = hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()
    with pytest.raises(RPCCapacityError, match="retry terminal derivation"):
        validate_capacity_receipt(forged)


def test_retry_receipt_aggregation_preserves_exact_metric_totals():
    tracker = RPCConcurrency()
    base = PassingRunner(tracker)

    def retry_runner(workers, worker, game):
        row = base(workers, worker, game)
        return replace(
            row, physical_attempt_count=row.rpc_count,
            first_attempt_failure_by_class={"completion-telemetry-drift": 1},
            redispatch_count=1, retry_wall_nanoseconds=7_000_000,
            retry_token_count=90)

    result = receipt(runner=retry_runner, tracker=tracker)
    metric_count = 2 * sum(capacity.WORKER_ARMS)
    assert result["physical_attempt_count"] == metric_count * 3
    assert result["redispatch_count"] == metric_count
    assert result["exhaustion_count"] == 0
    assert result["retry_wall_nanoseconds"] == metric_count * 7_000_000
    assert result["retry_token_count"] == metric_count * 90
    assert result["first_attempt_failure_by_class"] == {
        "completion-telemetry-drift": metric_count}
    validate_capacity_receipt(result)


def test_all_arms_pass_and_next_larger_rule_selects_a_supported_arm():
    result = receipt()
    assert result["route"] == ROUTE_FULL
    assert result["selected_workers"] == 4
    assert [arm["workers"] for arm in result["arms"]] == [1, 4]
    assert all(arm["passed"] for arm in result["arms"])
    validate_capacity_receipt(result)


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
