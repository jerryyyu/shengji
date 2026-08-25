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
    monkeypatch.setattr(capacity, "_runtime_identity", lambda: copy.deepcopy(RUNTIME))
    calls = []

    def evaluator(public, true, *, seeds):
        calls.append(tuple(seeds))
        state = type("State", (), {})()
        state.public_state_sha256 = pt1.pt0_public_state_sha256(
            public, perspective_seat=public.turn)
        state.true_world_sha256 = pt1._world_hash(true.verify())
        return tuple(_record(state, seed) for seed in seeds)

    report = capacity.run_capacity(
        _design(), capture_secret=SECRET, state_capture=_capture,
        evaluator=evaluator, deadline=deadline, monotonic=lambda: 0.0)
    return report, calls


def _reseal(payload):
    payload["report_sha256"] = hashlib.sha256(
        capacity.canonical_json_bytes({k: payload[k]
            for k in payload if k != "report_sha256"})).hexdigest()
    return payload


def test_exact_16_marginal_coverage_and_real_batch_calls(monkeypatch):
    report, calls = _run(monkeypatch)
    payload = report.payload()
    assert payload["record_count"] == 16
    assert len(calls) == 16 and all(seed == (0, 1, 2, 3) for seed in calls)
    assert {row["trump_rank"] for row in payload["records"]} == set(
        row.rank for row in capacity.capacity_coordinates())
    assert {row["role"] for row in payload["records"]} == {
        "banker-team", "attacker-team"}
    assert {row["remaining_hand_threshold"] for row in payload["records"]} == {3, 4}
    assert {row["banker"] for row in payload["records"]} == {0, 1}
    assert payload["caps"]["scientific_wall_nanoseconds"] > 0
    assert payload["caps"]["scientific_cpu_nanoseconds"] > 0
    assert payload["caps"]["scientific_artifact_bytes"] > 0
    assert payload["caps"]["scientific_exact_nodes"] > 0
    assert payload["caps"]["peak_rss_bytes"] >= max(
        row["peak_rss_raw"] for row in payload["records"])
    assert all(row["work"]["C"]["exact_nodes"] == 17
               for row in payload["records"])
    assert all(row["artifact_projection_bytes"] == sum(
        len(_record(type("State", (), {
            "public_state_sha256": row["public_state_sha256"],
            "true_world_sha256": row["true_world_sha256"]})(), seed).canonical_bytes())
        for seed in capacity.CAPACITY_POLICY_SEEDS)
               for row in payload["records"])
    assert report.payload()["authority"] == capacity.CAPACITY_AUTHORITIES
    assert capacity.verify_capacity_report(report, design=_design()).payload() == payload


def test_report_redacts_distinctive_actions_values_points_worlds_and_seeds(monkeypatch):
    report, _ = _run(monkeypatch)
    raw = json.dumps(report.payload(), sort_keys=True)
    for forbidden in ("C4", "D4", "12345", "9876", "selected_action",
                      "selected_utilities", "selected_points", "round_seed"):
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
    assert observed == {"workers": 4, "submitted": 16}
    assert report.payload()["parallel_workers"] == 4
    assert report.payload()["record_count"] == 16
    assert capacity.verify_capacity_report(
        report, design=design).payload() == report.payload()


def test_cli_write_once_and_progress_publication(monkeypatch, tmp_path):
    report, _ = _run(monkeypatch)
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
