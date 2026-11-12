"""Legal-set-aware listwise loss (``policy_prior.listwise_loss_legal``) and the
off-ballot negatives that feed it (``served_policy_rows --legal-negatives``,
``train_cwv --policy-legal-negatives``).

The ballot-only listwise loss sees only the search's admitted candidates, so it
says nothing about the rest of the legal set the served prior ranks.  These tests
pin that the legal-set loss: equals the ballot-only loss on a row with no
negative; puts off-ballot actions in the normaliser with zero target mass, with
the sampled-softmax correction; pushes an off-ballot action below the ballot on a
toy legal set where the ballot-only loss leaves it on top; and that the producer,
stream and trainer carry the negatives end to end while the default output stays
byte-identical."""
from __future__ import annotations

import json
import math
import random

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.harvest.common import action_key  # noqa: E402
from shengji.harvest.legal import enumerate_legal  # noqa: E402
from shengji.harvest.rebuild import state_for_record  # noqa: E402
from shengji.train import policy_prior as pp  # noqa: E402
from shengji.train import served_policy_rows as spr  # noqa: E402
from shengji.train.policy_rows import PolicyRowsStream, policy_losses  # noqa: E402
from test_cwv_train import THIRDS, store_dir  # noqa: E402,F401
from test_policy_rows_served import _records, pv_package, pv_store, served_store  # noqa: E402,F401


def _ball(cands, width=None):
    """(ball [1, B, C], mask [1, B]) of one row's candidates (card-index lists)."""
    b = len(cands) if width is None else width
    c = max(len(a) for a in cands)
    ball = torch.full((1, b, c), -1, dtype=torch.int8)
    mask = torch.zeros((1, b), dtype=torch.bool)
    for j, a in enumerate(cands):
        ball[0, j, :len(a)] = torch.tensor(a, dtype=torch.int8)
        mask[0, j] = True
    return ball, mask


def _negs(cands, logw=0.0):
    if not cands:
        return (torch.full((1, 0, 1), -1, dtype=torch.int8), torch.zeros((1, 0), dtype=torch.bool),
                torch.tensor([logw]))
    n, m = _ball(cands)
    return n, m, torch.tensor([logw], dtype=torch.float32)


# sample_legal_negatives

def test_negatives_are_the_legal_actions_off_the_ballot_as_multisets():
    legal = [[1], [2], [3, 4], [4, 3], [5, 5], [6]]
    ballot = [[2], [4, 3], []]
    kept, n_off, logw = pp.sample_legal_negatives(legal, ballot, 10, random.Random(0))
    assert sorted(map(tuple, kept)) == [(1,), (5, 5), (6,)] and n_off == 3 and logw == 0.0


def test_negatives_are_capped_uniformly_with_the_sampled_softmax_correction():
    legal = [[i] for i in range(50)]
    kept, n_off, logw = pp.sample_legal_negatives(legal, [[0], [1]], 8, random.Random(5))
    again, _, _ = pp.sample_legal_negatives(legal, [[0], [1]], 8, random.Random(5))
    assert len(kept) == 8 and n_off == 48 and kept == again
    assert not {0, 1} & {a[0] for a in kept}
    assert logw == pytest.approx(math.log(48 / 8))
    with pytest.raises(pp.PolicyPriorError):
        pp.sample_legal_negatives(legal, [], 0, random.Random(0))


def test_negative_tensors_pad_and_carry_the_correction():
    meta = [{"negs": [[1], [2, 3]], "neg_logw": 0.5}, {"negs": [], "neg_logw": 0.0}]
    negs, mask, logw = pp.negative_tensors(meta)
    assert negs.shape == (2, 2, 2) and negs.dtype == np.int8
    assert mask.tolist() == [[True, True], [False, False]]
    assert negs[0, 1].tolist() == [2, 3] and negs[0, 0].tolist() == [1, -1]
    assert logw.tolist() == [0.5, 0.0]


# listwise_loss_legal on toy legal sets

