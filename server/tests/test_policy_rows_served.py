"""Served-capture policy rows (``train.served_policy_rows``): soft rows carry the
base pass's means so the trainer's target is softmax(means / T) on the admitted
ballot, a lead whose confirmed challenger replaced the base winner is a hard row
on the played slot, rows without two finite means are excluded and counted by
reason, held-out seeds and deal keys never reach the output, the output
directory is fresh and disjoint from the inputs, the bytes do not depend on the
worker count, and the real trainer streams the rows end to end."""
from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.ai.registry import REGISTRY, register_pv_search_policies  # noqa: E402
from shengji.harvest import trajectory  # noqa: E402
from shengji.harvest.common import action_key  # noqa: E402
from shengji.train import policy_prior as pp  # noqa: E402
from shengji.train import pv_search_policy as pv  # noqa: E402
from shengji.train import served_policy_rows as spr  # noqa: E402
from shengji.train.cwv_bury_policy import CWVBuryConfig  # noqa: E402
from shengji.train.cwv_data import POINTS_PER_LEVEL, deal_key  # noqa: E402
from shengji.train.policy_rows import PolicyRowsStream, open_policy_rows, policy_losses  # noqa: E402
from test_cwv_train import THIRDS, store_dir  # noqa: E402,F401

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
BURY = CWVBuryConfig(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)
SEED0 = 4_370_000
ROUNDS = 4                       # two deal clusters: seeds SEED0 and SEED0 + 1


@pytest.fixture(scope="module")
def pv_package(tmp_path_factory):
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import file_sha256, local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp("spr-pkg")
    torch.manual_seed(11)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                        public_dim=561, enc_version=2, attention_heads=1,
                                        trunk_block="residual", trunk_layers=2,
                                        search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "joint.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2), "sees_hidden_hands": True})
    pkg = d / "joint.npz"
    export_cwv_numpy(ckpt, pkg)
    return str(pkg), file_sha256(pkg)


@pytest.fixture(scope="module")
def pv_store(pv_package, tmp_path_factory):
    """A real pv-search trajectory store (two deals, both mirrors)."""
    path, sha = pv_package
    env = dict(CKPT=path, SHA256=sha, BURY_ARM="hybrid", **{k.upper(): v for k, v in SMALL.items()},
               **{"BURY_" + k.upper(): v for k, v in asdict(BURY).items()})
    with pytest.MonkeyPatch.context() as mp:
        for key, value in env.items():
            mp.setenv("SHENGJI_PV_" + key, str(value))
        mp.delenv("SHENGJI_PV_SERVING_BUDGET_SECONDS", raising=False)
        mp.delenv("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS", raising=False)
        names = register_pv_search_policies(**pv.pv_env_recipe())
        try:
            out = tmp_path_factory.mktemp("spr-store") / "run"
            trajectory.generate(rounds=ROUNDS, seed0=SEED0, out_dir=out, workers=1, policy=names[0],
                                merge=False, resume=False, explore_rate=0.0, explore_k=0,
                                seed_windows=out.parent / "seed_windows.json")
        finally:
            for n in names:
                REGISTRY.pop(n, None)
    return out


def _records(store: Path) -> list[dict]:
    from shengji.train.data import discover_store, iter_records
    return [r for sh in discover_store(store).shards for r in iter_records(sh)]


def _priced(rec) -> list[float]:
    av = rec.get("action_values") or {}
    return [m for m in av.get("means") or [] if m is not None and math.isfinite(m)]


def _is_lead(rec) -> bool:
    return rec["decision_kind"] == "play" and rec["ply"] % 4 == 0 and rec["ply"] > 0


