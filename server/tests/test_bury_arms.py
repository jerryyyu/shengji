"""The value-only, MC-on-all and wider-finalist bury arms, and the paired bury
screen with pv-search play.

Witnesses: arm selection fails closed and ``mc_all`` is ``mc``; the served name is
unchanged and every new arm registers under its own name; ``value`` plays the value
head's top-ranked candidate with no rollouts; ``mc`` rolls every candidate under the
incumbent margin; the finalist count is respected; a budget expiry returns the
incumbent with the receipt fields for each arm; the screen replays one deal with
identical play seeds, so an identical bury gives an identical round.
"""
import copy
import json
import random
import tomllib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.ai import registry
from shengji.ai.mcbot import MCBot
from shengji.ai.smart import SmartBot
from shengji.api import debug
from shengji.engine.cards import RANKS
from shengji.train import cwv_bury_policy as policy
from shengji.train import cwv_bury_screen as screen
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state
from test_bury_fly_config import RELEASE38, SERVED_PV_SHA
from test_cwv_bury_policy import _Evaluator, _Helper, _bury_state
from test_cwv_bury_serving import Evaluator
from test_pv_search_serving import package  # noqa: F401

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
BURY = dict(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)


def _fly_env():
    return tomllib.loads((Path(__file__).parents[2] / "fly.toml").read_text())["env"]


def _names(monkeypatch, **overrides):
    from shengji.ai import cwv_policy
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: SERVED_PV_SHA[:8])
    env = {**_fly_env(), **overrides}
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_arm_selection_fails_closed_and_mc_all_is_mc(monkeypatch):
    assert policy.canonical_arm("mc_all") == policy.canonical_arm("mc") == "mc"
    assert policy.canonical_arm("value") == "value"
    for bad in ("", "model", "hybrid-8", "mc-all", None):
        with pytest.raises(policy.BuryPolicyError, match="^unknown bury arm"):
            policy.canonical_arm(bad)
    env = _fly_env()
    assert pv.pv_env_recipe({**env, "SHENGJI_PV_BURY_ARM": "mc_all"})["bury_arm"] == "mc"
    assert pv.pv_env_recipe({**env, "SHENGJI_PV_BURY_ARM": "value"})["bury_arm"] == "value"
    wide = pv.pv_env_recipe({**env, "SHENGJI_PV_BURY_ALTERNATIVES": "8"})
    assert wide["bury_arm"] == "hybrid" and wide["bury_config"].alternatives == 8
    with pytest.raises(pv.PVSearchPolicyError, match="^unknown bury arm 'valu'$"):
        pv.pv_env_recipe({**env, "SHENGJI_PV_BURY_ARM": "valu"})
    # Registration itself refuses: nothing is registered under a guessed arm.
    for key, value in {**env, "SHENGJI_PV_BURY_ARM": "valu"}.items():
        if key.startswith("SHENGJI_PV_"):
            monkeypatch.setenv(key, value)
    before = set(registry.REGISTRY)
    with pytest.raises(pv.PVSearchPolicyError, match="^unknown bury arm 'valu'$"):
        registry._register_pv_search_from_env()
    assert set(registry.REGISTRY) == before
    # Below the environment boundary only identities are accepted.
    with pytest.raises(policy.BuryPolicyError, match="^unknown bury arm 'mc_all'$"):
        policy.CWVBuryBot(_Evaluator(), arm="mc_all")


def test_served_name_is_unchanged_and_each_arm_has_its_own(monkeypatch):
    assert _names(monkeypatch) == [RELEASE38]
    assert _names(monkeypatch, SHENGJI_PV_BURY_ALTERNATIVES="4") == [RELEASE38]
    play = RELEASE38[:RELEASE38.index("-bury-")]
    arms = {
        "value": dict(SHENGJI_PV_BURY_ARM="value"),
        "mc_all": dict(SHENGJI_PV_BURY_ARM="mc_all"),
        "hybrid-8": dict(SHENGJI_PV_BURY_ALTERNATIVES="8"),
        "hybrid-16": dict(SHENGJI_PV_BURY_ALTERNATIVES="16"),
    }
    names = {label: _names(monkeypatch, **env)[0] for label, env in arms.items()}
    assert names == {
        "value": play + "-bury-value-ca98e87724cf",
        "mc_all": play + "-bury-mc-cc4d2fdd0e22",
        "hybrid-8": play + "-bury-hybrid-a267d2fa10fe",
        "hybrid-16": play + "-bury-hybrid-18e6d99b596d",
    }
    assert len({RELEASE38, *names.values()}) == 5
    assert names["mc_all"] == _names(monkeypatch, SHENGJI_PV_BURY_ARM="mc")[0]


