"""Witnesses for scripts/cwv_duel.py: calibration, the budget ladder, pairing.

6. Calibration never reads outcomes; W is a function of wall time only, and
   a run refuses a calibration bound to another checkpoint/flags/ranks.
7. The duel's seat mirroring and seed layout equal shengji/evaluation.py's.
8. The three budgets are chosen from wall time only and are monotone in W.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
from pathlib import Path

import pytest

from shengji import evaluation
from shengji.ai.registry import REGISTRY


def _load_script(name: str):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def duel():
    return _load_script("cwv_duel")


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("cwv-duel") / "tiny.pt"
    _load_script("cwv_dev_checkpoint").build_dev_checkpoint(
        str(out), rounds=2, max_epochs=2, quiet=True)
    return str(out)


def _grid(walls, decoys):
    return [{"worlds": w, "mean_wall": t, "utility": u, "win_rate": u}
            for (w, t), u in zip(walls, decoys)]


# ------------------------------------------------- 6/8. wall-only ladder

def test_budget_ladder_is_a_function_of_wall_time_only_and_monotone(duel):
    grid = _grid([(30, 0.03), (100, 0.09), (300, 0.27), (1000, 0.9)],
                 decoys=[0.9, 0.1, 0.5, 0.2])        # decoys prefer W=30
    chosen = duel.choose_budget_ladder(0.15, grid, ["1x", "3x", "10x"])
    worlds = [rung["worlds"] for rung in chosen["ladder"]]
    fit = duel.fit_line([(r["worlds"], r["mean_wall"]) for r in grid])
    assert fit["r2"] > 0.999
    expected = [max(1, round((m * 0.15 - fit["a"]) / fit["b"])) for m in (1, 3, 10)]
    assert worlds == expected == [165, 499, 1668], worlds
    assert worlds == sorted(set(worlds)), "rungs are strictly increasing in W"
    ratios = [rung["predicted_ratio"] for rung in chosen["ladder"]]
    assert ratios[0] == pytest.approx(1.0, abs=0.01)
    assert ratios[1] == pytest.approx(3.0, abs=0.01)
    assert ratios[2] == pytest.approx(10.0, abs=0.01)

    # the decoys are invisible: permuting or removing them changes nothing
    shuffled = _grid([(30, 0.03), (100, 0.09), (300, 0.27), (1000, 0.9)],
                     decoys=[0.1, 0.9, 0.2, 0.5])
    assert [r["worlds"] for r in duel.choose_budget_ladder(
        0.15, shuffled, ["1x", "3x", "10x"])["ladder"]] == worlds
    bare = [{"worlds": r["worlds"], "mean_wall": r["mean_wall"]} for r in grid]
    assert [r["worlds"] for r in duel.choose_budget_ladder(
        0.15, bare, ["1x", "3x", "10x"])["ladder"]] == worlds

    # RED when chosen on utility: a mutant chooser that maximises the decoy
    # picks W=30 for every rung -- neither matched nor monotone.
    def on_utility(production_wall, rows, multipliers):
        best = max(rows, key=lambda row: row["utility"])
        return {"ladder": [{"budget": m, "worlds": best["worlds"]} for m in multipliers]}
    mutant = [r["worlds"] for r in on_utility(0.15, grid, ["1x", "3x", "10x"])["ladder"]]
    assert mutant != worlds and mutant != sorted(set(mutant))

    # colliding targets are forced apart, never equal
    tight = duel.choose_budget_ladder(0.15, grid, ["1x", "1.001x", "1.002x"])
    assert [r["worlds"] for r in tight["ladder"]] == [165, 166, 167]
    # a measured 1x anchor pins its rung and the others stay monotone
    anchored = duel.choose_budget_ladder(0.15, grid, ["1x", "3x", "10x"],
                                         anchors={1.0: 172})
    assert [r["worlds"] for r in anchored["ladder"]] == [172, 499, 1668]
    assert [r["anchored"] for r in anchored["ladder"]] == [True, False, False]
    assert duel.matched_measurement(grid, 0.15) is None
    assert duel.matched_measurement(grid + [{"worlds": 160, "mean_wall": 0.146}], 0.15)["worlds"] == 160
    assert duel.local_worlds_for_wall(grid, 0.15) == 167     # between 100 and 300
    assert duel.local_worlds_for_wall(grid, 2.0) > 1000       # beyond the grid: the fit
    with pytest.raises(ValueError):
        duel.choose_budget_ladder(0.15, _grid([(30, 0.9), (100, 0.1)], [0, 0]), ["1x"])


def test_production_scaled_reference_arms_scale_selection_and_report_doses(duel):
    """The bar is production's own compute curve: N and R scale together."""
    from shengji.ai.registry import register_scaled_policies, scaled_policy_name
    from shengji.engine.ballot import ballot_for_policy

    base = _real_make_bot("mc-s0-report-lcb", seed=1)
    for multiplier, name in ((3, "mc-s0-report-lcb-x3"), (10, "mc-s0-report-lcb-x10")):
        assert scaled_policy_name("mc-s0-report-lcb", multiplier) == name
        bot = _real_make_bot(name, seed=1)
        assert bot.N_DETERMINIZATIONS == base.N_DETERMINIZATIONS * multiplier
        assert bot.REPORT_FOLD_WORLDS == base.REPORT_FOLD_WORLDS * multiplier
        assert bot.REPORT_RULE == base.REPORT_RULE and bot.REQUIRE_EXACT_WORK
        assert bot.dose_multiplier == multiplier and bot.policy_name == name
        assert ballot_for_policy(name).digest == ballot_for_policy("mc-s0-report-lcb").digest
    names = register_scaled_policies("mc-lite", [2.5])
    try:
        assert names == ["mc-lite-x2.5"]
        lite = _real_make_bot("mc-lite-x2.5", seed=2)
        assert lite.N_DETERMINIZATIONS == round(5 * 2.5) and lite.REPORT_FOLD_WORLDS == 0
    finally:
        REGISTRY.pop("mc-lite-x2.5", None)


