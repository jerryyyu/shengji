"""Fail-closed orchestration witnesses for the scientific PT1 lane."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass, replace

import pytest

from shengji.rl import privileged_teacher_pt1_execution as execution


KEYS = tuple((f"r{i}", i % 2, "banker-team" if i % 2 == 0 else "attacker-team",
              3 if i % 2 == 0 else 4, i % 4) for i in range(416))
CAPS = {name: 1_000_000_000 for name in execution.SCIENTIFIC_CAP_KEYS}
SOURCE = {"git_head": "a" * 40, "source_tree_dirty": False,
          "files": [], "files_sha256": "b" * 64}
RUNTIME = {"hostname": "mini", "boot_identity_sha256": "c" * 64,
           "python_version": "3.14.0", "python_executable_sha256": "d" * 64,
           "native_extension_sha256": "e" * 64, "compiled_engine": True,
           "strict_voids": True, "worker_count": 2}
SCIENTIFIC = bytes(range(32))
SCIENTIFIC_SHA = hashlib.sha256(SCIENTIFIC).hexdigest()


@pytest.fixture(autouse=True)
def _authenticated_review_seam(monkeypatch):
    """Tests isolate controller behavior below the real remote review check."""
    monkeypatch.setattr(
        execution, "_authenticate_review_provenance", lambda *args: None)


def test_darwin_boot_identity_tracks_session_uuid_not_adjusted_clock(monkeypatch):
    session = {"uuid": b"stable-boot-session-1\n"}
    commands = []

    def sysctl(command, **_kwargs):
        commands.append(tuple(command))
        assert command == ["sysctl", "-n", "kern.bootsessionuuid"]
        return session["uuid"]

    monkeypatch.setattr(execution.sys, "platform", "darwin")
    monkeypatch.setattr(execution.subprocess, "check_output", sysctl)
    before = execution._boot_identity_bytes()
    # A wall-clock/NTP adjustment cannot affect the session UUID primitive.
    after_clock_adjustment = execution._boot_identity_bytes()
    assert before == after_clock_adjustment == b"stable-boot-session-1"
    session["uuid"] = b"stable-boot-session-2\n"
    assert execution._boot_identity_bytes() != before
    assert commands == [
        ("sysctl", "-n", "kern.bootsessionuuid"),
        ("sysctl", "-n", "kern.bootsessionuuid"),
        ("sysctl", "-n", "kern.bootsessionuuid"),
    ]


class FakeDesign:
    def __init__(self, commitment):
        self.commitment = commitment
        self.state_keys = KEYS

    def payload(self):
        return {"commitment": self.commitment, "state_keys": [list(k) for k in KEYS]}


@dataclass(frozen=True)
class FakeState:
    rank: str
    banker: int
    role: str
    remaining_hand_threshold: int
    replicate: int
    public_state_sha256: str
    true_world_sha256: str
    schema: str = "fake-state"
    round_seed: int = 1
    capture_round_cluster_sha256: str = "3" * 64
    capture_id_sha256: str = "4" * 64
    public_round: object = None
    true_world: object = None


@dataclass(frozen=True)
class FakeArm:
    seed: int


@dataclass(frozen=True)
class FakeRecord:
    public_state_sha256: str
    true_world_sha256: str
    arms: tuple[FakeArm, ...]

    def payload(self):
        return {"schema": "fake", "public": self.public_state_sha256,
                "true": self.true_world_sha256,
                "seeds": [arm.seed for arm in self.arms]}


class FakeReport:
    def canonical_bytes(self):
        return b'{"capacity":true}\n'

    def payload(self):
        return {"capture_secret_sha256": "f" * 64, "caps": CAPS,
                "status": "COMPLETE", "record_count": 16,
                "total_record_count": 16, "truncated_by_deadline": False,
                "parallel_workers": 2, "runtime": {}}


class Immediate:
    def __init__(self, fn, payload):
        self.value = fn(payload)
    def result(self):
        return self.value


class SpyExecutor:
    workers = []
    def __init__(self, count):
        self.workers.append(count)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def submit(self, fn, payload):
        return Immediate(fn, payload)


def _fake_worker(payload):
    key, state = payload
    records = tuple(FakeRecord(state.public_state_sha256,
                               state.true_world_sha256,
                               tuple(FakeArm(seed) for _ in range(4)))
                    for seed in (0, 1, 2, 3))
    return key, records


def _fake_verify(record):
    if isinstance(record, FakeRecord):
        return record
    return FakeRecord(record["public"], record["true"],
                      tuple(FakeArm(seed) for seed in record["seeds"]))


def _states():
    result = {}
    for index, key in enumerate(KEYS, 1):
        public = hashlib.sha256(f"public-{index}".encode()).hexdigest()
        result[key] = FakeState(
            *key, public, hashlib.sha256(f"world-{index}".encode()).hexdigest(),
            execution.NATURAL_PT1_STATE_SCHEMA, index,
            execution._cluster_sha256(index),
            execution._capture_id_sha256(*key, public))
    return result


def _freeze(monkeypatch, tmp_path):
    monkeypatch.setattr(execution, "NaturalPT1Design", FakeDesign)
    monkeypatch.setattr(execution, "verify_capacity_report", lambda value: FakeReport())
    monkeypatch.setattr(execution, "verify_manifest", lambda manifest, report: None)
    design_sha = hashlib.sha256(execution.canonical_json_bytes(
        FakeDesign(SCIENTIFIC_SHA).payload())).hexdigest()
    marker = execution.canonical_json_bytes({
        "schema": execution.REVIEW_MARKER_SCHEMA, "source_git": "a" * 40,
        "design_sha256": design_sha, "capacity_report_sha256": hashlib.sha256(
            b'{"capacity":true}\n').hexdigest(),
        "capacity_manifest_sha256": "3" * 64,
        "authority": dict(execution.AUTHORITIES)})
    # The fake manifest bytes are supplied by the freeze input and are bound by
    # the marker; this keeps the test independent of capacity capture details.
    manifest = {"manifest": True}
    marker_value = json.loads(marker)
    marker_value["capacity_manifest_sha256"] = hashlib.sha256(
        execution.canonical_json_bytes(manifest)).hexdigest()
    marker = execution.canonical_json_bytes(marker_value)
    freeze = execution.freeze_execution(
        design_sha256=design_sha, scientific_capture_secret_sha256=SCIENTIFIC_SHA,
        capacity_report=FakeReport(), capacity_manifest=manifest,
        review_marker=marker, evidence_root=tmp_path / "evidence",
        deadline_nanoseconds=1_000_000_000, worker_count=2, resume_allowed=True,
        source=SOURCE, runtime=RUNTIME)
    return freeze


def test_freeze_binds_marker_runtime_population_and_authority(monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    assert len(freeze.state_keys) == 416
    assert freeze.seeds == (0, 1, 2, 3)
    assert freeze.payload()["authority"] == execution.AUTHORITIES
    altered = freeze.payload()
    altered["runtime"]["compiled_engine"] = False
    with pytest.raises(execution.PT1ExecutionError):
        execution.verify_freeze(altered)
    marker = execution.canonical_json_bytes(dict(freeze.review_marker))
    observed = []
    monkeypatch.setattr(
        execution, "_authenticate_review_provenance",
        lambda root, commit, raw: observed.append((raw, dict(freeze.review_marker), commit)))
    execution.authenticate_review_marker(
        marker, freeze, review_commit="4" * 40)
    assert observed == [(marker, dict(freeze.review_marker), "4" * 40)]
    assert "review_commit" not in freeze.review_marker
    forged = dict(freeze.review_marker)
    forged["source_git"] = "9" * 40
    with pytest.raises(execution.PT1ExecutionError, match="bind freeze"):
        execution.authenticate_review_marker(
            execution.canonical_json_bytes(forged), freeze,
            review_commit="4" * 40)


def test_parallel_groups_deadline_cannot_reset_on_resume(monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_source_identity", lambda *args: SOURCE)
    monkeypatch.setattr(execution, "_runtime_identity", lambda count: RUNTIME)
    monkeypatch.setattr("shengji.rl.privileged_teacher_pt1_capacity._runtime_identity",
                        lambda: {})
    monkeypatch.setattr(execution, "validate_population", lambda *args: None)
    monkeypatch.setattr(execution, "verify_record", _fake_verify)
    monkeypatch.setattr(execution, "reduce_pt1_statistics",
                        lambda *args: type("S", (), {"payload": lambda self: {"ok": True}})())
    monkeypatch.setattr(execution, "verify_statistics_report", lambda *args, **kwargs: None)
    clock = iter((0.0, 0.0, 2.0))
    root = tmp_path / "evidence"
    result = execution.run_execution(
        freeze, output_root=root, capture_secret=SCIENTIFIC,
        population=_states(), executor_factory=lambda n: SpyExecutor(n),
        worker=_fake_worker, review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40,
        monotonic=lambda: next(clock))
    assert result["status"] == "TRUNCATED"
    assert len(list((root / execution.GROUP_DIR).glob("group-*.json"))) == 0
    resumed = execution.run_execution(
        freeze, output_root=root, capture_secret=SCIENTIFIC,
        population=_states(), executor_factory=lambda n: SpyExecutor(n),
        worker=_fake_worker, review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40,
        monotonic=lambda: 3.0)
    assert resumed["status"] == "TRUNCATED"
    assert resumed["completed_units"] == 0


def test_deadline_during_finalization_cannot_publish_packet(monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_source_identity", lambda *args: SOURCE)
    monkeypatch.setattr(execution, "_runtime_identity", lambda count: RUNTIME)
    monkeypatch.setattr("shengji.rl.privileged_teacher_pt1_capacity._runtime_identity",
                        lambda: {})
    monkeypatch.setattr(execution, "validate_population", lambda *args: None)
    monkeypatch.setattr(execution, "verify_record", _fake_verify)
    monkeypatch.setattr(execution, "reduce_pt1_statistics",
                        lambda *args: type("S", (), {"payload": lambda self: {"ok": True}})())
    monkeypatch.setattr(execution, "verify_statistics_report", lambda *args, **kwargs: None)
    calls = 0
    def clock():
        nonlocal calls
        calls += 1
        return 2.0 if calls >= 418 else 0.0
    root = tmp_path / "evidence"
    result = execution.run_execution(
        freeze, output_root=root, capture_secret=SCIENTIFIC,
        population=_states(), executor_factory=lambda n: SpyExecutor(n),
        worker=_fake_worker,
        review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40, monotonic=clock)
    assert result == {"status": "TRUNCATED", "completed_units": 416,
                      "total_units": 416, "authority": execution.AUTHORITIES}
    assert not (root / execution.PACKET_NAME).exists()
    assert not (root / execution.MANIFEST_NAME).exists()
    assert execution.verify_execution(
        root, freeze, capture_secret=SCIENTIFIC, population=_states(),
        review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40)["status"] == "TRUNCATED"


def test_deadline_after_terminal_writes_removes_late_packet(monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_source_identity", lambda *args: SOURCE)
    monkeypatch.setattr(execution, "_runtime_identity", lambda count: RUNTIME)
    monkeypatch.setattr("shengji.rl.privileged_teacher_pt1_capacity._runtime_identity",
                        lambda: {})
    monkeypatch.setattr(execution, "validate_population", lambda *args: None)
    monkeypatch.setattr(execution, "verify_record", _fake_verify)
    monkeypatch.setattr(execution, "reduce_pt1_statistics",
                        lambda *args: type("S", (), {"payload": lambda self: {"ok": True}})())
    monkeypatch.setattr(execution, "verify_statistics_report", lambda *args, **kwargs: None)
    calls = 0
    def clock():
        nonlocal calls
        calls += 1
        # Receipt + 208 wave pre/post checks + pre-publication +
        # post-packet/manifest remain in time.  The final progress publication
        # crosses the boundary and must be rolled back to TRUNCATED.
        return 2.0 if calls >= 420 else 0.0
    root = tmp_path / "evidence"
    result = execution.run_execution(
        freeze, output_root=root, capture_secret=SCIENTIFIC,
        population=_states(), executor_factory=lambda n: SpyExecutor(n),
        worker=_fake_worker,
        review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40, monotonic=clock)
    assert result["status"] == "TRUNCATED"
    assert result["completed_units"] == 416
    assert not (root / execution.PACKET_NAME).exists()
    assert not (root / execution.MANIFEST_NAME).exists()
    assert execution.verify_execution(
        root, freeze, capture_secret=SCIENTIFIC, population=_states(),
        review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40)["status"] == "TRUNCATED"


def test_parallel_groups_complete_and_final_reopen(monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_source_identity", lambda *args: SOURCE)
    monkeypatch.setattr(execution, "_runtime_identity", lambda count: RUNTIME)
    monkeypatch.setattr("shengji.rl.privileged_teacher_pt1_capacity._runtime_identity",
                        lambda: {})
    monkeypatch.setattr(execution, "validate_population", lambda *args: None)
    monkeypatch.setattr(execution, "verify_record", _fake_verify)
    monkeypatch.setattr(execution, "reduce_pt1_statistics",
                        lambda *args: type("S", (), {"payload": lambda self: {"ok": True}})())
    monkeypatch.setattr(execution, "verify_statistics_report", lambda *args, **kwargs: None)
    root = tmp_path / "evidence"
    result = execution.run_execution(
        freeze, output_root=root, capture_secret=SCIENTIFIC,
        population=_states(), executor_factory=lambda n: SpyExecutor(n),
        worker=_fake_worker,
        review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40,
        monotonic=lambda: 0.0)
    assert result["status"] == "COMPLETE"
    states = _states()
    assert execution.verify_execution(
        root, freeze, capture_secret=SCIENTIFIC, population=states,
        review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40)["status"] == "COMPLETE"
    wrong = dict(states)
    wrong[KEYS[0]] = replace(wrong[KEYS[0]], true_world_sha256="8" * 64)
    with pytest.raises(execution.PT1ExecutionError, match="recapture identity"):
        execution.verify_execution(
            root, freeze, capture_secret=SCIENTIFIC, population=wrong,
            review_marker=execution.canonical_json_bytes(
                dict(freeze.review_marker)), review_commit="4" * 40)
    extra = root / "unreviewed.txt"
    extra.write_text("drift")
    with pytest.raises(execution.PT1ExecutionError, match="namespace"):
        execution.verify_execution(
            root, freeze, capture_secret=SCIENTIFIC, population=states,
            review_marker=execution.canonical_json_bytes(
                dict(freeze.review_marker)), review_commit="4" * 40)
    extra.unlink()
    group = root / execution.GROUP_DIR / "group-0000.json"
    os.chmod(group, 0o600)
    with pytest.raises(execution.PT1ExecutionError, match="unsafe"):
        execution.verify_execution(
            root, freeze, capture_secret=SCIENTIFIC, population=states,
            review_marker=execution.canonical_json_bytes(
                dict(freeze.review_marker)), review_commit="4" * 40)
    os.chmod(group, 0o400)
    groups = root / execution.GROUP_DIR
    real_groups = root / "groups-real"
    groups.rename(real_groups)
    groups.symlink_to(real_groups, target_is_directory=True)
    with pytest.raises(execution.PT1ExecutionError, match="safe owned directory"):
        execution.verify_execution(
            root, freeze, capture_secret=SCIENTIFIC, population=states,
            review_marker=execution.canonical_json_bytes(
                dict(freeze.review_marker)), review_commit="4" * 40)
    assert all(count == 2 for count in SpyExecutor.workers)


def test_actual_path_combines_parallel_capture_evaluation_and_child_cpu(
        monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_source_identity", lambda *args: SOURCE)
    monkeypatch.setattr(execution, "_runtime_identity", lambda count: RUNTIME)
    monkeypatch.setattr("shengji.rl.privileged_teacher_pt1_capacity._runtime_identity",
                        lambda: {})
    monkeypatch.setattr(execution, "verify_record", _fake_verify)
    monkeypatch.setattr(execution, "reduce_pt1_statistics",
                        lambda *args: type("S", (), {"payload": lambda self: {"ok": True}})())
    monkeypatch.setattr(execution, "verify_statistics_report", lambda *args, **kwargs: None)
    states = _states()
    def combined(payload):
        _, _, key = payload
        _, records = _fake_worker((key, states[key]))
        return key, states[key], records, 5, 7, 11
    monkeypatch.setattr(execution, "_scientific_worker", combined)
    progress = []
    packet = execution.run_execution(
        freeze, output_root=tmp_path / "evidence",
        capture_secret=SCIENTIFIC,
        executor_factory=lambda n: SpyExecutor(n),
        review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
        review_commit="4" * 40,
        monotonic=lambda: 0.0, progress_sink=progress.append)
    assert packet["resources"]["scientific_cpu_nanoseconds"] == 416 * 7
    assert progress[-1]["percent_basis_points"] == 10_000


def test_aggregate_exact_node_cap_is_wired_at_execution(monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_source_identity", lambda *args: SOURCE)
    monkeypatch.setattr(execution, "_runtime_identity", lambda count: RUNTIME)
    monkeypatch.setattr("shengji.rl.privileged_teacher_pt1_capacity._runtime_identity",
                        lambda: {})
    monkeypatch.setattr(execution, "validate_population", lambda *args: None)
    monkeypatch.setattr(execution, "verify_record", _fake_verify)
    original = execution._group_payload
    def nodes(*args, **kwargs):
        result = original(*args, **kwargs)
        result["exact_nodes"] = 1
        return result
    monkeypatch.setattr(execution, "_group_payload", nodes)
    payload = freeze.payload()
    payload["capacity_caps"]["scientific_exact_nodes"] = 0
    capped = execution.verify_freeze(payload)
    with pytest.raises(execution.PT1ExecutionError, match="scientific cap"):
        execution.run_execution(
            capped, output_root=tmp_path / "evidence",
            capture_secret=SCIENTIFIC, population=_states(),
            executor_factory=lambda n: SpyExecutor(n), worker=_fake_worker,
            review_marker=execution.canonical_json_bytes(
                dict(capped.review_marker)), review_commit="4" * 40,
            monotonic=lambda: 0.0)


def test_worker_failure_retains_durable_groups_and_no_final_packet(monkeypatch, tmp_path):
    freeze = _freeze(monkeypatch, tmp_path)
    monkeypatch.setattr(execution, "_source_identity", lambda *args: SOURCE)
    monkeypatch.setattr(execution, "_runtime_identity", lambda count: RUNTIME)
    monkeypatch.setattr("shengji.rl.privileged_teacher_pt1_capacity._runtime_identity",
                        lambda: {})
    monkeypatch.setattr(execution, "validate_population", lambda *args: None)
    monkeypatch.setattr(execution, "verify_record", _fake_verify)
    def failing(payload):
        if payload[0][0] == "r2":
            raise RuntimeError("worker failed")
        return _fake_worker(payload)
    with pytest.raises(execution.PT1ExecutionError, match="worker failure"):
        execution.run_execution(
            freeze, output_root=tmp_path / "evidence", capture_secret=SCIENTIFIC,
            population=_states(), executor_factory=lambda n: SpyExecutor(n),
            worker=failing, review_marker=execution.canonical_json_bytes(dict(freeze.review_marker)),
            review_commit="4" * 40)
    assert not (tmp_path / "evidence" / execution.PACKET_NAME).exists()
