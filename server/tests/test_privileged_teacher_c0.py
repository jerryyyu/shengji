"""Adversarial witnesses for the PT C0 full-play consumer ladder."""

from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.smart import SmartBot
from shengji.rl import privileged_teacher_c0 as c0
from shengji.rl import privileged_teacher_full_ab as full


_SECRET = b"pt-full-private-seed-material!!!"
assert len(_SECRET) == 32


def _parent_design() -> full.FullABDesign:
    return full.FullABDesign(
        seed_commitment_sha256=hashlib.sha256(_SECRET).hexdigest(),
        execution_git="a" * 40,
        native_sha256="b" * 64,
        hostname=full.MINI_HOSTNAME,
    )


def _production_work() -> dict[str, int]:
    result = {field: 0 for field in full._WORK_FIELDS}
    result.update({
        "search_calls": 1,
        "rollouts": 660,
        "sample_attempts": 330,
        "accepted_worlds": 330,
        "verified_rollouts": 660,
    })
    return result


def _parent_outcome(arm: str, *, points: int, banker: int,
                    treatment: int) -> full.ArmOutcome:
    return full.ArmOutcome(
        arm=arm,
        attacker_points=points,
        signed_level_utility=full.signed_level_utility(
            points, banker_seat=banker, perspective_seat=treatment),
        decision_count=60,
        work=_production_work(),
    )


def _parent_record(rank: str, banker: int, role: str) -> dict[str, object]:
    treatment = banker % 2 if role == "banker-team" else 1 - banker % 2
    return full._record_payload(
        rank=rank, banker=banker, replicate=0, role=role,
        root_sha256=hashlib.sha256(f"{rank}:{banker}".encode()).hexdigest(),
        a=_parent_outcome("A", points=80, banker=banker, treatment=0),
        a0=_parent_outcome(
            "A0", points=40, banker=banker, treatment=treatment),
        b=_parent_outcome(
            "B", points=120, banker=banker, treatment=treatment),
    )


def _parent_report() -> dict[str, object]:
    design = _parent_design()
    records = [_parent_record(rank, banker, role)
               for rank, banker, _ in design.root_coordinates
               for role in full.ROLES]
    body = {
        "schema": full.SCHEMA,
        "status": "COMPLETE",
        "design": design.payload(),
        "completed_roots": 26,
        "record_count": 52,
        "played_round_count": 130,
        "records": records,
        "summaries": full._summaries(records),
        "elapsed_seconds": 1.0,
        "authority": dict(full.AUTHORITY),
    }
    return {**body, "report_sha256": full._sha(body)}


def _design(parent: dict[str, object] | None = None) -> c0.C0Design:
    parent = _parent_report() if parent is None else parent
    return c0.C0Design(
        seed_commitment_sha256=hashlib.sha256(_SECRET).hexdigest(),
        execution_git="c" * 40,
        native_sha256="d" * 64,
        hostname=full.MINI_HOSTNAME,
        parent_external_sha256=hashlib.sha256(
            full.canonical_json_bytes(parent)).hexdigest(),
        parent_report_sha256=parent["report_sha256"],
        parent_execution_git="a" * 40,
    )


def _telemetry(*, candidates: int = 2, changed: int = 0,
               outside: int = 0) -> dict[str, int]:
    return {
        "treatment_decisions": 1,
        "contested_decisions": 1,
        "candidate_count_sum": candidates,
        "selected_differs_from_candidate_zero": changed,
        "selected_outside_production_ballot": outside,
        "bare_point_avoidance": 0,
        "bare_point_introduction": 0,
        "positive_exact_gap": changed,
        "zero_exact_gap": 1 - changed,
        "negative_exact_gap": 0,
    }


def _c0_work(*, candidates: int = 2) -> dict[str, int]:
    result = {field: 0 for field in full._WORK_FIELDS}
    result.update({
        "search_calls": 1,
        "rollouts": candidates,
        "sample_attempts": 1,
        "accepted_worlds": 1,
        "verified_rollouts": candidates,
    })
    return result


