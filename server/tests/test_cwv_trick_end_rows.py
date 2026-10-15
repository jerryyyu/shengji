"""Trick-end training rows: each record's realised trick-end state, with the record's label.

Every served pv-search leaf is a finished trick, while three in four training rows are mid-trick
afterstates (the root played first, second or third).  The trick-end flavour of the cache adds,
per record whose afterstate is mid-trick, the state after the fourth play of that trick as the
round really continued, encoded from the record's seat with the record's target.

Pinned here: the option is off by default and the plain flavour is untouched; the added rows
equal an INDEPENDENT derivation (the next trick's leader's own record, rebuilt from its prefix,
rather than the cache's replay); labels and identities are the record's; the counts add up; the
added rows are train-only under the split selectors, on the cache and the pack paths alike; and
the trainer flag trains on them while every held-out count stays one row per record.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from shengji.harvest.rebuild import state_for_record
from shengji.rl.value_afterstate_v2 import tensors_from_round
from shengji.train import cwv_data, cwv_pack, train_cwv
from shengji.train.data import Residency, SplitSelector, discover_store, split_deals, split_mask
from tests.test_cwv_train import THIRDS, records, store_dir  # noqa: F401  (shared corpus fixtures)

VERSION = 7


def _round_and_ply(record):
    _run, cluster, mirror, _seat, ply = record["source_ref"].split(":")
    return (cluster, mirror), int(ply)


def _expected(shard_records):
    """``[(record, trick-end state)]`` in record order, derived WITHOUT the cache's replay:
    the trick-end state of a play at ply p (trick position p % 4 < 3) is the decision state of
    whichever record of the same round sits at the next trick's first ply."""
    at = defaultdict(dict)
    for r in shard_records:
        key, ply = _round_and_ply(r)
        at[key][ply] = r
    out = []
    for r in shard_records:
        try:
            cwv_data.bridge_record(r, version=VERSION)
        except cwv_data.TrainDataError:
            continue
        key, ply = _round_and_ply(r)
        if ply % 4 == 3:
            continue
        nxt = at[key].get(ply - ply % 4 + 4)
        if nxt is not None:
            out.append((r, state_for_record(nxt)))
    return out


@pytest.fixture(scope="module")
def built(store_dir, records, tmp_path_factory):  # noqa: F811
    cache = tmp_path_factory.mktemp("trick-end-cache")
    store = discover_store(str(store_dir), limit_clusters=None)
    out = []
    for shard in store.shards:
        plain, plain_counts = cwv_data.build_cache(shard, cache, version=VERSION)
        te, te_counts = cwv_data.build_cache(shard, cache, version=VERSION, trick_end=True)
        shard_records = [json.loads(line) for line in Path(shard.path).read_text().splitlines()]
        out.append((shard, plain, plain_counts, te, te_counts, shard_records))
    return cache, out


def test_off_by_default_and_the_plain_flavour_is_untouched(built, tmp_path):
    _cache, shards = built
    shard, plain, _pc, te, _tc, _recs = shards[0]
    assert plain == cwv_data.cache_path(_cache, shard.sha256, version=VERSION)
    assert te == cwv_data.cache_path(_cache, shard.sha256, version=VERSION, trick_end=True) != plain
    assert ".cwvte-" in te.name and ".cwv-" in plain.name
    again, _ = cwv_data.build_cache(shard, tmp_path, version=VERSION)
    meta = cwv_data.read_meta(plain)
    assert cwv_data.read_meta(again) == meta, "the default build is the plain flavour"
    with np.load(again) as x, np.load(plain) as y:
        assert x.files == y.files
        assert all(np.array_equal(x[k], y[k]) for k in x.files)
    assert "trick_end" not in meta and "trick_end" not in meta["counts"]
    with np.load(plain) as z:
        assert "trick_end" not in z.files
    assert cwv_data.load_block(plain).trick_end is None
    with pytest.raises(cwv_data.TrainDataError):
        cwv_data.check_meta(meta, path=plain, trick_end=True)
    with pytest.raises(cwv_data.TrainDataError):
        cwv_data.check_meta(cwv_data.read_meta(te), path=te, trick_end=False)
    with pytest.raises(cwv_data.TrainDataError):
        cwv_data.cache_path(_cache, shard.sha256, history=True, trick_end=True)
    assert train_cwv.build_parser().parse_args(
        ["train", "--data", "d", "--out", "o"]).trick_end_rows is False


