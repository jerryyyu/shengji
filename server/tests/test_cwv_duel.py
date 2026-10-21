"""Witnesses for scripts/cwv_duel.py: calibration, the budget ladder, pairing.

6. Calibration never reads outcomes; W is a function of wall time only, and
   a run refuses a calibration bound to another checkpoint/flags/ranks.
7. The duel's seat mirroring and seed layout equal shengji/evaluation.py's.
8. The three budgets are chosen from wall time only and are monotone in W.
"""
from __future__ import annotations

import copy
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
    # This is an outcome-isolation/binding witness, not a wall benchmark.
    # Still execute the real production and model consumers; only replace
    # their timing observations so shared-runner jitter cannot invert W2/W4.
    real_production, real_measure = duel.measure_production, duel.measure_bot
    measured_worlds = []

    def stable_production(*args, **kwargs):
        result = real_production(*args, **kwargs)
        return {**result, "subset_mean_wall": 0.004}

    def stable_measure(*args, **kwargs):
        result = real_measure(*args, **kwargs)
        assert result["decisions"] > 0
        measured_worlds.append(result["worlds"])
        return {**result, "mean_wall": 0.001 * result["worlds"]}

    monkeypatch.setattr(duel, "measure_production", stable_production)
    monkeypatch.setattr(duel, "measure_bot", stable_measure)
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
    assert {2, 4, 15, 50}.issubset(measured_worlds)
    assert calibration["matched_1x"] is True
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


@pytest.mark.parametrize('round_kind', ['first_round', 'fixed_banker'])
def test_pairs_are_published_as_they_complete_and_resume_never_replays(
        duel, tmp_path, monkeypatch, round_kind):
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
    payload['round_kind'] = round_kind
    if round_kind == 'fixed_banker':
        payload['rank_spec'] = '2,A'
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
    other_kind = 'fixed_banker' if round_kind == 'first_round' else 'first_round'
    with pytest.raises(ValueError, match='retained shard round_kind'):
        duel._worker({**payload, 'round_kind': other_kind})

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

    # reader and sink share ONE boundary: a complete JSON line without its
    # trailing newline is not a record for either, so the pair is replayed
    # rather than read back by one and cut by the other.
    with open(shard, "a") as fh:
        fh.write(json.dumps({"run": "run-y", "label": "arm", "seed": 701, "flip": 1}))
    assert [duel.pair_key(r) for r in duel.read_shard(shard)][-1] == ("arm", 701, 0)
    after_lf = duel.valid_prefix_length(shard)
    duel.ShardSink(shard)
    assert os.path.getsize(shard) == after_lf
    assert [duel.pair_key(r) for r in duel.read_shard(shard)][-1] == ("arm", 701, 0)
    monkeypatch.setattr(duel, "register_cwv_policies", lambda *a, **k: [])
    replayed = []
    monkeypatch.setattr(duel, "play_shard",
                        lambda *a, done=frozenset(), **k: replayed.append(done) or [])
    duel._worker({"checkpoint": None, "worlds": [], "finish_trick": True, "lcb": 0.0,
                  "run_id": "run-y", "plan": [("arm", "smart")], "clusters": [0, 1],
                  "seed0": 700, "rank_spec": None, "opponent": "heuristic",
                  "out": str(tmp_path), "shard": 0})
    assert ("arm", 701, 1) not in replayed[0] and ("arm", 701, 0) in replayed[0]

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


def test_fixed_banker_is_seed_stable_across_mirrors_and_preserves_deck(duel):
    seed = 424_243
    banker = seed % 4
    first = duel.start_round_at(duel.Game(random.Random(seed)), "A", banker)
    mirror = duel.start_round_at(duel.Game(random.Random(seed)), "A", banker)
    assert first.banker == mirror.banker == banker
    assert first.deck == mirror.deck

    logs = [duel.play_pair("smart", "heuristic", seed, flip,
                           trump_rank="A", round_kind="fixed_banker")[0]
            for flip in (0, 1)]
    assert [log.banker for log in logs] == [banker, banker]


def test_fixed_banker_metadata_is_shard_stable_and_legacy_rows_unchanged(duel, tmp_path):
    rows = duel.play_shard("fixed", [("candidate", "smart")], [0, 1], 700,
                           "2,A", "heuristic", round_kind="fixed_banker")
    assert [(row["seed"], row["flip"], row["round_kind"], row["initial_banker"])
            for row in rows] == [
                (700, 0, "fixed_banker", 0), (700, 1, "fixed_banker", 0),
                (701, 0, "fixed_banker", 1), (701, 1, "fixed_banker", 1)]
    path = str(tmp_path / "fixed.jsonl")
    sink = duel.ShardSink(path)
    for row in rows:
        sink(row)
    assert duel.read_shard(path) == rows

    legacy = {"label": "candidate", "seed": 700, "flip": 0}
    legacy_path = str(tmp_path / "legacy.jsonl")
    duel.ShardSink(legacy_path)(legacy)
    assert duel.read_shard(legacy_path) == [legacy]
    with open(legacy_path, "a") as fh:
        fh.write(json.dumps({**legacy, "round_kind": "fixed_banker",
                             "initial_banker": 0}) + "\n")
    with pytest.raises(ValueError, match="round_kind drift"):
        duel.read_shard(legacy_path)


