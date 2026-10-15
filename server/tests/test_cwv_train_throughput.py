"""The training-throughput changes (perf audit B1, board D10) move wall time and
nothing else.

* The loader prefetch thread gathers the next value batch and its root batch
  while the current step runs.
* The host-side row plans (``host_used_rows``, ``ballot_rows``) let the search
  head and the listwise policy loss select their rows with index tensors
  instead of boolean masks, whose ``nonzero`` makes the host wait for the
  device several times a batch.
* The startup row count uses the deal keys the store already recorded, and the
  stratified prior reads five columns per shard in a process pool.

Each is compared with the path it replaces, on the same seed: weights equal
bit for bit, every logged number equal.
"""
from __future__ import annotations

import glob
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.rl.value_afterstate import (MAX_SIGNED_LEVEL_UTILITY,  # noqa: E402
                                         MIN_SIGNED_LEVEL_UTILITY)
from shengji.train import cwv_data, train_cwv  # noqa: E402
from shengji.train import policy_prior as pp  # noqa: E402
from shengji.train import search_mean_target as smt  # noqa: E402
from shengji.train import search_mean_sidecar as sc  # noqa: E402
from shengji.train.data import SplitSelector, split_deals  # noqa: E402
from shengji.train.policy_prior import EXPLORE_FLAG_BEAT  # noqa: E402
from shengji.train.policy_rows import explore_row_weights  # noqa: E402
from tests.test_cwv_train import THIRDS, store_dir, other_dir, records  # noqa: F401, E402


def _bits(t: torch.Tensor) -> torch.Tensor:
    """A float tensor's raw bits (so -0.0 and 0.0 differ, as do NaN payloads)."""
    t = t.detach().contiguous()
    return t.view(torch.int32) if t.dtype == torch.float32 else t


def _same_bits(a: torch.Tensor, b: torch.Tensor) -> bool:
    return a.dtype == b.dtype and a.shape == b.shape and torch.equal(_bits(a), _bits(b))


def _strip_secs(value):
    """Drop what differs between two identical runs: timings (keys ending in
    ``secs``) and the out-dir path a candidate set was saved to."""
    if isinstance(value, dict):
        return {k: _strip_secs(v) for k, v in value.items()
                if not str(k).endswith("secs") and k != "saved_to"}
    if isinstance(value, list):
        return [_strip_secs(v) for v in value]
    return value


# ------------------------------------------------------------ the training run

@pytest.fixture(scope="module")
def c14_kw(store_dir, tmp_path_factory):  # noqa: F811
    """A C14-shaped toy run: grid trunk, aux points head, search-mean head on
    a sidecar, policy head on tagged soft-target root rows with an explore
    weight."""
    from scripts.compose_policy_rows import compose
    tmp = tmp_path_factory.mktemp("throughput")
    side = tmp / "sidecar"
    built = [sc.build_sidecar(p, side, level_objective=False)
             for p in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True))]
    assert built and sum(c["with_mean"] for c in built) > 0
    tagged = tmp / "tagged"
    pp.extract(tagged, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1,
               chunk_rows=64)
    composed = tmp / "composed"
    compose(composed, [("fixture", tagged)])
    return tmp, dict(
        data=[str(store_dir)], arch="mlp", device="cpu", epochs=2, seed=7, batch_size=64,
        n_boot=10, hidden=32, trunk_block="grid", grid_channels=4, aux_points=True,
        search_head=True, search_mean_sidecar=str(side), policy_head=True,
        policy_rows=str(composed), policy_batch_fraction=0.5, policy_soft_targets=True,
        policy_explore_weight=2.0, log=None, cache_workers=1, eval_workers=1, bench_batch=32,
        val_rank_records=50, encoder_version=2, **THIRDS)


def _run(tmp, kw, name, monkeypatch, *, prefetch: str, host_rows: str):
    monkeypatch.setenv("SHENGJI_CWV_PREFETCH", prefetch)
    monkeypatch.setenv("SHENGJI_CWV_HOST_ROWS", host_rows)
    receipt = train_cwv.train(out=tmp / name, **kw)
    return receipt, tmp / name