class _Poisoned:
    """A round log whose OUTCOME fields raise: reading one is the mutation."""

    def __init__(self, log):
        self.trump_rank = log.trump_rank
        self.banker = log.banker

    @property
    def winner_team(self):
        raise AssertionError("calibration read an outcome (winner_team)")

    @property
    def attacker_points(self):
        raise AssertionError("calibration read an outcome (attacker_points)")

    @property
    def level_change(self):
        raise AssertionError("calibration read an outcome (level_change)")


def test_calibration_is_outcome_blind_and_runs_refuse_a_foreign_binding(
        duel, checkpoint, tmp_path, monkeypatch):
    real_play_round = duel.play_round
    monkeypatch.setattr(duel, "play_round",
                        lambda game, policies: _Poisoned(real_play_round(game, policies)))
    args = duel.build_parser().parse_args([
        "calibrate", "--checkpoint", checkpoint, "--out", str(tmp_path / "cal.json"),
        "--base-policy", "mc-lite", "--deals", "1", "--grid", "2,4",
        "--subset-stride", "6", "--max-iterations", "1", "--budgets", "1x,3x,10x"])
    try:
        calibration = duel.calibrate(args)
    finally:
        for name in list(REGISTRY):
            if name.startswith("mc-cwv-"):
                REGISTRY.pop(name)
    assert calibration["outcome_blind"] is True
    assert calibration["production"]["decisions"] > 0
    ladder = calibration["ladder"]
    assert [r["budget"] for r in ladder] == ["1x", "3x", "10x"]
    assert [r["worlds"] for r in ladder] == sorted({r["worlds"] for r in ladder})
    assert all(r["predicted_ratio"] > 0 for r in ladder)
    assert calibration["binding"]["checkpoint_sha256"] == calibration["checkpoint"]["sha256"]
    assert calibration["identity_sha256"] == duel.calibration_identity(calibration["binding"])
    production_ladder = calibration["production_ladder"]
    assert [r["budget"] for r in production_ladder] == ["3x", "10x"]
    assert [r["policy"] for r in production_ladder] == ["mc-lite-x3", "mc-lite-x10"]
    assert [r["n_determinizations"] for r in production_ladder] == [15, 50]
    assert all(r["measured_ratio"] > 0 for r in production_ladder)
    # and the mutation really is observable: a reader of the outcome raises
    with pytest.raises(AssertionError, match="read an outcome"):
        _ = _Poisoned(real_play_round(
            duel.Game(random.Random(1)),
            [duel.make_bot("smart", seed=s) for s in range(4)])).winner_team

    binding = calibration["binding"]
    live = dict(checkpoint_sha256=binding["checkpoint_sha256"], finish_trick=True,
                lcb=0.0, base_policy="mc-lite", trump_ranks="canonical",
                budgets=[1.0, 3.0, 10.0])
    rungs = duel.check_calibration(calibration, **live)
    assert [r["worlds"] for r in rungs] == [r["worlds"] for r in ladder]
    for change in (dict(checkpoint_sha256="0" * 64), dict(finish_trick=False),
                   dict(lcb=1.0), dict(base_policy="mc-s0-report-lcb"),
                   dict(trump_ranks="2"), dict(budgets=[1.0, 30.0])):
        with pytest.raises(duel.CalibrationMismatch):
            duel.check_calibration(calibration, **{**live, **change})
    tampered = json.loads(json.dumps(calibration))
    tampered["binding"]["finish_trick"] = False
    with pytest.raises(duel.CalibrationMismatch, match="tampered"):
        duel.check_calibration(tampered, **{**live, "finish_trick": False})
    with open(tmp_path / "cal.json") as fh:
        assert json.load(fh)["identity_sha256"] == calibration["identity_sha256"]


