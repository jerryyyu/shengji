"""Issue #542 lever 4: the candidate pass scores the PUBLIC HEAD once per shard, not once
per search record.  Measured 2026-09-20 on 200 runA shards: 24,468 per-record forwards took
25.5 s of a 37 s pass (device round-trips for a handful of rows each); the workers finish in
12 s underneath.  The batched values must equal the per-record values up to float batch-shape
effects, in record order; SHENGJI_CWV_BATCHED_PUBLIC=0 restores the per-record path."""
import numpy as np
import pytest
import torch

from shengji.rl.encode_versions import OBS_DIM_BY_VERSION
from shengji.train import cwv_eval
from shengji.train.model import ValuePriorNet
from tests.test_cwv_candidate_batching import _entries

_REAL_PUBLIC_VALUES = cwv_eval.public_values   # captured once: _pass is monkeypatched twice per test


def _head(seed=3):
    torch.manual_seed(seed)
    return ValuePriorNet({"obs_dim": OBS_DIM_BY_VERSION[2], "trunk": [24, 12]}).eval()


class _Result:
    source_ref = []
    deal_key = []
    decision_obs = np.zeros((0, 1), dtype=np.float32)

    def __init__(self, search):
        self.search = search


def _pass(monkeypatch, head, entries, batched):
    monkeypatch.setenv("SHENGJI_CWV_BATCHED_PUBLIC", "1" if batched else "0")
    monkeypatch.setattr(cwv_eval, "iter_shard_results", lambda tasks, workers: [_Result(entries)])
    calls = []

    def counting(model, obs, device, **kw):
        calls.append(int(np.asarray(obs).shape[0]))
        return _REAL_PUBLIC_VALUES(model, obs, device, **kw)
    monkeypatch.setattr(cwv_eval, "public_values", counting)
    seen = []
    monkeypatch.setattr(cwv_eval, "candidate_agreement",
                        lambda scores, means: seen.append(np.array(scores, copy=True)) or {"n": int(scores.size)})
    out = cwv_eval.candidate_pass([("shard", None)], score_fn=None, score_many_fn=None,
                                  public_head=head, prior=None, device="cpu", workers=1,
                                  rank_limit=None, history=False)
    return out, calls, seen


def test_one_public_head_forward_per_shard_gives_the_per_record_values_in_order(monkeypatch):
    _model, entries = _entries(widths=(1, 3, 9, 2, 14, 5, 1, 8))
    head = _head()
    per_record, calls_one, seen_one = _pass(monkeypatch, head, entries, batched=False)
    batched, calls_many, seen_many = _pass(monkeypatch, head, entries, batched=True)
    assert calls_one == [int(e["public"].shape[0]) for e in entries]        # one forward per record
    assert calls_many == [sum(int(e["public"].shape[0]) for e in entries)]  # one forward per shard
    assert len(seen_one) == len(seen_many) == len(entries)
    for e, a, b in zip(entries, seen_one, seen_many):
        assert b.shape == a.shape == (int(e["public"].shape[0]),)
        np.testing.assert_allclose(b, a, rtol=0, atol=1e-6)
    assert per_record["search_records"] == batched["search_records"] == len(entries)


def test_terminal_candidates_keep_their_terminal_level_under_batching(monkeypatch):
    _model, entries = _entries(widths=(4, 6))
    entries[0]["terminal"][1] = True
    entries[0]["terminal_level"][1] = 2.0
    head = _head()
    _out, _calls, seen = _pass(monkeypatch, head, entries, batched=True)
    assert seen[0][1] == cwv_eval.pt0_level(2.0)


def test_a_wrong_row_count_from_the_head_is_refused(monkeypatch):
    _model, entries = _entries(widths=(2, 3))
    head = _head()
    monkeypatch.setenv("SHENGJI_CWV_BATCHED_PUBLIC", "1")
    monkeypatch.setattr(cwv_eval, "iter_shard_results", lambda tasks, workers: [_Result(entries)])
    monkeypatch.setattr(cwv_eval, "public_values", lambda model, obs, device, **kw: np.zeros(1))
    with pytest.raises(ValueError, match="one value per candidate row"):
        cwv_eval.candidate_pass([("shard", None)], score_fn=None, score_many_fn=None,
                                public_head=head, prior=None, device="cpu", workers=1,
                                rank_limit=None, history=False)