def test_prefetch_and_host_rows_train_bit_identical(c14_kw, monkeypatch):
    tmp, kw = c14_kw
    ref, ref_dir = _run(tmp, kw, "inline-device-rows", monkeypatch, prefetch="0", host_rows="0")
    trace = tmp / "loss-trace.jsonl"
    monkeypatch.setenv("SHENGJI_CWV_LOSS_TRACE", str(trace))
    new, new_dir = _run(tmp, kw, "prefetch-host-rows", monkeypatch, prefetch="2", host_rows="1")
    monkeypatch.delenv("SHENGJI_CWV_LOSS_TRACE")
    windows = [json.loads(line) for line in open(trace)]
    for epoch in (1, 2):
        mine = [w for w in windows if w["epoch"] == epoch]
        assert sum(w["rows"] for w in mine) == new["epochs"][epoch - 1]["train"]["rows"]
    # the run exercised every changed site
    ep = new["epochs"][0]["train"]
    assert ep["search_head_rows"] > 0 and ep["policy_rows"] > 0 and ep["batches"] >= 2
    assert new["config"]["policy_explore_weight"] == 2.0 and new["config"]["policy_soft_targets"]
    for a, b in zip(ref["epochs"], new["epochs"]):
        assert _strip_secs(a["train"]) == _strip_secs(b["train"])
        assert _strip_secs(a["val"]) == _strip_secs(b["val"])
    assert len(ref["epochs"]) == len(new["epochs"]) == 2
    for key in ("final", "selection", "baselines", "split", "population", "best_epoch"):
        assert _strip_secs(ref[key]) == _strip_secs(new[key]), key
    for name in ["best.pt"] + [f"checkpoints/epoch-{e:02d}.pt" for e in (1, 2)]:
        m_ref, meta_ref, aux_ref = train_cwv.load_cwv_checkpoint(ref_dir / name)
        m_new, meta_new, aux_new = train_cwv.load_cwv_checkpoint(new_dir / name)
        s_ref, s_new = m_ref.state_dict(), m_new.state_dict()
        assert s_ref.keys() == s_new.keys()
        for key in s_ref:
            assert _same_bits(s_ref[key], s_new[key]), (name, key)
        assert meta_ref["aux_points_head"] == meta_new["aux_points_head"]


# ------------------------------------------------------- search-head row plan

def _soft_inputs(rng, b, *, mean_scale=150.0, level_edge=None, huge=False):
    mean = (rng.normal(size=b) * mean_scale).astype(np.float32)
    mean[rng.random(b) < 0.3] = np.nan
    level = np.full(b, np.nan, np.float32)
    direct = rng.random(b) < 0.3
    level[direct] = rng.uniform(-6, 6, size=int(direct.sum())).astype(np.float32)
    if level_edge is not None:
        level[0] = np.float32(level_edge)
    if huge:
        mean[1] = np.float32(1e9)       # far outside the support (a level would override it)
        level[1] = np.nan
    role = rng.random(b) < 0.5
    if huge:
        role[1] = True                  # the attacker's huge mean ramps far above the support
    realised = rng.integers(0, 204, size=b)
    return mean, level, role, realised


@pytest.mark.parametrize("case", ["typical", "no_level", "near_low_edge", "near_high_edge",
                                  "outside", "none_used"])
def test_host_used_rows_equal_the_device_mask_or_decline(case):
    rng = np.random.default_rng(11)
    for trial in range(20):
        b = 257
        kw = {}
        if case == "near_low_edge":
            kw["level_edge"] = MIN_SIGNED_LEVEL_UTILITY + 0.5
        if case == "near_high_edge":
            kw["level_edge"] = MAX_SIGNED_LEVEL_UTILITY - 0.25
        if case == "outside":
            kw["huge"] = True
        mean, level, role, realised = _soft_inputs(rng, b, **kw)
        if case == "none_used":
            mean[:] = np.nan
            level[:] = np.nan
        lvl = None if case == "no_level" else level
        t_mean, t_role = torch.from_numpy(mean), torch.from_numpy(role)
        t_real = torch.from_numpy(realised)
        t_lvl = None if lvl is None else torch.from_numpy(lvl)
        probs, used = smt.soft_targets(t_mean, t_role, t_real, level=t_lvl)
        rows = smt.host_used_rows(mean, role, lvl)
        if case in ("near_low_edge", "near_high_edge", "outside"):
            assert rows is None          # a row inside the margin: the device decides
            continue
        assert rows is not None
        assert np.array_equal(rows, torch.nonzero(used).squeeze(1).numpy())
        probs2, used2 = smt.soft_targets(t_mean, t_role, t_real, level=t_lvl,
                                         rows=torch.from_numpy(rows))
        assert _same_bits(probs, probs2) and torch.equal(used, used2)


