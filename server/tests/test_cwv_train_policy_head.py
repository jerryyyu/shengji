"""#425: the joint net — a policy head on the value trunk, mixed root/value batches,
warm start from a headless incumbent, matched twin, and consumer loading."""
from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import policy_prior as pp
from shengji.train import train_cwv
from tests.test_cwv_train import THIRDS, store_dir, other_dir, records  # noqa: F401
from shengji.train.policy_rows import PolicyRows
from shengji.train.train_cwv import exposure_sets


def test_policy_head_config_is_optional_in_the_payload_and_builds_the_module():
    plain = ValueModelConfig(architecture="mlp", width=16, history_layers=1, attention_heads=1,
                             feedforward_width=32, public_dim=561, enc_version=2)
    assert "policy_head" not in plain.payload()
    joint = ValueModelConfig(**{**plain.__dict__, "policy_head": True})
    assert joint.payload()["policy_head"] is True
    assert ValueModelConfig.from_payload(joint.payload()) == joint
    net = ValueNetwork(joint)
    assert net.policy_head.out_features == 54
    with pytest.raises(Exception):
        ValueNetwork(plain).policy_logits(torch.zeros(1, 16))
    x = torch.zeros(2, 833)
    assert net.policy_logits(net.features_flat(x)).shape == (2, 54)
    with pytest.raises(Exception):
        ValueModelConfig(**{**plain.__dict__, "architecture": "transformer", "policy_head": True}).validate()


@pytest.fixture(scope="module")
def policy_rows(store_dir, tmp_path_factory):  # noqa: F811
    out = tmp_path_factory.mktemp("rows") / "rows"
    summary = pp.extract(out, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    assert summary["rows"] > 20 and summary["deals"] >= 1
    return str(out)


def test_joint_net_trains_from_a_headless_incumbent_and_the_twin_matches_steps(
        store_dir, policy_rows, tmp_path):  # noqa: F811
    from shengji.ai.cwv_policy import load_cwv_checkpoint as consumer_load
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=10, hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32,
              val_rank_records=50, encoder_version=2, aux_points=True, **THIRDS)
    base = train_cwv.train(out=tmp_path / "base", **kw)
    assert "policy_head" not in base["model"]["config"] and base["policy_head"] is None
    with pytest.raises(train_cwv.TrainError, match="needs --policy-rows"):
        train_cwv.train(out=tmp_path / "bad", policy_head=True, **kw)
    with pytest.raises(train_cwv.TrainError, match="need --policy-head"):
        train_cwv.train(out=tmp_path / "bad2", policy_rows=policy_rows, **kw)

    joint = train_cwv.train(out=tmp_path / "joint", policy_head=True, policy_rows=policy_rows,
                            policy_eval=policy_rows, policy_weight=1.0, policy_listwise_weight=1.0,
                            policy_batch_fraction=0.5, init=str(tmp_path / "base" / "best.pt"),
                            init_exclude_exposed=True, **kw)
    assert joint["model"]["config"]["policy_head"] is True
    assert joint["init"]["policy_head_fresh"] is True and joint["init"]["aux_points_head_loaded"] is True
    block = joint["policy_head"]
    assert block["twin"] is False and block["root_batch"] == 32 and block["rows"]["rows_used"] > 0
    # Codex HOLD on #428: root rows share the value store's three deals (train/val/test), so the
    # rows on the val/test deals and on the policy-eval deals are DROPPED, the kept root deals
    # are inside the exposure's fit set, and the policy eval keeps only deals the trunk never fit.
    rows_id, eval_id = block["rows"], block["eval"]
    assert rows_id["rows_excluded"] > 0 and rows_id["deals_excluded"] >= 2
    assert rows_id["rows_used"] + rows_id["rows_excluded"] == rows_id["rows_read"]
    # the ancestor (base) fit the train deal and selected on the val deal: the eval keeps the test deal only
    assert eval_id["rows_excluded"] > 0 and eval_id["deals"] == 1 and eval_id["ancestral_exposed_deals"] == 2
    assert block["root_fit_deals"] == 1 and block["root_only_fit_deals"] == 0
    fit = exposure_sets(joint["exposure"])["fit"]
    assert set(joint["population"]["train"]) <= fit and len(fit) == 1
    tr = joint["epochs"][0]["train"]
    assert tr["policy_rows"] > 0 and tr["policy_bce"] > 0 and tr["policy_listwise"] >= 0
    val = joint["epochs"][0]["val"]["policy"]
    assert val["top64"] and all(0.0 <= v <= 1.0 for v in val["top64"].values()) and val["deals"]
    assert "policy_head" in joint["consumer"]["heads"]
    # the checkpoint carries the head and the consumer's loader rebuilds it
    model, meta, _ = consumer_load(tmp_path / "joint" / "best.pt")
    assert model.config.policy_head and "policy_head.weight" in model.state_dict()
    assert meta["policy_head"]["rows"]["npz_sha256"] == block["rows"]["npz_sha256"]
    lo = model.policy_logits(model.features_flat(torch.zeros(1, 833)))
    assert lo.shape == (1, 54) and torch.isfinite(lo).all()
    # a headless run cannot warm-start from a policy-head net (layout differs)
    with pytest.raises(train_cwv.TrainError):
        train_cwv.train(out=tmp_path / "back", init=str(tmp_path / "joint" / "best.pt"),
                        init_exclude_exposed=True, **kw)

    # the matched twin: same batches and steps, weight 0 -> the head never moves
    twin = train_cwv.train(out=tmp_path / "twin", policy_head=True, policy_rows=policy_rows,
                           policy_eval=policy_rows, policy_weight=0.0, policy_batch_fraction=0.5,
                           init=str(tmp_path / "base" / "best.pt"), init_exclude_exposed=True, **kw)
    assert twin["policy_head"]["twin"] is True
    assert twin["epochs"][0]["train"]["policy_rows"] == tr["policy_rows"]
    assert twin["epochs"][0]["train"]["rows"] == tr["rows"] and twin["epochs"][0]["train"]["batches"] == tr["batches"]
    tw, _, _ = consumer_load(tmp_path / "twin" / "best.pt")
    # weight 0: the trunk received no policy gradient, so the two nets diverge only through it
    assert not torch.allclose(tw.state_dict()["head.weight"], model.state_dict()["head.weight"])
    assert twin["epochs"][0]["train"]["policy_bce"] is not None      # forwarded and measured, not trained


