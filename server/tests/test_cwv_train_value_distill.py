"""train_cwv value anchoring: --value-teacher / --value-distill-weight add
W x KL(teacher || student) on the value heads outside --value-weight, and
--freeze-trunk trains only the policy tower and policy head."""
from __future__ import annotations

import math

import pytest
import torch

from shengji.ai.cwv_policy import load_cwv_checkpoint as consumer_load
from shengji.train import policy_prior as pp
from shengji.train import train_cwv
from shengji.train.cwv_data import cwv_encoder_identity
from shengji.train.train_cwv import (exposure_sets, file_sha256, load_cwv_checkpoint,
                                     save_cwv_checkpoint)
from tests.test_cwv_train import THIRDS, store_dir  # noqa: F401

KW = dict(arch="mlp", device="cpu", epochs=1, seed=7, n_boot=10, hidden=32, dropout=0.0,
          log=None, cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50,
          encoder_version=2, aux_points=True, **THIRDS)


@pytest.fixture(scope="module")
def base(store_dir, tmp_path_factory):  # noqa: F811
    """A headless value net (the --init source and default teacher) and root rows."""
    root = tmp_path_factory.mktemp("distill")
    train_cwv.train(out=root / "base", data=[str(store_dir)], batch_size=64, **KW)
    rows = root / "rows"
    pp.extract(rows, [str(store_dir)], lo=0.0, hi=1.01, thin=1.0, max_rows=400, workers=1)
    ckpt = root / "base" / "best.pt"
    return {"ckpt": str(ckpt), "sha": file_sha256(ckpt), "rows": str(rows),
            "data": [str(store_dir)]}


def _inputs(net, n=128, seed=0):
    g = torch.Generator().manual_seed(seed)
    return (torch.randn(n, net.config.public_dim, generator=g),
            torch.randn(n, 5, 54, generator=g), torch.randn(n, 2, generator=g))


def _kl(teacher, student, inputs):
    with torch.no_grad():
        t = torch.log_softmax(teacher.head_logits(teacher.features(*inputs), "outcome"), 1)
        s = torch.log_softmax(student.head_logits(student.features(*inputs), "outcome"), 1)
    return float(torch.nn.functional.kl_div(s, t, reduction="batchmean", log_target=True))


def test_distill_weight_zero_and_absent_train_the_default_net(base, tmp_path):
    absent = train_cwv.train(out=tmp_path / "absent", data=base["data"], batch_size=64, **KW)
    zero = train_cwv.train(out=tmp_path / "zero", data=base["data"], batch_size=64,
                           value_distill_weight=0.0, freeze_trunk=False, **KW)
    assert "value_distill" not in absent["config"] and "freeze_trunk" not in absent["config"]
    assert zero["config_sha256"] == absent["config_sha256"]
    assert "value_distill_kl" not in absent["epochs"][0]["train"]
    a_sd = consumer_load(tmp_path / "absent" / "checkpoints" / "epoch-01.pt")[0].state_dict()
    z_sd = consumer_load(tmp_path / "zero" / "checkpoints" / "epoch-01.pt")[0].state_dict()
    assert all(torch.equal(a_sd[k], z_sd[k]) for k in a_sd)
    assert absent["epochs"][0]["train"]["loss"] == zero["epochs"][0]["train"]["loss"]
    # the base fixture is the same run: the default path is deterministic end to end
    b_sd = consumer_load(base["ckpt"])[0].state_dict()
    assert all(torch.equal(a_sd[k], b_sd[k]) for k in a_sd)


def test_teacher_equal_to_init_gives_zero_kl_at_step_zero_and_is_recorded(base, tmp_path):
    """One batch (the KL is measured on the forward before the only step): a teacher that
    IS the init has KL 0, and the logged loss is value_weight x value block + W x KL + policy."""
    one = dict(data=base["data"], batch_size=100_000, policy_head=True, policy_rows=base["rows"],
               policy_batch_fraction=0.002, init=base["ckpt"], init_exclude_exposed=True, **KW)
    r = train_cwv.train(out=tmp_path / "one", value_weight=0.1, value_teacher=base["ckpt"],
                        value_teacher_sha256=base["sha"], value_distill_weight=1.0, **one)
    tr = r["epochs"][0]["train"]
    assert tr["batches"] == 1 and tr["value_distill_kl"] == pytest.approx(0.0, abs=1e-7)
    value = tr["cross_entropy"] + train_cwv.DEFAULTS["aux_weight"] * tr["aux_huber"]
    policy = tr["policy_bce"] + tr["policy_listwise"]
    assert tr["loss"] == pytest.approx(0.1 * value + policy, rel=1e-5)
    vd = r["config"]["value_distill"]
    assert vd["teacher_sha256"] == base["sha"] and vd["weight"] == 1.0
    assert vd["heads"] == ["outcome"] and r["config"]["value_weight"] == 0.1
    meta = load_cwv_checkpoint(tmp_path / "one" / "checkpoints" / "epoch-01.pt")[1]
    assert meta["config"]["value_distill"] == vd
    teacher_rows = [a for a in r["exposure"]["ancestors"] if a.get("role") == "value-teacher"]
    assert len(teacher_rows) == 1 and teacher_rows[0]["sha256"] == base["sha"]
    assert exposure_sets(meta["exposure"])["fit"] >= set(r["population"]["train"])


