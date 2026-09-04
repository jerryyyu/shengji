"""trajectory generator: round-trip, determinism, width invariance,
allocation vs preference, exploration over the full legal set, production
identity, shard manifest, resume witnesses, bury path, class-knob overrides
(``--knob``) and ballot widening (``--widen``).

Reduced work (N=2 selection worlds, R=30 report worlds -- the LCB minimum)
keeps the whole file around a minute and a half of pure-engine self-play.
"""
import gc
import hashlib
import json
import math
import os
import random
import shutil

import pytest

from shengji.ai.env import play_round
from shengji.ai.registry import make_bot
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.harvest import ballot_capture, legal, rebuild, trajectory
from shengji.harvest.common import action_key, sha256_file
from shengji.harvest.schema import SchemaError, finalize_record, validate_record

SEED0 = 4_100_000
ROUNDS = 2
WORK = {"select_worlds": 2, "report_worlds": 30}
EXPLORE = {"explore_rate": 0.5, "explore_k": 2}
PLAIN = {"explore_rate": 0.0, "explore_k": 2}
#: ``--knob`` overrides of the knobs fixture and their coerced values
KNOBS = ["V3_LEAD_SINGLES=1", "LEAD_MAX_CANDIDATES=64"]
KNOB_VALUES = {"LEAD_MAX_CANDIDATES": 64, "V3_LEAD_SINGLES": True}
#: the Run B data-policy overrides (issue #205 follow-up)
RUN_B_KNOBS = {"V3_LEAD_SINGLES": True, "LEAD_MAX_CANDIDATES": 64,
               "FOLLOW_MAX_CANDIDATES": 64, "TRACTOR_LOCK": False,
               "RETAIN_ALL_LEAD_PAIRS": True}
WIDEN = ["union"]
#: run_id of the PLAIN configuration as generated BEFORE --knob/--widen
#: existed (c82eac20): the neutral witness -- a run without either option
#: must keep the identity its stores already carry
PLAIN_RUN_ID = "traj-s4100000-b8fbc705e8e1"


def _read_dir(out):
    manifest = json.loads((out / "manifest.json").read_text())
    shards = {s["cluster"]: (out / s["path"]).read_bytes() for s in manifest["shards"]}
    merged_path = out / "trajectory.jsonl"
    merged = (merged_path.read_bytes() if merged_path.exists()
              else b"".join(shards[c] for c in sorted(shards)))
    records = [json.loads(line) for line in merged.decode("ascii").splitlines()]
    return {"out": out, "manifest": manifest, "records": records, "bytes": merged,
            "shards": shards, "manifest_bytes": (out / "manifest.json").read_bytes(),
            "sidecars": {s["cluster"]: (out / s["sidecar"]).read_bytes()
                         for s in manifest["shards"]}}


def _generate(out, *, workers=1, policy=trajectory.DEFAULT_POLICY, rounds=ROUNDS,
              seed0=SEED0, merge=True, resume=False, **options):
    trajectory.generate(rounds=rounds, seed0=seed0, out_dir=out, workers=workers,
                        policy=policy, merge=merge, resume=resume, **WORK, **options)
    return _read_dir(out)


def _by_round(records):
    rounds = {}
    for r in records:
        _, cluster, mirror, _, _ = r["source_ref"].split(":")
        rounds.setdefault((int(cluster), int(mirror)), []).append(r)
    return rounds


def _plays(records):
    return sorted((r for r in records if r["decision_kind"] == "play"),
                  key=lambda r: r["ply"])


def _softmax(means, tau):
    top = max(means)
    w = [math.exp((m - top) / tau) for m in means]
    return [x / sum(w) for x in w]


def _median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


@pytest.fixture(scope="module")
def explore_run(tmp_path_factory):
    return _generate(tmp_path_factory.mktemp("explore") / "run", **EXPLORE)


@pytest.fixture(scope="module")
def plain_run(tmp_path_factory):
    return _generate(tmp_path_factory.mktemp("plain") / "run", **PLAIN)


@pytest.fixture(scope="module")
def clean4(tmp_path_factory):
    """An uninterrupted 4-round (2-cluster) plain run: the reference for the
    resume witnesses."""
    return _generate(tmp_path_factory.mktemp("clean4") / "run", rounds=4, **PLAIN)


#: the retention / timing fixture: 6 clusters on the cheapest MCBot policy
#: (plain ``mc``, one selection world, no report fold: ~0.6 s per cluster)
RETENTION = dict(rounds=12, seed0=4_200_000, policy="mc", select_worlds=1,
                 explore_rate=0.0, explore_k=0)


@pytest.fixture(scope="module")
def retention_run(tmp_path_factory):
    """A 6-cluster run on 2 workers, sampling the parent's live cluster
    results at every publish, plus the same run on 1 worker."""
    live = []

    def progress(event):
        gc.collect()             # only strong references count
        live.append((event["cluster"], len(trajectory.LIVE_RESULTS)))

    out = tmp_path_factory.mktemp("retention") / "w2"
    manifest = trajectory.generate(out_dir=out, workers=2, merge=False,
                                   progress=progress, **RETENTION)
    single = tmp_path_factory.mktemp("retention") / "w1"
    trajectory.generate(out_dir=single, workers=1, merge=False, **RETENTION)
    return {"out": out, "manifest": manifest, "live": live,
            "runtime": json.loads((out / "runtime.json").read_text()),
            "w2": _read_dir(out), "w1": _read_dir(single)}


@pytest.fixture(scope="module")
def knobs_run(tmp_path_factory):
    """The plain configuration with the V3 lead singles and a 64-slot lead
    cap as class-knob overrides: lead ballots widen, follows do not."""
    return _generate(tmp_path_factory.mktemp("knobs") / "run", knobs=KNOBS, **PLAIN)


@pytest.fixture(scope="module")
def widen_run(tmp_path_factory):
    """The plain configuration widened by ``--widen union``."""
    return _generate(tmp_path_factory.mktemp("widen") / "run", widen=WIDEN, **PLAIN)


# 1 ---------------------------------------------------------------- round trip