def test_search_head_loss_through_index_rows_matches_the_mask_bit_for_bit():
    rng = np.random.default_rng(5)
    mean, level, role, realised = _soft_inputs(rng, 300)
    t = {k: torch.from_numpy(v) for k, v in
         (("mean", mean), ("level", level), ("role", role), ("real", realised))}
    rows = smt.host_used_rows(mean, role, level)
    assert rows is not None and 0 < rows.size < 300
    w = torch.randn(16, 204)
    feats = torch.randn(300, 16)

    def run(select_with_rows: bool):
        weight = w.clone().requires_grad_(True)
        logits = feats @ weight
        idx = torch.from_numpy(rows) if select_with_rows else None
        probs, used = smt.soft_targets(t["mean"], t["role"], t["real"], level=t["level"], rows=idx)
        sel = idx if select_with_rows else used
        loss = torch.nn.functional.cross_entropy(logits[sel], probs[sel])
        loss.backward()
        return loss.detach(), weight.grad

    loss_mask, grad_mask = run(False)
    loss_rows, grad_rows = run(True)
    assert _same_bits(loss_mask, loss_rows) and _same_bits(grad_mask, grad_rows)


# ------------------------------------------------------------- ballot rows

def _ballot_inputs(rng, b=97, slots=6, cards=3):
    logits = torch.from_numpy(rng.normal(size=(b, 54)).astype(np.float32))
    ball = rng.integers(0, 54, size=(b, slots, cards))
    ball[rng.random((b, slots, cards)) < 0.3] = -1
    mask = rng.random((b, slots)) < 0.8
    mask[:, 0] = True
    tgt = rng.integers(0, slots, size=b)
    tgt[rng.random(b) < 0.25] = -1
    vals = rng.normal(size=(b, slots)).astype(np.float32) * 30
    vals[rng.random((b, slots)) < 0.3] = np.nan
    weight = torch.where(torch.from_numpy(rng.random(b) < 0.2), 2.0, 1.0).to(torch.float32)
    return (logits, torch.from_numpy(ball), torch.from_numpy(mask), torch.from_numpy(tgt),
            torch.from_numpy(vals), weight)


@pytest.mark.parametrize("soft", [True, False])
@pytest.mark.parametrize("weighted", [True, False])
@pytest.mark.parametrize("all_missing", [False, True])
def test_listwise_losses_through_ballot_rows_match_the_mask_bit_for_bit(soft, weighted, all_missing):
    rng = np.random.default_rng(3)
    logits, ball, mask, tgt, vals, weight = _ballot_inputs(rng)
    if all_missing:
        tgt[:] = -1
    rows = torch.from_numpy(pp.ballot_rows(tgt.numpy()))

    def run(r):
        lg = logits.clone().requires_grad_(True)
        w = weight if weighted else None
        if soft:
            loss = pp.listwise_loss_soft(lg, ball, mask, tgt, vals, 1.0, row_weight=w, rows=r)
        else:
            loss = pp.listwise_loss(lg, ball, mask, tgt, row_weight=w, rows=r)
        loss.backward()
        return loss.detach(), lg.grad

    loss_mask, grad_mask = run(None)
    loss_rows, grad_rows = run(rows)
    assert _same_bits(loss_mask, loss_rows)
    assert _same_bits(grad_mask, grad_rows)


def test_explore_weights_equal_the_masked_assignment():
    flag = torch.from_numpy(np.random.default_rng(1).integers(0, 3, size=500))
    for weight in (2.0, 0.37, 1e-3):
        old = torch.ones(flag.shape, dtype=torch.float32)
        old[flag == EXPLORE_FLAG_BEAT] = float(weight)
        assert _same_bits(explore_row_weights(flag, weight), old)
    assert explore_row_weights(flag, 1.0) is None


# ---------------------------------------------------------------- prefetch