def _outcome(arm: str, *, points: int, banker: int,
             treatment: int) -> c0.C0Outcome:
    return c0.C0Outcome(
        arm=arm,
        attacker_points=points,
        signed_level_utility=full.signed_level_utility(
            points, banker_seat=banker, perspective_seat=treatment),
        decision_count=60,
        work=_c0_work(),
        telemetry=_telemetry(),
    )


def _c0_report(parent: dict[str, object],
               design: c0.C0Design) -> dict[str, object]:
    parents = c0._parent_records(parent)
    records = []
    for coordinate in design.root_coordinates:
        rank, banker, _ = coordinate
        for role in c0.ROLES:
            treatment = banker % 2 if role == "banker-team" else 1 - banker % 2
            records.append(c0._record_payload(
                coordinate=coordinate, role=role,
                parent=parents[(*coordinate, role)],
                outcomes=tuple(_outcome(
                    arm, points=80 + 40 * index, banker=banker,
                    treatment=treatment)
                    for index, arm in enumerate(c0.ARMS))))
    body = {
        "schema": c0.SCHEMA,
        "status": "COMPLETE",
        "design": design.payload(),
        "completed_roots": 26,
        "record_count": 52,
        "played_round_count": 156,
        "records": records,
        "summaries": c0._summaries(records),
        "elapsed_seconds": 2.0,
        "authority": dict(c0.AUTHORITY),
    }
    return {**body, "report_sha256": c0._sha(body)}


def _decision_record() -> dict[str, object]:
    return {
        "n_determinizations": 1,
        "report_worlds_requested": 0,
        "report_rule": "none",
        "margin": 0.0,
        "candidates": [["H10"], ["S3"]],
        "means": [0.0, 1.0],
        "played_index": 1,
        "alloc": {
            "mode": "uniform", "worlds": 1, "short": False,
            "n_by_candidate": [1, 1],
        },
        "work": {
            "selection_budget": 2, "selection_rollouts": 2,
            "report_budget": 0, "report_rollouts": 0,
            "total_budget": 2, "total_rollouts": 2,
            "complete": True,
        },
        "sampler_counters": {"delta": {
            "sample_attempts": 1, "accepted_worlds": 1,
            "failed_worlds": 0, "rejected_worlds": 0,
            "impossible_worlds": 0,
        }},
    }


def test_c0_design_reuses_parent_population_and_authorizes_nothing():
    parent = _parent_report()
    design = _design(parent)
    assert design.root_coordinates == _parent_design().root_coordinates
    assert design.payload()["played_round_count"] == 156
    assert design.payload()["parent_report_sha256"] == parent["report_sha256"]
    assert not any(design.payload()["authority"].values())
    assert c0.validate_parent(parent, design) == _parent_design()
    tampered = copy.deepcopy(parent)
    tampered["report_sha256"] = "f" * 64
    with pytest.raises(c0.PrivilegedTeacherC0Error,
                       match="parent report refused"):
        c0.validate_parent(tampered, design)
    wrong_external = c0.C0Design(
        seed_commitment_sha256=design.seed_commitment_sha256,
        execution_git=design.execution_git,
        native_sha256=design.native_sha256,
        hostname=design.hostname,
        parent_external_sha256="e" * 64,
        parent_report_sha256=design.parent_report_sha256,
        parent_execution_git=design.parent_execution_git,
    )
    with pytest.raises(c0.PrivilegedTeacherC0Error,
                       match="parent report identity drift"):
        c0.validate_parent(parent, wrong_external)