def test_the_added_rows_are_the_independently_derived_trick_end_states(built):
    _cache, shards = built
    total = 0
    for shard, plain, plain_counts, te, te_counts, shard_records in shards:
        a = cwv_data.load_block(plain, shard_sha256=shard.sha256)
        b = cwv_data.load_block(te, shard_sha256=shard.sha256)
        n = plain_counts["encoded"]
        assert te_counts["encoded"] == n and b.n == n + te_counts["trick_end"]["rows"]
        assert cwv_data.cache_rows(cwv_data.read_meta(te)) == b.n
        for name in cwv_data.CwvBlock.ARRAYS:              # the record rows, unchanged
            assert np.array_equal(getattr(a, name)[:], getattr(b, name)[:n]), name
        assert not b.trick_end[:n].any() and b.trick_end[n:].all()
        expected = _expected(shard_records)
        assert len(expected) == b.n - n > 0
        by_ref = {r: i for i, r in enumerate(a.source_ref.tolist())}
        for j, (record, state) in enumerate(expected):
            row = n + j
            src = by_ref[record["source_ref"]]
            assert state.phase == "play" and not state.trick.plays, "a trick boundary"
            want = tensors_from_round(state, int(record["seat"]), version=VERSION)
            assert b.public[row].tobytes() == want.public.tobytes()
            assert np.array_equal(b.world[row], np.rint(want.world * 2).astype(np.uint8))
            assert b.input_sha256[row].decode() == want.sha256()
            # the record's label and identity; no search-mean evidence
            for name in ("target", "utility", "attacker_points", "points_so_far", "ply",
                         "role_attacker", "seat", "deal_key", "cluster", "source_ref", "perspective"):
                assert getattr(b, name)[row] == getattr(a, name)[src], name
            assert b.record_sha256[row].decode() == cwv_data.trick_end_record_sha256(
                a.record_sha256[src].decode()) != a.record_sha256[src].decode()
            assert not b.has_search_means[row] and b.n_search[row] == 0
            # v7 states who leads next: the winner of the trick just finished
            rel = (state.turn - int(record["seat"])) % 4
            block = b.public[row, 560:564].tolist()
            assert block == [1.0 if i == rel else 0.0 for i in range(4)]
        skipped = te_counts["trick_end"]["skipped"]
        assert set(skipped) == set(cwv_data.TRICK_END_SKIPS)
        assert te_counts["trick_end"]["rows"] + sum(skipped.values()) == n
        assert skipped["no_continuation"] == skipped["ambiguous"] == skipped["replay_failed"] == 0
        assert skipped["boundary"] > 0 and skipped["terminal"] > 0
        total += b.n - n
    assert total > 100


def test_a_missing_continuation_is_counted_never_filled(built):
    _cache, shards = built
    shard, *_rest, shard_records = shards[0]
    rows = []
    for r in shard_records:
        try:
            rows.append(cwv_data.bridge_record(r, version=2))
        except cwv_data.TrainDataError:
            continue
    one_seat = [row for row in rows if row.seat == rows[0].seat]
    added, counts = cwv_data.trick_end_rows(one_seat, version=2)
    # a seat's own later decisions finish only the tricks it played into last
    assert counts["skipped"]["no_continuation"] > 0
    assert counts["rows"] + sum(counts["skipped"].values()) == len(one_seat)
    for row, state, tensors in added:
        assert not state.trick.plays and tensors.public.shape == (561,)


