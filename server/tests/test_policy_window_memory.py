"""Independent padding and lifetime witnesses for the policy-row window stream."""
from __future__ import annotations

import hashlib
import json
import sys
import weakref

import numpy as np
import pytest

from shengji.train import policy_prior as pp
from shengji.train import policy_rows as pr


def _old_pad2(a, width, fill):
    if a.shape[1] == width:
        return a
    out = np.full((a.shape[0], width), fill, dtype=a.dtype)
    out[:, :a.shape[1]] = a
    return out


def _old_pad2f(a, width, fill):
    if a.shape[1] >= width:
        return a[:, :width]
    out = np.full((a.shape[0], width), fill, np.float32)
    out[:, :a.shape[1]] = a
    return out


def _old_pad3(arrays, fill):
    b = max(a.shape[1] for a in arrays)
    c = max(a.shape[2] for a in arrays)
    padded = []
    for a in arrays:
        out = np.full((a.shape[0], b, c), fill, dtype=a.dtype)
        out[:, :a.shape[1], :a.shape[2]] = a
        padded.append(out)
    return np.concatenate(padded)


def test_single_allocation_padding_matches_literal_previous_oracle():
    balls = [np.arange(4, dtype=np.int8).reshape(2, 2, 1),
             np.arange(2, dtype=np.int16).reshape(1, 1, 2)]
    masks = [np.array([[True, False], [False, True]], dtype=bool),
             np.array([[1]], dtype=np.int8)]
    vals = [np.array([[1.00000001], [np.nan]], dtype=np.float64),
            np.array([[2.0, 3.0]], dtype=np.float64)]

    np.testing.assert_array_equal(pr._pad_concat(balls, -1), _old_pad3(balls, -1))
    np.testing.assert_array_equal(pr._pad2_concat(masks, 2, False),
                                  np.concatenate([_old_pad2(a, 2, False) for a in masks]))
    expected_vals = np.concatenate([_old_pad2f(a, 2, np.nan) for a in vals])
    got_vals = pr._pad2_concat(vals, 2, np.nan, float32_when_narrow=True)
    np.testing.assert_array_equal(got_vals, expected_vals)
    assert got_vals.dtype == expected_vals.dtype == np.float64


