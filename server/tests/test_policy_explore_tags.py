"""#676 strategy D: policy rows tag the exploration draws that beat the shortlist, and the
trainer can upweight them.  Both are additive and default-off.

What the flag literally counts (``policy_prior.explore_tags_of``):
  0  no ballot slot is a member of the record's ``exploration.added``;
  1  a draw is in the ballot but no draw holds a FINITE value strictly above the best
     finite non-draw value (ties, a draw the search did not value, a ballot whose
     non-draw side has no values, and plain losses);
  2  a draw holds the strictly highest search value in the ballot ("beat the shortlist"),
     with ``explore_margin`` = that value minus the best non-draw value (NaN otherwise).

Witnesses: the tag on hand-built records; the chunk arrays and manifest counts; a tag-less
chunk loading with zeros and ``explore_tags: false``; the W=1.0 identity (the loss tensors
are the pre-#676 ones, and an explicit all-ones weight gives the same numbers); the
trainer's refusal of W != 1.0 on an untagged extract; the receipt fields.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.train import policy_prior as pp  # noqa: E402
from shengji.train import train_cwv  # noqa: E402
from shengji.train.policy_rows import (PolicyRows, PolicyRowsStream, explore_row_weights,  # noqa: E402
                                       policy_losses)
from tests.test_cwv_train import THIRDS, store_dir, other_dir, records  # noqa: F401, E402

NAN = float("nan")


# ------------------------------------------------------------------ the tag on hand-built records

def test_flag_0_without_a_draw_in_the_ballot():
    ballot = [["S3"], ["S7"], ["SA"]]
    assert pp.explore_tags_of(ballot, [1.0, 2.0, 3.0], []) == (0, pytest.approx(NAN, nan_ok=True))
    # a draw the record names but the ballot does not carry is not "in the ballot"
    flag, margin = pp.explore_tags_of(ballot, [1.0, 2.0, 3.0], [["HK"]])
    assert flag == 0 and math.isnan(margin)


def test_flag_1_when_the_draw_is_in_the_ballot_but_does_not_beat_it():
    ballot = [["S3"], ["S7"], ["SA"]]
    # plain loss
    assert pp.explore_tags_of(ballot, [1.0, 2.0, 3.0], [["S7"]])[0] == 1
    # an exact tie is not a beat (the issue counts out-valued, strictly)
    assert pp.explore_tags_of(ballot, [1.0, 3.0, 3.0], [["S7"]])[0] == 1
    # the draw the search did not value cannot have beaten anything
    assert pp.explore_tags_of(ballot, [1.0, NAN, 3.0], [["S7"]])[0] == 1
    # a ballot whose non-draw side has no finite value cannot have BEEN beaten
    assert pp.explore_tags_of(ballot, [NAN, 5.0, NAN], [["S7"]])[0] == 1
    for means in ([1.0, 2.0, 3.0], [1.0, 3.0, 3.0], [1.0, NAN, 3.0], [NAN, 5.0, NAN]):
        assert math.isnan(pp.explore_tags_of(ballot, means, [["S7"]])[1])


def test_flag_2_with_the_margin_over_the_best_non_draw_value():
    ballot = [["S3", "S7"], ["S7", "S8"], ["S9", "SA"], ["SK", "SA"]]
    # the LAST two slots are the draws (the pv path appends them); the best draw wins by 0.133
    flag, margin = pp.explore_tags_of(ballot, [-1.0, -0.9, -0.95, -0.767], [["SA", "SK"], ["S9", "SA"]])
    assert flag == 2 and margin == pytest.approx(0.133)
    # membership is by action identity, not list position or card order
    flag, margin = pp.explore_tags_of(ballot, [-0.5, -0.9, -0.95, -0.767], [["S7", "S3"]])
    assert flag == 2 and margin == pytest.approx(0.267)
    # two draws, one of them the worst slot: the best draw still beats the shortlist
    flag, margin = pp.explore_tags_of(ballot, [0.0, 0.5, -9.0, 0.1], [["S7", "S8"], ["S9", "SA"]])
    assert flag == 2 and margin == pytest.approx(0.4)
    # the SHORTLIST is production_ballot: a draw production admitted on its own score is the
    # shortlist's candidate, so its win is not a miss (flag 0 when it was the only draw ...)
    production = [["S3", "S7"], ["S7", "S8"], ["S9", "SA"]]
    flag, margin = pp.explore_tags_of(ballot, [0.0, 0.5, -9.0, 0.1], [["S7", "S8"]], production=production)
    assert flag == 0 and math.isnan(margin)
    # (... and the other draw is measured against production's list, which includes it)
    flag, margin = pp.explore_tags_of(ballot, [0.0, 0.5, -9.0, 0.1], [["S7", "S8"], ["SA", "SK"]], production=production)
    assert flag == 1 and math.isnan(margin)
    flag, margin = pp.explore_tags_of(ballot, [0.0, 0.5, -9.0, 0.75], [["S7", "S8"], ["SA", "SK"]], production=production)
    assert flag == 2 and margin == pytest.approx(0.25)


def test_a_widened_non_draw_action_is_neither_production_nor_a_draw():
    """Codex HOLD on #684: with an explicit production_ballot the shortlist is EXACTLY that
    list.  Ballot S3/H3/C3 with means 0/2/1, exploration C3, production [S3]: H3 is a widened
    action (neither), so the draw C3 = 1 beats production's best S3 = 0 -> flag 2, margin 1."""
    ballot = [["S3"], ["H3"], ["C3"]]
    flag, margin = pp.explore_tags_of(ballot, [0.0, 2.0, 1.0], [["C3"]], production=[["S3"]])
    assert flag == 2 and margin == pytest.approx(1.0)
    # the widened action never counts on the draw side either: an unvalued production slot
    # cannot have been beaten even though H3 holds a value
    flag, margin = pp.explore_tags_of(ballot, [NAN, 2.0, 1.0], [["C3"]], production=[["S3"]])
    assert flag == 1 and math.isnan(margin)
    # without a production_ballot the fallback (ballot minus draws) still treats H3 as the shortlist's
    flag, margin = pp.explore_tags_of(ballot, [0.0, 2.0, 1.0], [["C3"]])
    assert flag == 1 and math.isnan(margin)
    # empty ballot entries (the ones ballot_tensors drops) are skipped, not counted as slots
    flag, margin = pp.explore_tags_of([[], ["S3"], ["S7"]], [99.0, 1.0, 2.0], [["S7"]])
    assert flag == 2 and margin == pytest.approx(1.0)