def _served_fixture(records: list[dict]) -> tuple[list[dict], dict]:
    """The real records rewritten into the served capture's record shapes: one
    applied lead confirmation (the challenger appended to the ballot with a None
    mean, the decision record under ``allocation.serving_decision``), one
    rejected confirmation, one serving-budget fallback, one applied record whose
    challenger disagrees with the played action, and one record whose played
    slot lost its mean with no confirmation recorded."""
    out = copy.deepcopy(records)
    marks: dict[str, int] = {}
    leads = [i for i, r in enumerate(out) if _is_lead(r) and len(_priced(r)) >= 2]
    plays = [i for i, r in enumerate(out) if r["decision_kind"] == "play" and len(_priced(r)) >= 3]
    assert len(leads) >= 3 and plays, "the fixture store has too few contested decisions"

    def apply_lcc(i: int, *, consistent: bool) -> None:
        r = out[i]
        on_ballot = {action_key(a) for a in r["ballot"]}
        challenger = next(list(a) for a in r["legal_actions"] if action_key(a) not in on_ballot)
        k = len(r["ballot"])
        r["ballot"].append(challenger)
        r["action_values"]["means"].append(None)
        r["action_values"]["eligible_indices"].append(k)
        r["action"] = challenger
        r["allocation"]["played_index"] = k
        other = r["ballot"][0]
        r["allocation"]["serving_decision"] = {
            "schema": "pv-search-decision-v1", "lead_confirm_status": "applied",
            "lead_confirm_applied": True,
            "lead_confirm_to": list(challenger if consistent else other)}

    apply_lcc(leads[0], consistent=True); marks["lcc"] = leads[0]
    apply_lcc(leads[1], consistent=False); marks["lcc_bad"] = leads[1]
    rej = out[leads[2]]
    rej["allocation"]["serving_decision"] = {"schema": "pv-search-decision-v1",
                                             "lead_confirm_status": "rejected",
                                             "lead_confirm_applied": False, "lead_confirm_to": None}
    marks["rejected"] = leads[2]
    fb = next(i for i, r in enumerate(out) if r["decision_kind"] == "play" and i not in leads[:3]
              and len(_priced(r)) >= 2)
    out[fb]["ballot"] = [list(out[fb]["action"])]
    out[fb]["action_values"] = None
    out[fb]["allocation"] = {**trajectory.point_mass_allocation("serving_budget_fallback"),
                             "serving_decision": {"schema": "pv-search-fallback-v1", "reason": "budget"}}
    marks["fallback"] = fb
    up = next(i for i in plays if i not in leads[:3] and i != fb)
    r = out[up]
    slot = next(j for j, a in enumerate(r["ballot"]) if action_key(a) == action_key(r["action"]))
    r["action_values"]["means"][r["action_values"]["eligible_indices"].index(slot)] = None
    marks["unpriced"] = up
    return out, marks


