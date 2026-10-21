"""The belief proposal's log (``SHENGJI_PV_BELIEF_LOG``, `ai.belief_numpy` log
helpers, `scripts/belief_debug.py`).

Witnesses: the snapshot round-trips within half a quantisation step and its
summary is the per-copy entropy / top mass; the flag accepts only 0/1/unset,
is on by default and enters no name (release 45, v86 and the v92 combo names
are unchanged under 0, 1 and unset); on the production package, a run of real
decisions with the flag off and on takes identical actions, draws identical
worlds, leaves the sampler stream in the identical state and writes identical
records except the added ``belief_*`` keys; every logged decision's worlds are
regenerated exactly offline from its seed, through the debug tool on a room log;
the trajectory store carries the fields; the x-ray shows the summary only.
"""
import copy
import importlib.util
import json
import os
import random
import tomllib
from pathlib import Path

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import PRODUCTION_SHA
from test_world_history_legal import RELEASE45_ENV, RELEASE45_NAME
from test_release46_fly_config import without_combo
from test_encoder_round_compat import pinned_production_package  # noqa: F401

SERVER = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("belief_debug", SERVER / "scripts" / "belief_debug.py")
belief_debug = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(belief_debug)

BELIEF_SHA = "763b5e0536549404b9b5c3449e2379f7af48a4b59c163928296ee904d4da4343"
BELIEF_ENV = {"SHENGJI_PV_WORLD_HISTORY_LEGAL": "1", "SHENGJI_PV_WORLD_HISTORY_DRAW": "1",
              "SHENGJI_PV_BELIEF_WORLDS": "1",
              "SHENGJI_PV_BELIEF_CKPT": "/data/models/s17long-e2-763b5e05.npz",
              "SHENGJI_PV_BELIEF_SHA256": BELIEF_SHA}
EXACT_VDEF_ENV = {"SHENGJI_PV_EXACT_LEAD_ENDGAME": "1", "SHENGJI_PV_EXACT_DEEP_CARDS": "7",
                  "SHENGJI_PV_EXACT_FOLLOW": "1", "SHENGJI_PV_EXACT_FOLLOW_SOLVER": "compact-level",
                  "SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS": "7",
                  "SHENGJI_PV_EXACT_FOLLOW_MAX_NODES": "50000000",
                  "SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST": "1"}
V86_NAME = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-la-dtr-vd-r38f35977-bury-hybrid-bwv-"
            "1c0559db4938")
COMBO_NAME = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-vd-vdef-ed7-xf7-"
              "xfcompactlevel-r73993d62-bury-hybrid-bwv-cf77a93949b0")
LOG_KEYS = {"belief_log", "belief_seed", "belief_snapshot", "belief_entropy_bits",
            "belief_top_mass", "belief_hidden_copies", "belief_refusals", "belief_log_error"}
#: wall-clock fields: the only record values two identical runs may differ in
CLOCK_SUFFIXES = ("seconds", "secs", "_ms")
#: real decisions per arm in the differential (the bar is 200)
MIN_DECISIONS = 200


# ------------------------------------------------------------------ snapshot

def test_snapshot_round_trip_and_summary():
    rng = np.random.default_rng(0)
    P = rng.dirichlet(np.ones(4), size=bn.N_CARDS)
    P[[3, 17, 40]] = 0.0
    snap = bn.encode_snapshot(P)
    assert snap["v"] == bn.SNAPSHOT_VERSION and len(snap["rows"]) == 14
    back = bn.decode_snapshot(json.loads(json.dumps(snap)))
    assert np.abs(back - P).max() <= 0.5 / bn.SNAPSHOT_SCALE + 1e-12
    assert not back[[3, 17, 40]].any()
    n_c = np.full(bn.N_CARDS, 2)
    n_c[[3, 17, 40]] = 0
    n_c[5] = 1
    s = bn.snapshot_summary(P, n_c)
    live = P.sum(-1) > 0
    w = n_c[live]
    ent = -(P[live] * np.log2(P[live])).sum(-1)
    assert s["belief_hidden_copies"] == int(w.sum())
    assert s["belief_entropy_bits"] == round(float((w * ent).sum() / w.sum()), 4)
    assert s["belief_top_mass"] == round(float((w * P[live].max(-1)).sum() / w.sum()), 4)
    assert bn.snapshot_summary(np.zeros((54, 4)), np.zeros(54))["belief_hidden_copies"] == 0
    with pytest.raises(bn.BeliefNumpyError):
        bn.decode_snapshot({**snap, "v": 2})
    with pytest.raises(bn.BeliefNumpyError):
        bn.decode_snapshot({**snap, "rows": "f" * 14})


