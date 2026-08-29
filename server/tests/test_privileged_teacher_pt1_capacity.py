"""Pure capacity-lane coverage, redaction, and identity witnesses."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import random
from concurrent.futures import Future
from pathlib import Path

import pytest

from shengji.engine.cards import Ordering, make_deck
from shengji.engine.round import Round, Trick
from shengji.rl import privileged_teacher_pt1 as pt1
from shengji.rl import privileged_teacher_pt1_capacity as capacity


_CLI_SPEC = importlib.util.spec_from_file_location(
    "privileged_teacher_pt1_capacity_cli",
    Path(__file__).parents[1] / "scripts" / "privileged_teacher_pt1_capacity.py")
assert _CLI_SPEC is not None and _CLI_SPEC.loader is not None
capacity_cli = importlib.util.module_from_spec(_CLI_SPEC)
_CLI_SPEC.loader.exec_module(capacity_cli)


SECRET = bytes(range(32))
SECRET_SHA = hashlib.sha256(SECRET).hexdigest()
RUNTIME = {"git_head": "a" * 40, "source_tree_dirty": False,
           "source_population_sha256": "b" * 64, "source_file_count": 5,
           "host_name": "mini", "machine": "arm64", "logical_cpu_count": 10,
           "boot_identity_sha256": "e" * 64,
           "python_version": "3.14.0", "python_executable_sha256": "c" * 64,
           "native_extension_sha256": "d" * 64, "compiled_engine": True,
           "strict_voids": True}
_CACHED_CAPACITY_PAYLOAD = None
_CACHED_CAPACITY_CALLS = None


def test_capacity_darwin_boot_identity_uses_stable_session_uuid(monkeypatch):
    session = {"uuid": b"stable-capacity-session-1\n"}
    commands = []

    def sysctl(command, **_kwargs):
        commands.append(tuple(command))
        assert command == ["sysctl", "-n", "kern.bootsessionuuid"]
        return session["uuid"]

    monkeypatch.setattr(capacity.sys, "platform", "darwin")
    original_is_file = capacity.Path.is_file
    monkeypatch.setattr(capacity.Path, "is_file", lambda path: False
                        if str(path) == "/proc/sys/kernel/random/boot_id"
                        else original_is_file(path))
    monkeypatch.setattr(capacity.subprocess, "check_output", sysctl)
    before = capacity._boot_identity_bytes()
    # A clock correction is irrelevant because no wall-clock-derived value is read.
    assert capacity._boot_identity_bytes() == before
    session["uuid"] = b"stable-capacity-session-2\n"
    assert capacity._boot_identity_bytes() != before
    assert commands == [
        ("sysctl", "-n", "kern.bootsessionuuid"),
        ("sysctl", "-n", "kern.bootsessionuuid"),
        ("sysctl", "-n", "kern.bootsessionuuid"),
    ]


def test_capacity_runtime_requires_strict_environment_and_activation(monkeypatch):
    from shengji.engine import fast
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(fast, "activate", lambda: False)
    with pytest.raises(capacity.PT1CapacityError,
                       match="active compiled engine and strict voids"):
        capacity._runtime_identity()


def _design():
    return capacity.CapacityDesign(
        capture_secret_sha256=SECRET_SHA, parallel_workers=1)


def _round(coordinate, hidden=0):
    deck = make_deck()
    actor = coordinate.banker if coordinate.role == "banker-team" \
        else (coordinate.banker + 1) % 4
    hands = [[deck[(seat * 10 + index + hidden) % len(deck)]
              for index in range(coordinate.threshold)] for seat in range(4)]
    rnd = Round(coordinate.rank, banker=coordinate.banker, rng=random.Random(hidden))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", coordinate.rank)
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = hands
    rnd.buried = [deck[100], deck[101]]
    rnd.trick = Trick(leader=actor)
    rnd.turn = actor
    rnd.deck = deck
    rnd.attacker_points = coordinate.index
    return rnd


def _capture(design, coordinate, seed, attempt):
    return _round(coordinate, hidden=coordinate.index)


def _record(state, seed):
    ballot = (("C4",), ("D4",))
    utilities = ((ballot[0], 12345), (ballot[1], 0))
    points = ((ballot[0], 9876), (ballot[1], 0))
    identity = pt1._evaluator_identity(
        state.public_state_sha256, state.true_world_sha256,
        utilities, points, 17, 3)
    work = pt1.WorkReceipt(30, 300, 2, 30, 3, 300, 4,
                           900, 900, 17, 3, 11)
    arms = tuple(pt1.ArmDecision(
        name, ("C4",) if name == "C" else ("D4",), ballot,
        state.public_state_sha256, state.true_world_sha256,
        pt1.PRODUCTION_POLICY if name != "C" else "ExactWorldSession",
        seed, work, identity) for name in ("A", "B", "C"))
    capture_id = getattr(
        state, "capture_id_sha256",
        hashlib.sha256(state.public_state_sha256.encode()).hexdigest())
    return pt1.PT1Record(
        hashlib.sha256(f"{capture_id}:{seed}".encode()).hexdigest(),
        state.public_state_sha256, state.true_world_sha256, ballot, arms,
        (("A", 0), ("B", 0), ("C", 12345)),
        (("A", 0), ("B", 0), ("C", 9876)), utilities, points, identity,
        0, pt1.AUTHORITY)


def _run(monkeypatch, *, deadline=None):
    global _CACHED_CAPACITY_PAYLOAD, _CACHED_CAPACITY_CALLS
    if deadline is None and _CACHED_CAPACITY_PAYLOAD is not None:
        return (capacity.CapacityReport(copy.deepcopy(_CACHED_CAPACITY_PAYLOAD)),
                list(_CACHED_CAPACITY_CALLS))
    monkeypatch.setattr(capacity, "_runtime_identity", lambda: copy.deepcopy(RUNTIME))
    # These unit tests exercise the capacity schedule, redaction and resource
    # wiring. Natural-state eligibility is covered by the natural-provider
    # suite; bypass its comparatively expensive action enumeration here.
    monkeypatch.setattr(capacity, "_first_eligible",
                        lambda state, **_kwargs: copy.deepcopy(state))
    def state_from(_design, _state, *, rank, banker, role, threshold,
                   replicate, round_seed):
        public_sha = hashlib.sha256(
            f"public:{rank}:{banker}:{role}:{threshold}:{replicate}:"
            f"{round_seed}".encode()).hexdigest()
        true_sha = hashlib.sha256(f"true:{public_sha}".encode()).hexdigest()
        public = type("Public", (), {"public_sha256": public_sha})()
        true = type("True", (), {"true_sha256": true_sha})()
        return capacity.NaturalPT1State(
            rank, banker, role, threshold, replicate, round_seed,
            hashlib.sha256(f"cluster:{round_seed}".encode()).hexdigest(),
            hashlib.sha256(
                f"capture:{rank}:{banker}:{role}:{threshold}:{replicate}:"
                f"{public_sha}".encode()).hexdigest(),
            public_sha, true_sha, public, true)
    monkeypatch.setattr(capacity, "_state_from_round", state_from)
    calls = []

    def evaluator(public, true, *, seeds):
        calls.append(tuple(seeds))
        state = type("State", (), {})()
        state.public_state_sha256 = public.public_sha256
        state.true_world_sha256 = true.true_sha256
        return tuple(_record(state, seed) for seed in seeds)

    report = capacity.run_capacity(
        _design(), capture_secret=SECRET, state_capture=_capture,
        evaluator=evaluator, deadline=deadline, monotonic=lambda: 0.0)
    if deadline is None:
        _CACHED_CAPACITY_PAYLOAD = report.payload()
        _CACHED_CAPACITY_CALLS = list(calls)
    return report, calls


def _reseal(payload):
    payload["report_sha256"] = hashlib.sha256(
        capacity.canonical_json_bytes({k: payload[k]
            for k in payload if k != "report_sha256"})).hexdigest()
    return payload


def test_exact_full_grid_coverage_and_real_batch_calls(monkeypatch):
    report, calls = _run(monkeypatch)
    payload = report.payload()
    assert payload["record_count"] == capacity.TARGET_STATE_COUNT == 416
    assert len(calls) == 416 and all(seed == (0, 1, 2, 3) for seed in calls)
    assert {row["trump_rank"] for row in payload["records"]} == set(
        row.rank for row in capacity.capacity_coordinates())
    assert {row["role"] for row in payload["records"]} == {
        "banker-team", "attacker-team"}
    assert {row["remaining_hand_threshold"] for row in payload["records"]} == {3, 4}
    assert {row["banker"] for row in payload["records"]} == {0, 1}
    assert {row["replicate"] for row in payload["records"]} == set(range(4))
    assert len({(row["trump_rank"], row["banker"], row["role"],
                row["remaining_hand_threshold"], row["replicate"])
                for row in payload["records"]}) == 416
    assert payload["caps"]["scientific_wall_nanoseconds"] > 0
    assert payload["caps"]["scientific_cpu_nanoseconds"] > 0
    assert payload["caps"]["scientific_artifact_bytes"] > 0
    assert payload["caps"]["scientific_exact_nodes"] > 0
    assert payload["caps"]["peak_rss_bytes"] >= max(
        row["peak_rss_raw"] for row in payload["records"])
    assert all(row["work"]["C"]["exact_nodes"] == 17
               for row in payload["records"])
    sample = payload["records"][0]
    sample_state = type("State", (), {
        "public_state_sha256": sample["public_state_sha256"],
        "true_world_sha256": sample["true_world_sha256"]})()
    expected_artifact_bytes = sum(
        len(_record(sample_state, seed).canonical_bytes())
        for seed in capacity.CAPACITY_POLICY_SEEDS)
    assert all(row["artifact_projection_bytes"] == expected_artifact_bytes
               for row in payload["records"])
    assert report.payload()["authority"] == capacity.CAPACITY_AUTHORITIES
    assert capacity.verify_capacity_report(report, design=_design()).payload() == payload


def test_report_redacts_distinctive_actions_values_points_worlds_and_seeds(monkeypatch):
    report, _ = _run(monkeypatch)
    raw = json.dumps(report.payload(), sort_keys=True)
    # Numeric score literals can occur coincidentally inside timing counters;
    # privacy is a field/string boundary, not a decimal-substring boundary.
    for forbidden in ("C4", "D4", "selected_action",
                      "selected_utilities", "selected_points", "round_seed",
                      "legal_ballot", "hidden_state"):
        assert forbidden not in raw


@pytest.mark.parametrize("mutation", ["selector", "coverage", "resource", "source", "hash"])
def test_selector_coverage_resource_source_and_hash_mutations_refuse(monkeypatch, mutation):
    report, _ = _run(monkeypatch)
    payload = report.payload()
    if mutation == "selector":
        payload["selector_namespace"] = "wrong"
    elif mutation == "coverage":
        payload["records"][0]["index"] = 1
    elif mutation == "resource":
        payload["caps"]["scientific_wall_nanoseconds"] += 1
    elif mutation == "source":
        payload["runtime"]["source_population_sha256"] = "e" * 64
    else:
        payload["report_sha256"] = "f" * 64
    if mutation != "hash":
        _reseal(payload)
    with pytest.raises(capacity.PT1CapacityError):
        capacity.verify_capacity_report(payload, design=_design())


def test_deadline_seals_truncated_prefix_without_claiming_complete(monkeypatch):
    report, calls = _run(monkeypatch, deadline=0.0)
    payload = report.payload()
    assert calls == []
    assert payload["status"] == "TRUNCATED"
    assert payload["truncated_by_deadline"] is True
    assert payload["record_count"] == 0


def test_parallel_topology_uses_frozen_worker_pool_and_reopens(monkeypatch):
    template, _ = _run(monkeypatch)
    monkeypatch.setattr(capacity, "_runtime_identity",
                        lambda: copy.deepcopy(RUNTIME))
    rows = {row["index"]: row for row in template.payload()["records"]}
    observed = {"workers": None, "submitted": 0}

    class FakePool:
        def __init__(self, *, max_workers):
            observed["workers"] = max_workers

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, function, args):
            observed["submitted"] += 1
            coordinate = args[2]
            future = Future()
            future.set_result(copy.deepcopy(rows[coordinate.index]))
            return future

    monkeypatch.setattr(capacity, "ProcessPoolExecutor", FakePool)
    design = capacity.CapacityDesign(
        capture_secret_sha256=SECRET_SHA, parallel_workers=4)
    report = capacity.run_capacity(design, capture_secret=SECRET)
    assert observed == {"workers": 4, "submitted": 416}
    assert report.payload()["parallel_workers"] == 4
    assert report.payload()["record_count"] == 416
    assert capacity.verify_capacity_report(
        report, design=design).payload() == report.payload()


def test_cli_write_once_and_progress_publication(monkeypatch, tmp_path):
    report, _ = _run(monkeypatch)
    monkeypatch.setattr(capacity, "_runtime_identity",
                        lambda: copy.deepcopy(RUNTIME))
    monkeypatch.setattr(capacity_cli, "run_capacity",
                        lambda *args, **kwargs: report)
    output = tmp_path / "capacity"
    secret_file = tmp_path / "secret"
    secret_file.write_bytes(SECRET)
    secret_file.chmod(0o400)
    argv = ["--secret-file", str(secret_file), "--output-dir", str(output)]
    argv += ["--workers", "1"]
    assert capacity_cli.main(argv) == 0
    packet = (output / "capacity.json").read_bytes()
    manifest = (output / "manifest.json").read_bytes()
    progress = (output / "progress.json").read_bytes()
    assert packet == report.canonical_bytes()
    assert json.loads(manifest)["report_sha256"] == hashlib.sha256(packet).hexdigest()
    assert json.loads(progress)["status"] == "COMPLETE"
    assert json.loads(progress)["percent_basis_points"] == 10_000
    assert (output / "capacity.json").stat().st_mode & 0o777 == 0o400
    assert capacity_cli.main(argv) == 0
    assert (output / "capacity.json").read_bytes() == packet
    assert (output / "manifest.json").read_bytes() == manifest
    with pytest.raises(capacity.PT1CapacityError):
        capacity_cli._write_once(output / "capacity.json", b"different")


def test_worker_failure_binds_coordinate_and_cli_publishes_redacted_receipt(
        monkeypatch, tmp_path):
    coordinate = capacity.capacity_coordinates()[0]
    monkeypatch.setattr(capacity, "_runtime_identity",
                        lambda: copy.deepcopy(RUNTIME))
    monkeypatch.setattr(
        capacity, "_run_capacity_unit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            pt1.PrivilegedTeacherPT1Error(
                "production route did not expose decision telemetry")))
    with pytest.raises(capacity.PT1CapacityWorkerError) as failure:
        capacity.run_capacity(_design(), capture_secret=SECRET)
    assert failure.value.coordinate == coordinate
    assert failure.value.cause_code == "PRODUCTION_ROUTE_NO_TELEMETRY"
    assert failure.value.completed_units == 0

    output = tmp_path / "failed-capacity"
    secret_file = tmp_path / "secret"
    secret_file.write_bytes(SECRET)
    secret_file.chmod(0o400)
    monkeypatch.setattr(
        capacity_cli, "run_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure.value))
    argv = ["--secret-file", str(secret_file), "--output-dir", str(output),
            "--workers", "1"]
    with pytest.raises(SystemExit, match="2"):
        capacity_cli.main(argv)
    receipt = json.loads((output / "failure.json").read_bytes())
    progress = json.loads((output / "progress.json").read_bytes())
    assert receipt["failed_coordinate"] == coordinate.payload()
    assert receipt["cause_code"] == "PRODUCTION_ROUTE_NO_TELEMETRY"
    assert receipt["completed_units"] == 0
    assert receipt["score_redacted"] is True
    assert receipt["authority"] == capacity.CAPACITY_AUTHORITIES
    assert progress["status"] == "FAILED"
    raw = json.dumps(receipt, sort_keys=True)
    for forbidden in ("selected_action", "selected_utilities", "selected_points",
                      "round_seed", "legal_ballot", "hidden_state"):
        assert forbidden not in raw