def _stub(monkeypatch, rnd, extra, means, roll=None):
    """Stubbed ballot, worlds and value ranking; ``roll`` is the MC stage."""
    incumbent = list(SmartBot().decide_bury(rnd, rnd.banker))
    hand = rnd.hands[rnd.banker]
    candidates = [incumbent] + [list(hand[i:i + 8]) for i in range(1, extra + 1)]
    monkeypatch.setattr(policy, "bury_candidates", lambda _rnd, _bot: copy.deepcopy(candidates))
    monkeypatch.setattr(policy, "make_bot", lambda _name, *, seed: _Helper(seed))
    monkeypatch.setattr(policy, "sample_worlds",
                        lambda bot, _rnd, _seat, n: ([("w",)] * n, n))
    monkeypatch.setattr(policy, "score_bury_candidates", lambda _rnd, local, worlds, *_a, **_k:
                        np.repeat(np.asarray([means], dtype=float), len(worlds), axis=0))

    def refuse(*_args, **_kwargs):
        raise AssertionError("this arm must not roll out")

    monkeypatch.setattr(policy, "rollout_bury_values", refuse if roll is None else roll)
    return candidates


def test_value_plays_the_top_value_ranked_candidate_without_rollouts(monkeypatch):
    rnd = _bury_state(9)
    candidates = _stub(monkeypatch, rnd, 5, [0, 1, 9, 2, 3, 4])
    bot = policy.make_cwv_bury_bot(_Evaluator(), seed=13, arm="value")
    assert bot.decide_bury(rnd, rnd.banker) == candidates[2]
    record = bot.last_bury_record
    assert record["arm"] == "value" and record["picked_index"] == 2
    assert record["model_means"] == [0, 1, 9, 2, 3, 4]
    assert record["mc_evidence"] is None and record["mc_rollouts"] == 0
    assert (record["candidate_count"], record["finalist_count"]) == (6, 0)
    assert record["fallback_reason"] is None
    assert record["model_worlds"] == 32 and record["selection_worlds"] == 0
    assert record["model_positions"] == 6 * 32
    # A ranking is not an MC value label: the data writer refuses it.
    with pytest.raises(policy.BuryPolicyError, match="^searched bury is missing MC evidence$"):
        policy.trajectory_bury_record(record)
    # No margin: any lead over the incumbent is played; an exact tie keeps it.
    _stub(monkeypatch, rnd, 5, [0, 1e-9, 0, 0, 0, 0])
    bot.decide_bury(rnd, rnd.banker)
    assert bot.last_bury_record["picked_index"] == 1
    _stub(monkeypatch, rnd, 5, [3, 3, 3, 3, 3, 3])
    assert bot.decide_bury(rnd, rnd.banker) == candidates[0]


@pytest.mark.parametrize("gain, picked", [(4, 0), (5, 3), (6, 3)])
def test_mc_all_rolls_every_candidate_and_respects_the_margin(monkeypatch, gain, picked):
    rnd = _bury_state(9)
    seen = {}

    def roll(_rnd, local, worlds, _bot):
        seen["local"] = [list(c) for c in local]
        points = np.full((len(worlds), len(local)), 60, dtype=np.int64)
        points[:, 3] = 60 - gain          # attacker points: lower is better for the banker
        return np.zeros(points.shape), points

    candidates = _stub(monkeypatch, rnd, 6, [0] * 7, roll)
    monkeypatch.setattr(_Helper, "MARGIN", 5.0)
    bot = policy.make_cwv_bury_bot(_Evaluator(), seed=13, arm=policy.canonical_arm("mc_all"))
    assert bot.decide_bury(rnd, rnd.banker) == candidates[picked]
    assert seen["local"] == candidates
    record = bot.last_bury_record
    assert record["arm"] == "mc" and record["model_means"] is None
    assert (record["candidate_count"], record["finalist_count"]) == (7, 7)
    assert record["mc_rollouts"] == 7 * 32
    assert record["mc_evidence"]["candidate_indices"] == list(range(7))
    assert record["mc_evidence"]["incumbent_margin"] == 5.0


