"""Consumer witnesses for opt-in W32 allocation; no provider/checkpoint needed."""

import copy
import json

import numpy as np
import pytest

from shengji.ai import mcbot
from shengji.train import cwv_shortlist_screen as S
from tests.test_world_shortlist import play_state, round_signature


def learned_config(**extra):
    config = {
        "schema": "cwv-shortlist-config-v1", "arm": "learned",
        "checkpoint": "checkpoint.pt", "checkpoint_sha256": "checkpoint-sha",
        "shortlist": {"worlds": 32, "selection_worlds": 30,
                       "alternatives": 4, "batch_size": 128, "uniform": False},
        "report_worlds": 300, "production_multiplier": 1,
        "target_wall_multiplier": 1, "seed0": 17, "clusters": 1,
    }
    config.update(extra)
    return config


@pytest.fixture
def evaluator(monkeypatch):
    class Evaluator:
        checkpoint_sha256 = "checkpoint-sha"

        def identity(self):
            return {"checkpoint_sha256": self.checkpoint_sha256}

    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k: Evaluator())
    return Evaluator()


def test_legacy_recipe_defaults_uniform_and_explicit_mode_binds(evaluator):
    legacy = learned_config()
    assert S._selection_allocation(legacy) == "uniform"
    assert "selection_allocation" not in S._recipe(legacy)
    assert S.make_side(legacy, "arm", 17).ADAPTIVE_ALLOCATION is False
    for mode in ("uniform", "adaptive"):
        config = learned_config(selection_allocation=mode)
        assert S._recipe(config)["selection_allocation"] == mode
        assert S.make_side(config, "baseline", 17).ADAPTIVE_ALLOCATION is False


@pytest.mark.parametrize("config, message", [
    ({"arm": "uniform", "selection_allocation": "adaptive"},
     "adaptive selection allocation requires learned arm"),
    ({"arm": "learned", "selection_allocation": "adaptive",
      "double_shortlist": {"mode": "uniform"}},
     "adaptive selection allocation is incompatible with double-shortlist"),
    ({"arm": "learned", "selection_allocation": "bogus"},
     "selection allocation must be uniform or adaptive"),
])
def test_invalid_allocation_recipe_refuses_at_worker_entry(config, message):
    with pytest.raises(ValueError, match=f"^{message}$"):
        S.make_side(config, "arm", 17)