def test_prefetch_yields_the_inline_items_and_random_draws_in_order():
    def produce():
        rng = np.random.default_rng(9)
        for _ in range(200):
            yield rng.integers(0, 1 << 30, size=3)
    inline = list(produce())
    with cwv_data.Prefetch(produce, depth=2) as ahead:
        fetched = list(ahead)
    assert len(fetched) == len(inline)
    assert all(np.array_equal(a, b) for a, b in zip(inline, fetched))


def test_prefetch_reraises_the_producer_error_after_the_items_before_it():
    def produce():
        yield from range(5)
        raise ValueError("loader failed")
    got = []
    with pytest.raises(ValueError, match="loader failed"):
        with cwv_data.Prefetch(produce, depth=3) as ahead:
            for item in ahead:
                got.append(item)
    assert got == list(range(5))


def test_prefetch_close_mid_stream_runs_the_generator_cleanup_on_its_thread():
    seen = {}

    def produce():
        try:
            for i in range(10_000):
                yield i
        finally:
            seen["cleanup_thread"] = threading.current_thread().name

    ahead = cwv_data.Prefetch(produce, depth=2)
    first = [next(ahead) for _ in range(3)]
    ahead.close()
    assert first == [0, 1, 2]
    assert seen["cleanup_thread"] == "cwv-prefetch"
    assert not ahead._thread.is_alive()
    with pytest.raises(StopIteration):
        next(ahead)


def test_prefetch_stops_when_the_consumer_raises():
    seen = {"closed": False}

    def produce():
        try:
            yield from range(10_000)
        finally:
            seen["closed"] = True

    with pytest.raises(RuntimeError, match="step failed"):
        with cwv_data.Prefetch(produce, depth=2) as ahead:
            for item in ahead:
                if item == 4:
                    raise RuntimeError("step failed")
    assert seen["closed"]


# ------------------------------------------------------------------ startup

def _stores(store_dir, tmp_path):  # noqa: F811
    """The fixture's shard store (one deal per shard) and the same records as
    one jsonl file, whole and limited to its first deals (one shard holding
    several deals, so a split straddles it; the limit gives it kept rows),
    then two of them in the trick-end flavour, whose derived rows only the
    train part selects."""
    merged = tmp_path / "merged" / "all.jsonl"
    merged.parent.mkdir()
    with open(merged, "wb") as out:
        for path in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True)):
            out.write(open(path, "rb").read())
    out = []
    for data, limit, trick_end in ((store_dir, None, False), (merged, None, False),
                                   (merged, 4, False), (store_dir, None, True),
                                   (merged, 4, True)):
        prepared = cwv_data.prepare_stores([str(data)], tmp_path / "cache", limit_clusters=limit,
                                           history=False, witness_seed=7, cache_workers=1,
                                           version=2, trick_end=trick_end)
        out.append(prepared.block_store)
    return out


def _decode_counts(store, masks):
    counts = {part: 0 for part in masks}
    for block in store.iter_blocks():
        for part, fn in masks.items():
            counts[part] += int(fn(block).sum())
    return counts


def test_split_row_counts_and_parallel_baselines_match_full_decodes(store_dir, tmp_path):  # noqa: F811
    stores = _stores(store_dir, tmp_path)
    assert len(stores[1]) == 1 and len(stores[1].keys_of(0)) > 1
    assert stores[2].keep_idx[0] is not None
    assert all(meta.get("trick_end") for meta in stores[3].metas)
    assert stores[3].block(0).trick_end.any()
    for store in stores:
        assignment = split_deals(store.keys(), seed=7, **THIRDS)
        masks = {part: SplitSelector(assignment, part) for part in ("train", "val", "test")}
        assert cwv_data.split_row_counts(store, masks) == _decode_counts(store, masks)
        # a selector that is not a deal-key split falls back to decoding every block
        generic = {"all": lambda block: np.ones(block.n, dtype=bool)}
        assert cwv_data.split_row_counts(store, generic) == _decode_counts(store, generic)
        serial = train_cwv.fit_baselines(store, masks["train"])
        parallel = train_cwv.fit_baselines(store, masks["train"], workers=2)
        assert serial == parallel
        assert serial["stratified_prior"]["n"] > 0