@pytest.mark.parametrize("alternatives", [4, 8, 16])
def test_hybrid_finalist_count_is_respected(monkeypatch, alternatives):
    rnd = _bury_state(9)
    seen = {}

    def roll(_rnd, local, worlds, _bot):
        seen["local"] = len(local)
        shape = (len(worlds), len(local))
        return np.zeros(shape), np.zeros(shape, dtype=np.int64)

    _stub(monkeypatch, rnd, 11, list(range(12)), roll)
    bot = policy.make_cwv_bury_bot(
        _Evaluator(), seed=13, arm="hybrid",
        bury_config=policy.CWVBuryConfig(alternatives=alternatives))
    bot.decide_bury(rnd, rnd.banker)
    record = bot.last_bury_record
    finalists = min(alternatives, 11) + 1          # the incumbent is always rolled
    assert seen["local"] == record["finalist_count"] == len(record["shortlist"]) == finalists
    assert record["shortlist"] == [0] + list(range(12 - finalists + 1, 12))
    assert record["candidate_count"] == 12 and record["mc_rollouts"] == finalists * 32


@pytest.mark.parametrize("arm, alternatives, where, finalists, rolled", [
    ("value", 2, "model", None, 0),
    ("mc", 2, "rollout", "all", 2),
    ("hybrid", 2, "rollout", 3, 2),
    ("hybrid", 4, "rollout", 5, 2),
])
def test_budget_expiry_falls_back_with_the_receipt(monkeypatch, arm, alternatives, where,
                                                   finalists, rolled):
    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(policy, "time", SimpleNamespace(perf_counter=lambda: clock.value))
    rollout = MCBot._rollout_from_bury
    count = [0]

    def timed_rollout(self, *args, **kwargs):
        result = rollout(self, *args, **kwargs)
        count[0] += 1
        if count[0] == 3:                 # the third rollout runs past the deadline
            clock.value = 2.0
        return result

    class TimedEvaluator(Evaluator):
        def score(self, positions, seat, **kwargs):
            if where == "model":
                clock.value = 2.0
            return super().score(positions, seat, **kwargs)

    monkeypatch.setattr(MCBot, "_rollout_from_bury", timed_rollout)
    rnd = reopen_state(capture_state(65))
    player = policy.CWVBuryBot(
        TimedEvaluator(), seed=73, arm=arm, serving_budget_seconds=1.0,
        bury_config=policy.CWVBuryConfig(max_candidates=6, model_worlds=2,
                                         selection_worlds=2, alternatives=alternatives))
    before = player.rng.getstate()
    assert player.decide_bury(rnd, rnd.banker) == SmartBot().decide_bury(rnd, rnd.banker)
    assert player.rng.getstate() == before and rnd.phase == "bury"
    record = player.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1" and record["arm"] == arm
    assert record["reason"] == record["fallback_reason"] == "budget"
    assert record["work_complete"] is False and record["elapsed_seconds"] == 2.0
    assert record["candidate_count"] == 6
    assert record["finalist_count"] == (6 if finalists == "all" else finalists)
    # Only rollouts that finished inside the budget are counted.
    assert record["mc_rollouts"] == rolled and count[0] == (0 if arm == "value" else 3)
    assert "mc_evidence" not in record


