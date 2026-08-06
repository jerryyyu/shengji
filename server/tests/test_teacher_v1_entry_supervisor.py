"""Focused falsification tests for the teacher-v1 entry supervisor."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_v1_entry_supervisor as supervisor  # noqa: E402
from shengji.teacher_v1 import (CAPTURE_PACKET_ID, REPRESENTATIVE_CELLS,  # noqa: E402
                                capture_coverage, capture_packet,
                                stable_digest)


GIT = "1" * 40


def runtime() -> dict:
    return {
        "git": GIT, "tree_dirty": False, "promotable": True,
        "host": "test-host", "python": "3.14.6",
        "fast_engine": True, "require_voids": True,
        "fast_router_sha256": stable_digest("router"),
        "fast_binary_sha256": stable_digest("binary"),
        "state_script_sha256": stable_digest("states"),
    }


def test_literal_entry_contract_is_exact():
    assert supervisor.static_contract_problems() == []
    assert supervisor.EXPECTED_PACKET == {
        "packet_id": "teacher-v1-entry-120m-v1",
        "seed0": 120_000_000,
        "seed_end_inclusive": 120_001_023,
        "max_deals": 1_024,
        "shard_count": 8,
        "sharding": "interleaved_seed_offset_mod_8",
        "deals_per_shard": 128,
    }


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"git": "2" * 40}, "runtime git"),
        ({"tree_dirty": True}, "dirty or non-promotable"),
        ({"promotable": False}, "dirty or non-promotable"),
        ({"fast_engine": False}, "compiled engine"),
        ({"require_voids": False}, "strict void mode"),
    ],
)
def test_runtime_requires_exact_clean_compiled_strict_identity(change, problem):
    value = {**runtime(), **change}
    assert any(problem in item
               for item in supervisor.runtime_problems(value, GIT))


def test_preflight_binds_runtime_actor_exams_and_diagnostic_checkpoint(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(supervisor.states, "runtime", lambda _smoke: runtime())
    actor = {"policy": "mc-strong", "identity": stable_digest("actor")}
    monkeypatch.setattr(supervisor.states, "actor_identity", lambda: actor)
    sources = [
        {"path": path, "sha256": supervisor.EXPECTED_EXAM_SHA256[path],
         "deals": index + 1}
        for index, path in enumerate(supervisor.EXPECTED_EXAM_SPLITS)
    ]
    exclusion = {
        "verified": True, "overlap": 0, "sources": sources,
        "excluded_deals": 6,
    }
    monkeypatch.setattr(
        supervisor.states, "load_exam_exclusion",
        lambda _paths: ({1, 2, 3, 4, 5, 6}, exclusion),
    )
    checkpoint = tmp_path / "snapshots_v11pair" / "ep07.npz"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"checkpoint")
    monkeypatch.setattr(supervisor, "SERVER_ROOT", tmp_path)
    monkeypatch.setattr(
        supervisor.states, "sha256_file",
        lambda path: (supervisor.EXPECTED_V11_SHA256
                      if Path(path) == checkpoint else stable_digest(path)),
    )
    admitted = supervisor.preflight(CAPTURE_PACKET_ID, GIT)
    assert admitted["runtime"] == runtime()
    assert admitted["actor"] == actor
    assert admitted["exam_exclusion"] == exclusion
    assert admitted["checkpoint_sha256"] == supervisor.EXPECTED_V11_SHA256


def test_one_directory_is_one_attempt_even_when_existing_directory_is_empty(
    tmp_path,
):
    attempt = tmp_path / CAPTURE_PACKET_ID
    attempt.mkdir()
    with pytest.raises(supervisor.EntryRefusal, match="no resume or replacement"):
        supervisor.prepare_output_dir(attempt)


def test_command_graph_is_exact_and_stops_before_receipts_or_labels(tmp_path):
    paths = supervisor.entry_paths(tmp_path)
    captures = supervisor.capture_jobs(paths)
    assert len(captures) == 8
    for index, job in enumerate(captures):
        argv = list(job.argv)
        assert argv[2] == "capture"
        assert argv[argv.index("--packet-id") + 1] == CAPTURE_PACKET_ID
        assert argv[argv.index("--seed0") + 1] == "120000000"
        assert argv[argv.index("--max-deals") + 1] == "1024"
        assert argv[argv.index("--shard-index") + 1] == str(index)
        assert argv[argv.index("--shard-count") + 1] == "8"
        assert "--smoke" not in argv

    capture_hashes = [stable_digest({"capture": index}) for index in range(8)]
    diagnostics = supervisor.diagnostic_jobs(paths, capture_hashes)
    assert len(diagnostics) == 8
    for index, job in enumerate(diagnostics):
        argv = list(job.argv)
        assert argv[2] == "diagnose"
        assert argv[argv.index("--input") + 1] == str(paths.captures[index])
        assert argv[argv.index("--expected-input-sha256") + 1] == \
            capture_hashes[index]

    freeze = supervisor.freeze_job(paths)
    assert freeze.argv[2:5] == ("freeze", "--stage", "a")
    assert freeze.argv.count("--input") == 8
    assert all(word not in " ".join(freeze.argv)
               for word in ("teacher_v1_label", "teacher_v1_receipt",
                            "teacher_v1_gate"))
    all_argv = " ".join(
        word for job in [*captures, *diagnostics, freeze] for word in job.argv
    )
    assert "teacher_v1_label.py" not in all_argv
    assert "teacher_v1_receipt.py" not in all_argv
    assert "teacher_v1_gate.py" not in all_argv


def test_diagnostics_refuse_anything_but_eight_literal_parent_hashes(tmp_path):
    paths = supervisor.entry_paths(tmp_path)
    with pytest.raises(supervisor.EntryRefusal, match="eight literal"):
        supervisor.diagnostic_jobs(paths, [stable_digest("one")])
    with pytest.raises(supervisor.EntryRefusal, match="eight literal"):
        supervisor.diagnostic_jobs(paths, ["not-a-hash"] * 8)


class FakeProgress:
    def __init__(self):
        self.events = []

    def event(self, phase, status, **fields):
        self.events.append((phase, status, fields))


class FakeProcess:
    def __init__(self, code):
        self.code = code
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.killed = True
        self.code = -9


def test_first_worker_refusal_terminates_peers_and_does_not_publish_logs(tmp_path):
    jobs = [
        supervisor.Job(
            "bad", ("python", "bad"), tmp_path / "bad.log.partial",
            tmp_path / "bad.log",
        ),
        supervisor.Job(
            "peer", ("python", "peer"), tmp_path / "peer.log.partial",
            tmp_path / "peer.log",
        ),
    ]
    processes = {}

    def popen(argv, **_kwargs):
        process = FakeProcess(7 if argv[-1] == "bad" else None)
        processes[argv[-1]] = process
        return process

    progress = FakeProgress()
    with pytest.raises(supervisor.EntryRefusal, match="stopped peers"):
        supervisor.run_jobs(
            "capture", jobs, progress, popen=popen, poll_seconds=0,
            heartbeat_seconds=10_000,
        )
    assert processes["peer"].terminated
    assert not jobs[0].log_final.exists()
    assert not jobs[1].log_final.exists()
    assert jobs[0].log_partial.exists()
    assert jobs[1].log_partial.exists()
    assert any(status == "REFUSED" for _, status, _ in progress.events)


def test_successful_workers_publish_their_exclusive_logs(tmp_path):
    jobs = [
        supervisor.Job(
            f"ok-{index}",
            (sys.executable, "-c", f"print('worker-{index}')"),
            tmp_path / f"ok-{index}.log.partial",
            tmp_path / f"ok-{index}.log",
        )
        for index in range(2)
    ]
    progress = FakeProgress()
    supervisor.run_jobs(
        "bounded", jobs, progress, poll_seconds=0.001,
        heartbeat_seconds=10_000,
    )
    assert [job.log_final.read_text().strip() for job in jobs] == [
        "worker-0", "worker-1",
    ]
    assert not any(job.log_partial.exists() for job in jobs)
    assert progress.events[-1][1] == "COMPLETE"


def test_supervision_transitions_capture_to_diagnostics_to_freeze_only(
    tmp_path, monkeypatch,
):
    phases = []
    fake_runtime = runtime()
    admitted = {
        "runtime": fake_runtime,
        "actor": {"policy": "mc-strong", "identity": stable_digest("actor")},
        "exam_exclusion": {"verified": True, "overlap": 0, "sources": []},
        "checkpoint_sha256": supervisor.EXPECTED_V11_SHA256,
    }
    monkeypatch.setattr(supervisor, "preflight", lambda *_args: admitted)
    monkeypatch.setattr(supervisor, "recheck", lambda *_args: None)
    monkeypatch.setattr(supervisor, "require_inventory", lambda *_args: None)

    def run_jobs(phase, jobs, _progress):
        phases.append((phase, [job.name for job in jobs]))

    hashes = [stable_digest({"artifact": index}) for index in range(8)]
    monkeypatch.setattr(supervisor, "run_jobs", run_jobs)
    monkeypatch.setattr(
        supervisor, "validate_capture_population",
        lambda *_args: ([{} for _ in range(8)], hashes),
    )
    monkeypatch.setattr(
        supervisor, "validate_diagnostic_population",
        lambda *_args: ([{} for _ in range(8)], hashes),
    )
    monkeypatch.setattr(
        supervisor, "validate_stage_a_state_set",
        lambda *_args: ({}, stable_digest("stage-a")),
    )

    attempt = tmp_path / CAPTURE_PACKET_ID
    digest = supervisor.supervise(CAPTURE_PACKET_ID, GIT, attempt)
    assert digest == stable_digest("stage-a")
    assert phases == [
        ("capture", [f"capture_shard{index:02d}" for index in range(8)]),
        ("diagnostic", [f"diagnostic_shard{index:02d}" for index in range(8)]),
        ("freeze", ["freeze_stage_a"]),
    ]
    progress = [json.loads(line) for line in
                (attempt / "supervisor_progress.jsonl").read_text().splitlines()]
    assert progress[-1]["terminal"] == "STAGE_A_STATES_FROZEN"
    assert progress[-1]["labels_launched"] is False
    assert progress[-1]["stage_a_launched"] is False


def _stage_a_fixture(tmp_path):
    paths = supervisor.entry_paths(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    diagnostic_hashes = []
    for index, path in enumerate(paths.diagnostics):
        path.write_text(json.dumps({"shard": index}) + "\n")
        diagnostic_hashes.append(supervisor.states.sha256_file(str(path)))

    actor = {"policy": "mc-strong", "identity": stable_digest("actor")}
    exclusion = {
        "verified": True, "overlap": 0, "excluded_deals": 3,
        "sources": [{"path": path} for path in supervisor.EXPECTED_EXAM_SPLITS],
    }
    parent_map = {
        str(index): stable_digest({"capture-parent": index})
        for index in range(8)
    }
    diagnostic_map = {
        str(index): stable_digest({"diagnostic-records": index})
        for index in range(8)
    }
    coverage = {
        **capture_coverage(),
        "capture_parent_sha256": parent_map,
        "diagnostic_records_sha256": diagnostic_map,
    }
    inputs = [
        {
            "path": str(paths.diagnostics[index]),
            "sha256": diagnostic_hashes[index],
            "capture_shard_index": index,
            "capture_parent_sha256": parent_map[str(index)],
            "diagnostic_records_sha256": diagnostic_map[str(index)],
        }
        for index in range(8)
    ]
    diagnostics = [{
        **runtime(), "actor": actor, "exam_exclusion": exclusion,
    } for _ in range(8)]

    selected = []
    seed = 120_000_000
    for cell in REPRESENTATIVE_CELLS:
        for _ in range(4):
            selected.append({
                "state_id": f"state-{seed}", "seed": seed,
                "phase": cell[0], "role": cell[1], "decision": cell[2],
                "kind": "representative",
            })
            seed += 1
    for kind in ("boundary", "uncertainty"):
        for _ in range(8):
            selected.append({
                "state_id": f"state-{seed}", "seed": seed,
                "phase": "early", "role": "attacker", "decision": "lead",
                "kind": kind,
            })
            seed += 1
    payload = {
        "schema": supervisor.STATE_SET_SCHEMA,
        "experiment_id": "teacher-v1",
        "packet_id": CAPTURE_PACKET_ID,
        "capture_packet": capture_packet(),
        "capture_coverage": coverage,
        "stage": "a", "complete": True,
        "requested": 64, "selected": 64,
        "states": selected, "states_digest": stable_digest(selected),
        "diagnostic_inputs": inputs,
        "actor": actor, "exam_exclusion": exclusion,
        "one_state_per_deal": True,
        "excluded_stage_a": None, "stage_a_gate": None,
        **runtime(),
    }
    paths.state_set.write_text(json.dumps(payload, sort_keys=True) + "\n")
    return paths, payload, diagnostics, diagnostic_hashes, actor, exclusion


def test_frozen_output_must_be_exactly_64_stage_a_states(tmp_path, monkeypatch):
    (paths, payload, diagnostics, diagnostic_hashes,
     actor, exclusion) = _stage_a_fixture(tmp_path)
    replayed = []
    monkeypatch.setattr(
        supervisor.states, "replay_state", lambda state: replayed.append(state)
    )
    _, digest = supervisor.validate_stage_a_state_set(
        paths, diagnostics, diagnostic_hashes, runtime(), actor, exclusion,
    )
    assert len(replayed) == 64
    assert len(digest) == 64

    payload["states"] = payload["states"][:-1]
    payload["selected"] = 63
    payload["states_digest"] = stable_digest(payload["states"])
    paths.state_set.write_text(json.dumps(payload, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="not exactly 64"):
        supervisor.validate_stage_a_state_set(
            paths, diagnostics, diagnostic_hashes, runtime(), actor, exclusion,
        )


def test_frozen_output_cannot_cross_into_stage_b(tmp_path, monkeypatch):
    (paths, payload, diagnostics, diagnostic_hashes,
     actor, exclusion) = _stage_a_fixture(tmp_path)
    monkeypatch.setattr(supervisor.states, "replay_state", lambda _state: None)
    payload["stage"] = "b"
    paths.state_set.write_text(json.dumps(payload, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="complete Stage-A"):
        supervisor.validate_stage_a_state_set(
            paths, diagnostics, diagnostic_hashes, runtime(), actor, exclusion,
        )