def _write_chunks(root, specs):
    root.mkdir()
    chunks = []
    for i, spec in enumerate(specs):
        n, b, c, with_vals, dtype = spec[:5]
        marker = sum(s[0] for s in specs[:i])
        x = np.zeros((n, pp.INPUT_DIM), np.float32)
        x[:, 0] = np.arange(marker, marker + n)
        y = np.full((n, 54), marker + 0.5, dtype=np.float16 if i % 2 else np.float32)
        ball = np.full((n, b, c), marker + i, dtype=dtype)
        mask = np.ones((n, b), dtype=bool if i % 2 else np.int8)
        tgt = np.arange(marker, marker + n, dtype=np.int16)
        keys = np.asarray([f"deck:{key}" for key in spec[5]], dtype="U16") if len(spec) > 5 else np.asarray([], dtype="U16")
        arrays = {"X": x, "Y": y, "ball": ball, "mask": mask, "tgt": tgt, "deal_key": keys}
        if with_vals:
            vals = np.full((n, max(1, b - 1)), np.nan, dtype=np.float64 if i == 3 else np.float32)
            if n:
                vals[:, 0] = np.arange(marker, marker + n) + 0.00000001
            arrays["vals"] = vals
        path = root / f"chunk-{i:05d}.npz"
        np.savez_compressed(path, **arrays)
        chunks.append({"file": path.name, "rows": n,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    json.dump({"schema": pp.CHUNK_SCHEMA, "input_dim": pp.INPUT_DIM, "enc_version": 2,
               "rows": sum(s[0] for s in specs), "chunks": chunks},
              (root / "manifest.json").open("w"))


def _rewrite_first_chunk_vals(root, vals):
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    chunk_path = root / manifest["chunks"][0]["file"]
    with np.load(chunk_path) as source:
        arrays = {name: source[name] for name in source.files}
    arrays["vals"] = vals
    np.savez_compressed(chunk_path, **arrays)
    manifest["chunks"][0]["sha256"] = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("vals_rows", [1, 3])
@pytest.mark.parametrize("exclude, limit", [(frozenset(), None), ({"deck:drop"}, 1)])
def test_constructor_refuses_optional_vals_row_count_mismatch_before_filtering_or_limit(
        tmp_path, vals_rows, exclude, limit):
    root = tmp_path / "malformed"
    _write_chunks(root, [(2, 2, 1, True, np.int8, ("drop", "keep"))])
    with np.load(root / "chunk-00000.npz") as source:
        vals = np.zeros((vals_rows, source["vals"].shape[1]), np.float32)
    _rewrite_first_chunk_vals(root, vals)

    with pytest.raises(ValueError, match="not row-aligned"):
        pr.PolicyRowsStream(root, exclude=exclude, limit=limit)


@pytest.mark.parametrize("vals", [np.float32(1.0), np.zeros(2, np.float32)])
def test_constructor_refuses_non_matrix_optional_vals(tmp_path, vals):
    root = tmp_path / "malformed-shape"
    _write_chunks(root, [(2, 2, 1, True, np.int8, ("a", "b"))])
    _rewrite_first_chunk_vals(root, vals)

    with pytest.raises(ValueError, match="not row-aligned"):
        pr.PolicyRowsStream(root)


def _oracle_batches(specs, *, exclude, window, batch_size, seed, limit=None):
    source = []
    for i, spec in enumerate(specs):
        n, b, c, with_vals, dtype = spec[:5]
        marker = sum(s[0] for s in specs[:i])
        p = {"X": np.zeros((n, pp.INPUT_DIM), np.float32),
             "Y": np.full((n, 54), marker + 0.5, dtype=np.float16 if i % 2 else np.float32),
             "ball": np.full((n, b, c), marker + i, dtype=dtype),
             "mask": np.ones((n, b), dtype=bool if i % 2 else np.int8),
             "tgt": np.arange(marker, marker + n, dtype=np.int16),
             "deal_key": np.asarray([f"deck:{key}" for key in spec[5]], dtype="U16")}
        p["X"][:, 0] = np.arange(marker, marker + n)
        if with_vals:
            p["vals"] = np.full((n, max(1, b - 1)), np.nan,
                                 dtype=np.float64 if i == 3 else np.float32)
            if n:
                p["vals"][:, 0] = np.arange(marker, marker + n) + 0.00000001
        keep = np.asarray([k not in exclude for k in p["deal_key"]], dtype=bool)
        q = {k: v[keep] for k, v in p.items() if k != "deal_key"}
        q["explore_flag"] = np.zeros(int(keep.sum()), np.int8)
        q["explore_margin"] = np.full(int(keep.sum()), np.nan, np.float32)
        source.append(q)

    rng = np.random.default_rng(seed)
    order = rng.permutation(len(source)); drawn = 0; expected = []
    for start in range(0, len(order), window):
        parts = [source[i] for i in order[start:start + window]]
        x = np.concatenate([p["X"] for p in parts]); y = np.concatenate([p["Y"] for p in parts])
        ball = _old_pad3([p["ball"] for p in parts], -1)
        mask = np.concatenate([_old_pad2(p["mask"], ball.shape[1], False) for p in parts])
        tgt = np.concatenate([p["tgt"] for p in parts])
        vals = (np.concatenate([_old_pad2f(p["vals"], ball.shape[1], np.nan) for p in parts])
                if all("vals" in p for p in parts) else None)
        eflag = np.concatenate([p["explore_flag"] for p in parts])
        emargin = np.concatenate([p["explore_margin"] for p in parts])
        perm = rng.permutation(len(x))
        for b in range(0, len(perm), batch_size):
            if limit is not None and drawn >= limit:
                return expected
            idx = perm[b:b + batch_size]
            if limit is not None:
                idx = idx[:limit - drawn]
            drawn += len(idx)
            out = {"x": x[idx], "y": y[idx], "ball": ball[idx], "mask": mask[idx],
                   "tgt": tgt[idx], "explore_flag": eflag[idx], "explore_margin": emargin[idx]}
            if vals is not None:
                out["vals"] = vals[idx]
            expected.append(out)
    return expected


def test_window_batches_match_oracle_across_zero_rows_optional_vals_exclusion_and_limit(tmp_path):
    # Seed 0 gives windows [no-vals, vals] and [zero-row vals, vals], exercising both branches.
    specs = [(2, 2, 1, True, np.int8, ("a", "drop")),
             (0, 2, 2, True, np.int16, ()),
             (1, 3, 2, False, np.int8, ("c",)),
             (2, 1, 3, True, np.int16, ("d", "e"))]
    root = tmp_path / "rows"
    _write_chunks(root, specs)
    stream = pr.PolicyRowsStream(root, exclude={"deck:drop"}, window=2, limit=3)
    got = list(stream.batches(1, np.random.default_rng(0)))
    expected = _oracle_batches(specs, exclude={"deck:drop"}, window=2, batch_size=1, seed=0, limit=3)
    assert len(got) == len(expected) == 3
    assert [set(batch) for batch in got] == [set(batch) for batch in expected]
    for actual, want in zip(got, expected):
        for key in want:
            assert actual[key].dtype == want[key].dtype, key
            np.testing.assert_array_equal(actual[key], want[key], err_msg=key)
    assert not any("vals" in batch for batch in got[:2])
    assert got[-1]["vals"].dtype == expected[-1]["vals"].dtype
    assert np.isnan(got[-1]["vals"]).any()


def test_load_closes_npz_and_keeps_direct_arrays_for_all_kept_rows(tmp_path, monkeypatch):
    specs = [(1, 1, 1, True, np.int8, ("a",))]
    root = tmp_path / "rows"
    _write_chunks(root, specs)
    stream = pr.PolicyRowsStream(root)
    real_load = np.load
    archives = []

    def tracked_load(*args, **kwargs):
        source = real_load(*args, **kwargs)

        class TrackingArchive:
            def __init__(self):
                self.loaded = {}

            @property
            def files(self):
                return source.files

            @property
            def fid(self):
                return source.fid

            @property
            def zip(self):
                return source.zip

            def __getitem__(self, key):
                value = source[key]
                self.loaded[key] = value
                return value

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                source.close()

        archive = TrackingArchive()
        archives.append(archive)
        return archive

    monkeypatch.setattr(pr.np, "load", tracked_load)
    out = stream._load(stream.chunks[0])
    assert archives and archives[0].fid is None and archives[0].zip is None
    assert out["X"].shape == (1, pp.INPUT_DIM) and out["ball"].shape == (1, 1, 1)
    assert out["X"] is archives[0].loaded["X"]
    assert out["ball"] is archives[0].loaded["ball"]
    assert out["explore_flag"].dtype == np.int8 and out["explore_margin"].dtype == np.float32


def test_source_chunks_and_completed_windows_are_not_retained_while_streaming():
    stream = pr.PolicyRowsStream.__new__(pr.PolicyRowsStream)
    stream.chunks, stream.window, stream.limit = [0, 1], 1, None
    source_refs, completed_window_refs = [], []

    def load(index):
        if index == 1:
            # The caller may retain yielded batches, but the generator must not
            # retain the previous full window while allocating the next one.
            assert completed_window_refs
            assert all(ref() is None for ref in completed_window_refs)
        data = {"X": np.full((2, 3), index, np.float16),
                "Y": np.zeros((2, 54), np.uint8),
                "ball": np.zeros((2, 2, 1), np.int8),
                "mask": np.ones((2, 2), bool), "tgt": np.zeros(2, np.int64),
                "vals": np.ones((2, 2), np.float32),
                "explore_flag": np.zeros(2, np.int8),
                "explore_margin": np.zeros(2, np.float32)}
        source_refs.extend(weakref.ref(a) for a in data.values())
        return data

    class OrderedRng:
        def permutation(self, n):
            return np.arange(n)

    stream._load = load
    gen = stream.batches(1, OrderedRng())
    first = next(gen)
    assert all(ref() is None for ref in source_refs)
    frame_locals = gen.gi_frame.f_locals
    completed_window_refs.extend(weakref.ref(frame_locals[name])
                                 for name in ("X", "Y", "ball", "mask", "tgt", "vals", "eflag", "emargin"))
    if sys.version_info < (3, 13):
        # Before PEP 667, f_locals is a snapshot dict CACHED on the frame: it would keep the
        # window alive itself and fail this test on 3.12 (CI) though the generator frees it.
        # Clearing the snapshot never writes back to the frame's fast locals.  On 3.13+ it is a
        # write-through proxy, so it must not be cleared.
        frame_locals.clear()
    del frame_locals
    next(gen)  # second batch of window zero
    second_window = next(gen)  # asserts old window is gone inside load(1)
    assert all(ref() is None for ref in source_refs)
    assert first["x"].tolist() == [[0, 0, 0]]
    assert second_window["x"].tolist() == [[1, 1, 1]]
    gen.close()