def test_fixed_banker_cli_requires_explicit_rank_before_output(duel, tmp_path):
    adapter = _load_script("pv_dev_duel")
    control = {"SHENGJI_BOT": "unit-control", "recipe": "unit-control"}
    candidate = {"SHENGJI_BOT": "unit-candidate", "recipe": "unit-candidate"}
    out = tmp_path / "not-created"
    with pytest.raises(ValueError, match="explicit"):
        adapter.run(control, candidate, out=out, seed0=100, pairs=2,
                    ranks="canonical", round_kind="fixed_banker")
    assert not out.exists()


def test_fixed_banker_reader_rejects_missing_or_drifted_metadata(tmp_path):
    adapter = _load_script("pv_dev_duel")
    meta = dict(schema="pv-dev-duel-v1", candidate="T", control="C",
                seed0=100, cluster0=0, pairs=2, ranks=["2", "A"],
                round_kind="fixed_banker", initial_banker=adapter.duel.FIXED_BANKER_RULE)
    (tmp_path / "run.json").write_text(json.dumps(meta))
    (tmp_path / "DONE").write_text("2 complete pairs\n")
    rows = [dict(seed=100+i, flip=f, trump_rank=rank, policy="T", opponent="C",
                 label="candidate", winner_team=f, level_change=1, won=1,
                 level_utility=1, round_kind="fixed_banker", initial_banker=(100+i) % 4,
                 arm_play_decisions=1, opp_play_decisions=1,
                 arm_play_health=dict(decisions=1, pv_complete=1),
                 opp_play_health=dict(decisions=1, pv_complete=1))
            for i, rank in enumerate(meta["ranks"]) for f in (0, 1)]
    path = tmp_path / "rounds.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert adapter.read(tmp_path, meta)["pairs"] == 2

    legacy_meta = {key: value for key, value in meta.items()
                   if key not in ("round_kind", "initial_banker")}
    (tmp_path / "run.json").write_text(json.dumps(legacy_meta))
    with pytest.raises(ValueError, match="round_kind metadata drift"):
        adapter.read(tmp_path, legacy_meta)

    (tmp_path / "run.json").write_text(json.dumps(meta))
    missing = list(rows)
    missing[0] = {key: value for key, value in missing[0].items()
                  if key not in ("round_kind", "initial_banker")}
    path.write_text("".join(json.dumps(row) + "\n" for row in missing))
    with pytest.raises(ValueError, match="round_kind metadata drift"):
        adapter.read(tmp_path, meta)

    drift = list(rows)
    drift[0]["initial_banker"] = 3
    path.write_text("".join(json.dumps(row) + "\n" for row in drift))
    with pytest.raises(ValueError, match="initial_banker"):
        adapter.read(tmp_path, meta)


def test_pv_health_reaches_persisted_mixed_rank_mirrors(duel, monkeypatch, tmp_path):
    class Bot:
        def __init__(self, candidate):
            self.candidate = candidate
            self.calls = 0

        def decide_play(self, rnd, seat):
            self.calls += 1
            if not self.candidate:
                self.last_decision_record = None
            elif self.calls == 1:
                self.last_decision_record = {
                    'schema': 'pv-search-decision-v1', 'work_complete': True,
                    'lead_alias_refill_applied': True,
                    'lead_alias_refill_replacements': 2,
                }
            elif self.calls == 2:
                self.last_decision_record = {
                    'schema': 'pv-search-decision-v1', 'work_complete': True,
                    'lead_alias_refill_abandoned': 'soft_budget',
                }
            else:
                self.last_decision_record = {
                    'schema': 'pv-search-fallback-v1', 'work_complete': False,
                    'reason': 'budget' if self.calls == 3 else 'search-error',
                }
            return [seat]

    monkeypatch.setattr(duel, 'make_bot', lambda policy, **kw: Bot(policy == 'candidate'))

    def play(game, policies, rank):
        for _ in range(4):
            for seat, bot in enumerate(policies):
                assert bot.decide_play(None, seat) == [seat]
        return duel.RoundLog(rank, 0, 0, 0, 1)

    monkeypatch.setattr(duel, 'play_round_at', play)
    path = str(tmp_path / 'shard.jsonl')
    rows = duel.play_shard('unit', [('alias', 'candidate')], [0, 1], 10,
                           '2,A', 'control', sink=duel.ShardSink(path))
    assert duel.read_shard(path) == rows
    assert [(r['trump_rank'], r['flip']) for r in rows] == [
        ('2', 0), ('2', 1), ('A', 0), ('A', 1)]
    for row in rows:
        assert row['arm_play_health'] == {
            'decisions': 8, 'pv_complete': 4, 'pv_fallback': 4,
            'pv_budget': 2, 'pv_error': 2,
            'lead_alias_refill_applied': 2, 'lead_alias_refill_replacements': 4,
            'lead_alias_refill_abandoned': 2,
        }
        assert row['opp_play_health'] == {'decisions': 8, 'non_pv_record': 8}
        assert row['arm_play_decisions'] == row['arm_play_health']['decisions']


