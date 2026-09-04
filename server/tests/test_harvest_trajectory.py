"""trajectory generator: round-trip, determinism, width invariance,
allocation + exploration, production identity, manifest hashes, bury path.

Reduced work (N=2 selection worlds, R=30 report worlds -- the LCB minimum)
keeps the whole file around half a minute of pure-engine self-play.
"""
import json
import random

import pytest

from shengji.ai.env import play_round
from shengji.ai.registry import make_bot
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.harvest import legal, rebuild, trajectory
from shengji.harvest.common import action_key, sha256_file
from shengji.harvest.schema import SchemaError, finalize_record, validate_record

SEED0 = 4_100_000
ROUNDS = 2
WORK = {"select_worlds": 2, "report_worlds": 30}
EXPLORE = {"explore_rate": 0.5, "explore_k": 2}
PLAIN = {"explore_rate": 0.0, "explore_k": 2}


def _generate(out, *, workers=1, policy=trajectory.DEFAULT_POLICY, **knobs):
    manifest = trajectory.generate(rounds=ROUNDS, seed0=SEED0, out_dir=out,
                                   workers=workers, policy=policy, **WORK, **knobs)
    path = out / "trajectory.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines()]
    return {"out": out, "manifest": manifest, "records": records,
            "bytes": path.read_bytes()}


def _by_round(records):
    rounds = {}
    for r in records:
        _, cluster, mirror, _, _ = r["source_ref"].split(":")
        rounds.setdefault((int(cluster), int(mirror)), []).append(r)
    return rounds


def _plays(records):
    return sorted((r for r in records if r["decision_kind"] == "play"),
                  key=lambda r: r["ply"])


@pytest.fixture(scope="module")
def explore_run(tmp_path_factory):
    return _generate(tmp_path_factory.mktemp("explore"), **EXPLORE)


@pytest.fixture(scope="module")
def plain_run(tmp_path_factory):
    return _generate(tmp_path_factory.mktemp("plain"), **PLAIN)


# 1 ---------------------------------------------------------------- round trip

@pytest.mark.parametrize("run", ["explore_run", "plain_run"])
def test_round_trip_through_rebuild(run, request):
    run = request.getfixturevalue(run)
    records = run["records"]
    counts = run["manifest"]["sources"]["trajectory"]["counts"]
    assert counts["rounds"] == ROUNDS
    assert counts["decisions"] == len(records) > 0
    assert counts["bury_records"] == 0          # the default policy exposes none
    assert counts["short_searches"] == counts["zero_world"] == 0
    for record in records:
        validate_record(record)
        assert record["source"] == "trajectory"
        assert record["policy"] == trajectory.DEFAULT_POLICY
        assert record["decision_kind"] == "play"
        assert record["hidden_hands"] is None and record["authority"] is None
        assert "state_private" not in record
        assert record["deck"] == rebuild.deck_from_seed(
            record["setup"]["trump_rank"], record["setup"]["banker"],
            record["round_seed"])
        rnd = rebuild.state_for_record(record)
        assert rnd.phase == "play" and rnd.turn == record["seat"]
        assert record["ply"] == len(record["plays_prefix"])
        assert record["trick"] == record["ply"] // 4
        assert record["role"] == rebuild.actor_role(rnd, record["seat"])
        assert legal.is_legal(rnd, record["seat"], record["action"])
        keys = {tuple(a) for a in record["legal_actions"]}
        assert action_key(record["action"]) in keys
        for cand in record["ballot"]:
            assert action_key(cand) in keys
            assert legal.is_legal(rnd, record["seat"], cand)
        if record["legal_actions_complete"]:
            assert record["legal_actions_count"] == len(keys)
            assert keys == legal.enumerate_legal(rnd, record["seat"], cap=None).keys()
        else:
            assert record["legal_actions_count"] is None or \
                record["legal_actions_count"] > len(keys) - len(record["ballot"])
        rnd.play(record["seat"], record["action"])          # the engine accepts it
    # the seed-only path rebuilds the same state as the explicit deck
    for record in random.Random(1).sample(records, 8):
        a = rebuild.state_for_record(record)
        b = rebuild.state_for_record({**record, "deck": None})
        assert [sorted(h) for h in a.hands] == [sorted(h) for h in b.hands]
    # whole-round replay: the recorded outcome IS the engine's round result
    for (cluster, mirror), recs in _by_round(records).items():
        recs = _plays(recs)
        assert [r["ply"] for r in recs] == list(range(len(recs)))
        assert {r["round_seed"] for r in recs} == {SEED0 + cluster}
        rnd = rebuild.round_from_setup(recs[0]["deck"], recs[0]["setup"])
        prefix = []
        for r in recs:
            assert r["plays_prefix"] == prefix
            assert rnd.turn == r["seat"]
            prev_last = rnd.last_trick
            rnd.play(r["seat"], r["action"])
            played = actual_play_after(rnd, r["seat"], prev_last)
            assert action_key(played) == action_key(r.get("engine_play", r["action"]))
            prefix.append({"seat": r["seat"], "cards": played})
        assert rnd.phase == "round_end"
        game = Game(random.Random(0))
        game.round, game.banker = rnd, rnd.banker
        result = game.finish_round()
        for r in recs:
            out = r["outcome"]
            assert out["attacker_points"] == result.attacker_points == rnd.attacker_points
            assert out["winner_team"] == result.winner_team
            assert out["level_change"] == result.level_change
            assert out["kitty_bonus"] == result.kitty_points
            assert out["signed_level_utility"] == rebuild.signed_level_utility(
                result.attacker_points, banker_seat=rnd.banker,
                perspective_seat=r["seat"])