def test_c0_policy_ladder_changes_one_axis_at_a_time():
    p = c0.C0ProductionBallotBot(seed=1)
    h = c0.C0WideHeuristicBot(seed=1)
    s = c0.C0WideSmartBot(seed=1)
    assert p.N_DETERMINIZATIONS == h.N_DETERMINIZATIONS == \
        s.N_DETERMINIZATIONS == 1
    assert p.LEVEL_OBJECTIVE and h.LEVEL_OBJECTIVE and s.LEVEL_OBJECTIVE
    assert p.REPORT_FOLD_WORLDS == h.REPORT_FOLD_WORLDS == \
        s.REPORT_FOLD_WORLDS == 0
    assert p.TRACTOR_LOCK is True and h.TRACTOR_LOCK is False
    assert p.V3_LEAD_SINGLES is False and h.V3_LEAD_SINGLES is True
    assert type(p.rollout_policy) is HeuristicBot
    assert type(h.rollout_policy) is HeuristicBot
    assert type(s.rollout_policy) is SmartBot
    assert [p._score(points) for points in (0, 1, 39, 40, 79, 80, 120, 200)] == [
        -3.0, -2.0, -2.0, -1.0, -1.0, 1.0, 1.0, 3.0]
    for bad in (True, -1, 79.5, float("inf")):
        with pytest.raises(c0.PrivilegedTeacherC0Error,
                           match="terminal score drift"):
            p._score(bad)


def test_wide_ballot_contains_production_and_has_nonzero_dose():
    rnd = full._build_root(_parent_design(), _SECRET, "7", 0, 0)
    production = c0._production_ballot(rnd, rnd.turn)
    wide = {tuple(sorted(action)) for action in
            c0.C0WideHeuristicBot(seed=1)._candidates(rnd, rnd.turn)}
    assert production <= wide
    assert wide - production


def test_exact_work_and_bare_point_wiring_can_fail():
    record = _decision_record()
    bot = SimpleNamespace(last_decision_record=record)
    assert c0._verify_c0_decision_work(bot) == 2
    telemetry = c0._telemetry()
    assert c0._observe_decision(
        telemetry, bot, was_lead=True,
        production_ballot={("H10",), ("S3",)}) == 2
    assert telemetry["selected_differs_from_candidate_zero"] == 1
    assert telemetry["bare_point_avoidance"] == 1
    assert telemetry["positive_exact_gap"] == 1
    for mutate in (
            lambda row: row.update(n_determinizations=30),
            lambda row: row["alloc"].update(n_by_candidate=[1, 0]),
            lambda row: row["work"].update(total_rollouts=0),
            lambda row: row["sampler_counters"]["delta"].update(
                accepted_worlds=0, failed_worlds=1)):
        broken = copy.deepcopy(record)
        mutate(broken)
        with pytest.raises(c0.PrivilegedTeacherC0Error,
                           match="contested decision exact work drift"):
            c0._verify_c0_decision_work(
                SimpleNamespace(last_decision_record=broken))


def test_play_arm_wires_exact_verifier_and_sentinel_to_published_outcome(
        monkeypatch):
    class FakeRound:
        def __init__(self):
            self.phase = "play"
            self.turn = 0
            self.banker = 0
            self.attacker_points = 80
            self.trick = SimpleNamespace(plays=[])

        def play(self, seat, cards):
            assert seat == 0 and cards == ["S3"]
            self.phase = "round_end"
            self.turn = None

    class FakeBot:
        def __init__(self, active=False):
            for field in full._WORK_FIELDS:
                if field != "verified_rollouts":
                    setattr(self, field, 0)
            self.last_decision_record = None
            self.active = active

        def decide_play(self, _rnd, _seat):
            assert self.active
            self.last_decision_record = _decision_record()
            self.search_calls = 1
            self.rollouts = 2
            self.sample_attempts = 1
            self.accepted_worlds = 1
            return ["S3"]

    bots = [FakeBot(True), FakeBot(), FakeBot(), FakeBot()]
    monkeypatch.setattr(c0, "_bots", lambda *_args, **_kwargs: bots)
    monkeypatch.setattr(
        c0, "_production_ballot", lambda *_args: {("H10",), ("S3",)})
    original = c0._verify_c0_decision_work
    calls = []

    def verify(bot):
        calls.append(bot)
        return original(bot)

    monkeypatch.setattr(c0, "_verify_c0_decision_work", verify)
    outcome = c0._play_arm(
        FakeRound(), rank="7", banker=0, replicate=0, arm="C0-P",
        treatment_team=0, seed_secret=_SECRET)
    assert calls == [bots[0]]
    assert outcome.work["verified_rollouts"] == 2
    assert outcome.telemetry["contested_decisions"] == 1
    assert outcome.telemetry["bare_point_avoidance"] == 1


