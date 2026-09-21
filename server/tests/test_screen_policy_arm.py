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
