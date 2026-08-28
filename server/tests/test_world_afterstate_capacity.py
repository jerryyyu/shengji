from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.engine.cards import RANKS
from shengji.rl.world_afterstate_capacity import (
    AUTHORITY,
    WorldAfterstateCapacityError,
    build_capacity_fixtures,
    run_capacity,
    validate_capacity_receipt,
)


def _prepare_run(monkeypatch, capacity, git: str) -> None:
    monkeypatch.setattr(capacity, "_git", lambda _repo, *args:
                        git if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(capacity, "_strict_runtime_binding", lambda: {
        "environment": dict(capacity.REQUIRED_ENVIRONMENT),
        "python_executable": "/runtime/python",
        "python_executable_sha256": "1" * 64,
        "fast_router_path": "/runtime/fast.py",
        "fast_router_sha256": "2" * 64,
        "native_path": "/runtime/_fast.so",
        "native_sha256": "3" * 64,
        "compiled_engine_active": True,
        "safe_path": True,
        "dont_write_bytecode": True,
        "pythonpath_absent": True,
    })
    snapshots = iter((
        {"method": "linux-cgroup-v2-memory.peak",
         "path": "/sys/fs/cgroup/test-capacity",
         "current_bytes": 10_000, "peak_bytes": 12_000},
        {"method": "linux-cgroup-v2-memory.peak",
         "path": "/sys/fs/cgroup/test-capacity",
         "current_bytes": 11_000, "peak_bytes": 20_000},
    ))
    monkeypatch.setattr(capacity, "_capacity_memory_snapshot",
                        lambda: next(snapshots))
    monkeypatch.setattr(capacity, "run_afterstate_continuation",
                        lambda _audit, _identity: {
                            "continuation_decisions": 2,
                            "continuation_rollouts": 3,
                            "continuation_searches": 2,
                            "terminal_state": {"public": {
                                "phase": "round_end"}},
                        })


def test_capacity_fixtures_cover_every_rank_and_reopen():
    audits = build_capacity_fixtures(13)
    assert len(audits) == 13
    assert {audit["source_state"]["trump_rank"] for audit in audits} \
        == set(RANKS)
    assert all(audit["prestate_sha256"] != audit["successor_sha256"]
               for audit in audits)


def test_tiny_cpu_capacity_receipt_is_outcome_blind(monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    _prepare_run(monkeypatch, capacity, "a" * 40)
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="a" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[2],
        model_steps=1, device_name="cpu")
    validate_capacity_receipt(receipt)
    assert receipt["authority"] == AUTHORITY
    assert receipt["outcome_blind"] is True
    assert len(receipt["model_measurements"]) == 3
    continuation = receipt["composed_measurement"]["complete_continuation"]
    assert continuation["policy"] == capacity.CONTINUATION_POLICY
    assert continuation["fixture_index"] \
        == capacity.CONTINUATION_FIXTURE_INDEX
    assert continuation["decisions"] == 2
    assert continuation["rollouts"] == 3
    assert continuation["searches"] == 2
    assert continuation["terminal_result_discarded"] is True
    assert receipt["aggregate_memory"]["finish_peak_bytes"] == 20_000


def test_capacity_receipt_authority_and_rank_coverage_are_load_bearing(
        monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    _prepare_run(monkeypatch, capacity, "b" * 40)
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="b" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[1],
        model_steps=1, device_name="cpu")
    forged = copy.deepcopy(receipt)
    forged["authority"]["training_authorized"] = True
    with pytest.raises(WorldAfterstateCapacityError,
                       match="authority drift"):
        validate_capacity_receipt(forged)
    forged = copy.deepcopy(receipt)
    del forged["fixtures"]["trump_rank_counts"][RANKS[-1]]
    with pytest.raises(WorldAfterstateCapacityError,
                       match="trump-rank coverage drift"):
        validate_capacity_receipt(forged)


def test_capacity_receipt_binds_worker_and_model_schedule(monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    _prepare_run(monkeypatch, capacity, "c" * 40)
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="c" * 40, fixture_count=13,
        worker_counts=[1, 2], worker_repetitions=1, batch_sizes=[1, 2],
        model_steps=1, device_name="cpu")

    forged = copy.deepcopy(receipt)
    forged["tensor_worker_scaling"].pop()
    with pytest.raises(WorldAfterstateCapacityError,
                       match="worker schedule drift"):
        validate_capacity_receipt(forged)

    forged = copy.deepcopy(receipt)
    forged["tensor_worker_scaling"][-1]["output_population_sha256"] = "0" * 64
    with pytest.raises(WorldAfterstateCapacityError,
                       match="parallel tensor output drift"):
        validate_capacity_receipt(forged)

    forged = copy.deepcopy(receipt)
    forged["model_measurements"].pop()
    with pytest.raises(WorldAfterstateCapacityError,
                       match="model schedule drift"):
        validate_capacity_receipt(forged)

    forged = copy.deepcopy(receipt)
    forged["schedule"]["fixture_count"] += 1
    with pytest.raises(WorldAfterstateCapacityError,
                       match="fixture accounting drift"):
        validate_capacity_receipt(forged)


def test_capacity_strict_runtime_requires_flags_active_route_and_binds_bytes(
        monkeypatch, tmp_path):
    import shengji.rl.world_afterstate_capacity as capacity

    monkeypatch.delenv("SHENGJI_FAST", raising=False)
    monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS", raising=False)
    with pytest.raises(WorldAfterstateCapacityError,
                       match="strict compiled environment"):
        capacity._strict_runtime_binding()

    python_path = tmp_path / "python"
    router_path = tmp_path / "fast.py"
    native_path = tmp_path / "_fast.so"
    python_path.write_bytes(b"python-v1")
    router_path.write_bytes(b"router-v1")
    native_path.write_bytes(b"native-v1")
    decompose = object()
    round_play = object()
    monkeypatch.setenv("SHENGJI_FAST", "1")
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr(capacity, "_safe_python_runtime", lambda: True)
    monkeypatch.setattr(capacity.sys, "executable", str(python_path))
    monkeypatch.setattr(capacity.fast, "__file__", str(router_path))
    monkeypatch.setattr(capacity.fast, "HAVE_FAST", True)
    monkeypatch.setattr(capacity.fast, "decompose", decompose)
    monkeypatch.setattr(capacity.combos, "decompose", decompose)
    monkeypatch.setattr(capacity.fast, "_fast", SimpleNamespace(
        __file__=str(native_path), round_play=round_play))
    monkeypatch.setattr(capacity.Round, "play", round_play)
    first = capacity._strict_runtime_binding()
    native_path.write_bytes(b"native-v2")
    second = capacity._strict_runtime_binding()
    assert first["native_sha256"] != second["native_sha256"]
    assert first["compiled_engine_active"] is True


def test_capacity_run_wires_the_strict_runtime_gate(monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    monkeypatch.setattr(capacity, "_git", lambda _repo, *args:
                        "e" * 40 if args == ("rev-parse", "HEAD") else "")

    def refuse():
        raise WorldAfterstateCapacityError("strict runtime sentinel")

    monkeypatch.setattr(capacity, "_strict_runtime_binding", refuse)
    with pytest.raises(WorldAfterstateCapacityError,
                       match="strict runtime sentinel"):
        run_capacity(
            repo=Path.cwd(), expected_git="e" * 40, fixture_count=13,
            worker_counts=[1], worker_repetitions=1, batch_sizes=[1],
            model_steps=1, device_name="cpu")


def test_capacity_composed_and_memory_boundaries_are_load_bearing(monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    _prepare_run(monkeypatch, capacity, "d" * 40)
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="d" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[1],
        model_steps=1, device_name="cpu")

    forged = copy.deepcopy(receipt)
    forged["composed_measurement"]["strict_world_materialization"][
        "accepted"] -= 1
    with pytest.raises(WorldAfterstateCapacityError,
                       match="strict world materialization drift"):
        validate_capacity_receipt(forged)

    forged = copy.deepcopy(receipt)
    forged["runtime"]["environment"]["SHENGJI_FAST"] = "0"
    with pytest.raises(WorldAfterstateCapacityError,
                       match="strict runtime identity drift"):
        validate_capacity_receipt(forged)

    forged = copy.deepcopy(receipt)
    forged["aggregate_memory"]["finish_peak_bytes"] = 1
    with pytest.raises(WorldAfterstateCapacityError,
                       match="aggregate memory receipt drift"):
        validate_capacity_receipt(forged)


def test_capacity_receipt_outcome_vocabulary_exclusion_is_load_bearing(
        monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    _prepare_run(monkeypatch, capacity, "6" * 40)
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="6" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[1],
        model_steps=1, device_name="cpu")

    forged = copy.deepcopy(receipt)
    forged["runtime"]["native_path"] = "/runtime/label_fast.so"
    with pytest.raises(
            WorldAfterstateCapacityError,
            match="capacity receipt contains outcome-bearing vocabulary"):
        validate_capacity_receipt(forged)


def test_capacity_receipt_compiled_engine_flag_is_load_bearing(monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    _prepare_run(monkeypatch, capacity, "7" * 40)
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="7" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[1],
        model_steps=1, device_name="cpu")

    forged = copy.deepcopy(receipt)
    forged["runtime"]["compiled_engine_active"] = False
    with pytest.raises(WorldAfterstateCapacityError,
                       match="capacity strict runtime identity drift"):
        validate_capacity_receipt(forged)


def test_capacity_receipt_aggregate_memory_method_is_load_bearing(
        monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    _prepare_run(monkeypatch, capacity, "8" * 40)
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="8" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[1],
        model_steps=1, device_name="cpu")

    forged = copy.deepcopy(receipt)
    forged["aggregate_memory"]["method"] = "parent-rss"
    with pytest.raises(WorldAfterstateCapacityError,
                       match="capacity aggregate memory receipt drift"):
        validate_capacity_receipt(forged)


def test_capacity_memory_snapshot_reads_the_process_cgroup_and_can_fail(
        tmp_path):
    import shengji.rl.world_afterstate_capacity as capacity
    proc = tmp_path / "proc-cgroup"
    root = tmp_path / "cgroup"
    unit = root / "system.slice" / "capacity.service"
    unit.mkdir(parents=True)
    proc.write_text("0::/system.slice/capacity.service\n")
    (unit / "memory.current").write_text("12000\n")
    (unit / "memory.peak").write_text("19000\n")
    assert capacity._capacity_memory_snapshot(
        proc_cgroup=proc, cgroup_root=root) == {
            "method": "linux-cgroup-v2-memory.peak",
            "path": str(unit),
            "current_bytes": 12_000,
            "peak_bytes": 19_000,
        }
    (unit / "memory.peak").write_text("11000\n")
    with pytest.raises(WorldAfterstateCapacityError,
                       match="memory counters drifted"):
        capacity._capacity_memory_snapshot(
            proc_cgroup=proc, cgroup_root=root)
