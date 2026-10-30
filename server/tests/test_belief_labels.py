"""S17 step 1: the belief-label extractor (`shengji.train.belief_labels`).

Synthetic games stand in for trajectory shards: a heuristic table that sometimes
leads a whole side suit as a throw (so failed throws and their public notices
occur), records written in a shard's seat-grouped order.  The leakage tests
re-deal the hidden cards behind a fixed public history and require the inputs
not to move while the labels do.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.engine.cards import SUITS
from shengji.engine.round import Round
from shengji.harvest.rebuild import round_from_setup
from shengji.rl.encode import CARD_INDEX
from shengji.train import belief_labels as bl


def _setup_for(deck, banker, declare):
    base = {"trump_rank": "2", "banker": banker, "declarations": [], "trump_suit": None,
            "trump_is_nt": False}
    rnd = round_from_setup(deck, base, stop_before_bury=True, check_trump=False)
    if declare:
        # the banker declares a trump-rank card it was dealt, when it has one
        # the banker's hand already holds the kitty here: declare only a DEALT card
        dealt = list((Counter(rnd.hands[banker]) - Counter(rnd.kitty)).elements())
        if rnd.declaration is None:
            code = next((c for c in sorted(dealt) if c[1:] == "2" and c[0] in SUITS), None)
            if code is not None:
                base["declarations"] = [{"seat": banker, "cards": [code]}]
                rnd = round_from_setup(deck, base, stop_before_bury=True, check_trump=False)
    base["trump_suit"] = rnd.trump_suit
    base["trump_is_nt"] = bool(rnd.trump_is_nt)
    base["buried"] = HeuristicBot().decide_bury(rnd, rnd.banker)
    base["banker"] = rnd.banker
    return base


def _throw_attempt(rnd, seat, rng):
    """A whole non-trump suit led at once (a throw the engine may refuse)."""
    o = rnd.ordering
    by_suit = {}
    for c in rnd.hands[seat]:
        by_suit.setdefault(o.eff_suit(c), []).append(c)
    options = [cards for suit, cards in sorted(by_suit.items())
               if suit in SUITS and len(set(cards)) >= 3]
    return list(rng.choice(options)) if options else None


def synthetic_cluster(seed: int, *, throw_rate: float = 0.35, declare: bool = True):
    """One deal, two rounds (banker 0 then banker 1), records in shard order."""
    deck = list(Round("2", 0, random.Random(seed)).deck)
    rng = random.Random(seed)
    bot = HeuristicBot()
    records = []
    for mirror, banker in enumerate((0, 1)):
        setup = _setup_for(deck, banker, declare)
        rnd = round_from_setup(deck, setup)
        prefix = []
        per_seat = {s: [] for s in range(4)}
        while rnd.phase == "play":
            seat = rnd.turn
            action = None
            if not rnd.trick.plays and rng.random() < throw_rate:
                action = _throw_attempt(rnd, seat, rng)
            if action is None:
                action = list(bot.decide_play(rnd, seat))
            rec = {"decision_kind": "play", "seat": seat, "action": action,
                   "plays_prefix": [dict(p) for p in prefix], "deck": deck, "setup": setup,
                   "round_seed": seed, "source_ref": f"syn:{seed}:{mirror}:{seat}:{len(prefix)}"}
            before = len(rnd.history)
            rnd.play(seat, list(action))
            played = (rnd.history[-1].plays[-1].cards if len(rnd.history) > before
                      else rnd.trick.plays[-1].cards)
            if Counter(played) != Counter(action):
                rec["engine_play"] = list(played)
            prefix.append({"seat": seat, "cards": list(played)})
            per_seat[seat].append(rec)
        for s in range(4):                    # a shard groups a round's records by seat
            records += per_seat[s]
    return records


@pytest.fixture(scope="module")
def cluster():
    # a seed whose games include failed throws and a declaration
    for seed in range(1000, 1100):
        recs = synthetic_cluster(seed)
        if sum("engine_play" in r for r in recs) >= 2 and recs[0]["setup"]["declarations"]:
            return recs
    pytest.fail("no synthetic seed produced failed throws")


def test_feature_blocks_are_the_declared_width_and_hold_no_world():
    assert bl.FEATURE_DIM == sum(w for _, w in bl.FEATURE_BLOCKS)
    names = [n for n, _ in bl.FEATURE_BLOCKS]
    assert not any("world" in n or "hand_rel" in n for n in names)
    # the gen5 extract's world block is a witness only; the base row is v4, built from scratch
    assert bl.EXTRACT_WORLD == (561, 831) and bl.BASE_DIM == 635


def test_replay_follows_table_order_and_reposts_failed_throws(cluster):
    seen = list(bl.iter_decisions(cluster))
    assert len(seen) == len(cluster)
    assert [d.round_index for d in seen].count(1) == sum(r["source_ref"].split(":")[2] == "1"
                                                       for r in cluster)
    # a failed throw replayed from the ATTEMPTED cards puts its notice on the ledger
    assert any(d.refusals for d in seen)
    # every refusal the ledger holds is a throw that a record attempted
    attempted = {tuple(sorted(r["action"])) for r in cluster if "engine_play" in r}
    for d in seen:
        for ref in d.refusals:
            assert tuple(sorted(ref.attempted)) in attempted


def test_replay_refuses_an_inconsistent_stream(cluster):
    plays = bl.game_order(cluster)
    broken = copy.deepcopy(plays)
    del broken[5]
    with pytest.raises(bl.BeliefLabelError):
        list(bl.iter_decisions(broken, ordered=True))
    tampered = copy.deepcopy(plays)
    tampered[3]["plays_prefix"][-1]["seat"] = (tampered[3]["plays_prefix"][-1]["seat"] + 1) % 4
    with pytest.raises(bl.BeliefLabelError):
        list(bl.iter_decisions(tampered, ordered=True))


def _redeal_hidden(rnd, seat, rng):
    """The same public history with the hidden cards dealt differently: the other
    seats' hands (and the kitty, unless the actor buried it) shuffled, sizes kept."""
    other = copy.deepcopy(rnd)
    holders = [(seat + rel) % 4 for rel in (1, 2, 3)]
    pool = [c for s in holders for c in other.hands[s]]
    kitty_hidden = other.banker != seat
    if kitty_hidden:
        pool += list(other.buried)
    rng.shuffle(pool)
    at = 0
    for s in holders:
        n = len(other.hands[s])
        other.hands[s] = pool[at:at + n]
        at += n
    if kitty_hidden:
        other.buried = pool[at:]
    return other