# ------------------------------------------------------------------ flag and names

@pytest.mark.parametrize("raw,want", [(None, True), ("", True), ("1", True), ("0", False)])
def test_flag_values(raw, want):
    env = {} if raw is None else {"SHENGJI_PV_BELIEF_LOG": raw}
    assert pv.belief_log_enabled(env) is want


@pytest.mark.parametrize("bad", ["2", "true", "yes", " 1"])
def test_flag_refuses_anything_else(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**RELEASE45_ENV, "SHENGJI_PV_BELIEF_LOG": bad})


def test_names_do_not_read_the_flag(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])
    monkeypatch.setattr(pv, "file_sha256",
                        lambda path: BELIEF_SHA if "s17long" in str(path) else PRODUCTION_SHA)
    arms = {RELEASE45_NAME: RELEASE45_ENV, V86_NAME: {**RELEASE45_ENV, **BELIEF_ENV},
            COMBO_NAME: {**RELEASE45_ENV, **BELIEF_ENV, **EXACT_VDEF_ENV}}
    for name, env in arms.items():
        for flag in (None, "0", "1"):
            e = dict(env) if flag is None else {**env, "SHENGJI_PV_BELIEF_LOG": flag}
            assert list(pv.pv_registry_entries(**pv.pv_env_recipe(e))) == [name]
            recipe = pv.pv_env_recipe(e)
            assert "belief_log" not in recipe


# ------------------------------------------------------------------ real decisions

@pytest.fixture(scope="module")
def belief_package(tmp_path_factory):
    """The S17 package when ``SHENGJI_PV_BELIEF46_PACKAGE_PATH`` names it (sha
    pinned), else a seeded random-weight package of the same runtime (NumPy
    only: the draw, the log and the replay do not depend on what was learnt)."""
    real = os.environ.get("SHENGJI_PV_BELIEF46_PACKAGE_PATH")
    if real:
        return {"path": real, "sha256": BELIEF_SHA}
    rng = np.random.default_rng(11)
    config = {"d": 16, "heads": 2, "enc_layers": 1, "xattn_layers": 1, "x_hidden": 16,
              "card_self_attn": True}
    shapes = bn.expected_shapes(config, **bn.DIMS)
    # the 1-D weights are the layer norms' gains
    weights = {k: (np.ones(s) if k.endswith(".weight") and len(s) == 1
                   else rng.normal(0.0, 0.2, s)).astype(np.float32) for k, s in shapes.items()}
    path = tmp_path_factory.mktemp("belief-log") / "random.npz"
    sha = bn.save_package(path, config, weights, {"temperature": 1.0})
    return {"path": str(path), "sha256": sha}


def served_env(package_path, belief):
    # the release-45 base (production without release 46's combo lines) plus the
    # belief proposal: the exact stages and the declaration gate are not under test
    env = without_combo(tomllib.loads((SERVER.parent / "fly.toml").read_text())["env"])
    env = {k: v for k, v in env.items() if k.startswith("SHENGJI_PV_")}
    # no serving budget: a wall-clock fallback would make the two arms differ
    # for a reason that is not the flag
    env.pop("SHENGJI_PV_SERVING_BUDGET_SECONDS")
    env.update(SHENGJI_PV_CKPT=str(package_path), SHENGJI_PV_WORLD_HISTORY_LEGAL="1",
               SHENGJI_PV_WORLD_HISTORY_DRAW="1", SHENGJI_PV_BELIEF_WORLDS="1",
               SHENGJI_PV_BELIEF_CKPT=belief["path"], SHENGJI_PV_BELIEF_SHA256=belief["sha256"])
    return env


