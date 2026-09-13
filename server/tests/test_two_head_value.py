"""#373: a second 204-class head on the mlp trunk trained on the search-mean
soft target, selectable per consumer.  Every model trained before the option
existed must keep its payload and bytes; the new head must train only on rows
with a sidecar mean, be reported (never selected on), reach the evaluator and
the screen ARM by name, refuse when absent, and export as one package head."""
import copy
import glob
import json

import numpy as np
import pytest
import torch

from shengji.ai import cwv_policy
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.value_afterstate import OUTCOME_CLASSES, PERSPECTIVE_DIM, WORLD_RECEIVERS
from shengji.rl.value_checkpoint import load_checkpoint, save_checkpoint
from shengji.rl.value_model import (ValueModelConfig, ValueModelError, ValueNetwork,
                                    _LEGACY_HEAD, model_state_sha256, mlp_input_dim)
from shengji.train import cwv_shortlist_screen as S
from shengji.train import search_mean_sidecar as sc
from shengji.train import train_cwv
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401
from tests.test_cwv_train import THIRDS, train_v0


def _cfg(hidden=64, **kw):
    return train_cwv.model_config("mlp", hidden=hidden, encoder_version=2, **kw)


def _inputs(cfg, n=5, seed=0):
    g = torch.Generator().manual_seed(seed)
    public = torch.rand((n, cfg.public_dim), generator=g)
    world = torch.rand((n, WORLD_RECEIVERS, N_CARDS), generator=g)
    perspective = torch.zeros((n, PERSPECTIVE_DIM)); perspective[:, 0] = 1.0
    history = torch.zeros((n, 1, HISTORY_EVENT_DIM)); mask = torch.ones((n, 1), dtype=torch.bool)
    return public, history, mask, world, perspective


def test_legacy_payload_carries_no_head_fields_and_still_loads():
    cfg = _cfg()
    assert (cfg.search_head, cfg.value_head) == (False, "outcome") == tuple(_LEGACY_HEAD.values())
    payload = cfg.payload()
    assert "search_head" not in payload and "value_head" not in payload
    assert ValueModelConfig.from_payload(payload) == cfg
    legacy = {k: v for k, v in payload.items() if k not in ("public_dim", "enc_version")}
    assert ValueModelConfig.from_payload(legacy).search_head is False
    # a single-head net has no search_head parameters: bytes and state hash unchanged
    assert not any(k.startswith("search_head") for k in ValueNetwork(cfg).state_dict())


def test_two_head_config_round_trips_and_refuses_nonsense():
    cfg = _cfg(search_head=True)
    payload = cfg.payload()
    assert payload["search_head"] is True and payload["value_head"] == "outcome"
    assert ValueModelConfig.from_payload(payload) == cfg
    served = ValueModelConfig.from_payload({**payload, "value_head": "search-mean"})
    assert served.value_head == "search-mean"
    with pytest.raises(ValueModelError, match="search-mean head this net does not have"):
        ValueModelConfig.from_payload({**_cfg().payload(), "search_head": False,
                                       "value_head": "search-mean"})
    with pytest.raises(ValueModelError):
        ValueModelConfig.from_payload({**payload, "value_head": "aux"})
    with pytest.raises(ValueModelError, match="schema drift"):
        ValueModelConfig.from_payload({**payload, "search_head_weight": 1.0})
    with pytest.raises(train_cwv.TrainError, match="mlp trunk"):
        train_cwv.model_config("seq", encoder_version=2, search_head=True)
    with pytest.raises(ValueModelError, match="mlp trunk"):
        ValueModelConfig(architecture="transformer", search_head=True).validate()


