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
        CWV_SIMULATIONS=8, CWV_MAX_DEPTH=2))
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