@pytest.mark.parametrize('expiry', ['soft', 'hard'])
def test_timed_policy_counts_actual_refill_abandonment(duel, monkeypatch, expiry):
    """The persisted health counter accepts the producer's reason string."""
    from shengji.train import lead_alias_refill as lar
    from shengji.train.pv_search_policy import PVSearchBudgetExceeded
    from test_pv_doomed_throw_swap import OTHER_C2_THROW, SEAT, THROW, oxps

    rnd = oxps()
    worlds = [(copy.deepcopy(rnd.hands), list(rnd.buried))]
    monkeypatch.setattr(lar, 'MAX_SECONDS', -1 if expiry == 'soft' else 10)

    def check_budget():
        if expiry == 'hard':
            raise PVSearchBudgetExceeded('injected')

    _, refill_record = lar.refill_indices(
        rnd, SEAT, [THROW, OTHER_C2_THROW], [3., 2.], [0, 1], worlds,
        check_budget)
    assert refill_record['lead_alias_refill_abandoned'] == f'{expiry}_budget'

    class Bot:
        last_decision_record = {
            'schema': 'pv-search-decision-v1', 'work_complete': True,
            **refill_record,
        }

        def decide_play(self, _rnd, _seat):
            return ['C2']

    timer = duel.TimedPolicy(Bot())
    timer.decide_play(None, SEAT)
    assert timer.play_health == {
        'decisions': 1, 'pv_complete': 1,
        'lead_alias_refill_abandoned': 1,
        'lead_alias_refill_applied': 0,
        'lead_alias_refill_replacements': 0,
    }

    # Carry the real producer record through the S52 reader's quality gate:
    # an abandonment is a measured health failure, not a fabricated boolean.
    adapter = _load_script('pv_dev_duel')
    expected = dict(schema='pv-dev-duel-v1', candidate='T', control='C',
                    seed0=100, cluster0=0, pairs=2, ranks=['2'])
    rows = [dict(seed=seed, flip=flip, trump_rank='2', policy='T',
                 opponent='C', label='candidate', winner_team=flip, won=1,
                 level_change=1, level_utility=1, arm_play_decisions=1,
                 opp_play_decisions=1, arm_play_health=dict(timer.play_health),
                 opp_play_health=dict(decisions=1, pv_complete=1))
            for seed in (100, 101) for flip in (0, 1)]
    summary = adapter._summarize(rows, expected)
    assert summary['verdict'] == 'QUALITY_FAIL'
    assert summary['quality_issues'] == ['arm:lead_alias_refill_abandoned=4']


@pytest.mark.parametrize('rank', [None, 'A'])
def test_timed_duel_forwards_every_public_play_to_all_seats(duel, rank):
    observations = [[], [], [], []]
    timers = []
    for seat in range(4):
        bot = _real_make_bot('smart', seed=2718 + seat)
        bot.observe_public = lambda rnd, seat=seat: observations[seat].append(rnd.phase)
        timers.append(duel.TimedPolicy(bot))
    game = duel.Game(random.Random(2718))
    if rank is None:
        duel.play_round(game, timers)
    else:
        duel.play_round_at(game, timers, rank)
    plays = sum(len(t.walls) for t in timers)
    assert plays > 0
    assert [len(seen) for seen in observations] == [plays] * 4
    assert all(seen[-1] == 'round_end' for seen in observations)


@pytest.mark.parametrize('round_kind', ['first_round', 'fixed_banker'])
def test_pv_dev_adapter_registers_then_persists_complete_pairs(monkeypatch, tmp_path,
                                                               round_kind):
    from shengji.ai import registry
    from shengji.train import pv_search_policy as pv

    adapter = _load_script('pv_dev_duel')
    monkeypatch.setattr(registry, 'REGISTRY', dict(registry.REGISTRY))
    constructed = []

    def entries(**recipe):
        def factory(seed):
            constructed.append((recipe['name'], seed))
            return _real_make_bot('smart', seed=seed)
        return {recipe['name']: factory}

    monkeypatch.setattr(pv, 'pv_env_recipe', lambda env: {'name': env['recipe']})
    monkeypatch.setattr(pv, 'pv_registry_entries', entries)
    control = {'SHENGJI_BOT': 'unit-control', 'recipe': 'unit-control'}
    candidate = {'SHENGJI_BOT': 'unit-candidate', 'recipe': 'unit-candidate'}
    out = tmp_path / 'duel'
    control_path = tmp_path / 'control.json'
    candidate_path = tmp_path / 'candidate.json'
    control_path.write_text(json.dumps(control))
    candidate_path.write_text(json.dumps(candidate))
    adapter.main(['--control-env', str(control_path), '--candidate-env', str(candidate_path),
                  '--out', str(out), '--seed0', '100', '--pairs', '2', '--cluster0', '1',
                  '--ranks', '2,A', '--round-kind', round_kind])
    meta = json.loads((out / 'run.json').read_text())
    rows = adapter.duel.read_shard(str(out / 'rounds.jsonl'))
    assert [(r['seed'], r['flip'], r['trump_rank']) for r in rows] == [
        (101, 0, 'A'), (101, 1, 'A'), (102, 0, '2'), (102, 1, '2')]
    assert all(r['policy'] == 'unit-candidate' for r in rows)
    if round_kind == 'fixed_banker':
        assert meta['initial_banker'] == adapter.duel.FIXED_BANKER_RULE
        assert all(r['round_kind'] == round_kind
                   and r['initial_banker'] == r['seed'] % 4 for r in rows)
    else:
        assert 'round_kind' not in meta
        assert all('round_kind' not in r and 'initial_banker' not in r for r in rows)
    assert all(r['arm_play_health']['decisions'] == r['arm_play_decisions'] for r in rows)
    assert constructed[:2] == [('unit-control', 0), ('unit-candidate', 0)]
    assert (out / 'DONE').read_text() == '2 complete pairs\n'
    health = json.loads((out / 'health.json').read_text())
    assert health['rounds'] == 4
    assert health['sides']['arm']['decisions'] == sum(r['arm_play_decisions'] for r in rows)
    assert health['sides']['arm']['max_decision_seconds'] == max(r['arm_play_max_secs'] for r in rows)
    assert adapter.read(out, meta)['verdict'] == 'QUALITY_FAIL'
    prior = (out / 'rounds.jsonl').read_bytes()
    with pytest.raises(FileExistsError):
        adapter.run(control, candidate, out=out, seed0=100, pairs=2, ranks='2,A',
                    round_kind=round_kind)
    assert (out / 'rounds.jsonl').read_bytes() == prior
    with pytest.raises(ValueError, match='derived PV recipe'):
        adapter.register_pair(control, {**candidate, 'SHENGJI_BOT': 'wrong'})
    with pytest.raises(ValueError, match='distinct'):
        adapter.register_pair(control, control)

    def broken(*args, **kw):
        raise RuntimeError('synthetic worker failure')

    monkeypatch.setattr(adapter.duel, 'play_shard', broken)
    with pytest.raises(RuntimeError, match='synthetic worker failure'):
        adapter.run(control, candidate, out=tmp_path / 'failed', seed0=200,
                    pairs=1, ranks='A', round_kind=round_kind)
    assert not (tmp_path / 'failed' / 'DONE').exists()