def test_distillation_pulls_a_perturbed_student_toward_the_teacher(base, tmp_path):
    """Pure distillation (--value-weight 0, no policy head): the student starts from a
    perturbed copy of the teacher and every epoch moves it closer."""
    net, meta, _ = load_cwv_checkpoint(base["ckpt"])
    torch.manual_seed(3)
    with torch.no_grad():
        for p in net.parameters():
            p.add_(0.3 * torch.randn_like(p))
    save_cwv_checkpoint(tmp_path / "perturbed.pt", net, metadata=meta)
    teacher = load_cwv_checkpoint(base["ckpt"])[0]
    r = train_cwv.train(out=tmp_path / "pull", data=base["data"], batch_size=16,
                        init=str(tmp_path / "perturbed.pt"), init_exclude_exposed=True,
                        value_weight=0.0, value_teacher=base["ckpt"],
                        value_teacher_sha256=base["sha"], value_distill_weight=1.0,
                        **{**KW, "epochs": 3, "lr": 3e-3, "patience": 5})
    kls = [e["train"]["value_distill_kl"] for e in r["epochs"]]
    assert kls[0] > 0 and kls[-1] < kls[0]
    inputs = _inputs(teacher)
    before = _kl(teacher, net, inputs)
    after = _kl(teacher, load_cwv_checkpoint(tmp_path / "pull" / "checkpoints" / "epoch-03.pt")[0],
                inputs)
    assert before > 0 and after < before


def test_teacher_refusals(base, tmp_path):
    kw = dict(data=base["data"], batch_size=64, **KW)
    good = dict(value_teacher=base["ckpt"], value_teacher_sha256=base["sha"],
                value_distill_weight=1.0)
    cases = [
        (dict(value_distill_weight=1.0), "needs --value-teacher"),
        (dict(value_teacher=base["ckpt"], value_teacher_sha256=base["sha"]),
         "needs --value-distill-weight > 0"),
        (dict(value_teacher_sha256=base["sha"]), "needs --value-teacher"),
        ({**good, "value_teacher_sha256": None}, "needs --value-teacher-sha256"),
        ({**good, "value_distill_weight": -1.0}, "finite weight >= 0"),
        ({**good, "value_distill_weight": float("nan")}, "finite weight >= 0"),
        ({**good, "value_teacher": str(tmp_path / "missing.pt")}, "no such checkpoint"),
        ({**good, "value_teacher_sha256": "0" * 64}, "SHA256 .* differs"),
        ({**good, "arch": "seq", "aux_points": False}, "mlp outcome head"),
    ]
    for extra, match in cases:
        with pytest.raises(train_cwv.TrainError, match=match):
            train_cwv.train(out=tmp_path / "bad", **{**kw, **extra})
    # a teacher at another encoder version reads different inputs: refused
    cfg = train_cwv.model_config("mlp", hidden=32, dropout=0.0, encoder_version=1)
    meta = load_cwv_checkpoint(base["ckpt"])[1]
    v1 = tmp_path / "v1.pt"
    save_cwv_checkpoint(v1, train_cwv.ValueNetwork(cfg),
                        metadata={**meta, "encoder": cwv_encoder_identity(1)})
    with pytest.raises(train_cwv.TrainError, match="encoder v1"):
        train_cwv.train(out=tmp_path / "bad", **{**kw, **good, "value_teacher": str(v1),
                                                 "value_teacher_sha256": file_sha256(v1)})