def test_reconstructed_root_and_both_roles_are_bound_before_play(monkeypatch):
    parent = _parent_report()
    design = _design(parent)
    parent_design = _parent_design()
    rows = c0._parent_records(parent)
    coordinate = design.root_coordinates[0]
    root_hash = rows[(*coordinate, "banker-team")]["root_sha256"]
    monkeypatch.setattr(full, "_build_root", lambda *_args: object())
    monkeypatch.setattr(full, "_root_sha256", lambda _root: root_hash)
    calls = []

    def play(_root, *, rank, banker, replicate, arm, treatment_team,
             seed_secret):
        del rank, replicate
        assert seed_secret == _SECRET
        calls.append((arm, treatment_team))
        return _outcome(
            arm, points=80, banker=banker, treatment=treatment_team)

    monkeypatch.setattr(c0, "_play_arm", play)
    records = c0._run_root(
        design, parent_design, rows, _SECRET, coordinate)
    assert calls == [
        (arm, treatment) for treatment in (0, 1) for arm in c0.ARMS]
    assert len(records) == 2
    bad_rows = copy.deepcopy(rows)
    bad_rows[(*coordinate, "attacker-team")]["root_sha256"] = "f" * 64
    with pytest.raises(c0.PrivilegedTeacherC0Error,
                       match="reconstructed parent root drift"):
        c0._run_root(design, parent_design, bad_rows, _SECRET, coordinate)


def test_report_roundtrip_tamper_and_privacy_boundaries():
    parent = _parent_report()
    design = _design(parent)
    report = _c0_report(parent, design)
    external = design.parent_external_sha256
    raw = c0.report_bytes(
        report, design, parent, parent_external_sha256=external)
    assert json.loads(raw)["report_sha256"] == report["report_sha256"]
    forbidden = {"hands", "buried", "deck", "seed", "rng_state"}

    def walk(value):
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(json.loads(raw))
    tampered = copy.deepcopy(report)
    tampered["records"][0]["arms"]["C0-H"]["telemetry"][
        "candidate_count_sum"] = 0
    body = {key: value for key, value in tampered["records"][0].items()
            if key != "record_sha256"}
    tampered["records"][0]["record_sha256"] = c0._sha(body)
    tampered["summaries"] = c0._summaries(tampered["records"])
    body = {key: value for key, value in tampered.items()
            if key != "report_sha256"}
    tampered["report_sha256"] = c0._sha(body)
    with pytest.raises(c0.PrivilegedTeacherC0Error,
                       match="telemetry accounting drift"):
        c0.validate_report(
            tampered, design, parent,
            parent_external_sha256=external)


def test_run_refuses_parent_or_secret_before_any_root(monkeypatch):
    parent = _parent_report()
    design = _design(parent)
    monkeypatch.setattr(
        c0, "_run_root", lambda *_args: (_ for _ in ()).throw(
            AssertionError("root opened before admission refusal")))
    with pytest.raises(c0.PrivilegedTeacherC0Error,
                       match="seed secret commitment drift"):
        c0.run_dev(
            design, parent_report=parent, seed_secret=b"z" * 32,
            parent_external_sha256=design.parent_external_sha256)
    with pytest.raises(c0.PrivilegedTeacherC0Error,
                       match="parent external identity drift"):
        c0.run_dev(
            design, parent_report=parent, seed_secret=_SECRET,
            parent_external_sha256="f" * 64)