# 2 -------------------------------------------------------------- determinism

def test_rerun_is_byte_identical(explore_run, tmp_path):
    again = _generate(tmp_path / "again", **EXPLORE)
    assert again["bytes"] == explore_run["bytes"]
    assert again["manifest"]["outputs"] == explore_run["manifest"]["outputs"]
    assert (again["manifest"]["sources"]["trajectory"]["counts"]
            == explore_run["manifest"]["sources"]["trajectory"]["counts"])


# 3 ---------------------------------------------------------- width invariance

def test_worker_count_does_not_change_bytes(explore_run, tmp_path):
    wide = _generate(tmp_path / "w2", workers=2, **EXPLORE)
    assert wide["bytes"] == explore_run["bytes"]
    assert (wide["manifest"]["outputs"]["trajectory.jsonl"]["sha256"]
            == explore_run["manifest"]["outputs"]["trajectory.jsonl"]["sha256"])
    assert wide["manifest"]["sources"]["trajectory"]["extras"]["knobs"]["workers"] == 2


# 4 ------------------------------------------------------ allocation, exploration

def test_allocation_and_exploration(explore_run):
    records = explore_run["records"]
    counts = explore_run["manifest"]["sources"]["trajectory"]["counts"]
    fired = added_total = searched_with_added = 0
    for r in records:
        alloc = r["allocation"]
        w = alloc["weights"]
        assert alloc["kind"] == trajectory.ALLOCATION_KIND
        assert len(w) == len(r["ballot"]) and all(x >= 0 for x in w)
        assert abs(sum(w) - 1.0) <= 1e-9
        assert len(alloc["selection_worlds"]) == len(alloc["report_worlds"]) == len(w)
        played = alloc["played_index"]
        assert action_key(r["ballot"][played]) == action_key(r["action"])
        # support inside the ballot (aligned lists) and mass = world counts
        worlds = [a + b for a, b in zip(alloc["selection_worlds"], alloc["report_worlds"])]
        if alloc["searched"]:
            assert alloc["total_worlds"] == sum(worlds) > 0
            assert w == [x / sum(worlds) for x in worlds]
            assert min(alloc["selection_worlds"]) == WORK["select_worlds"]
            assert alloc["work"]["complete"] is True
            values = r["action_values"]
            assert values["kind"] == trajectory.ACTION_VALUES_KIND
            assert len(values["means"]) == len(values["paired_se"]) == len(w)
            assert all(m is not None for m in values["means"])
            fold = values["report"]
            if fold is not None and fold["worlds"]:
                finalists = {0, alloc["report_candidate_index"]}
                assert len(finalists) == 2
                assert {i for i, n in enumerate(alloc["report_worlds"]) if n} == finalists
                assert all(alloc["report_worlds"][i] == fold["worlds"] == WORK["report_worlds"]
                           for i in finalists)
            else:
                assert not any(alloc["report_worlds"])
        else:
            assert alloc["reason"] in ("tractor_lock", "single_candidate")
            assert w == [1.0] and r["ballot"] == [r["action"]]
            assert r["action_values"] is None and alloc["total_worlds"] == 0
        ex = r["exploration"]
        legal_keys = {tuple(a) for a in r["legal_actions"]}
        ballot_keys = {action_key(c) for c in r["ballot"]}
        if ex is None:
            assert "production_ballot" not in r
            continue
        fired += 1
        assert ex["rate"] == EXPLORE["explore_rate"]
        assert len(ex["added"]) <= EXPLORE["explore_k"]
        added_total += len(ex["added"])
        prod = r["production_ballot"]
        assert r["ballot"] == prod + ex["added"]      # appended after production's list
        prod_keys = {action_key(c) for c in prod}
        for a in ex["added"]:
            assert action_key(a) in ballot_keys and action_key(a) in legal_keys
            assert action_key(a) not in prod_keys
        if not ex["added"]:
            # nothing was left to add: the listed legal set was already on the ballot
            assert legal_keys <= prod_keys
        elif alloc["searched"]:
            searched_with_added += 1
            for i in range(len(prod), len(r["ballot"])):    # worlds like any other
                assert alloc["selection_worlds"][i] == alloc["selection_worlds"][0] > 0
    assert fired == counts["explore_fired"] > 0
    assert added_total == counts["explore_added"] > 0
    assert searched_with_added > 0