@pytest.fixture(scope="module")
def served_store(pv_store, tmp_path_factory):
    recs, marks = _served_fixture(_records(pv_store))
    d = tmp_path_factory.mktemp("spr-served") / "store"
    d.mkdir()
    (d / "trajectory.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
    return d, recs, marks


@pytest.fixture(scope="module")
def produced(served_store, tmp_path_factory):
    d, recs, marks = served_store
    out = tmp_path_factory.mktemp("spr-out") / "rows"
    summary = spr.produce(out, [d], version=2, chunk_rows=64)
    return out, summary, recs, marks


def _rows(out: Path) -> dict[str, np.ndarray]:
    man = json.loads((out / "manifest.json").read_text())
    parts = [dict(np.load(out / c["file"])) for c in man["chunks"]]
    width = max(p["ball"].shape[1] for p in parts)
    cards = max(p["ball"].shape[2] for p in parts)
    rows = {k: np.concatenate([p[k] for p in parts]) for k in ("X", "Y", "tgt", "deal_key", "target_kind")}
    rows["ball"] = np.concatenate([np.pad(p["ball"], ((0, 0), (0, width - p["ball"].shape[1]),
                                                       (0, cards - p["ball"].shape[2])), constant_values=-1)
                                   for p in parts])
    rows["mask"] = np.concatenate([np.pad(p["mask"], ((0, 0), (0, width - p["mask"].shape[1])))
                                   for p in parts])
    rows["vals"] = np.concatenate([np.pad(p["vals"], ((0, 0), (0, width - p["vals"].shape[1])),
                                          constant_values=np.nan) for p in parts])
    return rows


def _kept(recs: list[dict]) -> list[tuple[dict, str]]:
    """The records the producer keeps, in record order (one shard: no reordering)."""
    kept = []
    for r in recs:
        if r["decision_kind"] != "play":
            continue
        target, _reason, _means, _units = spr.classify(r)
        if target is not None:
            kept.append((r, target))
    return kept


@pytest.mark.parametrize("temperature", [1.0, 0.5, 3.0])
def test_soft_rows_target_softmax_of_the_ballot_means(produced, temperature):
    out, summary, recs, _marks = produced
    rows = _rows(out)
    kept = _kept(recs)
    assert len(kept) == summary["rows"] == len(rows["tgt"])
    vals = torch.from_numpy(rows["vals"]); mask = torch.from_numpy(rows["mask"])
    probs, usable = pp.soft_ballot_targets(vals, mask, temperature)
    soft_seen = 0
    for i, (rec, target) in enumerate(kept):
        slot = next(j for j, a in enumerate(rec["ballot"]) if action_key(a) == action_key(rec["action"]))
        assert rows["tgt"][i] == slot and rows["deal_key"][i] == deal_key(rec["deck"])
        assert sorted(np.flatnonzero(rows["Y"][i]).tolist()) == sorted({pp.CARD_INDEX[c] for c in rec["action"]})
        if target != "soft":
            continue
        soft_seen += 1
        av = rec["action_values"]
        by_slot = {j: m for j, m in zip(av["eligible_indices"], av["means"]) if m is not None}
        finite = sorted(by_slot)
        z = np.asarray([by_slot[j] * POINTS_PER_LEVEL / temperature for j in finite], np.float64)
        want = np.exp(z - z.max()); want /= want.sum()
        assert bool(usable[i]) and rows["target_kind"][i] == spr.TARGET_SOFT
        got = probs[i].numpy()
        np.testing.assert_allclose(got[finite], want, rtol=1e-5, atol=1e-6)
        assert np.all(got[[j for j in range(len(got)) if j not in by_slot]] == 0)
    assert soft_seen == summary["target_rows"]["soft"] > 10


def test_an_applied_lead_confirmation_is_a_hard_row_on_the_played_challenger(produced):
    out, summary, recs, marks = produced
    rows = _rows(out)
    kept = _kept(recs)
    lcc = recs[marks["lcc"]]
    i = next(n for n, (r, _t) in enumerate(kept) if r is lcc)
    assert kept[i][1] == "hard_lcc" and summary["target_rows"]["hard_lcc"] == 1
    assert rows["target_kind"][i] == spr.TARGET_HARD_LCC
    assert rows["tgt"][i] == len(lcc["ballot"]) - 1                    # the appended challenger
    assert np.isnan(rows["vals"][i]).all()
    vals = torch.from_numpy(rows["vals"][i:i + 1]); mask = torch.from_numpy(rows["mask"][i:i + 1])
    _probs, usable = pp.soft_ballot_targets(vals, mask, 1.0)
    assert not bool(usable[0])
    # the trainer's soft loss on this row IS the hard cross-entropy on the played slot
    logits = torch.randn(1, 54)
    ball = torch.from_numpy(rows["ball"][i:i + 1]); tgt = torch.from_numpy(rows["tgt"][i:i + 1]).long()
    soft = pp.listwise_loss_soft(logits, ball, mask, tgt, vals, temperature=1.0)
    hard = pp.listwise_loss(logits, ball, mask, tgt)
    assert torch.allclose(soft, hard)
    # a rejected confirmation keeps the base winner: an ordinary soft row
    rej = recs[marks["rejected"]]
    assert next(t for r, t in kept if r is rej) == "soft"
    assert summary["lead_confirm_status"] == {"applied": 2, "rejected": 1}


def test_rows_without_two_finite_means_are_excluded_and_counted_by_reason(produced, served_store):
    _out, summary, recs, _marks = produced
    plays = [r for r in recs if r["decision_kind"] == "play"]
    ex = summary["excluded"]
    assert summary["play_records"] == len(plays) == summary["rows"] + summary["excluded_rows"]
    assert summary["non_play_records"] == len(recs) - len(plays)
    assert ex["unsearched:serving_budget_fallback"] == 1
    assert ex["lcc_record_inconsistent"] == 1 and ex["played_unpriced_without_lcc"] == 1
    natural = sum(1 for r in plays if "serving_decision" not in r["allocation"]
                  and r["action_values"] is not None and len(_priced(r)) < 2)
    unsearched = sum(1 for r in plays if r["allocation"].get("searched") is False
                     and r["allocation"].get("reason") != "serving_budget_fallback")
    assert ex["fewer_than_two_finite_means"] == natural
    assert sum(v for k, v in ex.items() if k.startswith("unsearched:")) == unsearched + 1
    assert natural + unsearched > 0, "the fixture should hold single-candidate decisions"
    assert ex["excluded_seed"] == ex["excluded_deal_key"] == ex["rebuild_failed"] == ex["turn_mismatch"] == 0
    on_disk = json.loads((_out / "summary.json").read_text())
    assert on_disk == json.loads(json.dumps(summary, sort_keys=True))
    man = json.loads((_out / "manifest.json").read_text())
    assert man["producer"]["excluded"] == ex and man["values_scale"] == "points"


def test_excluded_seeds_and_deal_keys_never_reach_the_output(pv_store, tmp_path):
    recs = _records(pv_store)
    seeds = sorted({r["round_seed"] for r in recs})
    assert seeds == [SEED0, SEED0 + 1]
    held = {deal_key(r["deck"]) for r in recs if r["round_seed"] == SEED0 + 1}
    kept = {deal_key(r["deck"]) for r in recs if r["round_seed"] == SEED0}
    assert len(held) == 1 and not held & kept
    held_plays = sum(1 for r in recs if r["round_seed"] == SEED0 + 1 and r["decision_kind"] == "play")
    s = spr.produce(tmp_path / "a", [pv_store], version=2, exclude_seeds=[(SEED0 + 1, SEED0 + 2)])
    rows = _rows(tmp_path / "a")
    assert set(rows["deal_key"].astype(str)) == kept
    assert s["excluded"]["excluded_seed"] == held_plays and s["exclusions"]["excluded_deals_seen"] == 1
    assert s["exclusions"]["seed_intervals_half_open"] == [[SEED0 + 1, SEED0 + 2]]
    keys = tmp_path / "held.txt"; keys.write_text("".join(k + "\n" for k in sorted(held)))
    s = spr.produce(tmp_path / "b", [pv_store], version=2, exclude_deal_keys=keys)
    assert set(_rows(tmp_path / "b")["deal_key"].astype(str)) == kept
    assert s["excluded"]["excluded_deal_key"] == held_plays and s["exclusions"]["deal_keys_listed"] == 1
    # the CLI form, LO:HI half-open
    assert spr.parse_seed_interval(f"{SEED0 + 1}:{SEED0 + 2}") == (SEED0 + 1, SEED0 + 2)
    assert spr.parse_seed_interval(str(SEED0)) == (SEED0, SEED0 + 1)
    with pytest.raises(spr.ServedPolicyRowsError, match="below"):
        spr.parse_seed_interval("9:9")
    # every seed excluded: nothing to write
    with pytest.raises(spr.ServedPolicyRowsError, match="no rows"):
        spr.produce(tmp_path / "c", [pv_store], version=2, exclude_seeds=[(SEED0, SEED0 + 2)])


def test_output_must_be_fresh_and_disjoint_from_the_inputs(pv_store, tmp_path):
    (tmp_path / "exists").mkdir()
    with pytest.raises(spr.ServedPolicyRowsError, match="already exists"):
        spr.produce(tmp_path / "exists", [pv_store], version=2)
    with pytest.raises(spr.ServedPolicyRowsError, match="overlaps"):
        spr.produce(pv_store / "rows", [pv_store], version=2)
    with pytest.raises(spr.ServedPolicyRowsError, match="overlaps"):
        spr.produce(pv_store.parent, [pv_store], version=2)
    with pytest.raises(spr.ServedPolicyRowsError, match="explicitly"):
        spr.produce(tmp_path / "v", [pv_store], version="2")
    with pytest.raises(SystemExit):           # the CLI has no default encoder version
        spr.main(["--data", str(pv_store), "--out", str(tmp_path / "cli")])
    assert not (tmp_path / "cli").exists()


def test_output_bytes_do_not_depend_on_workers_and_the_encoder_is_checked(pv_store, tmp_path):
    one = spr.produce(tmp_path / "one", [pv_store], version=2, chunk_rows=50, workers=1)
    two = spr.produce(tmp_path / "two", [pv_store], version=2, chunk_rows=50, workers=2)
    m1 = (tmp_path / "one" / "manifest.json").read_bytes()
    assert m1 == (tmp_path / "two" / "manifest.json").read_bytes()
    man = json.loads(m1)
    assert len(man["chunks"]) >= 2 and man["enc_version"] == 2 and man["input_dim"] == pp.INPUT_DIM
    for c in man["chunks"]:
        assert (tmp_path / "one" / c["file"]).read_bytes() == (tmp_path / "two" / c["file"]).read_bytes()
    assert {k: v for k, v in one.items() if k != "out"} == {k: v for k, v in two.items() if k != "out"}
    assert one["encoder_implementation_sha256"]
    stream = open_policy_rows(tmp_path / "one", version=2)
    assert isinstance(stream, PolicyRowsStream) and stream.n == one["rows"]
    assert stream.identity["values_scale"] == "points" and stream.identity["chunks_verified"] == len(man["chunks"])
    with pytest.raises(ValueError, match="schema drift"):
        PolicyRowsStream(tmp_path / "one", version=5)
    capped = spr.produce(tmp_path / "cap", [pv_store], version=2, chunk_rows=50, max_rows=70)
    assert capped["rows"] == 70 and capped["stopped_at_max_rows"]
    assert [c["rows"] for c in json.loads((tmp_path / "cap" / "manifest.json").read_text())["chunks"]] == [50, 20]


def test_the_stream_trains_one_soft_step_with_the_hard_row_mixed_in(produced):
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    out, summary, _recs, _marks = produced
    stream = PolicyRowsStream(out, window=100, version=2)              # every chunk in one window
    torch.manual_seed(3)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=16, history_layers=1, attention_heads=1,
                                        feedforward_width=32, public_dim=561, enc_version=2,
                                        policy_head=True))
    opt = torch.optim.SGD(net.parameters(), lr=0.1)
    batch = next(stream.batches(10 ** 6, np.random.default_rng(0)))       # every row in one batch
    t = stream.tensors(batch, "cpu")
    assert "vals" in t and int((t["tgt"] >= 0).sum()) == summary["rows"] == len(t["x"])
    assert int((~torch.isfinite(t["vals"]) | ~t["mask"]).all(1).sum()) == 1    # the one hard row
    before = [p.detach().clone() for p in net.policy_head.parameters()]
    bce, lw, _ = policy_losses(net, t, listwise_weight=1.0, soft_targets=True, soft_temperature=1.0)
    assert torch.isfinite(bce) and torch.isfinite(lw) and float(lw.detach()) > 0
    opt.zero_grad(); (bce + lw).backward(); opt.step()
    assert any(not torch.equal(a, b) for a, b in zip(before, net.policy_head.parameters()))


def test_train_cwv_streams_the_rows_with_soft_targets(produced, store_dir, tmp_path):  # noqa: F811
    from shengji.train import train_cwv
    out, summary, _recs, _marks = produced
    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64, n_boot=10,
              hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32, val_rank_records=50,
              encoder_version=2, **THIRDS)
    r = train_cwv.train(out=tmp_path / "run", policy_head=True, policy_rows=str(out),
                        policy_batch_fraction=0.5, policy_soft_targets=True,
                        policy_soft_temperature=1.0, **kw)
    block = r["policy_head"]
    assert block["rows"]["format"] == pp.CHUNK_SCHEMA and block["rows"]["rows_used"] == summary["rows"]
    assert block["rows"]["rows_excluded"] == 0                   # disjoint from the value store's deals
    tr = r["epochs"][0]["train"]
    assert tr["policy_rows"] > 0 and math.isfinite(tr["policy_listwise"]) and tr["policy_listwise"] > 0
