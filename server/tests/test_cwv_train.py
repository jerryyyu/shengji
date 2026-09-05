"""Complete-world value net (cwv_train_spec): six witnesses, each with a
mutation that turns it RED.

1. Bridge round trip on a tiny store + 3 Luna private rows: every row
   rebuilds to a complete round accepted by ``_validate_complete_round``
   and the world tensor conserves the 108-card deck (RED: a dropped hand).
2. The world tensor carries the hidden hands: permuting hidden cards among
   the non-acting seats CHANGES the encoding while the public tensor stays
   byte-identical (RED: a zeroed world tensor).
3. Split by deal: no deal in two splits (RED: splitting by record).
4. The target mapping equals ``value_afterstate``'s and maps exactly onto
   the record's PT0 utility (RED: a flipped sign).
5. Candidate-ranking agreement on a record with 3 candidates and known
   search means (RED: candidates scored from the wrong perspective).
6. Training smoke on CPU: a receipt with every required field, a
   checkpoint that loads through ``value_checkpoint`` and whose
   ``value_inference.predict_round`` equals the training-side forward
   (RED: a checkpoint that drops ``arch``).

Pure engine + CPU torch; two tiny shard stores are generated here at
reduced work (N=2 selection worlds, R=30 report worlds).
"""
from __future__ import annotations

import json
import random

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.harvest import rebuild, trajectory  # noqa: E402
from shengji.harvest.common import write_jsonl  # noqa: E402
from shengji.harvest.schema import finalize_record, split_record  # noqa: E402
from shengji.rl import value_afterstate  # noqa: E402
from shengji.rl.value_afterstate import (  # noqa: E402
    ValueAfterstateError,
    ValueAfterstateTensors,
    category_signed_level,
    signed_level_category,
    tensors_from_round,
)
from shengji.rl.value_checkpoint import load_checkpoint  # noqa: E402
from shengji.rl.value_inference import predict_round, predict_tensors  # noqa: E402
from shengji.train import cwv_data, cwv_eval, train_cwv, train_v0  # noqa: E402
from shengji.train.data import TrainDataError, discover_store  # noqa: E402

SEED0 = 4_100_000
ROUNDS = 6
WORK = {"select_worlds": 2, "report_worlds": 30}
EXPLORE = {"explore_rate": 0.5, "explore_k": 2}
N_LUNA = 3
THIRDS = dict(val_fraction=1 / 3, test_fraction=1 / 3)     # 3 deals -> 1 / 1 / 1


@pytest.fixture(scope="module")
def store_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("cwv-traj") / "run"
    trajectory.generate(rounds=ROUNDS, seed0=SEED0, out_dir=out, workers=1, merge=False,
                        **WORK, **EXPLORE)
    return out


@pytest.fixture(scope="module")
def other_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("cwv-other") / "run"
    trajectory.generate(rounds=2, seed0=SEED0 + 7_777, out_dir=out, workers=1, merge=False,
                        **WORK, **EXPLORE)
    return out


def _records(store_dir):
    manifest = json.loads((store_dir / "manifest.json").read_text())
    recs = []
    for shard in manifest["shards"]:
        recs += [json.loads(line)
                 for line in (store_dir / shard["path"]).read_text().splitlines()]
    return recs


@pytest.fixture(scope="module")
def records(store_dir):
    recs = _records(store_dir)
    assert len(recs) > 200
    return recs


@pytest.fixture(scope="module")
def other_records(other_dir):
    return _records(other_dir)


def _luna_rows(records, n=N_LUNA):
    """Luna-like private rows: hidden hands + deck, a wide ballot, no search
    evidence (only the played action is known)."""
    rng = random.Random(3)
    picks = rng.sample([r for r in records if len(r["ballot"]) >= 2 and r["ply"] > 0], n)
    rows = []
    for r in picks:
        rnd = rebuild.state_for_record(r)
        _, cluster, mirror, _, ply = r["source_ref"].split(":")
        fields = {k: v for k, v in r.items()
                  if k not in ("record_sha256", "preference", "allocation",
                               "action_values", "exploration", "production_ballot")}
        fields.update(
            source="luna-rpc", policy="gpt-5.6-luna", round_seed=None,
            source_ref=(f"pt-luna-test/attempts/{cluster}-mirror-{mirror}/"
                        f"trajectory.json#event-{ply}"),
            allocation=None, action_values=None, authority=None,
            hidden_hands=rebuild.hands_snapshot(rnd))
        _public, private = split_record(finalize_record(fields))
        rows.append(private)
    return rows


