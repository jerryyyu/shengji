"""Can-fail tests for PT-Luna admission, capacity, and source collection."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from shengji.rl import privileged_teacher_luna_selfplay as luna
from shengji.rl import privileged_teacher_luna_selfplay_controller as controller
from shengji.rl import privileged_teacher_luna_selfplay_execution as execution
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


def _cli_module():
    spec = importlib.util.spec_from_file_location(
        "privileged_teacher_luna_selfplay_cli",
        Path(__file__).parents[1] / "scripts" /
        "privileged_teacher_luna_selfplay.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SECRET = b"luna-self-play-secret-material!!"
TOOL = Path(__file__).parents[1] / "scripts" / "privileged_teacher_luna_selfplay_tool.py"
MECHANICS = hashlib.sha256(b"fake-mechanics").hexdigest()


def _codex_stdout() -> bytes:
    return (json.dumps({"type": "thread.started", "thread_id": "fake"}) + "\n"
            + json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 10, "cached_input_tokens": 2,
                "cache_write_input_tokens": 1, "output_tokens": 3,
                "reasoning_output_tokens": 4}}) + "\n").encode()


def _metric(workers: int, worker: int, game: int) -> dict[str, object]:
    del worker, game
    return {"complete": True, "verified": True,
            "wall_nanoseconds": max(1, 8_000_000_000 // workers),
            "busy_cpu_nanoseconds": 1_000_000_000,
            "peak_rss_bytes": 1_000_000, "swap_bytes": 0,
            "process_errors": 0, "tool_calls": 4,
            "token_count": 10, "token_rate_milli": 10,
            "mechanics_sha256": MECHANICS}


def _fake_process(session, *, mailbox_path, final_output_path, **_kwargs):
    terminal = None
    while True:
        observed = execution.tool_request(mailbox_path, {"op": "observe"})
        if observed["status"] in ("round_end", "failed"):
            terminal = observed
            break
        if observed["status"] == "waiting":
            waited = execution.tool_request(mailbox_path, {"op": "wait"})
            if waited["status"] in ("round_end", "failed"):
                terminal = waited
                break
        else:
            played = execution.tool_request(mailbox_path, {
                "op": "play", "decision_sha256": observed["decision_sha256"],
                "candidate_index": 0, "confidence": "low"})
            if played["status"] in ("round_end", "failed"):
                terminal = played
                break
    assert terminal is not None and terminal["status"] == "round_end"
    final_output_path.write_bytes(canonical_json_bytes({
        "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
        "completion_token": terminal["completion_token"]}))
    return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())


class TinyDesign(luna.LunaDesign):
    """A type-safe five-mode fixture; production LunaDesign stays 52 clusters."""

    _coords = (("2", 0, 0), ("3", 0, 0), ("4", 0, 0),
               ("5", 1, 0), ("6", 1, 0))

    @property
    def root_coordinates(self):
        return self._coords

    @property
    def deal_clusters(self):
        return self._coords

    @property
    def mirror_assignments(self):
        # The controller tests exercise the one-game path; the production
        # constants and 104-game schedule remain covered by the core tests.
        return ((self._coords[0], 0),)

    def payload(self):
        base = super().payload()
        base.update({"trump_ranks": [row[0] for row in self._coords],
                     "banker_seats": [0, 1], "replicates": 1,
                     "deal_cluster_count": len(self._coords),
                     "game_count": len(self.mirror_assignments),
                     "mirror_count_per_cluster": 2})
        return base


def _tiny_census(design: TinyDesign) -> luna.RootCensus:
    rows = []
    for index, coordinate in enumerate(design.root_coordinates):
        root = luna.build_root(SECRET, coordinate)
        root_sha = luna.root_identity(root)
        rows.append({"coordinate": list(coordinate), "root_sha256": root_sha,
                     "mode": luna.TRUMP_MODES[index],
                     "mirror_root_sha256": root_sha})
    body = {"schema": luna.ROOT_CENSUS_SCHEMA,
            "seed_commitment_sha256": hashlib.sha256(SECRET).hexdigest(),
            "coordinates": rows, "coordinate_count": len(rows),
            "mode_count": len(luna.TRUMP_MODES), "authority": dict(luna.AUTHORITY)}
    return luna.RootCensus(body, hashlib.sha256(canonical_json_bytes(body)).hexdigest())


def _capacity(*, one_arm: bool = False) -> controller.CapacityReceipt:
    def runner(workers, worker, game):
        value = _metric(workers, worker, game)
        if one_arm and workers == 2:
            value["peak_rss_bytes"] = 8_000_000_000
        return value
    return controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000, game_runner=runner)


def _verified_capacity_fixture(*, one_arm: bool = False) -> controller.CapacityReceipt:
    """Typed external receipt fixture; no synthetic receipt is relabelled."""
    source = _capacity(one_arm=one_arm).body
    body = {
        "schema": controller.CAPACITY_SCHEMA,
        "deadline_nanoseconds": source["deadline_nanoseconds"],
        "physical_memory_bytes": source["physical_memory_bytes"],
        "cumulative_wall_budget_nanoseconds": source[
            "cumulative_wall_budget_nanoseconds"],
        "cumulative_token_budget": source["cumulative_token_budget"],
        "arms": source["arms"],
        "selected_workers": source["selected_workers"],
        "stop_reason": source["stop_reason"],
        "route": source["route"],
        "authority": source["authority"],
        "execution_kind": controller.CAPACITY_EXECUTION_VERIFIED,
        "scientific_admissible": False,
    }
    tool_sha = hashlib.sha256(TOOL.read_bytes()).hexdigest()
    games = [{"workers": arm["workers"], "worker": worker, "game": game,
              "runtime_sha256": "a" * 64,
              "evidence_sha256": "b" * 64,
              "tool_script_sha256": tool_sha}
             for arm in source["arms"]
             for worker in range(arm["workers"])
             for game in range(2)]
    body["provenance"] = {
        "schema": controller.CAPACITY_PROVENANCE_SCHEMA,
        "execution_kind": controller.CAPACITY_EXECUTION_VERIFIED,
        "scientific_admissible": False,
        "runtime_sha256": controller._sha(
            [game["runtime_sha256"] for game in games]),
        "evidence_sha256": controller._sha(
            [game["evidence_sha256"] for game in games]),
        "tool_script_sha256": tool_sha,
        "games": games,
    }
    return controller.CapacityReceipt(body, controller._sha(body))


def _reviewed_inputs(tmp_path, design, census, capacity, monkeypatch, *,
                     historical=False, current_variant=None):
    """Create a local bare GitHub-main stand-in with review line history."""
    tool = TOOL
    output_root = tmp_path
    freeze = controller.launch_freeze_payload(
        design=design, census=census, capacity=capacity, worker_count=1,
        output_root=output_root, tool_script=tool)
    claim = controller._review_claim(
        freeze=freeze, design=design, census=census, capacity=capacity,
        output_root=output_root, tool_script=tool)
    marker_prefix = controller.REVIEW_MARKER_PREFIX.encode("ascii")
    historical_markers = ()
    if historical:
        historical_claim = {**claim, "candidate_freeze_sha256": "0" * 64}
        historical_markers = (marker_prefix
                              + canonical_json_bytes(historical_claim),)
    source = tmp_path / "review-source"
    remote = tmp_path / "review-remote.git"
    source.mkdir()
    subprocess.run(("git", "init", str(source)), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(("git", "-C", str(source), "config", "user.name", "reviewer"),
                   check=True)
    subprocess.run(("git", "-C", str(source), "config", "user.email", "reviewer@example"),
                   check=True)
    marker = marker_prefix + canonical_json_bytes(claim)
    previous = b"review baseline\n" + b"".join(historical_markers)
    (source / "HANDOFF_REVIEW.md").write_bytes(previous)
    subprocess.run(("git", "-C", str(source), "add", "HANDOFF_REVIEW.md"),
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(("git", "-C", str(source), "commit", "-m", "review"),
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    current = previous + marker
    if current_variant == "replay":
        current = previous + historical_markers[-1]
    elif current_variant == "replacement":
        current = b"review baseline\n" + marker
    elif current_variant == "extra":
        current += b"extra suffix"
    (source / "HANDOFF_REVIEW.md").write_bytes(current)
    subprocess.run(("git", "-C", str(source), "add", "HANDOFF_REVIEW.md"),
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(("git", "-C", str(source), "commit", "-m", "external review"),
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    review_commit = subprocess.check_output(
        ("git", "-C", str(source), "rev-parse", "HEAD"), text=True).strip()
    subprocess.run(("git", "init", "--bare", str(remote)), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(("git", "-C", str(source), "remote", "add", "origin", str(remote)),
                   check=True)
    subprocess.run(("git", "-C", str(source), "push", "origin",
                    f"HEAD:refs/heads/main"), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    monkeypatch.setattr(controller, "CANONICAL_REMOTE_URL", str(remote))
    return freeze, review_commit


def test_capacity_stops_on_rss_and_never_reaches_larger_arm():
    calls = []

    def runner(workers, worker, game):
        calls.append((workers, worker, game))
        value = _metric(workers, worker, game)
        if workers == 2:
            value["peak_rss_bytes"] = 8_000_000_000
        return value

    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000, game_runner=runner)
    assert [arm["workers"] for arm in receipt.body["arms"]] == [1, 2]
    assert receipt.body["selected_workers"] == 1
    assert len(calls) == 2 + 4
    controller.validate_capacity_receipt(receipt)


def test_capacity_stops_on_process_and_deadline_conditions():
    for field in ("swap_bytes", "process_errors"):
        def runner(workers, worker, game, field=field):
            value = _metric(workers, worker, game)
            value[field] = 1
            return value
        receipt = controller.run_capacity(
            deadline_nanoseconds=1_000_000_000,
            physical_memory_bytes=8_000_000_000, game_runner=runner)
        assert len(receipt.body["arms"]) == 1
        assert receipt.body["selected_workers"] is None
    def late(workers, worker, game):
        value = _metric(workers, worker, game)
        value["wall_nanoseconds"] = 900_000_000
        return value
    receipt = controller.run_capacity(
        deadline_nanoseconds=1_000_000_000,
        physical_memory_bytes=8_000_000_000, game_runner=late)
    assert receipt.body["route"] == controller.CAPACITY_REFUSE_ROUTE


def test_capacity_stops_on_scaling_and_selects_fastest_passing_arm():
    def runner(workers, worker, game):
        value = _metric(workers, worker, game)
        if workers == 2:
            time.sleep(0.01)
        return value
    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000, game_runner=runner)
    assert [arm["workers"] for arm in receipt.body["arms"]] == [1, 2]
    # The earlier passing arm remains eligible because arm 2 is the larger
    # tested witness, while the final arm itself is never selectable.
    assert receipt.body["selected_workers"] == 1


def test_capacity_arms_are_concurrent_and_parallelism_is_empirical(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()
    start_barriers = {workers: threading.Barrier(workers)
                      for workers in controller.CAPACITY_WORKERS if workers > 1}
    active_barriers = {workers: threading.Barrier(workers)
                       for workers in controller.CAPACITY_WORKERS if workers > 1}

    # Keep the scheduler/worker witness real, but make the receipt's wall
    # arithmetic independent of host load.  Each arm still has one executor
    # thread per worker and the second barrier proves all workers overlap
    # while active; only the controller clock is deterministic.
    monkeypatch.setattr(
        controller.time, "monotonic_ns",
        _controlled_arm_clock(*((500_000_000,) * len(controller.CAPACITY_WORKERS))))

    def runner(workers, worker, game):
        nonlocal active, peak
        if workers > 1:
            start_barriers[workers].wait(timeout=2)
        with lock:
            active += 1
            peak = max(peak, active)
        if workers > 1:
            active_barriers[workers].wait(timeout=2)
        with lock:
            active -= 1
        value = _metric(workers, worker, game)
        return value

    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000, game_runner=runner)
    assert peak > 1
    assert receipt.body["arms"][-1]["workers"] == 8
    assert receipt.body["arms"][-1]["aggregate_token_rate_milli"] == 80
    assert receipt.body["arms"][-1]["observed_parallelism_milli"] >= 700 * 8


def test_capacity_budget_stops_before_next_arm_and_is_bound_in_receipt():
    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000,
        cumulative_wall_budget_nanoseconds=10_000_000_000,
        cumulative_token_budget=20, game_runner=_metric)
    assert [arm["workers"] for arm in receipt.body["arms"]] == [1]
    assert receipt.body["stop_reason"] == "cumulative_token_budget_before_arm"
    controller.validate_capacity_receipt(receipt)


def test_real_capacity_uses_live_execution_meter_and_refuses_zero_measurement(
        tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "CAPACITY_WORKERS", (1,))
    issued = []

    class Meter:
        def __init__(self):
            self.value = {"schema": execution.RESOURCE_SCHEMA,
                          "busy_cpu_nanoseconds": 100,
                          "peak_rss_bytes": 200, "swap_bytes": 0,
                          "sample_count": 2}
        def close(self):
            return dict(self.value)

    meters = []
    def meter_factory():
        meter = Meter()
        meters.append(meter)
        return meter
    monkeypatch.setattr(execution, "ProcessTreeResourceMeter", meter_factory)

    def run(game, *, private_root, resource_meter, **_kwargs):
        issued.append(resource_meter)
        return SimpleNamespace(attempt_path=private_root / "sealed")
    monkeypatch.setattr(execution, "run_luna_game", run)
    evidence = SimpleNamespace(body={
        "codex_usage": {"cached_input_tokens": 1, "input_tokens": 2,
                        "cache_write_input_tokens": 0, "output_tokens": 3,
                        "reasoning_output_tokens": 4},
        "trace": [{"request": {"op": "observe"}}],
        "runtime": {"codex": "fixture"}, "process_error": None,
        "execution_kind": execution.PRODUCTION_EXECUTION_KIND,
        "actual_subprocess": True, "synthetic": False})
    evidence.sha256 = controller._sha(evidence.body)
    monkeypatch.setattr(execution, "reopen_attempt", lambda _path:
                        SimpleNamespace(status="complete",
                                        evidence=(evidence, evidence),
                                        scientific_admissible=True))
    receipt = controller.run_real_capacity(
        capacity_secret=SECRET, tool_script=TOOL,
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000)
    assert receipt.body["selected_workers"] is None
    assert receipt.body["execution_kind"] == controller.CAPACITY_EXECUTION_VERIFIED
    assert receipt.body["scientific_admissible"] is False
    assert len(issued) == 2 and issued == meters
    assert receipt.body["arms"][0]["aggregate_busy_cpu_nanoseconds"] == 200

    meters.clear()
    issued.clear()
    def zero_meter_factory():
        meter = Meter()
        meter.value["peak_rss_bytes"] = 0
        return meter
    monkeypatch.setattr(execution, "ProcessTreeResourceMeter",
                        zero_meter_factory)
    with pytest.raises(controller.ControllerError, match="process RSS"):
        controller.run_real_capacity(
            capacity_secret=SECRET, tool_script=TOOL,
            deadline_nanoseconds=1200 * 1_000_000_000,
            physical_memory_bytes=8_000_000_000)


def test_real_capacity_refusal_is_typed_and_redacted_after_temp_cleanup(
        tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "CAPACITY_WORKERS", (1,))
    roots = []

    class Meter:
        def close(self):
            return {"schema": execution.RESOURCE_SCHEMA,
                    "busy_cpu_nanoseconds": 1,
                    "peak_rss_bytes": 2, "swap_bytes": 0,
                    "sample_count": 1}

    monkeypatch.setattr(execution, "ProcessTreeResourceMeter", Meter)

    def run(game, *, private_root, **_kwargs):
        roots.append(Path(private_root))
        return SimpleNamespace(attempt_path=Path(private_root) / "sealed")

    monkeypatch.setattr(execution, "run_luna_game", run)
    evidence = SimpleNamespace(
        team=0,
        body={"execution_kind": execution.PRODUCTION_EXECUTION_KIND,
              "actual_subprocess": True, "synthetic": False,
              "process_error": None})
    monkeypatch.setattr(
        execution, "reopen_attempt",
        lambda _path: SimpleNamespace(status="incomplete",
                                       evidence=(evidence,)))

    with pytest.raises(controller.CapacityEvidenceRefusal) as caught:
        controller.run_real_capacity(
            capacity_secret=SECRET, tool_script=TOOL,
            deadline_nanoseconds=1200 * 1_000_000_000,
            physical_memory_bytes=8_000_000_000)
    refusal = caught.value
    assert refusal.body == {
        "schema": controller.CAPACITY_FAILURE_SCHEMA,
        "failure_kind": "evidence",
        "coordinate": ["2", 0, 0], "workers": 1, "worker": 0, "game": 0,
        "reopened_status": "incomplete", "reopen_failure_code": None,
        "evidence_count": 1,
        "expected_team_count": 2,
        "evidence_classification": [{
            "team": 0,
            "execution_kind": execution.PRODUCTION_EXECUTION_KIND,
            "actual_subprocess": True, "synthetic": False,
            "process_error_present": False,
            "process_returncode": None, "process_error": None,
            "codex_event_type_counts": {"opaque": 1},
            "codex_item_type_counts": {"opaque": 1},
            "codex_item_status_counts": {"opaque": 1},
            "final_output_present": False,
            "trace_operation_counts": {"other": 1},
            "stdout_sha256": None, "output_sha256": None,
        }],
        "scientific_admissible": False, "collection_authorized": False,
        "opened": {"outcomes": False, "actions": False,
                    "trajectories": False, "model_prose": False},
        "retained": {"outcomes": False, "actions": False,
                      "trajectories": False, "model_prose": False},
        "authority": {key: False for key in luna.AUTHORITY},
    }
    payload = refusal.serialized()
    assert payload["diagnostic_sha256"] == controller._sha(refusal.body)
    assert not roots[0].exists()

    def raising(error):
        def reopen(_path):
            raise error
        return reopen

    for error, expected_code in (
            (execution.LunaExecutionError("manifest hash drift"),
             "manifest_hash_drift"),
            (execution.LunaExecutionError("unreviewed private /tmp/secret"),
             "luna_execution_other"),
            (RuntimeError("private model prose /tmp/secret"),
             "unexpected_exception")):
        monkeypatch.setattr(execution, "reopen_attempt", raising(error))
        with pytest.raises(controller.CapacityEvidenceRefusal) as caught:
            controller.run_real_capacity(
                capacity_secret=SECRET, tool_script=TOOL,
                deadline_nanoseconds=1200 * 1_000_000_000,
                physical_memory_bytes=8_000_000_000)
        refusal = caught.value
        assert refusal.body["reopen_failure_code"] == expected_code
        assert refusal.body["evidence_classification"] == []
        raw = refusal.canonical_bytes()
        assert b"private model prose" not in raw
        assert b"unreviewed private" not in raw
        assert b"/tmp/secret" not in raw
        assert roots[-1].exists() is False


def test_capacity_failure_reopen_code_validation_is_strict():
    refusal = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status=None, evidence=(), failure_kind="reopen_failure",
        reopen_failure_code="manifest_hash_drift")
    for bad in (None, "raw exception", 1):
        body = dict(refusal.body)
        body["reopen_failure_code"] = bad
        with pytest.raises(controller.ControllerError,
                           match="reopen code drift"):
            controller._validate_capacity_failure_body(body)
    body = dict(refusal.body)
    body["failure_kind"] = "evidence"
    body["reopen_failure_code"] = "manifest_hash_drift"
    with pytest.raises(controller.ControllerError, match="reopen code drift"):
        controller._validate_capacity_failure_body(body)


def test_capacity_failure_process_diagnostic_is_bounded_and_distinguishable():
    secret = b"MODEL PROSE SECRET"
    stdout = (json.dumps({"type": "thread.started", "message":
                          secret.decode()}) + "\n"
              + json.dumps({"type": "turn.completed", "item": {
                  "text": secret.decode()}}) + "\n").encode()
    evidence = SimpleNamespace(team=0, body={
        "execution_kind": execution.PRODUCTION_EXECUTION_KIND,
        "actual_subprocess": True, "synthetic": False,
        "process_returncode": 7,
        "process_error": "Luna model process did not complete engine round",
        "stdout_base64": base64.b64encode(stdout).decode(),
        "final_base64": base64.b64encode(secret).decode(),
        "output_sha256": "a" * 64,
        "trace": [{"request": {"op": "observe", "secret": secret.decode()},
                   "response": {"text": secret.decode()}}],
    })
    refusal = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status="incomplete", evidence=(evidence,))
    diagnostic = refusal.body["evidence_classification"][0]
    assert diagnostic["process_returncode"] == 7
    assert diagnostic["process_error"] == (
        "Luna model process did not complete engine round")
    assert diagnostic["codex_event_type_counts"] == {
        "thread.started": 1, "turn.completed": 1}
    assert diagnostic["final_output_present"] is True
    assert diagnostic["trace_operation_counts"] == {"observe": 1}
    assert secret not in refusal.canonical_bytes()
    public_failure = refusal.canonical_bytes()
    for private_key in (b"stop_hook", b"config_override", b"script_path",
                        b"completion_token"):
        assert private_key not in public_failure

    evidence.body["process_error"] = (
        "Luna terminal mailbox witness absent or malformed")
    terminal = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status="incomplete", evidence=(evidence,))
    assert terminal.body["evidence_classification"][0]["process_error"] == (
        "Luna terminal mailbox witness absent or malformed")

    evidence.body["process_error"] = "provider leaked: " + secret.decode()
    opaque = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status="incomplete", evidence=(evidence,))
    assert opaque.body["evidence_classification"][0]["process_error"] == "other"


def test_capacity_failure_codex_item_telemetry_is_allowlisted_and_redacted():
    secret = "COMMAND SECRET MODEL PROSE"
    events = [
        {"type": "item.started", "item": {
            "id": "private-id", "type": "command_execution",
            "command": secret}},
        {"type": "item.completed", "item": {
            "id": "private-id", "type": "command_execution",
            "aggregated_output": secret}},
        {"type": "item.updated", "item": {
            "type": "future_item", "status": "future_status",
            "text": secret}},
        {"type": "item.completed", "item": {
            "type": [], "status": {}, "text": secret}},
        {"type": "future.event", "payload": secret},
    ]
    stdout = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
    evidence = SimpleNamespace(team=0, body={
        "execution_kind": execution.PRODUCTION_EXECUTION_KIND,
        "actual_subprocess": True, "synthetic": False,
        "process_returncode": 7,
        "process_error": "Luna model process did not complete engine round",
        "stdout_base64": base64.b64encode(stdout).decode(),
        "final_base64": base64.b64encode(secret.encode()).decode(),
        "output_sha256": "c" * 64, "trace": [],
    })
    refusal = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status="incomplete", evidence=(evidence,))
    diagnostic = refusal.body["evidence_classification"][0]
    assert diagnostic["codex_event_type_counts"] == {
        "item.completed": 2, "item.started": 1, "item.updated": 1,
        "opaque": 1}
    assert diagnostic["codex_item_type_counts"] == {
        "command_execution": 2, "opaque": 2}
    assert diagnostic["codex_item_status_counts"] == {
        "completed": 1, "started": 1, "opaque": 2}
    assert secret.encode() not in refusal.canonical_bytes()


def test_capacity_failure_malformed_stdout_is_opaque():
    evidence = SimpleNamespace(team=1, body={
        "execution_kind": execution.PRODUCTION_EXECUTION_KIND,
        "actual_subprocess": True, "synthetic": False,
        "process_returncode": None, "process_error": None,
        "stdout_base64": base64.b64encode(b"not JSONL").decode(),
        "final_base64": "", "output_sha256": "b" * 64,
        "trace": [],
    })
    refusal = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status="incomplete", evidence=(evidence,))
    diagnostic = refusal.body["evidence_classification"][0]
    assert diagnostic["codex_event_type_counts"] == {"opaque": 1}
    assert diagnostic["codex_item_type_counts"] == {"opaque": 1}
    assert diagnostic["codex_item_status_counts"] == {"opaque": 1}
    assert diagnostic["final_output_present"] is False
    assert refusal.body["scientific_admissible"] is False
    assert refusal.body["collection_authorized"] is False
    assert all(value is False for value in refusal.body["authority"].values())


def test_capacity_failure_publication_is_exclusive_and_one_link(tmp_path):
    def refusal(coordinate):
        return controller.CapacityEvidenceRefusal(
            coordinate=coordinate, workers=1, worker=0, game=0,
            reopened_status="incomplete", evidence=())

    output = tmp_path / "failure.json"
    first = refusal(("2", 0, 0))
    second = refusal(("2", 0, 1))
    barrier = threading.Barrier(2)
    results = []

    def publish(item):
        barrier.wait()
        try:
            results.append(controller.publish_capacity_failure(output, item))
        except controller.ControllerError:
            results.append(None)

    threads = [threading.Thread(target=publish, args=(item,))
               for item in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(value is not None for value in results) == [False, True]
    assert stat.S_IMODE(output.stat().st_mode) == 0o400
    assert output.stat().st_nlink == 1
    winning = output.read_bytes()
    assert winning in (first.canonical_bytes(), second.canonical_bytes())
    assert controller.publish_capacity_failure(output, first if winning == first.canonical_bytes()
                                               else second) == controller._sha_bytes(winning)
    assert output.read_bytes() == winning

    link = tmp_path / "failure-link.json"
    link.symlink_to(output)
    with pytest.raises(controller.ControllerError, match="occupied"):
        controller.publish_capacity_failure(link, first)


def test_capacity_failure_preinstall_error_leaves_no_partial_final(tmp_path,
                                                                    monkeypatch):
    output = tmp_path / "failure.json"
    refusal = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status="incomplete", evidence=())

    def fail_install(source, destination):
        assert Path(source).parent == output.parent
        assert destination == output
        assert not output.exists()
        raise OSError("injected install failure")

    monkeypatch.setattr(controller, "_rename_noreplace", fail_install)
    with pytest.raises(OSError, match="injected install failure"):
        controller.publish_capacity_failure(output, refusal)
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_noreplace_install_refuses_destination_race(tmp_path):
    source = tmp_path / "complete.tmp"
    destination = tmp_path / "failure.json"
    source.write_bytes(b"complete")
    destination.write_bytes(b"prior-writer")
    with pytest.raises(FileExistsError):
        controller._rename_noreplace(source, destination)
    assert source.read_bytes() == b"complete"
    assert destination.read_bytes() == b"prior-writer"


def test_cli_real_failure_publishes_diagnostic_and_fake_does_not(tmp_path,
                                                                 monkeypatch):
    cli = _cli_module()
    secret = tmp_path / "secret"
    secret.write_bytes(SECRET)
    failure = tmp_path / "failure.json"
    output = tmp_path / "capacity.json"
    refusal = controller.CapacityEvidenceRefusal(
        coordinate=("2", 0, 0), workers=1, worker=0, game=0,
        reopened_status="incomplete", evidence=())
    monkeypatch.setattr(cli.controller, "run_real_capacity",
                        lambda **_kwargs: (_ for _ in ()).throw(refusal))
    assert cli.main(["capacity", "--secret-file", str(secret),
                     "--tool-script", str(TOOL), "--output", str(output),
                     "--failure-output", str(failure),
                     "--physical-memory-bytes", "8000000000"]) == 2
    assert failure.read_bytes() == refusal.canonical_bytes()
    assert not output.exists()

    fake_failure = tmp_path / "fake-failure.json"
    fake_output = tmp_path / "fake-capacity.json"
    assert cli.main(["capacity", "--fake", "--output", str(fake_output),
                     "--failure-output", str(fake_failure),
                     "--physical-memory-bytes", "8000000000"]) == 0
    assert fake_output.exists()
    assert not fake_failure.exists()


def test_public_capacity_api_cannot_issue_verified_runtime_or_science():
    with pytest.raises(TypeError):
        controller.run_capacity(
            deadline_nanoseconds=1200 * 1_000_000_000,
            physical_memory_bytes=8_000_000_000, game_runner=_metric,
            synthetic=False)
    with pytest.raises(TypeError):
        controller.run_capacity(
            deadline_nanoseconds=1200 * 1_000_000_000,
            physical_memory_bytes=8_000_000_000, game_runner=_metric,
            provenance_factory=lambda: {})
    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000, game_runner=_metric)
    assert receipt.body["execution_kind"] == controller.CAPACITY_EXECUTION_SYNTHETIC
    assert receipt.body["scientific_admissible"] is False


def test_removed_provider_capacity_argument_and_metric_field_are_rejected():
    with pytest.raises(TypeError):
        controller.run_real_capacity(
            capacity_secret=SECRET, tool_script=TOOL,
            deadline_nanoseconds=1200 * 1_000_000_000,
            physical_memory_bytes=8_000_000_000,
            provider_capacity_rate_milli=1 << 60)
    forged = _metric(1, 0, 0)
    forged["provider_capacity_rate_milli"] = 1 << 60
    with pytest.raises(controller.ControllerError, match="metric schema"):
        controller.run_capacity(
            deadline_nanoseconds=1200 * 1_000_000_000,
            physical_memory_bytes=8_000_000_000,
            game_runner=lambda *_args: forged)


def _overlap_runner(*, serialized: bool = False, incomplete: bool = False):
    lock = threading.Lock()
    barriers = {workers: threading.Barrier(workers)
                for workers in controller.CAPACITY_WORKERS if workers > 1}

    def runner(workers, worker, game):
        if workers > 1:
            barriers[workers].wait(timeout=2)
        if serialized:
            with lock:
                time.sleep(0.2)
        else:
            time.sleep(0.2)
        value = _metric(workers, worker, game)
        value["wall_nanoseconds"] = 200_000_000
        if incomplete:
            value["complete"] = False
            value["verified"] = False
            value["process_errors"] = 1
        return value
    return runner


def _controlled_arm_clock(*durations_nanoseconds: int):
    """Return deterministic start/finish pairs for successive capacity arms.

    The overlap witnesses below still use real barriers and threads to prove
    concurrent scheduling.  Their receipt arithmetic must not, however,
    depend on unrelated load on the host running the test suite.
    """
    readings = []
    now = 1_000_000_000
    for duration in durations_nanoseconds:
        readings.extend((now, now + duration))
        now += duration + 1_000_000
    iterator = iter(readings)
    return lambda: next(iterator)


def test_barrier_backed_overlap_passes_empirical_concurrency(monkeypatch):
    monkeypatch.setattr(controller, "CAPACITY_WORKERS", (1, 2))
    monkeypatch.setattr(
        controller.time, "monotonic_ns",
        _controlled_arm_clock(500_000_000, 500_000_000))
    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000,
        game_runner=_overlap_runner())
    assert receipt.body["arms"][-1]["parallelism_passed"] is True
    assert receipt.body["selected_workers"] == 1


def test_serialized_probe_fails_empirical_concurrency_and_admits_none(monkeypatch):
    monkeypatch.setattr(controller, "CAPACITY_WORKERS", (1, 2))
    monkeypatch.setattr(
        controller.time, "monotonic_ns",
        _controlled_arm_clock(500_000_000, 1_000_000_000))
    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000,
        game_runner=_overlap_runner(serialized=True))
    assert receipt.body["arms"][-1]["parallelism_passed"] is False
    assert receipt.body["selected_workers"] is None


def test_process_failure_or_incomplete_probe_fails_and_admits_none(monkeypatch):
    monkeypatch.setattr(controller, "CAPACITY_WORKERS", (1, 2))
    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000,
        game_runner=_overlap_runner(incomplete=True))
    assert receipt.body["arms"][0]["complete_passed"] is False
    assert receipt.body["arms"][0]["process_passed"] is False
    assert receipt.body["selected_workers"] is None


def test_passing_eight_selects_at_most_six(monkeypatch):
    monkeypatch.setattr(
        controller.time, "monotonic_ns",
        _controlled_arm_clock(*((500_000_000,) * 5)))
    receipt = controller.run_capacity(
        deadline_nanoseconds=1200 * 1_000_000_000,
        physical_memory_bytes=8_000_000_000,
        game_runner=_overlap_runner())
    assert receipt.body["arms"][-1]["workers"] == 8
    assert receipt.body["arms"][-1]["passed"] is True
    assert receipt.body["selected_workers"] <= 6


def test_verified_capacity_requires_one_provenance_row_per_measured_game():
    payload = _verified_capacity_fixture(one_arm=True).serialized()
    payload["provenance"]["games"].pop()
    games = payload["provenance"]["games"]
    payload["provenance"]["runtime_sha256"] = controller._sha(
        [game["runtime_sha256"] for game in games])
    payload["provenance"]["evidence_sha256"] = controller._sha(
        [game["evidence_sha256"] for game in games])
    body = {key: value for key, value in payload.items()
            if key != "receipt_sha256"}
    payload["receipt_sha256"] = controller._sha(body)
    with pytest.raises(controller.ControllerError, match="evidence population"):
        controller.CapacityReceipt.reopen(payload)


def test_population_admission_requires_capacity_and_census_before_runner(tmp_path):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    calls = []
    def runner(_game, _root):
        calls.append(1)
        raise AssertionError("runner must not be called")
    with pytest.raises(controller.ControllerError, match="capacity"):
        controller.run_source_population(
            design=design, seed_secret=SECRET, census=census,
            capacity={}, evidence_root=tmp_path, game_runner=runner)
    assert calls == []
    forged = census.serialized()
    forged["coordinates"] = list(forged["coordinates"])
    forged["coordinates"][0] = dict(forged["coordinates"][0])
    forged["coordinates"][0]["root_sha256"] = "f" * 64
    forged_body = {key: value for key, value in forged.items()
                   if key != "census_sha256"}
    forged["census_sha256"] = hashlib.sha256(
        canonical_json_bytes(forged_body)).hexdigest()
    with pytest.raises(controller.ControllerError, match="census admission"):
        controller.run_source_population(
            design=design, seed_secret=SECRET, census=forged,
            capacity=_capacity(), evidence_root=tmp_path, game_runner=runner)
    assert calls == []
    with pytest.raises(controller.ControllerError, match="capacity admission"):
        controller.run_source_population(
            design=design, seed_secret=SECRET, census=census,
            capacity=_capacity(), evidence_root=tmp_path, game_runner=runner)
    assert calls == []


def test_candidate_freeze_and_direct_controller_omission_cannot_admit(tmp_path,
                                                                       monkeypatch):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze = controller.launch_freeze_payload(
        design=design, census=census, capacity=capacity, worker_count=1,
        output_root=tmp_path, tool_script=TOOL)
    assert freeze["authenticated"] is False
    assert freeze["scientific_execution_authorized"] is False
    with pytest.raises(controller.ControllerError, match="review admission"):
        controller.run_source_population(
            design=design, seed_secret=SECRET, census=census,
            capacity=capacity, evidence_root=tmp_path,
            game_runner=lambda *_: None, worker_count=1)

    relabelled = _capacity(one_arm=True)
    relabelled_payload = relabelled.serialized()
    relabelled_payload["execution_kind"] = controller.CAPACITY_EXECUTION_VERIFIED
    relabelled_payload["scientific_admissible"] = True
    relabelled_payload["provenance"] = {
        "schema": controller.CAPACITY_PROVENANCE_SCHEMA,
        "execution_kind": controller.CAPACITY_EXECUTION_VERIFIED,
        "scientific_admissible": True,
        "runtime_sha256": "c" * 64,
        "evidence_sha256": "d" * 64,
        "tool_script_sha256": "e" * 64,
    }
    relabelled_body = {key: value for key, value in relabelled_payload.items()
                       if key != "receipt_sha256"}
    relabelled_payload["receipt_sha256"] = controller._sha(relabelled_body)
    with pytest.raises(controller.ControllerError, match="provenance"):
        controller.CapacityReceipt.reopen(relabelled_payload)


def test_source_review_allows_a_distinct_marker_appended_to_history(
        tmp_path, monkeypatch):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze, review_commit = _reviewed_inputs(
        tmp_path, design, census, capacity, monkeypatch, historical=True)
    review = controller.authenticate_source_review(
        freeze=freeze, design=design, census=census, capacity=capacity,
        output_root=tmp_path, tool_script=TOOL, review_commit=review_commit,
        repo_root=tmp_path)
    expected = controller._review_claim(
        freeze=freeze, design=design, census=census, capacity=capacity,
        output_root=tmp_path, tool_script=TOOL)
    assert review["review_claim"] == expected


@pytest.mark.parametrize("variant", ("replay", "replacement", "extra"))
def test_source_review_rejects_non_append_only_marker_history(
        tmp_path, monkeypatch, variant):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze, review_commit = _reviewed_inputs(
        tmp_path, design, census, capacity, monkeypatch,
        historical=True, current_variant=variant)
    with pytest.raises(controller.ControllerError, match="review marker commit"):
        controller.authenticate_source_review(
            freeze=freeze, design=design, census=census, capacity=capacity,
            output_root=tmp_path, tool_script=TOOL, review_commit=review_commit,
            repo_root=tmp_path)


@pytest.mark.parametrize("relative", controller.SOURCE_CLOSURE)
def test_review_binding_closes_complete_source_before_admission(
        tmp_path, monkeypatch, relative):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze, review_commit = _reviewed_inputs(tmp_path, design, census, capacity,
                                             monkeypatch)
    target = Path(__file__).parents[1] / relative
    original = Path.read_bytes

    def altered(path):
        raw = original(path)
        return raw + b"\n# source-closure mutation\n" if path == target else raw

    monkeypatch.setattr(Path, "read_bytes", altered)
    calls = []
    with pytest.raises(controller.ControllerError, match="freeze binding"):
        controller.run_source_population(
            design=design, seed_secret=SECRET, census=census,
            capacity=capacity, evidence_root=tmp_path,
            game_runner=lambda *_args: calls.append(1), worker_count=1,
            candidate_freeze=freeze, review_commit=review_commit,
            repo_root=tmp_path, tool_script=TOOL)
    assert calls == []
    assert not (tmp_path / "population-admission.json").exists()


def test_source_review_refuses_unbound_fast_runtime(monkeypatch):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    with pytest.raises(controller.ControllerError, match="pure Python engine"):
        controller._source_sha256()


def test_population_preseal_failure_publishes_missing_terminal_report(tmp_path, monkeypatch):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze, review_commit = _reviewed_inputs(tmp_path, design, census, capacity,
                                             monkeypatch)
    updates = []
    def runner(_game, _root):
        raise RuntimeError("pre-seal failure")
    report = controller.run_source_population(
        design=design, seed_secret=SECRET, census=census, capacity=capacity,
        evidence_root=tmp_path, game_runner=runner, worker_count=1,
        progress_sink=updates.append, candidate_freeze=freeze,
        review_commit=review_commit, repo_root=tmp_path,
        tool_script=TOOL)
    assert report["terminal_route"] == luna.INCOMPLETE_ROUTE
    assert report["rows"][0]["attempt_manifest_sha256"] is None
    assert report["rows"][0]["error"] == "RuntimeError"
    assert updates[-1]["completed_games"] == 1
    assert updates[-1]["sealed_games"] == 0
    assert updates[-1]["failure_count"] == 1
    reopened = controller.reopen_population_report(
        tmp_path / "population-report.json", design=design,
        capacity=capacity, census=census, candidate_freeze=freeze,
        review_commit=review_commit, repo_root=tmp_path, tool_script=TOOL)
    assert reopened["rows"][0]["error"] == "RuntimeError"
def test_population_uses_execution_adapter_and_reopens_complete_attempt(tmp_path,
                                                                         monkeypatch):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze, review_commit = _reviewed_inputs(tmp_path, design, census, capacity,
                                             monkeypatch)
    calls = []
    def runner(game, private_root):
        calls.append((game.coordinate, game.mirror))
        return execution.run_luna_game(
            game, private_root=private_root, tool_script=TOOL,
            planner_process=_fake_process)
    with pytest.raises(controller.SourceAdmissionError, match="synthetic"):
        controller.run_source_population(
            design=design, seed_secret=SECRET, census=census, capacity=capacity,
            evidence_root=tmp_path, game_runner=runner, worker_count=1,
            candidate_freeze=freeze, review_commit=review_commit,
            repo_root=tmp_path, tool_script=TOOL)
    assert len(calls) == 1
    assert not (tmp_path / "population-report.json").exists()


def test_incomplete_attempt_keeps_real_manifest_identity_and_is_not_retried(tmp_path,
                                                                            monkeypatch):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze, review_commit = _reviewed_inputs(tmp_path, design, census, capacity,
                                             monkeypatch)
    calls = []
    def runner(game, private_root):
        calls.append((game.coordinate, game.mirror))
        if len(calls) == 1:
            def fail(session, **_kwargs):
                game.fail("synthetic failure")
                return subprocess.CompletedProcess(("fake",), 1, b"")
            return execution.run_luna_game(game, private_root=private_root,
                                           tool_script=TOOL, planner_process=fail)
        return execution.run_luna_game(game, private_root=private_root,
                                       tool_script=TOOL, planner_process=_fake_process)
    report = controller.run_source_population(
        design=design, seed_secret=SECRET, census=census, capacity=capacity,
        evidence_root=tmp_path, game_runner=runner, worker_count=1,
        candidate_freeze=freeze, review_commit=review_commit,
        repo_root=tmp_path, tool_script=TOOL)
    assert report["terminal_route"] == luna.INCOMPLETE_ROUTE
    row = report["rows"][0]
    assert row["status"] == "incomplete"
    manifest = tmp_path / "attempts" / row["attempt_path"] / "manifest.json"
    assert row["attempt_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert len(calls) == 1
    with pytest.raises(controller.ControllerError, match="occupied"):
        controller.run_source_population(
            design=design, seed_secret=SECRET, census=census, capacity=capacity,
            evidence_root=tmp_path, game_runner=runner, worker_count=1,
            candidate_freeze=freeze, review_commit=review_commit,
            repo_root=tmp_path, tool_script=TOOL)


def test_controller_death_before_manifest_is_hash_bound_and_never_retried(tmp_path,
                                                                          monkeypatch):
    design = TinyDesign(seed_commitment_sha256=hashlib.sha256(SECRET).hexdigest())
    census = _tiny_census(design)
    capacity = _verified_capacity_fixture(one_arm=True)
    freeze, review_commit = _reviewed_inputs(tmp_path, design, census, capacity,
                                             monkeypatch)
    attempt = tmp_path / "attempts" / "2-0-0-mirror-0"
    attempt.mkdir(parents=True)
    (attempt / "partial-output.bin").write_bytes(b"controller died before manifest")
    calls = []

    def runner(_game, _root):
        calls.append(1)
        raise AssertionError("orphaned attempt must not be retried")

    report = controller.run_source_population(
        design=design, seed_secret=SECRET, census=census, capacity=capacity,
        evidence_root=tmp_path, game_runner=runner, worker_count=1,
        candidate_freeze=freeze, review_commit=review_commit,
        repo_root=tmp_path, tool_script=TOOL)
    row = report["rows"][0]
    assert row["status"] == "incomplete"
    assert row["error"] == "controller-death-before-manifest"
    manifest = attempt / "manifest.json"
    assert row["attempt_manifest_sha256"] == hashlib.sha256(
        manifest.read_bytes()).hexdigest()
    recovered = execution.reopen_attempt(attempt)
    assert recovered.status == "incomplete"
    assert recovered.error == "controller-death-before-manifest"
    reopened = controller.reopen_population_report(
        tmp_path / "population-report.json", design=design,
        capacity=capacity, census=census, candidate_freeze=freeze,
        review_commit=review_commit, repo_root=tmp_path, tool_script=TOOL)
    assert reopened["rows"][0]["attempt_manifest_sha256"] == row[
        "attempt_manifest_sha256"]
    assert calls == []


def test_cli_without_authenticated_freeze_never_launches_and_refuses_occupied_output(
        tmp_path):
    cli = _cli_module()
    output = tmp_path / "capacity.json"
    output.write_bytes(b"occupied")
    assert cli.main(["capacity", "--fake", "--output", str(output),
                     "--physical-memory-bytes", "8000000000"]) == 2
    assert output.read_bytes() == b"occupied"
    with pytest.raises(SystemExit):
        cli.main(["collect", "--design", str(tmp_path / "design.json"),
                  "--secret-file", str(tmp_path / "secret"),
                  "--census", str(tmp_path / "census"),
                  "--capacity", str(tmp_path / "capacity"),
                  "--output-root", str(tmp_path / "out"),
                  "--tool-script", str(TOOL)])
    assert not (tmp_path / "out").exists()