def test_search_error_fallback_and_complete_receipts_carry_the_fields():
    class FailingEvaluator(Evaluator):
        def score(self, *args, **kwargs):
            raise RuntimeError("boom")

    rnd = reopen_state(capture_state(65))
    config = policy.CWVBuryConfig(max_candidates=6, model_worlds=2, selection_worlds=2,
                                  alternatives=2)
    failed = policy.CWVBuryBot(FailingEvaluator(), seed=73, arm="value", bury_config=config,
                               serving_budget_seconds=30.0)
    assert failed.decide_bury(rnd, rnd.banker) == SmartBot().decide_bury(rnd, rnd.banker)
    record = failed.last_bury_record
    assert record["fallback_reason"] == "search-error" and record["error_class"] == "RuntimeError"
    assert (record["candidate_count"], record["finalist_count"], record["mc_rollouts"]) == (6, None, 0)
    for arm, finalists in (("heuristic", 0), ("value", 0), ("mc", 6), ("hybrid", 3)):
        player = policy.CWVBuryBot(Evaluator(), seed=73, arm=arm, bury_config=config,
                                   serving_budget_seconds=30.0)
        player.decide_bury(rnd, rnd.banker)
        record = player.last_bury_record
        assert record["schema"] == "cwv-bury-policy-v1" and record["arm"] == arm
        assert record["fallback_reason"] is None and record["elapsed_seconds"] >= 0
        assert record["candidate_count"] == len(record["candidates"]) == (1 if arm == "heuristic" else 6)
        assert record["finalist_count"] == finalists
        assert record["mc_rollouts"] == finalists * 2


def test_value_arm_xray_shows_the_ranked_pool_without_mc_columns():
    rnd = reopen_state(capture_state(65))
    player = policy.CWVBuryBot(
        Evaluator(), seed=73, arm="value",
        bury_config=policy.CWVBuryConfig(max_candidates=6, model_worlds=2,
                                         selection_worlds=2, alternatives=2))
    view = debug._bury_xray(rnd, rnd.banker, player)
    assert view["mode"] == "value" and view["fallback"] is False
    assert view["reason"] == "value-head-top-ranked" and view["margin"] is None
    assert len(view["candidates"]) == 6 and view["work"]["candidate_rollouts"] == 0
    assert all(row["banker_avg"] is None and row["worlds"] == 0 for row in view["candidates"])
    assert sum(row["bot_buries"] for row in view["candidates"]) == 1


def test_arm_specs_and_release_38_play_recipe():
    assert screen.arm_recipe("mc_all") == screen.arm_recipe("mc")
    assert screen.arm_recipe("mc")["arm"] == "mc"
    assert screen.arm_recipe("hybrid") == screen.arm_recipe("hybrid-4") == {
        "arm": "hybrid", "bury_config": dict(max_candidates=32, model_worlds=32,
                                             selection_worlds=32, alternatives=4)}
    assert screen.arm_recipe("hybrid-8")["bury_config"]["alternatives"] == 8
    assert screen.arm_recipe("value")["arm"] == "value"
    for bad in ("value-8", "hybrid-x", "hybrid-", "hybrid-0", "hybrid-32", "model", ""):
        with pytest.raises(ValueError):
            screen.arm_recipe(bad)
    # The screen's card play is the served recipe, minus the package and the budgets.
    served = pv.pv_env_recipe(_fly_env())
    for key in ("checkpoint", "sha256", "serving_budget_seconds", "bury_arm", "bury_config",
                "bury_serving_budget_seconds"):
        served.pop(key)
    assert served == screen.PV_PLAY


def _pv_config(tmp_path, package, arms):
    path, sha = package
    return {"output": str(tmp_path), "checkpoint": path, "checkpoint_sha256": sha,
            "config_sha256": "pv", "deals": 1, "start_index": 1040,
            "population": screen.ALLRANK_POPULATION, "namespace": screen.ALLRANK_NAMESPACE,
            "play": "pv-search", "pv_play": SMALL, "bury_budget_seconds": None,
            "control": "hybrid",
            "arm_recipes": {label: {"arm": arm, "bury_config": BURY} for label, arm in arms}}


