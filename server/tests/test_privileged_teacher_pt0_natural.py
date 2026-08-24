"""Small, real-engine witnesses for the natural PT0 source core."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from shengji.rl.privileged_teacher_pt0_natural import (
    NaturalPT0Design,
    NaturalPT0Error,
    _make_record,
    _sample_worlds,
    capture_natural_states,
    run_natural_packet,
)


CAPTURE_SECRET = bytes(range(32))
CAPTURE_SECRET_SHA256 = hashlib.sha256(CAPTURE_SECRET).hexdigest()


def _design() -> NaturalPT0Design:
    return NaturalPT0Design(
        capture_secret_sha256=CAPTURE_SECRET_SHA256,
        trump_ranks=("7",), production_policy="heuristic",
        banker_seats=(0,),
        unique_worlds_per_state=2, max_sampler_attempts=100,
        max_exact_nodes=50_000)


def test_capture_is_engine_driven_and_covers_exact_rank_role_threshold(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    captured = capture_natural_states(
        _design(), capture_secret=CAPTURE_SECRET)
    assert set(captured) == {
        ("7", 0, "banker-team", 2), ("7", 0, "attacker-team", 2),
        ("7", 0, "banker-team", 3), ("7", 0, "attacker-team", 3),
    }
    assert all(state.phase == "play" and state.turn is not None
               for state in captured.values())


def test_rank_banker_cells_use_domain_separated_deals(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    design = NaturalPT0Design(
        capture_secret_sha256=CAPTURE_SECRET_SHA256,
        trump_ranks=("7", "8"),
        production_policy="heuristic", banker_seats=(0, 1),
        unique_worlds_per_state=2, max_sampler_attempts=100,
        max_exact_nodes=50_000)
    captured = capture_natural_states(
        design, capture_secret=CAPTURE_SECRET)
    cell_seeds = {
        (rank, banker): {
            state._natural_round_seed
            for (state_rank, state_banker, _, _), state in captured.items()
            if state_rank == rank and state_banker == banker
        }
        for rank in design.trump_ranks for banker in design.banker_seats
    }
    assert all(len(seeds) == 1 for seeds in cell_seeds.values())
    assert len({next(iter(seeds)) for seeds in cell_seeds.values()}) == 4


def test_same_seed_packet_is_byte_reproducible(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    first = run_natural_packet(_design(), capture_secret=CAPTURE_SECRET)
    second = run_natural_packet(_design(), capture_secret=CAPTURE_SECRET)
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == \
        json.dumps(second, sort_keys=True, separators=(",", ":"))
    assert first["status"] == "COMPLETE"
    assert first["truncated_by_deadline"] is False
    assert first["progress"] == {
        "completed_units": 4, "total_units": 4,
        "percent_basis_points": 10_000,
    }
    assert first["summary"]["complete_grid_inference"] is True
    assert {row["policy"] for row in first["summary"]["policy_summaries"]} == {
        "heuristic", "smart", "mc-s0-report-lcb",
    }
    assert all(row["bootstrap_interval"]["replicates"] == 5_000
               for row in first["summary"]["policy_summaries"])
    assert all({row["dimension"] for row in policy["descriptive_slices"]} == {
        "trump_rank", "banker", "role", "remaining_hand_threshold",
    } for policy in first["summary"]["policy_summaries"])


def test_sampler_requires_strict_void_boundary(monkeypatch):
    state = next(iter(capture_natural_states(
        _design(), capture_secret=CAPTURE_SECRET).values()))
    monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS", raising=False)
    with pytest.raises(NaturalPT0Error, match="SHENGJI_REQUIRE_VOIDS"):
        _sample_worlds(_design(), state, role="banker-team", threshold=2,
                       round_seed=1, trump_rank="7", cohort="proposal", count=2)


def test_sampled_worlds_share_public_fingerprint_and_are_hidden_from_packet(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    design = _design()
    state = next(iter(capture_natural_states(
        design, capture_secret=CAPTURE_SECRET).values()))
    worlds, public = _sample_worlds(
        design, state, role="banker-team", threshold=2, round_seed=1,
        trump_rank="7", cohort="proposal", count=2)
    from shengji.rl.privileged_teacher_pt0 import pt0_public_state_sha256
    assert all(pt0_public_state_sha256(world, perspective_seat=state.turn) == public
               for _, world in worlds)
    packet = run_natural_packet(design, capture_secret=CAPTURE_SECRET)
    raw = json.dumps(packet, sort_keys=True).lower()
    assert "true_world" not in raw and "hidden_hands" not in raw
    assert "round_seed" not in raw
    assert "capture_seed_index" not in raw
    assert all("world_sha256" not in record for record in packet["records"])


def test_deadline_seals_only_complete_record_prefix(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    captured = capture_natural_states(
        _design(), capture_secret=CAPTURE_SECRET)
    emitted = []
    ticks = iter((0.0, 1.0))
    packet = run_natural_packet(
        _design(), capture_secret=CAPTURE_SECRET,
        deadline=0.5, monotonic=lambda: next(ticks),
        state_capture=lambda _: captured,
        record_sink=lambda index, raw: emitted.append((index, raw)))
    assert packet["status"] == "TRUNCATED"
    assert packet["truncated_by_deadline"] is True
    assert packet["record_count"] == 1
    assert packet["summary"]["complete_grid_inference"] is False
    assert all(row["bootstrap_interval"] is None
               for row in packet["summary"]["policy_summaries"])
    assert len(emitted) == 1 and emitted[0][0] == 0
    assert json.loads(emitted[0][1]) == packet["records"][0]
    with pytest.raises(NaturalPT0Error, match="deadline"):
        run_natural_packet(
            _design(), capture_secret=CAPTURE_SECRET,
            deadline=float("nan"))


def test_deadline_can_truncate_inside_capture_before_another_round(monkeypatch):
    calls = []

    def empty_capture(*args, **kwargs):
        calls.append(1)
        return {}

    monkeypatch.setattr(
        "shengji.rl.privileged_teacher_pt0_natural._capture_round",
        empty_capture)
    ticks = iter((0.0, 0.1, 1.0))
    packet = run_natural_packet(
        _design(), capture_secret=CAPTURE_SECRET,
        deadline=0.5, monotonic=lambda: next(ticks))
    assert calls == [1]
    assert packet["status"] == "TRUNCATED"
    assert packet["record_count"] == 0


def test_held_out_summary_preserves_negative_teacher_delta(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    packet = run_natural_packet(_design(), capture_secret=CAPTURE_SECRET)
    for record in packet["records"]:
        for baseline in record["baselines"]:
            baseline["evaluation_delta_pt0_minus_baseline"] = {
                "numerator": -1, "denominator": 1,
            }
    from shengji.rl.privileged_teacher_pt0_natural import (
        summarize_natural_records,
    )
    summary = summarize_natural_records(
        _design(), packet["records"], complete=True)
    assert all(row["mean_held_out_delta"] == {
        "numerator": -1, "denominator": 1,
    } for row in summary["policy_summaries"])
    assert all(row["negative_state_count"] == 4
               for row in summary["policy_summaries"])


def test_bucket_completeness_refuses_missing_bucket(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    design = _design()
    captured = capture_natural_states(
        design, capture_secret=CAPTURE_SECRET)
    captured.pop(("7", 0, "banker-team", 2))
    with pytest.raises(NaturalPT0Error, match="bucket completeness"):
        run_natural_packet(
            design, capture_secret=CAPTURE_SECRET,
            state_capture=lambda _: captured)


def test_proposal_evaluation_overlap_refuses(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    design = _design()
    state = next(iter(capture_natural_states(
        design, capture_secret=CAPTURE_SECRET).values()))
    original = _sample_worlds

    def overlap(*args, **kwargs):
        return original(*args, **{
            **kwargs, "cohort": "proposal", "count": 2,
            "excluded_world_sha256s": frozenset(),
        })

    monkeypatch.setattr(
        "shengji.rl.privileged_teacher_pt0_natural._sample_worlds", overlap)
    with pytest.raises(NaturalPT0Error, match="overlap"):
        _make_record(design, state, role="banker-team", threshold=2,
                     round_seed=1, trump_rank="7")


def test_public_drift_and_duplicate_population_are_load_bearing(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    design = _design()
    state = next(iter(capture_natural_states(
        design, capture_secret=CAPTURE_SECRET).values()))
    original = _sample_worlds

    def drift(*args, **kwargs):
        worlds, public = original(*args, **kwargs)
        altered = copy.copy(worlds[0][1])
        altered.attacker_points += 1
        return [(worlds[0][0], altered), *worlds[1:]], public

    monkeypatch.setattr(
        "shengji.rl.privileged_teacher_pt0_natural._sample_worlds", drift)
    with pytest.raises(NaturalPT0Error, match="public state drift"):
        _make_record(design, state, role="banker-team", threshold=2,
                     round_seed=1, trump_rank="7")