@pytest.mark.parametrize("run", ["explore_run", "plain_run"])
def test_round_trip_through_rebuild(run, request):
    run = request.getfixturevalue(run)
    records = run["records"]
    counts = run["manifest"]["counts"]
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
        for cand in record["ballot"]:            # the whole ballot is listed
            assert action_key(cand) in keys
            assert legal.is_legal(rnd, record["seat"], cand)
        if record["legal_actions_complete"]:
            assert record["legal_actions_count"] == len(keys)
            assert keys == legal.enumerate_legal(rnd, record["seat"], cap=None).keys()
        else:
            assert record["legal_actions_count"] is None or \
                record["legal_actions_count"] > 256
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
    assert again["shards"] == explore_run["shards"]
    assert again["sidecars"] == explore_run["sidecars"]
    assert again["manifest_bytes"] == explore_run["manifest_bytes"]


# 3 ---------------------------------------------------------- width invariance

def test_worker_count_does_not_change_bytes(explore_run, tmp_path):
    wide = _generate(tmp_path / "w2", workers=2, **EXPLORE)
    assert wide["bytes"] == explore_run["bytes"]
    assert wide["shards"] == explore_run["shards"]
    assert wide["sidecars"] == explore_run["sidecars"]
    assert wide["manifest_bytes"] == explore_run["manifest_bytes"]
    runtime = json.loads((wide["out"] / "runtime.json").read_text())
    assert runtime["workers"] == 2 and runtime["clusters"]["generated"] == [0]


# 4 ------------------------------------------ allocation vs preference, exploration

def test_allocation_is_search_work_and_preference_is_the_target(explore_run):
    records = explore_run["records"]
    counts = explore_run["manifest"]["counts"]
    fired = added_total = searched_with_added = refined = beyond_listing = 0
    for r in records:
        alloc, pref = r["allocation"], r["preference"]
        k = len(r["ballot"])
        w = alloc["weights"]
        assert alloc["kind"] == trajectory.ALLOCATION_KIND == "search-work"
        assert "NOT a preference" in alloc["counter"]
        assert len(w) == k and all(x >= 0 for x in w)
        assert abs(sum(w) - 1.0) <= 1e-9
        assert len(alloc["selection_worlds"]) == len(alloc["report_worlds"]) == k
        played = alloc["played_index"]
        assert action_key(r["ballot"][played]) == action_key(r["action"])
        worlds = [a + b for a, b in zip(alloc["selection_worlds"], alloc["report_worlds"])]
        # preference: two distributions over the ballot, recomputable
        assert pref["kind"] == trajectory.PREFERENCE_KIND
        for key in ("softmax", "final"):
            assert len(pref[key]) == k and all(0 <= x <= 1 for x in pref[key])
            assert abs(sum(pref[key]) - 1.0) <= 1e-9
        assert pref["final"] == [1.0 if i == played else 0.0 for i in range(k)]
        assert pref["played_index"] == played
        if alloc["searched"]:
            assert alloc["total_worlds"] == sum(worlds) > 0
            assert w == [x / sum(worlds) for x in worlds]
            assert min(alloc["selection_worlds"]) == WORK["select_worlds"]
            assert alloc["work"]["complete"] is True
            values = r["action_values"]
            assert values["kind"] == trajectory.ACTION_VALUES_KIND
            assert len(values["means"]) == len(values["paired_se"]) == k
            assert all(m is not None for m in values["means"])
            fold = values["report"]
            if fold is not None and fold["worlds"]:
                finalists = {0, alloc["report_candidate_index"]}
                assert len(finalists) == 2
                assert {i for i, n in enumerate(alloc["report_worlds"]) if n} == finalists
                assert all(alloc["report_worlds"][i] == fold["worlds"] == WORK["report_worlds"]
                           for i in finalists)
                # the challenger's mean was refined by pooling the report gap
                c = alloc["report_candidate_index"]
                assert pref["refined_indices"] == [c]
                n_sel = alloc["selection_worlds"][c]
                d_sel = values["means"][c] - values["means"][0]
                pooled = (n_sel * d_sel + fold["worlds"] * fold["gap"]) / (n_sel + fold["worlds"])
                assert pref["means"][c] == pytest.approx(values["means"][0] + pooled)
                assert pref["means"][0] == values["means"][0]
                refined += 1
            else:
                assert not any(alloc["report_worlds"])
                assert pref["refined_indices"] == []
                assert pref["means"] == values["means"]
            if pref["tau"] is not None:
                finite = [s for s in pref["paired_se"][1:] if s is not None]
                assert pref["tau"] == max(_median(finite), trajectory.TAU_FLOOR)
                assert pref["softmax"] == pytest.approx(_softmax(pref["means"], pref["tau"]),
                                                        abs=1e-12)
            else:
                assert pref["softmax"] == [1.0 / k] * k
        else:
            assert alloc["reason"] in ("tractor_lock", "single_candidate")
            assert w == [1.0] and r["ballot"] == [r["action"]]
            assert r["action_values"] is None and alloc["total_worlds"] == 0
            assert pref["softmax"] == pref["final"] == [1.0] and pref["tau"] is None
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
        assert ex["pool_count"] is not None
        if r["legal_actions_count"] is not None:     # exact: every non-ballot legal action
            assert ex["pool_count"] == r["legal_actions_count"] - len(prod_keys)
        for a in ex["added"]:
            assert action_key(a) in ballot_keys and action_key(a) in legal_keys
            assert action_key(a) not in prod_keys
        if not ex["added"]:
            # nothing was left to add: the ballot already covered the legal set
            assert ex["pool_count"] == 0 and legal_keys <= prod_keys
        elif alloc["searched"]:
            searched_with_added += 1
            for i in range(len(prod), len(r["ballot"])):    # worlds like any other
                assert alloc["selection_worlds"][i] == alloc["selection_worlds"][0] > 0
        if not r["legal_actions_complete"]:
            # the listing is the enumerator's 256-prefix plus the force-included
            # ballot; a draw from the FULL set usually lands beyond that prefix
            prefix = {tuple(a) for a in r["legal_actions"][:256]}
            beyond_listing += sum(1 for a in ex["added"] if action_key(a) not in prefix)
    assert fired == counts["explore_fired"] > 0
    assert added_total == counts["explore_added"] > 0
    assert searched_with_added > 0 and refined > 0
    assert counts["explore_pool_skipped"] == 0
    assert beyond_listing > 0


# 5 ------------------------------------------------------------------ identity

def test_explore_rate_zero_is_production(plain_run):
    records = plain_run["records"]
    counts = plain_run["manifest"]["counts"]
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


# 6 ---------------------------------------------------------- shard manifest