def test_tags_from_a_record_shaped_like_a_trajectory_decision():
    """The extractor's inputs: the raw ballot, the slot-aligned means it already builds, and
    ``exploration.added`` exactly as ``harvest.trajectory`` writes it."""
    rec = {"ballot": [["S3", "S7", "S8", "S9"], ["S3", "S7", "S8", "SK"], ["S3", "S7", "SA", "SK"]],
           "production_ballot": [["S3", "S7", "S8", "S9"], ["S3", "S7", "S8", "SK"]],
           "exploration": {"added": [["S3", "S7", "SA", "SK"]], "pool_count": 14, "rate": 0.1},
           "action_values": {"eligible_indices": [0, 1, 2], "means": [-0.99, -0.96, -0.80],
                             "perspective": "acting-team",
                             "units": "expected-signed-level-half-integer"}}
    from shengji.train.cwv_data import search_means_points
    idx, means, _units = search_means_points(rec)
    means_raw = [NAN] * len(rec["ballot"])
    for i, m in zip(idx, means):
        means_raw[i] = m
    flag, margin = pp.explore_tags_of(rec["ballot"], means_raw, rec["exploration"]["added"],
                                      production=rec["production_ballot"])
    assert flag == 2
    # the margin is on the SAME scale the row's vals carry (the points temperature scale)
    assert margin == pytest.approx(means_raw[2] - means_raw[1])
    # and a record without an exploration block is flag 0
    assert pp.explore_tags_of(rec["ballot"], means_raw, (rec.get("nothing") or {}).get("added") or [])[0] == 0