def test_no_negatives_equals_the_ballot_only_losses():
    torch.manual_seed(0)
    logits = torch.randn(3, 54)
    cands = [[0], [1, 2], [3]]
    ball = torch.stack([_ball(cands)[0][0]] * 3); mask = torch.stack([_ball(cands)[1][0]] * 3)
    tgt = torch.tensor([0, 2, -1])
    vals = torch.tensor([[1.0, 0.5, float("nan")], [float("nan")] * 3, [0.0, 1.0, 2.0]])
    negs = torch.full((3, 0, 1), -1, dtype=torch.int8); nm = torch.zeros((3, 0), dtype=torch.bool)
    lw = torch.zeros(3)
    soft = pp.listwise_loss_legal(logits, ball, mask, tgt, vals, negs, nm, lw, temperature=0.7)
    assert torch.allclose(soft, pp.listwise_loss_soft(logits, ball, mask, tgt, vals, temperature=0.7), atol=1e-6)
    hard = pp.listwise_loss_legal(logits, ball, mask, tgt, None, negs, nm, lw)
    assert torch.allclose(hard, pp.listwise_loss(logits, ball, mask, tgt), atol=1e-6)
    # all-masked negative slots are the same as none
    negs2 = torch.zeros((3, 2, 1), dtype=torch.int8); nm2 = torch.zeros((3, 2), dtype=torch.bool)
    assert torch.allclose(pp.listwise_loss_legal(logits, ball, mask, tgt, vals, negs2, nm2, lw, temperature=0.7),
                          soft, atol=1e-6)


def test_the_loss_on_a_toy_legal_set_matches_the_formula():
    logits = torch.zeros(1, 54)
    logits[0, :6] = torch.tensor([1.0, 0.5, -0.2, 2.0, 0.3, -1.0])
    cands = [[0], [1, 2]]                      # ballot: scores 1.0 and 0.3
    off = [[3], [4], [5, 5]]                   # off-ballot legal: scores 2.0, 0.3, -2.0
    ball, mask = _ball(cands); negs, nm, lw = _negs(off)
    vals = torch.tensor([[1.0, 0.0]]); tgt = torch.tensor([0])
    got = pp.listwise_loss_legal(logits, ball, mask, tgt, vals, negs, nm, lw, temperature=1.0)
    p = torch.softmax(torch.tensor([1.0, 0.0]), 0)
    s = torch.tensor([1.0, 0.3]); z = torch.logsumexp(torch.tensor([1.0, 0.3, 2.0, 0.3, -2.0]), 0)
    assert torch.allclose(got, -(p * (s - z)).sum(), atol=1e-6)
    # K=1: a one-slot ballot is the played move against the whole legal set
    b1, m1 = _ball([[0]])
    one = pp.listwise_loss_legal(logits, b1, m1, tgt, None, negs, nm, lw)
    assert torch.allclose(one, -(1.0 - torch.logsumexp(torch.tensor([1.0, 2.0, 0.3, -2.0]), 0)), atol=1e-6)
    assert float(pp.listwise_loss(logits, b1, m1, tgt)) == pytest.approx(0.0, abs=1e-7)


def test_the_correction_lets_kept_negatives_stand_in_for_all():
    logits = torch.zeros(1, 54); logits[0, 0] = 1.0
    ball, mask = _ball([[0], [1]]); tgt = torch.tensor([0]); vals = torch.tensor([[1.0, 0.0]])
    full = pp.listwise_loss_legal(logits, ball, mask, tgt, vals, *_negs([[2], [3], [4], [5]]))
    half = pp.listwise_loss_legal(logits, ball, mask, tgt, vals, *_negs([[2], [3]], logw=math.log(2)))
    assert torch.allclose(full, half, atol=1e-6)        # equal-scoring negatives: exact


def test_negatives_get_a_downward_gradient_and_the_ballot_only_loss_gives_none():
    logits = torch.zeros(1, 54, requires_grad=True)
    ball, mask = _ball([[0], [1]]); tgt = torch.tensor([0]); vals = torch.tensor([[1.0, 0.0]])
    pp.listwise_loss_legal(logits, ball, mask, tgt, vals, *_negs([[7], [8, 8]])).backward()
    g = logits.grad[0]
    assert g[7] > 0 and g[8] > 0 and g[0] < 0                 # descent lowers 7 and 8, raises 0
    logits.grad = None
    pp.listwise_loss_soft(logits, ball, mask, tgt, vals).backward()
    assert float(logits.grad[0, 7]) == 0.0 and float(logits.grad[0, 8]) == 0.0