def test_pv_search_screen_pairs_one_deal_and_identical_bury_is_identical_play(tmp_path, package):
    """Control vs the same recipe under a second label: the same deal, bury, transcript
    and outcome.  Every arm plays the served bot class with the same four play seeds."""
    config = _pv_config(tmp_path, package, [("hybrid", "hybrid"), ("hybrid-again", "hybrid"),
                                            ("value", "value"), ("mc_all", "mc")])
    seeds = []
    entry = screen.pv_arm_entry

    def recording(config_, recipe):
        name, factory = entry(config_, recipe)

        def build(*, seed):
            seeds.append((recipe["arm"], seed))
            bot = factory(seed=seed)
            assert isinstance(bot, pv.PVSearchBuryBot) and bot.bury_arm == recipe["arm"]
            assert bot.serving_budget_seconds is None       # no wall-clock play fallback
            return bot
        return name, build

    screen.pv_arm_entry = recording
    try:
        shard = screen.run_cluster(config, 3)
    finally:
        screen.pv_arm_entry = entry
    records = {r["arm"]: r for r in shard["records"]}
    assert list(records) == ["hybrid", "hybrid-again", "value", "mc_all"]
    expected = [screen.derived_seed(f"{screen.ALLRANK_NAMESPACE}:play:1043", seat)
                for seat in range(4)]
    assert [seed for _, seed in seeds] == expected * 4
    control, again = records["hybrid"], records["hybrid-again"]
    assert all(r["state"] == control["state"] and r["state"]["index"] == 1043
               for r in records.values())
    assert control["policy"] == again["policy"] and "-bury-hybrid-" in control["policy"]
    assert "-bury-value-" in records["value"]["policy"]
    assert "-bury-mc-" in records["mc_all"]["policy"]
    for key in ("buried", "transcript", "attacker_points", "kitty_bonus", "banker_utility",
                "model_unit_utility", "work"):
        assert control[key] == again[key]
    assert control["bury"]["picked_index"] == again["bury"]["picked_index"]
    assert len(control["transcript"]) > 0 and control["bury"]["arm"] == "hybrid"
    assert records["value"]["bury"]["mc_rollouts"] == 0
    assert records["mc_all"]["bury"]["finalist_count"] == records["mc_all"]["bury"]["candidate_count"]
    # The bury is the only difference: the same bury under another arm is the same round.
    for record in records.values():
        if sorted(record["buried"]) == sorted(control["buried"]):
            assert record["transcript"] == control["transcript"]
            assert record["attacker_points"] == control["attacker_points"]
    assert screen.run_cluster(config, 3) == shard            # completed arms are not replayed


def _shard(cluster, rows):
    rank, banker = RANKS[cluster % 13], cluster // 13
    state = {"setup": {"trump_rank": rank, "trump_suit": "S", "trump_is_nt": False},
             "initial_banker": banker}
    return {"cluster": cluster, "records": [{"state": state, **row} for row in rows]}


INCUMBENT = ["S2", "S3", "S4", "S6", "S7", "S8", "S9", "SJ"]


def _row(arm, buried, points, kitty, bury):
    return {"arm": arm, "buried": buried, "attacker_points": points,
            "banker_won": int(points < 80), "banker_utility": screen.banker_utility(points),
            "model_unit_utility": 1.0 if points < 80 else -1.0, "kitty_bonus": kitty,
            "transcript": [min(buried)], "wall_seconds": 2.0, "cpu_seconds": 2.0, "bury": bury}


def _done(seconds, finalists):
    return {"elapsed_seconds": seconds, "candidates": [INCUMBENT] * 6, "candidate_count": 6,
            "finalist_count": finalists, "mc_rollouts": finalists * 32, "fallback_reason": None}