def test_tag_arrays_and_counts_read_rows_without_the_fields_as_zero():
    meta = [{"explore_flag": 2, "explore_margin": 0.25}, {"explore_flag": 1, "explore_margin": None},
            {}, {"explore_flag": 0, "explore_margin": None}]
    flag, margin = pp.explore_tag_arrays(meta)
    assert flag.dtype == np.int8 and margin.dtype == np.float32
    assert flag.tolist() == [2, 1, 0, 0]
    assert margin[0] == pytest.approx(0.25) and np.isnan(margin[1:]).all()
    assert pp.explore_flag_counts(flag) == {"0": 2, "1": 1, "2": 1}


# ------------------------------------------------------------------ chunks, manifest, loaders

def _meta_row(ballot, taken, key, flag=None, margin=None, means=None):
    m = {"ballot": ballot, "taken": taken, "deal": key[-4:], "deal_key": key,
         "means": means if means is not None else [NAN] * len(ballot), "units": pp.NO_SEARCH_VALUES}
    if flag is not None:
        m["explore_flag"] = flag
        m["explore_margin"] = margin
    return m


def _chunk_dir(tmp_path, rows, *, with_tags: bool, manifest_tags: bool | None = None):
    """A chunked extract of ``rows`` metadata; ``with_tags`` False writes the pre-#676 arrays only
    and omits the manifest keys (an old extract), unless ``manifest_tags`` overrides the latter."""
    d = tmp_path / ("tagged" if with_tags else "untagged"); d.mkdir()
    X = [np.zeros(pp.INPUT_DIM, np.float32) for _ in rows]
    Y = [np.zeros(54, np.float32) for _ in rows]
    chunk = pp._write_chunk(d, 0, X, Y, rows)
    if not with_tags:
        z = np.load(d / chunk["file"])
        arrays = {k: z[k] for k in z.files if k not in ("explore_flag", "explore_margin")}
        np.savez_compressed(d / chunk["file"], **arrays)
        chunk["sha256"] = hashlib.sha256(open(d / chunk["file"], "rb").read()).hexdigest()
        chunk.pop("explore_flag_counts")
    man = {"schema": pp.CHUNK_SCHEMA, "input_dim": pp.INPUT_DIM, "enc_version": 2, "rows": len(rows),
           "chunks": [chunk], "deals": chunk["deals"], "deal_key_schema": "shengji-value-deal-key-v1"}
    if with_tags if manifest_tags is None else manifest_tags:
        man["explore_tags"] = True
        man["explore_flag_counts"] = chunk.get("explore_flag_counts")
    json.dump(man, open(d / "manifest.json", "w"))
    return d


ROWS = [_meta_row([[0], [1]], [1], "deck:a", 2, 0.5), _meta_row([[0], [1]], [0], "deck:a", 1, None),
        _meta_row([[2]], [2], "deck:b", 0, None), _meta_row([[3], [4]], [4], "deck:b", 2, 0.125)]


def test_chunk_carries_the_tag_arrays_and_their_counts(tmp_path):
    d = _chunk_dir(tmp_path, ROWS, with_tags=True)
    z = np.load(d / "chunk-00000.npz")
    assert z["explore_flag"].dtype == np.int8 and z["explore_flag"].tolist() == [2, 1, 0, 2]
    assert z["explore_margin"].dtype == np.float32
    assert z["explore_margin"][[0, 3]].tolist() == pytest.approx([0.5, 0.125]) and np.isnan(z["explore_margin"][[1, 2]]).all()
    man = json.load(open(d / "manifest.json"))
    assert man["explore_tags"] is True and man["explore_flag_counts"] == {"0": 1, "1": 1, "2": 2}
    # the schema string did not move: an older reader keys on it
    assert man["schema"] == pp.CHUNK_SCHEMA == "shengji-policy-rows-chunked-v1"
    s = PolicyRowsStream(d)
    assert s.explore_tags is True and s.identity["explore_tags"] is True
    assert s.identity["explore_flag_counts"] == {"0": 1, "1": 1, "2": 2}
    got = {}
    for b in s.batches(3, np.random.default_rng(0)):
        t = s.tensors(b, "cpu")
        assert t["explore_flag"].dtype == torch.long and t["explore_flag"].shape == (len(b["x"]),)
        for k, f, m in zip(b["tgt"].tolist(), b["explore_flag"].tolist(), b["explore_margin"].tolist()):
            got.setdefault((k, f), []).append(m)
    # ballot_tensors' tgt per row is [1, 0, 0, 1]; the flags ride along with the rows
    assert sorted(got) == [(0, 0), (0, 1), (1, 2)] and sorted(got[(1, 2)]) == pytest.approx([0.125, 0.5])
    # the exposure rule still applies to the tags: dropping deck:a drops its flag-2 row
    fewer = PolicyRowsStream(d, exclude={"deck:a"})
    assert fewer.identity["explore_flag_counts"] == {"0": 1, "1": 0, "2": 1}


