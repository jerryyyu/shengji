"""Focused falsification tests for the teacher-v1 entry supervisor."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_v1_entry_supervisor as supervisor  # noqa: E402
from shengji.teacher_v1 import (CAPTURE_PACKET_ID, REPRESENTATIVE_CELLS,  # noqa: E402
                                REFUSED_CAPTURE_PACKET,
                                REFUSED_CAPTURE_PACKETS, SEED_START,
                                capture_coverage, capture_packet,
                                capture_shard_seeds, stable_digest)


GIT = "1" * 40


def runtime() -> dict:
    return {
        "git": GIT, "tree_dirty": False, "promotable": True,
        "host": "test-host", "python": "3.14.6",
        "fast_engine": True, "require_voids": True,
        "experimental_sampler_ballot_flags": [],
        "fast_router_sha256": stable_digest("router"),
        "fast_binary_sha256": stable_digest("binary"),
        "state_script_sha256": stable_digest("states"),
    }


def test_literal_entry_contract_is_exact():
    assert supervisor.static_contract_problems() == []
    assert supervisor.EXPECTED_PACKET == {
        "packet_id": "teacher-v1-entry-149m-v3",
        "seed0": 149_000_000,
        "seed_end_inclusive": 149_001_023,
        "max_deals": 1_024,
        "shard_count": 8,
        "sharding": "interleaved_seed_offset_mod_8",
        "deals_per_shard": 128,
    }
    assert REFUSED_CAPTURE_PACKETS == supervisor.EXPECTED_REFUSED_PACKETS
    assert REFUSED_CAPTURE_PACKET == supervisor.EXPECTED_REFUSED_PACKET
    assert REFUSED_CAPTURE_PACKET["packet_id"] == \
        "teacher-v1-entry-143m-v2"
    assert REFUSED_CAPTURE_PACKET["status"] == "REFUSED"
    assert REFUSED_CAPTURE_PACKET["witness"]["state_id"] == \
        "143000001:44:0"
    assert supervisor.EXPECTED_PYTHON == "3.14.6"
    assert supervisor.EXPECTED_EXPERIMENTAL_SAMPLER_BALLOT_FLAGS == (
        "SHENGJI_WEIGHTED_SPLITS",
        "SHENGJI_UNIFORM_DEAL",
        "SHENGJI_PHYSICAL_FILLS",
        "SHENGJI_ALLOW_BALLOT_MISMATCH",
    )


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"git": "2" * 40}, "runtime git"),
        ({"tree_dirty": True}, "dirty or non-promotable"),
        ({"promotable": False}, "dirty or non-promotable"),
        ({"fast_engine": False}, "compiled engine"),
        ({"require_voids": False}, "strict void mode"),
        ({"python": "3.13.9"}, "runtime Python"),
        ({"experimental_sampler_ballot_flags": ["SHENGJI_UNIFORM_DEAL"]},
         "experimental sampler/ballot flags"),
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

    monkeypatch.setattr(
        supervisor.states, "runtime",
        lambda _smoke: {**runtime(), "python": "3.13.9"},
    )
    with pytest.raises(supervisor.EntryRefusal, match="runtime Python"):
        supervisor.preflight(CAPTURE_PACKET_ID, GIT)


@pytest.mark.parametrize(
    "flag", supervisor.EXPECTED_EXPERIMENTAL_SAMPLER_BALLOT_FLAGS,
)
@pytest.mark.parametrize("value", ["1", ""])
def test_preflight_refuses_each_experimental_sampler_or_ballot_flag(
    monkeypatch, flag, value,
):
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setenv(flag, value)
    with pytest.raises(supervisor.EntryRefusal, match="must be unset"):
        supervisor.preflight(CAPTURE_PACKET_ID, GIT)


def test_one_directory_is_one_attempt_even_when_existing_directory_is_empty(
    tmp_path,
):
    attempt = tmp_path / CAPTURE_PACKET_ID
    attempt.mkdir()
    with pytest.raises(supervisor.EntryRefusal, match="no resume or replacement"):
        supervisor.prepare_output_dir(attempt)


@pytest.mark.parametrize(
    "packet_id", ["teacher-v1-entry-120m-v1", "teacher-v1-entry-143m-v2"],
)
def test_refused_namespace_cannot_be_reused(packet_id):
    with pytest.raises(supervisor.EntryRefusal, match=CAPTURE_PACKET_ID):
        supervisor.resolve_output_dir(f"runs/logs/{packet_id}")


def test_command_graph_is_exact_and_stops_before_receipts_or_labels(tmp_path):
    paths = supervisor.entry_paths(tmp_path)
    captures = supervisor.capture_jobs(paths)
    assert len(captures) == 8
    for index, job in enumerate(captures):
        argv = list(job.argv)
        assert argv[2] == "capture"
        assert argv[argv.index("--packet-id") + 1] == CAPTURE_PACKET_ID
        assert argv[argv.index("--seed0") + 1] == "149000000"
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


def _write_capture_population(paths, actor, exclusion, records_by_shard=None):
    paths.root.mkdir(exist_ok=True)
    records_by_shard = records_by_shard or {}
    manifests = []
    hashes = []
    for index, path in enumerate(paths.captures):
        seeds = capture_shard_seeds(index)
        records = copy.deepcopy(records_by_shard.get(index, []))
        reached = {record["seed"] for record in records}
        unreachable = [seed for seed in seeds if seed not in reached]
        payload = {
            "schema": supervisor.states.CAPTURE_SCHEMA,
            "experiment_id": "teacher-v1",
            "packet_id": CAPTURE_PACKET_ID,
            "capture_packet": capture_packet(),
            "seed_start": SEED_START,
            "seed0": SEED_START,
            "max_deals": 1_024,
            "shard_count": 8,
            "shard_index": index,
            "complete": True,
            "scanned_deals": 128,
            "scanned_seeds": seeds,
            "scanned_seeds_sha256": stable_digest(seeds),
            "unreachable_targets": len(unreachable),
            "unreachable_seeds": unreachable,
            "n_records": len(records),
            "records": records,
            "records_digest": stable_digest(records),
            "actor": actor,
            "exam_exclusion": exclusion,
            **runtime(),
        }
        path.write_text(json.dumps(payload, sort_keys=True) + "\n")
        manifests.append(payload)
        hashes.append(supervisor.states.sha256_file(str(path)))
    return manifests, hashes


def _write_diagnostic_population(
    paths, captures, capture_hashes, actor, exclusion,
):
    manifests = []
    for index, path in enumerate(paths.diagnostics):
        records = [{
            "state_id": state["state_id"],
            "state": copy.deepcopy(state),
        } for state in captures[index]["records"]]
        state_ids = [record["state_id"] for record in records]
        payload = {
            "schema": supervisor.states.DIAGNOSTIC_SCHEMA,
            "experiment_id": "teacher-v1",
            "packet_id": CAPTURE_PACKET_ID,
            "capture_packet": capture_packet(),
            "capture_shard_index": index,
            "capture_scanned_seeds": captures[index]["scanned_seeds"],
            "capture_scanned_seeds_sha256": captures[index][
                "scanned_seeds_sha256"
            ],
            "capture_unreachable_seeds": captures[index]["unreachable_seeds"],
            "capture_input_sha256": capture_hashes[index],
            "input": str(paths.captures[index]),
            "input_sha256": capture_hashes[index],
            "complete": True,
            "n_records": len(records),
            "records": records,
            "records_digest": stable_digest(records),
            "diagnosed_state_ids": state_ids,
            "diagnosed_state_ids_sha256": stable_digest(state_ids),
            "selector_worlds": supervisor.states.SELECTOR_WORLDS,
            "selector_policy": "current mc-strong N=30 raw-point objective",
            "v11_checkpoint_sha256": supervisor.states.V11_CHECKPOINT_SHA256,
            "actor": actor,
            "exam_exclusion": exclusion,
            **runtime(),
        }
        manifests.append(payload)
        path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    return manifests


def test_json_loaded_capture_actor_matches_preflight_and_real_drift_refuses(
    tmp_path,
):
    actor = supervisor.states.actor_identity()
    loaded_actor = json.loads(json.dumps(actor))
    assert loaded_actor == actor
    assert isinstance(actor["ballot"]["config"], list)
    assert all(isinstance(item, list) for item in actor["ballot"]["config"])

    exclusion = {
        "verified": True,
        "overlap": 0,
        "excluded_deals": 3,
        "sources": [
            {"path": path, "sha256": supervisor.EXPECTED_EXAM_SHA256[path]}
            for path in supervisor.EXPECTED_EXAM_SPLITS
        ],
    }
    paths = supervisor.entry_paths(tmp_path / CAPTURE_PACKET_ID)
    _write_capture_population(paths, loaded_actor, exclusion)
    manifests, hashes = supervisor.validate_capture_population(
        paths, runtime(), actor, exclusion,
    )
    assert len(manifests) == len(hashes) == 8

    drifted = json.loads(paths.captures[0].read_text())
    drifted["actor"]["ballot"]["config"][0][1] = "real-drift"
    paths.captures[0].write_text(json.dumps(drifted, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="actor drift"):
        supervisor.validate_capture_population(
            paths, runtime(), actor, exclusion,
        )


def test_diagnostics_are_exact_children_of_capture_states(tmp_path):
    actor = {"policy": "mc-strong", "identity": stable_digest("actor")}
    exclusion = {
        "verified": True, "overlap": 0, "excluded_deals": 3,
        "sources": [
            {"path": path, "sha256": supervisor.EXPECTED_EXAM_SHA256[path]}
            for path in supervisor.EXPECTED_EXAM_SPLITS
        ],
    }
    paths = supervisor.entry_paths(tmp_path / CAPTURE_PACKET_ID)
    records_by_shard = {}
    for index in range(8):
        records_by_shard[index] = [{
            "packet_id": CAPTURE_PACKET_ID,
            "state_id": f"state-{index}-0",
            "seed": capture_shard_seeds(index)[0],
            "opaque": {"parent": index, "position": 0},
        }]
    records_by_shard[0].append({
        "packet_id": CAPTURE_PACKET_ID,
        "state_id": "state-0-1",
        "seed": capture_shard_seeds(0)[1],
        "opaque": {"parent": 0, "position": 1},
    })
    captures, capture_hashes = _write_capture_population(
        paths, actor, exclusion, records_by_shard,
    )
    diagnostics = _write_diagnostic_population(
        paths, captures, capture_hashes, actor, exclusion,
    )
    loaded, hashes = supervisor.validate_diagnostic_population(
        paths, captures, capture_hashes, runtime(), actor, exclusion,
    )
    assert len(loaded) == len(hashes) == 8

    altered = copy.deepcopy(diagnostics[0])
    altered["records"][0]["state"]["opaque"]["position"] = 99
    altered["records_digest"] = stable_digest(altered["records"])
    paths.diagnostics[0].write_text(json.dumps(altered, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="full capture state drift"):
        supervisor.validate_diagnostic_population(
            paths, captures, capture_hashes, runtime(), actor, exclusion,
        )

    swapped = copy.deepcopy(diagnostics[0])
    swapped["records"][0]["state"], swapped["records"][1]["state"] = (
        swapped["records"][1]["state"], swapped["records"][0]["state"]
    )
    swapped["records_digest"] = stable_digest(swapped["records"])
    paths.diagnostics[0].write_text(json.dumps(swapped, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="embedded state_id drift"):
        supervisor.validate_diagnostic_population(
            paths, captures, capture_hashes, runtime(), actor, exclusion,
        )


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
    validations = []
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
    def validate_capture(*_args):
        validations.append("capture")
        return [{} for _ in range(8)], hashes

    def validate_diagnostic(*_args):
        validations.append("diagnostic")
        return [{} for _ in range(8)], hashes

    def validate_stage_a(*_args):
        validations.append("stage-a")
        return {}, stable_digest("stage-a")

    monkeypatch.setattr(
        supervisor, "validate_capture_population", validate_capture,
    )
    monkeypatch.setattr(
        supervisor, "validate_diagnostic_population", validate_diagnostic,
    )
    monkeypatch.setattr(
        supervisor, "validate_stage_a_state_set", validate_stage_a,
    )

    attempt = tmp_path / CAPTURE_PACKET_ID
    digest = supervisor.supervise(CAPTURE_PACKET_ID, GIT, attempt)
    assert digest == stable_digest("stage-a")
    assert phases == [
        ("capture", [f"capture_shard{index:02d}" for index in range(8)]),
        ("diagnostic", [f"diagnostic_shard{index:02d}" for index in range(8)]),
        ("freeze", ["freeze_stage_a"]),
    ]
    assert validations == [
        "capture", "diagnostic", "capture", "diagnostic", "stage-a",
    ]
    progress = [json.loads(line) for line in
                (attempt / "supervisor_progress.jsonl").read_text().splitlines()]
    assert progress[-1]["terminal"] == "STAGE_A_STATES_FROZEN"
    assert progress[-1]["labels_launched"] is False
    assert progress[-1]["stage_a_launched"] is False


def _stage_a_fixture(tmp_path):
    paths = supervisor.entry_paths(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    actor = {"policy": "mc-strong", "identity": stable_digest("actor")}
    exclusion = {
        "verified": True, "overlap": 0, "excluded_deals": 3,
        "sources": [{"path": path} for path in supervisor.EXPECTED_EXAM_SPLITS],
    }
    diagnostic_rows = []
    seed = SEED_START
    for cell in REPRESENTATIVE_CELLS:
        for _ in range(4):
            state = {
                "state_id": f"state-{seed}", "seed": seed,
                "phase": cell[0], "role": cell[1], "decision": cell[2],
                "selector_pool": "representative",
            }
            diagnostic_rows.append({
                "state_id": state["state_id"], "state": state,
                "gap": 0.0, "gap_se": 0.0, "disagreement": False,
            })
            seed += 1
    for challenge_index in range(16):
        state = {
            "state_id": f"state-{seed}", "seed": seed,
            "phase": "early", "role": "attacker", "decision": "lead",
            "selector_pool": "challenge",
        }
        diagnostic_rows.append({
            "state_id": state["state_id"], "state": state,
            "gap": 5.0 + challenge_index / 100.0,
            "gap_se": float(challenge_index), "disagreement": True,
        })
        seed += 1

    parent_map = {}
    diagnostic_map = {}
    diagnostics = []
    diagnostic_hashes = []
    for index, path in enumerate(paths.diagnostics):
        records = diagnostic_rows[index::8]
        parent_map[str(index)] = stable_digest({"capture-parent": index})
        diagnostic_map[str(index)] = stable_digest(records)
        manifest = {
            "capture_shard_index": index,
            "capture_input_sha256": parent_map[str(index)],
            "records": records,
            "records_digest": diagnostic_map[str(index)],
            **runtime(), "actor": actor, "exam_exclusion": exclusion,
        }
        diagnostics.append(manifest)
        path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
        diagnostic_hashes.append(supervisor.states.sha256_file(str(path)))

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
    selected, selection_problems = supervisor.states.select_gate_states(
        diagnostic_rows, "a", set()
    )
    assert selection_problems == []
    assert len(selected) == 64
    payload = {
        "schema": supervisor.STATE_SET_SCHEMA,
        "experiment_id": "teacher-v1",
        "packet_id": CAPTURE_PACKET_ID,
        "capture_packet": capture_packet(),
        "capture_coverage": coverage,
        "stage": "a", "complete": True,
        "seed_start": SEED_START,
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


def test_frozen_output_refuses_invented_or_reordered_diagnostic_states(
    tmp_path, monkeypatch,
):
    (paths, payload, diagnostics, diagnostic_hashes,
     actor, exclusion) = _stage_a_fixture(tmp_path)
    monkeypatch.setattr(supervisor.states, "replay_state", lambda _state: None)

    invented = copy.deepcopy(payload)
    invented["states"][0]["invented_after_diagnosis"] = True
    invented["states_digest"] = stable_digest(invented["states"])
    paths.state_set.write_text(json.dumps(invented, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="canonical source drift"):
        supervisor.validate_stage_a_state_set(
            paths, diagnostics, diagnostic_hashes, runtime(), actor, exclusion,
        )

    reordered = copy.deepcopy(payload)
    reordered["states"][0], reordered["states"][1] = (
        reordered["states"][1], reordered["states"][0]
    )
    reordered["states_digest"] = stable_digest(reordered["states"])
    paths.state_set.write_text(json.dumps(reordered, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="exact diagnostic recomputation"):
        supervisor.validate_stage_a_state_set(
            paths, diagnostics, diagnostic_hashes, runtime(), actor, exclusion,
        )


def test_frozen_output_refuses_out_of_range_seed_and_forged_coverage(
    tmp_path, monkeypatch,
):
    (paths, payload, diagnostics, diagnostic_hashes,
     actor, exclusion) = _stage_a_fixture(tmp_path)
    monkeypatch.setattr(supervisor.states, "replay_state", lambda _state: None)

    out_of_range = copy.deepcopy(payload)
    out_of_range["states"][0]["seed"] = SEED_START - 1
    out_of_range["states_digest"] = stable_digest(out_of_range["states"])
    paths.state_set.write_text(json.dumps(out_of_range, sort_keys=True) + "\n")
    with pytest.raises(supervisor.EntryRefusal, match="outside the v3 seed range"):
        supervisor.validate_stage_a_state_set(
            paths, diagnostics, diagnostic_hashes, runtime(), actor, exclusion,
        )

    forged = copy.deepcopy(payload)
    forged_parent = stable_digest("forged-parent")
    forged["capture_coverage"]["capture_parent_sha256"]["0"] = forged_parent
    forged["diagnostic_inputs"][0]["capture_parent_sha256"] = forged_parent
    paths.state_set.write_text(json.dumps(forged, sort_keys=True) + "\n")
    with pytest.raises(
        supervisor.EntryRefusal, match="differs from reopened diagnostics",
    ):
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