def logged_round(game_seed):
    """A heuristic setup at its first play, with the room-log setup events."""
    h = HeuristicBot()
    rnd = Game(random.Random(game_seed)).start_round()
    events = [{"e": "round_start", "round": game_seed, "deck": list(rnd.deck),
               "trump_rank": rnd.trump_rank, "banker": rnd.banker, "players": []}]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = h.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            events.append({"e": "declare", "round": game_seed, "seat": seat, "cards": cards})
    for seat in range(4):
        cards = h.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            events.append({"e": "declare", "round": game_seed, "seat": seat, "cards": cards})
    rnd.finalize_declare()
    bury = h.decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, bury)
    events += [{"e": "trump", "round": game_seed, "banker": rnd.banker},
               {"e": "bury", "round": game_seed, "seat": rnd.banker, "cards": list(bury)}]
    return rnd, events


def engine_cards(rnd, seat):
    trick = rnd.trick if rnd.trick is not None and rnd.trick.plays else rnd.history[-1]
    return next(list(p.cards) for p in trick.plays if p.seat == seat)


def play_rounds(env, flag, n_decisions):
    """One bot in all four seats over heuristic setups until ``n_decisions``
    plays: per decision its state, action, record and the worlds it drew."""
    os.environ["SHENGJI_PV_BELIEF_LOG"] = flag
    try:
        entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
        name, = entries
        bot = entries[name](seed=7)
    finally:
        os.environ.pop("SHENGJI_PV_BELIEF_LOG")
    drawn = []
    original = bot._worlds

    def capture(rnd, seat, check_budget=None):
        worlds, attempts = original(rnd, seat, check_budget)
        drawn.append(copy.deepcopy(worlds))
        return worlds, attempts
    bot._worlds = capture
    out, logs, game_seed = [], [], 0
    while len(out) < n_decisions:
        rnd, events = logged_round(2000 + game_seed)
        while rnd.phase == "play":
            seat = rnd.turn
            before = copy.deepcopy(rnd)
            del drawn[:]
            cards = bot.decide_play(rnd, seat)
            record = copy.deepcopy(bot.last_decision_record)
            rnd.play(seat, cards)
            event = {"e": "play", "round": 2000 + game_seed, "seat": seat,
                     "cards": engine_cards(rnd, seat), "bot": True, "decision": record}
            if event["cards"] != list(cards):
                event["attempted_cards"] = list(cards)
            events.append(event)
            out.append({"rnd": before, "seat": seat, "cards": list(cards), "record": record,
                        "worlds": list(drawn)})
        logs.append(events)
        game_seed += 1
    return bot, out, logs


@pytest.fixture(scope="module")
def arms(pinned_production_package, belief_package):
    env = served_env(pinned_production_package, belief_package)
    off_bot, off, _ = play_rounds(env, "0", MIN_DECISIONS)
    on_bot, on, logs = play_rounds(env, "1", MIN_DECISIONS)
    return {"off_bot": off_bot, "off": off, "on_bot": on_bot, "on": on, "logs": logs,
            "package": belief_package}


def _clock(key):
    return key.endswith(CLOCK_SUFFIXES)


