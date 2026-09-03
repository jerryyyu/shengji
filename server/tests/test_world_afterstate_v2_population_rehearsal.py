from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_population_rehearsal import (
    AUTHORITY, PopulationRehearsalError, rehearsal_identities,
    reopen_population_rehearsal, run_population_rehearsal_v2,
)
from shengji.rl.world_afterstate_v2_protocol import (
    TIER_SPECS, build_population_slot_ledger,
)


def _collection(namespace: str, freeze: str, admission: str,
                *, wrong_group: bool = False, incomplete: bool = False) -> dict:
    slots = list(build_population_slot_ledger(TIER_SPECS[0]))
    rows = []
    for slot in slots[:len(slots) - int(incomplete)]:
        source = "mechanics" if wrong_group and slot.ordinal == 0 else slot.source
        rows.append({
            "slot_sha256": slot.slot_sha256, "tier": slot.tier,
            "split": slot.split, "source": source, "ordinal": slot.ordinal,
            "attempt_count": 2, "accepted_attempt": 1,
            "rejection_counts": [["engine-error", 1]], "shard": {},
        })
    return {
        "schema": "fake", "freeze_sha256": freeze,
        "population_namespace_sha256": namespace,
        "admission_sha256": admission, "tier": "D256",
        "config_sha256": "1" * 64, "max_attempts_per_slot": 128,
        "slots": rows, "attempts_total": len(rows) * 2,
        "accepted_slots": 256 if not incomplete else len(rows),
        "manifest_sha256": "2" * 64, "population_sha256": "3" * 64,
        "authority": dict(AUTHORITY),
    }


