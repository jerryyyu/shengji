"""S134 unified heads on the belief trunk (`train.unified_seq`, `train.suit_perm`, `ai.unified_numpy`).

Synthetic games from ``test_belief_labels`` stand in for a trajectory store; the store gets a real
manifest and per-shard sidecars (rounds with their outcome) so the outcome join, the extractors and the
trainer run their production paths.  Models are small and random.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import threading
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

import test_belief_labels as tbl  # noqa: E402
from test_belief_labels import synthetic_cluster  # noqa: E402

from shengji.ai import unified_numpy as un  # noqa: E402
from shengji.harvest.rebuild import round_from_setup  # noqa: E402
from shengji.train import belief_history as bh  # noqa: E402
from shengji.train import belief_labels as bl  # noqa: E402
from shengji.train import belief_seq as bs  # noqa: E402
from shengji.train import suit_perm as sp  # noqa: E402
from shengji.train import unified_readout as ur  # noqa: E402
from shengji.train import unified_seq as us  # noqa: E402

SMALL = dict(d=32, heads=4, enc_layers=2, xattn_layers=2, x_hidden=32, card_self_attn=True)
SUITS = "SHDC"
PARITY_TOL = 1e-4


# ------------------------------------------------------------------ synthetic store

def _nt_setup(deck, banker, declare):
    """A no-trump round: the seat dealt both big jokers declares them."""
    base = {"trump_rank": "2", "banker": banker, "declarations": [], "trump_suit": None, "trump_is_nt": False}
    rnd = round_from_setup(deck, base, stop_before_bury=True, check_trump=False)
    for s in range(4):
        dealt = Counter(rnd.hands[s]) - (Counter(rnd.kitty) if s == rnd.banker else Counter())
        if dealt["BJ"] == 2:
            base["declarations"] = [{"seat": s, "cards": ["BJ", "BJ"]}]
            break
    rnd = round_from_setup(deck, base, stop_before_bury=True, check_trump=False)
    base["trump_suit"] = rnd.trump_suit
    base["trump_is_nt"] = bool(rnd.trump_is_nt)
    base["buried"] = tbl.HeuristicBot().decide_bury(rnd, rnd.banker)
    base["banker"] = rnd.banker
    return base


def nt_cluster(seed):
    saved = tbl._setup_for
    tbl._setup_for = _nt_setup
    try:
        return synthetic_cluster(seed)
    finally:
        tbl._setup_for = saved


def _relabel(perm):
    def f(c):
        return c if c in ("LJ", "BJ") else SUITS[perm[SUITS.index(c[0])]] + c[1:]
    return f


def relabel_records(recs, perm):
    """The same games with every suit relabeled by ``perm`` (the trump suit too)."""
    f = _relabel(perm)
    out = []
    for r in recs:
        r = copy.deepcopy(r)
        r["deck"] = [f(c) for c in r["deck"]]
        s = r["setup"]
        if s.get("buried"):
            s["buried"] = [f(c) for c in s["buried"]]
        for d in s.get("declarations") or []:
            d["cards"] = [f(c) for c in d["cards"]]
        if s.get("trump_suit") in tuple(SUITS):
            s["trump_suit"] = SUITS[perm[SUITS.index(s["trump_suit"])]]
        for p in r["plays_prefix"]:
            p["cards"] = [f(c) for c in p["cards"]]
        r["action"] = [f(c) for c in r["action"]]
        if "engine_play" in r:
            r["engine_play"] = [f(c) for c in r["engine_play"]]
        out.append(r)
    return out


def _round_outcomes(recs):
    """Per mirror: (banker, attacker points, decisions), by replaying the games."""
    out = {}
    last = None
    for d in bl.iter_decisions(recs):
        last = d
        m = int(d.record["source_ref"].split(":")[2])
        o = out.setdefault(m, {"banker": int(d.rnd.banker), "decisions": 0, "rnd": d.rnd})
        o["decisions"] += 1
    assert last is not None
    for o in out.values():
        rnd = o.pop("rnd")
        assert rnd.phase == "round_end"
        o["attacker_points"] = int(rnd.attacker_points)
    return out


def write_store(root: Path, clusters, seed0=1000):
    """A trajectory store (manifest + shards + sidecars) of ``clusters`` (lists of records)."""
    sh = root / "shards"
    sh.mkdir(parents=True)
    shards = []
    for k, recs in enumerate(clusters):
        p = sh / f"cluster-{k:06d}.jsonl"
        with open(p, "w") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        seed = int(recs[0]["round_seed"])
        rounds = [dict(mirror=m, seed=seed, **o) for m, o in sorted(_round_outcomes(recs).items())]
        side = {"cluster": k, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "rounds": rounds}
        sp_ = sh / f"cluster-{k:06d}.json"
        sp_.write_text(json.dumps(side))
        shards.append({"cluster": k, "path": f"shards/{p.name}", "sha256": side["sha256"],
                       "bytes": p.stat().st_size, "sidecar": f"shards/{sp_.name}",
                       "sidecar_sha256": hashlib.sha256(sp_.read_bytes()).hexdigest(), "seed": seed})
    (root / "manifest.json").write_text(json.dumps({"schema": "shengji-trajectory-manifest-v1", "seed0": seed0,
                                                    "run_id": "syn", "shards": shards}))
    return root


def extract_dir(store: Path, out: Path, *, calib=0.0, test=0.0, task_clusters=10):
    bl.extract([str(store)], str(out), cluster_stride=1, cluster_offset=0, max_clusters_per_store=None,
               calib=calib, test=test, sampler_worlds=0, sampler_splits=(), sampler_stride=1, workers=1,
               task_clusters=task_clusters, log=lambda *a, **k: None)
    bh.extract([str(out)], str(store.parent), workers=1, log=lambda *a, **k: None)
    return out


def _seeds_with_throws(n, start=1000):
    out = []
    for seed in range(start, start + 200):
        recs = synthetic_cluster(seed)
        if sum("engine_play" in r for r in recs) >= 1:
            out.append(seed)
        if len(out) == n:
            return out
    pytest.fail("no synthetic seeds with failed throws")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("s134")
    seeds = _seeds_with_throws(3)
    clusters = [synthetic_cluster(s) for s in seeds] + [nt_cluster(1003)]
    assert clusters[-1][0]["setup"]["trump_is_nt"]
    store = write_store(root / "stores" / "corpus", clusters)
    data = extract_dir(store, root / "x", calib=0.5)
    assert us.entries_for([str(data)], "train") and us.entries_for([str(data)], "calib")
    return {"root": root, "store": store, "data": data, "clusters": clusters}


def _loaded(world):
    entries = us.entries_for([str(world["data"])], "train") + us.entries_for([str(world["data"])], "calib")
    idx = us.OutcomeIndex()
    parts = [us.load_unified_part(e, bs._Verified(), idx) for e in entries]
    return bs.concat_parts(parts), idx


def _batch_of(part, perm=None):
    rids = np.unique(part["row_round"])
    return us.make_unified_batch(part, rids, np.arange(len(part["X"])), perm=perm)


def test_stream_prebuilds_weighted_augmented_leaves_in_the_loader(world):
    entries = us.entries_for([str(world["data"])], "train")
    weights = np.arange(1, len(ur.CORPUS_HEADS) + 1, dtype=np.float32)
    for entry in entries:
        entry["corpus_w"] = weights
    options = dict(index=us.OutcomeIndex(), verified=bs._Verified(), suit_aug=True,
                   threads=1, buffer_chunks=1, rounds_per_batch=2, row_frac=1.0)
    caller = threading.get_ident()
    producers = []

    def build(part, round_ids, rows, *, perm):
        assert perm is not None
        producers.append(threading.get_ident())
        return ur.make_batch(part, round_ids, rows, perm=perm)

    baseline = us.Stream(entries, **options).batches(7, 1, prefetch=1)
    prefetched = us.Stream(entries, batch_builder=build, **options).batches(7, 1, prefetch=1)
    for (old_buffer, old), (new_buffer, new) in zip(baseline, prefetched, strict=True):
        assert new_buffer == old_buffer
        assert "leaf_row" not in old
        expected = {**old, **{f"leaf_{key}": value for key, value in ur.leaf_batch(old).items()}}
        assert new.keys() == expected.keys()
        np.testing.assert_array_equal(new["row_w"], np.broadcast_to(weights, new["row_w"].shape))
        for key, value in expected.items():
            np.testing.assert_array_equal(new[key], value, err_msg=key)
    assert producers and all(producer != caller for producer in producers)


# ------------------------------------------------------------------ suit permutation

def _extract_batch(recs, root: Path):
    store = write_store(root / "corpus", [recs])
    data = extract_dir(store, root / "x")
    part = bs.load_part(us.entries_for([str(data)], "train")[0], bs.ROW_KEYS, bs._Verified())
    return bs.make_batch(part, np.unique(part["row_round"]), np.arange(len(part["X"])))


@pytest.mark.parametrize("kind", ["suited", "no_trump"])
def test_relabeling_a_batch_equals_extracting_the_relabeled_games(tmp_path, kind):
    recs = synthetic_cluster(_seeds_with_throws(1)[0]) if kind == "suited" else nt_cluster(1003)
    assert bool(recs[0]["setup"]["trump_is_nt"]) == (kind == "no_trump")
    base = _extract_batch(recs, tmp_path / "base")
    moved = np.zeros(base["X"].shape[1], bool)
    for k, perm in enumerate(sp.PERMS[1:]):
        got = _extract_batch(relabel_records(recs, perm), tmp_path / f"p{k}")
        want = sp.apply(base, perm)
        assert set(got) == set(want)
        for key in got:
            assert np.array_equal(np.asarray(got[key]), np.asarray(want[key])), (perm, key)
        moved |= (np.asarray(want["X"]) != np.asarray(base["X"])).any(0)
        if kind == "suited":
            assert not np.array_equal(got["X"], base["X"])
    # the relabelings move the suited cards of the hand plane (jokers stay) and well over a hundred columns
    assert moved[:52].all() and not moved[52:54].any() and moved.sum() > 100


def test_the_24_relabelings_are_distinct_bijections_and_the_identity_is_a_no_op(world):
    part, _ = _loaded(world)
    b = bs.make_batch(part, np.unique(part["row_round"]), np.arange(len(part["X"])))
    gathers = {tuple(sp.feature_gather(p)) for p in sp.PERMS}
    assert len(sp.PERMS) == 24 and len(gathers) == 24
    for p in sp.PERMS:
        for g in (sp.feature_gather(p), sp.card_gather(p), sp.suit5_gather(p)):
            assert sorted(g.tolist()) == list(range(len(g)))
    same = sp.apply(b, sp.PERMS[0])
    assert all(np.array_equal(same[k], b[k]) for k in b)
    # applying perm then its inverse restores the batch
    p = (2, 0, 3, 1)
    inv = tuple(int(i) for i in np.argsort(p))
    back = sp.apply(sp.apply(b, p), inv)
    assert all(np.array_equal(back[k], b[k]) for k in b)
    with pytest.raises(ValueError):
        sp.apply(b, (0, 0, 1, 2))


def test_draws_are_uniform_over_the_24_and_seeded():
    a = [sp.draw(np.random.default_rng([1, 0, 0, 24])) for _ in range(3)]
    b = [sp.draw(np.random.default_rng([1, 0, 0, 24])) for _ in range(3)]
    assert a == b
    rng = np.random.default_rng(0)
    counts = Counter(sp.draw(rng) for _ in range(24000))
    assert set(counts) == set(sp.PERMS) and max(counts.values()) < 1.15 * 1000


# ------------------------------------------------------------------ outcome join

def test_every_row_gets_its_rounds_outcome_from_the_actors_side(world):
    part, idx = _loaded(world)
    assert len(part["X"]) == sum(len(c) for c in world["clusters"])
    from shengji.rl.value_afterstate import category_signed_level
    # replay truth: attacker points per (cluster, mirror)
    truth = {}
    for c, recs in enumerate(world["clusters"]):
        for m, o in _round_outcomes(recs).items():
            truth[(c, m)] = o
    for i in range(len(part["X"])):
        c, ri = int(part["cluster"][i]), int(part["round_index"][i])
        o = truth[(c, ri)]
        att = int(part["row_seat"][i]) % 2 != o["banker"] % 2
        assert part["q_target"][i] == us.outcome_category(o["attacker_points"], att)
        lvl = category_signed_level(int(part["q_target"][i]))
        assert (lvl > 0) == ((o["attacker_points"] >= 80) == att)
    rec = idx.manifests[str(world["store"])]
    assert rec["manifest_sha256"] == hashlib.sha256((world["store"] / "manifest.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("fault", ["seed", "banker", "decisions", "sidecar_bytes"])
def test_the_join_refuses_a_sidecar_that_disagrees(world, tmp_path, fault):
    import shutil
    store = tmp_path / "stores" / "corpus"
    shutil.copytree(world["store"], store)
    man = json.loads((store / "manifest.json").read_text())
    side_p = store / man["shards"][0]["sidecar"]
    side = json.loads(side_p.read_text())
    if fault == "seed":
        side["rounds"][0]["seed"] += 1
    elif fault == "banker":
        side["rounds"][0]["banker"] = (side["rounds"][0]["banker"] + 1) % 4
    elif fault == "decisions":
        side["rounds"][0]["decisions"] += 1
    else:                                  # an edited outcome the manifest's sha does not cover
        side["rounds"][0]["attacker_points"] += 5
    side_p.write_text(json.dumps(side))
    if fault != "sidecar_bytes":
        man["shards"][0]["sidecar_sha256"] = hashlib.sha256(side_p.read_bytes()).hexdigest()
        (store / "manifest.json").write_text(json.dumps(man))
    recorded = str(world["store"])
    idx = us.OutcomeIndex(us.parse_store_map([f"{world['data']}@{recorded}={store}"]))
    e = [x for x in us.entries_for([str(world["data"])], "train") + us.entries_for([str(world["data"])], "calib")
         if 0 in np.load(x["path"])["cluster"]][0]
    with pytest.raises(us.UnifiedSeqError):
        us.load_unified_part(e, bs._Verified(), idx)


def test_policy_targets_are_the_attempted_cards_and_lie_in_hand(world):
    part, _ = _loaded(world)
    b = _batch_of(part)
    t = b["pol_target"]
    hand = b["X"][:, :54] > 0
    assert (t.sum(-1) > 0).all() and not ((t > 0) & ~hand).any()
    failed = b["tok_f"][b["rr"], b["ply"], us._FAILED] > 0
    assert failed.any()
    assert np.array_equal(t[failed], b["tok_att"][b["rr"], b["ply"]][failed])
    # relabeled targets are the relabeled cards
    p = (1, 2, 3, 0)
    bp = _batch_of(part, perm=p)
    assert np.array_equal(bp["pol_target"], t[:, sp.card_gather(p)])
    assert np.array_equal(bp["q_target"], b["q_target"])


# ------------------------------------------------------------------ model

def _small_model(seed=0, **kw):
    torch.manual_seed(seed)
    m = us.build_unified(SMALL, **kw)
    # non-trivial head biases so a parity test cannot pass on zeros
    with torch.no_grad():
        for p in m.parameters():
            p.add_(0.01 * torch.randn_like(p))
    return m.eval()


def test_shapes_and_the_belief_head_is_the_served_networks(world):
    part, _ = _loaded(world)
    b = _batch_of(part)
    m = _small_model()
    tb = us.to_device(b, "cpu")
    with torch.no_grad():
        out = m(tb)
        ref = m.trunk(tb)
    B = len(b["X"])
    assert out["belief"].shape == (B, 54, 4) and out["q"].shape == (B, 204) and out["policy"].shape == (B, 54)
    assert torch.equal(out["belief"], ref)
    m.trunk.grouped_xattn = True
    with torch.no_grad():
        assert torch.allclose(m(tb)["belief"], ref, atol=1e-5)


def test_q_reads_the_actors_own_play_and_nothing_after_it(world):
    part, _ = _loaded(world)
    b = _batch_of(part)
    m = _small_model()
    i = int(np.flatnonzero((b["ply"] > 2) & (b["ply"] < b["tok_int"].shape[1] - 2))[0])
    r, ply = int(b["rr"][i]), int(b["ply"][i])
    with torch.no_grad():
        base = m(us.to_device(b, "cpu"))
    later = copy.deepcopy(b)
    later["tok_cards"][r, ply + 1:] = 0
    later["tok_f"][r, ply + 1:] = 0
    own = copy.deepcopy(b)
    own["tok_f"][r, ply] = own["tok_f"][r, ply] + 1.0
    with torch.no_grad():
        a = m(us.to_device(later, "cpu"))
        o = m(us.to_device(own, "cpu"))
    assert torch.allclose(a["q"][i], base["q"][i], atol=1e-6)
    assert torch.allclose(a["policy"][i], base["policy"][i], atol=1e-6)
    assert not torch.allclose(o["q"][i], base["q"][i], atol=1e-4)
    # the policy and belief heads read only the plays before the decision
    assert torch.allclose(o["policy"][i], base["policy"][i], atol=1e-6)
    assert torch.allclose(o["belief"][i], base["belief"][i], atol=1e-6)


def test_policy_detach_keeps_the_policy_loss_off_the_trunk(world):
    part, _ = _loaded(world)
    tb = us.to_device(_batch_of(part), "cpu")
    for detach in (False, True):
        m = _small_model(policy_detach=detach).train()
        L = us.losses(m, tb)
        (L["p_sum"] / L["rows"]).backward()
        g = m.trunk.encoder.layers[0].linear1.weight.grad
        moved = g is not None and float(g.abs().sum()) > 0
        assert moved != detach
        assert float(m.p_head[1].weight.grad.abs().sum()) > 0


# ------------------------------------------------------------------ numpy runtime

def test_numpy_runtime_matches_torch(world, tmp_path):
    part, _ = _loaded(world)
    b = _batch_of(part, perm=(3, 1, 0, 2))
    m = _small_model(seed=3)
    with torch.no_grad():
        out = m(us.to_device(b, "cpu"))
    sd = {k: v.detach().numpy() for k, v in m.state_dict().items()}
    trunk = {k[len("trunk."):]: v for k, v in sd.items() if k.startswith("trunk.")}
    heads = {k: v for k, v in sd.items() if not k.startswith("trunk.")}
    path = tmp_path / "u.npz"
    sha = un.save_package(path, m.config, trunk, heads, {"note": "test"})
    rt = un.load_unified_numpy(path, sha256=sha)
    with pytest.raises(un.UnifiedNumpyError):
        un.load_unified_numpy(path, sha256="0" * 64)
    qp = torch.softmax(out["q"].double(), -1).numpy()
    diffs = {"belief": 0.0, "policy": 0.0, "q": 0.0}
    for i in range(len(b["X"])):
        pre = un.batch_inputs(b, i, with_play=False)
        diffs["belief"] = max(diffs["belief"], float(np.abs(rt.belief_logits(pre) - out["belief"][i].numpy()).max()))
        diffs["policy"] = max(diffs["policy"], float(np.abs(rt.policy_logits(pre) - out["policy"][i].numpy()).max()))
        diffs["q"] = max(diffs["q"], float(np.abs(rt.q_probs(un.batch_inputs(b, i, with_play=True)) - qp[i]).max()))
        if i == 0:
            assert np.allclose(rt.belief_logits(pre), rt.trunk.logits(pre), atol=1e-6)
    assert max(diffs.values()) < PARITY_TOL, diffs


# ------------------------------------------------------------------ training CLI

def test_train_dryrun_seal_and_export(world, tmp_path):
    import shengji.ai.belief_numpy as bn
    torch.manual_seed(0)
    trunk = bs.build_model(**SMALL)
    init = tmp_path / "init.npz"
    bn.save_package(init, trunk.config, {k: v.detach().numpy() for k, v in trunk.state_dict().items()},
                    {"temperature": 1.0})
    common = ["train", "--data", str(world["data"]), "--init", str(init), "--threads", "1", "--loader-threads", "1",
              "--rounds-per-batch", "2", "--buffer-chunks", "1", "--calib-rows", "100000"]
    out = tmp_path / "run"
    assert us.main(common + ["--out", str(out), "--dryrun", "--dryrun-steps", "2"]) == 0
    assert "S134U DRYRUN OK" in (out / "dryrun.log").read_text() and not (out / "checkpoint.pt").exists()
    assert us.main(common + ["--out", str(out), "--init-sha256", "0" * 64]) == 1
    assert "S134U ABORT" in (out / "status.log").read_text()
    (out / "status.log").unlink()
    assert us.main(common + ["--out", str(out)]) == 0
    log = (out / "status.log").read_text()
    assert "S134U START" in log and "S134U DONE" in log and "INIT calib" in log
    inputs = json.loads((out / "inputs.json").read_text())
    assert inputs["init"]["sha256"] == us.sha256_file(init) and inputs["stores"]
    assert us.main(common + ["--out", str(out)]) == 2          # a sealed run is never re-run
    pkg = tmp_path / "u.npz"
    assert us.main(["export", "--ckpt", str(out / "best.pt"), "--out", str(pkg),
                    "--belief-ckpt", str(tmp_path / "belief.pt")]) == 0
    rt = un.load_unified_numpy(pkg)
    model, saved = bs.load_trained(str(tmp_path / "belief.pt"))
    assert model.config == rt.trunk.config
    assert us.main(["parity", "--ckpt", str(out / "best.pt"), "--pkg", str(pkg), "--sha256", rt.package_sha256,
                    "--data", str(world["data"]), "--split", "train", "--rows", "50"]) == 0
    assert us.main(["parity", "--ckpt", str(out / "best.pt"), "--pkg", str(pkg), "--data", str(world["data"]),
                    "--split", "train", "--rows", "50", "--tol", "0"]) == 1


def test_a_stopped_run_resumes_to_the_uninterrupted_runs_weights(world, tmp_path):
    import shengji.ai.belief_numpy as bn
    data = extract_dir(world["store"], tmp_path / "x1", calib=0.5, task_clusters=1)
    assert len(us.entries_for([str(data)], "train")) >= 2
    torch.manual_seed(0)
    trunk = bs.build_model(**SMALL)
    init = tmp_path / "init.npz"
    bn.save_package(init, trunk.config, {k: v.detach().numpy() for k, v in trunk.state_dict().items()},
                    {"temperature": 1.0})
    common = ["train", "--data", str(data), "--init", str(init), "--threads", "1", "--loader-threads", "1",
              "--rounds-per-batch", "1", "--buffer-chunks", "1", "--save-every", "0", "--head-warmup-buffers", "1"]
    whole, cut = tmp_path / "whole", tmp_path / "cut"
    assert us.main(common + ["--out", str(whole)]) == 0
    cut.mkdir()
    (cut / "STOP").touch()
    assert us.main(common + ["--out", str(cut)]) == 3
    assert "STOPPED" in (cut / "status.log").read_text()
    (cut / "STOP").unlink()
    assert us.main(common + ["--out", str(cut), "--q-weight", "2.0"]) == 1          # another recipe refuses
    assert us.main(common + ["--out", str(cut)]) == 0
    log = (cut / "status.log").read_text()
    assert "RESUME epoch 0 buffer 1" in log and "S134U DONE" in log
    a = torch.load(whole / "best.pt", weights_only=False)["model"]
    b = torch.load(cut / "best.pt", weights_only=False)["model"]
    assert all(torch.equal(a[k], b[k]) for k in a)


def test_store_map_rules_are_per_extract_dir():
    rules = us.parse_store_map(["/x/perf-v1@/root/=/fleet/perf/", "/root/=/fleet/cloud/"])
    idx = us.OutcomeIndex(rules)
    assert idx.resolve("/root/y/corpus", "/x/perf-v1/part-00") == "/fleet/perf/y/corpus"
    assert idx.resolve("/root/y/corpus", "/x/cloud-v1/part-00") == "/fleet/cloud/y/corpus"
    assert idx.resolve("/elsewhere/corpus", "/x/perf-v1") == "/elsewhere/corpus"
    with pytest.raises(us.UnifiedSeqError):
        us.parse_store_map(["no-equals"])


@pytest.mark.parametrize("change", ["head_warmup_buffers", "buffer_chunks", "weight_decay", "input_manifest"])
def test_a_resume_refuses_a_changed_recipe_or_input_before_any_update(world, tmp_path, change):
    import shengji.ai.belief_numpy as bn
    data = extract_dir(world["store"], tmp_path / "x", calib=0.5, task_clusters=1)
    torch.manual_seed(0)
    trunk = bs.build_model(**SMALL)
    init = tmp_path / "init.npz"
    bn.save_package(init, trunk.config, {k: v.detach().numpy() for k, v in trunk.state_dict().items()},
                    {"temperature": 1.0})
    common = ["train", "--data", str(data), "--init", str(init), "--threads", "1", "--loader-threads", "1",
              "--rounds-per-batch", "1", "--buffer-chunks", "1", "--save-every", "0", "--head-warmup-buffers", "1"]
    out = tmp_path / "run"
    out.mkdir()
    (out / "STOP").touch()
    assert us.main(common + ["--out", str(out)]) == 3
    (out / "STOP").unlink()
    before = (out / "checkpoint.pt").read_bytes()
    extra = {"head_warmup_buffers": ["--head-warmup-buffers", "2"], "buffer_chunks": ["--buffer-chunks", "2"],
             "weight_decay": ["--weight-decay", "0.02"], "input_manifest": []}[change]
    inputs = out / "inputs.json"
    original = inputs.read_bytes()
    if change == "input_manifest":                  # the chunks the run recorded are not the chunks seen now
        rec = json.loads(original)
        rec["chunk_sha256_digest"] = "0" * 64
        inputs.write_text(json.dumps(rec))
    assert us.main(common + ["--out", str(out)] + extra) == 1
    log = (out / "status.log").read_text()
    assert "S134U ABORT" in log and "resume:" in log and "RESUME" not in log and "S134U DONE" not in log
    assert (out / "checkpoint.pt").read_bytes() == before              # the refusal touched nothing
    inputs.write_bytes(original)
    assert us.main(common + ["--out", str(out)]) == 0                   # the unchanged recipe still resumes
    log = (out / "status.log").read_text()
    assert "RESUME epoch 0 buffer 1" in log and "S134U DONE" in log


def test_the_init_gate_refuses_before_any_update_and_on_a_resume_with_another_init(world, tmp_path):
    import shengji.ai.belief_numpy as bn
    data = extract_dir(world["store"], tmp_path / "x", calib=0.5, task_clusters=1)
    torch.manual_seed(0)
    trunk = bs.build_model(**SMALL)
    init = tmp_path / "init.npz"
    bn.save_package(init, trunk.config, {k: v.detach().numpy() for k, v in trunk.state_dict().items()},
                    {"temperature": 1.0})
    common = ["train", "--data", str(data), "--init", str(init), "--threads", "1", "--loader-threads", "1",
              "--rounds-per-batch", "1", "--buffer-chunks", "1", "--save-every", "0", "--head-warmup-buffers", "1"]
    wrong = tmp_path / "wrong"
    assert us.main(common + ["--out", str(wrong), "--expect-init-belief-ll", "0.5"]) == 1
    log = (wrong / "status.log").read_text()
    assert "S134U ABORT" in log and "does not round" in log and "epoch 1 buffer" not in log
    assert not (wrong / "checkpoint.pt").exists() and not (wrong / "best.pt").exists()
    line = next(x for x in log.splitlines() if " INIT calib " in x)
    ll = json.loads(line.split(" INIT calib ", 1)[1])["belief_ll"]
    expect = ["--expect-init-belief-ll", f"{ll:.5f}"]
    out = tmp_path / "run"
    out.mkdir()
    (out / "STOP").touch()
    assert us.main(common + ["--out", str(out)] + expect) == 3        # the matching INIT trains on
    (out / "STOP").unlink()
    ck = out / "checkpoint.pt"
    good = ck.read_bytes()
    for bad in (float("nan"), "0.98782", ll + 0.01):
        saved = torch.load(ck, weights_only=False)
        saved["state"]["init_calib"]["belief_ll"] = bad
        torch.save(saved, ck)
        assert us.main(common + ["--out", str(out)] + expect) == 1
        assert "RESUME" not in (out / "status.log").read_text()
        ck.write_bytes(good)
    assert us.main(common + ["--out", str(out)] + expect) == 0
    log = (out / "status.log").read_text()
    assert "RESUME epoch 0 buffer 1" in log and "S134U DONE" in log


def test_check_init_belief_ll_rules():
    us.check_init_belief_ll({"belief_ll": 0.9878241464563413}, 0.98782)
    us.check_init_belief_ll({}, None)
    for bad in ({"belief_ll": 0.97}, {"belief_ll": float("inf")}, {"belief_ll": None}, {}, None):
        with pytest.raises(us.UnifiedSeqError):
            us.check_init_belief_ll(bad, 0.98782)


def test_fixed_trunk_candidate_update_exports_served_scores(world, tmp_path):
    from shengji.harvest.legal import enumerate_legal
    from shengji.harvest.rebuild import state_for_record
    from shengji.train import search_free_head as trainer
    from shengji.train import search_free_play as sf
    from shengji.train import unified_readout

    entry = us.entries_for([str(world["data"])], "train")[0]
    verified = bs._Verified()
    part = us.load_unified_part(entry, verified, us.OutcomeIndex())
    tokens, row, slot, mean, played = [], [], [], [], []
    for i, ply in enumerate(part["row_ply"]):
        if ply not in (0, 4):
            continue
        records = bl.game_order(world["clusters"][part["cluster"][i]])
        rec = records[part["decision"][i]]
        rnd = state_for_record(rec)
        seat = rec["seat"]
        actions = enumerate_legal(rnd, seat, cap=20).actions
        if len(actions) < 2:
            continue
        other = next(a for a in actions if Counter(a) != Counter(rec["action"]))
        for j, action in enumerate((other, rec["action"])):
            tokens.append(sf.candidate_token(rnd, seat, action))
            row.append(i)
            slot.append(j)
            mean.append(0.2 * j)
            played.append(j == 1)
        if len(set(row)) == 2:
            break
    assert len(set(row)) == 2
    key = hashlib.sha256((str(entry["dir"]) + "|" + entry["sha256"]).encode()).hexdigest()[:20]
    arrays = dict(zip(("tok_int", "tok_f", "tok_cards", "tok_att"), map(np.stack, zip(*tokens))))
    np.savez(tmp_path / (key + ".npz"), n_rows=len(part["X"]), row=row, slot=slot, mean=mean,
             played=played, **arrays)
    b, c = next(trainer.candidate_batches(entry, tmp_path, verified, rounds_per_batch=16))
    torch.manual_seed(5)
    m = unified_readout.build(SMALL).eval()
    head = trainer.build_head(m.config["trunk"])
    before = {k: v.clone() for k, v in m.state_dict().items()}
    pred = trainer.score_batch(m, head, b, c)
    opt = torch.optim.SGD(head.parameters(), lr=0.01)
    assert trainer.fit_shard(m, head, opt, entry, tmp_path, verified, rounds_per_batch=16) == 2
    assert all(p.grad is None for p in m.parameters())
    assert all(torch.equal(v, before[k]) for k, v in m.state_dict().items())
    with torch.no_grad():
        after = torch.stack(trainer.score_batch(m, head, b, c)).numpy()
    assert not np.allclose(after, torch.stack(pred).detach().numpy())
    path = tmp_path / "sf.npz"
    sha = trainer.export(path, m, head, {})
    runtime = sf.load_package(path, sha256=sha)
    for i in range(len(b["X"])):
        inp = un.batch_inputs(b, i, with_play=False)
        keep = c["row"] == i
        live = runtime.score(inp, runtime.trunk_states(inp), [tokens[k] for k in np.flatnonzero(keep)])
        np.testing.assert_allclose(live, after[:, keep], atol=1e-4, rtol=1e-4)

    from shengji.harvest.legal import is_legal
    from shengji.train import relaxed_play as rp
    for builder in (rp.build_casual, rp.build_beginner):
        bot = builder(tbl.HeuristicBot(), path, seed=17, sha256=sha)
        assert is_legal(rnd, seat, bot.decide_play(rnd, seat))
        assert bot.last_decision_record["schema"] == rp.RECORD_SCHEMA

    np.savez(tmp_path / (key + ".npz"), n_rows=len(part["X"]), row=row, slot=slot,
             mean=mean, played=np.logical_not(played), **arrays)
    with pytest.raises(ValueError, match="recorded attempt"):
        next(trainer.candidate_batches(entry, tmp_path, verified))