def test_a_tag_less_chunk_loads_with_zeros_and_says_so(tmp_path):
    """Additive: an extract written before the tags has no arrays and no manifest keys; the
    stream fills flag 0 / margin NaN and reports ``explore_tags: False`` (never True)."""
    d = _chunk_dir(tmp_path, ROWS, with_tags=False)
    man = json.load(open(d / "manifest.json"))
    assert "explore_tags" not in man and "explore_flag" not in np.load(d / "chunk-00000.npz").files
    s = PolicyRowsStream(d)
    assert s.explore_tags is False and s.identity["explore_tags"] is False
    assert s.identity["explore_flag_counts"] == {"0": 4, "1": 0, "2": 0}
    for b in s.batches(10, np.random.default_rng(0)):
        assert b["explore_flag"].dtype == np.int8 and not b["explore_flag"].any()
        assert np.isnan(b["explore_margin"]).all()
        assert s.tensors(b, "cpu")["explore_flag"].tolist() == [0] * len(b["x"])
    # a manifest that CLAIMS tags over a chunk without them is downgraded, not believed
    (tmp_path / "claim").mkdir()
    d2 = _chunk_dir(tmp_path / "claim", ROWS, with_tags=False, manifest_tags=True)
    assert PolicyRowsStream(d2).explore_tags is False


def test_the_monolithic_loader_carries_or_fills_the_tags(tmp_path):
    def write(prefix, rows):
        np.savez_compressed(str(prefix) + ".npz", X=np.zeros((len(rows), pp.INPUT_DIM), np.float32),
                            Y=np.zeros((len(rows), 54), np.float32))
        with open(str(prefix) + ".meta.jsonl", "w") as fh:
            for m in rows:
                fh.write(json.dumps(m) + "\n")
        return str(prefix)
    tagged = PolicyRows(write(tmp_path / "t", ROWS))
    assert tagged.explore_tags is True and tagged.identity["explore_flag_counts"] == {"0": 1, "1": 1, "2": 2}
    b = next(tagged.batches(10, np.random.default_rng(0)))
    assert sorted(b["explore_flag"].tolist()) == [0, 1, 2, 2]
    old = [{k: v for k, v in m.items() if not k.startswith("explore_")} for m in ROWS]
    plain = PolicyRows(write(tmp_path / "p", old))
    assert plain.explore_tags is False and plain.identity["explore_flag_counts"] == {"0": 4, "1": 0, "2": 0}
    assert not next(plain.batches(10, np.random.default_rng(0)))["explore_flag"].any()