def test_control_summary_is_zero_for_control_vs_control_and_reports_each_arm():
    incumbent, row, done = INCUMBENT, _row, _done
    alternative = ["H5", "HK", "H4", "H6", "H7", "H8", "H9", "HJ"]
    expired = {"elapsed_seconds": 2.0, "candidate_count": 6, "finalist_count": 6,
               "mc_rollouts": 40, "fallback_reason": "budget"}
    shards = []
    for cluster in range(52):
        worse = cluster < 13                       # the value arm concedes the kitty here
        shards.append(_shard(cluster, [
            row("hybrid", incumbent, 40, 0, done(1.0, 5)),
            row("hybrid-4", list(reversed(incumbent)), 40, 0, done(1.0, 5)),
            row("value", alternative, 120 if worse else 40, 80 if worse else 0, done(0.5, 0)),
            row("mc_all", incumbent, 40, 0, expired if cluster % 2 else done(3.0, 6)),
        ]))
    labels = ("hybrid", "hybrid-4", "value", "mc_all")
    config = {"deals": 52, "population": screen.ALLRANK_POPULATION, "control": "hybrid",
              "bury_budget_seconds": 2.0,
              "arm_recipes": {label: screen.arm_recipe(label) for label in labels},
              "policies": {label: f"policy-{label}" for label in labels}}
    result = screen.summarize(shards, config)
    assert sorted(result["comparisons"]) == [
        "hybrid-4_minus_hybrid", "mc_all_minus_hybrid", "value_minus_hybrid"]
    null = result["comparisons"]["hybrid-4_minus_hybrid"]
    for metric in ("utility", "model_unit_utility", "banker_win_rate_difference",
                   "attacker_points", "kitty_bonus", "buried_points_delta"):
        assert null[metric]["mean"] == 0 and null[metric]["ci95"] == [0.0, 0.0]
    assert null["different_bury_deals"] == 0 and null["different_bury_fraction"] == 0
    assert null["same_bury_transcript_mismatch_count"] == 0
    value = result["comparisons"]["value_minus_hybrid"]
    assert value["different_bury_fraction"] == 1 and value["different_bury_deals"] == 52
    assert value["utility"]["mean"] == pytest.approx(-2 * 13 / 52)
    assert value["utility"]["n_independent_states"] == 52
    assert "strata" in value["utility"]["resampling"]          # the screen's own bootstrap
    assert value["model_unit_utility"]["mean"] == pytest.approx(-2 * 13 / 52)
    assert value["buried_points_delta"]["mean"] == 15
    assert value["kitty_ge80_difference"]["mean"] == pytest.approx(13 / 52)
    cost = result["cost"]
    assert cost["value"]["mean_buried_points"] == 15 and cost["hybrid"]["mean_buried_points"] == 0
    assert cost["value"]["mean_kitty_bonus"] == 20 and cost["value"]["kitty_ge80_count"] == 13
    assert cost["value"]["kitty_nonzero_count"] == 13
    assert cost["value"]["bury_latency_p50_seconds"] == 0.5
    assert cost["mc_all"]["bury_latency_p95_seconds"] == 3.0
    assert cost["mc_all"]["fallback_counts"] == {"budget": 26} and cost["mc_all"]["fallback_count"] == 26
    assert cost["hybrid"]["fallback_counts"] == {} and cost["hybrid"]["mean_finalist_count"] == 5
    assert cost["mc_all"]["full_bury_rollouts"] == 26 * 40 + 26 * 6 * 32
    report = screen.arm_report(result, config, "value")
    assert report["vs_control"] is value and report["cost"] is cost["value"]
    assert report["policy"] == "policy-value" and report["control"] == "hybrid"
    assert screen.arm_report(result, config, "hybrid")["vs_control"] is None


