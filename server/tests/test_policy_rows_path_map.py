"""A composed policy-rows directory copied to another host reads through SHENGJI_PATH_MAP.

Composed manifests record each part's absolute ``dir`` and link each chunk to
its absolute source.  On the copy those paths exist only under a new root; the
map relocates them, and with no map the recorded paths are read unchanged.
"""
import hashlib
import json
import shutil

import numpy as np
import pytest

pytest.importorskip("torch")

from shengji.ops.hostinfo import PATH_MAP_ENV  # noqa: E402
from shengji.train.policy_prior import CHUNK_SCHEMA, ENC_VERSION, input_dim  # noqa: E402
from shengji.train.policy_rows import PolicyRowsStream  # noqa: E402


def _leaf(directory, rows=6):
    directory.mkdir(parents=True)
    n, legal = rows, 3
    rng = np.random.default_rng(5)
    chunk = directory / "c0000.npz"
    np.savez(chunk, X=rng.random((n, input_dim(ENC_VERSION)), dtype=np.float32),
             Y=np.zeros((n, 54), np.float32), ball=np.zeros((n, legal, 54), np.int8),
             mask=np.ones((n, legal), bool), tgt=np.zeros(n, np.int64),
             deal_key=np.array([f"d{i}" for i in range(n)]),
             explore_flag=np.zeros(n, np.int8), explore_margin=np.zeros(n, np.float32))
    sha = hashlib.sha256(chunk.read_bytes()).hexdigest()
    manifest = {"schema": CHUNK_SCHEMA, "enc_version": ENC_VERSION, "input_dim": input_dim(ENC_VERSION),
                "rows": n, "values_scale": "points", "explore_tags": True,
                "chunks": [{"file": chunk.name, "rows": n, "sha256": sha}]}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def _composed(origin_root, out):
    """A composed directory as written on the origin host, pointing at origin_root/leaf."""
    leaf_man = json.loads((origin_root / "leaf" / "manifest.json").read_text())
    out.mkdir()
    chunk = dict(leaf_man["chunks"][0], file="p0000-c0000.npz", source=str(origin_root / "leaf"))
    (out / chunk["file"]).symlink_to(origin_root / "leaf" / "c0000.npz")
    manifest = {**leaf_man, "chunks": [chunk],
                "composed_from": [{"tag": "p0000", "dir": str(origin_root / "leaf")}]}
    (out / "manifest.json").write_text(json.dumps(manifest))


def test_unmapped_composed_directory_reads_recorded_paths(tmp_path, monkeypatch):
    monkeypatch.delenv(PATH_MAP_ENV, raising=False)
    _leaf(tmp_path / "origin" / "leaf")
    _composed(tmp_path / "origin", tmp_path / "composed")
    stream = PolicyRowsStream(tmp_path / "composed")
    assert stream.n == 6 and stream.values_scale == "points"
    assert "path_map" not in stream.identity
    assert sum(len(b["x"]) for b in stream.batches(4, np.random.default_rng(0))) == 6


def test_copied_composed_directory_needs_and_honours_the_map(tmp_path, monkeypatch):
    origin, copy = tmp_path / "origin", tmp_path / "copy"
    _leaf(origin / "leaf")
    _composed(origin, tmp_path / "composed")
    shutil.copytree(origin, copy)
    shutil.rmtree(origin)                   # the origin host's root does not exist here
    monkeypatch.delenv(PATH_MAP_ENV, raising=False)
    with pytest.raises(ValueError, match="no readable manifest"):
        PolicyRowsStream(tmp_path / "composed")
    monkeypatch.setenv(PATH_MAP_ENV, f"{origin}={copy}")
    stream = PolicyRowsStream(tmp_path / "composed")
    assert stream.n == 6 and stream.identity["path_map"] == [[str(origin), str(copy)]]
    assert sum(len(b["x"]) for b in stream.batches(4, np.random.default_rng(0))) == 6


def test_mapped_chunk_must_still_match_the_manifest_digest(tmp_path, monkeypatch):
    origin, copy = tmp_path / "origin", tmp_path / "copy"
    _leaf(origin / "leaf")
    _composed(origin, tmp_path / "composed")
    shutil.copytree(origin, copy)
    shutil.rmtree(origin)
    with np.load(copy / "leaf" / "c0000.npz") as d:
        arrays = {k: d[k] for k in d.files}
    arrays["tgt"] = arrays["tgt"] + 1
    np.savez(copy / "leaf" / "c0000.npz", **arrays)
    monkeypatch.setenv(PATH_MAP_ENV, f"{origin}={copy}")
    with pytest.raises(ValueError, match="SHA256 differs"):
        PolicyRowsStream(tmp_path / "composed")
