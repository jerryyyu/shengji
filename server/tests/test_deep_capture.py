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
    "zero_world_decisions", "impossible_worlds",
])
def test_fatal_sampler_counter_aborts_shard(
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
    with pytest.raises(RuntimeError, match="fatal sampler counters"):
        cap.capture(args)


def test_rejected_world_excludes_whole_deal_but_completes_shard(
        tmp_path, monkeypatch):
    args = _args(tmp_path, max_seeds=1)
    split, trick = cap.cell_targets(args.seed0, args.salt)
    args.only_cell = [f"{split}/{trick}/attacker",
                      f"{split}/{trick}/defender"]
    monkeypatch.setattr(cap, "runtime_contract", _fake_runtime)
    monkeypatch.setattr(cap, "source_digests", lambda: {"test": "1"})
    policy = SimpleNamespace(zero_world_decisions=0, rejected_worlds=2,
                             impossible_worlds=0,
                             reject_cause={"pair_cap": 7})
    outcome = cap.DealOutcome(None, None, {}, [], [policy])
    monkeypatch.setattr(cap, "play_to_trick", lambda *_: outcome)

    assert cap.capture(args) == 0
    spath = cap.shard_path(args.out, 0, 1)
    assert open(spath).read() == ""
    manifest = json.load(open(cap.manifest_path(spath)))
    assert manifest["accepted"] == 0
    assert manifest["sampler_counters"] == {
        "zero_world_decisions": 0, "rejected_worlds": 0,
        "impossible_worlds": 0,
    }
    assert manifest["observed_sampler_counters"]["rejected_worlds"] == 2
    assert manifest["sampler_rejected_deals"] == 1
    assert manifest["reject_reasons"]["strict_sampler_rejected_deal"] == 1
    assert manifest["sampler_reject_causes"] == {"pair_cap": 7}


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


def test_preplay_groups_partition_cells_without_duplicate_deal_work():
    cells = cap.all_cells()
    assignments = [cap.owned_cells(cells, index, 8) for index in range(8)]
    assert set().union(*assignments) == cells
    assert sum(len(group) for group in assignments) == len(cells)
    for left in range(8):
        for right in range(left + 1, 8):
            assert assignments[left].isdisjoint(assignments[right])
    # Role is deliberately paired on one owner because it is unknown pre-play.
    for split, trick in cap.GROUPS:
        owners = {cap.group_owner(split, trick, 8)}
        assert len(owners) == 1
        owner = owners.pop()
        assert (split, trick, "attacker") in assignments[owner]
        assert (split, trick, "defender") in assignments[owner]


def test_merge_refuses_missing_shards_without_occupying_final_name(
        tmp_path, monkeypatch):
    args = _args(tmp_path, mode="merge", shard_count=2,
                 only_cell=["report/17/defender"])
    monkeypatch.setattr(cap, "runtime_contract", _fake_runtime)
    with pytest.raises(RuntimeError, match="missing artifact or manifest"):
        cap.merge(args)
    assert not (tmp_path / "deep.jsonl").exists()
    assert not (tmp_path / "deep.manifest.json").exists()


def test_merge_refuses_source_drift_across_complete_shards(
        tmp_path, monkeypatch):
    args = _args(tmp_path, shard_count=2, only_cell=["report/17/defender"])
    monkeypatch.setattr(cap, "runtime_contract", _fake_runtime)
    monkeypatch.setattr(cap, "source_digests", lambda: {"test": "1"})
    for index in range(2):
        args.shard_index = index
        cap.capture(args)
    second = cap.manifest_path(cap.shard_path(args.out, 1, 2))
    payload = json.load(open(second))
    payload["source_digests"] = {"test": "DIFFERENT"}
    with open(second, "w") as fh:
        json.dump(payload, fh)
    args.mode = "merge"
    with pytest.raises(RuntimeError, match="source/ballot drift"):
        cap.merge(args)
    assert not (tmp_path / "deep.jsonl").exists()


@pytest.mark.parametrize("mutation,needle", [
    (lambda manifest: manifest.update(scan_complete=False), "incomplete scan"),
    (lambda manifest: manifest["sampler_counters"].update(rejected_worlds=1),
     "forbidden accepted sampler fallback"),
    (lambda manifest: manifest["observed_sampler_counters"].update(
        impossible_worlds=1), "fatal observed sampler counter"),
    (lambda manifest: manifest.update(sampler_rejected_deals=1),
     "sampler rejection accounting"),
    (lambda manifest: manifest.update(accepted=1), "record count"),
    (lambda manifest: manifest.update(owned_cells=[]), "cell ownership"),
])
def test_shard_manifest_refusal_paths(mutation, needle, tmp_path, monkeypatch):
    args = _args(tmp_path, shard_count=1, only_cell=["report/17/defender"])
    monkeypatch.setattr(cap, "runtime_contract", _fake_runtime)
    monkeypatch.setattr(cap, "source_digests", lambda: {"test": "1"})
    cap.capture(args)
    spath = cap.shard_path(args.out, 0, 1)
    manifest = json.load(open(cap.manifest_path(spath)))
    mutation(manifest)
    problems = cap.validate_shard(manifest, [], args, 0,
                                  cap.config_for(args, cap.parse_cells(args.only_cell)),
                                  _fake_runtime())
    assert any(needle in problem for problem in problems), problems