def test_cli_reaches_real_adaptive_decision_report_and_trace(monkeypatch, tmp_path, evaluator):
    """Real CLI/config/factory/W32/sampler/allocator/report/logger chain.

    Only neural values and expensive terminal rollout returns are synthetic.
    The actual legal ballot, W32 draws, paired allocation, report sampling and
    LCB decision remain live. Disabling make_side's treatment must fail here.
    """
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "_run_pending", lambda *a, **k: None)
    out = tmp_path / "screen"
    assert S.main([
        "--arm", "learned", "--checkpoint", "checkpoint.pt", "--worlds", "32",
        "--selection-allocation", "adaptive", "--baseline", "flat-shortlist",
        "--clusters", "1", "--workers", "1", "--seed0", "17", "--out", str(out),
    ]) == 0
    config = json.loads((out / "config.json").read_text())
    assert config["selection_allocation"] == "adaptive"

    rank_calls = []

    def ranked_means(self, rnd, seat, actions, worlds):
        rank_calls.append((len(actions), len(worlds)))
        return np.arange(len(actions), dtype=np.float64)

    def rollout(self, rnd, seat, hands, buried, candidate, *, exact_session=None):
        index = self.last_shortlist["shortlist"].index(candidate)
        value = (0.0, 10.0, -10.0, -20.0, -30.0)[index]
        return value if rnd.is_attacker(seat) else -value

    monkeypatch.setattr(S.CWVShortlistBot, "_means", ranked_means)
    monkeypatch.setattr(S.CWVShortlistBot, "_rollout", rollout)
    monkeypatch.setattr(S.CWVShortlistBot, "_score", lambda self, value: value)
    rnd = play_state()
    before = round_signature(rnd)
    bots = [S.make_side(config, side, 17) for side in ("arm", "baseline")]
    policies = [S.CwvTimedPolicy(bot) for bot in bots]
    rng_after_selection = []

    # Observe, not replace, the real independent report implementation. It must
    # restore each arm's selection RNG after sampling its own R300 child stream.
    original_report = mcbot.MCBot._report_fold_gap

    def report(self, *args, **kwargs):
        original_rng = self.rng
        state = self.rng.getstate()
        result = original_report(self, *args, **kwargs)
        assert self.rng is original_rng and self.rng.getstate() == state
        rng_after_selection.append(state)
        return result

    monkeypatch.setattr(mcbot.MCBot, "_report_fold_gap", report)
    played = [policy.decide_play(rnd, rnd.turn) for policy in policies]
    assert round_signature(rnd) == before
    assert len(rank_calls) == 2 and all(n > 5 and w == 32 for n, w in rank_calls)
    adaptive, uniform = [bot.last_decision_record for bot in bots]
    assert adaptive["candidates"] == uniform["candidates"]
    assert adaptive["report_seed"] == uniform["report_seed"]
    assert rng_after_selection[0] != rng_after_selection[1]
    assert adaptive["alloc"]["mode"] == "deterministic_adaptive"
    assert adaptive["n_by_candidate"] == [64, 64, 7, 7, 7]
    assert adaptive["eligible_indices"] == [0, 1]
    assert adaptive["alloc"]["survivor_indices"] == [0, 1]
    assert adaptive["alloc"]["prunes"] == [{
        "world": 7, "leader": 1, "deterministic_survivors": [0, 1], "survivors": [0, 1],
    }]
    assert adaptive["alloc"]["decision_rollouts"] == 149
    assert adaptive["alloc"]["dummy_rollouts"] == 1
    assert uniform["alloc"]["mode"] == "uniform"
    assert uniform["n_by_candidate"] == [30] * 5
    for rec, policy, move in zip((adaptive, uniform), policies, played):
        assert rec["work"] == {
            "selection_budget": 150, "selection_rollouts": 150,
            "report_budget": 600, "report_rollouts": 600,
            "total_budget": 750, "total_rollouts": 750,
            "complete": True,
        }
        assert rec["report_candidate_index"] == 1
        assert move == rec["candidates"][1]
        assert rec["paired_se"] == [0.0] * 5
        assert rec["report_fold"]["worlds"] == 300
        assert rec["report_fold"]["complete"] is True
        assert rec["report_fold"]["rule"] == "lcb"
        assert rec["report_fold"]["gap"] == 10.0
        assert policy.decisions[-1]["selection_allocation"] == rec["alloc"]
        assert policy.decisions[-1]["selection_allocation"] is not rec["alloc"]

    # A subsequent forced decision must clear actual MC evidence rather than
    # exporting the previous decision's allocation again.
    bot, policy = bots[0], policies[0]
    saved_trace = copy.deepcopy(policy.decisions)

    def singleton(rnd, seat):
        bot.last_shortlist = {
            "legal_count": 1, "counts": {"forced": 1},
            "production_keys": [tuple(sorted(played[0]))],
        }
        return [played[0]]

    monkeypatch.setattr(bot, "_candidates", singleton)
    assert policy.decide_play(rnd, rnd.turn) == played[0]
    assert bot.last_alloc is None and bot.last_decision_record is None
    assert policy.decisions[:-1] == saved_trace
    assert policy.decisions[-1]["forced"] is True
    assert "selection_allocation" not in policy.decisions[-1]


def test_resume_refuses_selection_allocation_change(tmp_path):
    config = learned_config(selection_allocation="uniform")
    shard = {
        "schema": "cwv-shortlist-shard-v1", "cluster": 0, "seed": 17,
        "rank": "2", "recipe": S._recipe(config),
        "records": [{"cluster": 0, "seed": 17, "mirror": mirror,
                     "trump_rank": "2", "arm": "learned"} for mirror in (0, 1)],
    }
    path = tmp_path / "cluster-00000.json"
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, config, 0) == shard
    changed = {**config, "selection_allocation": "adaptive"}
    with pytest.raises(ValueError, match="^completed shard does not match"):
        S.reopen_shard(path, changed, 0)
