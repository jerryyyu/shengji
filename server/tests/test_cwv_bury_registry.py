"""Opt-in recipe identity, real checkpoint loading and spawned data workers."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shengji.ai import registry
from shengji.ai.cwv_policy import file_sha256
from shengji.harvest import shortlist_scores, trajectory
from shengji.train.cwv_bury_policy import (
    BuryPolicyError, CWVBuryBot, CWVBuryConfig, bury_env_recipe,
    bury_registry_entries,
)
from shengji.train.cwv_shortlist import CWVShortlistBot, make_shortlist_bot
from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state

# Reuse the existing two-deal/two-epoch tiny checkpoint fixture. This tests
# actual loading/encoding, not model quality; no research artifacts are read.
from test_cwv_shortlist_registry import checkpoint  # noqa: F401


PLAY = dict(alternatives=1, selection_worlds=1, report_worlds=30)
BURY = CWVBuryConfig(max_candidates=6, model_worlds=1, selection_worlds=2, alternatives=2)


def test_registered_identity_binds_play_and_bury_and_full_checkpoint(checkpoint, monkeypatch):
    before = dict(registry.REGISTRY)
    try:
        names = registry.register_cwv_bury_policies(checkpoint, [1], arm="hybrid",
                                                    bury_config=BURY, **PLAY)
        name, = names
        bot = registry.make_bot(name, seed=17)
        base = make_shortlist_bot(checkpoint, seed=17, worlds=1, **PLAY)
        assert type(bot) is CWVBuryBot
        assert bot.decide_play.__func__ is base.decide_play.__func__
        assert bot._candidates.__func__ is base._candidates.__func__
        assert bot.rng.getstate() == base.rng.getstate()
        assert bot.shortlist_config == base.shortlist_config
        assert bot.REPORT_FOLD_WORLDS == base.REPORT_FOLD_WORLDS == 30
        assert bot.evaluator is base.evaluator
        assert bot.MC_BURY is False  # do not recurse into the inherited chooser
        identity = bot.bury_recipe_identity
        assert identity["checkpoint_sha256"] == file_sha256(checkpoint)
        assert identity["play_policy"] == base.policy_name
        assert identity["config"]["selection_worlds"] == 2
        assert identity["fallback"] == "raise"
        config = trajectory.build_config(policy=name, seed0=4_700_021, explore_rate=0)
        assert config["bury_policy"] == identity
        assert config["policy_flags"]["mc_bury"] is True  # actual helper work
        mutant = copy.deepcopy(config)
        mutant["bury_policy"]["config"]["selection_worlds"] += 1
        assert trajectory.run_id_for(mutant) != config["run_id"]
        configs = [BURY, CWVBuryConfig(max_candidates=7, model_worlds=1, selection_worlds=2, alternatives=2),
                   CWVBuryConfig(max_candidates=6, model_worlds=2, selection_worlds=2, alternatives=2),
                   CWVBuryConfig(max_candidates=6, model_worlds=1, selection_worlds=3, alternatives=2),
                   CWVBuryConfig(max_candidates=6, model_worlds=1, selection_worlds=2, alternatives=1)]
        variants = [next(iter(bury_registry_entries(checkpoint, [1], arm="hybrid",
                                                    bury_config=c, **PLAY))) for c in configs]
        variants += [next(iter(bury_registry_entries(checkpoint, [1], arm=a,
                                                      bury_config=BURY, **PLAY))) for a in ("heuristic", "mc")]
        variants.append(next(iter(bury_registry_entries(checkpoint, [2], arm="hybrid",
                                                         bury_config=BURY, **PLAY))))
        assert len(set(variants)) == len(variants)
        assert all(registry.REGISTRY[k] is v for k, v in before.items())
        # After the new bury, identical actual play states/RNG must still
        # produce the old play policy's action and counter advances.
        rnd = reopen_state(capture_state(65))
        rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
        assert bot.rng.getstate() == base.rng.getstate()
        assert bot.decide_play(copy.deepcopy(rnd), rnd.turn) == base.decide_play(copy.deepcopy(rnd), rnd.turn)
        assert bot.rng.getstate() == base.rng.getstate()
        assert bot.rollouts == base.rollouts
    finally:
        for name in set(registry.REGISTRY) - set(before):
            registry.REGISTRY.pop(name)


def test_full_legal_capture_still_refuses_unknown_subclasses(checkpoint, monkeypatch):
    class Foreign(CWVShortlistBot):
        pass

    bot = make_shortlist_bot(checkpoint, worlds=1, **PLAY)
    bot.__class__ = Foreign
    monkeypatch.setitem(registry.REGISTRY, "test-foreign", lambda **kw: bot)
    with pytest.raises(trajectory.TrajectoryError, match="^full-legal score capture requires a learned shortlist policy$"):
        trajectory.build_config(policy="test-foreign", seed0=4_700_021, capture_full_legal_scores=True)


def test_bury_env_is_opt_in_and_separates_play_from_bury():
    assert bury_env_recipe({}) is None
    with pytest.raises(BuryPolicyError, match="requires SHENGJI_CWV_SHORTLIST_CKPT"):
        bury_env_recipe({"SHENGJI_CWV_BURY_ARM": "hybrid"})
    parsed = bury_env_recipe({"SHENGJI_CWV_SHORTLIST_CKPT": "example.pt",
                             "SHENGJI_CWV_SHORTLIST_SELECTION_WORLDS": "30",
                             "SHENGJI_CWV_BURY_ARM": "hybrid",
                             "SHENGJI_CWV_BURY_SELECTION_WORLDS": "128"})
    assert parsed[2]["selection_worlds"] == 30
    assert parsed[4].selection_worlds == 128


def test_spawned_generator_uses_bury_recipe_and_full_legal_sidecar(checkpoint, tmp_path):
    # One complete cluster through two-worker spawn mode. The child must
    # independently resolve the opt-in env factory and real checkpoint.
    out = tmp_path / "generated"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SHENGJI_CWV_", "SHENGJI_NETROLL_"))}
    env.update({"SHENGJI_CWV_SHORTLIST_CKPT": checkpoint,
                "SHENGJI_CWV_SHORTLIST_WORLDS": "1",
                "SHENGJI_CWV_SHORTLIST_ALTERNATIVES": "1",
                "SHENGJI_CWV_SHORTLIST_SELECTION_WORLDS": "1",
                "SHENGJI_CWV_SHORTLIST_REPORT_WORLDS": "30",
                "SHENGJI_CWV_BURY_ARM": "hybrid",
                "SHENGJI_CWV_BURY_MAX_CANDIDATES": "6",
                "SHENGJI_CWV_BURY_MODEL_WORLDS": "1",
                "SHENGJI_CWV_BURY_SELECTION_WORLDS": "2",
                "SHENGJI_CWV_BURY_ALTERNATIVES": "2",
                "SHENGJI_REQUIRE_VOIDS": "1", "OMP_NUM_THREADS": "1"})
    code = """