def test_forward_selects_the_named_head_and_refuses_a_missing_one():
    torch.manual_seed(1)
    cfg = _cfg(search_head=True)
    net = ValueNetwork(cfg).eval()
    x = _inputs(cfg)
    with torch.no_grad():
        default = net(*x)
        outcome = net(*x, head="outcome")
        search = net(*x, head="search-mean")
    assert torch.equal(default, outcome) and outcome.shape == search.shape == (5, OUTCOME_CLASSES)
    assert not torch.allclose(outcome, search)
    served = ValueNetwork(ValueModelConfig.from_payload({**cfg.payload(), "value_head": "search-mean"}))
    served.load_state_dict(net.state_dict())
    with torch.no_grad():
        assert torch.equal(served.eval()(*x), search)  # value_head decides the default
    single = ValueNetwork(_cfg()).eval()
    with pytest.raises(ValueModelError, match="no search-mean head"):
        single(*_inputs(_cfg()), head="search-mean")
    # the state hash covers the second head: same trunk, different head -> different hash
    h0 = model_state_sha256(net)
    with torch.no_grad():
        net.search_head.bias.add_(1.0)
    assert model_state_sha256(net) != h0


def test_checkpoint_round_trip_keeps_both_heads(tmp_path):
    torch.manual_seed(2)
    cfg = _cfg(search_head=True)
    net = ValueNetwork(cfg)
    save_checkpoint(tmp_path / "two.pt", net, metadata={"note": "test"})
    back, _meta = load_checkpoint(tmp_path / "two.pt")
    assert back.config == cfg and set(back.state_dict()) == set(net.state_dict())
    x = _inputs(cfg)
    with torch.no_grad():
        assert torch.equal(back.eval()(*x, head="search-mean"), net.eval()(*x, head="search-mean"))


@pytest.fixture(scope="module")
def two_head_run(store_dir, luna, tmp_path_factory):
    """One toy training run with the search head (and the same run without it)."""
    tmp_path = tmp_path_factory.mktemp("twohead")
    luna_path, _rows = luna
    side = tmp_path / "sidecar"
    built = [sc.build_sidecar(p, side, level_objective=False)
             for p in sorted(glob.glob(str(store_dir) + "/**/*.jsonl", recursive=True))]
    assert built and sum(c["with_mean"] for c in built) > 0
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=2, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    plain = train_cwv.train(out=tmp_path / "plain", **kw)
    two = train_cwv.train(out=tmp_path / "two", search_head=True,
                          search_mean_sidecar=str(side), **kw)
    return {"tmp": tmp_path, "side": side, "kw": kw, "plain": plain, "two": two}


def test_trainer_trains_the_search_head_on_sidecar_rows_only_and_reports_it(two_head_run):
    r = two_head_run
    two, plain = r["two"], r["plain"]
    assert two["config"]["search_head"] is True and two["config"]["search_head_weight"] == 1.0
    assert plain["config"]["search_head"] is False and plain["config"]["search_head_weight"] == 0.0
    assert two["target"] == {"kind": "realised"}  # the outcome head keeps its target
    assert two["search_head"]["sidecar_manifest_sha256"] == sc.manifest_sha256(r["side"])
    assert two["search_head"]["value_head"] == "outcome" and "ramp" in two["search_head"]["estimand"]
    assert plain.get("search_head") is None
    ep = two["epochs"][0]["train"]
    assert 0 < ep["search_head_rows"] <= ep["rows"] and ep["search_head_cross_entropy"] > 0
    # the second head's ranking is reported, never selected on
    val = two["epochs"][0]["val"]
    assert "search_head" in val and set(k for k in val["search_head"] if k.startswith("rank_"))
    assert two["selection"]["criterion"] == plain["selection"]["criterion"]
    assert "search_head" not in plain["epochs"][0]["val"]
    assert "search_mean_head" in two["consumer"]["heads"]
    assert "search_mean_head" not in plain["consumer"]["heads"]
    # best.pt carries both heads and loads through the production loader
    model, meta, _sha = cwv_policy.load_cwv_checkpoint(r["tmp"] / "two" / "best.pt")
    assert model.config.search_head is True and model.config.value_head == "outcome"
    assert any(k.startswith("search_head") for k in model.state_dict())


def test_search_head_needs_a_sidecar_and_a_realised_primary(two_head_run):
    r = two_head_run
    with pytest.raises(train_cwv.TrainError, match="search-mean-sidecar"):
        train_cwv.train(out=r["tmp"] / "nosidecar", search_head=True, **r["kw"])
    with pytest.raises(train_cwv.TrainError, match="cannot be combined"):
        train_cwv.train(out=r["tmp"] / "both", search_head=True, target="search-mean",
                        search_mean_sidecar=str(r["side"]), **r["kw"])
    with pytest.raises(train_cwv.TrainError, match="search-head-weight"):
        train_cwv.train(out=r["tmp"] / "w0", search_head=True, search_head_weight=0.0,
                        search_mean_sidecar=str(r["side"]), **r["kw"])


