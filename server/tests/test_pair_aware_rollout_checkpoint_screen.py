"""Adversarial contracts for the checkpointed Pair whole-round screen."""
from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_aware_rollout_checkpoint_screen as SCREEN  # noqa: E402


SHA = "a" * 64
GIT = "b" * 40


def _runtime(monkeypatch):
    sources = {"server/test.py": "0" * 64}
    monkeypatch.setattr(SCREEN, "source_sha256s", lambda: sources)
    return {
        "git": GIT,
        "hostname": "perf",
        "machine": "x86_64",
        "platform": "Linux",
        "cpu_count": 16,
        "memory_bytes": 32 * 1024 ** 3,
        "python": {
            "executable": "/usr/bin/python3.14",
            "resolved": "/usr/bin/python3.14",
            "version": "3.14.0",
            "sha256": "1" * 64,
            "soabi": "cpython-314-x86_64-linux-gnu",
        },
        "native": {"path": "/tmp/_fast.so", "sha256": "2" * 64},
        "systemd_unit": {
            "unit": SCREEN.SYSTEMD_UNIT,
            "sha256": SCREEN.sha256_bytes(SCREEN.systemd_unit_bytes()),
        },
        "fast_enabled": True,
        "fast_environment": True,
        "fast_routing_active": True,
        "strict_voids": True,
        "dont_write_bytecode": True,
        "python_hash_seed": "0",
        "process_nice": 5,
        "boot_id": "boot",
        "module_origins": {
            "controller": "/repo/capacity.py",
            "design": "/repo/design.py",
            "duel": "/repo/duel.py",
            "fast": "/repo/fast.py",
            "native": "/tmp/_fast.so",
            "screen_controller": str(SCREEN.SCRIPT),
        },
        "loadable_shadows": [],
        "source_sha256s": sources,
    }


def _review():
    return {
        "commit": "3" * 40,
        "parent_commit": "4" * 40,
        "ledger_sha256": "5" * 64,
        "marker_sha256": "6" * 64,
        "claim": SCREEN.implementation_review_claim(expected_git=GIT),
    }


def _capacity():
    return {
        "source_git": SCREEN.SOURCE_GIT,
        "packet_sha256": SCREEN.CAPACITY_PACKET_SHA256,
        "admission_sha256": SCREEN.CAPACITY_ADMISSION_SHA256,
        "result_sha256": SCREEN.CAPACITY_RESULT_SHA256,
        "receipt_sha256": SCREEN.CAPACITY_RECEIPT_SHA256,
        "runtime_profile_sha256": SCREEN.CAPACITY_RUNTIME_PROFILE_SHA256,
        "packet_review_commit": SCREEN.CAPACITY_PACKET_REVIEW_COMMIT,
        "terminal_review": {
            "commit": SCREEN.CAPACITY_TERMINAL_REVIEW_COMMIT,
            "parent_commit": SCREEN.CAPACITY_TERMINAL_REVIEW_PARENT,
            "ledger_sha256": "7" * 64,
            "append_sha256": SCREEN.CAPACITY_TERMINAL_APPEND_SHA256,
        },
        "projection": {
            "measured_slowest_lane_seconds_per_cluster": 256.5,
            "planning_seconds_per_cluster": 384.75,
            "projected_wall_hours": 47.88,
            "microshard_timeout_seconds": 12_612.0,
        },
        "runtime_compatibility": {
            "same_host_and_boot": True,
            "same_python": True,
            "same_native_bytes": True,
            "same_compiled_strict_flags_and_nice": True,
            "capacity_source_paths": 70,
            "capacity_sources_exact_subset_of_screen": True,
            "screen_source_paths": 71,
        },
    }


def _packet(monkeypatch):
    runtime = _runtime(monkeypatch)
    return SCREEN.packet_payload(
        expected_git=GIT, runtime=runtime,
        implementation_review=_review(), capacity=_capacity())


class FakeCore:
    LABEL_ORDER = ("treatment", "matched_null", "champion")
    ROOT_WORLDS = 30
    REPORT_WORLDS = 300
    PAIR_AWARE_COUNTER_FIELDS = ("calls", "triggers")

    @staticmethod
    def counters(_records):
        return {
            "search_secs": 0.0,
            "sample_attempts": 330,
            "accepted_worlds": 330,
            "failed_worlds": 0,
            "searches": 1,
        }

    @staticmethod
    def telemetry_problems(value, *, expected_mode):
        expected = {"mode": expected_mode, "calls": 0, "triggers": 0}
        return [] if value == expected else ["telemetry drift"]