def test_extract_on_a_real_store_writes_the_tags_and_the_manifest_counts_add_up(store_dir, tmp_path, monkeypatch):  # noqa: F811
    """The fixture store is generated with explore_rate 0.5 / explore_k 2, so draws exist."""
    out = tmp_path / "chunked"
    pp.extract(out, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1, chunk_rows=64)
    man = json.load(open(out / "manifest.json"))
    assert man["explore_tags"] is True and man["explore_flag_names"] == {"0": "no_draw", "1": "draw_in_ballot", "2": "draw_beat_shortlist"}
    counts = man["explore_flag_counts"]
    assert sum(counts.values()) == man["rows"] and counts["1"] + counts["2"] > 0, counts
    per_chunk = {k: sum(c["explore_flag_counts"][k] for c in man["chunks"]) for k in ("0", "1", "2")}
    assert per_chunk == counts
    # the arrays agree with the counts and with the per-row rule re-run on the records
    flags = np.concatenate([np.load(out / c["file"])["explore_flag"] for c in man["chunks"]])
    margins = np.concatenate([np.load(out / c["file"])["explore_margin"] for c in man["chunks"]])
    assert pp.explore_flag_counts(flags) == counts
    assert np.isfinite(margins[flags == 2]).all() and (margins[flags == 2] > 0).all()
    assert np.isnan(margins[flags < 2]).all()
    s = PolicyRowsStream(out)
    assert s.identity["explore_tags"] is True and s.identity["explore_flag_counts"] == counts
    # the single-file extract writes the same per-row fields and the summary counts
    flat = tmp_path / "flat"
    summary = pp.extract(flat, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    assert summary["explore_tags"] is True and summary["explore_flag_counts"] == counts
    assert PolicyRows(flat).identity["explore_flag_counts"] == counts
    # Differential producer-to-consumer witness against the previous eager map.
    def eager(ex, args, workers):
        yield from ex.map(pp._shard_rows, args, chunksize=4)
    monkeypatch.setattr(pp, '_bounded_shard_rows', eager)
    reference = tmp_path / 'reference'
    pp.extract(reference, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0,
               max_rows=400, workers=2, chunk_rows=64)
    ref = json.loads((reference / 'manifest.json').read_text())
    assert man == ref
    for chunk in man['chunks']:
        assert (out / chunk['file']).read_bytes() == (reference / chunk['file']).read_bytes()


@pytest.mark.parametrize('fail', [False, True])
def test_bounded_shards_preserve_order_and_cancel_unconsumed_tasks(fail):
    from concurrent.futures import Future
    class Pool:
        def __init__(self):
            self.calls = []
        def submit(self, fn, batch):
            f = Future()
            self.calls.append((batch, f))
            # Only the first task finishes; later tasks stay pending to prove
            # close/error cancellation without timing-sensitive real threads.
            if len(self.calls) == 1:
                if fail:
                    f.set_exception(ValueError('bad shard'))
                else:
                    f.set_result(list(batch))
            return f
    pool = Pool()
    rows = pp._bounded_shard_rows(pool, iter(range(1000)), 2)
    if fail:
        with pytest.raises(ValueError, match='bad shard'):
            next(rows)
    else:
        assert [next(rows) for _ in range(4)] == [0, 1, 2, 3]
        rows.close()
    assert [batch for batch, _ in pool.calls] == [list(range(i, i+4)) for i in range(0, 16, 4)]
    assert all(f.cancelled() for _, f in pool.calls[1:])


def test_bounded_shards_refill_in_order_and_handle_empty_input():
    from concurrent.futures import Future
    class Pool:
        def submit(self, fn, batch):
            f = Future()
            f.set_result(list(batch))
            return f
    assert list(pp._bounded_shard_rows(Pool(), [], 2)) == []
    assert list(pp._bounded_shard_rows(Pool(), range(101), 2)) == list(range(101))


# ------------------------------------------------------------------ the W=1.0 identity

class _Head:
    """A deterministic 'model' whose logits depend on x, so a weight that moved anything shows."""
    def __init__(self):
        torch.manual_seed(0)
        self.lin = torch.nn.Linear(6, 54)

    def features_flat(self, x):
        return x

    def policy_logits(self, f):
        return self.lin(f)


def _batch():
    g = torch.Generator().manual_seed(1)
    x = torch.randn(5, 6, generator=g)
    y = (torch.rand(5, 54, generator=g) > 0.7).float()
    ball = torch.tensor([[[0, 1], [2, -1], [3, -1]], [[4, -1], [5, 6], [-1, -1]], [[7, -1], [8, -1], [-1, -1]],
                         [[9, -1], [10, 11], [12, -1]], [[13, -1], [-1, -1], [-1, -1]]], dtype=torch.int8)
    mask = torch.tensor([[1, 1, 1], [1, 1, 0], [1, 1, 0], [1, 1, 1], [1, 0, 0]], dtype=torch.bool)
    tgt = torch.tensor([2, 0, -1, 1, 0])                   # row 2 has no ballot target
    vals = torch.tensor([[1.0, 2.0, 3.0], [1.0, 0.5, NAN], [NAN, NAN, NAN], [0.2, 0.1, 0.3], [1.0, NAN, NAN]])
    flag = torch.tensor([2, 0, 2, 1, 0])
    return {"x": x, "y": y, "ball": ball, "mask": mask, "tgt": tgt, "vals": vals, "explore_flag": flag}


@pytest.mark.parametrize("soft", [False, True])
def test_weight_one_is_the_unweighted_loss_to_the_bit(soft):
    """Two identities.  (a) ``explore_row_weights(flag, 1.0)`` is None, so the trainer calls
    ``policy_losses`` exactly as before the flag existed -- whose reductions are the pre-#676
    expressions, re-stated here literally and compared with torch.equal (bit-identical).
    (b) an explicit all-ones vector through the weighted path gives the same listwise tensor
    to the bit and the same BCE to one float32 ulp (6e-8 here: torch's ``mean`` sums the
    b x 54 elements in one order, the weighted path averages per-row means) -- which is WHY
    the trainer passes None at W=1.0 rather than a vector of ones."""
    t = _batch(); m = _Head()
    assert explore_row_weights(t["explore_flag"], 1.0) is None
    kw = dict(listwise_weight=1.0, soft_targets=soft, soft_temperature=1.0)
    bce0, lw0, logits = policy_losses(m, t, **kw)
    # (a) the pre-#676 expressions
    assert torch.equal(bce0, torch.nn.functional.binary_cross_entropy_with_logits(logits, t["y"]))
    if soft:
        ref = pp.listwise_loss_soft(logits, t["ball"], t["mask"], t["tgt"], t["vals"], temperature=1.0)
    else:
        ref = pp.listwise_loss(logits, t["ball"], t["mask"], t["tgt"])
    assert torch.equal(lw0, ref)
    # (b) all-ones weights
    ones = torch.ones(5)
    bce1, lw1, _ = policy_losses(m, t, **kw, row_weight=ones)
    assert torch.equal(lw0, lw1), (lw0, lw1)
    assert torch.allclose(bce0, bce1, rtol=0, atol=2e-7) and abs(float(bce0 - bce1)) <= 1.2e-7, (bce0, bce1)
    # a batch with NO flag-2 rows under W != 1 gets the all-ones vector: the same numbers again
    none = {**t, "explore_flag": torch.tensor([0, 1, 0, 1, 0])}
    w = explore_row_weights(none["explore_flag"], 3.0)
    assert torch.equal(w, ones)
    bce2, lw2, _ = policy_losses(m, none, **kw, row_weight=w)
    assert torch.equal(bce1, bce2) and torch.equal(lw1, lw2)


@pytest.mark.parametrize("soft", [False, True])
def test_a_weight_above_one_moves_both_terms_toward_the_flag_2_rows(soft):
    t = _batch(); m = _Head()
    kw = dict(listwise_weight=1.0, soft_targets=soft, soft_temperature=1.0)
    w = explore_row_weights(t["explore_flag"], 4.0)
    assert w.tolist() == [4.0, 1.0, 4.0, 1.0, 1.0]
    bce0, lw0, logits = policy_losses(m, t, **kw)
    bce4, lw4, _ = policy_losses(m, t, **kw, row_weight=w)
    assert not torch.equal(bce0, bce4) and not torch.equal(lw0, lw4)
    # the weighted BCE is the weighted mean of per-row card means, exactly
    per_row = torch.nn.functional.binary_cross_entropy_with_logits(logits, t["y"], reduction="none").mean(1)
    assert torch.allclose(bce4, (per_row * w).sum() / w.sum())
    # the listwise term weights only the rows WITH a ballot target (row 2 is flag 2 but has none)
    ok = t["tgt"] >= 0
    if not soft:
        b = t["ball"][ok].long()
        gathered = (logits[ok].gather(1, b.clamp(min=0).reshape(b.shape[0], -1)).reshape(b.shape) * (b >= 0)).sum(2)
        scores = gathered.masked_fill(~t["mask"][ok], -1e9)
        ce = torch.nn.functional.cross_entropy(scores, t["tgt"][ok], reduction="none")
        assert torch.allclose(lw4, (ce * w[ok]).sum() / w[ok].sum())
    # gradients flow through the weighted path
    (bce4 + lw4).backward()
    assert m.lin.weight.grad is not None and torch.isfinite(m.lin.weight.grad).all()


# ------------------------------------------------------------------ the trainer: validation, refusal, receipt

def test_the_flag_needs_a_policy_head_and_a_positive_finite_weight():
    base = dict(data=["/nonexistent"], policy_head=True, policy_rows="x")
    for bad in (0.0, -2.0, NAN, float("inf")):
        with pytest.raises(train_cwv.TrainError, match="--policy-explore-weight must be finite and > 0"):
            train_cwv.build_config(**base, policy_explore_weight=bad)
    with pytest.raises(train_cwv.TrainError, match="need --policy-head"):
        train_cwv.build_config(data=["/nonexistent"], policy_head=False, policy_explore_weight=2.0)
    cfg = train_cwv.build_config(**base, policy_explore_weight=2.5)
    assert cfg["policy_explore_weight"] == 2.5
    assert train_cwv.build_config(**base)["policy_explore_weight"] == 1.0
    assert train_cwv.build_config(data=["/nonexistent"])["policy_explore_weight"] == 1.0


def test_the_trainer_refuses_a_weight_on_an_untagged_extract_and_records_the_tags(store_dir, tmp_path):  # noqa: F811
    """A run asked for the weighted arm on an extract that cannot be weighted must refuse
    (the --policy-soft-targets pattern), never train the unweighted thing under the label."""
    tagged = tmp_path / "tagged"
    pp.extract(tagged, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1, chunk_rows=64)
    from scripts.compose_policy_rows import compose
    composed = tmp_path / "composed"
    compose(composed, [('fixture', tagged)])
    # strip the tags: the chunk arrays and the manifest keys, re-hashing each chunk
    untagged = tmp_path / "untagged"; untagged.mkdir()
    man = json.load(open(tagged / "manifest.json"))
    for c in man["chunks"]:
        z = np.load(tagged / c["file"])
        np.savez_compressed(untagged / c["file"], **{k: z[k] for k in z.files if not k.startswith("explore_")})
        c["sha256"] = hashlib.sha256(open(untagged / c["file"], "rb").read()).hexdigest()
        c.pop("explore_flag_counts")
    for k in ("explore_tags", "explore_flag_names", "explore_flag_counts"):
        man.pop(k)
    json.dump(man, open(untagged / "manifest.json", "w"))
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32,
              log=None, cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50, encoder_version=2,
              policy_head=True, policy_batch_fraction=0.5, **THIRDS)
    with pytest.raises(train_cwv.TrainError, match="--policy-explore-weight 2.0: this extract carries no exploration tags"):
        train_cwv.train(out=tmp_path / "refused", policy_rows=str(untagged), policy_explore_weight=2.0, **kw)
    assert not (tmp_path / "refused" / "receipt.json").exists()
    # the default on the untagged extract trains (nothing changed for existing extracts)
    r0 = train_cwv.train(out=tmp_path / "plain", policy_rows=str(untagged), **kw)
    assert r0["config"]["policy_explore_weight"] == 1.0 and r0["policy_head"]["explore_weight"] == 1.0
    assert r0["policy_head"]["explore_tags"] is False
    assert r0["policy_head"]["explore_flag_counts"] == {"0": r0["policy_head"]["rows"]["rows_used"], "1": 0, "2": 0}
    # the weighted arm on the tagged extract records the weight and the (post-exclusion) counts
    r2 = train_cwv.train(out=tmp_path / "weighted", policy_rows=str(composed), policy_explore_weight=2.0, **kw)
    assert r2["config"]["policy_explore_weight"] == 2.0 and r2["policy_head"]["explore_weight"] == 2.0
    assert r2["policy_head"]["explore_tags"] is True
    counts = r2["policy_head"]["explore_flag_counts"]
    assert sum(counts.values()) == r2["policy_head"]["rows"]["rows_used"]
    assert r2["epochs"][0]["train"]["policy_rows"] > 0
    receipt = json.load(open(tmp_path / "weighted" / "receipt.json"))
    assert receipt["config"]["policy_explore_weight"] == 2.0 and receipt["policy_head"]["explore_flag_counts"] == counts