def test_evaluator_reads_the_named_head_and_binds_it_in_its_identity(two_head_run):
    ckpt = two_head_run["tmp"] / "two" / "best.pt"
    default = cwv_policy.CompleteWorldEvaluator(ckpt, threads=1)
    search = cwv_policy.CompleteWorldEvaluator(ckpt, threads=1, value_head="search-mean")
    assert default.value_head == "outcome" and "value_head" not in default.identity()
    assert search.value_head == "search-mean" and search.identity()["value_head"] == "search-mean"
    cfg = default.model.config
    public, _h, _m, world, persp = _inputs(cfg, n=4, seed=3)
    from shengji.rl.value_afterstate import ValueAfterstateTensors
    rows = [ValueAfterstateTensors(public[i].numpy(), np.zeros((1, HISTORY_EVENT_DIM), np.float32),
                                   world[i].numpy(), persp[i].numpy()) for i in range(4)]
    p0, p1 = default.probabilities(rows), search.probabilities(rows)
    assert p0.shape == p1.shape == (4, OUTCOME_CLASSES) and not np.allclose(p0, p1)
    with torch.no_grad():
        want = torch.softmax(default.model(public, _h, _m, world, persp, head="search-mean"), 1)
    assert np.allclose(p1, want.numpy(), atol=1e-6)
    # the shared cache keys on the head: two entries, never one reused
    a = cwv_policy.shared_evaluator(ckpt, threads=1)
    b = cwv_policy.shared_evaluator(ckpt, threads=1, value_head="search-mean")
    assert a is not b and a.value_head == "outcome" and b.value_head == "search-mean"
    assert cwv_policy.shared_evaluator(ckpt, threads=1, value_head="search-mean") is b
    single = two_head_run["tmp"] / "plain" / "best.pt"
    with pytest.raises(cwv_policy.CWVError, match="no search-mean head"):
        cwv_policy.CompleteWorldEvaluator(single, threads=1, value_head="search-mean")


def test_screen_binds_the_value_head_to_the_arm_evaluator_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "_run_pending", lambda config, pending, shards, **kw: None)
    seen = []

    class Evaluator:
        checkpoint_sha256 = "a" * 64

        def __init__(self, value_head):
            self.value_head = value_head

        def identity(self):
            return {"backend": "torch"}

    def fake_shared(*a, **kw):
        seen.append(kw.get("value_head"))
        return Evaluator(kw.get("value_head"))

    monkeypatch.setattr(S, "shared_evaluator", fake_shared)
    monkeypatch.setattr(S, "execution_source_identity", lambda *_: {"source": "test"})
    ckpt = tmp_path / "m.pt"
    ckpt.write_bytes(b"x")
    out = tmp_path / "head"
    assert S.main(["--arm", "learned", "--checkpoint", str(ckpt), "--value-head", "search-mean",
                   "--clusters", "1", "--workers", "1", "--seed0", "17", "--out", str(out)]) == 0
    persisted = json.loads((out / "config.json").read_text())
    assert persisted["value_head"] == "search-mean"
    seen.clear()
    S.make_side(persisted, "arm", seed=17)
    S.make_side(persisted, "baseline", seed=17)
    assert seen == ["search-mean"]  # the arm gets the head; the production baseline builds no evaluator
    out2 = tmp_path / "plain"
    assert S.main(["--arm", "learned", "--checkpoint", str(ckpt),
                   "--clusters", "1", "--workers", "1", "--seed0", "17", "--out", str(out2)]) == 0
    assert "value_head" not in json.loads((out2 / "config.json").read_text())
    with pytest.raises(SystemExit):
        S.main(["--arm", "production", "--value-head", "search-mean", "--clusters", "1",
                "--workers", "1", "--seed0", "17", "--out", str(tmp_path / "bad")])