def _dose(role="attacker"):
    return {
        "shared_prefix_plays": 1,
        "root_action_changed": True,
        "change_play_index": 1,
        "change_phase": "early",
        "change_role": role,
    }


def _valid_outcome(monkeypatch, *, clusters=2):
    monkeypatch.setattr(SCREEN, "MICROSHARD_CLUSTERS", clusters)
    packet = _packet(monkeypatch)
    rows = []
    for index in range(clusters):
        rows.append({
            "cluster_index": index,
            "seed": SCREEN.SCREEN_SEED0 + SCREEN.STREAM_STRIDE * index,
            "level_utility": {
                "treatment": [1, 1],
                "matched_null": [0, 0],
                "champion": [0, 0],
            },
            "won": {
                "treatment": [1, 1],
                "matched_null": [0, 0],
                "champion": [0, 0],
            },
            "natural_dose": [_dose("attacker"), _dose("defender")],
        })
    counts = {}
    for label, mode in (("treatment", "treatment"),
                        ("matched_null", "matched_null"),
                        ("champion", "off")):
        counts[label] = {
            "records": 2 * clusters,
            "arm": FakeCore.counters([]),
            "opp": FakeCore.counters([]),
            "arm_pair": {"mode": mode, "calls": 0, "triggers": 0},
            "opp_pair": {"mode": "off", "calls": 0, "triggers": 0},
        }
    value = {
        "schema": SCREEN.OUTCOME_SCHEMA,
        "run_id": SCREEN.RUN_ID,
        "git": packet["git"],
        "packet_sha256": SHA,
        "packet_internal_sha256": packet["internal_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "microshard_index": 0,
        "cluster_index_start": 0,
        "clusters": clusters,
        "seed0": SCREEN.SCREEN_SEED0,
        "stream_stride": SCREEN.STREAM_STRIDE,
        "elapsed_seconds": 1.0,
        "cluster_rows": rows,
        "counts": counts,
        "natural_dose": SCREEN.dose_summary(rows),
        "exact_work_complete": True,
        "aggregate_execution_authorized": False,
        "outcome_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = SCREEN.digest(value)
    return packet, value


def _resign(value):
    value["internal_sha256"] = SCREEN.digest({
        key: child for key, child in value.items()
        if key != "internal_sha256"
    })


def test_reviewed_geometry_and_capacity_budget_are_exact():
    assert SCREEN.SCREEN_CLUSTERS == 7_168
    assert SCREEN.MICROSHARD_CLUSTERS == 32
    assert SCREEN.MICROSHARDS == 224
    assert SCREEN.WORKERS == 16
    assert SCREEN.SCREEN_CLUSTERS == (
        SCREEN.MICROSHARDS * SCREEN.MICROSHARD_CLUSTERS)
    assert _capacity()["projection"]["projected_wall_hours"] < 52.0


def test_capacity_terminal_review_is_exact_and_append_only():
    value = SCREEN.capacity_terminal_review()
    assert value["commit"] == SCREEN.CAPACITY_TERMINAL_REVIEW_COMMIT
    assert value["append_sha256"] == SCREEN.CAPACITY_TERMINAL_APPEND_SHA256


def test_implementation_review_can_freeze_only():
    claim = SCREEN.implementation_review_claim(expected_git=GIT)
    assert claim["screen_packet_freeze_authorized"] is True
    assert claim["screen_execution_authorized"] is False
    assert claim["resume_execution_authorized"] is False
    assert claim["aggregate_execution_authorized"] is False
    assert claim["outcome_access_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["production_deployment"] is False


def test_implementation_claim_command_emits_one_canonical_raw_line(
        monkeypatch, capsysbinary):
    monkeypatch.setattr(SCREEN, "require_fresh_process", lambda: None)
    monkeypatch.setattr(SCREEN, "require_clean_exact_git", lambda _git: None)
    args = SimpleArgs(expected_git=GIT)
    SCREEN.implementation_review_claim_command(args)
    expected = (SCREEN.IMPLEMENTATION_REVIEW_PREFIX.encode()
                + SCREEN.canonical(
                    SCREEN.implementation_review_claim(expected_git=GIT)))
    assert capsysbinary.readouterr().out == expected


class SimpleArgs:
    def __init__(self, **values):
        self.__dict__.update(values)


def test_packet_review_is_distinct_and_bounded_to_one_screen(monkeypatch):
    packet = _packet(monkeypatch)
    claim = SCREEN.packet_review_claim(packet=packet, packet_sha256=SHA)
    assert SCREEN.PACKET_REVIEW_PREFIX != SCREEN.IMPLEMENTATION_REVIEW_PREFIX
    assert claim["one_screen_execution_authorized"] is True
    assert claim["resume_execution_authorized"] is False
    assert claim["aggregate_execution_authorized"] is False
    assert claim["outcome_access_authorized"] is False


def test_capacity_runtime_must_match_screen_runtime(monkeypatch):
    runtime = _runtime(monkeypatch)
    capacity_runtime = copy.deepcopy(runtime)
    capacity_runtime["source_sha256s"] = {"server/test.py": "0" * 64}
    compatible = SCREEN.capacity_runtime_compatibility(
        capacity_runtime, runtime)
    assert compatible["same_host_and_boot"] is True
    assert compatible["same_native_bytes"] is True
    drift = copy.deepcopy(capacity_runtime)
    drift["native"]["sha256"] = "f" * 64
    with pytest.raises(SCREEN.ScreenRefused, match="compatibility"):
        SCREEN.capacity_runtime_compatibility(drift, runtime)


def test_capacity_packet_validator_is_path_independent_and_closed(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime["git"] = SCREEN.SOURCE_GIT
    monkeypatch.setattr(
        SCREEN, "CAPACITY_RUNTIME_PROFILE_SHA256", SCREEN.digest(runtime))
    packet = {
        "schema": SCREEN.CAPACITY.PACKET_SCHEMA,
        "run_id": SCREEN.DESIGN.CAPACITY_RUN_ID,
        "git": SCREEN.SOURCE_GIT,
        "design_git": SCREEN.DESIGN_GIT,
        "design_source_sha256": SCREEN.DESIGN_SOURCE_SHA256,
        "implementation_review": {
            "commit": "1" * 40,
            "parent_commit": "2" * 40,
            "ledger_sha256": "3" * 64,
            "marker_sha256": "4" * 64,
            "claim": {"reviewed": True},
        },
        "runtime": runtime,
        "runtime_profile_sha256": SCREEN.digest(runtime),
        "capacity": {
            "seed0": SCREEN.DESIGN.CAPACITY_SEED0,
            "workers": SCREEN.DESIGN.MIN_WORKERS,
            "clusters_per_worker":
                SCREEN.DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
            "stream_stride": SCREEN.DESIGN.STREAM_STRIDE,
            "all_workers_start_concurrently": True,
            "outcomes_published": False,
        },
        "one_capacity_execution_authorized": False,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    packet["internal_sha256"] = SCREEN.digest(packet)
    assert SCREEN.capacity_packet_problems(packet) == []
    packet["screen_execution_authorized"] = True
    _resign(packet)
    assert SCREEN.capacity_packet_problems(packet)


def test_packet_is_closed_and_all_authority_false(monkeypatch):
    packet = _packet(monkeypatch)
    assert SCREEN.packet_problems(packet, expected_git=GIT) == []
    for key in (
            "one_screen_execution_authorized", "resume_execution_authorized",
            "aggregate_execution_authorized", "outcome_access_authorized",
            "strength_claim", "production_promotion", "production_deployment",
            "retry_or_extension_authorized"):
        assert packet[key] is False


@pytest.mark.parametrize("mutation", [
    lambda packet: packet.update(strength_claim=True),
    lambda packet: packet["execution"].update(workers=15),
    lambda packet: packet["execution"].update(automatic_retry=True),
    lambda packet: packet["capacity_evidence"]["projection"].update(
        projected_wall_hours=52.01),
    lambda packet: packet["science"].update(clusters=7_167),
    lambda packet: packet.update(foreign_authority=True),
])
def test_rehashed_packet_mutations_refuse(monkeypatch, mutation):
    packet = _packet(monkeypatch)
    mutation(packet)
    _resign(packet)
    assert SCREEN.packet_problems(packet, expected_git=GIT)


def test_systemd_unit_is_one_shot_and_campaign_bounded():
    unit = SCREEN.systemd_unit_bytes().decode()
    assert "User=root" in unit
    assert "Nice=5" in unit
    assert "Restart=no" in unit
    assert "KillMode=control-group" in unit
    assert "RuntimeMaxSec=52h" in unit
    assert "/usr/bin/python3.14 -I -P -B" in unit
    assert "run-screen" in unit
    assert "resume" not in unit
    assert "aggregate" not in unit


def test_strict_json_rejects_duplicate_and_nonfinite():
    with pytest.raises(ValueError, match="duplicate"):
        SCREEN.strict_json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError, match="nonfinite"):
        SCREEN.strict_json(b'{"a":NaN}')


def test_admission_is_closed_and_cannot_resume(monkeypatch):
    packet = _packet(monkeypatch)
    review = {"commit": "8" * 40, "marker_sha256": "9" * 64}
    value = SCREEN.admission_payload(
        packet=packet, packet_sha256=SHA, packet_review=review,
        invocation_id="0" * 32)
    assert SCREEN.admission_problems(
        value, packet=packet, packet_sha256=SHA,
        packet_review=review, invocation_id="0" * 32) == []
    value["resume_execution_authorized"] = True
    _resign(value)
    assert SCREEN.admission_problems(
        value, packet=packet, packet_sha256=SHA,
        packet_review=review, invocation_id="0" * 32)


def test_receipt_is_score_free_and_closed(monkeypatch):
    packet = _packet(monkeypatch)
    receipt = SCREEN.receipt_payload(
        packet=packet, packet_sha256=SHA, microshard_index=3,
        outcome_raw=b'{"sealed":true}\n', elapsed_seconds=3.5)
    assert SCREEN.receipt_problems(
        receipt, packet=packet, packet_sha256=SHA,
        microshard_index=3) == []
    assert SCREEN._forbidden_keys(receipt) == set()
    receipt["nested"] = {"winner": 1}
    _resign(receipt)
    assert SCREEN.receipt_problems(
        receipt, packet=packet, packet_sha256=SHA,
        microshard_index=3)
    receipt = SCREEN.receipt_payload(
        packet=packet, packet_sha256=SHA, microshard_index=3,
        outcome_raw=b'{"sealed":true}\n', elapsed_seconds=3.5)
    assert receipt["outcomes_opened_by_supervisor"] is False
    receipt.pop("outcomes_opened_by_supervisor")
    _resign(receipt)
    assert SCREEN.receipt_problems(
        receipt, packet=packet, packet_sha256=SHA,
        microshard_index=3)
    receipt["outcomes_opened_by_supervisor"] = True
    _resign(receipt)
    assert SCREEN.receipt_problems(
        receipt, packet=packet, packet_sha256=SHA,
        microshard_index=3)


def test_dose_summary_requires_exact_changed_and_unchanged_shapes():
    rows = [{"natural_dose": [_dose("attacker"), _dose("defender")]}]
    summary = SCREEN.dose_summary(rows)
    assert summary["root_action_changes"] == 2
    assert summary["changes_by_role"] == {"attacker": 1, "defender": 1}
    rows[0]["natural_dose"][0]["change_play_index"] = 2
    with pytest.raises(SCREEN.ScreenRefused, match="changed-dose"):
        SCREEN.dose_summary(rows)


def test_valid_outcome_and_load_bearing_mutations(monkeypatch):
    packet, value = _valid_outcome(monkeypatch)
    SCREEN.validate_outcome(
        value, packet=packet, packet_sha256=SHA,
        microshard_index=0, core=FakeCore)
    mutations = []
    changed = copy.deepcopy(value)
    changed["cluster_rows"][0]["level_utility"]["matched_null"] = [1, 0]
    mutations.append(changed)
    changed = copy.deepcopy(value)
    changed["counts"]["treatment"]["arm"]["sample_attempts"] = 329
    mutations.append(changed)
    changed = copy.deepcopy(value)
    changed["outcome_access_authorized"] = True
    mutations.append(changed)
    changed = copy.deepcopy(value)
    changed["cluster_rows"][0]["won"]["treatment"] = [True, 1]
    mutations.append(changed)
    changed = copy.deepcopy(value)
    changed["foreign"] = 1
    mutations.append(changed)
    for mutation in mutations:
        _resign(mutation)
        with pytest.raises(SCREEN.ScreenRefused):
            SCREEN.validate_outcome(
                mutation, packet=packet, packet_sha256=SHA,
                microshard_index=0, core=FakeCore)


def test_atomic_bundle_publication_and_collision_preservation(
        tmp_path, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid())
    path = tmp_path / "microshard-000"
    partial = tmp_path / "microshard-000.partial"
    outcome = {"sealed": True}
    receipt = {"score_free": True}
    SCREEN.publish_bundle(path=path, partial=partial,
                          outcome=outcome, receipt=receipt)
    assert path.is_dir() and not partial.exists()
    assert stat_mode(path) == 0o555
    assert stat_mode(path / "outcome.json") == 0o444
    before = (path / "outcome.json").read_bytes()
    with pytest.raises(SCREEN.ScreenRefused, match="slot already consumed"):
        SCREEN.publish_bundle(path=path, partial=partial,
                              outcome={"sealed": False}, receipt=receipt)
    assert (path / "outcome.json").read_bytes() == before


def test_review_and_admission_publish_as_one_atomic_gate(tmp_path, monkeypatch):
    gate = tmp_path / "execution.consumed"
    partial = tmp_path / "execution.partial"
    monkeypatch.setattr(SCREEN, "GATE_PATH", gate)
    monkeypatch.setattr(SCREEN, "GATE_PARTIAL_PATH", partial)
    SCREEN.publish_execution_gate(
        marker=b"review\n", admission={"admitted": True})
    assert gate.is_dir() and not partial.exists()
    assert stat_mode(gate) == 0o555
    assert (gate / "packet-review-snapshot.md").read_bytes() == b"review\n"
    assert SCREEN.strict_json(
        (gate / "admission.json").read_bytes()) == {"admitted": True}
    with pytest.raises(SCREEN.ScreenRefused, match="already consumed"):
        SCREEN.publish_execution_gate(
            marker=b"different\n", admission={"admitted": False})


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_manifest_uses_receipts_only_and_matches_design(monkeypatch):
    packet = _packet(monkeypatch)
    monkeypatch.setattr(SCREEN, "MICROSHARDS", 3)
    monkeypatch.setattr(SCREEN, "MICROSHARD_CLUSTERS", 32)
    monkeypatch.setattr(SCREEN, "SCREEN_CLUSTERS", 96)
    monkeypatch.setattr(SCREEN.DESIGN, "MICROSHARDS", 3)
    monkeypatch.setattr(SCREEN.DESIGN, "SCREEN_CLUSTERS", 96)
    seen = []

    def receipt_only(*, packet, packet_sha256, microshard_index):
        seen.append(microshard_index)
        return {
            "cluster_index_start": microshard_index * 32,
            "seed0": SCREEN.SCREEN_SEED0
            + SCREEN.STREAM_STRIDE * microshard_index * 32,
            "clusters": 32,
            "outcome_sha256": f"{microshard_index + 1:064x}",
            "elapsed_seconds": float(microshard_index + 1),
            "campaign_runtime_profile_sha256":
                packet["runtime_profile_sha256"],
        }

    monkeypatch.setattr(SCREEN, "read_receipt_only", receipt_only)
    original = SCREEN.DESIGN.manifest_problems
    monkeypatch.setattr(SCREEN.DESIGN, "manifest_problems", lambda *a, **k: [])
    value = SCREEN.manifest_payload(packet=packet, packet_sha256=SHA)
    assert seen == [0, 1, 2]
    assert value["outcomes_opened"] is False
    assert value["aggregate_execution_authorized"] is False
    assert len(value["completed"]) == 3
    monkeypatch.setattr(SCREEN.DESIGN, "manifest_problems", original)


def test_supervisor_never_exceeds_worker_limit(tmp_path, monkeypatch):
    packet = _packet(monkeypatch)
    monkeypatch.setattr(SCREEN, "MICROSHARDS", 5)
    monkeypatch.setattr(SCREEN, "WORKERS", 2)
    monkeypatch.setattr(
        SCREEN, "LOG_PATHS",
        tuple(tmp_path / f"{index}.log" for index in range(5)))
    monkeypatch.setattr(SCREEN, "_child_argv", lambda **_kwargs: ["child"])
    alive = {"count": 0, "max": 0}

    class Process:
        def __init__(self, *_args, **_kwargs):
            self.done = False
            alive["count"] += 1
            alive["max"] = max(alive["max"], alive["count"])

        def poll(self):
            if not self.done:
                self.done = True
                alive["count"] -= 1
            return 0

        def terminate(self):
            self.done = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.done = True

    monkeypatch.setattr(SCREEN.subprocess, "Popen", Process)
    monkeypatch.setattr(SCREEN, "read_receipt_only", lambda **_kwargs: {})
    monkeypatch.setattr(SCREEN, "manifest_payload", lambda **_kwargs: {
        "completed": list(range(5))})
    monkeypatch.setattr(SCREEN, "write_exclusive", lambda *_args, **_kwargs: None)
    SCREEN.supervise(packet=packet, packet_sha256=SHA)
    assert alive["max"] == 2


def test_microshard_reauthenticates_live_runtime(monkeypatch):
    packet = _packet(monkeypatch)
    drifted = copy.deepcopy(packet["runtime"])
    drifted["boot_id"] = "different-boot"
    monkeypatch.setattr(SCREEN, "require_fresh_process", lambda: None)
    monkeypatch.setattr(SCREEN, "require_clean_exact_git", lambda _git: None)
    monkeypatch.setattr(SCREEN, "load_packet", lambda *_a, **_k: packet)
    monkeypatch.setattr(SCREEN, "require_systemd", lambda _sha: "0" * 32)
    monkeypatch.setattr(SCREEN, "runtime_snapshot", lambda _git: drifted)
    monkeypatch.setattr(
        SCREEN, "strict_object",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("worker reached admission before runtime refusal")))
    args = SimpleArgs(
        expected_git=GIT,
        packet=SCREEN.PACKET_PATH,
        expected_packet_sha256=SHA,
        admission=SCREEN.ADMISSION_PATH,
        microshard_index=0,
        out=SCREEN.BUNDLE_PATHS[0],
    )
    with pytest.raises(
            SCREEN.ScreenRefused,
            match="microshard runtime differs from packet"):
        SCREEN.run_microshard_command(args)


def test_run_admission_binds_the_live_runtime(monkeypatch):
    packet = _packet(monkeypatch)
    drifted = copy.deepcopy(packet["runtime"])
    drifted["native"]["sha256"] = "f" * 64
    monkeypatch.setattr(SCREEN, "require_fresh_process", lambda: None)
    monkeypatch.setattr(SCREEN, "require_clean_exact_git", lambda _git: None)
    monkeypatch.setattr(SCREEN, "load_packet", lambda *_a, **_k: packet)
    monkeypatch.setattr(SCREEN, "require_systemd", lambda _sha: "0" * 32)
    monkeypatch.setattr(SCREEN, "runtime_snapshot", lambda _git: drifted)
    monkeypatch.setattr(
        SCREEN, "require_frozen_runtime_inputs",
        lambda _runtime: (_ for _ in ()).throw(
            AssertionError("run reached frozen inputs before runtime refusal")))
    args = SimpleArgs(
        expected_git=GIT,
        packet=SCREEN.PACKET_PATH,
        expected_packet_sha256=SHA,
        packet_review_commit="c" * 40,
        admission=SCREEN.ADMISSION_PATH,
    )
    with pytest.raises(
            SCREEN.ScreenRefused,
            match="live screen runtime differs from packet"):
        SCREEN.run_screen_command(args)


def test_supervisor_manifest_never_opens_outcome_bytes(tmp_path, monkeypatch):
    packet = _packet(monkeypatch)
    outcome_raw = b'{"sealed":true}\n'
    receipt = SCREEN.receipt_payload(
        packet=packet, packet_sha256=SHA, microshard_index=0,
        outcome_raw=outcome_raw, elapsed_seconds=1.0)
    bundle = tmp_path / "microshard-000"
    bundle.mkdir()
    (bundle / "receipt.json").write_bytes(SCREEN.canonical(receipt))
    (bundle / "outcome.json").write_bytes(outcome_raw)
    for child in bundle.iterdir():
        child.chmod(0o444)
    bundle.chmod(0o555)

    real_lstat = Path.lstat
    real_read_bytes = Path.read_bytes

    def root_lstat(path):
        observed = list(real_lstat(path))
        observed[4] = 0
        return os.stat_result(observed)

    opened = []

    def receipt_only_bytes(path, **_kwargs):
        if path.name == "outcome.json":
            raise AssertionError("supervisor opened sealed outcome bytes")
        opened.append(path.name)
        return real_read_bytes(path)

    def guarded_read_bytes(path):
        if path.name == "outcome.json":
            raise AssertionError("supervisor opened sealed outcome bytes")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "lstat", root_lstat)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(SCREEN, "stable_bytes", receipt_only_bytes)
    monkeypatch.setattr(SCREEN, "BUNDLE_PATHS", (bundle,))
    monkeypatch.setattr(SCREEN, "MICROSHARDS", 1)
    monkeypatch.setattr(SCREEN, "SCREEN_CLUSTERS", SCREEN.MICROSHARD_CLUSTERS)
    monkeypatch.setattr(SCREEN.DESIGN, "manifest_problems", lambda *_a, **_k: [])
    manifest = SCREEN.manifest_payload(packet=packet, packet_sha256=SHA)
    assert opened == ["receipt.json"]
    assert manifest["outcomes_opened"] is False


def test_cli_refuses_unsafe_imports_and_unauthenticated_capacity_source(
        tmp_path):
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    unsafe = subprocess.run(
        [sys.executable, "-B", str(SCREEN.SCRIPT),
         "implementation-review-claim", "--expected-git", GIT],
        cwd=SCREEN.REPO, env=environment,
        capture_output=True, text=True, check=False,
    )
    assert unsafe.returncode != 0
    assert "isolated safe-path no-bytecode Python" in unsafe.stderr

    scripts = tmp_path / "server/scripts"
    scripts.mkdir(parents=True)
    copied = scripts / SCREEN.SCRIPT.name
    copied.write_bytes(SCREEN.SCRIPT.read_bytes())
    capacity = scripts / SCREEN.CAPACITY_PATH.name
    capacity.write_bytes(SCREEN.CAPACITY_PATH.read_bytes())
    sentinel = tmp_path / "PREIMPORT_SHADOW_EXECUTED"
    (scripts / "json.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('stdlib shadow executed')\n"
        "raise RuntimeError('PREIMPORT_SHADOW_EXECUTED')\n",
        encoding="utf-8",
    )
    isolated = subprocess.run(
        [sys.executable, "-I", "-P", "-B", str(copied),
         "implementation-review-claim", "--expected-git", GIT],
        cwd=tmp_path, env=environment,
        capture_output=True, text=True, check=False,
    )
    assert isolated.returncode != 0
    assert not sentinel.exists()
    assert "PREIMPORT_SHADOW_EXECUTED" not in isolated.stderr

    capacity.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('capacity source executed')\n",
        encoding="utf-8",
    )
    unauthenticated = subprocess.run(
        [sys.executable, "-I", "-P", "-B", str(copied),
         "implementation-review-claim", "--expected-git", GIT],
        cwd=tmp_path, env=environment,
        capture_output=True, text=True, check=False,
    )
    assert unauthenticated.returncode != 0
    assert not sentinel.exists()
    assert "reviewed Pair capacity source drift" in unauthenticated.stderr


def test_parser_exposes_no_resume_or_aggregate_command():
    parser = SCREEN.parser()
    commands = next(action for action in parser._actions
                    if getattr(action, "choices", None)).choices
    assert set(commands) == {
        "unit-template", "implementation-review-claim", "freeze", "verify",
        "run-screen", "run-microshard",
    }


def test_source_closure_names_the_new_controller(monkeypatch):
    relative = "server/scripts/pair_aware_rollout_checkpoint_screen.py"
    monkeypatch.setattr(SCREEN, "git", lambda *_args: relative)
    monkeypatch.setattr(SCREEN, "sha256_file", lambda _path: SHA)
    assert SCREEN.source_sha256s() == {relative: SHA}
    source = SCREEN.SCRIPT.read_text()
    assert "supervisor_reads_outcome_files\": False" in source