def test_manifest_lists_shards_with_matching_hashes(clean4):
    out = clean4["out"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema"] == trajectory.MANIFEST_SCHEMA
    assert manifest["clusters"] == 2 and manifest["rounds"] == 4
    assert [s["cluster"] for s in manifest["shards"]] == [0, 1]
    total = 0
    for shard in manifest["shards"]:
        path = out / shard["path"]
        assert shard["path"] == f"shards/cluster-{shard['cluster']:06d}.jsonl"
        assert shard["seed"] == SEED0 + shard["cluster"]
        assert shard["sha256"] == sha256_file(path)
        assert shard["bytes"] == path.stat().st_size
        assert shard["records"] == len(path.read_bytes().splitlines())
        assert (path.stat().st_mode & 0o777) == 0o444      # published read-only
        sidecar = json.loads((out / shard["sidecar"]).read_text())
        assert shard["sidecar_sha256"] == sha256_file(out / shard["sidecar"])
        assert sidecar["schema"] == trajectory.SHARD_SCHEMA
        assert sidecar["run_id"] == manifest["run_id"]
        assert sidecar["sha256"] == shard["sha256"] and sidecar["records"] == shard["records"]
        assert sidecar["counts"]["rounds"] == 2
        assert trajectory.verify_shard(out, manifest["config"], shard["cluster"],
                                       shard["seed"])[1] == "ok"
        total += shard["records"]
    assert manifest["counts"]["records"] == total == len(clean4["records"])
    merged = manifest["merged"]
    assert merged["path"] == "trajectory.jsonl"
    assert merged["sha256"] == sha256_file(out / "trajectory.jsonl")
    assert merged["records"] == total
    assert merged["bytes"] == (out / "trajectory.jsonl").stat().st_size
    assert clean4["bytes"] == b"".join(clean4["shards"][c] for c in (0, 1))
    assert len(manifest["identity"]["git_sha"]) == 40
    cfg = manifest["config"]
    assert cfg["policy"] == "mc-s0-report-lcb" and cfg["policy_class"] == "MCS0ReportLCB"
    assert cfg["work"]["registered"] == {"n_determinizations": 30,
                                         "report_fold_worlds": 300,
                                         "report_rule": "lcb"}
    assert cfg["work"]["effective"] == {"n_determinizations": 2,
                                        "report_fold_worlds": 30,
                                        "report_rule": "lcb"}
    assert cfg["work"]["production"] is False
    assert manifest["work_realized"]["rollouts"] > 0
    run = json.loads((out / "run.json").read_text())
    assert run["run_id"] == manifest["run_id"] == trajectory.build_config(
        seed0=SEED0, **WORK, **PLAIN)["run_id"]
    assert all(r["source_ref"].startswith(manifest["run_id"] + ":")
               for r in clean4["records"])
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["clusters"] == {"requested": 2, "reused": [], "generated": [0, 1],
                                   "failed": []}
    assert runtime["peak_rss_bytes"]["self"] > 0
    assert "wall_secs" not in manifest and "started" not in manifest    # deterministic


# 7 ------------------------------------------------------------ bury records

def test_bury_records_when_the_bury_path_exposes_a_record(tmp_path):
    run = _generate(tmp_path / "bury", policy="mc-s0-report-lcb-structured-bury",
                    **PLAIN)
    counts = run["manifest"]["counts"]
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
        k = len(r["ballot"])
        assert len(r["allocation"]["weights"]) == k == len(r["action_values"]["means"])
        assert abs(sum(r["allocation"]["weights"]) - 1.0) <= 1e-9
        pref = r["preference"]
        assert pref["tau"] is None and pref["softmax"] == [1.0 / k] * k   # means, no SEs
        assert sum(pref["final"]) == 1.0 and pref["final"][pref["played_index"]] == 1.0
        rnd = rebuild.state_for_record(r)
        assert rnd.phase == "bury" and rnd.turn == r["seat"]
        rnd.bury(r["seat"], r["action"])
        assert rnd.phase == "play"
    # a bury record precedes its seat's plays in the shard order
    for (_, _), recs in _by_round(run["records"]).items():
        kinds = [(r["seat"], r["decision_kind"]) for r in recs]
        banker = recs[0]["setup"]["banker"]
        assert all(k != (banker, "play") for k in kinds[:kinds.index((banker, "bury"))])


# W1 ---------------------------------- preference differs where allocation cannot

def _codex_case(*, played, gap):
    """Codex's witness: K=4, N=30 selection worlds, R=300 report worlds,
    challenger = candidate 2; only the report outcome differs."""
    return {
        "candidates": [["SA"], ["SK"], ["S2"], ["S3"]],
        "n_by_candidate": [30, 30, 30, 30],
        "means": [10.0, 5.0, 12.0, 3.0],
        "paired_se": [0.0, 4.0, 4.0, 4.0],
        "eligible_indices": [0, 1, 2, 3],
        "raw_winner_index": 2,
        "report_candidate_index": 2,
        "report_fold": {"gap": gap, "se": 2.0, "worlds": 300, "complete": True},
        "played_index": played,
        "played": [["SA"], ["SK"], ["S2"], ["S3"]][played],
        "reason": "report_lcb_override" if played else "report_lcb_below_min_gain",
        "work": {"complete": True},
    }


def test_preference_differs_where_allocation_cannot():
    loss = _codex_case(played=0, gap=-9.0)
    win = _codex_case(played=2, gap=+9.0)
    ballot = loss["candidates"]
    alloc_loss = trajectory.allocation_from_record(loss, ballot)
    alloc_win = trajectory.allocation_from_record(win, ballot)
    expected = [330 / 720, 30 / 720, 330 / 720, 30 / 720]
    assert alloc_loss["weights"] == alloc_win["weights"] == pytest.approx(expected)
    assert [round(x, 4) for x in alloc_win["weights"]] == [0.4583, 0.0417, 0.4583, 0.0417]
    pref_loss = trajectory.preference_from_record(loss)
    pref_win = trajectory.preference_from_record(win)
    for pref in (pref_loss, pref_win):
        assert abs(sum(pref["softmax"]) - 1.0) <= 1e-9
        assert abs(sum(pref["final"]) - 1.0) <= 1e-9
        assert pref["refined_indices"] == [2]
        # recomputable from the stored inputs
        assert pref["softmax"] == pytest.approx(_softmax(pref["means"], pref["tau"]))
    assert pref_loss["softmax"] != pref_win["softmax"]
    assert pref_loss["final"] == [1.0, 0.0, 0.0, 0.0]
    assert pref_win["final"] == [0.0, 0.0, 1.0, 0.0]
    # the refinement: pooled gap over 30 + 300 shared worlds, anchored on candidate 0
    assert pref_loss["means"][2] == pytest.approx(10.0 + (30 * 2.0 + 300 * -9.0) / 330)
    assert pref_win["means"][2] == pytest.approx(10.0 + (30 * 2.0 + 300 * 9.0) / 330)
    assert pref_loss["means"][:2] == pref_win["means"][:2] == [10.0, 5.0]
    se_pooled = math.sqrt((30 * 4.0) ** 2 + (300 * 2.0) ** 2) / 330
    assert pref_win["paired_se"][2] == pytest.approx(se_pooled)
    assert pref_win["tau"] == 4.0                    # median of (4.0, 1.85, 4.0)
    assert pref_loss["softmax"][0] > pref_loss["softmax"][2]
    assert pref_win["softmax"][2] > pref_win["softmax"][0]
    # no report fold: the selection-stage means are used as recorded
    bare = {k: v for k, v in win.items() if k != "report_fold"}
    plain = trajectory.preference_from_record(bare)
    assert plain["refined_indices"] == [] and plain["means"] == [10.0, 5.0, 12.0, 3.0]
    assert plain["softmax"] == pytest.approx(_softmax([10.0, 5.0, 12.0, 3.0], 4.0))
    # edge rules: no finite SE -> uniform; zero-world means -> the decision
    uniform = trajectory.preference_from_evidence([1.0, 2.0], [0.0, math.inf], 1)
    assert uniform["tau"] is None and uniform["softmax"] == [0.5, 0.5]
    none = trajectory.preference_from_evidence([-math.inf] * 2, [0.0, 4.0], 0)
    assert none["softmax"] == none["final"] == [1.0, 0.0]


# W2 ------------------------------------- exploration pool is the FULL legal set

class _LastSlotRng:
    """A stand-in stream whose ``randrange`` always returns 0: reservoir
    slot 0 ends up holding the LAST enumerated action."""

    def randrange(self, n):
        return 0


def test_exploration_pool_is_the_full_legal_set(explore_run):
    capped = [r for r in explore_run["records"]
              if not r["legal_actions_complete"] and r["ply"] % 4 == 0]
    assert capped, "the fixture holds no capped lead state"
    r = max(capped, key=lambda r: r["legal_actions_count"])
    assert r["legal_actions_count"] > 256
    rnd = rebuild.state_for_record(r)
    ballot = r.get("production_ballot", r["ballot"])
    listing = {tuple(a) for a in r["legal_actions"]}
    prefix = {tuple(a) for a in r["legal_actions"][:256]}
    # the deterministic witness: the last enumerated action is reachable
    sample, pool = trajectory.sample_off_ballot(rnd, r["seat"], 2, _LastSlotRng(), ballot)
    assert pool == r["legal_actions_count"] - len(ballot)
    last = legal.enumerate_legal(rnd, r["seat"], cap=None).actions[-1]
    assert tuple(sample[-1]) == tuple(last)
    assert tuple(last) not in prefix and tuple(last) not in listing   # beyond the cap
    assert legal.is_legal(rnd, r["seat"], last)
    assert legal.engine_accepts(rnd, r["seat"], last)
    # the old prefix-only draw (random.sample over the 256 listing) could never
    # return it; the reservoir draw over the full set does, for real seeds too
    outside = 0
    for seed in range(5):
        drawn, pool_again = trajectory.sample_off_ballot(
            rnd, r["seat"], 2, random.Random(seed), ballot)
        assert pool_again == pool and len(drawn) == 2
        for a in drawn:
            assert legal.is_legal(rnd, r["seat"], a)
            assert action_key(a) not in {action_key(c) for c in ballot}
            outside += tuple(a) not in prefix
    assert outside > 0


# W3 ------------------------------ worker failure keeps shards; resume completes

def test_worker_failure_keeps_shards_and_resume_completes_identically(
        clean4, tmp_path, monkeypatch):
    out = tmp_path / "interrupted"
    monkeypatch.setenv(trajectory.FAIL_CLUSTERS_ENV, "1")
    with pytest.raises(trajectory.TrajectoryError,
                       match="cluster 1: TrajectoryError: injected"):
        trajectory.generate(rounds=4, seed0=SEED0, out_dir=out, workers=2, merge=True,
                            **WORK, **PLAIN)
    # the cluster that finished is published and verifies; the failed one is absent
    config = trajectory.build_config(seed0=SEED0, **WORK, **PLAIN)
    assert trajectory.verify_shard(out, config, 0, SEED0)[1] == "ok"
    assert trajectory.verify_shard(out, config, 1, SEED0 + 1)[1] == "missing"
    assert not (out / "manifest.json").exists()
    assert not (out / "trajectory.jsonl").exists()
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["clusters"]["generated"] == [0]
    assert runtime["clusters"]["failed"][0][0] == 1
    assert (out / "shards" / "cluster-000000.jsonl").read_bytes() == clean4["shards"][0]
    # resume: cluster 0 reused, cluster 1 regenerated; bytes as the clean run
    monkeypatch.delenv(trajectory.FAIL_CLUSTERS_ENV)
    resumed = _generate(out, rounds=4, resume=True, **PLAIN)
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["resume"] is True
    assert runtime["clusters"] == {"requested": 2, "reused": [0], "generated": [1],
                                   "failed": []}
    assert resumed["shards"] == clean4["shards"]
    assert resumed["sidecars"] == clean4["sidecars"]
    assert resumed["bytes"] == clean4["bytes"]
    assert resumed["manifest_bytes"] == clean4["manifest_bytes"]


# W4 ------------------------------------------- resume refuses a different run

def test_resume_refuses_a_different_run(clean4, tmp_path):
    out = tmp_path / "copy"
    shutil.copytree(clean4["out"], out)
    with pytest.raises(trajectory.TrajectoryError, match="resume refused"):
        _generate(out, rounds=4, resume=True, seed0=SEED0 + 1, **PLAIN)
    with pytest.raises(trajectory.TrajectoryError, match="resume refused"):
        _generate(out, rounds=4, resume=True, **EXPLORE)
    with pytest.raises(trajectory.TrajectoryError, match="already holds run"):
        _generate(out, rounds=4, resume=False, **PLAIN)
    # nothing was touched
    assert _read_dir(out)["manifest_bytes"] == clean4["manifest_bytes"]


def test_resume_refuses_transitive_source_drift(clean4, tmp_path, monkeypatch):
    out = tmp_path / "source-drift"
    shutil.copytree(clean4["out"], out)
    original_digest = trajectory._source_tree_digest
    monkeypatch.setattr(
        trajectory, "_source_tree_digest",
        lambda root: hashlib.sha256(
            (original_digest(root) + ":changed-transitive-source").encode()
        ).hexdigest(),
    )
    with pytest.raises(trajectory.TrajectoryError,
                       match="source_tree_sha256"):
        _generate(out, rounds=4, resume=True, **PLAIN)
    # Admission fails before any completed artifact is touched.
    assert _read_dir(out)["manifest_bytes"] == clean4["manifest_bytes"]
    assert _read_dir(out)["bytes"] == clean4["bytes"]


# W5 ------------------------------------ a corrupted shard is regenerated on resume

def test_corrupted_shard_is_regenerated_on_resume(clean4, tmp_path):
    out = tmp_path / "corrupt"
    shutil.copytree(clean4["out"], out)
    shard = out / "shards" / "cluster-000000.jsonl"
    os.chmod(shard, 0o644)
    data = bytearray(shard.read_bytes())
    data[100] ^= 0x01                                   # flip one bit
    shard.write_bytes(bytes(data))
    config = trajectory.build_config(seed0=SEED0, **WORK, **PLAIN)
    assert trajectory.verify_shard(out, config, 0, SEED0)[1] == "sha256"
    assert trajectory.verify_shard(out, config, 1, SEED0 + 1)[1] == "ok"
    resumed = _generate(out, rounds=4, resume=True, **PLAIN)
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["clusters"] == {"requested": 2, "reused": [1], "generated": [0],
                                   "failed": []}
    assert (shard.stat().st_mode & 0o777) == 0o444
    assert resumed["shards"] == clean4["shards"]
    assert resumed["manifest_bytes"] == clean4["manifest_bytes"]
    assert resumed["bytes"] == clean4["bytes"]


# W6 --------------------------- the parent drops published results (#208)

def test_parent_does_not_retain_published_results(retention_run):
    live = retention_run["live"]
    manifest = retention_run["manifest"]
    assert manifest["clusters"] == 6 and len(live) == 6
    assert retention_run["runtime"]["workers"] == 2
    assert retention_run["runtime"]["clusters"]["generated"] == list(range(6))
    # at every publish the parent holds at most the in-flight window of
    # results (the one being published + those completed but not yet
    # consumed), never every cluster published so far
    window = trajectory.INFLIGHT_PER_WORKER * 2
    assert max(n for _, n in live) <= window < 6
    assert live[-1][1] <= 2                       # nothing accumulated by the end
    assert len(trajectory.LIVE_RESULTS) == 0      # and nothing outlives the pool
    # the bounded window changes scheduling only: bytes as on one worker
    assert retention_run["w2"]["shards"] == retention_run["w1"]["shards"]
    assert retention_run["w2"]["sidecars"] == retention_run["w1"]["sidecars"]
    assert retention_run["w2"]["manifest_bytes"] == retention_run["w1"]["manifest_bytes"]


def test_per_cluster_wall_secs_is_the_clusters_own_duration(retention_run):
    per_cluster = retention_run["runtime"]["per_cluster"]
    assert sorted(per_cluster) == [str(c) for c in range(6)]
    finished = {}
    for c, t in per_cluster.items():
        # the task's own clock: both rounds plus the task's few ms of
        # overhead -- not the time since the pool started
        rounds = sum(t["round_wall_secs"])
        assert len(t["round_wall_secs"]) == 2 and rounds > 0
        # (each value is rounded to 4 decimals on its own, hence the slack)
        assert -1e-3 <= t["wall_secs"] - rounds < 0.25, (c, t)
        assert t["finished_at"] - t["started_at"] == pytest.approx(t["wall_secs"], abs=0.05)
        finished[int(c)] = t["finished_at"]
    # two workers: the sixth cluster cannot start before four others finished
    assert per_cluster["5"]["started_at"] >= sorted(finished.values())[3]
    total = retention_run["runtime"]["wall_secs"]
    assert max(t["wall_secs"] for t in per_cluster.values()) < total


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
        trajectory.run_clusters(config, rounds=3, seed0=1, out_dir=tmp_path)   # odd
    with pytest.raises(trajectory.TrajectoryError):
        trajectory.run_clusters(config, rounds=2, seed0=1, out_dir=tmp_path, workers=0)


def _schema_base():
    return {
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


def test_schema_exploration_and_preference_fields():
    base = _schema_base()
    ex = {"rate": 0.1, "added": [["S4"]], "pool_count": 1}
    ok = finalize_record({**base, "exploration": ex})
    assert ok["exploration"] == ex
    assert finalize_record({**base, "exploration": None})["exploration"] is None
    assert "exploration" not in finalize_record(base)
    for bad in ({"rate": 1.5, "added": [], "pool_count": 0}, {"rate": 0.1, "added": []},
                {"rate": 0.1, "added": [["S9"]], "pool_count": 1},
                {"rate": 0.1, "added": "S4", "pool_count": 1},
                {"rate": 0.1, "added": [], "pool_count": -1}):
        with pytest.raises(SchemaError):
            finalize_record({**base, "exploration": bad})
    pref = {"kind": "trajectory-preference-v1", "softmax": [0.25, 0.75],
            "final": [0.0, 1.0], "tau": 1.5, "means": [1.0, 2.0],
            "paired_se": [0.0, 1.5], "refined_indices": [], "played_index": 1}
    assert finalize_record({**base, "preference": pref})["preference"] == pref
    assert finalize_record({**base, "preference": None})["preference"] is None
    for bad in ({**pref, "softmax": [0.5, 0.6]}, {**pref, "final": [1.0]},
                {**pref, "softmax": [1.5, -0.5]}, "nope"):
        with pytest.raises(SchemaError):
            finalize_record({**base, "preference": bad})


def test_schema_widening_field():
    base = _schema_base()
    wd = {"variants": ["union"], "added": [["S4"]]}
    assert finalize_record({**base, "widening": wd})["widening"] == wd
    assert finalize_record({**base, "widening": None})["widening"] is None
    assert "widening" not in finalize_record(base)          # sources that do not widen
    empty = {"variants": ["points"], "added": []}
    assert finalize_record({**base, "widening": empty})["widening"] == empty
    for bad in ({"variants": [], "added": []}, {"variants": ["union"]},
                {"variants": ["union"], "added": [["S9"]]},        # not on the ballot
                {"variants": "union", "added": []}, {"variants": ["union"], "added": "S4"},
                {"variants": [""], "added": []},
                {"variants": ["union"], "added": [], "extra": 1}, "nope"):
        with pytest.raises(SchemaError):
            finalize_record({**base, "widening": bad})


# K1 ------------------------------------ no --knob / --widen: bytes as today

def test_no_knobs_and_no_widen_is_byte_identical(plain_run, tmp_path):
    neutral = _generate(tmp_path / "neutral", knobs=[], widen=[], **PLAIN)
    assert neutral["manifest"]["run_id"] == plain_run["manifest"]["run_id"] == PLAIN_RUN_ID
    assert neutral["bytes"] == plain_run["bytes"]
    assert neutral["shards"] == plain_run["shards"]
    assert neutral["sidecars"] == plain_run["sidecars"]
    assert neutral["manifest_bytes"] == plain_run["manifest_bytes"]
    for spec in ({}, {"knobs": None}, {"knobs": []}, {"knobs": {}}, {"widen": None},
                 {"widen": []}, {"knobs": [], "widen": []}):
        cfg = trajectory.build_config(seed0=SEED0, **WORK, **PLAIN, **spec)
        assert cfg["run_id"] == PLAIN_RUN_ID
        assert cfg["knobs"] == {} and cfg["widen"] == []
        assert cfg["trajectory_class"] == "Trajectory_MCS0ReportLCB"
    cfg = plain_run["manifest"]["config"]
    assert cfg["knobs"] == {} and cfg["widen"] == []
    assert all("widening" not in r and "production_ballot" not in r
               for r in plain_run["records"])


# K2 ----------------------------------------------- refusals before any round

def test_knob_and_widen_refusals_happen_before_any_round(tmp_path, capsys):
    def refuses(match, **kw):
        with pytest.raises(trajectory.TrajectoryError, match=match):
            trajectory.build_config(seed0=1, **WORK, **kw)

    refuses("unknown knob NOPE", knobs=["NOPE=1"])
    refuses("not a bool", knobs=["V3_LEAD_SINGLES=maybe"])
    refuses("given more than once", knobs=["LEAD_MAX_CANDIDATES=64",
                                           "LEAD_MAX_CANDIDATES=32"])
    refuses("search work is not a policy knob", knobs=["N_DETERMINIZATIONS=5"])
    refuses("search work is not a policy knob", knobs=["REPORT_FOLD_WORLDS=30"])
    refuses("not an int", knobs=["LEAD_MAX_CANDIDATES=1.5"])
    refuses("not finite", knobs=["MARGIN=nan"])
    refuses("not a public attribute name", knobs=["_rng=1"])
    refuses("method or descriptor", knobs=["decide_play=1"])
    refuses("expected NAME=VALUE", knobs=["LEAD_MAX_CANDIDATES"])
    refuses("cannot be overridden", knobs=["LEAD_MARGIN=3"])          # None-valued
    refuses("sets it per instance", policy="mc-s0-report-lcb-structured-bury",
            knobs=["MC_BURY=0"])
    refuses("unknown widen variant", widen=["nope"])
    refuses("unknown widen variant", widen=["production"])
    # accepted forms coerce to the attribute's own type, in any spelling
    cfg = trajectory.build_config(seed0=1, **WORK, knobs=[
        "V3_LEAD_SINGLES=true", "LEAD_MAX_CANDIDATES= 64 ", "MARGIN=2"])
    assert cfg["knobs"] == {"LEAD_MAX_CANDIDATES": 64, "MARGIN": 2.0,
                            "V3_LEAD_SINGLES": True}
    assert cfg["knobs"] == trajectory.build_config(seed0=1, **WORK, knobs={
        "MARGIN": 2, "V3_LEAD_SINGLES": 1, "LEAD_MAX_CANDIDATES": 64})["knobs"]
    assert trajectory.parse_widen(["union", "wide", "union"]) == ["union", "wide"]
    assert trajectory.widen_extensions(["union"]) == ballot_capture.UNION_OF
    # the command line refuses the same way, before touching the out dir
    out = tmp_path / "never"
    base = ["--rounds", "2", "--seed", "1", "--out", str(out),
            "--select-worlds", "2", "--report-worlds", "30"]
    for extra, message in ((["--knob", "NOPE=1"], "unknown knob NOPE"),
                           (["--knob", "N_DETERMINIZATIONS=5"], "search work"),
                           (["--knob", "V3_LEAD_SINGLES=1", "--knob", "V3_LEAD_SINGLES=0"],
                            "more than once"),
                           (["--widen", "nope"], "unknown widen variant")):
        assert trajectory.main([*base, *extra]) == 2
        assert f"REFUSING: " in capsys.readouterr().err
    assert not out.exists()


# K3 ----------------- knobs widen the search; production_ballot stays production

def _independent_knobs_bot(overrides, seed=0):
    """The overridden class rebuilt from scratch, without the generator."""
    bot = make_bot(trajectory.DEFAULT_POLICY, seed=seed)
    bot.__class__ = type("IndependentKnobs", (type(bot),), dict(overrides))
    return bot


def test_knobs_widen_the_search_ballot_and_keep_production_ballot(knobs_run, plain_run):
    records = knobs_run["records"]
    manifest = knobs_run["manifest"]
    assert manifest["run_id"] != plain_run["manifest"]["run_id"]
    assert manifest["config"]["knobs"] == KNOB_VALUES
    assert manifest["config"]["policy_class"] == "MCS0ReportLCB"
    assert manifest["config"]["trajectory_class"] == "Trajectory_Knobs_MCS0ReportLCB"
    assert manifest["counts"]["explore_fired"] == 0
    production = make_bot(trajectory.DEFAULT_POLICY, seed=0)
    knobbed = _independent_knobs_bot(KNOB_VALUES)
    widened = 0
    for r in records:
        validate_record(r)
        assert r["policy"] == trajectory.DEFAULT_POLICY   # make_bot(policy) builds production
        assert "widening" not in r
        rnd = rebuild.state_for_record(r)
        if r["allocation"]["reason"] == "tractor_lock":
            assert "production_ballot" not in r
            continue
        prod = r["production_ballot"]                      # on EVERY decision with a ballot
        # production's list, computed independently from the base class ...
        assert prod == [list(c) for c in production._candidates(rnd, r["seat"])]
        # ... and the searched ballot is the overridden class's list
        assert r["ballot"] == [list(c) for c in knobbed._candidates(rnd, r["seat"])]
        assert r["ballot"][:len(prod)] == prod             # production first, then the widening
        assert {action_key(c) for c in prod} <= {action_key(c) for c in r["ballot"]}
        k = len(r["ballot"])
        pref, alloc = r["preference"], r["allocation"]
        for key in ("softmax", "final"):
            assert len(pref[key]) == k and abs(sum(pref[key]) - 1.0) <= 1e-9
        assert len(alloc["weights"]) == len(alloc["selection_worlds"]) == k
        assert action_key(r["ballot"][alloc["played_index"]]) == action_key(r["action"])
        if alloc["searched"]:
            assert alloc["selection_worlds"] == [WORK["select_worlds"]] * k
            assert len(r["action_values"]["means"]) == k
        if k > len(prod):
            widened += 1
            assert r["ply"] % 4 == 0        # these overrides only touch LEAD ballots
    assert widened > 0


# K4 --------------------------------- manifest / run.json stamp the identity

def test_manifest_and_run_json_stamp_knobs_and_widen(knobs_run, widen_run, plain_run):
    for run, knobs, widen in ((knobs_run, KNOB_VALUES, []), (widen_run, {}, WIDEN),
                              (plain_run, {}, [])):
        manifest = run["manifest"]
        run_json = json.loads((run["out"] / "run.json").read_text())
        for cfg in (manifest["config"], run_json["config"]):
            assert cfg["knobs"] == knobs and cfg["widen"] == widen
        expected = trajectory.build_config(seed0=SEED0, **WORK, **PLAIN,
                                           knobs=knobs, widen=widen)["run_id"]
        assert run_json["run_id"] == manifest["run_id"] == expected
        assert all(s["run_id"] == manifest["run_id"] for s in
                   (json.loads(b) for b in run["sidecars"].values()))
        assert all(r["source_ref"].startswith(manifest["run_id"] + ":")
                   for r in run["records"])
    ids = {plain_run["manifest"]["run_id"], knobs_run["manifest"]["run_id"],
           widen_run["manifest"]["run_id"]}
    assert len(ids) == 3
    # the override SET is the identity, not its spelling or order
    for spelling in (["V3_LEAD_SINGLES=true", "LEAD_MAX_CANDIDATES=64"],
                     ["LEAD_MAX_CANDIDATES=64", "V3_LEAD_SINGLES=1"], KNOB_VALUES):
        cfg = trajectory.build_config(seed0=SEED0, **WORK, **PLAIN, knobs=spelling)
        assert cfg["run_id"] == knobs_run["manifest"]["run_id"]
    for other in (["V3_LEAD_SINGLES=1"], ["V3_LEAD_SINGLES=1", "LEAD_MAX_CANDIDATES=32"],
                  [*KNOBS, "TRACTOR_LOCK=0"]):
        assert trajectory.build_config(seed0=SEED0, **WORK, **PLAIN,
                                       knobs=other)["run_id"] not in ids
    assert trajectory.build_config(seed0=SEED0, **WORK, **PLAIN, widen=["union", "union"]
                                   )["run_id"] == widen_run["manifest"]["run_id"]
    assert trajectory.build_config(seed0=SEED0, **WORK, **PLAIN, widen=["wide"]
                                   )["run_id"] not in ids
    assert trajectory.build_config(seed0=SEED0, **WORK, **PLAIN, knobs=KNOBS,
                                   widen=WIDEN)["run_id"] not in ids
    # policy_flags describe the DATA policy; work.registered stays production's
    cfg = trajectory.build_config(seed0=1, **WORK, knobs=["TRACTOR_LOCK=0", "MC_BURY=1"])
    assert cfg["policy_flags"]["tractor_lock"] is False and cfg["policy_flags"]["mc_bury"] is True
    assert cfg["work"]["registered"] == knobs_run["manifest"]["config"]["work"]["registered"]
    assert cfg["work"]["registered"]["n_determinizations"] == 30


# K5 ------------------------------ resume refuses a different knob / widen set

def test_resume_refuses_a_different_knob_or_widen_set(knobs_run, widen_run, clean4,
                                                      tmp_path):
    knobs_copy, widen_copy, plain_copy = (tmp_path / n for n in ("knobs", "widen", "plain"))
    shutil.copytree(knobs_run["out"], knobs_copy)
    shutil.copytree(widen_run["out"], widen_copy)
    shutil.copytree(clean4["out"], plain_copy)
    cases = [
        (knobs_copy, {}),                                                  # no overrides
        (knobs_copy, {"knobs": ["V3_LEAD_SINGLES=1"]}),                   # a subset
        (knobs_copy, {"knobs": [*KNOBS, "TRACTOR_LOCK=0"]}),               # a superset
        (knobs_copy, {"knobs": ["V3_LEAD_SINGLES=1", "LEAD_MAX_CANDIDATES=32"]}),
        (knobs_copy, {"knobs": KNOBS, "widen": WIDEN}),                    # widening added
        (widen_copy, {}),
        (widen_copy, {"widen": ["wide"]}),
        (widen_copy, {"widen": [*WIDEN, "points"]}),
        (widen_copy, {"widen": WIDEN, "knobs": KNOBS}),
        (plain_copy, {"knobs": KNOBS}),
        (plain_copy, {"widen": WIDEN}),
    ]
    for out, options in cases:
        rounds = 4 if out is plain_copy else ROUNDS
        with pytest.raises(trajectory.TrajectoryError, match="resume refused"):
            _generate(out, rounds=rounds, resume=True, **PLAIN, **options)
    # nothing was touched
    assert _read_dir(knobs_copy)["manifest_bytes"] == knobs_run["manifest_bytes"]
    assert _read_dir(widen_copy)["manifest_bytes"] == widen_run["manifest_bytes"]
    assert _read_dir(plain_copy)["manifest_bytes"] == clean4["manifest_bytes"]
    # the same set, in another spelling, resumes and reuses every shard
    for out, run, options in ((knobs_copy, knobs_run,
                               {"knobs": ["LEAD_MAX_CANDIDATES=64", "V3_LEAD_SINGLES=true"]}),
                              (widen_copy, widen_run, {"widen": ["union", "union"]})):
        resumed = _generate(out, resume=True, **PLAIN, **options)
        runtime = json.loads((out / "runtime.json").read_text())
        assert runtime["clusters"] == {"requested": 1, "reused": [0], "generated": [],
                                       "failed": []}
        assert resumed["shards"] == run["shards"] and resumed["bytes"] == run["bytes"]
        assert resumed["manifest_bytes"] == run["manifest_bytes"]


# K6 -------------------------- --widen union: every variant's candidates, work

def test_widen_union_appends_every_variant_candidate(widen_run, plain_run):
    records = widen_run["records"]
    manifest = widen_run["manifest"]
    counts = manifest["counts"]
    assert manifest["run_id"] != plain_run["manifest"]["run_id"]
    assert manifest["config"]["widen"] == ["union"] and manifest["config"]["knobs"] == {}
    assert manifest["config"]["trajectory_class"] == "Trajectory_MCS0ReportLCB"
    assert counts["explore_fired"] == 0
    production = make_bot(trajectory.DEFAULT_POLICY, seed=0)
    decisions = added_total = played_added = lead_widened = follow_widened = 0
    for r in records:
        validate_record(r)
        assert r["policy"] == trajectory.DEFAULT_POLICY
        rnd = rebuild.state_for_record(r)
        seat = r["seat"]
        if r["allocation"]["reason"] == "tractor_lock":
            assert r["widening"] is None and "production_ballot" not in r
            continue
        decisions += 1
        prod = r["production_ballot"]
        assert prod == [list(c) for c in production._candidates(rnd, seat)]
        wd = r["widening"]
        assert wd["variants"] == ["union"]
        assert r["ballot"] == prod + wd["added"]       # production first, then the widening
        keys = {action_key(c) for c in r["ballot"]}
        prod_keys = {action_key(c) for c in prod}
        assert len(keys) == len(r["ballot"])           # no duplicates
        # every variant's set, recomputed here, is covered -- and nothing else
        expected = set()
        for name in ballot_capture.UNION_OF:
            expected |= {action_key(k) for k in ballot_capture.EXTENSIONS[name](rnd, seat)}
        expected = {k for k in expected if legal.is_legal(rnd, seat, list(k))}
        assert expected <= keys
        assert {action_key(a) for a in wd["added"]} == expected - prod_keys
        assert wd["added"] == [list(k) for k in sorted(action_key(a) for a in wd["added"])]
        listing = {tuple(a) for a in r["legal_actions"]}
        for a in wd["added"]:
            assert legal.is_legal(rnd, seat, a) and legal.engine_accepts(rnd, seat, a)
            assert action_key(a) in listing
        added_total += len(wd["added"])
        if action_key(r["action"]) in {action_key(a) for a in wd["added"]}:
            played_added += 1
        k = len(r["ballot"])
        pref, alloc = r["preference"], r["allocation"]
        for key in ("softmax", "final"):
            assert len(pref[key]) == k and abs(sum(pref[key]) - 1.0) <= 1e-9
        assert len(alloc["weights"]) == len(alloc["selection_worlds"]) == k
        if alloc["searched"]:
            # work accounting: N selection worlds for every widened candidate
            assert alloc["selection_worlds"] == [WORK["select_worlds"]] * k
            assert alloc["total_worlds"] == WORK["select_worlds"] * k + sum(alloc["report_worlds"])
            assert len(r["action_values"]["means"]) == k
        if wd["added"]:
            if r["ply"] % 4 == 0:
                lead_widened += 1
            else:
                follow_widened += 1
    assert counts["widen_decisions"] == decisions > 0
    assert counts["widen_added"] == added_total > 0
    assert counts["widen_played"] == played_added
    assert lead_widened > 0 and follow_widened > 0


# K7 ----------------- knobs + widening + exploration compose on one decision

def test_knobs_widening_and_exploration_compose(widen_run):
    """The Run B shape without rollouts: one contested lead state, the bot's
    ``_candidates`` called directly."""
    config = trajectory.build_config(seed0=SEED0, **WORK, explore_rate=1.0, explore_k=2,
                                     knobs=RUN_B_KNOBS, widen=WIDEN)
    assert config["knobs"] == dict(sorted(RUN_B_KNOBS.items()))
    assert config["policy_flags"]["tractor_lock"] is False
    r = next(r for r in _plays(widen_run["records"])
             if r["ply"] % 4 == 0 and len(r["production_ballot"]) > 1)
    rnd = rebuild.state_for_record(r)
    seat = r["seat"]
    bot = trajectory.make_trajectory_bot(config, seed=7, explore_rng=random.Random(1))
    assert type(bot).__name__ == "Trajectory_Knobs_MCS0ReportLCB"
    assert type(bot.production_probe).__name__ == "MCS0ReportLCB"
    ballot = bot._candidates(rnd, seat)
    prod = bot.last_production_ballot
    assert prod == r["production_ballot"]
    assert prod == [list(c) for c in make_bot(trajectory.DEFAULT_POLICY, seed=0)
                    ._candidates(rnd, seat)]
    own = [list(c) for c in _independent_knobs_bot(RUN_B_KNOBS)._candidates(rnd, seat)]
    wd, ex = bot.last_widening, bot.last_exploration
    assert ex is not None and ex["rate"] == 1.0
    assert ballot == own + wd["added"] + ex["added"]      # overrides, widening, exploration
    parts = [own, wd["added"], ex["added"]]
    assert len({action_key(a) for part in parts for a in part}) == len(ballot)
    assert len(own) > len(prod) and len(ballot) > len(own)
    assert wd["variants"] == ["union"]
    expected = set()
    for name in ballot_capture.UNION_OF:
        expected |= {action_key(k) for k in ballot_capture.EXTENSIONS[name](rnd, seat)}
    assert {k for k in expected if legal.is_legal(rnd, seat, list(k))} <= {
        action_key(c) for c in ballot}
    assert {action_key(c) for c in ballot} <= bot.last_legal.keys()
    assert bot.explore_fired == 1 and bot.widen_added == len(wd["added"])
    with pytest.raises(trajectory.TrajectoryError, match="consulted twice"):
        bot._candidates(rnd, seat)