def _write_sealed(path: Path, payload: dict) -> None:
    path.write_bytes(canonical_json_bytes(payload))
    path.chmod(0o400)


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch):
    import shengji.rl.world_afterstate_v2_population_rehearsal as module
    expected_head = "a" * 40
    capacity_raw = b"capacity-amendment"
    protocol_raw = b"authoritative-protocol"
    capacity = SimpleNamespace(
        schema="world-afterstate-v2-capacity-economics-amendment-v2",
        population_wall_seconds_max=7200, execution_git=expected_head,
        source_sha256="5" * 64)
    monkeypatch.setattr(module, "capacity_context",
                        lambda raw: (capacity, "D256", 2, 16))
    monkeypatch.setattr(module, "protocol_bytes", lambda: protocol_raw)
    monkeypatch.setattr(module, "reopen_protocol_bytes", lambda raw: {})
    monkeypatch.setattr(module, "population_namespace",
                        lambda *args: "d" * 64)
    monkeypatch.setattr(module, "rehearsal_identities",
                        lambda *args: ("f" * 64, "e" * 64))
    monkeypatch.setattr(module, "_ensure_head_clean", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_capacity_source_sha256", lambda _repo: "5" * 64)
    state = {"collection": None}

    def collect(root: Path, **kwargs):
        root.joinpath("population-controller").mkdir(parents=True)
        root.joinpath("population").mkdir()
        payload = state["collection"] or _collection(
            kwargs["population_namespace_sha256"], kwargs["freeze_sha256"],
            kwargs["admission_sha256"])
        _write_sealed(
            root.joinpath("population-controller", "receipt.json"), payload)
        return payload

    monkeypatch.setattr(module, "collect_population_v2", collect)
    monkeypatch.setattr(module, "reopen_population_collection_v2",
                        lambda root, **kwargs: state["collection"] or _collection(
                            kwargs["population_namespace_sha256"], kwargs["freeze_sha256"],
                            kwargs["admission_sha256"]))
    return module, expected_head, capacity_raw


class _Clock:
    def __init__(self, wall=(10, 20), cpu=(3, 8)):
        self.wall = iter(wall)
        self.cpu = iter(cpu)

    def monotonic_ns(self):
        return next(self.wall)

    def process_time_ns(self):
        return next(self.cpu)


def _probes():
    values = iter((1000, 900))
    return {"disk_free_bytes": lambda _path: next(values),
            "peak_rss_bytes": lambda: 7000}


def test_full_d256_wiring_counts_pairs_resources_and_authority(
        tmp_path: Path, seams):
    module, head, capacity = seams
    root, receipt = tmp_path / "root", tmp_path / "rehearsal.json"
    result = run_population_rehearsal_v2(
        capacity, root, receipt, expected_head=head, clock=_Clock(),
        resource_probes=_probes())
    assert result.group_counts == {
        "natural-fit": 128, "mechanics-fit": 32,
        "natural-select": 48, "natural-audit": 48}
    assert result.fit_pair_counts == {"natural": 64, "mechanics": 16}
    assert result.attempts_total == 512
    assert result.rejection_counts == {"engine-error": 256}
    assert result.elapsed_wall_ns == 10
    assert result.process_cpu_ns == 5
    assert result.disk_free_before_bytes == 1000
    assert result.disk_free_after_bytes == 900
    assert result.population_root == str(root.resolve())
    assert result.payload()["authority"] == AUTHORITY
    assert all(value is False for value in AUTHORITY.values())
    assert reopen_population_rehearsal(
        receipt, root=root, capacity_raw=capacity, expected_head=head
    ).payload() == result.payload()


def test_reopen_binds_selected_population_worker_to_capacity(
        tmp_path: Path, seams, monkeypatch: pytest.MonkeyPatch):
    module, head, capacity = seams
    root, receipt = tmp_path / "root", tmp_path / "rehearsal.json"
    run_population_rehearsal_v2(
        capacity, root, receipt, expected_head=head, clock=_Clock(),
        resource_probes=_probes())
    original = module.capacity_context
    monkeypatch.setattr(
        module, "capacity_context",
        lambda raw: (original(raw)[0], "D256", 1, 16))
    with pytest.raises(PopulationRehearsalError,
                       match="capacity tier binding drift"):
        reopen_population_rehearsal(
            receipt, root=root, capacity_raw=capacity, expected_head=head)


def test_identities_are_deterministic_and_distinct():
    args = ("a" * 40, "b" * 64, "c" * 64, "d" * 64)
    assert rehearsal_identities(*args) == rehearsal_identities(*args)
    assert rehearsal_identities(*args)[0] != rehearsal_identities(*args)[1]


def test_disk_fallback_probes_existing_parent_before_fresh_root(
        tmp_path: Path, seams, monkeypatch: pytest.MonkeyPatch):
    module, head, capacity = seams
    seen = []
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: (
        seen.append(Path(path)) or SimpleNamespace(free=100)))
    run_population_rehearsal_v2(
        capacity, tmp_path / "fresh", tmp_path / "outer.json",
        expected_head=head, clock=_Clock(),
        resource_probes={"peak_rss_bytes": lambda: 1})
    assert seen[0] == tmp_path


@pytest.mark.parametrize("kind", ["incomplete", "wrong_group"])
def test_incomplete_or_wrong_group_refuses_without_outer_receipt(
        tmp_path: Path, seams, kind):
    module, head, capacity = seams
    original = module.collect_population_v2
    original_reopen = module.reopen_population_collection_v2
    payload = _collection("d" * 64, "f" * 64, "e" * 64,
                          **{kind: True})
    def collect(root, **kwargs):
        root.joinpath("population-controller").mkdir(parents=True)
        root.joinpath("population").mkdir()
        _write_sealed(
            root.joinpath("population-controller", "receipt.json"), payload)
    module.collect_population_v2 = collect
    module.reopen_population_collection_v2 = lambda root, **kwargs: payload
    try:
        with pytest.raises(PopulationRehearsalError):
            run_population_rehearsal_v2(
                capacity, tmp_path / "root", tmp_path / "outer.json",
                expected_head=head, clock=_Clock(), resource_probes=_probes())
        assert not (tmp_path / "outer.json").exists()
    finally:
        module.collect_population_v2 = original
        module.reopen_population_collection_v2 = original_reopen


