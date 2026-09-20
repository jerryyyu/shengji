"""The decoded pack: a run's cache written ONCE as contiguous memory-mapped arrays (#531).

Measured 2026-09-20 on the Mini (M1's recipe on the v5 corpus, 176k shards): 56% of every
training epoch was ``batch_wait`` -- inflating and reconstructing ``.npz`` shards that the
residency budget cannot keep (``176000 shards decode to 87.4 GB; budget 6.87 GB``).  The pack
holds the same arrays, already decoded, in a few large files that the OS pages in
sequentially, so a block is a slice and no shard is ever inflated during training.

Bytes, not floats, where that is lossless: of the public block's columns, those whose values
are exact multiples of 0.5 in [0, 127.5] on EVERY row (the card planes and small counts)
are stored as ``uint8 = value * 2``; the rest stay float32.  The split is decided from the
data at build time, verified on every shard, and recorded in the manifest, so
``reconstruct`` returns float32 arrays bit-identical to the cache's.  ``world`` is uint8 in
the cache already; scalars keep their cache dtypes; ``deal_key`` and ``cluster`` are one
value per shard (a shard is one deal) and are expanded on read; ``source_ref``,
``record_sha256`` and ``input_sha256`` are kept per row so ``gather`` is unchanged.

The pack is bound to the cache it was built from: the manifest carries the encoder
identity and every shard's sha256, nbytes and row count, and ``CwvPackStore`` refuses a
store whose entries it cannot match.  ``CwvPackStore.iter_batches`` consumes the rng
exactly as ``CwvBlockStore.iter_batches`` does -- the same shard-order shuffle, the same
byte-bounded windows (from the recorded nbytes and the same residency budget), the same
per-window row shuffle -- so the batch sequence, and therefore training, is identical
(tests/test_cwv_pack.py asserts bitwise-identical batches and checkpoints).

History (seq) caches are not packed: they are ragged and the seq arch is not the trained
recipe.  A pack built with a sidecar carries ``search_mean_played`` per row.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Collection, Iterator, Mapping, Sequence

import numpy as np

from .cwv_data import (CwvBlock, TrainDataError, gather, load_block, read_meta, check_meta)
from .data import Residency, ShardRef

PACK_SCHEMA = "shengji-cwv-pack-v1"
HALF_MAX = 127.5       # the largest half-multiple a byte (value * 2) can hold
SCALARS = ("perspective", "target", "utility", "attacker_points", "points_so_far", "ply",
           "role_attacker", "seat", "has_search_means", "n_search")
ROW_STRINGS = ("source_ref", "record_sha256", "input_sha256")
SHARD_STRINGS = ("deal_key", "cluster")


class PackError(TrainDataError):
    """A pack that does not match its cache, or a shard the pack cannot hold."""


# ------------------------------------------------------------------- build

def classify_public(public: np.ndarray) -> np.ndarray:
    """Per column: True where every value is an exact multiple of 0.5 in [0, HALF_MAX]."""
    doubled = public.astype(np.float64) * 2.0
    ok = (doubled == np.round(doubled)) & (doubled >= 0.0) & (doubled <= 255.0)
    return ok.all(axis=0)


def _memmap(path: Path, dtype, shape, mode: str) -> np.memmap:
    return np.memmap(str(path), dtype=dtype, mode=mode, shape=tuple(int(s) for s in shape))


def build_pack(entries: Sequence[tuple[ShardRef, str]], out_dir: str | os.PathLike, *,
               sidecar_dir: str | None = None, classify_shards: int = 500,
               force_float32: Collection[int] = (),
               progress: Callable[[str], None] | None = None) -> dict:
    """Write the pack of ``entries`` (``(ShardRef, cache path)`` in store order) to ``out_dir``.

    Two passes over the caches: the first ``classify_shards`` shards decide the half/float32
    column split (``force_float32`` overrides it); every shard is then decoded once, checked
    against the split, and appended.  A shard whose values violate the split raises
    ``PackError`` naming the column -- rebuild with that column in ``force_float32``.
    Returns the manifest."""
    say = progress or (lambda _s: None)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "manifest.json").exists():
        raise PackError(f"{out}: a pack is already here; refusing to overwrite")
    if not entries:
        raise PackError("no shards to pack")
    started = time.perf_counter()
    # ---- pass 1: metas (rows, nbytes, identity) and the column split
    metas = []
    identity = None
    for shard, path in entries:
        meta = check_meta(read_meta(path), path=path, shard_sha256=shard.sha256, history=False)
        enc = meta.get("encoder") or {}
        ident = (str(enc.get("implementation_sha256")), int(enc.get("enc_version", 0)))
        if identity is None:
            identity = ident
        elif ident != identity:
            raise PackError(f"{path}: encoder identity {ident} differs from {identity}")
        if meta.get("history"):
            raise PackError(f"{path}: history caches are not packed")
        metas.append(meta)
    public_dim = None
    half_ok = None
    widths: dict[str, int] = {}
    for (shard, path), _meta in list(zip(entries, metas))[:max(1, int(classify_shards))]:
        block = load_block(path, shard_sha256=shard.sha256, history=False)
        if public_dim is None:
            public_dim = int(block.public.shape[1])
        ok = classify_public(block.public)
        half_ok = ok if half_ok is None else (half_ok & ok)
        for name in ROW_STRINGS:
            widths[name] = max(widths.get(name, 0), int(getattr(block, name).dtype.itemsize))
    assert half_ok is not None and public_dim is not None
    for c in force_float32:
        half_ok[int(c)] = False
    half_cols = np.flatnonzero(half_ok).astype(np.int64)
    f32_cols = np.flatnonzero(~half_ok).astype(np.int64)
    rows_total = int(sum(int(m["counts"]["encoded"]) for m in metas))
    say(f"pack: {len(entries)} shards, {rows_total} rows, public {public_dim} = "
        f"{half_cols.size} half-multiple byte columns + {f32_cols.size} float32; identity {identity}")
    # ---- string dtypes: per-row strings as the widest seen in pass 1 (verified in pass 2)
    sample = load_block(entries[0][1], shard_sha256=entries[0][0].sha256, history=False)
    str_dtypes = {name: np.dtype(getattr(sample, name).dtype.kind + str(widths[name] // (4 if getattr(sample, name).dtype.kind == "U" else 1)))
                  for name in ROW_STRINGS}
    scalar_dtypes = {name: np.dtype(getattr(sample, name).dtype) for name in SCALARS}
    with_sidecar = sidecar_dir is not None
    # ---- allocate the memmaps
    arrays: dict[str, np.memmap] = {
        "public_half": _memmap(out / "public_half.u8", np.uint8, (rows_total, half_cols.size), "w+"),
        "public_f32": _memmap(out / "public_f32.f32", np.float32, (rows_total, f32_cols.size), "w+"),
        "world": _memmap(out / "world.u8", np.uint8, (rows_total, *sample.world.shape[1:]), "w+"),
    }
    for name in SCALARS:
        arrays[name] = _memmap(out / f"{name}.bin", scalar_dtypes[name], (rows_total,), "w+")
    for name in ROW_STRINGS:
        arrays[name] = _memmap(out / f"{name}.bin", str_dtypes[name], (rows_total,), "w+")
    if with_sidecar:
        arrays["search_mean_played"] = _memmap(out / "search_mean_played.f32", np.float32, (rows_total,), "w+")
    # ---- pass 2: decode every shard once and append
    shards_out = []
    offset = 0
    for i, ((shard, path), meta) in enumerate(zip(entries, metas)):
        block = load_block(path, shard_sha256=shard.sha256, history=False, sidecar_dir=sidecar_dir)
        n = block.n
        if int(block.public.shape[1]) != public_dim:
            raise PackError(f"{path}: public width {block.public.shape[1]} != {public_dim}")
        if half_cols.size:
            doubled = block.public[:, half_cols].astype(np.float64) * 2.0
            bad = ~((doubled == np.round(doubled)) & (doubled >= 0.0) & (doubled <= 255.0)).all(axis=0)
            if bad.any():
                raise PackError(f"{path}: public column(s) {half_cols[bad].tolist()} are not "
                                f"half-multiples in [0, {HALF_MAX}]; rebuild with force_float32")
            arrays["public_half"][offset:offset + n] = doubled.astype(np.uint8)
        if f32_cols.size:
            arrays["public_f32"][offset:offset + n] = block.public[:, f32_cols]
        arrays["world"][offset:offset + n] = block.world
        for name in SCALARS:
            arrays[name][offset:offset + n] = getattr(block, name)
        for name in ROW_STRINGS:
            col = getattr(block, name)
            if col.dtype.itemsize > str_dtypes[name].itemsize:
                raise PackError(f"{path}: {name} wider ({col.dtype}) than the pack's {str_dtypes[name]}")
            arrays[name][offset:offset + n] = col.astype(str_dtypes[name])
        if with_sidecar:
            arrays["search_mean_played"][offset:offset + n] = block.search_mean_played
        keys = np.unique(block.deal_key)
        clusters = np.unique(block.cluster)
        if keys.size != 1 or clusters.size != 1:
            raise PackError(f"{path}: {keys.size} deal keys / {clusters.size} clusters in one shard")
        shards_out.append({"sha256": shard.sha256, "label": shard.label, "offset": offset, "rows": n,
                           "nbytes": int(meta.get("nbytes") or 0), "deal_key": str(keys[0]),
                           "cluster": str(clusters[0])})
        offset += n
        if (i + 1) % 1000 == 0 or i + 1 == len(entries):
            say(f"pack: {i + 1}/{len(entries)} shards, {offset} rows, {time.perf_counter() - started:.0f}s")
    if offset != rows_total:
        raise PackError(f"rows written {offset} != rows declared {rows_total}")
    for arr in arrays.values():
        arr.flush()
    manifest = {
        "schema": PACK_SCHEMA, "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "encoder": {"implementation_sha256": identity[0], "enc_version": identity[1]},
        "public_dim": public_dim, "rows": rows_total,
        "half_cols": half_cols.tolist(), "f32_cols": f32_cols.tolist(),
        "world_shape": [int(s) for s in sample.world.shape[1:]],
        "scalar_dtypes": {k: v.str for k, v in scalar_dtypes.items()},
        "string_dtypes": {k: v.str for k, v in str_dtypes.items()},
        "deal_key_dtype": np.dtype(sample.deal_key.dtype).str, "cluster_dtype": np.dtype(sample.cluster.dtype).str,
        "sidecar": with_sidecar, "shards": shards_out,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    say(f"pack: done in {time.perf_counter() - started:.0f}s -> {out}")
    return manifest


# ------------------------------------------------------------------- store

class CwvPackStore:
    """``CwvBlockStore``'s contract over a pack: same ``entries``, ``rows``, ``keys``,
    ``block(i)``, ``iter_blocks``, ``windows`` and ``iter_batches`` -- no decode, no pool."""

    def __init__(self, entries: Sequence[tuple[ShardRef, str]], pack_dir: str | os.PathLike, *,
                 residency: Residency | None = None, resident_bytes: int | None = None,
                 keep: Sequence[Collection[str] | None] | None = None,
                 history: bool = False, sidecar_dir: str | None = None):
        if history:
            raise PackError("history caches are not packed")
        self.dir = Path(pack_dir)
        self.manifest = json.loads((self.dir / "manifest.json").read_text())
        if self.manifest.get("schema") != PACK_SCHEMA:
            raise PackError(f"{self.dir}: not a {PACK_SCHEMA} pack")
        if bool(sidecar_dir) != bool(self.manifest.get("sidecar")):
            raise PackError(f"{self.dir}: pack {'has' if self.manifest.get('sidecar') else 'has no'} "
                            f"sidecar column; the run {'wants' if sidecar_dir else 'wants none'}")
        self.entries = [(shard, str(path)) for shard, path in entries]
        by_sha = {s["sha256"]: s for s in self.manifest["shards"]}
        self.shards = []
        for shard, path in self.entries:
            rec = by_sha.get(shard.sha256)
            if rec is None:
                raise PackError(f"{self.dir}: shard {shard.label} ({shard.sha256[:12]}) is not in the pack")
            meta = check_meta(read_meta(path), path=path, shard_sha256=shard.sha256, history=False)
            enc = meta.get("encoder") or {}
            if str(enc.get("implementation_sha256")) != self.manifest["encoder"]["implementation_sha256"]:
                raise PackError(f"{path}: encoder identity differs from the pack's")
            if int(meta["counts"]["encoded"]) != int(rec["rows"]) or int(meta.get("nbytes") or 0) != int(rec["nbytes"]):
                raise PackError(f"{path}: rows/nbytes differ from the pack's record; rebuild the pack")
            self.shards.append((rec, meta))
        keep_list = list(keep) if keep is not None else [None] * len(self.entries)
        if len(keep_list) != len(self.entries):
            raise TrainDataError("keep must have one entry per shard")
        self.keep = [None if k is None else frozenset(str(x) for x in k) for k in keep_list]
        # a shard is one deal: kept entirely or not at all
        self.keep_idx: list[np.ndarray | None] = []
        self._rows: list[int] = []
        for (rec, _meta), kept in zip(self.shards, self.keep):
            if kept is None:
                self.keep_idx.append(None); self._rows.append(int(rec["rows"]))
            elif rec["deal_key"] in kept:
                self.keep_idx.append(np.arange(int(rec["rows"]), dtype=np.int64)); self._rows.append(int(rec["rows"]))
            else:
                self.keep_idx.append(np.zeros(0, np.int64)); self._rows.append(0)
        self.sizes = [int(rec["nbytes"]) for rec, _m in self.shards]
        self.residency = residency if residency is not None else Residency(resident_bytes)
        self.history = False
        self.sidecar_dir = sidecar_dir
        self.id = ("cwv-pack", id(self))
        self.decode_submitted = 0
        m = self.manifest
        rows = int(m["rows"]); half = len(m["half_cols"]); f32 = len(m["f32_cols"])
        self._half_cols = np.asarray(m["half_cols"], dtype=np.int64)
        self._f32_cols = np.asarray(m["f32_cols"], dtype=np.int64)
        self.public_dim = int(m["public_dim"])
        self._arr: dict[str, np.memmap] = {
            "public_half": _memmap(self.dir / "public_half.u8", np.uint8, (rows, half), "r"),
            "public_f32": _memmap(self.dir / "public_f32.f32", np.float32, (rows, f32), "r"),
            "world": _memmap(self.dir / "world.u8", np.uint8, (rows, *m["world_shape"]), "r"),
        }
        for name in SCALARS:
            self._arr[name] = _memmap(self.dir / f"{name}.bin", np.dtype(m["scalar_dtypes"][name]), (rows,), "r")
        for name in ROW_STRINGS:
            self._arr[name] = _memmap(self.dir / f"{name}.bin", np.dtype(m["string_dtypes"][name]), (rows,), "r")
        if m.get("sidecar"):
            self._arr["search_mean_played"] = _memmap(self.dir / "search_mean_played.f32", np.float32, (rows,), "r")

    # -- the CwvBlockStore surface ---------------------------------------------------
    def __len__(self) -> int:
        return len(self.entries)

    @property
    def nbytes(self) -> int:
        return int(sum(self.sizes))

    def rows(self) -> list[int]:
        return list(self._rows)

    def keys(self) -> list[str]:
        return sorted({rec["deal_key"] for (rec, _m), n in zip(self.shards, self._rows) if n})

    def keys_of(self, i: int) -> list[str]:
        return [self.shards[i][0]["deal_key"]] if self._rows[i] else []

    def is_resident(self, i: int) -> bool:
        return True

    def reconstruct_public(self, lo: int, hi: int) -> np.ndarray:
        """The cache's float32 public block for rows ``lo:hi``, bit-identical."""
        out = np.empty((hi - lo, self.public_dim), dtype=np.float32)
        if self._half_cols.size:
            out[:, self._half_cols] = self._arr["public_half"][lo:hi].astype(np.float32) * np.float32(0.5)
        if self._f32_cols.size:
            out[:, self._f32_cols] = self._arr["public_f32"][lo:hi]
        return out

    def block(self, i: int, *, pinned: Collection[int] = (), decoded=None) -> CwvBlock:
        rec, meta = self.shards[i]
        lo = int(rec["offset"]); n = int(rec["rows"]); hi = lo + n
        arrays: dict[str, np.ndarray] = {"public": self.reconstruct_public(lo, hi),
                                         "world": np.asarray(self._arr["world"][lo:hi])}
        for name in SCALARS:
            arrays[name] = np.asarray(self._arr[name][lo:hi])
        for name in ROW_STRINGS:
            arrays[name] = np.asarray(self._arr[name][lo:hi])
        m = self.manifest
        arrays["deal_key"] = np.full(n, rec["deal_key"], dtype=np.dtype(m["deal_key_dtype"]))
        arrays["cluster"] = np.full(n, rec["cluster"], dtype=np.dtype(m["cluster_dtype"]))
        if "search_mean_played" in self._arr:
            arrays["search_mean_played"] = np.asarray(self._arr["search_mean_played"][lo:hi])
        block = CwvBlock(arrays, meta, self.entries[i][1])
        if self.keep_idx[i] is not None:
            block = block.subset(self.keep_idx[i])
        return block

    def iter_blocks(self, *, skip: Callable[[list[str]], bool] | None = None) -> Iterator[CwvBlock]:
        for i in range(len(self.entries)):
            if skip is not None and skip(self.keys_of(i)):
                continue
            yield self.block(i)

    def windows(self, order: Sequence[int], window: int) -> list[list[int]]:
        # identical grouping to CwvBlockStore.windows: by count AND the residency budget over
        # the recorded decoded nbytes, so the batch sequence matches the cache path exactly
        budget = self.residency.budget
        groups: list[list[int]] = []; cur: list[int] = []; cur_bytes = 0
        for i in order:
            i = int(i); size = self.sizes[i]
            if budget is not None and size > budget:
                raise TrainDataError(f"{self.entries[i][0].label}: decodes to {size} bytes, above the "
                                     f"residency budget of {budget}; raise --resident-bytes")
            if cur and (len(cur) >= max(1, int(window)) or (budget is not None and cur_bytes + size > budget)):
                groups.append(cur); cur, cur_bytes = [], 0
            cur.append(i); cur_bytes += size
        if cur:
            groups.append(cur)
        return groups

    def iter_batches(self, mask_fn: Callable[[CwvBlock], np.ndarray], batch_size: int, *,
                     rng: np.random.Generator | None = None, window: int = 64,
                     decode_workers: int = 0, include_metadata: bool = True
                     ) -> Iterator[dict[str, np.ndarray]]:
        order = np.arange(len(self.entries))
        if rng is not None:
            rng.shuffle(order)
        batch_size = max(1, int(batch_size))
        for group in self.windows(order, window):
            blocks = [self.block(i) for i in group]
            which_parts: list[np.ndarray] = []; row_parts: list[np.ndarray] = []
            for j, block in enumerate(blocks):
                sel = np.flatnonzero(mask_fn(block))
                which_parts.append(np.full(sel.size, j, dtype=np.int64)); row_parts.append(sel.astype(np.int64))
            which = np.concatenate(which_parts) if which_parts else np.zeros(0, np.int64)
            rows = np.concatenate(row_parts) if row_parts else np.zeros(0, np.int64)
            if rows.size:
                idx = np.arange(rows.size)
                if rng is not None:
                    rng.shuffle(idx)
                for b0 in range(0, rows.size, batch_size):
                    sl = idx[b0:b0 + batch_size]
                    yield gather(blocks, which[sl], rows[sl])
            del blocks, which, rows