# 5 ------------------------------------------------------------------ identity

def test_explore_rate_zero_is_production(plain_run):
    records = plain_run["records"]
    counts = plain_run["manifest"]["sources"]["trajectory"]["counts"]
    assert counts["explore_fired"] == counts["explore_added"] == 0
    assert all(r["exploration"] is None and "production_ballot" not in r
               for r in records)
    plain = make_bot(trajectory.DEFAULT_POLICY, seed=0)
    for r in records:
        rnd = rebuild.state_for_record(r)
        if r["allocation"]["reason"] == "tractor_lock":
            pick = plain.canonical_lead(rnd, r["seat"])
            dec = decompose(pick, rnd.ordering)
            assert sorted(pick) == sorted(r["action"])
            assert len(dec.components) == 1 and dec.components[0].pair_len >= 2
        else:
            assert [list(c) for c in plain._candidates(rnd, r["seat"])] == r["ballot"]
    # the chosen actions are the plain bots' choices at the same seeds
    for (cluster, mirror), recs in _by_round(records).items():
        recs = _plays(recs)
        seed = SEED0 + cluster
        bots = []
        for s in trajectory.mirror_seat_seeds(seed, mirror):
            bot = make_bot(trajectory.DEFAULT_POLICY, seed=s)
            bot.N_DETERMINIZATIONS = WORK["select_worlds"]
            bot.REPORT_FOLD_WORLDS = WORK["report_worlds"]
            bots.append(bot)
        log = play_round(Game(random.Random(seed)), bots, record=True)
        assert [(s, sorted(c)) for s, c in log.history] == [
            (r["seat"], sorted(r.get("engine_play", r["action"]))) for r in recs]
        assert log.attacker_points == recs[0]["outcome"]["attacker_points"]
        assert log.winner_team == recs[0]["outcome"]["winner_team"]
        assert log.level_change == recs[0]["outcome"]["level_change"]


# 6 ------------------------------------------------------------------ manifest