def test_root_rows_refuse_metadata_without_deal_keys(tmp_path):
    rng = np.random.default_rng(0)
    np.savez_compressed(tmp_path / "r.npz", X=rng.standard_normal((3, pp.INPUT_DIM)).astype(np.float32),
                        Y=np.zeros((3, 54), np.float32))
    with open(tmp_path / "r.meta.jsonl", "w") as fh:
        for _ in range(3):
            fh.write(json.dumps({"n_legal": 2, "legal": [[0], [1]], "ballot": [[0]], "taken": [0],
                                 "complete": True, "deal": "a" * 16}) + "\n")
    with pytest.raises(ValueError, match="deal_key"):
        PolicyRows(tmp_path / "r")
    with open(tmp_path / "r.meta.jsonl", "w") as fh:
        for _ in range(3):
            fh.write(json.dumps({"n_legal": 2, "legal": [[0], [1]], "ballot": [[0]], "taken": [0],
                                 "complete": True, "deal": "a" * 16, "deal_key": "deck:" + "a" * 64}) + "\n")
    rows = PolicyRows(tmp_path / "r", exclude={"deck:" + "b" * 64})
    assert rows.n == 3 and rows.identity["rows_excluded"] == 0 and rows.deal_keys == {"deck:" + "a" * 64}
    with pytest.raises(ValueError, match="excluded"):
        PolicyRows(tmp_path / "r", exclude={"deck:" + "a" * 64})


