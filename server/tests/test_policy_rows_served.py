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
from shengji.harvest.rebuild import state_for_record  # noqa: E402
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
    if all("lead_type" in p for p in parts):
        rows["lead_type"] = np.concatenate([p["lead_type"] for p in parts])
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


def test_default_output_has_no_lead_transform_and_is_byte_stable(pv_store, tmp_path):
    one = spr.produce(tmp_path / "one", [pv_store], version=2, chunk_rows=50, workers=1)
    two = spr.produce(tmp_path / "two", [pv_store], version=2, chunk_rows=50, workers=1)
    assert one == {**two, "out": one["out"]}
    assert (tmp_path / "one" / "manifest.json").read_bytes() == (tmp_path / "two" / "manifest.json").read_bytes()
    for chunk in json.loads((tmp_path / "one" / "manifest.json").read_text())["chunks"]:
        with np.load(tmp_path / "one" / chunk["file"]) as data:
            assert "lead_type" not in data.files


def test_lead_types_hard_throw_rows_stream_to_hard_loss(produced, served_store, tmp_path):
    base_out, _base_summary, _recs, _marks = produced
    out = tmp_path / "hard-throw"
    summary = spr.produce(out, [served_store[0]], version=2, chunk_rows=64,
                          hard_lead_types=("throw",))
    rows = _rows(out)
    assert summary["lead_type_transform"] == {
        "lead_types": True, "hard_lead_types": ["throw"],
        "drop_hard_lcc_lead_types": [],
    }
    assert rows["lead_type"].dtype == np.int8
    hard = rows["target_kind"] == spr.TARGET_HARD_PLAYED
    assert hard.any() and summary["target_rows"]["hard_played"] == int(hard.sum())
    assert np.isnan(rows["vals"][hard]).all()
    assert np.all(rows["lead_type"][hard] == spr.LEAD_THROW)
    # Follows retain their old targets and values; only selected soft leads transform.
    follow = rows["lead_type"] == spr.LEAD_FOLLOW
    assert np.all(rows["target_kind"][follow] != spr.TARGET_HARD_PLAYED)
    base_rows = _rows(base_out)
    np.testing.assert_array_equal(rows["target_kind"][follow], base_rows["target_kind"][follow])
    np.testing.assert_allclose(rows["vals"][follow], base_rows["vals"][follow], equal_nan=True)

    stream = PolicyRowsStream(out, window=100, version=2)
    batch = next(stream.batches(10 ** 6, np.random.default_rng(0)))
    t = stream.tensors(batch, "cpu")
    hard_batch = (~torch.isfinite(t["vals"]) | ~t["mask"]).all(1)
    assert int(hard_batch.sum()) == int((hard | (rows["target_kind"] == spr.TARGET_HARD_LCC)).sum())
    hard_index = torch.nonzero(hard_batch & (t["tgt"] >= 0), as_tuple=False).flatten()
    logits = torch.randn(len(t["tgt"]), 54)
    soft = pp.listwise_loss_soft(logits, t["ball"], t["mask"], t["tgt"],
                                 t["vals"], temperature=1.0, rows=hard_index)
    hard_loss = pp.listwise_loss(logits, t["ball"], t["mask"], t["tgt"], rows=hard_index)
    assert torch.allclose(soft, hard_loss)