def test_pv_search_cli_binds_arms_and_refuses_an_existing_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    monkeypatch.setattr(screen, "execution_source_identity", lambda *_a: {})
    monkeypatch.setattr(screen, "pv_arm_entry", lambda config, recipe: (
        f"pv-{recipe['arm']}-{recipe['bury_config']['alternatives']}"
        f"-{config['bury_budget_seconds']}", None))
    observed = []
    monkeypatch.setattr(screen, "_run_pending", lambda config, pending, *_a, **_k:
                        observed.append((config, pending)))
    out = tmp_path / "run"
    base = ["--checkpoint", "unused", "--population", screen.ALLRANK_POPULATION,
            "--play", "pv-search", "--deals", "520", "--start-index", "1040"]
    arms = ["--arms", "value,mc_all,hybrid-8"]
    screen.main(base + arms + ["--out", str(out)])
    config, pending = observed[0]
    assert pending == list(range(520)) and config["start_index"] == 1040
    assert list(config["arm_recipes"]) == ["hybrid", "value", "mc_all", "hybrid-8"]
    assert config["control"] == "hybrid" and config["bury_budget_seconds"] == 2.0
    assert config["pv_play"] == screen.PV_PLAY and config["play"] == "pv-search"
    assert "w32" not in config and "bury" not in config
    assert config["policies"] == {"hybrid": "pv-hybrid-4-2.0", "value": "pv-value-4-2.0",
                                  "mc_all": "pv-mc-4-2.0", "hybrid-8": "pv-hybrid-8-2.0"}
    assert json.loads((out / "config.json").read_text()) == config
    with pytest.raises(SystemExit):                       # the directory now exists
        screen.main(base + arms + ["--out", str(out)])
    screen.main(base + arms + ["--out", str(out), "--resume"])
    assert observed[1] == observed[0]
    screen.main(base + ["--arms", "hybrid-4", "--control", "hybrid", "--bury-budget-seconds",
                        "none", "--out", str(tmp_path / "null")])
    assert observed[2][0]["bury_budget_seconds"] is None
    assert list(observed[2][0]["arm_recipes"]) == ["hybrid", "hybrid-4"]
    assert not (tmp_path / "null" / "summary.json").exists()      # nothing completed
    fresh = iter(range(100))
    for bad in (base + ["--arms", "valu"], base + ["--arms", "hybrid"], base,
                base + ["--arms", "value,value"], base + arms + ["--control", "best"],
                base + arms + ["--bury-budget-seconds", "0"],
                base[:-2] + arms, base + arms + ["--scaling"],
                ["--checkpoint", "unused", "--play", "pv-search", "--start-index", "1040"] + arms,
                ["--checkpoint", "unused"] + arms, ["--checkpoint", "unused", "--resume"]):
        with pytest.raises(SystemExit):
            screen.main(bad + ["--out", str(tmp_path / f"bad{next(fresh)}")])
    assert len(observed) == 3


def test_pv_search_cli_writes_one_report_per_arm_and_a_summary(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(screen, "shared_evaluator",
                        lambda *_a, **_k: SimpleNamespace(checkpoint_sha256="test"))
    monkeypatch.setattr(screen, "execution_source_identity", lambda *_a: {})
    monkeypatch.setattr(screen, "pv_arm_entry", lambda config, recipe: ("pv-" + recipe["arm"], None))

    def run(config, pending, shards, **_kwargs):
        shards.extend(_shard(cluster, [_row(arm, INCUMBENT, 40, 0, _done(1.0, 5))
                                       for arm in config["arm_recipes"]])
                      for cluster in pending)

    monkeypatch.setattr(screen, "_run_pending", run)
    out = tmp_path / "run"
    screen.main(["--checkpoint", "unused", "--population", screen.ALLRANK_POPULATION,
                 "--play", "pv-search", "--deals", "52", "--start-index", "1040",
                 "--arms", "hybrid-4,value", "--out", str(out)])
    capsys.readouterr()
    assert sorted(p.name for p in out.iterdir()) == [
        "config.json", "report-hybrid-4.json", "report-hybrid.json", "report-value.json",
        "summary.json"]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["complete"] and summary["control"] == "hybrid"
    assert summary["bury_budget_seconds"] == 2.0 and summary["comparisons_are_exploratory"]
    for arm in ("hybrid-4", "value"):
        report = json.loads((out / f"report-{arm}.json").read_text())
        assert report["vs_control"] == summary["comparisons"][f"{arm}_minus_hybrid"]
        assert report["vs_control"]["utility"]["mean"] == 0
        assert report["vs_control"]["utility"]["ci95"] == [0.0, 0.0]
        assert report["cost"] == summary["cost"][arm] and report["completed_deals"] == 52
    assert json.loads((out / "report-hybrid.json").read_text())["vs_control"] is None