def test_the_round_is_named_not_guessed_from_a_shared_opening(built):
    """The two mirrors of a deal share the deck and can open identically.  With the round named
    by the source_ref every row is finished in its own round; without it, a row whose opening
    both mirrors share is refused as ambiguous rather than finished in either one."""
    import dataclasses
    _cache, shards = built
    ambiguous = 0
    for _shard, *_rest, shard_records in shards:
        rows = [cwv_data.bridge_record(r, version=2) for r in shard_records]
        named, _ = cwv_data.trick_end_rows(rows, version=2)
        assert {cwv_data.round_of(r.source_ref) for r in rows} == {
            ":".join(r.source_ref.split(":")[:3]) for r in rows}
        anonymous = [dataclasses.replace(r, source_ref=f"other-format#{i}") for i, r in enumerate(rows)]
        guessed, counts = cwv_data.trick_end_rows(anonymous, version=2)
        assert counts["rows"] + sum(counts["skipped"].values()) == len(rows)
        ambiguous += counts["skipped"]["ambiguous"]
        by_index = {int(row.source_ref.split("#")[1]): t for row, _state, t in guessed}
        position = {id(row): i for i, row in enumerate(rows)}
        keyed = {position[id(row)]: t for row, _state, t in named}
        for i, t in by_index.items():
            assert t.public.tobytes() == keyed[i].public.tobytes(), "a guessed continuation"
    assert ambiguous > 0, "the fixture has mirrors with a shared opening"


def test_trick_end_rows_are_train_only_under_the_split_selectors(built):
    _cache, shards = built
    shard, _plain, plain_counts, te, te_counts, _recs = shards[0]
    block = cwv_data.load_block(te, shard_sha256=shard.sha256)
    key = block.deal_key[0]
    n, added = plain_counts["encoded"], te_counts["trick_end"]["rows"]
    for part in ("train", "val", "test"):
        assignment = {key: part}
        want = n + added if part == "train" else n
        assert int(SplitSelector(assignment, part)(block).sum()) == want
        assert int(split_mask(block, assignment, part).sum()) == want
    assert not SplitSelector({key: "val"}, "val")(block)[n:].any()


def test_the_pack_carries_the_flag_and_selects_identically(built, tmp_path):
    cache, shards = built
    entries = [(shard, str(te)) for shard, _p, _pc, te, _tc, _r in shards]
    manifest = cwv_pack.build_pack(entries, tmp_path / "pack", classify_shards=2)
    assert manifest["trick_end"] is True
    assert manifest["rows"] == sum(cwv_data.cache_rows(cwv_data.read_meta(te)) for _s, te in entries)
    cs = cwv_data.CwvBlockStore(entries, residency=Residency(None))
    ps = cwv_pack.CwvPackStore(entries, tmp_path / "pack", residency=Residency(None))
    assignment = split_deals(cs.keys(), seed=1, **THIRDS)
    for i in range(len(cs)):
        a, b = cs.block(i), ps.block(i)
        assert np.array_equal(a.trick_end, b.trick_end)
        for part in ("train", "val", "test"):
            sel = SplitSelector(assignment, part)
            assert np.array_equal(sel(a), sel(b))
    # a pack is one flavour: plain and trick-end caches never mix
    mixed = [(shards[0][0], str(shards[0][1]))] + entries[1:]
    with pytest.raises(cwv_pack.PackError, match="all trick-end caches or none"):
        cwv_pack.build_pack(mixed, tmp_path / "mixed", classify_shards=2)
    plain = [(shard, str(p)) for shard, p, _pc, _te, _tc, _r in shards]
    with pytest.raises(cwv_pack.PackError):
        cwv_pack.CwvPackStore(plain, tmp_path / "pack", residency=Residency(None))


def test_the_trainer_trains_on_them_and_holds_out_records_only(store_dir, tmp_path):  # noqa: F811
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=10, hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32,
              val_rank_records=50, encoder_version=VERSION, **THIRDS)
    plain = train_cwv.train(out=tmp_path / "plain", **kw)
    te = train_cwv.train(out=tmp_path / "te", trick_end_rows=True, **kw)
    assert "trick_end_rows" not in plain["config"] and te["config"]["trick_end_rows"] is True
    for part in ("val", "test"):
        assert te["split"][f"{part}_records"] == plain["split"][f"{part}_records"]
        assert te["split"][f"{part}_deals"] == plain["split"][f"{part}_deals"]
    assert te["split"]["train_records"] > plain["split"]["train_records"]
    assert list((tmp_path / "te" / "cache").glob("*.cwvte-v7-*.npz"))
    assert not list((tmp_path / "plain" / "cache").glob("*.cwvte-*.npz"))
    with pytest.raises(train_cwv.TrainError, match="mlp"):
        train_cwv.train(out=tmp_path / "seq", trick_end_rows=True, **{**kw, "arch": "seq"})