def test_fixed_banker_shard_assignment_is_stable_and_mirrors_share_deck(duel, monkeypatch):
    seen = []
    real_start = duel.start_round_at

    def traced(game, rank, banker):
        rnd = real_start(game, rank, banker)
        seen.append((list(rnd.deck), rnd.banker))
        return rnd

    monkeypatch.setattr(duel, 'start_round_at', traced)
    seed = 700
    duel.play_pair('smart', 'heuristic', seed, 0, trump_rank='A',
                   round_kind='fixed_banker')
    duel.play_pair('smart', 'heuristic', seed, 1, trump_rank='A',
                   round_kind='fixed_banker')
    assert seen[0] == seen[1] and seen[0][1] == seed % 4

    whole = duel.play_shard('stable', [('candidate', 'smart')], [0, 1], seed,
                            '2,A', 'heuristic', round_kind='fixed_banker')
    suffix = duel.play_shard('stable', [('candidate', 'smart')], [1], seed,
                             '2,A', 'heuristic', round_kind='fixed_banker')
    fields = lambda row: (row['seed'], row['flip'], row['trump_rank'],
                          row['initial_banker'], row['round_kind'])
    assert [fields(row) for row in suffix] == [fields(row) for row in whole
                                                if row['seed'] == seed + 1]


