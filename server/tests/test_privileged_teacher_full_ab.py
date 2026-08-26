"""Adversarial witnesses for the DEV-only PT-Full A/A0/B diagnostic."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from shengji.ai.memory import Memory
from shengji.engine.cards import RANKS
from shengji.rl import privileged_teacher_full_ab as full


_SECRET = b"pt-full-private-seed-material!!!"
assert len(_SECRET) == 32


def _design(**changes) -> full.FullABDesign:
    values = {
        "seed_commitment_sha256": hashlib.sha256(_SECRET).hexdigest(),
        "execution_git": "a" * 40,
        "native_sha256": "b" * 64,
        "hostname": "Jerrys-Mac-mini.local",
    }
    values.update(changes)
    return full.FullABDesign(**values)


def _work(value: int = 0) -> dict[str, int]:
    result = {field: value for field in full._WORK_FIELDS}
    result.update({
        "search_calls": 1,
        "rollouts": 660,
        "sample_attempts": 330,
        "accepted_worlds": 330,
        "verified_rollouts": 660,
    })
    return result


def _outcome(arm: str, *, points: int, banker: int,
             treatment: int) -> full.ArmOutcome:
    return full.ArmOutcome(
        arm=arm,
        attacker_points=points,
        signed_level_utility=full.signed_level_utility(
            points, banker_seat=banker, perspective_seat=treatment),
        decision_count=61,
        work=_work(),
    )


def _record(rank: str, banker: int, replicate: int, role: str,
            *, root_sha: str | None = None) -> dict[str, object]:
    banker_team = banker % 2
    treatment = banker_team if role == "banker-team" else 1 - banker_team
    return full._record_payload(
        rank=rank,
        banker=banker,
        replicate=replicate,
        role=role,
        root_sha256=root_sha or hashlib.sha256(
            f"{rank}:{banker}:{replicate}".encode()).hexdigest(),
        a=_outcome("A", points=80, banker=banker, treatment=0),
        a0=_outcome("A0", points=80, banker=banker, treatment=treatment),
        b=_outcome("B", points=120, banker=banker, treatment=treatment),
    )


def _report() -> dict[str, object]:
    design = _design()
    records = [
        _record(rank, banker, replicate, role)
        for rank, banker, replicate in design.root_coordinates
        for role in full.ROLES
    ]
    body = {
        "schema": full.SCHEMA,
        "status": "COMPLETE",
        "design": design.payload(),
        "completed_roots": len(design.root_coordinates),
        "record_count": len(records),
        "played_round_count": len(design.root_coordinates) * 5,
        "records": records,
        "summaries": full._summaries(records),
        "elapsed_seconds": 1.5,
        "authority": dict(full.AUTHORITY),
    }
    return {**body, "report_sha256": full._sha(body)}


def _reseal_record(record: dict[str, object]) -> None:
    body = {key: value for key, value in record.items()
            if key != "record_sha256"}
    record["record_sha256"] = full._sha(body)


def _reseal_report(report: dict[str, object]) -> None:
    report["summaries"] = full._summaries(report["records"])
    body = {key: value for key, value in report.items()
            if key != "report_sha256"}
    report["report_sha256"] = full._sha(body)


def test_design_is_exact_rank_diverse_bounded_population():
    design = _design()
    assert len(design.root_coordinates) == 26
    assert {rank for rank, _, _ in design.root_coordinates} == set(RANKS)
    assert design.payload()["comparison_record_count"] == 52
    assert design.payload()["played_round_count"] == 130
    assert not any(design.payload()["authority"].values())
    with pytest.raises(full.PrivilegedTeacherFullABError,
                       match="exactly one replicate"):
        _design(replicates=2)
    assert full._derive_seed(_SECRET, "deal", "7", 0, 0) != \
        full._derive_seed(b"x" * 32, "deal", "7", 0, 0)


def test_repeated_public_world_reuses_fresh_copies(monkeypatch):
    calls = {"count": 0}

    def sampled(_self, _rnd, _seat, _memory):
        calls["count"] += 1
        return ({1: ["C3"], 2: ["D4"], 3: ["S5"]}, ["H6"])

    monkeypatch.setattr(full._Production, "_sample_hands", sampled)
    bot = full.RepeatedPublicWorldBot(seed=7)
    bot._ptfull_repeated_world = None
    first = bot._sample_hands(object(), 0, object())
    first[0][1].append("C4")
    first[1].append("H7")
    second = bot._sample_hands(object(), 0, object())
    assert calls["count"] == 1
    assert second == ({1: ["C3"], 2: ["D4"], 3: ["S5"]}, ["H6"])
    assert second is not first and second[0] is not first[0]


def test_public_sampler_is_hidden_twin_invariant_and_true_world_is_not():
    design = _design()
    rnd = full._build_root(design, _SECRET, "7", 0, 0)
    twin = copy.deepcopy(rnd)
    # Seat 2 sees neither seat 1 nor seat 3.  Swap distinct physical cards
    # while preserving every public byte and every hand size.
    swap = next((i, j) for i, left in enumerate(twin.hands[1])
                for j, right in enumerate(twin.hands[3]) if left != right)
    i, j = swap
    twin.hands[1][i], twin.hands[3][j] = (
        twin.hands[3][j], twin.hands[1][i])
    public_first = full.RepeatedPublicWorldBot(seed=19)
    public_second = full.RepeatedPublicWorldBot(seed=19)
    sampled_first = public_first._sample_hands(rnd, 2, Memory(rnd, 2))
    sampled_second = public_second._sample_hands(twin, 2, Memory(twin, 2))
    assert sampled_first == sampled_second

    oracle = full.TrueWorldProductionBot(seed=19)
    with pytest.raises(full.PrivilegedTeacherFullABError,
                       match="requires marked privileged round"):
        oracle._sample_hands(rnd, 2, Memory(rnd, 2))
    rnd._ptfull_true_world = True
    twin._ptfull_true_world = True
    assert oracle._sample_hands(rnd, 2, Memory(rnd, 2)) != \
        oracle._sample_hands(twin, 2, Memory(twin, 2))


def test_each_root_runs_public_once_and_both_treatment_roles(monkeypatch):
    calls: list[tuple[str, int]] = []
    root = object()
    monkeypatch.setattr(full, "_build_root", lambda *_args: root)
    monkeypatch.setattr(full, "_root_sha256", lambda _root: "a" * 64)

    def play(_root, *, rank, banker, replicate, arm, treatment_team,
             seed_secret):
        del rank, replicate
        assert seed_secret == _SECRET
        calls.append((arm, treatment_team))
        points = 80 if arm != "B" else 120
        return _outcome(
            arm, points=points, banker=banker, treatment=treatment_team)

    monkeypatch.setattr(full, "_play_arm", play)
    records = full._run_root(_design(), _SECRET, ("7", 0, 0))
    assert calls == [("A", 0), ("A0", 0), ("B", 0),
                     ("A0", 1), ("B", 1)]
    assert [row["role"] for row in records] == list(full.ROLES)
    assert records[0]["root_sha256"] == records[1]["root_sha256"]


def test_run_progress_is_complete_ordered_and_deterministic(monkeypatch):
    def run_root(_design_value, seed_secret, coordinate):
        assert seed_secret == _SECRET
        rank, banker, replicate = coordinate
        return tuple(_record(rank, banker, replicate, role)
                     for role in full.ROLES)

    monkeypatch.setattr(full, "_run_root", run_root)
    ticks = iter(float(i) for i in range(28))
    monkeypatch.setattr(full.time, "monotonic", lambda: next(ticks))
    progress = []
    design = _design()
    report = full.run_dev(
        design, seed_secret=_SECRET, workers=1,
        progress_sink=progress.append)
    full.validate_report(report, design)
    assert len(progress) == 26
    assert progress[-1]["completed_roots"] == 26
    assert progress[-1]["percent_basis_points"] == 10_000
    assert [(row["trump_rank"], row["banker"], row["role"])
            for row in report["records"][:4]] == [
                (RANKS[0], 0, "banker-team"),
                (RANKS[0], 0, "attacker-team"),
                (RANKS[0], 1, "banker-team"),
                (RANKS[0], 1, "attacker-team"),
            ]


def test_semantic_tamper_and_cross_role_binding_refuse_after_rehash():
    report = _report()
    design = _design()
    full.validate_report(report, design)
    bad_utility = copy.deepcopy(report)
    bad_utility["records"][0]["arms"]["B"]["signed_level_utility"] += 1
    _reseal_record(bad_utility["records"][0])
    _reseal_report(bad_utility)
    with pytest.raises(full.PrivilegedTeacherFullABError,
                       match="signed utility drift"):
        full.validate_report(bad_utility, design)

    bad_root = copy.deepcopy(report)
    bad_root["records"][1]["root_sha256"] = "f" * 64
    _reseal_record(bad_root["records"][1])
    _reseal_report(bad_root)
    with pytest.raises(full.PrivilegedTeacherFullABError,
                       match="root role binding drift"):
        full.validate_report(bad_root, design)

    bad_public = copy.deepcopy(report)
    bad_public["records"][1]["arms"]["A"]["attacker_points"] = 120
    bad_public["records"][1]["arms"]["A"]["signed_level_utility"] = 1
    _reseal_record(bad_public["records"][1])
    _reseal_report(bad_public)
    with pytest.raises(full.PrivilegedTeacherFullABError,
                       match="public arm role binding drift"):
        full.validate_report(bad_public, design)


def test_report_has_no_raw_hidden_world_or_seed_fields():
    raw = full.report_bytes(_report(), _design())
    payload = json.loads(raw)
    forbidden = {"hands", "buried", "deck", "round_seed", "policy_seed"}

    def walk(value):
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)


def test_exact_work_wiring_passes_and_each_failure_direction_refuses():
    record = {
        "n_determinizations": 30,
        "report_worlds_requested": 300,
        "alloc": {
            "mode": "uniform", "worlds": 30, "short": False,
            "n_by_candidate": [30, 30],
        },
        "work": {
            "selection_budget": 60, "selection_rollouts": 60,
            "report_budget": 600, "report_rollouts": 600,
            "total_budget": 660, "total_rollouts": 660,
            "complete": True,
        },
        "report_fold": {"worlds": 300, "complete": True},
        "sampler_counters": {"delta": {
            "sample_attempts": 330, "accepted_worlds": 330,
            "failed_worlds": 0, "rejected_worlds": 0,
            "impossible_worlds": 0,
        }},
    }
    assert full._verify_decision_work(
        SimpleNamespace(last_decision_record=record)) == 660
    for mutate in (
            lambda row: row["alloc"].update(short=True),
            lambda row: row["work"].update(report_rollouts=598),
            lambda row: row["work"].update(
                selection_budget=0, selection_rollouts=0,
                report_budget=0, report_rollouts=0,
                total_budget=0, total_rollouts=0),
            lambda row: row["report_fold"].update(complete=False),
            lambda row: row["sampler_counters"]["delta"].update(
                accepted_worlds=329)):
        broken = copy.deepcopy(record)
        mutate(broken)
        with pytest.raises(full.PrivilegedTeacherFullABError,
                           match="contested decision exact work drift"):
            full._verify_decision_work(
                SimpleNamespace(last_decision_record=broken))


def test_seed_secret_commitment_is_required_before_any_root(monkeypatch):
    monkeypatch.setattr(
        full, "_run_root",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("root opened before commitment refusal")))
    with pytest.raises(full.PrivilegedTeacherFullABError,
                       match="seed secret commitment drift"):
        full.run_dev(_design(), seed_secret=b"z" * 32, workers=1)