def test_training_on_a_toy_legal_set_ranks_the_off_ballot_action_below_the_ballot():
    """The defect and its fix in miniature: an off-ballot action that shares a card
    with a ballot candidate rises with it under the ballot-only loss and stays above
    the ballot's floor; the legal-set loss puts it below the floor."""
    def run(legal):
        torch.manual_seed(0)
        logits = torch.zeros(1, 54, requires_grad=True)
        with torch.no_grad():
            logits[0, 9] = 3.0                    # the off-ballot action starts on top
        opt = torch.optim.SGD([logits], lr=0.5)
        ball, mask = _ball([[0, 1], [2]]); tgt = torch.tensor([0]); vals = torch.tensor([[1.0, 0.0]])
        negs = _negs([[0, 9], [3]])               # {0, 9} shares card 0 with the top ballot move
        for _ in range(200):
            opt.zero_grad()
            loss = (pp.listwise_loss_legal(logits, ball, mask, tgt, vals, *negs) if legal
                    else pp.listwise_loss_soft(logits, ball, mask, tgt, vals))
            loss.backward(); opt.step()
        lo = logits.detach()[0].numpy()
        sc = pp.score_candidates(lo, [[0, 1], [2], [0, 9], [3]])
        return sc[2] - min(sc[0], sc[1])
    assert run(legal=False) > 0                   # ballot-only: still above the ballot's floor
    assert run(legal=True) < 0                    # legal-set: pushed below it


def test_policy_losses_dispatches_and_refuses_a_batch_without_negatives():
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    torch.manual_seed(1)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=16, history_layers=1, attention_heads=1,
                                        feedforward_width=32, public_dim=561, enc_version=2, policy_head=True))
    ball, mask = _ball([[0], [1]])
    t = {"x": torch.randn(1, pp.input_dim(2)), "y": torch.zeros(1, 54), "ball": ball, "mask": mask,
         "tgt": torch.tensor([0]), "vals": torch.tensor([[1.0, 0.0]])}
    with pytest.raises(ValueError, match="no off-ballot negatives"):
        policy_losses(net, t, listwise_weight=1.0, soft_targets=True, legal_negatives=True)
    _, base, _ = policy_losses(net, t, listwise_weight=1.0, soft_targets=True)
    negs, nm, lw = _negs([])
    _, same, _ = policy_losses(net, dict(t, negs=negs, neg_mask=nm, neg_logw=lw), listwise_weight=1.0,
                               soft_targets=True, legal_negatives=True)
    assert torch.allclose(base, same, atol=1e-6)
    negs, nm, lw = _negs([[5], [6]])
    _, more, _ = policy_losses(net, dict(t, negs=negs, neg_mask=nm, neg_logw=lw), listwise_weight=1.0,
                               soft_targets=True, legal_negatives=True)
    assert float(more.detach()) > float(base.detach())


# producer -> stream -> trainer

@pytest.fixture(scope="module")
def produced_negs(served_store, tmp_path_factory):  # noqa: F811
    d, recs, _marks = served_store
    out = tmp_path_factory.mktemp("lneg-out") / "rows"
    summary = spr.produce(out, [d], version=2, chunk_rows=64, legal_negatives=3)
    return out, summary, recs