@pytest.mark.parametrize('round_kind', ['first_round', 'fixed_banker'])
def test_pv_dev_shards_match_single_population_and_refuse_bad_partitions(tmp_path, monkeypatch, round_kind):
    adapter = _load_script('pv_dev_duel')
    meta = dict(schema='pv-dev-duel-v1', candidate='T', control='C',
                seed0=100, cluster0=0, pairs=6, ranks=['2', 'A'],
                control_env={'SHENGJI_BOT': 'C'}, candidate_env={'SHENGJI_BOT': 'T'})
    if round_kind == 'fixed_banker':
        meta.update(round_kind=round_kind, initial_banker=adapter.duel.FIXED_BANKER_RULE)
    records = []
    for i in range(6):
        for flip in (0, 1):
            win = i % 3 != 0
            records.append(dict(seed=100+i, flip=flip, trump_rank=meta['ranks'][i % 2],
                policy='T', opponent='C', label='candidate', winner_team=flip if win else 1-flip,
                level_change=1, won=int(win), level_utility=1 if win else -1,
                arm_play_decisions=1, opp_play_decisions=1,
                arm_play_wall_secs=0.1, opp_play_wall_secs=0.1,
                arm_play_max_secs=0.1, opp_play_max_secs=0.1,
                arm_play_health=dict(decisions=1, pv_complete=1),
                opp_play_health=dict(decisions=1, pv_complete=1)))
            if round_kind == 'fixed_banker':
                records[-1].update(round_kind=round_kind, initial_banker=(100+i) % 4)

    monkeypatch.setattr(adapter, 'register_pair', lambda *_: ('C', 'T'))

    def persist(name, plan, rows):
        path = tmp_path / name
        def play(*args, sink, **kwargs):
            for row in rows:
                sink(row)
            return rows
        monkeypatch.setattr(adapter.duel, 'play_shard', play)
        adapter.run(plan['control_env'], plan['candidate_env'], out=path,
                    seed0=plan['seed0'], pairs=plan['pairs'],
                    cluster0=plan['cluster0'], ranks=','.join(plan['ranks']),
                    round_kind=round_kind)
        return path, plan

    whole = persist('whole', meta, records)
    a = persist('a', {**meta, 'pairs': 2}, records[:4])
    b = persist('b', {**meta, 'cluster0': 2, 'pairs': 4}, records[4:])
    assert adapter.read_shards([b, a], meta) == adapter.read(*whole)

    from concurrent.futures import Future

    class InlinePool:
        def __init__(self, *, max_workers, mp_context):
            assert max_workers == 2 and mp_context.get_start_method() == 'spawn'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, function, payload):
            future = Future()
            try:
                future.set_result(function(payload))
            except Exception as exc:
                future.set_exception(exc)
            return future

    def selected_play(_run, _arms, clusters, seed0, *args, sink, **kwargs):
        selected = [r for r in records if r['seed'] - seed0 in clusters]
        for row in selected:
            sink(row)
        return selected

    monkeypatch.setattr(adapter, 'ProcessPoolExecutor', InlinePool)
    monkeypatch.setattr(adapter.duel, 'play_shard', selected_play)
    pool_args = dict(out=tmp_path / 'pool', seed0=100, pairs=6, workers=2,
                     ranks='2,A', round_kind=round_kind)
    parallel = adapter.run_shards(meta['control_env'], meta['candidate_env'], **pool_args)
    assert adapter.read_shards(parallel, meta) == adapter.read(*whole)
    plan = json.loads((pool_args['out'] / 'shards.json').read_text())
    assert [(p['cluster0'], p['pairs']) for p in plan] == [(0, 3), (3, 3)]
    control_file, candidate_file = tmp_path / 'control.json', tmp_path / 'candidate.json'
    control_file.write_text(json.dumps(meta['control_env']))
    candidate_file.write_text(json.dumps(meta['candidate_env']))
    cli_out = tmp_path / 'cli-pool'
    adapter.main(['--control-env', str(control_file), '--candidate-env', str(candidate_file),
                  '--out', str(cli_out), '--seed0', '100', '--pairs', '6', '--workers', '2',
                  '--ranks', '2,A', '--round-kind', round_kind])
    cli_shards = [(cli_out / f'shard-{index:03d}', {**meta, 'cluster0': index * 3, 'pairs': 3})
                  for index in range(2)]
    assert adapter.read_shards(cli_shards, meta) == adapter.read(*whole)
    with pytest.raises(FileExistsError):
        adapter.run_shards(meta['control_env'], meta['candidate_env'], **pool_args)

    def failed_play(*args, **kwargs):
        if 3 in args[2]:
            raise RuntimeError('injected shard failure')
        return selected_play(*args, **kwargs)

    monkeypatch.setattr(adapter.duel, 'play_shard', failed_play)
    failed = {**pool_args, 'out': tmp_path / 'failed-pool'}
    with pytest.raises(RuntimeError, match='injected shard failure'):
        adapter.run_shards(meta['control_env'], meta['candidate_env'], **failed)
    assert not (failed['out'] / 'DONE').exists()
    assert (failed['out'] / 'shard-000' / 'DONE').exists()
    assert (failed['out'] / 'shard-001' / 'run.json').exists()
    assert not (failed['out'] / 'shard-001' / 'DONE').exists()
    for shards in ([a], [b], [a, a, b]):
        with pytest.raises(ValueError):
            adapter.read_shards(shards, meta)
    with pytest.raises(ValueError, match='recipe'):
        adapter.read_shards([a, (b[0], {**b[1], 'candidate': 'other'})], meta)
    (b[0] / 'DONE').unlink()
    with pytest.raises(FileNotFoundError):
        adapter.read_shards([a, b], meta)
    (b[0] / 'DONE').write_text('4 complete pairs\n')
    (b[0] / 'rounds.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records[:8]))
    with pytest.raises(ValueError, match='assigned schedule'):
        adapter.read_shards([a, b], meta)
    records[4]['arm_play_health'] = dict(decisions=1, pv_fallback=1)
    (b[0] / 'rounds.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records[4:]))
    assert adapter.read_shards([a, b], meta)['verdict'] == 'QUALITY_FAIL'


def test_pv_dev_worker_entrypoint_spawns_and_refuses_before_gameplay(tmp_path):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    from scripts.pv_dev_duel import _run_shard

    payload = dict(control={}, candidate={}, out=str(tmp_path / 'absent'),
                   seed0=0, pairs=0, ranks='2')
    with ProcessPoolExecutor(max_workers=1,
                             mp_context=multiprocessing.get_context('spawn')) as pool:
        with pytest.raises(ValueError, match='positive pairs'):
            pool.submit(_run_shard, payload).result(timeout=30)
    assert not (tmp_path / 'absent').exists()


def test_s52_worker_uses_the_fixed_population_and_only_alias_recipe(monkeypatch):
    from scripts import pv_dev_duel
    runner = _load_script('run_s52_dev')
    monkeypatch.setattr(runner, 'TREE', Path(__file__).resolve().parents[2])
    control, candidate = runner.arms()
    assert {k for k in candidate if candidate[k] != control.get(k)} == {
        'SHENGJI_BOT', 'SHENGJI_PV_LEAD_ALIAS_REFILL'}
    assert candidate['SHENGJI_PV_LEAD_ALIAS_REFILL'] == '1'
    assert '-lar-' in candidate['SHENGJI_BOT'] and '-dtrx-' not in candidate['SHENGJI_BOT']
    calls = []
    monkeypatch.setattr(runner, 'verify_extensions', lambda **_: None)
    monkeypatch.setattr(runner, 'arms', lambda: ('control', 'candidate'))
    monkeypatch.setattr(pv_dev_duel, 'run_shards', lambda *a, **kw: calls.append((a, kw)))
    runner.work()
    assert calls == [(('control', 'candidate'), dict(out=runner.OUT,
        seed0=184060910, pairs=624, ranks='2,3,4,5,6,7,8,9,10,J,Q,K,A',
        cluster0=0, round_kind='fixed_banker', workers=14))]
    monkeypatch.setattr(runner, 'arms', lambda: (control, candidate))
    reads = []
    monkeypatch.setattr(pv_dev_duel, 'read_pool',
                        lambda *a, **kw: reads.append((a, kw)))
    runner.read_result()
    (directory, expected), kwargs = reads[0]
    assert directory == runner.OUT and kwargs == {'workers': 14}
    for key in ('seed0', 'pairs', 'cluster0', 'round_kind'):
        assert expected[key] == calls[0][1][key]
    assert expected['ranks'] == calls[0][1]['ranks'].split(',')
    assert expected['control_env'] == control
    assert expected['candidate_env'] == candidate
    assert expected['control'] == control['SHENGJI_BOT']
    assert expected['candidate'] == candidate['SHENGJI_BOT']


def test_s52_launcher_terminal_requires_every_shard(tmp_path):
    import re
    import subprocess
    script = (Path(__file__).resolve().parents[1] / 'scripts' /
              'launch_s52_dev.sh').read_text()
    # The runner opens worker.log exclusively; the supervisor must not create it.
    assert 'CHILD_LOG=$LANE_DIR/runner.log' in script
    functions = '\n'.join(re.search(r'^' + name + r' \(\) \{\n.*?^}',
                                    script, re.M | re.S).group()
                          for name in ('all_shards_done', 'finish'))
    out = tmp_path / 'output'
    out.mkdir()
    (out / 'DONE').write_text('624 complete pairs in 14 shards\n')
    for i in range(14):
        shard = out / f'shard-{i:03d}'
        shard.mkdir()
        (shard / 'DONE').write_text(f'{45 if i < 8 else 44} complete pairs\n')
        (shard / 'health.json').write_text('{}')
    log = tmp_path / 'runner.log'
    log.write_text('{"terminal": "DEV DONE"}\n')

    def finish(rc):
        return subprocess.run(['bash', '-c',
            'say () { echo "$*"; }\n' + functions + f'\nfinish {rc}',
        ], env={**os.environ, 'OUT': str(out), 'CHILD_LOG': str(log),
                'PAIRS': '624', 'WORKERS': '14', 'RUN': 'synthetic'},
            capture_output=True, text=True)

    valid = finish(0)
    assert valid.returncode == 0 and '=== synthetic DONE ===' in valid.stdout
    assert finish(7).returncode == 7
    for path in (out / 'DONE', out / 'shard-013' / 'DONE',
                 out / 'shard-013' / 'health.json', log):
        saved = path.read_text()
        path.write_text('')
        invalid = finish(0)
        assert invalid.returncode == 5 and '=== synthetic DONE ===' not in invalid.stdout
        path.write_text(saved)


@pytest.mark.parametrize('valid_terminal', [True, False])
def test_s52_supervised_terminal_uses_real_child_and_preserves_claim(
        tmp_path, monkeypatch, capsys, valid_terminal):
    import signal
    runner = _load_script('run_s52_dev')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'TREE', Path(__file__).resolve().parents[2])
    monkeypatch.setattr(runner, 'OUT', tmp_path / 'output')
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                'VECLIB_MAXIMUM_THREADS', 'SHENGJI_FAST', 'PYTHONDONTWRITEBYTECODE'):
        monkeypatch.setenv(key, os.environ.get(key, ''))
    monkeypatch.setattr(runner, 'preflight', lambda: None)
    monkeypatch.setattr(runner, 'other_venv_pythons', lambda: [])
    monkeypatch.setattr(runner.os, 'nice', lambda _: None)
    # The child replaces games only; containment, exit checking and reporting are real.
    (tmp_path / 'run_s52_dev.py').write_text('''
import json
from pathlib import Path
def work():
    out = Path('output')
    out.mkdir()
    for i in range(14):
        shard = out / f'shard-{i:03d}'
        shard.mkdir()
        (shard / 'health.json').write_text(json.dumps({'synthetic': True}))
    (out / 'DONE').write_text('624 complete pairs in 14 shards\\n')
''')
    if not valid_terminal:
        child = tmp_path / 'run_s52_dev.py'
        child.write_text(child.read_text().replace('624 complete pairs', '4 complete pairs'))
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    try:
        if valid_terminal:
            runner.main()
            terminal = json.loads(capsys.readouterr().out)
            assert terminal['terminal'] == 'DEV DONE'
            assert terminal['supervision']['returncode'] == 0
            assert terminal['health'] == [{'synthetic': True}] * 14
        else:
            with pytest.raises(SystemExit, match='terminal does not match'):
                runner.main()
            assert capsys.readouterr().out == ''
        assert (tmp_path / 'CLAIM').is_dir()
        assert (tmp_path / 'worker.log').exists()
        with pytest.raises(SystemExit, match='prior output/claim/worker log'):
            runner.main()
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def _synthetic_pv_worker(payload):
    """Exercise real worker persistence without loading models or playing games."""
    from scripts import pv_dev_duel as adapter

    def play(_run, _arms, clusters, seed0, ranks, baseline, *, sink, **kwargs):
        records = []
        for index in clusters:
            for flip in (0, 1):
                row = dict(seed=seed0 + index, flip=flip,
                           trump_rank=adapter.duel.rank_plan(ranks)[index % 2],
                           policy='T', opponent='C', label='candidate', winner_team=flip,
                           level_change=1, won=1, level_utility=1,
                           round_kind='fixed_banker', initial_banker=(seed0 + index) % 4,
                           arm_play_decisions=1, opp_play_decisions=1,
                           arm_play_wall_secs=0.1, opp_play_wall_secs=0.1,
                           arm_play_max_secs=0.1, opp_play_max_secs=0.1,
                           arm_play_health=dict(decisions=1, pv_complete=1),
                           opp_play_health=dict(decisions=1, pv_complete=1))
                sink(row)
                records.append(row)
                if index == payload['candidate'].get('TEST_FAIL_AT'):
                    raise RuntimeError('synthetic child failure after persistence')
        return records

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(adapter, 'register_pair', lambda *_: ('C', 'T'))
        patch.setattr(adapter.duel, 'play_shard', play)
        result = adapter._run_shard(payload)
    (Path(payload['out']) / 'test-worker-pid').write_text(str(os.getpid()))
    return result


