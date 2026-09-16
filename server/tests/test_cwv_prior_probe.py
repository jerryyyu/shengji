import copy

import numpy as np
import pytest

from shengji.train import cwv_prior_probe as probe


class FakePrior:
    def __init__(self):
        self.calls = 0
        self.output = None

    def identity(self):
        return {"kind": "uniform-test-prior"}

    def probabilities(self, state, seat, ballot):
        return self.batch_from_encoded([self.encode(state, seat, ballot)])[0]

    def encode(self, state, seat, ballot):
        return np.array([seat]), np.ones((len(ballot), 2))

    def batch_from_encoded(self, rows):
        self.calls += 1
        self.output = [np.full(len(c), 1 / len(c)) for _, c in rows]
        return self.output


@pytest.fixture(autouse=True)
def simple_state_copy(monkeypatch):
    monkeypatch.setattr(probe, "leaf_copy", copy.deepcopy)


def test_capture_freezes_pre_action_state_and_preserves_output_identity():
    prior = FakePrior()
    recorder = probe.PriorRecorder(prior)
    state, ballot = {"history": [1]}, [["S2"], ["S3"]]
    encoded = recorder.encode(state, 2, ballot)
    state["history"].append(2)
    ballot[0].append("S4")
    encoded[0][0] = 9
    output = recorder.batch_from_encoded([encoded])
    assert output is prior.output and prior.calls == 1
    row = recorder.rows[0]
    assert row.state == {"history": [1]} and row.seat == 2
    assert row.ballot == (("S2",), ("S3",))
    assert row.observation.tolist() == [2]
    output[0][0] = 0
    assert row.probabilities.tolist() == [0.5, 0.5]


def test_prefix_bounded_and_equal_features_do_not_alias_reordered_requests():
    prior = FakePrior()
    recorder = probe.PriorRecorder(prior, limit=2)
    a = recorder.encode({"id": 1}, 0, [["S2"]])
    b = recorder.encode({"id": 2}, 0, [["S2"]])
    c = recorder.encode({"id": 3}, 0, [["S2"]])
    recorder.batch_from_encoded([b, c])
    assert len(recorder.rows) == 2
    assert recorder.rows[0].probabilities is None
    assert recorder.rows[1].probabilities.tolist() == [1]
    recorder.batch_from_encoded([a])
    assert not recorder._pending
    assert recorder.rows[0].probabilities.tolist() == [1]
    assert prior.calls == 2


def test_scalar_and_batch_entrypoints_capture_without_extra_forwards():
    prior = FakePrior()
    recorder = probe.PriorRecorder(prior)
    assert recorder.probabilities({}, 1, [["S2"]]).tolist() == [1]
    result = recorder.batch_probabilities([({}, 0, [["S3"]]), ({}, 2, [["S4"]])])
    assert len(result) == 2 and len(recorder.rows) == 3 and prior.calls == 2


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_limits(limit):
    with pytest.raises(ValueError):
        probe.PriorRecorder(FakePrior(), limit)


@pytest.mark.parametrize("bad", [[np.nan], [-1], [0.5], [0.5, 0.5]])
def test_invalid_captured_probabilities_fail_explicitly(bad):
    prior = FakePrior()
    recorder = probe.PriorRecorder(prior)
    encoded = recorder.encode({}, 0, [["S2"]])
    prior.batch_from_encoded = lambda rows: [np.array(bad)]
    with pytest.raises(ValueError):
        recorder.batch_from_encoded([encoded])
    assert recorder.rows[0].probabilities is None