def test_disjoint_root_store_joins_the_exposure_and_a_later_warm_start_sees_it(
        store_dir, other_dir, tmp_path):  # noqa: F811
    """Root rows from a DIFFERENT store: nothing is dropped, their deals are fit exposure beyond
    the value population, and a headless run on that store warm-starting from the joint
    checkpoint is refused because its val/test deals were root-fit."""
    out = tmp_path / "rows"
    pp.extract(out, [str(other_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    kw = dict(arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50, encoder_version=2, **THIRDS)
    joint = train_cwv.train(out=tmp_path / "joint", data=[str(store_dir)], policy_head=True,
                            policy_rows=str(out), policy_batch_fraction=0.5, **kw)
    block = joint["policy_head"]
    assert block["rows"]["rows_excluded"] == 0 and block["root_only_fit_deals"] == block["root_fit_deals"] >= 1
    fit = exposure_sets(joint["exposure"])["fit"]
    assert len(fit) == len(joint["population"]["train"]) + block["root_fit_deals"]
    # A later run whose val/test contains the root-fit deal (a seed under which the combined
    # stores put it there) is refused by the ancestral exposure check.
    from shengji.train.data import split_deals
    root_deal = next(iter(fit - set(joint["population"]["train"])))
    all_keys = sorted(fit | set(joint["population"]["val"]) | set(joint["population"]["test"]))
    seed = next(s for s in range(1, 400)
                if split_deals(all_keys, seed=s, **THIRDS).get(root_deal) in ("val", "test"))
    with pytest.raises(train_cwv.TrainError, match="fit on land in this run's val|fit-or-selected"):
        train_cwv.train(out=tmp_path / "later", data=[str(store_dir), str(other_dir)],
                        init=str(tmp_path / "joint" / "best.pt"), **{**kw, "seed": seed})


def test_policy_eval_excludes_ancestral_fit_and_selection_deals(store_dir, other_dir, tmp_path):  # noqa: F811
    """Codex HOLD 2 on #428: a deal the --init source (or an ancestor) fit or selected on, but
    absent from the current value training, must not survive into the policy eval.  Ancestor:
    a headless net on store_dir whose recorded exposure carries one extra fit deal (other_dir's,
    never in store_dir); current run: value rows from store_dir, policy eval rows from other_dir."""
    from shengji.train.train_cwv import exposure_block, exposure_sets as sets_of, load_cwv_checkpoint, save_cwv_checkpoint
    rows = tmp_path / "rows"
    pp.extract(rows, [str(other_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    train_rows = tmp_path / "train_rows"
    pp.extract(train_rows, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    eval_deals = PolicyRows(rows).deal_keys
    kw = dict(arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50, encoder_version=2, **THIRDS)
    base = train_cwv.train(out=tmp_path / "base", data=[str(store_dir)], **kw)
    assert not eval_deals & set(base["population"]["train"])                # absent from the value training
    model, meta, _ = load_cwv_checkpoint(tmp_path / "base" / "best.pt")
    exp = sets_of(meta["exposure"])
    meta = {**meta, "exposure": exposure_block(exp["fit"] | eval_deals, exp["selection"],
                                                 ancestors=meta["exposure"].get("ancestors", []))}
    save_cwv_checkpoint(tmp_path / "anc.pt", model, metadata=meta)
    # without the warm start the eval is held out from this run's value fit and is accepted
    ok = train_cwv.train(out=tmp_path / "noinit", data=[str(store_dir)], policy_head=True,
                         policy_rows=str(train_rows), policy_eval=str(rows), policy_batch_fraction=0.5, **kw)
    assert ok["policy_head"]["eval"]["rows"] > 0 and ok["policy_head"]["eval"]["ancestral_exposed_deals"] == 0
    # with the ancestor as --init the eval deal is ancestrally FIT -> refused, never reported as held out
    with pytest.raises(ValueError, match="policy eval: every row is in an excluded deal"):
        train_cwv.train(out=tmp_path / "init", data=[str(store_dir)], policy_head=True,
                        policy_rows=str(train_rows), policy_eval=str(rows), policy_batch_fraction=0.5,
                        init=str(tmp_path / "anc.pt"), **kw)


def test_policy_detach_trains_the_head_without_moving_the_trunk(store_dir, tmp_path):  # noqa: F811
    """#425 after J1: with --policy-detach the policy loss reaches the head only.  Witness on the
    loss function: gradients of the policy terms on the trunk are None/zero under detach and
    non-zero without it; and a trainer run records the flag in the receipt."""
    from shengji.train.policy_rows import policy_losses
    cfg = ValueModelConfig(architecture="mlp", width=16, history_layers=1, attention_heads=1,
                           feedforward_width=32, public_dim=561, enc_version=2, policy_head=True)
    net = ValueNetwork(cfg); torch.manual_seed(1)
    t = {"x": torch.randn(4, 833), "y": (torch.rand(4, 54) > 0.9).float(),
         "ball": torch.full((4, 2, 3), -1, dtype=torch.int8), "mask": torch.zeros(4, 2, dtype=torch.bool),
         "tgt": torch.full((4,), -1, dtype=torch.long)}
    for detach in (False, True):
        net.zero_grad(set_to_none=True)
        bce, lw, _ = policy_losses(net, t, listwise_weight=1.0, detach=detach)
        (bce + lw).backward()
        trunk_grads = [p.grad for n, p in net.named_parameters() if n.startswith("trunk")]
        head_grads = [p.grad for n, p in net.named_parameters() if n.startswith("policy_head")]
        assert all(g is not None and g.abs().sum() > 0 for g in head_grads)
        if detach:
            assert all(g is None for g in trunk_grads)
        else:
            assert any(g is not None and g.abs().sum() > 0 for g in trunk_grads)
    rows = tmp_path / "rows"
    pp.extract(rows, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=200, workers=1)
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32,
              log=None, cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50, encoder_version=2, **THIRDS)
    r = train_cwv.train(out=tmp_path / "det", policy_head=True, policy_rows=str(rows), policy_detach=True, **kw)
    assert r["policy_head"]["detach"] is True and r["config"]["policy_detach"] is True
    with pytest.raises(train_cwv.TrainError, match="need --policy-head"):
        train_cwv.train(out=tmp_path / "bad", policy_detach=True, **kw)


def test_chunked_root_rows_stream_every_row_and_train_the_head(store_dir, tmp_path):  # noqa: F811
    """#425 root-row cache: a chunked extraction (small chunks) carries the same rows as the single
    file; the stream yields every kept row once per pass, drops excluded deals, honours a per-pass
    limit, and the trainer trains from the directory with the format recorded."""
    from shengji.train.policy_rows import PolicyRows, PolicyRowsStream, open_policy_rows
    flat = tmp_path / "flat"; chunked = tmp_path / "chunked"
    pp.extract(flat, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    summary = pp.extract(chunked, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1, chunk_rows=64)
    man = json.load(open(chunked / "manifest.json"))
    single = PolicyRows(flat)
    assert summary["chunks"] == man["chunks"].__len__() >= 2 and man["rows"] == single.n
    assert sum(c["rows"] for c in man["chunks"]) == man["rows"]
    with pytest.raises(pp.PolicyPriorError, match="already present"):
        pp.extract(chunked, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=10, workers=1, chunk_rows=64)
    stream = open_policy_rows(chunked)
    assert isinstance(stream, PolicyRowsStream) and stream.n == single.n and stream.deal_keys == single.deal_keys
    assert stream.identity["format"] == pp.CHUNK_SCHEMA and stream.identity["rows_excluded"] == 0
    rng = np.random.default_rng(3)
    seen = 0; keys = set()
    for b in stream.batches(32, rng):
        seen += len(b["x"]); keys.update(map(tuple, np.asarray(b["y"]).tolist()))
        t = stream.tensors(b, "cpu")
        assert t["x"].shape[1] == pp.INPUT_DIM and t["ball"].dtype == torch.int8 and t["tgt"].dtype == torch.long
        assert t["mask"].shape[1] == t["ball"].shape[1] and t["ball"].shape[0] == len(b["x"])
    assert seen == single.n                                                   # one pass = every row once
    # the multiset of X rows is identical between the two formats (float16 both sides)
    a = np.sort(single.X.view(np.uint16).sum(axis=1)); bb = np.sort(np.concatenate(
        [np.load(chunked / c["file"])["X"].view(np.uint16).sum(axis=1) for c in man["chunks"]]))
    assert np.array_equal(a, bb)
    # exclusion and the per-pass limit
    one = next(iter(single.deal_keys))
    fewer = PolicyRowsStream(chunked, exclude={one})
    assert fewer.n < single.n and one not in fewer.deal_keys
    assert fewer.identity["deals_excluded"] == 1 and fewer.identity["rows_excluded"] == single.n - fewer.n
    capped = PolicyRowsStream(chunked, limit=50)
    assert sum(len(b["x"]) for b in capped.batches(32, np.random.default_rng(1))) == 50
    with pytest.raises(ValueError, match="excluded"):
        PolicyRowsStream(chunked, exclude=set(single.deal_keys))
    # the trainer reads the directory
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10, hidden=32,
              log=None, cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50, encoder_version=2, **THIRDS)
    r = train_cwv.train(out=tmp_path / "run", policy_head=True, policy_rows=str(chunked), policy_batch_fraction=0.5, **kw)
    assert r["policy_head"]["rows"]["format"] == pp.CHUNK_SCHEMA and r["epochs"][0]["train"]["policy_rows"] > 0
    assert r["policy_head"]["rows"]["rows_excluded"] > 0                       # val/test deals dropped per chunk