# ------------------------------------------------------------- 7. pairing

def _trace(monkeypatch, module, made, played):
    """Record every (policy, seed) construction and every dealt round."""
    def fake_make_bot(name, **kw):
        made.append((name, kw.get("seed")))
        return _real_make_bot(name, **kw)

    def fake_play_round(game, policies):
        inner = [getattr(p, "inner", p) for p in policies]
        played.append((game.rng.random(), [getattr(b, "policy_name", None) for b in inner],
                       [getattr(b, "seed", None) for b in inner]))
        return real_play_round(game, inner)
    monkeypatch.setattr(module, "make_bot", fake_make_bot)
    monkeypatch.setattr(module, "play_round", fake_play_round)


from shengji.ai.registry import make_bot as _real_make_bot  # noqa: E402
from shengji.ai.env import play_round as real_play_round  # noqa: E402


def test_pairs_are_published_as_they_complete_and_resume_never_replays(
        duel, tmp_path, monkeypatch):
    """Fault injection: the process dies after two pairs; the two are on disk,
    a rerun under the same run id reads them back and plays only the rest."""
    calls = []
    real_play_pair = duel.play_pair

    def dying_play_pair(policy, opponent, seed, flip, **kw):
        calls.append((policy, seed, flip))
        if len(calls) == 3:
            raise RuntimeError("simulated crash after two completed pairs")
        return real_play_pair(policy, opponent, seed, flip, **kw)
    monkeypatch.setattr(duel, "play_pair", dying_play_pair)
    payload = {"checkpoint": None, "worlds": [], "finish_trick": True, "lcb": 0.0,
               "run_id": "run-x", "plan": [("arm", "smart")], "clusters": [0, 1],
               "seed0": 700, "rank_spec": None, "opponent": "heuristic",
               "out": str(tmp_path), "shard": 0}
    monkeypatch.setattr(duel, "register_cwv_policies", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="simulated crash"):
        duel._worker(payload)
    shard = duel.shard_path(str(tmp_path), "run-x", 0)
    on_disk = duel.read_shard(shard)
    assert [duel.pair_key(r) for r in on_disk] == [("arm", 700, 0), ("arm", 700, 1)]

    # a torn tail (crash mid-write) is ignored, not a fatal parse error
    with open(shard, "a") as fh:
        fh.write('{"label": "arm", "seed": 701, "fl')
    assert len(duel.read_shard(shard)) == 2

    calls.clear()
    outcome = duel._worker(payload)                 # resume: same run id
    assert [duel.pair_key(r) for r in outcome["retained"]] == [("arm", 700, 0), ("arm", 700, 1)]
    assert [(s, f) for _, s, f in calls] == [(701, 0), (701, 1)], "earlier pairs not replayed"
    assert [duel.pair_key(r) for r in outcome["records"]] == [("arm", 701, 0), ("arm", 701, 1)]
    merged = duel.read_shard(shard)
    assert len(merged) == 4 and len({duel.pair_key(r) for r in merged}) == 4

    # RED when the sink is dropped: nothing survives the crash
    calls.clear()
    os.remove(shard)
    monkeypatch.setattr(duel, "ShardSink", lambda path: (lambda record: None))
    with pytest.raises(RuntimeError):
        duel._worker(payload)
    assert duel.read_shard(shard) == []