def test_flag_changes_no_decision_draw_or_record_value(arms):
    off, on = arms["off"], arms["on"]
    assert len(off) == len(on) >= MIN_DECISIONS
    assert not arms["off_bot"].belief_log and arms["on_bot"].belief_log
    assert arms["off_bot"].policy_name == arms["on_bot"].policy_name
    assert arms["off_bot"].sampler.rng.getstate() == arms["on_bot"].sampler.rng.getstate()
    searched = 0
    for a, b in zip(off, on):
        assert a["cards"] == b["cards"]
        assert a["worlds"] == b["worlds"]
        ra, rb = a["record"], b["record"]
        if ra is None:
            assert rb is None
            continue
        searched += 1
        assert not set(ra) & LOG_KEYS
        assert set(rb) - set(ra) <= LOG_KEYS and "belief_log" in rb
        for key in ra:
            if not _clock(key):
                assert ra[key] == rb[key], key
        json.dumps(rb, allow_nan=False)
    assert searched >= MIN_DECISIONS * 0.9


def test_every_logged_draw_regenerates_exactly(arms):
    model = bn.load_belief_numpy(arms["package"]["path"], arms["package"]["sha256"])
    replayed = 0
    for d in arms["on"]:
        rec = d["record"]
        if rec is None or rec.get("schema") != pv.RECORD_SCHEMA:
            continue
        assert rec["belief_fallback"] == 0 and "belief_seed" in rec
        assert isinstance(rec["belief_seed"], int) and 0 <= rec["belief_seed"] < 2 ** 63
        propose, worlds, stats, fill = belief_debug.regenerate(
            model, copy.deepcopy(d["rnd"]), d["seat"], rec, rec["worlds"])
        assert bn.encode_snapshot(propose.P) == rec["belief_snapshot"]
        assert int(propose.drawn) == rec["belief_proposed"]
        assert stats["history_rejections"] == rec["history_rejections"]
        if fill == 0:
            assert [worlds] == d["worlds"]
            replayed += 1
    assert replayed >= MIN_DECISIONS * 0.9