def test_freeze_trunk_trains_only_the_policy_tower_and_head(base, tmp_path):
    """T: the trunk, the outcome head and the aux head are bit-equal to --init after
    training, so the value outputs are the init's; the tower and policy head moved."""
    pk = dict(data=base["data"], batch_size=64, policy_head=True, policy_rows=base["rows"],
              policy_batch_fraction=0.5, init=base["ckpt"], init_exclude_exposed=True,
              policy_tower_layers=1, **KW)
    r = train_cwv.train(out=tmp_path / "frozen", freeze_trunk=True, **pk)
    assert r["config"]["freeze_trunk"] is True
    init_net, init_meta, init_aux = load_cwv_checkpoint(base["ckpt"])
    out_net, out_meta, out_aux = load_cwv_checkpoint(tmp_path / "frozen" / "checkpoints" / "epoch-01.pt")
    i_sd, o_sd = init_net.state_dict(), out_net.state_dict()
    frozen = [k for k in o_sd if not k.startswith(train_cwv.FREEZE_TRUNK_TRAINABLE)]
    assert frozen and set(frozen) == set(i_sd)
    assert all(torch.equal(i_sd[k], o_sd[k]) for k in frozen)
    assert out_meta["aux_points_head"] == init_meta["aux_points_head"]
    # the tower's output projection starts at zero: non-zero means the tower trained
    assert o_sd["policy_tower.0.down.weight"].abs().sum() > 0
    inputs = _inputs(init_net)
    with torch.no_grad():
        f_i, f_o = init_net.features(*inputs), out_net.features(*inputs)
        assert torch.equal(init_net.head_logits(f_i), out_net.head_logits(f_o))
        assert torch.equal(init_aux(f_i), out_aux(f_o))
    tr = r["epochs"][0]["train"]
    assert tr["policy_bce"] > 0 and math.isfinite(tr["cross_entropy"])
    # refusals
    for extra, match in ((dict(policy_head=False, policy_rows=None, policy_tower_layers=0),
                          "needs --policy-head"),
                         (dict(init=None, init_exclude_exposed=False), "needs --init"),
                         (dict(policy_detach=True), "drop --policy-detach"),
                         (dict(policy_trunk_grad_scale=0.5), "drop --policy-detach"),
                         (dict(policy_weight=0.0), "trains nothing"),
                         (dict(value_teacher=base["ckpt"], value_teacher_sha256=base["sha"],
                               value_distill_weight=1.0), "nothing to move")):
        with pytest.raises(train_cwv.TrainError, match=match):
            train_cwv.train(out=tmp_path / "bad", freeze_trunk=True, **{**pk, **extra})


def test_search_mean_head_is_distilled_only_when_both_nets_carry_one(base, tmp_path):
    meta = load_cwv_checkpoint(base["ckpt"])[1]
    plain = train_cwv.model_config("mlp", hidden=32, dropout=0.0, encoder_version=2)
    two = train_cwv.model_config("mlp", hidden=32, dropout=0.0, encoder_version=2,
                                 search_head=True)
    paths = {}
    for name, cfg in (("plain", plain), ("two", two)):
        paths[name] = tmp_path / f"{name}.pt"
        save_cwv_checkpoint(paths[name], train_cwv.ValueNetwork(cfg),
                            metadata={**meta, "model_config": cfg.payload()})
    load = lambda name, student: train_cwv._load_value_teacher(  # noqa: E731
        str(paths[name]), file_sha256(paths[name]), torch.device("cpu"), enc_version=2,
        student=student)[3]
    assert load("two", two) == ("outcome", "search-mean")
    assert load("plain", two) == ("outcome",)
    assert load("two", plain) == ("outcome",)
    teacher = train_cwv._load_value_teacher(str(paths["two"]), file_sha256(paths["two"]),
                                            torch.device("cpu"), enc_version=2, student=two)[0]
    assert not teacher.training and not any(p.requires_grad for p in teacher.parameters())


def test_kl_is_teacher_cross_entropy_minus_teacher_entropy():
    g = torch.Generator().manual_seed(5)
    s, t = torch.randn(9, 204, generator=g), torch.randn(9, 204, generator=g)
    t_logp = torch.log_softmax(t, 1)
    p = t_logp.exp()
    ce = -(p * torch.log_softmax(s, 1)).sum(1).mean()
    h = -(p * t_logp).sum(1).mean()
    assert float(train_cwv.value_distill_kl(s, t_logp)) == pytest.approx(float(ce - h), abs=1e-5)
    assert float(train_cwv.value_distill_kl(t, t_logp)) == pytest.approx(0.0, abs=1e-6)