def test_pv_dev_real_pool_terminal_and_partial_failure(tmp_path, monkeypatch):
    from concurrent.futures import ProcessPoolExecutor
    from scripts import pv_dev_duel as adapter

    class SyntheticPool(ProcessPoolExecutor):
        def submit(self, function, payload):
            assert function is adapter._run_shard
            return super().submit(_synthetic_pv_worker, payload)

    monkeypatch.setattr(adapter, 'ProcessPoolExecutor', SyntheticPool)
    monkeypatch.setattr(adapter, 'register_pair', lambda *_: ('C', 'T'))
    control, candidate = {'SHENGJI_BOT': 'C'}, {'SHENGJI_BOT': 'T'}
    args = dict(seed0=100, cluster0=4, pairs=7, ranks='2,A', workers=2,
                round_kind='fixed_banker')
    root = tmp_path / 'complete'
    shards = adapter.run_shards(control, candidate, out=root, **args)
    expected = dict(schema='pv-dev-duel-v1', control='C', candidate='T',
                    control_env=control, candidate_env=candidate, seed0=100,
                    cluster0=4, pairs=7, ranks=['2', 'A'], round_kind='fixed_banker',
                    initial_banker=adapter.duel.FIXED_BANKER_RULE)
    assert [(meta['cluster0'], meta['pairs']) for _, meta in shards] == [(4, 4), (8, 3)]
    result = adapter.read_shards(shards, expected)
    assert result['pairs'] == 7 and result['rounds'] == 14
    assert result['verdict'] == 'POSITIVE' and result['quality_issues'] == []
    assert result['mean_levels_per_round'] == 1
    assert result == adapter.read_shards(list(reversed(shards)), expected)
    assert result == adapter.read_pool(root, expected, workers=2)
    with pytest.raises(ValueError, match='pool terminal'):
        adapter.read_pool(root, expected, workers=3)
    with pytest.raises(ValueError, match='invalid pool'):
        adapter.read_pool(root, expected, workers=True)
    # The caller's plan, not the pool's dispatch log, fixes the population.
    (root / 'shards.json').write_text('[]')
    assert result == adapter.read_pool(root, expected, workers=2)
    done = root / 'shard-001' / 'DONE'
    done.rename(done.with_name('saved-DONE'))
    with pytest.raises(FileNotFoundError):
        adapter.read_pool(root, expected, workers=2)
    done.with_name('saved-DONE').rename(done)
    assert (root / 'DONE').read_text() == '7 complete pairs in 2 shards\n'
    for directory, _ in shards:
        assert int((Path(directory) / 'test-worker-pid').read_text()) != os.getpid()
    failed = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='synthetic child failure'):
        adapter.run_shards(control, {**candidate, 'TEST_FAIL_AT': 8}, out=failed, **args)
    assert not (failed / 'DONE').exists()
    with pytest.raises(FileNotFoundError):
        adapter.read_pool(failed, expected, workers=2)
    assert (failed / 'shard-000' / 'DONE').exists()
    assert not (failed / 'shard-001' / 'DONE').exists()
    partial = (failed / 'shard-001' / 'rounds.jsonl').read_text().splitlines()
    assert len(partial) == 1 and json.loads(partial[0])['seed'] == 108


