import json
from types import SimpleNamespace

import pytest

from shengji.ai.smart import SmartBot
from shengji.train import declare_conditional as conditional
from shengji.train import declare_screen as screen


def test_selection_is_outcome_blind_and_has_changed_and_unchanged_witnesses(monkeypatch):
    def forbidden(*args):
        raise AssertionError("selection cannot construct play bots or score outcomes")
    monkeypatch.setattr(screen, "make_bots", forbidden)
    monkeypatch.setattr(screen, "finish_round", forbidden)
    plan = conditional.selection_plan(53, 53)
    assert plan["population_deal_teams"] == 106
    assert [(r["spec"]["index"], [p["team"] for p in r["pairs"]]) for r in plan["selected"]] == [
        (80, [0]), (83, [0]), (104, [0])]
    assert all(p["states"]["baseline"] != p["states"]["pair-eager"]
               for r in plan["selected"] for p in r["pairs"])


def test_conditional_real_gameplay_recovers_completed_arm(tmp_path, monkeypatch):
    plan = conditional.selection_plan(80, 1)
    config = {"output": str(tmp_path), "selection": plan, "mode": "play", "config_sha256": "test"}
    monkeypatch.setattr(screen, "make_bots", lambda *_: [SmartBot() for _ in range(4)])
    original = screen.finish_round
    calls = []
    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("after completed baseline")
        return original(*args)
    monkeypatch.setattr(screen, "finish_round", fail_second)
    with pytest.raises(RuntimeError, match="^after completed baseline$"):
        conditional.run_cluster(config, 0)
    baseline = tmp_path/"arm-00000-0-baseline.json"
    before = baseline.read_bytes()
    monkeypatch.setattr(screen, "finish_round", original)
    result = conditional.run_cluster(config, 0)
    assert len(result["records"]) == 2
    assert baseline.read_bytes() == before
    assert all(r["outcome"]["transcript"] for r in result["records"])
    summary = conditional.summarize([result], config)
    assert summary["complete"] and summary["completed_independent_deals"] == 1
    b, t = result["records"]
    assert summary["comparisons"]["focal_signed_levels"]["mean"] == (
        t["outcome"]["focal_signed_levels"]-b["outcome"]["focal_signed_levels"])
    assert conditional.run_cluster(config, 0) == result


def test_conditional_selection_drift_refuses_before_play(tmp_path, monkeypatch):
    plan = conditional.selection_plan(80, 1)
    plan["selected"][0]["pairs"][0]["states"]["baseline"]["banker"] = 99
    monkeypatch.setattr(screen, "make_bots", lambda *_: pytest.fail("must refuse before gameplay"))
    with pytest.raises(ValueError, match="^conditional selection changed before gameplay$"):
        conditional.run_cluster({"output": str(tmp_path), "selection": plan,
                                 "mode": "play", "config_sha256": "test"}, 0)


def test_partner_wait_selection_binds_explicit_arm_pair(monkeypatch):
    calls = []

    def prepare(spec, arm, team):
        calls.append((arm, team))
        return SimpleNamespace(declaration={"arm": arm}, banker=team,
                               trump_suit="S"), []

    monkeypatch.setattr(screen, "prepare_round", prepare)
    plan = conditional.selection_plan(0, 1, treatment="partner-wait")
    assert plan["treatment"] == "partner-wait"
    assert [(arm, team) for arm, team in calls] == [
        ("baseline", 0), ("partner-wait", 0),
        ("baseline", 1), ("partner-wait", 1)]
    assert all(set(pair["states"]) == {"baseline", "partner-wait"}
               for deal in plan["selected"] for pair in deal["pairs"])


def test_partner_wait_worker_and_reducer_use_configured_arms(tmp_path, monkeypatch):
    spec = {"index": 7, "seed": 9, "rank": "2", "initial_banker": None}
    states = {arm: {"declaration": {"arm": arm}, "banker": 0,
                    "trump_suit": "S"}
              for arm in ("baseline", "partner-wait")}
    plan = {"start_index": 0, "population_deals": 1,
            "population_deal_teams": 2, "treatment": "partner-wait",
            "criterion": "test", "selected": [{"spec": spec,
            "pairs": [{"team": 0, "states": states}]}],
            "selected_deals": 1, "selected_deal_teams": 1}
    calls = []
    monkeypatch.setattr(screen, "prepare_round",
                        lambda got_spec, arm, team: (calls.append(arm) or
                        (SimpleNamespace(declaration={"arm": arm}, banker=0,
                                         trump_suit="S"), [])))
    monkeypatch.setattr(screen, "make_bots", lambda *_: [])
    def finish(rnd, *_):
        value = 3 if rnd.declaration["arm"] == "partner-wait" else 1
        return {"focal_signed_levels": value, "focal_won": int(value > 0),
                "kitty_bonus": value, "kitty_ge80": 0}
    monkeypatch.setattr(screen, "finish_round", finish)
    config = {"output": str(tmp_path), "selection": plan, "mode": "play",
              "config_sha256": "test", "treatment": "partner-wait",
              "arms": ["baseline", "partner-wait"]}
    shard = conditional.run_cluster(config, 0)
    assert calls == ["baseline", "partner-wait"]
    assert [row["arm"] for row in shard["records"]] == ["baseline", "partner-wait"]
    summary = conditional.summarize([shard], config)
    assert set(summary["cost"]) == {"baseline", "partner-wait"}
    assert summary["comparisons"]["focal_signed_levels"]["mean"] == 2


