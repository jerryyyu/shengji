"""Fail-closed tests for the Pair checkpoint successor capacity controller."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_aware_rollout_checkpoint_capacity as C  # noqa: E402
import pair_aware_rollout_duel as TEST_CORE  # noqa: E402

C.CORE = TEST_CORE


GIT = "a" * 40
PROFILE = "b" * 64
PACKET_SHA = "c" * 64


def _runtime():
    return {
        "git": GIT,
        "hostname": "capacity-host",
        "machine": "x86_64",
        "platform": "Linux-test",
        "cpu_count": 16,
        "memory_bytes": C.MIN_MEMORY_BYTES,
        "python": {
            "executable": "/usr/bin/python3",
            "resolved": "/usr/bin/python3",
            "version": "3.14.4",
            "sha256": "1" * 64,
            "soabi": "cpython-314-x86_64-linux-gnu",
        },
        "native": {"path": "/repo/_fast.so", "sha256": "2" * 64},
        "fast_enabled": True,
        "fast_environment": True,
        "fast_routing_active": True,
        "strict_voids": True,
        "dont_write_bytecode": True,
        "python_hash_seed": "0",
        "process_nice": 5,
        "boot_id": "boot-id",
        "module_origins": {
            "controller": "/repo/controller.py",
            "design": "/repo/design.py",
            "duel": "/repo/duel.py",
            "fast": "/repo/fast.py",
            "native": "/repo/_fast.so",
        },
        "loadable_shadows": [],
        "source_sha256s": {"server/shengji/x.py": "3" * 64},
    }


def _review():
    return {
        "commit": "4" * 40,
        "parent_commit": "5" * 40,
        "ledger_sha256": "6" * 64,
        "marker_sha256": "7" * 64,
        "claim": C.implementation_review_claim(expected_git=GIT),
    }


def _packet():
    return C.packet_payload(
        expected_git=GIT, runtime=_runtime(), implementation_review=_review())


def _result(seconds: float = 10.0):
    return {
        "schema": C.DESIGN.CAPACITY_SCHEMA,
        "run_id": C.RUN_ID,
        "seed0": C.DESIGN.CAPACITY_SEED0,
        "workers": C.DESIGN.MIN_WORKERS,
        "clusters_per_worker": C.DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
        "runtime_profile_sha256": C.digest(_runtime()),
        "score_free": True,
        "outcomes_published": False,
        "exact_work_complete": True,
        "concurrent_saturation_verified": True,
        "lanes": [
            {"index": index,
             "clusters": C.DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
             "elapsed_seconds": seconds + index / 100}
            for index in range(C.DESIGN.MIN_WORKERS)
        ],
    }


def test_controller_is_capacity_only_and_binds_reviewed_design():
    assert C.DESIGN_GIT == "36b3841f28e04a1b3ba066044db0ed8c992e8714"
    assert C.sha256_file(
        SCRIPTS / "pair_aware_rollout_checkpoint_successor_design.py"
    ) == C.DESIGN_SOURCE_SHA256
    claim = C.implementation_review_claim(expected_git=GIT)
    assert claim["capacity_packet_freeze_authorized"] is True
    assert claim["capacity_execution_authorized"] is False
    assert claim["screen_execution_authorized"] is False
    assert claim["resume_execution_authorized"] is False
    assert claim["aggregate_execution_authorized"] is False
    assert claim["strength_claim"] is False
    assert C.IMPLEMENTATION_REVIEW_PREFIX != \
        C.RETIRED_IMPLEMENTATION_REVIEW_PREFIX


def test_modified_design_source_cannot_execute_before_hash_refusal(tmp_path):
    scripts = tmp_path / "server/scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(Path(C.__file__), scripts / Path(C.__file__).name)
    tripwire = tmp_path / "tripwire"
    design = scripts / "pair_aware_rollout_checkpoint_successor_design.py"
    design.write_text(
        "from pathlib import Path\n"
        f"Path({str(tripwire)!r}).write_text('executed')\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(scripts)
    completed = subprocess.run(
        [sys.executable, "-B", str(scripts / Path(C.__file__).name), "--help"],
        cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode != 0
    assert not tripwire.exists()


def test_modified_duel_source_refuses_before_import(monkeypatch, tmp_path):
    source = tmp_path / "pair_aware_rollout_duel.py"
    source.write_text("raise RuntimeError('tripwire executed')\n")
    called = []
    monkeypatch.setattr(C, "CORE", None)
    monkeypatch.setattr(C, "CORE_PATH", source)
    monkeypatch.setattr(C, "require_clean_exact_git", lambda git: None)
    monkeypatch.setattr(C.importlib, "import_module", lambda name: called.append(name))
    with pytest.raises(C.CapacityRefused, match="duel source drift"):
        C._load_core(GIT)
    assert called == []


def test_preloaded_shengji_dependency_refuses_in_fresh_cli(tmp_path):
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "import sys, types\n"
        "module = types.ModuleType('shengji.engine.fast')\n"
        f"module.__file__ = {str(SCRIPTS / '../shengji/engine/fast.py')!r}\n"
        "sys.modules['shengji.engine.fast'] = module\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        (str(tmp_path), str(SCRIPTS), str(SCRIPTS.parent)))
    completed = subprocess.run(
        [sys.executable, "-B", str(Path(C.__file__)), "verify",
         "--expected-git", GIT, "--packet", str(tmp_path / "packet.json"),
         "--expected-packet-sha256", PACKET_SHA],
        cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "unpreloaded dependencies" in completed.stderr


def test_packet_is_closed_and_nonexecuting_before_review():
    packet = _packet()
    assert C.packet_problems(packet, expected_git=GIT) == []
    assert packet["capacity"] == {
        "seed0": C.DESIGN.CAPACITY_SEED0,
        "workers": 16,
        "clusters_per_worker": 8,
        "stream_stride": C.DESIGN.STREAM_STRIDE,
        "all_workers_start_concurrently": True,
        "outcomes_published": False,
    }
    assert packet["one_capacity_execution_authorized"] is False
    assert not any(packet[name] for name in (
        "screen_execution_authorized", "resume_execution_authorized",
        "aggregate_execution_authorized", "strength_claim",
        "production_deployment"))


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(schema="other"),
    lambda row: row.update(design_git="0" * 40),
    lambda row: row.update(runtime_profile_sha256="0" * 64),
    lambda row: row["capacity"].update(workers=8),
    lambda row: row.update(one_capacity_execution_authorized=True),
    lambda row: row.update(screen_execution_authorized=True),
    lambda row: row.update(outcomes=[]),
    lambda row: row["implementation_review"].update(marker_sha256="bad"),
])
def test_packet_mutations_refuse_even_when_self_hash_is_reforged(mutation):
    packet = _packet()
    mutation(packet)
    packet.pop("internal_sha256", None)
    packet["internal_sha256"] = C.digest(packet)
    assert C.packet_problems(packet, expected_git=GIT)


def test_load_packet_reauthenticates_review_commit_and_exact_snapshot(
        tmp_path, monkeypatch):
    packet = _packet()
    marker = C._canonical_marker(
        C.IMPLEMENTATION_REVIEW_PREFIX,
        C.implementation_review_claim(expected_git=GIT))
    packet["implementation_review"]["marker_sha256"] = C.sha256_bytes(marker)
    packet.pop("internal_sha256")
    packet["internal_sha256"] = C.digest(packet)
    raw = C.canonical(packet)
    path = tmp_path / "packet.json"
    path.write_bytes(raw)
    snapshot = tmp_path / "review.md"
    snapshot.write_bytes(marker)
    monkeypatch.setattr(C, "IMPLEMENTATION_REVIEW_PATH", snapshot)
    monkeypatch.setattr(
        C, "require_regular_unlinked",
        lambda path, **kwargs: Path(path).read_bytes())
    monkeypatch.setattr(
        C, "canonical_review_record",
        lambda **kwargs: (copy.deepcopy(packet["implementation_review"]), marker))
    assert C.load_packet(
        path, C.sha256_bytes(raw), expected_git=GIT) == packet
    monkeypatch.setattr(
        C, "canonical_review_record",
        lambda **kwargs: ({**packet["implementation_review"],
                           "commit": "0" * 40}, marker))
    with pytest.raises(C.CapacityRefused, match="review record drift"):
        C.load_packet(path, C.sha256_bytes(raw), expected_git=GIT)


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(machine="arm64"),
    lambda row: row.update(cpu_count=True),
    lambda row: row.update(cpu_count=15),
    lambda row: row.update(memory_bytes=C.MIN_MEMORY_BYTES - 1),
    lambda row: row.update(fast_enabled=False),
    lambda row: row.update(fast_environment=False),
    lambda row: row.update(fast_routing_active=False),
    lambda row: row.update(strict_voids=False),
    lambda row: row.update(dont_write_bytecode=False),
    lambda row: row.update(python_hash_seed=None),
    lambda row: row.update(process_nice=0),
    lambda row: row.update(boot_id=""),
    lambda row: row.update(loadable_shadows=["server/shadow.pyc"]),
    lambda row: row.update(module_origins={}),
    lambda row: row["native"].update(sha256="bad"),
    lambda row: row.update(source_sha256s={}),
])
def test_runtime_requires_homogeneous_compiled_strict_host(mutation):
    runtime = _runtime()
    mutation(runtime)
    assert C.runtime_problems(runtime, expected_git=GIT)


def test_lane_uses_exact_disjoint_seed_slice_and_returns_only_timing(monkeypatch):
    observed = []
    monkeypatch.setattr(
        C, "_validate_cluster",
        lambda seed, run_id: (observed.append((seed, run_id)) or (1, 1)))
    lane = C.run_lane(3, PROFILE)
    first = 3 * C.DESIGN.CAPACITY_CLUSTERS_PER_WORKER
    assert observed == [
        (C.DESIGN.CAPACITY_SEED0 + C.DESIGN.STREAM_STRIDE * (first + offset),
         C.RUN_ID)
        for offset in range(C.DESIGN.CAPACITY_CLUSTERS_PER_WORKER)
    ]
    assert set(lane) == {"index", "clusters", "elapsed_seconds"}
    assert not C._forbidden_keys(lane)


def test_cluster_validates_all_three_mirrored_arms_then_discards(monkeypatch):
    calls = []

    def play(label, seed, *, run_id):
        calls.append((label, seed, run_id))
        triggers = 1 if label == "treatment" else 0
        return [{
            "flip": flip,
            "arm": {"searches": 1, "pair_aware": {"triggers": triggers}},
            "opp": {"searches": 1, "pair_aware": {"triggers": triggers}},
        } for flip in (0, 1)]

    monkeypatch.setattr(C.CORE, "play_arm_cluster", play)
    monkeypatch.setattr(C.CORE, "record_problems", lambda *a, **k: [])
    monkeypatch.setattr(
        C.CORE, "matched_null_champion_problems", lambda *a, **k: [])
    assert C._validate_cluster(123, run_id=C.RUN_ID) == (12, 4)
    assert calls == [(label, 123, C.RUN_ID) for label in C.CORE.LABEL_ORDER]


def test_cluster_refuses_record_or_null_control_drift(monkeypatch):
    monkeypatch.setattr(
        C.CORE, "play_arm_cluster",
        lambda label, seed, *, run_id: [{}, {}])
    monkeypatch.setattr(C.CORE, "record_problems", lambda *a, **k: ["bad"])
    with pytest.raises(C.CapacityRefused, match="invalid capacity record"):
        C._validate_cluster(1, run_id=C.RUN_ID)


class _Queue:
    def __init__(self):
        self.values = []

    def put(self, value):
        self.values.append(value)

    def get(self, timeout):
        assert timeout == C.CAPACITY_WORKER_TIMEOUT_SECONDS
        return self.values.pop(0)


class _Process:
    def __init__(self, context, target, args, name):
        assert target is C._lane_process
        self.context = context
        self.args = args
        self.name = name
        self.exitcode = None
        self.alive = False

    def start(self):
        self.alive = True
        self.args[3].put({
            "index": self.args[0],
            "ok": self.args[0] != self.context.not_ok_index,
        })

    def join(self, timeout):
        assert timeout == 10

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.alive = False
        self.exitcode = 0


class _Event:
    def __init__(self, context):
        self.context = context

    def set(self):
        for process in self.context.processes:
            index, _git, profile, _ready, _start, results = process.args
            results.put({"index": index, "ok": True, "lane": {
                "index": index, "clusters": 8,
                "elapsed_seconds": 10.0 + index / 100}})
            process.alive = False
            process.exitcode = 0


class _Context:
    def __init__(self, *, not_ok_index=None):
        self.processes = []
        self.not_ok_index = not_ok_index

    def Queue(self):
        return _Queue()

    def Event(self):
        return _Event(self)

    def Process(self, *, target, args, name):
        process = _Process(self, target, args, name)
        self.processes.append(process)
        return process


def test_measurement_uses_all_16_concurrent_lanes_and_score_free_schema(
        monkeypatch):
    context = _Context()
    monkeypatch.setattr(C.multiprocessing, "get_context", lambda method: (
        context if method == "spawn" else None))
    result = C.measure_capacity(_packet())
    assert result == _result()
    assert C.DESIGN.concurrent_capacity_problems(
        result, expected_workers=16,
        runtime_profile_sha256=result["runtime_profile_sha256"]) == []
    assert not C._forbidden_keys(result)


def test_lane_process_reports_not_ok_when_worker_runtime_digest_drifts(
        monkeypatch):
    ready = _Queue()
    results = _Queue()
    monkeypatch.setattr(C, "runtime_snapshot", lambda expected_git: {
        "git": expected_git, "worker": "drifted"})
    monkeypatch.setattr(C, "run_lane", lambda *args: {
        "unexpected": "runtime guard was bypassed"})
    C._lane_process(
        7, GIT, "0" * 64, ready,
        SimpleNamespace(wait=lambda: None), results)
    assert ready.values == [{"index": 7, "ok": False}]
    assert results.values == []


def test_measurement_refuses_not_ok_worker_before_start_barrier(monkeypatch):
    context = _Context(not_ok_index=7)
    monkeypatch.setattr(C.multiprocessing, "get_context", lambda method: (
        context if method == "spawn" else None))
    with pytest.raises(C.CapacityRefused, match="start-barrier"):
        C.measure_capacity(_packet())


@pytest.mark.parametrize("key", [
    "utility", "scores", "winner", "attacker_points", "records", "actions",
])
def test_recursive_score_free_boundary_rejects_aliases(key):
    result = _result()
    result["lanes"][0][key] = 0
    assert key in C._forbidden_keys(result)


def test_result_validator_reconstructs_projection_and_refuses_nested_alias():
    packet = _packet()
    result = _result()
    assert C.capacity_result_problems(result, packet=packet) == []
    result["lanes"][0]["nested"] = {"reward": 1}
    assert C.capacity_result_problems(result, packet=packet)


def test_packet_review_authorizes_only_one_capacity_attempt():
    packet = _packet()
    claim = C.packet_review_claim(packet=packet, packet_sha256=PACKET_SHA)
    assert claim["one_capacity_execution_authorized"] is True
    assert claim["screen_execution_authorized"] is False
    assert claim["resume_execution_authorized"] is False
    assert claim["aggregate_execution_authorized"] is False
    assert claim["strength_claim"] is False
    assert C.IMPLEMENTATION_REVIEW_PREFIX != C.PACKET_REVIEW_PREFIX


def test_receipt_binds_packet_admission_result_and_closes_later_authority():
    packet = _packet()
    review = {"commit": "8" * 40, "marker_sha256": "9" * 64}
    result = _result()
    receipt = C.receipt_payload(
        packet=packet, packet_sha256=PACKET_SHA, packet_review=review,
        admission_sha256="d" * 64, result_sha256="e" * 64,
        result=result, invocation_id="invocation")
    unsigned = dict(receipt)
    assert unsigned.pop("internal_sha256") == C.digest(unsigned)
    assert receipt["capacity_result_review_authorized"] is True
    assert not any(receipt[name] for name in (
        "screen_packet_freeze_authorized", "screen_execution_authorized",
        "resume_execution_authorized", "aggregate_execution_authorized",
        "strength_claim", "production_deployment",
        "retry_or_extension_authorized"))
    assert C.receipt_problems(
        receipt, packet=packet, packet_sha256=PACKET_SHA,
        packet_review=review, admission_sha256="d" * 64,
        result_sha256="e" * 64, result=result,
        invocation_id="invocation") == []
    forged = copy.deepcopy(receipt)
    forged["screen_packet_freeze_authorized"] = True
    forged["internal_sha256"] = C.digest({
        key: value for key, value in forged.items()
        if key != "internal_sha256"})
    assert C.receipt_problems(
        forged, packet=packet, packet_sha256=PACKET_SHA,
        packet_review=review, admission_sha256="d" * 64,
        result_sha256="e" * 64, result=result,
        invocation_id="invocation")


def test_refusal_receipt_preserves_lane_timings_and_closes_all_later_authority():
    packet = _packet()
    review = {"commit": "8" * 40, "marker_sha256": "9" * 64}
    measurement = _result(seconds=10_000.0)
    projection = C.DESIGN.capacity_projection_details(
        measurement, expected_workers=C.DESIGN.MIN_WORKERS,
        runtime_profile_sha256=packet["runtime_profile_sha256"])
    assert projection["projected_wall_hours"] > \
        C.DESIGN.MAX_PLANNED_WALL_HOURS
    receipt = C.refusal_receipt_payload(
        packet=packet, packet_sha256=PACKET_SHA, packet_review=review,
        admission_sha256="d" * 64, measurement=measurement,
        projection=projection, invocation_id="a" * 32)
    assert receipt["measurement"]["lanes"] == measurement["lanes"]
    assert receipt["capacity_terminal_review_authorized"] is True
    assert not any(receipt[name] for name in (
        "screen_packet_freeze_authorized", "screen_execution_authorized",
        "resume_execution_authorized", "aggregate_execution_authorized",
        "strength_claim", "production_deployment",
        "retry_or_extension_authorized"))
    assert C.refusal_receipt_problems(
        receipt, packet=packet, packet_sha256=PACKET_SHA,
        packet_review=review, admission_sha256="d" * 64,
        measurement=measurement, projection=projection,
        invocation_id="a" * 32) == []
    forged = copy.deepcopy(receipt)
    forged["measurement"]["lanes"][0]["elapsed_seconds"] += 1
    forged["internal_sha256"] = C.digest({
        key: value for key, value in forged.items()
        if key != "internal_sha256"})
    assert C.refusal_receipt_problems(
        forged, packet=packet, packet_sha256=PACKET_SHA,
        packet_review=review, admission_sha256="d" * 64,
        measurement=measurement, projection=projection,
        invocation_id="a" * 32)


def test_run_publishes_score_free_refusal_receipt_before_over_cap_exit(
        tmp_path, monkeypatch):
    packet = _packet()
    review = {"commit": "8" * 40, "marker_sha256": "9" * 64}
    paths = {
        "PACKET_PATH": tmp_path / "packet.json",
        "PACKET_REVIEW_PATH": tmp_path / "packet-review.md",
        "ADMISSION_PATH": tmp_path / "admission.json",
        "RESULT_PATH": tmp_path / "capacity.json",
        "RECEIPT_PATH": tmp_path / "execution-receipt.json",
        "REFUSAL_RECEIPT_PATH": tmp_path / "capacity-refusal-receipt.json",
    }
    for name, path in paths.items():
        monkeypatch.setattr(C, name, path)
    monkeypatch.setattr(C, "require_fresh_process", lambda: None)
    monkeypatch.setattr(C, "require_clean_exact_git", lambda git: None)
    monkeypatch.setattr(C, "require_systemd", lambda: "a" * 32)
    monkeypatch.setattr(C, "load_packet", lambda *args, **kwargs: packet)
    monkeypatch.setattr(C, "runtime_snapshot", lambda git: packet["runtime"])
    monkeypatch.setattr(C, "require_frozen_runtime_inputs", lambda value: None)
    monkeypatch.setattr(
        C, "canonical_review_record",
        lambda **kwargs: (review, b"review marker\n"))
    monkeypatch.setattr(C, "measure_capacity",
                        lambda value: _result(seconds=10_000.0))
    args = SimpleNamespace(
        expected_git=GIT, packet=paths["PACKET_PATH"],
        expected_packet_sha256=PACKET_SHA,
        packet_review_commit=review["commit"],
        admission=paths["ADMISSION_PATH"], result=paths["RESULT_PATH"],
        receipt=paths["RECEIPT_PATH"],
        refusal_receipt=paths["REFUSAL_RECEIPT_PATH"])
    with pytest.raises(C.CapacityRefused, match="planned wall cap"):
        C.run_command(args)
    assert paths["REFUSAL_RECEIPT_PATH"].is_file()
    refusal = json.loads(paths["REFUSAL_RECEIPT_PATH"].read_text())
    assert refusal["status"] == "REFUSED_CAPACITY_PROJECTION"
    assert len(refusal["measurement"]["lanes"]) == 16
    assert not paths["RESULT_PATH"].exists()
    assert not paths["RECEIPT_PATH"].exists()


def test_admission_is_one_shot_capacity_only_and_closed():
    packet = _packet()
    review = {"commit": "8" * 40, "marker_sha256": "9" * 64}
    value = {
        "schema": C.ADMISSION_SCHEMA, "run_id": C.RUN_ID, "git": GIT,
        "packet_sha256": PACKET_SHA,
        "packet_review_commit": review["commit"],
        "packet_review_marker_sha256": review["marker_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "systemd_invocation_id": "invocation", "nonce": "a" * 64,
        "created_time_ns": 1,
        "one_capacity_execution_authorized": True,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False, "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = C.digest(value)
    assert C.admission_problems(
        value, packet=packet, packet_sha256=PACKET_SHA,
        review=review, invocation_id="invocation") == []
    for field in ("screen_execution_authorized",
                  "resume_execution_authorized",
                  "aggregate_execution_authorized", "strength_claim"):
        forged = copy.deepcopy(value)
        forged[field] = True
        forged.pop("internal_sha256")
        forged["internal_sha256"] = C.digest(forged)
        assert C.admission_problems(
            forged, packet=packet, packet_sha256=PACKET_SHA,
            review=review, invocation_id="invocation")


def test_strict_json_refuses_duplicate_and_nonfinite_values():
    with pytest.raises(ValueError, match="duplicate"):
        C.strict_json(b'{"x":1,"x":2}')
    with pytest.raises(ValueError, match="nonfinite"):
        C.strict_json(b'{"x":NaN}')


def test_exclusive_publication_refuses_reuse_and_leaves_no_partial(tmp_path):
    path = tmp_path / "value.json"
    C.write_exclusive(path, {"value": 1})
    assert path.read_bytes() == C.canonical({"value": 1})
    assert path.stat().st_nlink == 1
    assert path.stat().st_mode & 0o222 == 0
    assert not Path(str(path) + ".partial").exists()
    with pytest.raises(C.CapacityRefused, match="existing"):
        C.write_exclusive(path, {"value": 2})


def test_systemd_gate_refuses_unowned_process(monkeypatch):
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    with pytest.raises(C.CapacityRefused, match="systemd"):
        C.require_systemd()


def test_systemd_invocation_uses_unit_name_to_invocation_id(tmp_path):
    invocation = "a" * 32
    live = tmp_path / f"invocation:{C.SYSTEMD_UNIT}"
    os.symlink(invocation, live)

    assert C._systemd_invocation_exists(invocation, units_dir=tmp_path)
    assert not C._systemd_invocation_exists("b" * 32, units_dir=tmp_path)
    assert not C._systemd_invocation_exists("A" * 32, units_dir=tmp_path)
    assert not C._systemd_invocation_exists("short", units_dir=tmp_path)
    assert not C._systemd_invocation_exists(
        invocation, unit="other.service", units_dir=tmp_path)


def test_systemd_invocation_refuses_spent_inverse_shape(tmp_path):
    invocation = "a" * 32
    os.symlink(C.SYSTEMD_UNIT, tmp_path / f"invocation:{invocation}")

    assert not C._systemd_invocation_exists(invocation, units_dir=tmp_path)


def test_fresh_process_refuses_preloaded_shengji_dependency(monkeypatch):
    monkeypatch.setattr(
        C, "PRELOADED_SHENGJI_MODULES", ("shengji.engine.fast",))
    with pytest.raises(C.CapacityRefused, match="unpreloaded"):
        C.require_fresh_process()


def test_systemd_gate_pins_one_shot_service_and_cgroup(monkeypatch):
    invocation = "a" * 32
    group = "/system.slice/" + C.SYSTEMD_UNIT
    properties = {
        "Id": C.SYSTEMD_UNIT, "InvocationID": invocation,
        "LoadState": "loaded", "ActiveState": "active",
        "SubState": "running", "Type": "exec", "Restart": "no",
        "KillMode": "control-group", "UID": "[not set]",
        "ControlGroup": group, "WorkingDirectory": str(C.REPO),
        "NRestarts": "0",
    }
    monkeypatch.setenv("INVOCATION_ID", invocation)
    monkeypatch.setattr(C.os, "geteuid", lambda: 0)
    monkeypatch.setattr(C, "_systemd_invocation_exists", lambda value: True)
    monkeypatch.setattr(C, "_systemd_properties", lambda unit: properties)
    monkeypatch.setattr(C, "_current_cgroups", lambda: [f"0::{group}"])
    assert C.require_systemd() == invocation

    properties["Restart"] = "always"
    with pytest.raises(C.CapacityRefused, match="one-shot"):
        C.require_systemd()
    properties["Restart"] = "no"
    properties["KillMode"] = "process"
    with pytest.raises(C.CapacityRefused, match="one-shot"):
        C.require_systemd()
    properties["KillMode"] = "control-group"
    monkeypatch.setattr(C, "_current_cgroups", lambda: ["0::/other"])
    with pytest.raises(C.CapacityRefused, match="outside"):
        C.require_systemd()


def test_frozen_runtime_requires_root(monkeypatch):
    monkeypatch.setattr(C.os, "geteuid", lambda: 501)
    with pytest.raises(C.CapacityRefused, match="root-owned"):
        C.require_frozen_runtime_inputs(_runtime())


def test_stable_reader_refuses_symlink_and_hardlink(tmp_path):
    source = tmp_path / "source.json"
    source.write_bytes(b"{}\n")
    alias = tmp_path / "alias.json"
    alias.symlink_to(source)
    with pytest.raises(C.CapacityRefused):
        C.require_regular_unlinked(alias, label="symlink")

    hardlink = tmp_path / "hardlink.json"
    os.link(source, hardlink)
    with pytest.raises(C.CapacityRefused, match="linked"):
        C.require_regular_unlinked(source, label="hardlink")


def test_stable_reader_refuses_path_swap_during_read(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_bytes(b'{"value":"authenticated"}\n')
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b'{"value":"swapped"}\n')
    real_read = C.os.read
    swapped = False

    def racing_read(descriptor, size):
        nonlocal swapped
        raw = real_read(descriptor, size)
        if not swapped:
            swapped = True
            os.replace(replacement, source)
        return raw

    monkeypatch.setattr(C.os, "read", racing_read)
    with pytest.raises(C.CapacityRefused, match="unstable"):
        C.require_regular_unlinked(source, label="racing input")


def test_runtime_shadow_scan_refuses_ignored_loadable_code(tmp_path,
                                                           monkeypatch):
    server = tmp_path / "server"
    (server / "shengji").mkdir(parents=True)
    tracked = server / "shengji/tracked.py"
    tracked.write_text("tracked\n")
    native = server / "shengji/_fast.so"
    native.write_bytes(b"native")
    shadow = server / "shengji/__pycache__/shadow.pyc"
    shadow.parent.mkdir()
    shadow.write_bytes(b"shadow")
    monkeypatch.setattr(C, "REPO", tmp_path)
    monkeypatch.setattr(C, "SERVER", server)
    monkeypatch.setattr(
        C, "git", lambda *args: "server/shengji/tracked.py")
    assert C._shadow_paths(native) == [
        "server/shengji/__pycache__/shadow.pyc"]


def test_review_marker_requires_claude_commit_and_append_only_ledger(
        monkeypatch):
    commit = "8" * 40
    parent = "9" * 40
    claim = C.implementation_review_claim(expected_git=GIT)
    marker = C._canonical_marker(C.IMPLEMENTATION_REVIEW_PREFIX, claim)
    before = b"prior ledger\n"
    current = before + marker

    class Result:
        returncode = 0

    monkeypatch.setattr(C.subprocess, "run", lambda *a, **k: Result())

    def fake_git(*args):
        joined = " ".join(args)
        if "--format=%P" in joined:
            return parent
        if "--format=%an" in joined or "--format=%cn" in joined:
            return C.REVIEWER_NAME
        if "--format=%ae" in joined or "--format=%ce" in joined:
            return C.REVIEWER_EMAIL
        if "--format=%B" in joined:
            return C.REVIEWER_SESSION_TRAILER + "session"
        if args and args[0] == "diff-tree":
            return C.REVIEW_LEDGER
        raise AssertionError(args)

    blobs = {
        f"{commit}:{C.REVIEW_LEDGER}": current,
        f"{parent}:{C.REVIEW_LEDGER}": before,
        f"{C.CANONICAL_REVIEW_REF}:{C.REVIEW_LEDGER}": current + b"later\n",
    }
    monkeypatch.setattr(C, "git", fake_git)
    monkeypatch.setattr(C, "git_bytes", lambda *args: blobs[args[-1]])
    review, observed = C.canonical_review_record(
        commit=commit, prefix=C.IMPLEMENTATION_REVIEW_PREFIX,
        expected=claim, label="test review")
    assert observed == marker
    assert review["marker_sha256"] == C.sha256_bytes(marker)

    blobs[f"{C.CANONICAL_REVIEW_REF}:{C.REVIEW_LEDGER}"] = \
        b"rewritten\n" + marker
    with pytest.raises(C.CapacityRefused, match="append-only"):
        C.canonical_review_record(
            commit=commit, prefix=C.IMPLEMENTATION_REVIEW_PREFIX,
            expected=claim, label="test review")


def test_review_marker_refuses_commit_that_rewrites_parent(monkeypatch):
    commit = "8" * 40
    parent = "9" * 40
    claim = C.implementation_review_claim(expected_git=GIT)
    marker = C._canonical_marker(C.IMPLEMENTATION_REVIEW_PREFIX, claim)

    class Result:
        returncode = 0

    monkeypatch.setattr(C.subprocess, "run", lambda *a, **k: Result())

    def fake_git(*args):
        joined = " ".join(args)
        if "--format=%P" in joined:
            return parent
        if "--format=%an" in joined or "--format=%cn" in joined:
            return C.REVIEWER_NAME
        if "--format=%ae" in joined or "--format=%ce" in joined:
            return C.REVIEWER_EMAIL
        if "--format=%B" in joined:
            return C.REVIEWER_SESSION_TRAILER
        if args and args[0] == "diff-tree":
            return C.REVIEW_LEDGER
        raise AssertionError(args)

    rewritten = b"rewritten parent history\n" + marker
    blobs = {
        f"{commit}:{C.REVIEW_LEDGER}": rewritten,
        f"{parent}:{C.REVIEW_LEDGER}": b"original parent history\n",
        f"{C.CANONICAL_REVIEW_REF}:{C.REVIEW_LEDGER}":
            rewritten + b"later\n",
    }
    monkeypatch.setattr(C, "git", fake_git)
    monkeypatch.setattr(C, "git_bytes", lambda *args: blobs[args[-1]])
    with pytest.raises(C.CapacityRefused, match="append-only"):
        C.canonical_review_record(
            commit=commit, prefix=C.IMPLEMENTATION_REVIEW_PREFIX,
            expected=claim, label="test review")


def test_review_marker_refuses_duplicate_at_canonical_tip(monkeypatch):
    commit = "8" * 40
    parent = "9" * 40
    claim = C.implementation_review_claim(expected_git=GIT)
    marker = C._canonical_marker(C.IMPLEMENTATION_REVIEW_PREFIX, claim)
    before = b"prior ledger\n"
    current = before + marker

    class Result:
        returncode = 0

    monkeypatch.setattr(C.subprocess, "run", lambda *a, **k: Result())

    def fake_git(*args):
        joined = " ".join(args)
        if "--format=%P" in joined:
            return parent
        if "--format=%an" in joined or "--format=%cn" in joined:
            return C.REVIEWER_NAME
        if "--format=%ae" in joined or "--format=%ce" in joined:
            return C.REVIEWER_EMAIL
        if "--format=%B" in joined:
            return C.REVIEWER_SESSION_TRAILER
        if args and args[0] == "diff-tree":
            return C.REVIEW_LEDGER
        raise AssertionError(args)

    blobs = {
        f"{commit}:{C.REVIEW_LEDGER}": current,
        f"{parent}:{C.REVIEW_LEDGER}": before,
        f"{C.CANONICAL_REVIEW_REF}:{C.REVIEW_LEDGER}": current + marker,
    }
    monkeypatch.setattr(C, "git", fake_git)
    monkeypatch.setattr(C, "git_bytes", lambda *args: blobs[args[-1]])
    with pytest.raises(C.CapacityRefused, match="provenance drift"):
        C.canonical_review_record(
            commit=commit, prefix=C.IMPLEMENTATION_REVIEW_PREFIX,
            expected=claim, label="test review")


def test_request_text_in_parent_cannot_self_authorize(monkeypatch):
    commit = "8" * 40
    parent = "9" * 40
    claim = C.implementation_review_claim(expected_git=GIT)
    marker = C._canonical_marker(C.IMPLEMENTATION_REVIEW_PREFIX, claim)

    class Result:
        returncode = 0

    monkeypatch.setattr(C.subprocess, "run", lambda *a, **k: Result())
    monkeypatch.setattr(C, "git", lambda *args: (
        parent if "--format=%P" in " ".join(args)
        else C.REVIEWER_NAME if any(
            field in " ".join(args) for field in ("--format=%an", "--format=%cn"))
        else C.REVIEWER_EMAIL if any(
            field in " ".join(args) for field in ("--format=%ae", "--format=%ce"))
        else C.REVIEWER_SESSION_TRAILER if "--format=%B" in " ".join(args)
        else C.REVIEW_LEDGER))
    monkeypatch.setattr(C, "git_bytes", lambda *args: marker)
    with pytest.raises(C.CapacityRefused, match="provenance drift"):
        C.canonical_review_record(
            commit=commit, prefix=C.IMPLEMENTATION_REVIEW_PREFIX,
            expected=claim, label="test review")


def test_retired_v1_review_marker_cannot_authorize_v2(monkeypatch):
    commit = "8" * 40
    parent = "9" * 40
    claim = C.implementation_review_claim(expected_git=GIT)
    retired = C._canonical_marker(
        C.RETIRED_IMPLEMENTATION_REVIEW_PREFIX, claim)
    before = b"prior ledger\n"
    current = before + retired

    class Result:
        returncode = 0

    monkeypatch.setattr(C.subprocess, "run", lambda *a, **k: Result())

    def fake_git(*args):
        joined = " ".join(args)
        if "--format=%P" in joined:
            return parent
        if "--format=%an" in joined or "--format=%cn" in joined:
            return C.REVIEWER_NAME
        if "--format=%ae" in joined or "--format=%ce" in joined:
            return C.REVIEWER_EMAIL
        if "--format=%B" in joined:
            return C.REVIEWER_SESSION_TRAILER
        if args and args[0] == "diff-tree":
            return C.REVIEW_LEDGER
        raise AssertionError(args)

    blobs = {
        f"{commit}:{C.REVIEW_LEDGER}": current,
        f"{parent}:{C.REVIEW_LEDGER}": before,
        f"{C.CANONICAL_REVIEW_REF}:{C.REVIEW_LEDGER}": current,
    }
    monkeypatch.setattr(C, "git", fake_git)
    monkeypatch.setattr(C, "git_bytes", lambda *args: blobs[args[-1]])
    with pytest.raises(C.CapacityRefused, match="provenance drift"):
        C.canonical_review_record(
            commit=commit, prefix=C.IMPLEMENTATION_REVIEW_PREFIX,
            expected=claim, label="test review")


def test_capacity_run_has_no_screen_resume_or_aggregate_cli():
    choices = C.parser()._subparsers._group_actions[0].choices
    assert set(choices) == {"freeze", "verify", "run-capacity"}