def test_pv_dev_reader_rejects_inconsistent_pairs_before_scoring(tmp_path):
    import copy
    adapter = _load_script('pv_dev_duel')
    meta = dict(schema='pv-dev-duel-v1', candidate='T', control='C',
                seed0=100, cluster0=0, pairs=2, ranks=['2', 'A'])
    (tmp_path / 'run.json').write_text(json.dumps(meta))
    (tmp_path / 'DONE').write_text('2 complete pairs\n')
    rows = [dict(seed=100+i, flip=f, trump_rank=rank, policy='T', opponent='C',
                 label='candidate', winner_team=f, level_change=1, won=1,
                 level_utility=1, arm_play_decisions=1, opp_play_decisions=1,
                 arm_play_health=dict(decisions=1, pv_complete=1),
                 opp_play_health=dict(decisions=1, pv_complete=1))
            for i, rank in enumerate(meta['ranks']) for f in (0, 1)]
    path = tmp_path / 'rounds.jsonl'

    def write(records):
        path.write_text(''.join(json.dumps(r) + '\n' for r in records))

    write(rows)
    result = adapter.read(tmp_path, meta)
    assert result['pairs'] == 2 and result['rounds'] == 4
    assert result['mean_levels_per_round'] == 1
    assert result['by_rank']['A'] == dict(pairs=1, mean=1)
    assert result['by_rank_group']['rank_2']['ci95_normal'] is None
    assert result['by_rank_group']['rank_not_2']['ci95_normal'] is None
    assert result['verdict'] == 'POSITIVE'
    for key in ('seed0', 'cluster0', 'pairs'):
        bad_meta = {**meta, key: float(meta[key])}
        with pytest.raises(ValueError, match='integer'):
            adapter.read(tmp_path, bad_meta)
        (tmp_path / 'run.json').write_text(json.dumps(bad_meta))
        with pytest.raises(ValueError, match='metadata'):
            adapter.read(tmp_path, meta)
        (tmp_path / 'run.json').write_text(json.dumps(meta))
    for change in ({'seed': 999}, {'flip': 1}, {'trump_rank': 'A'},
                   {'seed': 100.0}, {'flip': False}, {'winner_team': False},
                   {'won': True}, {'level_utility': True},
                   {'arm_play_decisions': True},
                   {'opponent': 'T'}, {'policy': 'C'}, {'level_utility': -1},
                   {'winner_team': 1}, {'arm_play_decisions': 2}):
        bad = copy.deepcopy(rows)
        bad[0].update(change)
        write(bad)
        with pytest.raises(ValueError):
            adapter.read(tmp_path, meta)
    write(rows[:-1])
    with pytest.raises(ValueError, match='missing'):
        adapter.read(tmp_path, meta)
    write(rows)
    with pytest.raises(ValueError, match='metadata'):
        adapter.read(tmp_path, {**meta, 'seed0': 101})
    bad = copy.deepcopy(rows)
    bad[0]['arm_play_health'] = dict(decisions=1, pv_fallback=1, pv_budget=1)
    write(bad)
    assert adapter.read(tmp_path, meta)['verdict'] == 'QUALITY_FAIL'
    write(rows)
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match='torn'):
        adapter.read(tmp_path, meta)