def _compose_part(root, *, tagged=True):
    root.mkdir()
    part = _chunk_dir(root, ROWS, with_tags=tagged)
    manifest = json.loads((part / 'manifest.json').read_text())
    if tagged:
        manifest['explore_flag_names'] = {str(k): v for k, v in pp.EXPLORE_FLAG_NAMES.items()}
    (part / 'manifest.json').write_text(json.dumps(manifest))
    return part


def test_composer_cli_preserves_tags_bytes_and_post_exclusion_weights(tmp_path, capsys):
    from scripts.compose_policy_rows import main
    first, second = _compose_part(tmp_path / 'first'), _compose_part(tmp_path / 'second')
    originals = [(p / 'chunk-00000.npz').read_bytes() for p in (first, second)]
    out = tmp_path / 'joined'
    main([str(out), '--part', 'first', str(first), '--part', 'second', str(second)])
    assert json.loads(capsys.readouterr().out)['explore_flag_counts'] == {'0': 2, '1': 2, '2': 4}
    for tag, path, original in zip(('first', 'second'), (first, second), originals):
        link = out / f'{tag}-chunk-00000.npz'
        assert link.is_symlink() and link.resolve() == path / 'chunk-00000.npz'
        assert link.read_bytes() == original
    data = PolicyRowsStream(out, exclude={'deck:a'})
    assert data.identity['explore_tags'] is True
    assert data.identity['explore_flag_counts'] == {'0': 2, '1': 0, '2': 2}
    batch = next(data.batches(10, np.random.default_rng(0)))
    weights = explore_row_weights(data.tensors(batch, 'cpu')['explore_flag'], 3.0)
    assert sorted(weights.tolist()) == [1.0, 1.0, 3.0, 3.0]