def test_debug_tool_on_a_room_log(arms, tmp_path, capsys):
    path = tmp_path / "ROOM.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for events in arms["logs"] for e in events))
    listed = list(belief_debug.room_log_decisions(path))
    on = [d for d in arms["on"] if d["record"] is not None]
    assert len(listed) == len(on)
    model = bn.load_belief_numpy(arms["package"]["path"], arms["package"]["sha256"])
    for (round_no, ply, rnd, seat, rec), d in list(zip(listed, on))[:: max(1, len(on) // 12)]:
        assert seat == d["seat"] and rec == d["record"]
        result = belief_debug.report(rnd, seat, rec, model=model)
        assert result["snapshot_diff"] == 0 and all(result["checks"].values())
        if result["fill"] == 0:
            assert [result["worlds"]] == d["worlds"]
        assert 0.0 < result["truth"]["true_mass"] <= 1.0
    assert belief_debug.main(["--log", str(path), "--list"]) == 0
    round_no, ply = listed[5][:2]
    assert belief_debug.main(["--log", str(path), "--round", str(round_no), "--ply", str(ply),
                              "--belief-package", arms["package"]["path"]]) == 0
    out = capsys.readouterr().out
    assert "regenerated: snapshot max diff 0/255" in out and "p(true receiver)" in out


def test_trajectory_carries_the_fields(arms):
    from shengji.harvest.trajectory import pv_fields_from_record
    rec = next(d["record"] for d in arms["on"]
               if d["record"] and d["record"].get("schema") == pv.RECORD_SCHEMA)
    ballot = [list(a) for a in rec["admitted"]]
    _, _, av = pv_fields_from_record(rec, ballot)
    from shengji.harvest.trajectory import BELIEF_REPLAY_COUNTERS
    assert av["belief"] == {k: v for k, v in rec.items()
                            if k.startswith("belief_") or k in BELIEF_REPLAY_COUNTERS}
    assert {"history_rejections", "history_fallback_worlds"} <= set(av["belief"])
    assert {"belief_seed", "belief_snapshot", "belief_proposed"} <= set(av["belief"])
    bare = {k: v for k, v in rec.items() if not k.startswith("belief_")}
    assert "belief" not in pv_fields_from_record(bare, ballot)[2]


def test_a_failing_log_keeps_the_draw(belief_package, monkeypatch):
    from test_world_history_legal import fixture, served
    _, now, seat = fixture()
    model = bn.load_belief_numpy(belief_package["path"], belief_package["sha256"])

    def bot(flag):
        b = served(seed=7, world_history_legal=True, world_history_draw=True, belief_worlds=True,
                   belief_sha256=belief_package["sha256"])
        b.belief_model = model
        b.belief_log = flag
        return b
    quiet = bot(False)
    reference, _ = quiet._worlds(copy.deepcopy(now), seat)
    monkeypatch.setattr(bn, "log_fields",
                        lambda proposal: (_ for _ in ()).throw(RuntimeError("boom")))
    noisy = bot(True)
    worlds, _ = noisy._worlds(copy.deepcopy(now), seat)
    assert worlds == reference
    assert noisy.sampler.rng.getstate() == quiet.sampler.rng.getstate()
    stats = noisy._last_sampling
    assert stats["belief_fallback"] == 0 and stats["belief_log_error"] == "RuntimeError"
    assert "belief_seed" in stats and "belief_snapshot" not in stats


def test_xray_shows_the_summary_only(arms):
    from shengji.api.debug_play import play_analysis
    d = next(d for d in arms["on"]
             if d["record"] and d["record"].get("schema") == pv.RECORD_SCHEMA)
    bot = copy.copy(arms["on_bot"])
    bot.last_decision_record = d["record"]
    _, info = play_analysis(bot, d["cards"], is_attacker=True, elapsed=0.1)
    block = info["stages"]["belief"]
    assert set(block) == {"belief_fallback", "belief_proposed", "belief_ms",
                          "belief_entropy_bits", "belief_top_mass", "belief_hidden_copies"}
    assert "belief_seed" not in json.dumps(info) and "belief_snapshot" not in json.dumps(info)


def test_trajectory_shard_to_report(pinned_production_package, belief_package, tmp_path,
                                    monkeypatch):
    """The data-gen store end to end: the trajectory generator on the served
    belief recipe (serving budgets off: a data teacher has none) writes shard
    rows; for every searched row the shard report rebuilds the state,
    regenerates the draw from the logged seed and reproduces every logged
    counter (none absent), including rows whose history test rejected worlds."""
    from shengji.ai.registry import REGISTRY, register_pv_search_policies
    from shengji.harvest import trajectory
    from test_harvest_trajectory import _seed_windows
    env = served_env(pinned_production_package, belief_package)
    env.pop("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS")
    for key in [k for k in os.environ if k.startswith("SHENGJI_PV_")]:
        monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    names = register_pv_search_policies(**pv.pv_env_recipe())
    try:
        out = tmp_path / "run"
        trajectory.generate(rounds=2, seed0=4_310_000, out_dir=out, workers=1, policy=names[0],
                            merge=False, resume=False, seed_windows=_seed_windows(out),
                            explore_rate=0.0, explore_k=0)
    finally:
        for n in names:
            REGISTRY.pop(n, None)
    model = bn.load_belief_numpy(belief_package["path"], belief_package["sha256"])
    reports = rejected = 0
    for shard in sorted((out / "shards").glob("cluster-*.jsonl")):
        for line, raw in enumerate(shard.read_text().splitlines()):
            row = json.loads(raw)
            belief = (row.get("action_values") or {}).get("belief")
            if row["decision_kind"] != "play" or not belief:
                continue
            rnd, seat, fields = belief_debug.shard_decision(shard, line)
            assert fields["worlds"] == row["action_values"]["worlds"] == 64
            result = belief_debug.report(rnd, seat, fields, model=model)
            assert result["snapshot_diff"] == 0
            assert result["checks"] == {k: True for k in belief_debug.REPLAY_CHECKS}
            rejected += fields["history_rejections"] > 0
            reports += 1
    assert reports >= 50 and rejected >= 5
