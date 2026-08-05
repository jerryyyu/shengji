"""Fail-closed contracts for the deep-lead raw-state capture."""
from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from scripts import capture_deep_leads as cap
from shengji.state_replay import replay_deep_lead


def _args(tmp_path, **overrides):
    values = dict(
        mode="capture", seed0=92_000_000, max_seeds=0, bot=cap.BOT,
        salt=cap.SALT, out=str(tmp_path / "deep.jsonl"), per_cell=1,
        shard_index=0, shard_count=1, smoke=True, only_cell=[],
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def _fake_runtime(**_):
    return {"git": "a" * 40, "tree_dirty": True, "fast_engine": True,
            "require_voids": True}


def test_seed_ceiling_is_exclusive_and_capture_never_occupies_final_name(
        tmp_path, monkeypatch):
    """`max-seeds=0` processes zero deals; the aborted script processed one."""
    args = _args(tmp_path)
    called = []
    monkeypatch.setattr(cap, "runtime_contract", _fake_runtime)
    monkeypatch.setattr(cap, "source_digests", lambda: {"test": "1"})
    monkeypatch.setattr(cap, "play_to_trick", lambda *a, **k: called.append(a))
    assert cap.capture(args) == 0
    assert called == []
    assert not (tmp_path / "deep.jsonl").exists(), \
        "capture shards must not poison the final merged artifact name"
    spath = cap.shard_path(args.out, 0, 1)
    assert open(spath).read() == ""
    manifest = json.load(open(cap.manifest_path(spath)))
    assert manifest["scanned_seeds"] == 0
    assert manifest["last_seed"] is None


def test_engine_errors_propagate_and_leave_only_a_partial(tmp_path, monkeypatch):
    args = _args(tmp_path, max_seeds=1)
    split, trick = cap.cell_targets(args.seed0, args.salt)
    args.only_cell = [f"{split}/{trick}/attacker", f"{split}/{trick}/defender"]
    monkeypatch.setattr(cap, "runtime_contract", _fake_runtime)
    monkeypatch.setattr(cap, "source_digests", lambda: {"test": "1"})

    def broken(*_):
        raise AssertionError("illegal engine transition")

    monkeypatch.setattr(cap, "play_to_trick", broken)
    with pytest.raises(AssertionError, match="illegal engine transition"):
        cap.capture(args)
    spath = cap.shard_path(args.out, 0, 1)
    assert not __import__("os").path.exists(spath)
    assert __import__("os").path.exists(spath + ".partial")
    assert not __import__("os").path.exists(cap.manifest_path(spath))


@pytest.mark.parametrize("counter", [
    "zero_world_decisions", "rejected_worlds", "impossible_worlds",
])
def test_any_forbidden_sampler_counter_aborts_shard(
        counter, tmp_path, monkeypatch):
    args = _args(tmp_path, max_seeds=1)
    split, trick = cap.cell_targets(args.seed0, args.salt)
    args.only_cell = [f"{split}/{trick}/attacker", f"{split}/{trick}/defender"]
    monkeypatch.setattr(cap, "runtime_contract", _fake_runtime)
    monkeypatch.setattr(cap, "source_digests", lambda: {"test": "1"})
    policy = SimpleNamespace(zero_world_decisions=0, rejected_worlds=0,
                             impossible_worlds=0, reject_cause={})
    setattr(policy, counter, 1)
    outcome = cap.DealOutcome(None, None, {}, [], [policy])
    monkeypatch.setattr(cap, "play_to_trick", lambda *_: outcome)
    with pytest.raises(RuntimeError, match="forbidden sampler counters"):
        cap.capture(args)


def test_captured_setup_replays_without_reinvoking_declaration_policy():
    outcome = cap.play_to_trick(92_000_000, 0)
    assert outcome.reached
    rnd, seat = outcome.rnd, outcome.seat
    role = "attacker" if rnd.is_attacker(seat) else "defender"
    row = {
        "schema": cap.DEEP_LEAD_STATE_SCHEMA, "seed": 92_000_000,
        "split": "dev", "trick": 0, "role": role, "seat": seat,
        "ply": 0, "setup": outcome.setup, "plays": [],
    }
    rebuilt = replay_deep_lead(row)
    assert rebuilt.turn == seat
    assert rebuilt.banker == rnd.banker
    assert rebuilt.trump_suit == rnd.trump_suit
    assert outcome.setup["declarations"] or outcome.setup["final_declaration"] is None


def test_global_first_n_merge_is_independent_of_shard_completion_order():
    cell = ("dev", 12, "attacker")
    rows = [{"seed": seed, "split": cell[0], "trick": cell[1],
             "role": cell[2]} for seed in (20, 3, 11, 2, 30, 7)]
    a, short_a = cap.select_candidates(rows, {cell}, 3)
    b, short_b = cap.select_candidates(list(reversed(rows)), {cell}, 3)
    assert [r["seed"] for r in a] == [2, 3, 7]
    assert a == b and short_a == short_b == {}


def test_global_merge_reports_exact_cell_shortage():
    cell = ("report", 19, "defender")
    rows = [{"seed": 1, "split": cell[0], "trick": cell[1], "role": cell[2]}]
    _, shortages = cap.select_candidates(rows, {cell}, 4)
    assert shortages == {"report/19/defender": 3}