@pytest.mark.parametrize('bad', ['untagged', 'encoder', 'counts', 'missing_array', 'scale', 'escape'])
def test_composer_refuses_bad_parts_before_creating_output(tmp_path, bad):
    from scripts.compose_policy_rows import compose
    first = _compose_part(tmp_path / 'first')
    second = _compose_part(tmp_path / 'second', tagged=bad != 'untagged')
    path = second / 'manifest.json'
    manifest = json.loads(path.read_text())
    if bad == 'encoder':
        manifest['enc_version'] = 4
    elif bad == 'counts':
        manifest['explore_flag_counts']['2'] += 1
    elif bad == 'missing_array':
        chunk = second / 'chunk-00000.npz'
        with np.load(chunk) as arrays:
            kept = {k: arrays[k] for k in arrays.files if k != 'explore_margin'}
        np.savez_compressed(chunk, **kept)
    elif bad == 'scale':
        manifest['values_scale'] = 'levels'
    elif bad == 'escape':
        manifest['chunks'][0]['file'] = '../chunk-00000.npz'
    path.write_text(json.dumps(manifest))
    out = tmp_path / 'refused'
    with pytest.raises(ValueError):
        compose(out, [('first', first), ('second', second)])
    assert not out.exists()


def test_composer_refuses_duplicate_inputs_and_existing_output(tmp_path):
    from scripts.compose_policy_rows import compose
    part = _compose_part(tmp_path / 'part')
    out = tmp_path / 'out'
    for parts in ([], [('same', part), ('same', part)],
                  [('a', part), ('b', part)], [('../bad', part)]):
        with pytest.raises(ValueError):
            compose(out, parts)
        assert not out.exists()
    second = _compose_part(tmp_path / 'second')
    (second / 'chunk-00000.npz').rename(second / 'b-chunk-00000.npz')
    manifest = json.loads((second / 'manifest.json').read_text())
    manifest['chunks'][0]['file'] = 'b-chunk-00000.npz'
    (second / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='names collide'):
        compose(out, [('a-b', part), ('a', second)])
    assert not out.exists()
    out.mkdir()
    (out / 'sentinel').write_text('preserve')
    with pytest.raises(ValueError, match='already exists'):
        compose(out, [('a', part)])
    assert (out / 'sentinel').read_text() == 'preserve'


def test_cli_parses_and_forwards_the_weight():
    args = train_cwv.build_parser().parse_args(["train", "--out", "x", "--data", "d", "--policy-explore-weight", "3"])
    assert args.policy_explore_weight == 3.0
    assert train_cwv.build_parser().parse_args(["train", "--out", "x", "--data", "d"]).policy_explore_weight == 1.0
    import inspect
    assert "policy_explore_weight=args.policy_explore_weight" in inspect.getsource(train_cwv.main)
    assert "policy_explore_weight" in inspect.signature(train_cwv.train).parameters
