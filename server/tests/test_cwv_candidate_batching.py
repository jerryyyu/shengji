"""Issue #342 finding 1: the candidate pass scores many records per forward.

The batched scorer must hand every record exactly the values the per-record
scorer would, including across chunk boundaries, and the pass must consume
them in record order.  Tolerance covers batch-shape float effects only."""
import numpy as np
import pytest
import torch

from shengji.rl.encode_versions import OBS_DIM_BY_VERSION
from shengji.rl.value_afterstate import WORLD_RECEIVERS
from shengji.rl.encode import N_CARDS
from shengji.train import cwv_eval
from shengji.train.train_cwv import cwv_score_fn, cwv_score_many_fn
from shengji.rl.value_model import ValueModelConfig, ValueNetwork


def _entry(rng, k, public_dim):
    return {
        "public": rng.random((k, public_dim), dtype=np.float32),
        "world": rng.integers(0, 3, size=(k, WORLD_RECEIVERS, N_CARDS)).astype(np.uint8),
        "perspective": rng.integers(0, 2, size=k).astype(bool),
        "terminal": np.zeros(k, dtype=bool),
        "terminal_level": np.zeros(k, dtype=np.float64),
        "means": rng.random(k),
        "deal_key": f"deal-{k}",
    }


def _entries(seed=7, widths=(1, 3, 9, 2, 14, 5, 1, 8)):
    torch.manual_seed(seed)
    model = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                          attention_heads=1, enc_version=2, public_dim=561)).eval()
    public_dim = int(model.config.public_dim)
    rng = np.random.default_rng(seed)
    return model, [_entry(rng, k, public_dim) for k in widths]


def test_batched_scores_equal_per_record_scores_across_chunk_boundaries():
    model, entries = _entries()
    one = cwv_score_fn(model, torch.device("cpu"))
    many = cwv_score_many_fn(model, torch.device("cpu"), max_rows=7)  # forces several chunks
    expected = [one(e) for e in entries]
    got = many(entries)
    assert len(got) == len(entries)
    for e, a, b in zip(entries, expected, got):
        assert b.shape == (int(e["public"].shape[0]),)
        np.testing.assert_allclose(b, a, rtol=0, atol=1e-6)


def test_a_single_wide_record_still_forms_its_own_chunk():
    model, entries = _entries(widths=(40,))
    one = cwv_score_fn(model, torch.device("cpu"))
    many = cwv_score_many_fn(model, torch.device("cpu"), max_rows=8)  # smaller than the record
    np.testing.assert_allclose(many(entries)[0], one(entries[0]), rtol=0, atol=1e-6)


def test_candidate_pass_prefers_the_batched_scorer_and_keeps_record_order(monkeypatch):
    model, entries = _entries()
    calls = []

    class Result:
        source_ref = []
        deal_key = []
        decision_obs = np.zeros((0, 1), dtype=np.float32)
        search = entries

    monkeypatch.setattr(cwv_eval, "iter_shard_results", lambda tasks, workers: [Result()])
    monkeypatch.setattr(cwv_eval, "candidate_agreement",
                        lambda scores, means: {"n": int(scores.size), "first": float(scores[0])})

    def never(entry):
        raise AssertionError("per-record score_fn must not be called when a batch scorer exists")

    def many(batch):
        calls.append(len(batch))
        return [np.full(int(e["public"].shape[0]), float(i)) for i, e in enumerate(batch)]

    out = cwv_eval.candidate_pass([("shard", None)], score_fn=never, score_many_fn=many,
                                  public_head=None, prior=None, device="cpu", workers=1,
                                  rank_limit=None, history=False)
    assert calls == [len(entries)]
    rows = out["agreement"]["cwv"]
    assert [r["first"] for r in rows] == [float(i) for i in range(len(entries))]
    assert [r["n"] for r in rows] == [int(e["public"].shape[0]) for e in entries]


def test_batched_scorer_refuses_a_wrong_count(monkeypatch):
    model, entries = _entries()

    class Result:
        source_ref = []
        deal_key = []
        decision_obs = np.zeros((0, 1), dtype=np.float32)
        search = entries

    monkeypatch.setattr(cwv_eval, "iter_shard_results", lambda tasks, workers: [Result()])
    with pytest.raises(ValueError, match="one score array per record"):
        cwv_eval.candidate_pass([("shard", None)], score_fn=None,
                                score_many_fn=lambda batch: [], public_head=None, prior=None,
                                device="cpu", workers=1, rank_limit=None, history=False)