def test_inputs_do_not_move_when_the_hidden_deal_does(cluster):
    """The leakage test: no label information in the inputs."""
    rng = random.Random(7)
    changed_labels = 0
    checked = 0
    for d in bl.iter_decisions(cluster):
        if d.decision_index % 3:
            continue
        x = bl.belief_features(d.rnd, d.seat, d.refusals)
        y = bl.belief_labels(d.rnd, d.seat)
        other = _redeal_hidden(d.rnd, d.seat, rng)
        x2 = bl.belief_features(other, d.seat, d.refusals)
        y2 = bl.belief_labels(other, d.seat)
        assert np.array_equal(x, x2), "an input column reads a hidden card"
        changed_labels += not np.array_equal(y, y2)
        checked += 1
    assert checked > 20 and changed_labels > checked // 2


def test_labels_are_the_hidden_copies_and_match_the_extract_world_layout(cluster):
    for d in bl.iter_decisions(cluster):
        mem = Memory(d.rnd, d.seat, own_kitty=True)
        y = bl.belief_labels(d.rnd, d.seat, mem)
        assert np.array_equal(y.sum(axis=1), bl.hidden_counts(mem))
        w = bl.world_block(d.rnd, d.seat)        # X[:, 561:831] of a gen5 extract row
        kitty = np.zeros(54) if d.rnd.banker == d.seat else w[4] * 2
        assert np.array_equal(y, np.stack([w[1] * 2, w[2] * 2, w[3] * 2, kitty], 1))


def test_banker_and_kitty_semantics(cluster):
    blocks = dict(bl.FEATURE_BLOCKS)
    start = {}
    at = 0
    for name, width in bl.FEATURE_BLOCKS:
        start[name] = at
        at += width
    kitty_cols = slice(start["own_kitty"], start["own_kitty"] + blocks["own_kitty"])
    roles = Counter()
    for d in bl.iter_decisions(cluster):
        mem = bl.actor_memory(d.rnd, d.seat, d.refusals)
        x = bl.belief_features(d.rnd, d.seat, d.refusals, mem=mem)
        y = bl.belief_labels(d.rnd, d.seat, mem)
        m = bl.feasible_mask(d.rnd, d.seat, mem)
        if d.rnd.banker == d.seat:
            roles["banker"] += 1
            assert y[:, bl.KITTY].sum() == 0 and not m[:, bl.KITTY].any()
            assert np.array_equal(x[kitty_cols], bl._counts(d.rnd.buried))
            assert x[start["own_kitty_known"]] == 1.0
        else:
            roles["other"] += 1
            assert y[:, bl.KITTY].sum() == 8
            assert not x[kitty_cols].any() and x[start["own_kitty_known"]] == 0.0
        assert not np.any((y > 0) & ~m), "a true holder is outside the feasible mask"
    assert roles["banker"] and roles["other"]