def test_queue_passes_the_value_head_to_every_window(monkeypatch, tmp_path):
    from shengji.train import cwv_screen_queue as Q
    calls = []

    def fake_main(command):
        calls.append(command)
        out = __import__("pathlib").Path(command[command.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(
            {"complete": True, "completed_clusters": 1, "requested_clusters": 1}))
        return 0

    monkeypatch.setattr(Q.screen, "main", fake_main)
    monkeypatch.setattr(Q, "_window_complete", lambda *a, **k: True, raising=False)
    ckpt = tmp_path / "m.pt"
    ckpt.write_bytes(b"x")
    import hashlib
    sha = hashlib.sha256(b"x").hexdigest()
    try:
        Q.main(["--checkpoint", str(ckpt), "--checkpoint-sha256", sha, "--out", str(tmp_path),
                "--name", "arm", "--workers", "1", "--clusters", "1", "--seeds", "5",
                "--value-head", "search-mean"])
    except SystemExit:
        pass
    assert calls and "--value-head" in calls[0] and calls[0][calls[0].index("--value-head") + 1] == "search-mean"


def test_export_packages_the_named_head(two_head_run, tmp_path):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts"))
    from export_cwv_numpy import export_cwv_numpy
    ckpt = two_head_run["tmp"] / "two" / "best.pt"
    export_cwv_numpy(ckpt, tmp_path / "outcome.npz")
    export_cwv_numpy(ckpt, tmp_path / "search.npz", value_head="search-mean")
    model, _m, _s = cwv_policy.load_cwv_checkpoint(ckpt)
    a, b = np.load(tmp_path / "outcome.npz"), np.load(tmp_path / "search.npz")
    assert np.array_equal(a["head_weight"], model.head.weight.detach().numpy())
    assert np.array_equal(b["head_weight"], model.search_head.weight.detach().numpy())
    assert json.loads(str(a["metadata"]))["metadata"]["exported_value_head"] == "outcome"
    assert json.loads(str(b["metadata"]))["metadata"]["exported_value_head"] == "search-mean"
    with pytest.raises(ValueError, match="no search-mean head"):
        export_cwv_numpy(two_head_run["tmp"] / "plain" / "best.pt", tmp_path / "bad.npz",
                         value_head="search-mean")
    # export -> reopen -> identity (Codex HOLD on #374): the numpy evaluator binds
    # the exported head, names it in identity(), and computes with those weights;
    # an outcome package keeps the legacy omission
    outcome_eval = cwv_policy.shared_evaluator(tmp_path / "outcome.npz", threads=1)
    search_eval = cwv_policy.shared_evaluator(tmp_path / "search.npz", threads=1)
    assert outcome_eval.value_head == "outcome" and "value_head" not in outcome_eval.identity()
    assert search_eval.value_head == "search-mean" and search_eval.identity()["value_head"] == "search-mean"
    cfg = model.config
    public, _h, _m, world, persp = _inputs(cfg, n=3, seed=9)
    from shengji.rl.value_afterstate import ValueAfterstateTensors
    rows = [ValueAfterstateTensors(public[i].numpy(), np.zeros((1, HISTORY_EVENT_DIM), np.float32),
                                   world[i].numpy(), persp[i].numpy()) for i in range(3)]
    torch_search = cwv_policy.CompleteWorldEvaluator(ckpt, threads=1, value_head="search-mean")
    assert np.allclose(search_eval.probabilities(rows), torch_search.probabilities(rows), atol=1e-5)
    assert not np.allclose(search_eval.probabilities(rows), outcome_eval.probabilities(rows))
    with pytest.raises(cwv_policy.CWVError, match="cannot be overridden"):
        cwv_policy.shared_evaluator(tmp_path / "outcome.npz", threads=1, value_head="search-mean")
    # a package naming a head this schema does not know is refused at open
    import shutil
    z = dict(np.load(tmp_path / "search.npz"))
    meta = json.loads(str(z["metadata"])); meta["metadata"]["exported_value_head"] = "aux"
    z["metadata"] = np.asarray(json.dumps(meta, sort_keys=True))
    np.savez_compressed(tmp_path / "unknown.npz", **z)
    with pytest.raises(cwv_policy.CWVError, match="unknown exported value head"):
        cwv_policy.shared_evaluator(tmp_path / "unknown.npz", threads=1)