def test_read_columns_equal_the_decoded_block(store_dir, tmp_path):  # noqa: F811
    for store in _stores(store_dir, tmp_path):
        for i, cols in store.iter_columns(train_cwv.BASELINE_COLUMNS, workers=2, chunk=1):
            block = store.block(i)
            for name in train_cwv.BASELINE_COLUMNS:
                assert np.array_equal(cols[name], getattr(block, name)), name
            assert cols["ply"].dtype == block.ply.dtype
            if block.trick_end is None:
                assert "trick_end" not in cols
            else:
                assert np.array_equal(cols["trick_end"], block.trick_end)


def test_split_row_counts_decodes_only_straddling_shards(store_dir, tmp_path, monkeypatch):  # noqa: F811
    store = _stores(store_dir, tmp_path)[0]
    assignment = split_deals(store.keys(), seed=7, **THIRDS)
    masks = {part: SplitSelector(assignment, part) for part in ("train", "val", "test")}
    monkeypatch.setattr(type(store), "block",
                        lambda self, i, **kw: pytest.fail("decoded a single-deal shard"))
    counts = cwv_data.split_row_counts(store, masks)
    assert sum(counts.values()) == sum(store.rows())


# ------------------------------------------------------- --val-rows, --compile

def test_val_rows_and_compile_are_recorded_only_when_set():
    base = dict(data=["/nonexistent"], arch="mlp")
    plain = train_cwv.build_config(**base)
    assert "val_rows" not in plain and "compile" not in plain
    cfg = train_cwv.build_config(**base, val_rows=5000, compile_trunk=True)
    assert cfg["val_rows"] == 5000 and cfg["compile"] == "trunk"
    assert train_cwv.config_sha256(cfg) != train_cwv.config_sha256(plain)
    with pytest.raises(train_cwv.TrainError, match="--val-rows"):
        train_cwv.build_config(**base, val_rows=0)
    with pytest.raises(train_cwv.TrainError, match="--compile"):
        train_cwv.build_config(data=["/nonexistent"], arch="seq", compile_trunk=True)
    args = train_cwv.build_parser().parse_args(["train", "--data", "x", "--out", "y"])
    assert args.val_rows is None and args.compile_trunk is False


def test_compiled_trunk_keeps_the_eager_parameter_names():
    """``--compile`` compiles the trunk in place, so the state dict (and every
    checkpoint saved from it) keeps the eager module's keys and loads into an
    eager network.  Compilation itself waits for the first forward, which this
    test never runs."""
    cfg = train_cwv.model_config("mlp", hidden=32, trunk_layers=3, trunk_block="grid",
                                 grid_channels=4, search_head=True, policy_head=True,
                                 encoder_version=2)
    eager = train_cwv.ValueNetwork(cfg)
    compiled = train_cwv.ValueNetwork(cfg)
    compiled.load_state_dict(eager.state_dict())
    compiled.trunk.compile()
    assert list(compiled.state_dict()) == list(eager.state_dict())
    reloaded = train_cwv.ValueNetwork(cfg)
    reloaded.load_state_dict(compiled.state_dict())          # strict: same keys, same shapes