def test_declared_cards_and_throw_pins_are_inputs(cluster):
    start = 0
    offsets = {}
    for name, width in bl.FEATURE_BLOCKS:
        offsets[name] = (start, start + width)
        start += width
    saw_decl = saw_unplayed = False
    for d in bl.iter_decisions(cluster):
        x = bl.belief_features(d.rnd, d.seat, d.refusals)
        lo, hi = offsets["declared_cards"]
        if d.rnd.declaration is not None:
            saw_decl |= x[lo:hi].sum() > 0
        for rel in (1, 2, 3):
            lo, hi = offsets[f"throw_unplayed_rel{rel}"]
            saw_unplayed |= x[lo:hi].sum() > 0
    assert saw_decl and saw_unplayed


def _write_cluster(tmp_path, name, records):
    shards = tmp_path / name / "shards"
    shards.mkdir(parents=True)
    with open(shards / "cluster-000000.jsonl", "w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return shards / "cluster-000000.jsonl"


def test_a_cluster_is_one_deal_in_one_split_and_screen_windows_are_excluded(tmp_path, cluster):
    path = _write_cluster(tmp_path, "store", cluster)
    got = bl.extract_cluster(path, store_index=0, cluster_index=0, calib=0.3, test=0.3,
                             windows=[], sampler_worlds=4, sampler_splits=("train", "calib", "test"),
                             sampler_stride=7)
    assert got["split"] == bl.split_of(got["deal_key"], 0.3, 0.3)
    assert len(set(got["deal"].tolist())) == 1 and set(got["round_index"].tolist()) == {0, 1}
    assert got["X"].shape == (len(cluster), bl.FEATURE_DIM)
    assert (got["S_n"][got["decision"] % 7 == 0] == 4).all()
    seed = cluster[0]["round_seed"]
    registry = {"windows": [{"name": "screen-x", "purpose": "screen", "span": [seed, seed + 1]},
                            {"name": "traj-x", "purpose": "trajectory", "span": [0, 10 ** 9]}]}
    windows = bl.excluded_windows(registry)
    assert windows == [(seed, seed + 1, "screen-x")]
    out = bl.extract_cluster(path, store_index=0, cluster_index=0, calib=0.3, test=0.3,
                             windows=windows, sampler_worlds=0, sampler_splits=())
    assert out == {"excluded": True, "path": str(path)}


def _extract_resume_fixture(tmp_path, monkeypatch, cluster):
    store = tmp_path / "store" / "shards"
    store.mkdir(parents=True)
    for index, seed in enumerate((1000, 1001)):
        records = synthetic_cluster(seed, throw_rate=0.1)
        with open(store / f"cluster-{index:06d}.jsonl", "w") as fh:
            for record in records:
                fh.write(json.dumps(record) + "\n")
    monkeypatch.setattr(bl, "excluded_windows", lambda registry=None: [])
    kwargs = dict(cluster_stride=1, cluster_offset=0, max_clusters_per_store=None,
                  calib=0.3, test=0.3, sampler_worlds=0, sampler_splits=(),
                  sampler_stride=1, workers=1, task_clusters=1,
                  log=lambda *a, **k: None)
    return store.parent, kwargs


def test_extract_resume_reuses_receipted_tasks_and_matches_fresh(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    fresh = tmp_path / "fresh"
    expected = bl.extract([str(store)], str(fresh), **kwargs)
    resumed = tmp_path / "resumed"
    bl.extract([str(store)], str(resumed), **kwargs)
    (resumed / "manifest.json").unlink()
    monkeypatch.setattr(bl, "extract_cluster",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("replayed")))
    got = bl.extract([str(store)], str(resumed), resume=True, **kwargs)
    assert [c["chunk"] for c in got["chunks"]] == [c["chunk"] for c in expected["chunks"]]
    for split in ("train", "calib", "test"):
        if split in {s for c in expected["chunks"] for s in c["files"]}:
            left, right = bl.load_split(fresh, split), bl.load_split(resumed, split)
            assert left.keys() == right.keys()
            for key in left:
                assert np.array_equal(left[key], right[key])


def test_extract_resume_recomputes_only_missing_task(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    fresh = tmp_path / "fresh"
    bl.extract([str(store)], str(fresh), **kwargs)
    out = tmp_path / "partial"
    bl.extract([str(store)], str(out), **kwargs)
    first_receipt = out / ".task-s00-00000.receipt.json"
    second_receipt = out / ".task-s00-00001.receipt.json"
    preserved = json.loads(first_receipt.read_text())["result"]["files"]
    preserved_path = out / next(iter(preserved.values()))["file"]
    mtime = preserved_path.stat().st_mtime_ns
    for info in json.loads(second_receipt.read_text())["result"]["files"].values():
        (out / info["file"]).unlink()
    second_receipt.unlink()
    got = bl.extract([str(store)], str(out), resume=True, **kwargs)
    assert preserved_path.stat().st_mtime_ns == mtime
    for split in ("train", "calib", "test"):
        if split in {s for c in got["chunks"] for s in c["files"]}:
            left, right = bl.load_split(fresh, split), bl.load_split(out, split)
            for key in left:
                assert np.array_equal(left[key], right[key])


def test_extract_resume_refuses_recipe_input_and_chunk_drift(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    out = tmp_path / "extract"
    bl.extract([str(store)], str(out), **kwargs)
    with pytest.raises(bl.BeliefLabelError, match="resume recipe changed"):
        bl.extract([str(store)], str(out), calib=0.2, resume=True,
                   **{k: v for k, v in kwargs.items() if k != "calib"})
    source = next(store.glob("shards/*.jsonl"))
    source.write_text(source.read_text() + "\n")
    with pytest.raises(bl.BeliefLabelError, match="resume recipe changed"):
        bl.extract([str(store)], str(out), resume=True, **kwargs)
    source.write_bytes(source.read_bytes()[:-1])
    chunk = next(out.glob("*.npz"))
    chunk.write_bytes(chunk.read_bytes() + b"corrupt")
    with pytest.raises(bl.BeliefLabelError, match="recorded chunk hash mismatch"):
        bl.extract([str(store)], str(out), resume=True, **kwargs)


def test_extract_default_refuses_existing_output(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    out = tmp_path / "extract"
    bl.extract([str(store)], str(out), **kwargs)
    with pytest.raises(FileExistsError):
        bl.extract([str(store)], str(out), **kwargs)


def test_extract_resume_refuses_same_size_manifest_shard_drift(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    source = next(store.glob("shards/*.jsonl"))
    raw = source.read_bytes()
    (store / "manifest.json").write_text(json.dumps({
        "schema": "shengji-trajectory-manifest-v1",
        "shards": [{"path": f"shards/{source.name}", "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw)}]}))
    out = tmp_path / "extract"
    bl.extract([str(store)], str(out), **kwargs)
    source.write_bytes(raw.replace(b'"SA"', b'"S2"', 1))
    with pytest.raises(bl.BeliefLabelError, match="resume recipe changed"):
        bl.extract([str(store)], str(out), resume=True, **kwargs)


def test_extract_resume_refuses_source_inventory_removal(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    out = tmp_path / "extract"
    bl.extract([str(store)], str(out), **kwargs)
    next(store.glob("shards/cluster-000001.jsonl")).unlink()
    with pytest.raises(bl.BeliefLabelError, match="resume recipe changed"):
        bl.extract([str(store)], str(out), resume=True, **kwargs)


def test_extract_resume_refuses_live_replay_identity_drift(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    out = tmp_path / "extract"
    bl.extract([str(store)], str(out), **kwargs)
    legal = (bl.Path(bl.__file__).resolve().parents[1] / "engine" / "legal.py").resolve()
    original = bl._file_sha256

    def drift(path):
        return "0" * 64 if bl.Path(path).resolve() == legal else original(path)

    monkeypatch.setattr(bl, "_file_sha256", drift)
    with pytest.raises(bl.BeliefLabelError, match="resume recipe changed"):
        bl.extract([str(store)], str(out), resume=True, **kwargs)


@pytest.mark.parametrize("name", ["SHENGJI_WEIGHTED_SPLITS", "SHENGJI_UNIFORM_DEAL",
                                 "SHENGJI_PHYSICAL_FILLS", "SHENGJI_REQUIRE_VOIDS"])
def test_extract_resume_refuses_sampler_runtime_drift(tmp_path, monkeypatch, cluster, name):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    out = tmp_path / "extract"
    monkeypatch.delenv(name, raising=False)
    bl.extract([str(store)], str(out), **kwargs)
    monkeypatch.setenv(name, "1")
    with pytest.raises(bl.BeliefLabelError, match="resume recipe changed"):
        bl.extract([str(store)], str(out), resume=True, **kwargs)


def test_extract_failed_cluster_has_no_consumer_manifest(tmp_path, monkeypatch, cluster):
    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    broken = next(store.glob("shards/cluster-000000.jsonl"))
    records = [json.loads(line) for line in broken.read_text().splitlines()]
    records[0]["seat"] = (int(records[0]["seat"]) + 1) % 4
    broken.write_text("".join(json.dumps(record) + "\n" for record in records))
    out = tmp_path / "extract"
    with pytest.raises(bl.BeliefLabelError, match="failed"):
        bl.extract([str(store)], str(out), **kwargs)
    assert not (out / "manifest.json").exists()
    failed = json.loads((out / "failed-manifest.json").read_text())
    assert failed["status"] == "failed" and failed["failed_clusters"]


def test_the_committed_registry_yields_the_screen_windows():
    from shengji import seeds
    windows = bl.excluded_windows(seeds.load(seeds.DEFAULT_REGISTRY))
    assert windows and all(hi > lo for lo, hi, _ in windows)


def test_sampler_counts_place_exactly_the_hidden_copies(cluster):
    banker_seen = refusal_seen = False
    for d in bl.iter_decisions(cluster):
        if d.decision_index % 11:
            continue
        counts, n, stats = bl.sampler_counts(d.rnd, d.seat, d.refusals, 8, seed=d.decision_index)
        mem = Memory(d.rnd, d.seat, own_kitty=True)
        assert n == 8
        assert np.array_equal(counts.sum(axis=1), bl.hidden_counts(mem) * 8)
        m = bl.feasible_mask(d.rnd, d.seat, mem)
        assert not np.any((counts > 0) & ~m), "the sampler put a copy on an infeasible receiver"
        if d.rnd.banker == d.seat:
            banker_seen = True
            assert counts[:, bl.KITTY].sum() == 0
        if d.refusals:
            refusal_seen = True
            assert "refusal_rejections" in stats      # release 45's refusal-aware branch
    assert banker_seen and refusal_seen


def test_split_fraction_is_salted_and_deterministic():
    key = "deck:" + "0" * 64
    assert bl.split_fraction(key) == bl.split_fraction(key)
    assert 0.0 <= bl.split_fraction(key) < 1.0
    assert bl.split_of(key, 0.0, 1.0) == "test"
    assert bl.split_of(key, 0.0, 0.0) == "train"


def test_completed_resume_preserves_existing_history_consumer(tmp_path, monkeypatch, cluster):
    from shengji.train import belief_history as history, belief_seq

    store, kwargs = _extract_resume_fixture(tmp_path, monkeypatch, cluster)
    out = tmp_path / "extract"
    bl.extract([str(store)], str(out), **kwargs)
    history.extract([str(out)], str(store.parent), workers=1, log=lambda *a, **k: None)
    manifest_path = out / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest_mtime = manifest_path.stat().st_mtime_ns
    expected = {}
    for split in ("train", "calib", "test"):
        for entry in belief_seq.extract_entries([str(out)], split):
            expected[entry["path"]] = belief_seq.load_part(
                entry, belief_seq.ROW_KEYS, belief_seq._Verified())

    bl.extract([str(store)], str(out), resume=True, **kwargs)
    for split in ("train", "calib", "test"):
        for entry in belief_seq.extract_entries([str(out)], split):
            actual = belief_seq.load_part(entry, belief_seq.ROW_KEYS, belief_seq._Verified())
            for key in belief_seq.ROW_KEYS:
                np.testing.assert_array_equal(actual[key], expected[entry["path"]][key])
    assert manifest_path.read_bytes() == manifest_bytes
    assert manifest_path.stat().st_mtime_ns == manifest_mtime