import sys
from shengji.ai.registry import REGISTRY
from shengji.harvest.trajectory import generate
if __name__ == '__main__':
    name, = [n for n in REGISTRY if '-bury-hybrid-' in n]
    generate(rounds=2, seed0=4700021, out_dir=sys.argv[1], policy=name,
             workers=2, explore_rate=0, capture_full_legal_scores=True,
             seed_windows=sys.argv[2])
"""
    result = subprocess.run([sys.executable, "-c", code, str(out), str(tmp_path / "seeds.json")],
                            env=env, cwd=Path(__file__).parents[1], capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((out / "manifest.json").read_text())
    config = manifest["config"]
    assert config["bury_policy"]["checkpoint_sha256"] == file_sha256(checkpoint)
    assert config["bury_policy"]["config"]["selection_worlds"] == 2
    receipt, reason = trajectory.verify_shard(out, config, 0, config["seed0"])
    assert reason == "ok", reason
    assert receipt["work"]["bury_mc_rollouts"] == 12  # 2 rounds x 3 finalists x 2 worlds
    rows = [json.loads(line) for line in (out / receipt["path"]).read_text().splitlines()]
    plays = [r for r in rows if r["decision_kind"] == "play"]
    buries = [r for r in rows if r["decision_kind"] == "bury"]
    scores = list(shortlist_scores.read_scores(shortlist_scores.score_path(out, 0)))
    assert len(buries) == 2
    assert len(scores) == len(plays) > 20
    assert all(r["action_values"]["bury_search"]["arm"] == "hybrid" for r in buries)
    assert any(r["scores"] and r["scores"]["means"] is not None for r in scores)
    assert receipt["work"]["bury_model_positions"] == 12
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["per_cluster"]["0"]["bury_wall_secs"] > 0