def test_repair_of_a_torn_shard_never_touches_the_published_prefix(
        duel, tmp_path, monkeypatch):
    """Codex P1: a failure DURING a resume's repair must not destroy retained
    rows, and an intact shard must never be opened for writing."""
    shard = str(tmp_path / "run-y.shard0.jsonl")
    rows = [{"run": "run-y", "label": "arm", "seed": 700, "flip": f, "won": f}
            for f in (0, 1)]
    with open(shard, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    intact = open(shard, "rb").read()

    # an intact file: construction opens nothing for writing
    real_open = open
    writes = []

    def spying_open(path, mode="r", *a, **k):
        if str(path) == shard and any(c in mode for c in "wa+"):
            writes.append(mode)
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", spying_open)
    duel.ShardSink(shard)
    assert writes == [] and open(shard, "rb").read() == intact

    # a torn tail, and the repair is interrupted (truncate fails): the
    # published prefix survives byte for byte and the next resume reads it
    with open(shard, "a") as fh:
        fh.write('{"run": "run-y", "label": "arm", "seed": 701, "fl')
    torn = open(shard, "rb").read()
    assert duel.valid_prefix_length(shard) == len(intact)

    def failing_truncate(path, length):
        raise OSError("simulated failure during repair")
    monkeypatch.setattr(duel.os, "truncate", failing_truncate)
    with pytest.raises(OSError, match="during repair"):
        duel.ShardSink(shard)
    assert open(shard, "rb").read() == torn, "nothing was rewritten"
    assert [duel.pair_key(r) for r in duel.read_shard(shard)] == [
        ("arm", 700, 0), ("arm", 700, 1)]
    monkeypatch.undo()

    # the successful repair cuts exactly the invalid tail and appends after it
    sink = duel.ShardSink(shard)
    assert open(shard, "rb").read() == intact
    sink({"run": "run-y", "label": "arm", "seed": 701, "flip": 0})
    assert [duel.pair_key(r) for r in duel.read_shard(shard)] == [
        ("arm", 700, 0), ("arm", 700, 1), ("arm", 701, 0)]

    # RED under the old open-with-"w" repair: a failure at the first
    # json.dumps leaves zero records
    def failing_dumps(record):
        raise RuntimeError("serialization failure at the first json.dumps")

    def old_repair(path):
        complete = duel.read_shard(path)
        with open(path, "w") as fh:                  # the P1: opened with "w"
            for record in complete:
                fh.write(failing_dumps(record) + "\n")
    with open(shard, "a") as fh:
        fh.write('{"torn": ')
    with pytest.raises(RuntimeError):
        old_repair(shard)
    assert duel.read_shard(shard) == []


def test_duel_pairing_equals_evaluation_run_arm(duel, tmp_path, monkeypatch):
    made_ref, played_ref = [], []
    _trace(monkeypatch, evaluation, made_ref, played_ref)
    with open(tmp_path / "ref.jsonl", "w") as fh:
        ref_records = evaluation.run_arm("arm", "smart", "heuristic", 2, 900, fh, "t",
                                         progress=False)

    made, played = [], []
    _trace(monkeypatch, duel, made, played)
    records = duel.play_shard("t", [("arm", "smart")], [0, 1], 900, None, "heuristic")

    assert made == made_ref, "seat/seed layout differs from evaluation.run_arm"
    assert played == played_ref, "deal or seat mirror differs from evaluation.run_arm"
    assert [(r["seed"], r["flip"], r["won"], r["level_utility"]) for r in records] == \
        [(r["seed"], r["flip"], r["won"], r["level_utility"]) for r in ref_records]
    assert {r["arm_role"] for r in records} <= {"attacker", "defender"}

    # RED when the mirror is dropped: a mutant that seats flip 1 like flip 0
    # produces a different seat order for the second round of every seed.
    def unmirrored(policy, opponent, seed, flip):
        a1 = _real_make_bot(policy, seed=seed)
        a2 = _real_make_bot(policy, seed=seed + 500_000)
        b1 = _real_make_bot(opponent, seed=seed + 1_000_000)
        b2 = _real_make_bot(opponent, seed=seed + 1_500_000)
        return [a1, b1, a2, b2], (a1, a2), (b1, b2)
    monkeypatch.setattr(duel, "paired_bots", unmirrored)
    made_mut, played_mut = [], []
    _trace(monkeypatch, duel, made_mut, played_mut)
    duel.play_shard("t", [("arm", "smart")], [0, 1], 900, None, "heuristic")
    assert played_mut != played_ref


def test_explicit_rank_2_deals_are_the_canonical_deals(duel):
    seed = 424_242
    policies = [_real_make_bot("smart", seed=seed + off) for off in duel.SEAT_OFFSETS]
    canonical = real_play_round(duel.Game(random.Random(seed)), policies)
    policies = [_real_make_bot("smart", seed=seed + off) for off in duel.SEAT_OFFSETS]
    explicit = duel.play_round_at(duel.Game(random.Random(seed)), policies, "2")
    assert (canonical.trump_rank, canonical.banker, canonical.attacker_points,
            canonical.winner_team, canonical.level_change) == (
        explicit.trump_rank, explicit.banker, explicit.attacker_points,
        explicit.winner_team, explicit.level_change)
    assert duel.rank_plan("canonical") is None and duel.rank_plan("2") == ["2"]
    assert duel.rank_plan("cycle") == list(duel.RANKS)
    assert duel.rank_for(duel.rank_plan("cycle"), 14) == duel.RANKS[1]
    with pytest.raises(ValueError):
        duel.rank_plan("1")
    assert duel.parse_budgets("1x,3x,10x") == [1.0, 3.0, 10.0]
    with pytest.raises(ValueError):
        duel.parse_budgets("3x,1x")
    assert duel.shards(5, 2) == [[0, 2, 4], [1, 3]]