def test_completed_cluster_inner_record_drift_refuses_resume():
    spec = {"index": 7, "seed": 9, "rank": "2", "initial_banker": None}
    states = {arm: {"declaration": {"arm": arm}, "banker": 0,
                    "trump_suit": "S"}
              for arm in ("baseline", "partner-wait")}
    pair = {"team": 0, "states": states}
    plan = {"start_index": 0, "population_deals": 1,
            "population_deal_teams": 2, "treatment": "partner-wait",
            "criterion": "test", "selected": [{"spec": spec,
            "pairs": [pair]}], "selected_deals": 1,
            "selected_deal_teams": 1}
    config = {"selection": plan, "mode": "play", "config_sha256": "test",
              "treatment": "partner-wait", "arms": ["baseline", "partner-wait"]}
    records = [{"spec": spec, "arm": arm,
                "focal_team": pair["team"], "config_sha256": "test",
                "final_declaration": pair["states"][arm], "outcome": {}}
               for arm in config["arms"]]
    records[1]["spec"] = dict(records[1]["spec"], seed=-1)
    with pytest.raises(ValueError, match="^completed conditional cluster differs$"):
        conditional.validate_cluster({"cluster": 0, "config_sha256": "test",
                                      "records": records}, config, 0)


def test_main_refuses_omitted_pair_in_preconfig_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    plan = conditional.selection_plan(53, 53)
    plan["selected"].pop(0)
    plan["selected_deals"] -= 1
    plan["selected_deal_teams"] -= 1
    (tmp_path/"selection.json").write_text(json.dumps(plan))
    monkeypatch.setattr(conditional, "_run_pending", lambda *_a, **_k: pytest.fail("must not launch workers"))
    with pytest.raises(ValueError, match="^unbound cached selection differs from full census$"):
        conditional.main(["--out", str(tmp_path), "--checkpoint", str(tmp_path/"missing.npz"),
                          "--population-deals", "53"])
    assert not (tmp_path/"config.json").exists()


def test_main_refuses_cached_treatment_drift_before_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    (tmp_path/"selection.json").write_text(json.dumps({
        "start_index": 53, "population_deals": 53, "treatment": "pair-eager"}))
    monkeypatch.setattr(conditional, "_run_pending",
                        lambda *_a, **_k: pytest.fail("must not launch workers"))
    with pytest.raises(ValueError, match="^completed population selection treatment differs$"):
        conditional.main(["--out", str(tmp_path), "--checkpoint", str(tmp_path/"missing.npz"),
                          "--population-deals", "53", "--treatment", "partner-wait"])


def test_main_refuses_drifted_inner_cluster_on_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    spec = {"index": 7, "seed": 9, "rank": "2", "initial_banker": None}
    states = {arm: {"declaration": {"arm": arm}, "banker": 0,
                    "trump_suit": "S"}
              for arm in ("baseline", "partner-wait")}
    plan = {"start_index": 0, "population_deals": 53,
            "population_deal_teams": 106, "treatment": "partner-wait",
            "criterion": "test", "selected": [{"spec": spec,
            "pairs": [{"team": 0, "states": states}]}],
            "selected_deals": 1, "selected_deal_teams": 1}
    (tmp_path/"selection.json").write_text(json.dumps(plan))
    checkpoint = tmp_path/"checkpoint"
    checkpoint.write_bytes(b"test")
    bound = []
    monkeypatch.setattr(conditional, "selection_plan", lambda *_args: plan)
    monkeypatch.setattr(conditional, "_run_pending",
                        lambda config, *_a, **_k: bound.append(config))
    args = ["--out", str(tmp_path), "--checkpoint", str(checkpoint),
            "--start-index", "0", "--population-deals", "53",
            "--treatment", "partner-wait"]
    conditional.main(args)
    config = bound[0]
    records = [{"spec": spec, "arm": arm, "focal_team": 0,
                "config_sha256": config["config_sha256"],
                "final_declaration": states[arm], "outcome": {}}
               for arm in config["arms"]]
    records[1]["spec"] = dict(spec, seed=-1)
    (tmp_path/"cluster-00000.json").write_text(json.dumps({
        "cluster": 0, "config_sha256": config["config_sha256"],
        "records": records}))
    with pytest.raises(ValueError, match="^completed conditional cluster differs$"):
        conditional.main(args)


def test_main_accepts_complete_preconfig_resume_and_binds_it(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    plan = conditional.selection_plan(53, 53)
    (tmp_path/"selection.json").write_text(json.dumps(plan))
    checkpoint = tmp_path/"not-loaded-test-checkpoint"
    checkpoint.write_bytes(b"unused by this census/launch wiring test")
    launched = []
    monkeypatch.setattr(conditional, "_run_pending", lambda config, pending, *_a, **_k:
                        launched.append((config["selection"], pending)))
    args = ["--out", str(tmp_path), "--checkpoint", str(checkpoint), "--population-deals", "53"]
    conditional.main(args)
    assert launched == [(plan, [0, 1, 2])]
    assert json.loads((tmp_path/"config.json").read_bytes())["selection"] == plan
    # Once bound, ordinary resume needs no repeated whole-population census.
    monkeypatch.setattr(conditional, "selection_plan", lambda *_: pytest.fail("bound plan should be reused"))
    conditional.main(args)
    assert len(launched) == 2