def test_real_puct_consumer_keeps_action_rng_and_visits(monkeypatch):
    from test_cwv_puct import _contested_state, _StubEvaluator
    from shengji.ai.cwv_puct import CWVPuctBot, leaf_copy
    monkeypatch.setattr(probe, "leaf_copy", leaf_copy)
    cls = type("PriorProbe", (CWVPuctBot,), dict(
        CWV_PRIOR="head", CWV_WORLD_POOL=2, CWV_BATCH=2,
        CWV_SIMULATIONS=8))
    plain_prior = FakePrior()
    recorded_prior = FakePrior()
    recorder = probe.PriorRecorder(recorded_prior, limit=3)
    plain = cls(seed=7, evaluator=_StubEvaluator(lambda p, s: .25), prior_head=plain_prior)
    recorded = cls(seed=7, evaluator=_StubEvaluator(lambda p, s: .25), prior_head=recorder)
    rnd = _contested_state()
    a = plain.decide_play(copy.deepcopy(rnd), rnd.turn)
    b = recorded.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert a == b and plain.rng.getstate() == recorded.rng.getstate()
    assert plain.last_root.N == recorded.last_root.N
    assert {k: (e.N, e.W) for k, e in plain.last_root.edges.items()} == {
        k: (e.N, e.W) for k, e in recorded.last_root.edges.items()}
    assert plain_prior.calls == recorded_prior.calls
    assert len(recorder.rows) == 3 and not recorder._pending
    assert all(row.probabilities is not None for row in recorder.rows)


def test_prior_metrics_keep_ties_and_regret_explicit():
    result = probe.compare_prior([.6, .3, .1], [[0, 2, 2], [2, 2, 2]], top_k=2)
    assert result["selected_index"] == 0
    assert result["comparator_regret"] == 1
    assert result["comparator_best_indices"] == [1, 2]
    assert result["best_set_prior_mass"] == pytest.approx(.4)
    assert result["top_k_hits_best"] and result["strict_pairs"] == 2
    assert result["pairwise_accuracy"] == 0
    tied = probe.compare_prior([.5, .5], [[1, 1]], top_k=1)
    assert tied["selected_index"] == 0 and tied["pairwise_accuracy"] is None
    assert tied["comparator_regret"] == 0


@pytest.mark.parametrize("p,v", [([1], []), ([1], [[0, 1]]), ([1], [[np.nan]]),
                                 ([.5], [[1]]), ([-1, 2], [[1, 2]])])
def test_prior_metric_validation(p, v):
    with pytest.raises(ValueError):
        probe.compare_prior(p, v)


def test_unserved_request_cannot_be_compared():
    recorder = probe.PriorRecorder(FakePrior())
    recorder.encode({}, 0, [["S2"]])
    with pytest.raises(ValueError, match="not been served"):
        probe.compare_request(recorder.rows[0], sampler=None)


def test_real_common_world_comparator_uses_captured_actor_and_preserves_capture(monkeypatch):
    from test_cwv_puct import _contested_state
    from shengji.ai.cwv_puct import leaf_copy
    from shengji.ai.mcbot import MCBot
    monkeypatch.setattr(probe, "leaf_copy", leaf_copy)
    state = _contested_state(start=40)
    seat = state.turn
    ballot = MCBot(seed=0)._candidates(state, seat)[:2]
    prior = FakePrior()
    recorder = probe.PriorRecorder(prior, limit=1)
    recorder.probabilities(state, seat, ballot)
    row = recorder.rows[0]
    before = (copy.deepcopy(row.state.hands), len(row.state.history), row.state.turn)
    report = probe.compare_request(row, sampler=MCBot(seed=817), worlds=2)
    assert report["seat"] == seat and report["own_kitty"] is False
    assert report["metrics"]["worlds"] == 2 and report["metrics"]["actions"] == 2
    assert np.asarray(report["world_values"]).shape == (2, 2)
    assert (row.state.hands, len(row.state.history), row.state.turn) == before
    assert prior.calls == 1
    # Changing hidden assignments without changing the actor's hand/public
    # history must not affect resampling or comparator values at a fixed RNG.
    others = [s for s in range(4) if s != seat]
    a, b = others[:2]
    row.state.hands[a], row.state.hands[b] = row.state.hands[b], row.state.hands[a]
    second = probe.compare_request(row, sampler=MCBot(seed=817), worlds=2)
    assert second["sampled_worlds"] == report["sampled_worlds"]
    assert second["world_values"] == report["world_values"]