def test_drop_hard_lcc_throw_precedes_hard_played(tmp_path, served_store):
    _source, records, marks = served_store
    altered = copy.deepcopy(records)
    record = altered[marks["lcc"]]
    root = state_for_record(record)
    ballot_keys = {action_key(action) for action in record["ballot"]}
    throw = next(action for action in record["legal_actions"]
                 if spr._lead_type(root, action) == spr.LEAD_THROW
                 and action_key(action) not in ballot_keys)
    slot = len(record["ballot"])
    record["action"] = list(throw)
    record["ballot"].append(list(throw))
    record["action_values"]["means"].append(None)
    record["action_values"]["eligible_indices"].append(slot)
    record["allocation"]["played_index"] = slot
    record["allocation"]["serving_decision"]["lead_confirm_to"] = list(throw)
    custom = tmp_path / "altered"
    custom.mkdir()
    (custom / "trajectory.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in altered))
    out = tmp_path / "drop"
    summary = spr.produce(out, [custom], version=2, chunk_rows=64,
                          hard_lead_types=("throw",),
                          drop_hard_lcc_lead_types=("throw",))
    assert summary["excluded"]["hard_lcc_lead_type"] == 1
    assert summary["target_rows"]["hard_lcc"] == 0
    assert summary["target_rows"]["hard_played"] > 0


def test_invalid_lead_type_is_refused_before_writing(served_store, tmp_path):
    with pytest.raises(spr.ServedPolicyRowsError, match="invalid lead type"):
        spr.produce(tmp_path / "bad", [served_store[0]], version=2,
                    hard_lead_types=("not-a-lead",))
    assert not (tmp_path / "bad").exists()


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


# Partitions: N independently completed builds joined by ``combine``.

def _canonical_rows(directory: Path) -> list[tuple]:
    """Every row the real stream yields, as a hashable tuple (ballot slots and
    their values trimmed of each window's padding), in sorted order."""
    stream = PolicyRowsStream(directory, window=10 ** 6, version=2)
    batch = next(stream.batches(10 ** 7, np.random.default_rng(0)))
    out = []
    for i in range(len(batch["x"])):
        slots = []
        for j in np.flatnonzero(batch["mask"][i]):
            v = float(batch["vals"][i][j])
            slots.append((tuple(int(c) for c in batch["ball"][i][j] if c >= 0), None if math.isnan(v) else v))
        out.append((batch["x"][i].tobytes(), batch["y"][i].tobytes(), int(batch["tgt"][i]), tuple(slots),
                    int(batch["explore_flag"][i])))
    assert len(out) == stream.n
    return sorted(out, key=repr)


@pytest.fixture(scope="module")
def split_store(served_store, tmp_path_factory):
    """The served fixture's records as a five-shard store (no manifest; each
    shard verified by its sidecar), deals spanning shards."""
    from shengji.harvest.trajectory import SHARD_SCHEMA
    from shengji.train.data import sha256_file
    _d, recs, _marks = served_store
    root = tmp_path_factory.mktemp("spr-split") / "store"
    (root / "shards").mkdir(parents=True)
    bounds = np.linspace(0, len(recs), 6).astype(int)
    for k in range(5):
        part = recs[bounds[k]:bounds[k + 1]]
        path = root / "shards" / f"cluster-{k:06d}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in part))
        path.with_suffix(".json").write_text(json.dumps(
            {"schema": SHARD_SCHEMA, "sha256": sha256_file(path), "records": len(part), "cluster": k}))
    return root


_SAME = ("records", "play_records", "non_play_records", "rows", "excluded_rows", "target_rows", "excluded",
         "lead_confirm_status", "deals", "fit_deals_digest", "value_units", "enc_version", "input_dim",
         "encoder_implementation_sha256", "chunk_rows", "shard_order_seed")


@pytest.mark.parametrize("held_out", [False, True])
def test_partitions_combine_to_the_single_build_and_the_trainer_streams_them(
        split_store, store_dir, tmp_path, held_out):  # noqa: F811
    from shengji.train import train_cwv
    kw = dict(version=2, chunk_rows=7, exclude_seeds=[(SEED0 + 1, SEED0 + 2)] if held_out else [])
    single = spr.produce(tmp_path / "single", [split_store], **kw)
    parts = [tmp_path / f"part{i}" for i in range(3)]
    sums = [spr.produce(p, [split_store], partition=(i, 3), workers=1 + i % 2, **kw)
            for i, p in enumerate(parts)]
    assert sum(s["partition"]["shards"] for s in sums) == 5
    assert len({s["partition"]["all_shards_digest"] for s in sums}) == 1
    assert sum(s["rows"] for s in sums) == single["rows"]
    combined = spr.combine(tmp_path / "all", parts[::-1])          # any order
    for key in _SAME:
        assert combined[key] == single[key], key
    for key in ("excluded_deals_seen", "excluded_deals_digest", "seed_intervals_half_open"):
        assert combined["exclusions"][key] == single["exclusions"][key], key
    assert combined["play_records"] == combined["rows"] + combined["excluded_rows"]
    assert [p["index"] for p in combined["partitions"]] == [0, 1, 2]
    assert json.loads((tmp_path / "all" / "summary.json").read_text()) == json.loads(
        json.dumps(combined, sort_keys=True))
    # the same row multiset through the real stream, every chunk hash-verified
    assert _canonical_rows(tmp_path / "all") == _canonical_rows(tmp_path / "single")
    stream = open_policy_rows(tmp_path / "all", version=2)
    assert stream.identity["values_scale"] == "points"
    assert stream.identity["fit_deals_digest"] == single["fit_deals_digest"]
    assert stream.identity["chunks_verified"] == combined["chunks"] == sum(s["chunks"] for s in sums)
    if held_out:
        assert single["exclusions"]["excluded_deals_seen"] == 1
        assert min(s["rows"] for s in sums) >= 0 and combined["excluded"]["excluded_seed"] > 0
        return
    r = train_cwv.train(out=tmp_path / "run", policy_head=True, policy_rows=str(tmp_path / "all"),
                        policy_batch_fraction=0.5, policy_soft_targets=True, policy_soft_temperature=1.0,
                        data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64,
                        n_boot=10, hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32,
                        val_rank_records=50, encoder_version=2, **THIRDS)
    block = r["policy_head"]["rows"]
    assert block["rows_used"] == single["rows"] and block["chunks_verified"] == combined["chunks"]
    assert r["epochs"][0]["train"]["policy_rows"] > 0


def test_combine_refuses_mixed_lead_transform_semantics(split_store, tmp_path):
    spr.produce(tmp_path / "p0", [split_store], version=2, partition=(0, 2))
    spr.produce(tmp_path / "p1", [split_store], version=2, partition=(1, 2),
                lead_types=True)
    with pytest.raises(spr.ServedPolicyRowsError, match="other inputs or arguments"):
        spr.combine(tmp_path / "mixed", [tmp_path / "p0", tmp_path / "p1"])


def test_an_interrupted_partition_is_refused_then_rebuilt_to_the_same_bytes(split_store, tmp_path, monkeypatch):
    kw = dict(version=2, chunk_rows=5, partition=(1, 2))
    ref = spr.produce(tmp_path / "ref", [split_store], **kw)
    ref_man = (tmp_path / "ref" / "manifest.json").read_bytes()
    assert ref["chunks"] >= 2
    real = spr.write_chunk
    calls = []

    def dying(out_dir, index, *a):
        if len(calls) == 1:                      # the second flush dies half written
            (Path(out_dir) / f"chunk-{index:05d}.npz").write_bytes(b"PK\x03\x04partial")
            raise KeyboardInterrupt
        calls.append(index)
        return real(out_dir, index, *a)

    monkeypatch.setattr(spr, "write_chunk", dying)
    with pytest.raises(KeyboardInterrupt):
        spr.produce(tmp_path / "p1", [split_store], **kw)
    monkeypatch.setattr(spr, "write_chunk", real)
    assert not (tmp_path / "p1" / "manifest.json").exists()
    assert sorted(p.name for p in (tmp_path / "p1").iterdir()) == ["chunk-00000.npz", "chunk-00001.npz"]
    spr.produce(tmp_path / "p0", [split_store], **dict(kw, partition=(0, 2)))
    with pytest.raises(spr.ServedPolicyRowsError, match="no manifest"):
        spr.combine(tmp_path / "c", [tmp_path / "p0", tmp_path / "p1"])
    assert not (tmp_path / "c").exists()
    with pytest.raises(spr.ServedPolicyRowsError, match="already exists"):
        spr.produce(tmp_path / "p1", [split_store], **kw)
    spr.produce(tmp_path / "p1", [split_store], replace_incomplete=True, **kw)
    assert (tmp_path / "p1" / "manifest.json").read_bytes() == ref_man
    for c in json.loads(ref_man)["chunks"]:
        assert (tmp_path / "p1" / c["file"]).read_bytes() == (tmp_path / "ref" / c["file"]).read_bytes()
    # completed output is never rewritten, and a foreign file blocks removal
    with pytest.raises(spr.ServedPolicyRowsError, match="never rewritten"):
        spr.produce(tmp_path / "p1", [split_store], replace_incomplete=True, **kw)
    (tmp_path / "odd").mkdir(); (tmp_path / "odd" / "notes.txt").write_text("keep")
    with pytest.raises(spr.ServedPolicyRowsError, match="does not"):
        spr.produce(tmp_path / "odd", [split_store], replace_incomplete=True, **kw)
    assert (tmp_path / "odd" / "notes.txt").read_text() == "keep"
    spr.combine(tmp_path / "c", [tmp_path / "p0", tmp_path / "p1"])
    assert PolicyRowsStream(tmp_path / "c", version=2).n == sum(
        json.loads((tmp_path / p / "summary.json").read_text())["rows"] for p in ("p0", "p1"))


def test_combine_refuses_an_incomplete_mixed_or_tampered_set(split_store, tmp_path):
    kw = dict(version=2, chunk_rows=6)
    p = [tmp_path / f"p{i}" for i in range(3)]
    for i in range(3):
        spr.produce(p[i], [split_store], partition=(i, 3), **kw)
    with pytest.raises(spr.ServedPolicyRowsError, match=r"missing \[1\]"):
        spr.combine(tmp_path / "c", [p[0], p[2]])
    with pytest.raises(spr.ServedPolicyRowsError, match="listed twice"):
        spr.combine(tmp_path / "c", [p[0], p[1], p[2], p[1]])
    other = tmp_path / "other1"
    spr.produce(other, [split_store], partition=(1, 3), **dict(kw, chunk_rows=5))
    with pytest.raises(spr.ServedPolicyRowsError, match="other inputs"):
        spr.combine(tmp_path / "c", [p[0], other, p[2]])
    reseeded = tmp_path / "reseeded1"
    spr.produce(reseeded, [split_store], partition=(1, 3), seed=2, **kw)
    with pytest.raises(spr.ServedPolicyRowsError, match="other inputs"):
        spr.combine(tmp_path / "c", [p[0], reseeded, p[2]])
    two = tmp_path / "two1"
    spr.produce(two, [split_store], partition=(1, 2), **kw)
    with pytest.raises(spr.ServedPolicyRowsError, match="other inputs"):
        spr.combine(tmp_path / "c", [p[0], two, p[2]])
    single = tmp_path / "single"
    spr.produce(single, [split_store], **kw)
    with pytest.raises(spr.ServedPolicyRowsError, match="not a partition"):
        spr.combine(tmp_path / "c", [p[0], single, p[2]])
    man = json.loads((p[2] / "manifest.json").read_text())
    chunk = p[2] / man["chunks"][0]["file"]
    data = bytearray(chunk.read_bytes()); data[-30] ^= 1; chunk.write_bytes(bytes(data))
    with pytest.raises(spr.ServedPolicyRowsError, match="SHA256"):
        spr.combine(tmp_path / "c", p)
    assert not (tmp_path / "c").exists()
    with pytest.raises(spr.ServedPolicyRowsError, match="overlaps"):
        spr.combine(p[0] / "c", p)
    # partition arguments
    with pytest.raises(spr.ServedPolicyRowsError, match="whole build"):
        spr.produce(tmp_path / "m", [split_store], partition=(0, 2), max_rows=3, **kw)
    with pytest.raises(spr.ServedPolicyRowsError, match="no shard"):
        spr.produce(tmp_path / "e", [split_store], partition=(5, 6), **kw)
    for bad in ("3/3", "-1/2", "1", "a/b", "0/0"):
        with pytest.raises(spr.ServedPolicyRowsError, match="partition"):
            spr.parse_partition(bad)
    assert spr.parse_partition("2/7") == (2, 7)
    assert "partition" not in json.loads((single / "summary.json").read_text())


def test_the_cli_builds_a_partition_combines_and_benchmarks(split_store, tmp_path, capsys):
    from scripts import bench_served_policy_rows as bench
    base = ["--data", str(split_store), "--encoder-version", "2", "--chunk-rows", "8"]
    assert spr.main([*base, "--out", str(tmp_path / "p0"), "--partition", "0/2"]) == 0
    report = tmp_path / "bench.json"
    assert bench.main([*base, "--out", str(tmp_path / "p1"), "--partition", "1/2", "--workers", "2",
                       "--report", str(report), "--sample-seconds", "0.05"]) == 0
    b = json.loads(report.read_text())
    s1 = json.loads((tmp_path / "p1" / "summary.json").read_text())
    assert b["rows"] == s1["rows"] and b["chunks"] == s1["chunks"] == len(b["flushes"])
    assert [f["rows"] for f in b["flushes"]] == [c["rows"] for c in
                                                 json.loads((tmp_path / "p1" / "manifest.json").read_text())["chunks"]]
    assert b["peak_rss_mib"]["parent_plus_workers_sampled"] >= b["peak_rss_mib"]["parent_sampled"] > 0
    capsys.readouterr()
    assert spr.main(["combine", "--out", str(tmp_path / "all"), str(tmp_path / "p0"), str(tmp_path / "p1")]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["partition_count"] == 2 and printed["rows"] == PolicyRowsStream(tmp_path / "all", version=2).n
    assert spr.main(["combine", "--out", str(tmp_path / "all"), str(tmp_path / "p0"), str(tmp_path / "p1")]) == 2


def test_recovery_refuses_an_output_symlink_and_leaves_its_target(split_store, tmp_path):
    target = tmp_path / "unrelated"
    target.mkdir()
    (target / "chunk-00000.npz").write_bytes(b"not ours")
    link = tmp_path / "output"
    link.symlink_to(target, target_is_directory=True)
    base = ["--data", str(split_store), "--encoder-version", "2", "--out", str(link), "--partition", "0/2"]
    assert spr.main([*base, "--replace-incomplete"]) == 2
    assert spr.main(base) == 2
    assert link.is_symlink() and (target / "chunk-00000.npz").read_bytes() == b"not ours"
    with pytest.raises(spr.ServedPolicyRowsError, match="symlink"):
        spr.produce(link, [split_store], version=2, partition=(0, 2), replace_incomplete=True)
    for i in range(2):
        spr.produce(tmp_path / f"p{i}", [split_store], version=2, partition=(i, 2))
    with pytest.raises(spr.ServedPolicyRowsError, match="symlink"):
        spr.combine(link, [tmp_path / "p0", tmp_path / "p1"], replace_incomplete=True)
    assert link.is_symlink() and sorted(p.name for p in target.iterdir()) == ["chunk-00000.npz"]


def _tree_bytes(d: Path) -> dict[str, bytes]:
    """Every file's bytes; the summary's own ``out`` path is the one field that names the directory."""
    out = {p.name: p.read_bytes() for p in sorted(d.iterdir())}
    if "summary.json" in out:
        summary = json.loads(out["summary.json"])
        summary.pop("out")
        out["summary.json"] = json.dumps(summary, sort_keys=True).encode()
    return out


def test_an_interrupted_manifest_publication_is_never_taken_as_complete(split_store, tmp_path, monkeypatch):
    kw = dict(version=2, chunk_rows=6)
    for i in range(2):
        spr.produce(tmp_path / f"ref{i}", [split_store], partition=(i, 2), **kw)
    spr.produce(tmp_path / "p0", [split_store], partition=(0, 2), **kw)
    p0_bytes = _tree_bytes(tmp_path / "p0")

    def no_replace(*_a, **_k):
        raise OSError("interrupted before the manifest replaced into place")

    # the producer dies between the temporary manifest's fsync and its replace
    with monkeypatch.context() as m:
        m.setattr(spr.os, "replace", no_replace)
        with pytest.raises(OSError, match="interrupted"):
            spr.produce(tmp_path / "p1", [split_store], partition=(1, 2), **kw)
    names = sorted(p.name for p in (tmp_path / "p1").iterdir())
    assert spr.MANIFEST_TMP in names and "manifest.json" not in names
    with pytest.raises(spr.ServedPolicyRowsError, match="no manifest"):
        spr.combine(tmp_path / "c", [tmp_path / "p0", tmp_path / "p1"])
    spr.produce(tmp_path / "p1", [split_store], partition=(1, 2), replace_incomplete=True, **kw)
    assert _tree_bytes(tmp_path / "p1") == _tree_bytes(tmp_path / "ref1")

    # a truncated temporary manifest left by a crash mid-write is removable too
    (tmp_path / "p1" / "manifest.json").unlink()
    (tmp_path / "p1" / spr.MANIFEST_TMP).write_text('{"schema":')
    spr.produce(tmp_path / "p1", [split_store], partition=(1, 2), replace_incomplete=True, **kw)
    assert _tree_bytes(tmp_path / "p1") == _tree_bytes(tmp_path / "ref1")

    # a truncated FINAL manifest is refused, and kept for inspection
    bad = tmp_path / "bad1"
    bad.mkdir()
    for name, data in _tree_bytes(tmp_path / "ref1").items():
        (bad / name).write_bytes(data)
    (bad / "manifest.json").write_text('{"schema":')
    with pytest.raises(spr.ServedPolicyRowsError, match="not a readable manifest"):
        spr.produce(bad, [split_store], partition=(1, 2), replace_incomplete=True, **kw)
    with pytest.raises(spr.ServedPolicyRowsError, match="not a readable manifest"):
        spr.combine(tmp_path / "c", [tmp_path / "p0", bad])
    assert (bad / "manifest.json").read_text() == '{"schema":' and not (tmp_path / "c").exists()

    # combine dies the same way: its partitions are untouched, the rerun replaces only its links
    with monkeypatch.context() as m:
        m.setattr(spr.os, "replace", no_replace)
        with pytest.raises(OSError, match="interrupted"):
            spr.combine(tmp_path / "c", [tmp_path / "p0", tmp_path / "p1"])
    assert not (tmp_path / "c" / "manifest.json").exists() and (tmp_path / "c" / spr.MANIFEST_TMP).exists()
    with pytest.raises(spr.ServedPolicyRowsError, match="already exists"):
        spr.combine(tmp_path / "c", [tmp_path / "p0", tmp_path / "p1"])
    (tmp_path / "c" / spr.MANIFEST_TMP).write_text('{"schema":')
    spr.combine(tmp_path / "c", [tmp_path / "p0", tmp_path / "p1"], replace_incomplete=True)
    assert _tree_bytes(tmp_path / "p0") == p0_bytes
    assert _tree_bytes(tmp_path / "p1") == _tree_bytes(tmp_path / "ref1")
    rows = PolicyRowsStream(tmp_path / "c", version=2).n
    with pytest.raises(spr.ServedPolicyRowsError, match="never rewritten"):
        spr.combine(tmp_path / "c", [tmp_path / "p0", tmp_path / "p1"], replace_incomplete=True)
    (tmp_path / "c2").mkdir()
    (tmp_path / "c2" / "manifest.json").write_text('{"schema":')
    with pytest.raises(spr.ServedPolicyRowsError, match="not a readable manifest"):
        spr.combine(tmp_path / "c2", [tmp_path / "p0", tmp_path / "p1"], replace_incomplete=True)
    assert (tmp_path / "c2" / "manifest.json").exists()
    assert rows == sum(json.loads((tmp_path / f"p{i}" / "summary.json").read_text())["rows"] for i in range(2))


def test_a_partition_hashes_only_its_own_shards_and_still_combines_to_the_single_build(pv_store, tmp_path):
    import random
    import shutil
    from shengji.train.data import TrainDataError, discover_store
    store = tmp_path / "store"
    shutil.copytree(pv_store, store)
    assert (store / "manifest.json").is_file() and (store / "shards").is_dir()
    kw = dict(version=2, chunk_rows=40)
    single = spr.produce(tmp_path / "single", [store], **kw)
    parts = [tmp_path / f"p{i}" for i in range(2)]
    sums = [spr.produce(p, [store], partition=(i, 2), **kw) for i, p in enumerate(parts)]
    assert all(s["partition"]["shard_bytes_verified"] == "assigned" for s in sums)
    combined = spr.combine(tmp_path / "all", parts)
    for key in (*_SAME, "stores"):
        assert combined[key] == single[key], key
    assert _canonical_rows(tmp_path / "all") == _canonical_rows(tmp_path / "single")
    # a drifted shard of partition 1 stops partition 1 only: partition 0 never reads its bytes
    listed = spr._discover_listed(store).shards
    random.Random(1).shuffle(listed)
    Path(listed[1].path).chmod(0o644)
    with open(listed[1].path, "a") as fh:
        fh.write("\n")
    with pytest.raises(spr.ServedPolicyRowsError, match="sha256 drift"):
        spr.produce(tmp_path / "q1", [store], partition=(1, 2), **kw)
    assert spr.produce(tmp_path / "q0", [store], partition=(0, 2), **kw)["partition"]["all_shards_digest"] \
        == sums[0]["partition"]["all_shards_digest"]
    with pytest.raises(TrainDataError, match="sha256 drift"):
        discover_store(store)                       # the whole-store build still hashes everything
