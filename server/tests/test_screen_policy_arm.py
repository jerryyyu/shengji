"""The shortlist screen's ``--arm policy`` (release 29 confirmation): the arm is a served bot
built by registry name, its identity is bound at configuration time and re-checked in the
worker, and the queue's ``--arm-policy`` mode refuses checkpoint options."""
import pytest

from shengji.ai.registry import REGISTRY, register_pv_search_policies
from shengji.train import cwv_screen_queue as queue
from shengji.train import cwv_shortlist_screen as screen
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_bury_policy import CWVBuryConfig
from test_pv_search_serving import package  # noqa: F401

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
BURY = CWVBuryConfig(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)


@pytest.fixture
def registered(package):
    path, sha = package
    names = register_pv_search_policies(path, sha256=sha, bury_arm="hybrid", bury_config=BURY, **SMALL)
    try:
        yield names[0]
    finally:
        for n in names:
            REGISTRY.pop(n, None)


def test_policy_arm_builds_the_registry_bot_and_binds_its_identity(registered):
    from shengji.ai.registry import make_bot
    probe = make_bot(registered, seed=0)
    identity = screen._policy_identity(probe)
    assert identity["policy_name"] == registered and identity["bot_class"] == "PVSearchBuryBot"
    assert identity["bury_arm"] == "hybrid" and identity["bury_recipe_identity"]["play_policy"].startswith("pv-search-")
    config = {"arm": "policy", "arm_policy": registered, "arm_policy_identity": identity,
              "report_worlds": 300, "shortlist": {"worlds": 32, "selection_worlds": 30,
                                                   "alternatives": 4, "batch_size": 128, "uniform": False}}
    bot = screen.make_side(config, "arm", 7)
    assert isinstance(bot, pv.PVSearchBuryBot) and bot.policy_name == registered
    baseline = screen.make_side(config, "baseline", 7)
    assert type(baseline).__name__ == "MCS0ReportLCB"          # production's MC control, untouched
    config["arm_policy_identity"] = {**identity, "bot_class": "Other"}
    with pytest.raises(ValueError, match="identity changed"):
        screen.make_side(config, "arm", 7)
    recipe = screen._recipe({**config, "schema": "cwv-shortlist-config-v1", "checkpoint_sha256": None,
                             "production_multiplier": 1, "target_wall_multiplier": 1})
    assert recipe["arm_policy"] == registered and recipe["arm_policy_identity"]["bot_class"] == "Other"


def test_screen_and_queue_refuse_mismatched_policy_options(registered, tmp_path):
    with pytest.raises(SystemExit):
        screen.main(["--arm", "policy", "--out", str(tmp_path / "x"), "--clusters", "1", "--workers", "1",
                     "--seed0", "1"])                                     # no --arm-policy
    with pytest.raises(SystemExit):
        screen.main(["--arm", "learned", "--arm-policy", registered, "--checkpoint", str(tmp_path / "a.pt"),
                     "--out", str(tmp_path / "y"), "--clusters", "1", "--workers", "1", "--seed0", "1"])
    with pytest.raises(SystemExit):
        queue.main(["--arm-policy", registered, "--checkpoint", str(tmp_path / "a.pt"),
                    "--checkpoint-sha256", "0" * 64, "--out", str(tmp_path / "q"), "--name", "Q",
                    "--seeds", "1", "--workers", "1"])
    with pytest.raises(SystemExit):
        queue.main(["--out", str(tmp_path / "q2"), "--name", "Q", "--seeds", "1", "--workers", "1"])


def test_policy_arm_plays_one_cluster_through_the_deadline_worker(registered, package, tmp_path, monkeypatch):
    """End to end, as the lane runs it: one cluster (both mirrors) with the served pv-search
    bot as the arm under the 300 s deadline worker.  The worker pickles the bot state per
    move and the timed wrapper records the pv-search receipt (lane v34pv aborted on both)."""
    import json
    from dataclasses import asdict
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    # the spawned worker registers the name from SHENGJI_PV_* at import, as the lane/server do
    path, sha = package
    for key, value in dict(CKPT=path, SHA256=sha, BURY_ARM="hybrid", **{k.upper(): v for k, v in SMALL.items()},
                           **{"BURY_" + k.upper(): v for k, v in asdict(BURY).items()}).items():
        monkeypatch.setenv("SHENGJI_PV_" + key, str(value))
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe())) == [registered]
    out = tmp_path / "pv"
    screen.main(["--arm", "policy", "--arm-policy", registered, "--out", str(out),
                 "--clusters", "1", "--workers", "1", "--seed0", "1", "--decision-deadline", "300"])
    shards = sorted(out.glob("**/*.json"))
    assert shards and not (out / "failure.json").exists()
    traces = [s for s in (json.loads(p.read_text()) for p in shards)
              if isinstance(s, dict) and s.get("schema") == "cwv-shortlist-shard-v1"]
    assert len(traces) == 1
    arm = [t for t in traces[0]["decision_traces"] if t["side"] == "arm"]
    decisions = [d for t in arm for d in t["decisions"]]
    schemas = {d.get("schema") for d in decisions}
    assert "pv-search-decision-v1" in schemas and schemas <= {"pv-search-decision-v1", "pv-search-fallback-v1"}
    assert all(isinstance(d["played"], list) and d["played"] for d in decisions)
    assert not any("cwv_shortlist" in d for d in decisions)
    assert all(d["deadline"]["timed_out"] is False for d in decisions)   # outer 300 s never fired
    buries = [d for t in arm for d in t["bury_decisions"]]
    assert buries and {d["schema"] for d in buries} == {"cwv-bury-policy-v1"}
    summary = json.loads((out / "summary.json").read_text())
    assert summary["arm"] == "policy" and registered in summary["arm_description"]


def test_policy_arm_internal_budget_fallbacks_are_countable(package, tmp_path, monkeypatch):
    """Internal play/bury budget fallbacks (2 s / 3 s in production) must be visible in
    the traces as the bot's own fallback records, distinct from the outer 300 s deadline."""
    import json
    from dataclasses import asdict
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    path, sha = package
    for key, value in dict(CKPT=path, SHA256=sha, BURY_ARM="hybrid", SERVING_BUDGET_SECONDS="1e-9",
                           BURY_SERVING_BUDGET_SECONDS="1e-9", **{k.upper(): v for k, v in SMALL.items()},
                           **{"BURY_" + k.upper(): v for k, v in asdict(BURY).items()}).items():
        monkeypatch.setenv("SHENGJI_PV_" + key, str(value))
    name, = register_pv_search_policies(**pv.pv_env_recipe())
    try:
        out = tmp_path / "pvfb"
        screen.main(["--arm", "policy", "--arm-policy", name, "--out", str(out),
                     "--clusters", "1", "--workers", "1", "--seed0", "1", "--decision-deadline", "300"])
        shard, = [json.loads(p.read_text()) for p in out.glob("cluster-*.json")]
        arm = [t for t in shard["decision_traces"] if t["side"] == "arm"]
        plays = [d for t in arm for d in t["decisions"]]
        buries = [d for t in arm for d in t["bury_decisions"]]
        assert plays and {d["schema"] for d in plays} == {"pv-search-fallback-v1"}
        assert {d["reason"] for d in plays} == {"budget"}
        assert all(d["deadline"]["timed_out"] is False for d in plays)
        assert buries and {d["schema"] for d in buries} == {"cwv-bury-fallback-v1"}
        assert {d["reason"] for d in buries} == {"budget"}
        assert json.loads((out / "summary.json").read_text())["arm"] == "policy"
    finally:
        REGISTRY.pop(name, None)
