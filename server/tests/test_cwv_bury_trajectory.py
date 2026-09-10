"""Real bury producer -> trajectory -> immutable shard, with honest targets."""
import copy
import json

import numpy as np
import pytest

from shengji.ai.registry import make_bot
from shengji.harvest import rebuild, trajectory
from shengji.harvest.common import action_key
from shengji.harvest.schema import validate_record
from shengji.train import cwv_bury_policy as policy
from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state
from shengji.train.cwv_shortlist import CWVShortlistConfig


class Evaluator:
    max_batch = 64

    def score(self, positions, seat, **kwargs):
        return np.zeros(len(positions))


def test_mc_target_mapping_excludes_unsearched_pool_and_model_scores(monkeypatch):
    rnd = reopen_state(capture_state(65))
    bot = policy.make_cwv_bury_bot(Evaluator(), seed=71, arm="hybrid",
                                  bury_config=policy.CWVBuryConfig(
                                      max_candidates=6, model_worlds=2,
                                      selection_worlds=2, alternatives=2))
    monkeypatch.setattr(policy, "score_bury_candidates",
                        lambda r, cs, ws, e, **kw: np.tile(np.arange(len(cs)), (len(ws), 1)))
    monkeypatch.setattr(policy, "rollout_bury_values",
                        lambda r, cs, ws, b: (np.full((2, 3), 999.0),
                                             np.asarray([[80, 40, 120], [80, 40, 120]])))
    action = bot.decide_bury(rnd, rnd.banker)
    raw = bot.last_bury_record
    assert raw["mc_evidence"]["candidate_indices"] == [0, 4, 5]
    assert raw["picked_index"] == 4
    fields = trajectory._bury_fields({}, "test", 0, 0, rnd.banker,
                                     rnd.hands[rnd.banker], action, raw)
    assert fields["ballot"] == [raw["candidates"][i] for i in [0, 4, 5]]
    reference = make_bot("mc-s0-report-lcb", seed=0)
    expected = [-reference._score(float(p)) for p in [80, 40, 120]]
    assert fields["action_values"]["means"] == expected
    assert fields["preference"]["means"] == expected
    assert fields["allocation"]["selection_worlds"] == [2, 2, 2]
    assert fields["allocation"]["total_worlds"] == 6
    assert fields["allocation"]["played_index"] == 1
    assert fields["allocation"]["raw_winner_index"] == 1
    assert fields["preference"]["final"] == [0.0, 1.0, 0.0]
    search = fields["action_values"]["bury_search"]
    assert len(search["candidate_pool"]) == 6
    assert search["model_means"] == [0., 1., 2., 3., 4., 5.]
    assert search["model_values_are_mc_targets"] is False
    old = copy.deepcopy(raw)
    del old["mc_evidence"]
    with pytest.raises(policy.BuryPolicyError, match="^bury trajectory requires retained MC evidence;"):
        trajectory._bury_fields({}, "test", 0, 0, rnd.banker,
                                rnd.hands[rnd.banker], action, old)
    bad = copy.deepcopy(raw)
    bad["mc_evidence"]["candidate_indices"] = [0, 0, 5]
    with pytest.raises(policy.BuryPolicyError, match="^bury MC evidence is not aligned with its scored candidates$"):
        policy.trajectory_bury_record(bad)


@pytest.mark.parametrize("arm", ["heuristic", "mc", "hybrid"])
def test_actual_trajectory_round_and_shard_preserve_bury_evidence(tmp_path, monkeypatch, arm):
    # Only the unregistered factory/evaluator is supplied by the test. Keep
    # real trajectory mixin, sampling, MC search, engine, rebuild and writer.
    # Reduced doses make this a contract test, not new strength evidence.
    policy_name = f"test-cwv-bury-{arm}"
    raw_records = []
    original_decide = policy.CWVBuryBot.decide_bury

    def record_decide(self, rnd, seat):
        action = original_decide(self, rnd, seat)
        raw_records.append(copy.deepcopy(self.last_bury_record))
        return action

    def factory(name, *, seed):
        if name != policy_name:
            return make_bot(name, seed=seed)
        return policy.make_cwv_bury_bot(
            Evaluator(), CWVShortlistConfig(worlds=1, selection_worlds=1,
                                           alternatives=1),
            seed=seed, arm=arm, bury_config=policy.CWVBuryConfig(
                max_candidates=6, model_worlds=1, selection_worlds=2, alternatives=2))

    monkeypatch.setattr(policy.CWVBuryBot, "decide_bury", record_decide)
    monkeypatch.setattr(trajectory, "make_bot", factory)
    config = trajectory.build_config(policy=policy_name, seed0=4_100_000,
                                      explore_rate=0, select_worlds=1, report_worlds=30)
    records, stats = trajectory.play_trajectory_cluster(config, 0, config["seed0"])
    sidecar = trajectory.publish_shard(tmp_path, config, 0, config["seed0"], records, stats)
    reopened, reason = trajectory.verify_shard(tmp_path, config, 0, config["seed0"])
    assert reopened == sidecar, reason
    jsonl, _ = trajectory.shard_paths(tmp_path, 0)
    stored = [json.loads(line) for line in jsonl.read_text().splitlines()]
    assert stored == records and len(stored) > 2
    for record in stored:
        validate_record(record)
    buries = [r for r in stored if r["decision_kind"] == "bury"]
    assert len(buries) == len(raw_records) == 2
    for record, raw in zip(buries, raw_records):
        search = record["action_values"]["bury_search"]
        assert search["arm"] == arm
        assert search["candidate_pool"] == raw["candidates"]
        assert record["ballot"] == [raw["candidates"][i] for i in search["ballot_pool_indices"]]
        assert action_key(record["action"]) == action_key(raw["candidates"][raw["picked_index"]])
        assert record["allocation"]["total_worlds"] == raw["mc_rollouts"]
        assert record["action_values"]["means"] == (
            [None] if arm == "heuristic" else raw["mc_evidence"]["mean_banker_values"])
        rnd = rebuild.state_for_record(record)
        assert rnd.phase == "bury"
        rnd.bury(record["seat"], record["action"])
        assert rnd.phase == "play"