def test_val_rows_scores_each_epoch_on_one_seeded_subset_and_the_final_pass_on_all(
        c14_kw, monkeypatch):
    tmp, kw = c14_kw
    full = train_cwv.train(out=tmp / "val-full", **kw)
    n_val = full["split"]["val_records"]
    sub = train_cwv.train(out=tmp / "val-sub", val_rows=max(1, n_val // 3), **kw)
    again = train_cwv.train(out=tmp / "val-sub-again", val_rows=max(1, n_val // 3), **kw)
    block = sub["selection"]["val_subset"]
    assert "val_subset" not in full["selection"]
    assert sub["config"]["val_rows"] == max(1, n_val // 3) and "val_rows" not in full["config"]
    assert block["rows_requested"] <= block["rows"] <= n_val
    assert block["val_deals"] == full["split"]["val_deals"]
    assert again["selection"]["val_subset"] == block            # seeded: the same subset
    for epoch in sub["epochs"]:
        assert epoch["val"]["n"] == block["rows"]               # every epoch, the same rows
    assert sub["final"]["val"]["n"] == n_val                    # the final pass reads them all
    # training itself is untouched: the same weights as the full-validation run
    for a, b in zip(full["epochs"], sub["epochs"]):
        assert _strip_secs(a["train"]) == _strip_secs(b["train"])
    # the rank metrics read the candidate set, not the subset rows
    assert full["epochs"][0]["val"]["rank_regret"] == sub["epochs"][0]["val"]["rank_regret"]


class _FakeStore:
    """Single-deal shards of known sizes (what ``val_row_subset`` reads)."""

    def __init__(self, sizes):
        self.sizes = list(sizes)
        self.metas = [{} for _ in self.sizes]          # no trick-end rows

    def __len__(self):
        return len(self.sizes)

    def rows(self):
        return list(self.sizes)

    def keys_of(self, i):
        return [f"deal-{i:03d}"]

    def block(self, i, **kw):
        raise AssertionError("single-deal shards are counted without decoding")


def test_val_row_subset_takes_whole_seeded_deals_until_the_rows_are_covered():
    sizes = np.random.default_rng(2).integers(50, 200, size=60).tolist()
    store = _FakeStore(sizes)
    assignment = {f"deal-{i:03d}": ("val" if i % 3 == 0 else "train") for i in range(60)}
    val_total = sum(n for i, n in enumerate(sizes) if i % 3 == 0)
    selector, block = train_cwv.val_row_subset(store, assignment, 1000, seed=7)
    assert 1000 <= block["rows"] < val_total and block["deals"] < block["val_deals"] == 20
    chosen = [f"deal-{i:03d}" for i in range(60)
              if bool(selector(SimpleNamespace(deal_key=np.asarray([f"deal-{i:03d}"]))).all())]
    assert all(assignment[k] == "val" for k in chosen) and len(chosen) == block["deals"]
    assert block["rows"] == sum(sizes[int(k[5:])] for k in chosen)
    # the deals are a prefix of the seeded order, cut at the first one that covers the rows
    val_keys = sorted(k for k, v in assignment.items() if v == "val")
    order = np.random.default_rng([7, train_cwv.VAL_SUBSET_STREAM]).permutation(len(val_keys))
    taken = [val_keys[j] for j in order[:block["deals"]]]
    assert sorted(taken) == chosen
    assert block["rows"] - sizes[int(taken[-1][5:])] < 1000
    assert train_cwv.val_row_subset(store, assignment, 1000, seed=7)[1] == block
    assert train_cwv.val_row_subset(store, assignment, 1000, seed=8)[1]["digest"] != block["digest"]
    _sel, everything = train_cwv.val_row_subset(store, assignment, 10 ** 9, seed=7)
    assert everything["rows"] == val_total and everything["deals"] == 20


def test_sidecar_manifest_digest_does_not_depend_on_the_hash_threads(c14_kw):
    import hashlib
    from pathlib import Path
    tmp, kw = c14_kw
    side = Path(kw["search_mean_sidecar"])
    serial = hashlib.sha256(sc.SIDECAR_SCHEMA.encode("ascii"))
    for p in sorted(side.glob("*.npz")):
        serial.update(f"{p.name}:{sc.shard_sha256(p)}\n".encode("ascii"))
    assert len(list(side.glob("*.npz"))) > 1
    for workers in (1, 3, 8):
        assert sc.manifest_sha256(side, workers=workers) == serial.hexdigest()


def test_device_copies_keep_host_arrays_until_the_device_passes_their_step():
    log = []

    class Event:
        count = 0

        def __init__(self):
            Event.count += 1
            self.n = Event.count

        def record(self):
            log.append(("record", self.n))

        def synchronize(self):
            log.append(("sync", self.n))

    copies = cwv_data.DeviceCopies("cpu", 2, event=Event)
    held = []
    for step in range(4):
        copies.begin_step()
        array = np.full(3, step, dtype=np.float32)
        out = copies(array)
        assert torch.equal(out, torch.from_numpy(array))
        held.append([h for h in copies._held])
        copies.end_step()
        # never more than ``depth`` steps unfinished, and the oldest is waited for first
        assert len(copies._ring) <= 2
    assert log == [("record", 1), ("record", 2), ("sync", 1), ("record", 3), ("sync", 2),
                   ("record", 4)]
    assert [len(h) for _e, h in copies._ring] == [1, 1]
    copies.drain()
    assert copies._ring == [] and log[-2:] == [("sync", 3), ("sync", 4)]
    plain = cwv_data.DeviceCopies("cpu", 2)       # no event on the CPU: a plain copy
    assert plain.depth == 0 and torch.equal(plain(np.arange(3)), torch.arange(3))
    plain.begin_step(); plain.end_step(); plain.drain()
