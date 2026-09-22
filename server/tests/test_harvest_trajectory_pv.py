"""The trajectory generator over the pv-search bot (#592 step 2): records carry the
admitted ballot with played_index mapped through admitted_indices, the value head's means
as acting-team action values in their own units, the exploration draw is scored and priced,
explore 0 reproduces the served bot's decisions, a rerun is byte-identical, and the policy
rows extractor reads the means.  Budgeted (serving) recipes are refused as data teachers."""
import json
import random

import pytest

from shengji.ai.registry import REGISTRY, register_pv_search_policies
from shengji.harvest import trajectory
from shengji.harvest.common import action_key
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_bury_policy import CWVBuryConfig
from shengji.train.cwv_data import search_means
from test_harvest_trajectory import _read_dir, _seed_windows, _structural  # noqa: F401
from test_pv_search_serving import package  # noqa: F401

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
BURY = CWVBuryConfig(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)
SEED0 = 4_300_000


@pytest.fixture
def data_policy(package, monkeypatch):
    """The served recipe WITHOUT serving budgets (the data teacher), registered in this
    process and exported through SHENGJI_PV_* so a spawned worker registers the same name."""
    path, sha = package
    from dataclasses import asdict
    for key, value in dict(CKPT=path, SHA256=sha, BURY_ARM="hybrid", **{k.upper(): v for k, v in SMALL.items()},
                           **{"BURY_" + k.upper(): v for k, v in asdict(BURY).items()}).items():
        monkeypatch.setenv("SHENGJI_PV_" + key, str(value))
    monkeypatch.delenv("SHENGJI_PV_SERVING_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS", raising=False)
    names = register_pv_search_policies(**pv.pv_env_recipe())
    try:
        yield names[0]
    finally:
        for n in names:
            REGISTRY.pop(n, None)


def _gen(out, policy, **opt):
    trajectory.generate(rounds=2, seed0=SEED0, out_dir=out, workers=1, policy=policy, merge=True,
                        resume=False, seed_windows=_seed_windows(out), **opt)
    return _read_dir(out)


def test_pv_records_carry_the_admitted_ballot_and_priced_values(data_policy, tmp_path):
    run = _gen(tmp_path / "pv0", data_policy, explore_rate=0.0, explore_k=0)
    plays = [r for r in run["records"] if r["decision_kind"] == "play"]
    assert plays and run["manifest"]["config"]["policy_flags"]["search"] == "pv-search"
    assert run["manifest"]["config"]["policy_flags"]["value_units"] == trajectory.PV_VALUE_UNITS
    assert run["manifest"]["config"]["trajectory_class"].startswith("PVTrajectory_")
    searched = [r for r in plays if r["allocation"]["searched"]]
    assert searched
    for r in searched:
        k = len(r["ballot"])
        assert 1 <= k <= SMALL["candidates"] and r.get("production_ballot") is None
        assert r["allocation"]["selection_worlds"] == [SMALL["worlds"]] * k
        assert action_key(r["ballot"][r["allocation"]["played_index"]]) == action_key(r["action"])
        av = r["action_values"]
        assert av["units"] == trajectory.PV_VALUE_UNITS and av["perspective"] == "acting-team"
        assert len(av["means"]) == k == len(av["policy_log_odds"]) and av["eligible_indices"] == list(range(k))
        assert r["preference"]["tau"] is None and len(r["preference"]["means"]) == k
        assert r["legal_actions_count"] >= len(r["legal_actions"])
        got = search_means(r)
        assert (got is None) == (k < 2)
    buries = [r for r in run["records"] if r["decision_kind"] == "bury"]
    assert buries and all(r["allocation"]["searched"] for r in buries)


def test_explore_zero_is_the_served_bot_and_a_rerun_is_byte_identical(data_policy, tmp_path):
    a = _gen(tmp_path / "a", data_policy, explore_rate=0.0, explore_k=0)
    b = _gen(tmp_path / "b", data_policy, explore_rate=0.0, explore_k=0)
    assert a["bytes"] == b["bytes"]
    # the served bot at the same seat seed makes the same first play on the same deal
    from shengji.ai.registry import make_bot
    from shengji.engine.game import Game
    seed = SEED0
    bots = [make_bot(data_policy, seed=s) for s in trajectory.mirror_seat_seeds(seed, 0)]
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    first = [r for r in a["records"] if r["decision_kind"] == "play" and r["round_seed"] == seed
             and r["source_ref"].split(":")[2] == "0" and r["ply"] == 0][0]
    assert action_key(bots[rnd.turn].decide_play(rnd, rnd.turn)) == action_key(first["action"])
    assert first["seat"] == rnd.turn


def test_the_exploration_draw_is_scored_priced_and_recorded(data_policy, tmp_path):
    run = _gen(tmp_path / "x", data_policy, explore_rate=1.0, explore_k=2)
    plays = [r for r in run["records"] if r["decision_kind"] == "play" and r["allocation"]["searched"]]
    drawn = [r for r in plays if r.get("exploration") is not None]
    fired = [r for r in drawn if r["exploration"]["added"]]
    assert fired, "with explore_rate 1.0 some decision must draw an off-ballot candidate"
    for r in fired:
        added = {action_key(a) for a in r["exploration"]["added"]}
        keys = [action_key(a) for a in r["ballot"]]
        assert added <= set(keys)                                  # the draw is in the ballot ...
        assert r["production_ballot"] is not None                  # ... and production's list is stamped
        assert len(r["action_values"]["means"]) == len(keys)       # ... and priced
        assert set(keys) - {action_key(a) for a in r["production_ballot"]} == added - set(action_key(a) for a in r["production_ballot"])
    assert run["manifest"]["counts"]["explore_fired"] == len(drawn)   # a draw with an empty pool still fired


def test_budgeted_serving_recipes_and_knobs_are_refused(package, tmp_path, monkeypatch):
    path, sha = package
    names = register_pv_search_policies(path, sha256=sha, serving_budget_seconds=3, **SMALL)
    try:
        with pytest.raises(trajectory.TrajectoryError, match="serving-fallback"):
            trajectory.build_config(policy=names[0], seed0=SEED0)
    finally:
        for n in names:
            REGISTRY.pop(n, None)


def test_data_policy_refuses_knobs_and_work_overrides(data_policy):
    with pytest.raises(trajectory.TrajectoryError, match="pv-search data policy"):
        trajectory.build_config(policy=data_policy, seed0=SEED0, select_worlds=2)
    with pytest.raises(trajectory.TrajectoryError, match="pv-search data policy"):
        trajectory.build_config(policy=data_policy, seed0=SEED0, knobs=["TRACTOR_LOCK=0"])


def test_policy_rows_extract_reads_the_pv_means(data_policy, tmp_path):
    run = _gen(tmp_path / "rows", data_policy, explore_rate=0.0, explore_k=0)
    from shengji.train import policy_prior
    out = tmp_path / "rows"                                    # file mode: rows.npz + rows.meta.jsonl
    rc = policy_prior.main(["extract", "--out", str(out), "--data", str(run["out"]), "--workers", "1",
                            "--thin", "1.0", "--lo", "0.0", "--hi", "1.0"])
    assert rc in (0, None)
    meta = tmp_path / "rows.meta.jsonl"
    assert meta.exists(), sorted(p.name for p in tmp_path.iterdir())
    rows = [json.loads(l) for l in meta.read_text().splitlines() if l.strip()]
    with_means = [r for r in rows if isinstance(r.get("means"), list) and any(v is not None and v == v for v in r["means"])]
    assert with_means, "no policy row carries the search's means"