def test_the_producer_writes_the_off_ballot_legal_actions(produced_negs, served_store, tmp_path):  # noqa: F811
    out, summary, recs = produced_negs
    man = json.loads((out / "manifest.json").read_text())
    assert man["legal_negatives"] == 3 and summary["legal_negatives"]["cap"] == 3
    kept = [r for r in recs if r["decision_kind"] == "play" and spr.classify(r)[0] is not None]
    assert summary["rows"] == len(kept) and summary["excluded"]["legal_enumeration_failed"] == 0
    parts = [dict(np.load(out / c["file"])) for c in man["chunks"]]
    negs = [row for p in parts for row in zip(p["negs"], p["neg_mask"], p["neg_logw"], p["ball"], p["mask"])]
    with_negs = 0
    for rec, (ng, nm, lw, ball, bm) in zip(kept, negs):
        root = state_for_record(rec)
        legal = enumerate_legal(root, int(rec["seat"]), cap=pp.MAX_LEGAL,
                                must_include=[rec["action"]] + [a for a in rec["ballot"] if a]).actions
        on = {tuple(sorted(pp.cards_to_idx(a))) for a in rec["ballot"] if a}
        off = {tuple(sorted(pp.cards_to_idx(a))) for a in legal} - on
        got = {tuple(sorted(int(c) for c in ng[j] if c >= 0)) for j in np.flatnonzero(nm)}
        assert got <= off and len(got) == min(3, len(off)) and not got & on
        assert lw == pytest.approx(math.log(len(off) / len(got)) if got else 0.0, rel=1e-6)
        with_negs += bool(got)
    assert with_negs == summary["legal_negatives"]["rows_with_negatives"] > 0
    # same inputs, same bytes; the default build carries no negatives at all
    again = spr.produce(tmp_path / "again", [served_store[0]], version=2, chunk_rows=64, legal_negatives=3)
    assert [c["sha256"] for c in json.loads((tmp_path / "again" / "manifest.json").read_text())["chunks"]] \
        == [c["sha256"] for c in man["chunks"]] and again["rows"] == summary["rows"]
    spr.produce(tmp_path / "plain", [served_store[0]], version=2, chunk_rows=64)
    plain = json.loads((tmp_path / "plain" / "manifest.json").read_text())
    assert "legal_negatives" not in plain
    assert all("negs" not in np.load(tmp_path / "plain" / c["file"]).files for c in plain["chunks"])
    with pytest.raises(spr.ServedPolicyRowsError):
        spr.produce(tmp_path / "part", [served_store[0]], version=2, legal_negatives=3, partition=(0, 2))


def test_the_stream_carries_negatives_and_trains_one_step(produced_negs):
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    out, summary, _recs = produced_negs
    stream = PolicyRowsStream(out, window=100, version=2)
    assert stream.identity["legal_negatives"] == 3
    batch = next(stream.batches(10 ** 6, np.random.default_rng(0)))
    t = stream.tensors(batch, "cpu")
    assert t["negs"].shape[:2] == t["neg_mask"].shape and t["neg_logw"].shape == (len(t["x"]),)
    assert int(t["neg_mask"].sum()) == summary["legal_negatives"]["negatives_kept"]
    torch.manual_seed(3)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=16, history_layers=1, attention_heads=1,
                                        feedforward_width=32, public_dim=561, enc_version=2, policy_head=True))
    _, ballot_only, _ = policy_losses(net, t, listwise_weight=1.0, soft_targets=True)
    _, legal, _ = policy_losses(net, t, listwise_weight=1.0, soft_targets=True, legal_negatives=True)
    assert torch.isfinite(legal) and float(legal.detach()) > float(ballot_only.detach())
    legal.backward()


def test_train_cwv_trains_with_legal_negatives_and_refuses_rows_without(  # noqa: F811
        produced_negs, served_store, store_dir, tmp_path):
    from shengji.train import train_cwv
    out, summary, _recs = produced_negs
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10,
              hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50,
              encoder_version=2, policy_head=True, policy_batch_fraction=0.5, policy_soft_targets=True,
              policy_soft_temperature=1.0, **THIRDS)
    r = train_cwv.train(out=tmp_path / "run", policy_rows=str(out), policy_legal_negatives=True, **kw)
    assert r["policy_head"]["rows"]["legal_negatives"] == 3
    tr = r["epochs"][0]["train"]
    assert tr["policy_rows"] > 0 and math.isfinite(tr["policy_listwise"]) and tr["policy_listwise"] > 0
    plain = tmp_path / "plain"
    spr.produce(plain, [served_store[0]], version=2, chunk_rows=64)
    with pytest.raises(train_cwv.TrainError, match="no off-ballot"):
        train_cwv.train(out=tmp_path / "run2", policy_rows=str(plain), policy_legal_negatives=True, **kw)