@pytest.fixture(scope="module")
def two_head(base, store_dir, tmp_path_factory):  # noqa: F811
    """A two-head (outcome + search-mean) value net, the U teacher/init shape."""
    import glob
    from shengji.train import search_mean_sidecar as sc
    root = tmp_path_factory.mktemp("twohead")
    side = root / "sidecar"
    built = [sc.build_sidecar(p, side, level_objective=False)
             for p in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True))]
    assert built and sum(c["with_mean"] for c in built) > 0
    train_cwv.train(out=root / "two", data=base["data"], batch_size=64, search_head=True,
                    search_mean_sidecar=str(side), **KW)
    ckpt = root / "two" / "best.pt"
    return {"ckpt": str(ckpt), "sha": file_sha256(ckpt), "side": str(side)}


def test_u_shape_is_accepted_and_distils_both_heads_outside_the_value_weight(
        base, two_head, tmp_path):
    """The U arm: --value-weight 0.1 --value-distill-weight 1.0 --search-head-weight 0.001
    with a two-head teacher equal to the init.  One batch: KL 0 on both heads, and the logged
    loss is 0.1 x (CE + aux + 0.001 x search CE) + 1.0 x KL + policy (KL unscaled by 0.1)."""
    r = train_cwv.train(
        out=tmp_path / "u", data=base["data"], batch_size=100_000, policy_head=True,
        policy_rows=base["rows"], policy_batch_fraction=0.002, init=two_head["ckpt"],
        init_exclude_exposed=True, search_head=True, search_mean_sidecar=two_head["side"],
        search_head_weight=0.001, value_weight=0.1, value_teacher=two_head["ckpt"],
        value_teacher_sha256=two_head["sha"], value_distill_weight=1.0, **KW)
    assert r["config"]["value_distill"]["heads"] == ["outcome", "search-mean"]
    assert r["config"]["search_head_weight"] == 0.001
    tr = r["epochs"][0]["train"]
    assert tr["batches"] == 1 and tr["value_distill_kl"] == pytest.approx(0.0, abs=1e-6)
    value = (tr["cross_entropy"] + train_cwv.DEFAULTS["aux_weight"] * tr["aux_huber"]
             + 0.001 * tr["search_head_cross_entropy"])
    policy = tr["policy_bce"] + tr["policy_listwise"]
    assert tr["loss"] == pytest.approx(0.1 * value + tr["value_distill_kl"] + policy, rel=1e-5)
    # a perturbed init: the KL is non-zero and enters the loss at weight 1.0, not 0.1
    net, meta, _ = load_cwv_checkpoint(two_head["ckpt"])
    torch.manual_seed(4)
    with torch.no_grad():
        for p in net.parameters():
            p.add_(0.2 * torch.randn_like(p))
    save_cwv_checkpoint(tmp_path / "perturbed.pt", net, metadata=meta)
    r2 = train_cwv.train(
        out=tmp_path / "u2", data=base["data"], batch_size=100_000, policy_head=True,
        policy_rows=base["rows"], policy_batch_fraction=0.002, init=str(tmp_path / "perturbed.pt"),
        init_exclude_exposed=True, search_head=True, search_mean_sidecar=two_head["side"],
        search_head_weight=0.001, value_weight=0.1, value_teacher=two_head["ckpt"],
        value_teacher_sha256=two_head["sha"], value_distill_weight=1.0, **KW)
    tr2 = r2["epochs"][0]["train"]
    value2 = (tr2["cross_entropy"] + train_cwv.DEFAULTS["aux_weight"] * tr2["aux_huber"]
              + 0.001 * tr2["search_head_cross_entropy"])
    assert tr2["value_distill_kl"] > 1e-3
    assert tr2["loss"] == pytest.approx(
        0.1 * value2 + tr2["value_distill_kl"] + tr2["policy_bce"] + tr2["policy_listwise"],
        rel=1e-5)


def test_freeze_trunk_epoch_check_refuses_a_moved_parameter(base, tmp_path, monkeypatch):
    """The per-epoch witness compares every frozen parameter with its value at step 0; a
    parameter that moved refuses the run (here the policy head, listed as frozen)."""
    real = train_cwv._frozen_named

    def with_policy_head(model, aux_head):
        yield from real(model, aux_head)
        yield from ((n, p) for n, p in model.named_parameters() if n.startswith("policy_head."))
    monkeypatch.setattr(train_cwv, "_frozen_named", with_policy_head)
    with pytest.raises(train_cwv.TrainError, match="moved frozen parameter.*policy_head"):
        train_cwv.train(out=tmp_path / "moved", data=base["data"], batch_size=64,
                        policy_head=True, policy_rows=base["rows"], policy_batch_fraction=0.5,
                        init=base["ckpt"], init_exclude_exposed=True, freeze_trunk=True, **KW)