@pytest.mark.parametrize('ranks', [['2', 'A', '2', 'K'], ['A', 'K', 'A', 'K']])
def test_pv_dev_rank_groups_cluster_mirrors_and_handle_absent_rank(tmp_path, ranks):
    adapter = _load_script('pv_dev_duel')
    meta = dict(schema='pv-dev-duel-v1', candidate='T', control='C',
                seed0=100, cluster0=0, pairs=4, ranks=ranks)
    (tmp_path / 'run.json').write_text(json.dumps(meta))
    (tmp_path / 'DONE').write_text('4 complete pairs\n')
    rows = []
    for i, rank in enumerate(ranks):
        for flip in (0, 1):
            value = (1, 3, -1, 1)[i]
            winner = flip if value > 0 else 1-flip
            rows.append(dict(seed=100+i, flip=flip, trump_rank=rank,
                             policy='T', opponent='C', label='candidate',
                             winner_team=winner, level_change=abs(value),
                             won=int(value > 0), level_utility=value,
                             arm_play_decisions=1, opp_play_decisions=1,
                             arm_play_health=dict(decisions=1, pv_complete=1),
                             opp_play_health=dict(decisions=1, pv_complete=1)))
    (tmp_path / 'rounds.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    result = adapter.read(tmp_path, meta)
    assert result['mean_levels_per_round'] == 1
    groups = result['by_rank_group']
    if '2' in ranks:
        assert groups['rank_2'] == dict(pairs=2, rounds=4, mean_levels_per_round=0,
                                      ci95_normal=[-1.96, 1.96])
        assert groups['rank_not_2'] == dict(pairs=2, rounds=4, mean_levels_per_round=2,
                                          ci95_normal=pytest.approx([0.04, 3.96]))
    else:
        assert groups['rank_2'] == dict(pairs=0, rounds=0, mean_levels_per_round=None,
                                      ci95_normal=None)
        assert groups['rank_not_2']['pairs'] == 4


def test_full_rank_cycle_balances_fixed_bankers(duel):
    from collections import Counter
    ranks = duel.rank_plan('2,3,4,5,6,7,8,9,10,J,Q,K,A')
    counts = Counter((duel.rank_for(ranks, i), (153060914+i) % 4)
                     for i in range(624))
    assert len(counts) == 52
    assert set(counts.values()) == {12}


def test_pv_capacity_projection_never_reads_outcomes():
    adapter = _load_script('pv_dev_duel')

    class OperationalOnly(dict):
        def __getitem__(self, key):
            assert key.endswith(('_play_health', '_play_decisions',
                                 '_play_wall_secs', '_play_max_secs'))
            return super().__getitem__(key)

    row = OperationalOnly(level_utility=999, winner_team=0, won=1)
    for side in ('arm', 'opp'):
        row.update({f'{side}_play_health': dict(decisions=2, pv_complete=2),
                    f'{side}_play_decisions': 2, f'{side}_play_wall_secs': 0.4,
                    f'{side}_play_max_secs': 0.3})
    summary = adapter.capacity_summary([row], 1.0)
    assert set(summary) == {'schema', 'rounds', 'play_wall_seconds', 'sides'}
    assert summary['sides']['arm'] == dict(health=dict(decisions=2, pv_complete=2),
        decisions=2, decision_seconds=0.4, max_decision_seconds=0.3)