def test_wall_and_downstream_namespace_refuse(tmp_path: Path, seams):
    module, head, capacity = seams
    with pytest.raises(PopulationRehearsalError, match="wall"):
        run_population_rehearsal_v2(
            capacity, tmp_path / "slow", tmp_path / "slow.json",
            expected_head=head, clock=_Clock(wall=(0, 7_200_000_000_001)),
            resource_probes=_probes())
    original = module.collect_population_v2
    original_reopen = module.reopen_population_collection_v2
    def collect(root, **kwargs):
        root.joinpath("population-controller").mkdir(parents=True)
        root.joinpath("population").mkdir()
        root.joinpath("label").mkdir()
        _write_sealed(
            root.joinpath("population-controller", "receipt.json"),
            _collection(kwargs["population_namespace_sha256"],
                        kwargs["freeze_sha256"],
                        kwargs["admission_sha256"]))
    module.collect_population_v2 = collect
    module.reopen_population_collection_v2 = lambda root, **kwargs: _collection(
        kwargs["population_namespace_sha256"], kwargs["freeze_sha256"],
        kwargs["admission_sha256"])
    try:
        with pytest.raises(PopulationRehearsalError, match="downstream"):
            run_population_rehearsal_v2(
                capacity, tmp_path / "bad", tmp_path / "bad.json",
                expected_head=head, clock=_Clock(), resource_probes=_probes())
    finally:
        module.collect_population_v2 = original
        module.reopen_population_collection_v2 = original_reopen


def test_tampered_outer_or_collection_receipt_refuses(tmp_path: Path, seams):
    module, head, capacity = seams
    root, receipt = tmp_path / "root", tmp_path / "outer.json"
    run_population_rehearsal_v2(capacity, root, receipt, expected_head=head,
                                clock=_Clock(), resource_probes=_probes())
    payload = json.loads(receipt.read_bytes())
    payload["population_namespace_sha256"] = "0" * 64
    with pytest.raises(PopulationRehearsalError, match="self hash"):
        reopen_population_rehearsal(canonical_json_bytes(payload))
    collection = root / "population-controller" / "receipt.json"
    value = json.loads(collection.read_bytes())
    value["attempts_total"] += 1
    collection.chmod(0o600)
    _write_sealed(collection, value)
    with pytest.raises(PopulationRehearsalError):
        reopen_population_rehearsal(receipt, root=root)


def test_existing_root_or_outer_is_refused_as_no_resume(tmp_path: Path, seams):
    _module, head, capacity = seams
    root = tmp_path / "root"
    root.mkdir()
    (root / "old").write_text("x")
    with pytest.raises(PopulationRehearsalError, match="retry"):
        run_population_rehearsal_v2(capacity, root, tmp_path / "outer.json",
                                    expected_head=head, clock=_Clock(),
                                    resource_probes=_probes())


def test_outer_receipt_and_progress_must_be_outside_population_root(
        tmp_path: Path, seams):
    _module, head, capacity = seams
    root = tmp_path / "root"
    with pytest.raises(PopulationRehearsalError, match="receipt must be outside"):
        run_population_rehearsal_v2(
            capacity, root, root / "rehearsal.json", expected_head=head,
            clock=_Clock(), resource_probes=_probes())
    with pytest.raises(PopulationRehearsalError, match="progress path must be outside"):
        run_population_rehearsal_v2(
            capacity, root, tmp_path / "rehearsal.json", expected_head=head,
            progress=root / "progress.jsonl", clock=_Clock(),
            resource_probes=_probes())


def test_reopen_refuses_a_different_population_root(tmp_path: Path, seams):
    _module, head, capacity = seams
    root, receipt = tmp_path / "root", tmp_path / "rehearsal.json"
    run_population_rehearsal_v2(
        capacity, root, receipt, expected_head=head, clock=_Clock(),
        resource_probes=_probes())
    with pytest.raises(PopulationRehearsalError,
                       match="population root binding drift"):
        reopen_population_rehearsal(receipt, root=tmp_path / "other")