@pytest.fixture(scope="module")
def luna(tmp_path_factory, other_records):
    rows = _luna_rows(other_records)
    path = tmp_path_factory.mktemp("cwv-luna") / "luna-test.private.jsonl"
    write_jsonl(path, rows, private=True)
    return path, rows


@pytest.fixture(scope="module")
def blocks(store_dir, tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp("cwv-cache")
    store = discover_store(store_dir)
    built = cwv_data.ensure_caches([(s, False) for s in store.shards], cache_dir, workers=1)
    assert all(rebuilt for _meta, rebuilt in built)
    return [cwv_data.load_block(cwv_data.cache_path(cache_dir, s.sha256), shard_sha256=s.sha256)
            for s in store.shards]


# 1 ------------------------------------------------------ bridge round trip

def test_bridge_round_trip_complete_world(records, luna):
    _path, luna_rows = luna
    rows = records + luna_rows
    assert len(luna_rows) == N_LUNA
    for record in rows:
        row = cwv_data.bridge_record(record)
        # the reached state is a complete round: #214's own validation accepts it
        value_afterstate._validate_complete_round(row.successor)
        assert cwv_data.world_conservation(row.tensors, row.successor)
        # the uint8 planes rebuild the world tensor exactly
        planes = np.rint(row.tensors.world * 2.0).astype(np.uint8)
        assert np.array_equal(planes.astype(np.float32) * 0.5, row.tensors.world)
        # the binding IS example_from_trajectory_record's (input hash, target, deal)
        cwv_data.reference_check(record, row)
        assert row.deal_key.startswith("deck:")
    # the decision state itself is not a #214 tensor for the first play of
    # a round (no history event): the afterstate view is forced
    first = next(r for r in records if r["ply"] == 0)
    with pytest.raises(ValueAfterstateError, match="history tensor length"):
        tensors_from_round(rebuild.state_for_record(first), first["seat"])
    # RED: a dropped hand breaks deck conservation, in the engine check and
    # in the world-tensor check alike
    row = cwv_data.bridge_record(records[10])
    dropped = row.successor
    victim = next(s for s in range(4) if s != row.seat and dropped.hands[s])
    hidden = list(dropped.hands[victim])
    dropped.hands[victim] = []
    with pytest.raises(ValueAfterstateError, match="physical deck conservation"):
        value_afterstate._validate_complete_round(dropped)
    dropped.hands[victim] = hidden
    world = row.tensors.world.copy()
    relative = (victim - row.seat) % 4
    world[relative] = 0.0
    bad = ValueAfterstateTensors(row.tensors.public, row.tensors.history, world,
                                 row.tensors.perspective)
    assert not cwv_data.world_conservation(bad, row.successor)


# 2 ------------------------------------------- the world carries hidden hands

def _zeroed_world(rnd, seat):
    t = tensors_from_round(rnd, seat)
    return ValueAfterstateTensors(t.public, t.history, np.zeros_like(t.world), t.perspective)


def test_world_tensor_carries_hidden_hands(records, monkeypatch, tmp_path, store_dir):
    picks = [r for r in records if 5 <= r["ply"] <= 80][:6]
    assert len(picks) == 6
    conclusive = 0
    for record in picks:
        row = cwv_data.bridge_record(record)
        result = cwv_data.world_witness(row.successor, row.seat, random.Random(1), trials=3)
        cwv_data.check_witness(result)
        assert result["public_changed"] == 0          # the public head's boundary holds
        conclusive += result["trials"] - result["inconclusive"]
        assert result["world_changed"] == result["trials"] - result["inconclusive"]
        # the round is restored
        assert cwv_data.bridge_record(record).input_sha256 == row.input_sha256
    assert conclusive > 0
    # RED: an encoder whose world tensor is zeroed does not see the permutation
    row = cwv_data.bridge_record(picks[0])
    result = cwv_data.world_witness(row.successor, row.seat, random.Random(1), trials=3,
                                    encoder=_zeroed_world)
    assert result["world_changed"] == 0 and result["trials"] - result["inconclusive"] > 0
    with pytest.raises(TrainDataError, match="does not carry the hidden hands"):
        cwv_data.check_witness(result)
    # and the cache build refuses such an encoder, leaving no file
    store = discover_store(store_dir)
    monkeypatch.setattr(cwv_data, "world_witness",
                        lambda *a, **k: {"trials": 2, "world_changed": 0,
                                         "public_changed": 0, "inconclusive": 0})
    with pytest.raises(TrainDataError, match="does not carry the hidden hands"):
        cwv_data.build_cache(store.shards[0], tmp_path / "red")
    assert not list((tmp_path / "red").glob("*.npz")) if (tmp_path / "red").exists() else True


# 3 ------------------------------------------------------------ split by deal

def test_split_by_deal_witness(blocks):
    keys = sorted({k for b in blocks for k in b.deal_key.tolist()})
    assert len(keys) == 3
    assignment = cwv_data.split_deals(keys, seed=1, **THIRDS)
    counts = cwv_data.assert_split_by_deal(blocks, cwv_data.deal_assignment(assignment))
    assert counts == {"train": 1, "val": 1, "test": 1}
    parts = {part: {k for k, v in assignment.items() if v == part} for part in counts}
    assert not (parts["train"] & parts["val"]) and not (parts["train"] & parts["test"]) \
        and not (parts["val"] & parts["test"])
    # both mirrors of a cluster are one deal: every block holds exactly one key
    assert all(np.unique(b.deal_key).size == 1 for b in blocks)
    # RED: an assignment by record (row parity) splits every deal
    with pytest.raises(TrainDataError, match="must never be split"):
        cwv_data.assert_split_by_deal(
            blocks, lambda b: np.where(np.arange(b.n) % 2 == 0, "train", "test"))


# 4 ---------------------------------------------------------- target mapping

def test_target_mapping_matches_value_afterstate(records):
    for points in (0, 5, 39, 40, 79, 80, 95, 119, 120, 159, 160, 200, 240, 400):
        for attacker in (True, False):
            category = cwv_data.target_category(points, attacker)
            assert category == signed_level_category(points, attacker)
            level = category_signed_level(category)
            # the exact PT0 utility of that category is the record's convention
            pt0 = rebuild.signed_level_utility(points, banker_seat=1,
                                               perspective_seat=0 if attacker else 1)
            assert cwv_data.pt0_level(level) == pt0
            assert np.sign(level) == np.sign(pt0)
            one_hot = np.zeros(value_afterstate.OUTCOME_CLASSES)
            one_hot[category] = 1.0
            expected_level, expected_pt0 = cwv_data.expected_levels(one_hot[None, :])
            assert expected_level[0] == level and expected_pt0[0] == pt0
            # RED: the flipped perspective negates the utility
            assert cwv_data.pt0_level(category_signed_level(
                cwv_data.target_category(points, not attacker))) == -pt0
    # RED through the bridge: a record whose stored utility has the wrong
    # sign is refused (the mapping is checked on every cached row)
    record = dict(records[3])
    record["outcome"] = {**record["outcome"],
                         "signed_level_utility": -record["outcome"]["signed_level_utility"]}
    with pytest.raises(TrainDataError, match="utility_mismatch"):
        cwv_data.bridge_record(finalize_record(record))


# 5 ------------------------------------------------------ ranking agreement

def _oracle(entry, *, respect_perspective=True):
    """Signed successor attacker points from the acting team's view (the
    'value' of a hand-built scorer); the mutation ignores the perspective."""
    points = entry["successor_points"].astype(np.float64)
    if not respect_perspective:
        return points
    return np.where(entry["perspective"].astype(bool), points, -points)


def test_ranking_agreement_metric(records):
    # a defender's decision whose three candidates reach three distinct
    # point totals: the known search means are the oracle's own values
    chosen = None
    for record in records:
        if record["role"] != "banker-team" or len(record["ballot"]) < 3:
            continue
        rnd = rebuild.state_for_record(record)
        scored = cwv_eval.score_candidates(rnd, record["seat"], record["ballot"][:3])
        if np.unique(scored["successor_points"]).size == 3 and not scored["terminal"].any():
            chosen = (record, rnd, scored)
            break
    assert chosen is not None, "no defender decision with three distinct outcomes"
    record, rnd, scored = chosen
    assert not scored["perspective"].any()            # a defender's perspective
    means = _oracle(scored)
    agreement = cwv_eval.candidate_agreement(_oracle(scored), means)
    assert agreement == {"spearman": 1.0, "top1": 1.0, "regret": 0.0, "candidates": 3}
    # the metric on hand-built scores: a reversed ranking, ties, regret
    assert cwv_eval.candidate_agreement([1.0, 2.0, 3.0], [3.0, 1.0, 2.0])["spearman"] == \
        pytest.approx(-0.5)
    tied = cwv_eval.candidate_agreement([1.0, 1.0, 1.0], [3.0, 1.0, 2.0])
    assert tied["spearman"] is None and tied["top1"] == pytest.approx(1 / 3) \
        and tied["regret"] == pytest.approx(1.0)
    # RED: scoring from the wrong perspective (unsigned points for a
    # defender) reverses the ranking and misses the search's best candidate
    wrong = cwv_eval.candidate_agreement(_oracle(scored, respect_perspective=False), means)
    assert wrong["spearman"] == -1.0 and wrong["top1"] == 0.0 and wrong["regret"] > 0
    # and the engine refuses to apply the candidates for a seat that is not to move
    with pytest.raises(ValueAfterstateError, match="actor's play decision"):
        cwv_eval.score_candidates(rnd, (record["seat"] + 1) % 4, record["ballot"][:3])
    # the summary carries deal-bootstrap CIs
    summary = cwv_eval.summarize_agreement([agreement, wrong], ["d1", "d2"], n_boot=20, seed=1)
    assert summary["n"] == 2 and summary["top1"]["mean"] == pytest.approx(0.5)


# 6 --------------------------------------------------------- training smoke

def test_training_smoke_receipt_and_checkpoint_api(store_dir, luna, tmp_path):
    luna_path, _rows = luna
    public = train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu",
                            epochs=1, seed=7, batch_size=64, n_boot=10, log=None,
                            cache_workers=1, **THIRDS)
    assert public["final"]["test"]["held_out"] is True
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=2, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    out = tmp_path / "a"
    receipt = train_cwv.train(out=out, **kw)
    for key in train_cwv.REQUIRED_RECEIPT_FIELDS:
        assert key in receipt, key
    assert receipt["schema"] == train_cwv.RECEIPT_SCHEMA and receipt["command"] == "train"
    assert receipt["sees_hidden_hands"] is True and receipt["privacy"]["sees_hidden_hands"]
    assert receipt["encoder"]["implementation_sha256"] == \
        cwv_data.cwv_encoder_identity()["implementation_sha256"]
    split = receipt["split"]
    assert (split["train_deals"], split["val_deals"], split["test_deals"]) == (1, 1, 1)
    assert receipt["population"]["counts"] == {"train": 1, "val": 1, "test": 1}
    assert receipt["counts"]["records"]["skipped"] == {k: 0 for k in cwv_data.SKIP_REASONS}
    assert receipt["counts"]["records"]["world_witness"]["public_changed"] == 0
    assert receipt["counts"]["records"]["reference_checked"] >= 3
    assert len(receipt["epochs"]) == 2 and receipt["selection"]["split"] == "val"
    test = receipt["final"]["test"]
    assert test["held_out"] is True and test["value"]["n"] == split["test_records"]
    assert test["value"]["model"]["mae"] >= 0 and test["value"]["stratified_prior"]["mae"] >= 0
    assert test["public_head"]["n"] == split["test_records"]
    assert "paired_diff_model_minus_public" in test["public_head"]
    assert test["public_head"]["public_head_has_population"] is True
    assert len(test["reliability"]["pt0"]) <= 10 and test["reliability"]["bins"] == 10
    ranking = test["ranking"]
    assert ranking["records"] > 0 and set(ranking["scorers"]) == set(cwv_eval.SCORERS)
    assert 0 <= ranking["scorers"]["cwv"]["top1"]["mean"] <= 1
    luna_block = receipt["final"]["luna"]
    assert luna_block["held_out"] is True and luna_block["value"]["n"] == N_LUNA
    assert luna_block["public_head"]["n"] == N_LUNA
    assert receipt["luna"]["shared_deals_with_training"] == 0
    assert receipt["inference_benchmark"]["batch"] == 32
    assert receipt["inference_benchmark"]["forward_positions_per_second"] > 0
    assert receipt["view"] == cwv_data.VIEW
    assert (out / "receipt.json").is_file() and (out / "best.pt").is_file()
    # the checkpoint loads through #214's API unchanged, with the metadata
    model, metadata = load_checkpoint(out / "best.pt")
    assert metadata["arch"] == "mlp" and metadata["sees_hidden_hands"] is True
    assert metadata["population"]["counts"] == {"train": 1, "val": 1, "test": 1}
    assert model.config.architecture == "mlp"
    loaded, _meta, aux = train_cwv.load_cwv_checkpoint(out / "best.pt")
    assert aux is None
    # value_inference.predict_round on the rebuilt afterstate equals the
    # training-side forward on the cached row
    cache_dir = out / "cache"
    store = discover_store(store_dir)
    block = cwv_data.load_block(cwv_data.cache_path(cache_dir, store.shards[0].sha256))
    record = next(r for r in _records(store_dir) if r["source_ref"] == block.source_ref[5])
    row = cwv_data.bridge_record(record)
    assert row.input_sha256 == block.input_sha256[5].decode()
    prediction = predict_round(loaded, row.successor, row.seat)
    batch = cwv_data.tensors_of(cwv_data.collate(block, np.asarray([5])), "cpu")
    with torch.no_grad():
        logits, _aux = train_cwv.forward_batch(loaded, batch)
    level, _pt0 = cwv_data.expected_levels(torch.softmax(logits, dim=1).numpy())
    assert prediction.expected_signed_level == pytest.approx(level[0], abs=1e-5)
    assert predict_tensors(loaded, [row.tensors])[0].probability == prediction.probability
    # evaluate reproduces the checkpoint's TEST and Luna metrics
    ev = train_cwv.evaluate(checkpoint=str(out / "best.pt"), out=tmp_path / "e",
                            data=[str(store_dir)], eval_luna=str(luna_path), device="cpu",
                            n_boot=20, cache_dir=str(cache_dir), cache_workers=1,
                            eval_workers=1, bench_batch=8, log=None)
    assert ev["final"]["test"]["value"]["model"] == test["value"]["model"]
    assert ev["final"]["luna"]["value"]["model"] == luna_block["value"]["model"]
    assert ev["final"]["test"]["ranking"]["scorers"]["cwv"]["top1"]["mean"] == \
        ranking["scorers"]["cwv"]["top1"]["mean"]
    # RED: a checkpoint that drops ``arch`` is refused (the #214 container
    # itself still loads: the metadata is opaque to it)
    payload = torch.load(out / "best.pt", weights_only=True)
    payload["metadata"].pop("arch")
    torch.save(payload, tmp_path / "no-arch.pt")
    load_checkpoint(tmp_path / "no-arch.pt")
    with pytest.raises(train_v0.TrainError, match="arch"):
        train_cwv.load_cwv_checkpoint(tmp_path / "no-arch.pt")
    # the seq architecture cannot carry the aux head; the config refuses
    with pytest.raises(train_v0.TrainError, match="aux-points"):
        train_cwv.build_config(data=[str(store_dir)], arch="seq", aux_points=True)