def test_manifest_hashes_match_outputs(explore_run):
    out = explore_run["out"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest == explore_run["manifest"]
    sidecar = json.loads((out / "trajectory.manifest.json").read_text())
    assert set(manifest["outputs"]) == {"trajectory.jsonl"}
    for name, info in manifest["outputs"].items():
        path = out / name
        assert info["sha256"] == sha256_file(path) == sidecar["outputs"][name]["sha256"]
        assert info["bytes"] == path.stat().st_size
        assert info["private"] is False
    src = manifest["sources"]["trajectory"]
    assert src["counts"]["records"] == len(explore_run["records"]) \
        == sidecar["outputs"]["trajectory.jsonl"]["records"]
    assert manifest["totals"]["decisions"] == src["counts"]["decisions"]
    assert manifest["totals"]["rounds"] == ROUNDS
    assert len(manifest["git_head"]) == 40
    ex = src["extras"]
    assert ex["identity"]["git_sha"] == manifest["git_head"]
    assert ex["policy"]["name"] == "mc-s0-report-lcb"
    assert ex["policy"]["class"] == "MCS0ReportLCB"
    assert ex["work"]["registered"] == {"n_determinizations": 30,
                                        "report_fold_worlds": 300,
                                        "report_rule": "lcb"}
    assert ex["work"]["effective"] == {"n_determinizations": 2,
                                       "report_fold_worlds": 30,
                                       "report_rule": "lcb"}
    assert ex["work"]["production"] is False
    assert ex["work"]["realized"]["rollouts"] == src["counts"]["rollouts"] > 0
    assert ex["knobs"] == {"seed0": SEED0, "rounds": ROUNDS, "clusters": 1,
                           "workers": 1, "explore_rate": 0.5, "explore_k": 2,
                           "cap": 256}
    assert src["legal_actions_cap"] == 256
    assert all(r["source_ref"].startswith(ex["run_id"] + ":")
               for r in explore_run["records"])
    assert ex["run_id"] == trajectory.build_config(
        seed0=SEED0, **WORK, **EXPLORE)["run_id"]


# 7 ------------------------------------------------------------ bury records

def test_bury_records_when_the_bury_path_exposes_a_record(tmp_path):
    run = _generate(tmp_path / "bury", policy="mc-s0-report-lcb-structured-bury",
                    **PLAIN)
    counts = run["manifest"]["sources"]["trajectory"]["counts"]
    buries = [r for r in run["records"] if r["decision_kind"] == "bury"]
    assert len(buries) == counts["bury_records"] == ROUNDS
    assert counts["decisions"] == len(run["records"]) - len(buries)
    for r in buries:
        validate_record(r)
        assert r["policy"] == "mc-s0-report-lcb-structured-bury"
        assert r["source_ref"].endswith(f":{r['seat']}:bury")
        assert r["seat"] == r["setup"]["banker"] and r["role"] == "banker-team"
        assert r["ply"] is None and r["plays_prefix"] == []
        assert r["legal_actions"] is None and r["legal_actions_count"] > 1
        assert sorted(r["action"]) == r["setup"]["buried"]
        assert any(action_key(c) == action_key(r["action"]) for c in r["ballot"])
        w = r["allocation"]["weights"]
        assert len(w) == len(r["ballot"]) == len(r["action_values"]["means"])
        assert abs(sum(w) - 1.0) <= 1e-9
        rnd = rebuild.state_for_record(r)
        assert rnd.phase == "bury" and rnd.turn == r["seat"]
        rnd.bury(r["seat"], r["action"])
        assert rnd.phase == "play"
    # a bury record precedes its seat's plays in the merged order
    for (_, _), recs in _by_round(run["records"]).items():
        kinds = [(r["seat"], r["decision_kind"]) for r in recs]
        bury_at = kinds.index((recs[0]["setup"]["banker"], "bury"))
        assert all(k != (recs[0]["setup"]["banker"], "play") for k in kinds[:bury_at])


# ------------------------------------------------------------ fail closed

def test_refuses_unsupported_configurations(tmp_path):
    with pytest.raises(trajectory.TrajectoryError):
        trajectory.build_config(seed0=1, select_worlds=2, report_worlds=10)  # LCB < 30
    with pytest.raises(trajectory.TrajectoryError):
        trajectory.build_config(seed0=1, policy="smart")             # no ballot
    with pytest.raises(trajectory.TrajectoryError):
        trajectory.build_config(seed0=1, explore_rate=1.5)
    config = trajectory.build_config(seed0=1, **WORK)
    with pytest.raises(trajectory.TrajectoryError):
        trajectory.run_rounds(config, rounds=3, seed0=1)              # odd
    with pytest.raises(trajectory.TrajectoryError):
        trajectory.run_rounds(config, rounds=2, seed0=1, workers=0)


def test_schema_exploration_field():
    base = {
        "source": "trajectory", "source_ref": "r:0:0:1:1", "policy": "p",
        "round_seed": 7, "deck": None,
        "setup": {"trump_rank": "2", "banker": 0, "declarations": [],
                  "declaration": None, "trump_suit": "S", "trump_is_nt": False,
                  "buried": None},
        "plays_prefix": [{"seat": 0, "cards": ["SA"]}], "seat": 1, "ply": 1,
        "trick": 0, "role": "attacker-team",
        "legal_actions": [["S3"], ["S4"]], "legal_actions_complete": True,
        "legal_actions_count": 2, "ballot": [["S3"], ["S4"]],
        "allocation": None, "action_values": None, "action": ["S4"],
        "outcome": None, "hidden_hands": None,
    }
    ok = finalize_record({**base, "exploration": {"rate": 0.1, "added": [["S4"]]}})
    assert ok["exploration"] == {"rate": 0.1, "added": [["S4"]]}
    assert finalize_record({**base, "exploration": None})["exploration"] is None
    assert "exploration" not in finalize_record(base)
    for bad in ({"rate": 1.5, "added": []}, {"rate": 0.1},
                {"rate": 0.1, "added": [["S9"]]}, {"rate": 0.1, "added": "S4"}):
        with pytest.raises(SchemaError):
            finalize_record({**base, "exploration": bad})
