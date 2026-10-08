"""Synthetic design witness, not an estimate of actual C12/SL migration."""
import hashlib
import json

import numpy as np
import pytest

from shengji.train.data import split_deals
from shengji.train.policy_rows import open_policy_rows
from shengji.train.policy_prior import input_dim
from shengji.train.frozen_population import SCHEMA, bind_frozen_population
from tests.test_cwv_train import store_dir, other_dir, THIRDS  # noqa: F401
from tests.test_cwv_train_policy_head import policy_rows  # noqa: F401


def manifest_of(assignment):
    manifest = {"schema": SCHEMA, **{
        part: sorted(k for k, value in assignment.items() if value == part)
        for part in ("train", "val", "test")}}
    pins = {part: hashlib.sha256("\n".join(manifest[part]).encode()).hexdigest()
            for part in ("train", "val", "test")}
    return manifest, pins


def test_value_store_addition_changes_selection_and_policy_filter(tmp_path):
    keys = ["deck:" + hashlib.sha256(str(i).encode()).hexdigest() for i in range(200)]
    ranked = sorted(keys, key=lambda k: hashlib.sha256(f"1|{k}".encode()).hexdigest())
    base, extra = ranked[:100], ranked[100:]
    before = split_deals(base, seed=1)
    after = split_deals(base + extra, seed=1)
    held_before = {k for k, part in before.items() if part != "train"}
    held_after = {k for k, part in after.items() if part != "train"}
    assert sum(before[k] != after[k] for k in base) == 30
    assert {k for k in before if before[k] == "val"} != {
        k for k in after if after[k] == "val"}

    # Same policy files, no policy rows for the added value-only stores.
    prefix = tmp_path / "policy"
    np.savez(str(prefix) + ".npz", X=np.zeros((100, input_dim(2))),
             Y=np.zeros((100, 54), dtype=np.uint8))
    meta = [{"deal_key": k, "ballot": [], "taken": [], "explore_flag": 0}
            for k in base]
    (tmp_path / "policy.meta.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in meta))
    old = open_policy_rows(prefix, exclude=held_before, version=2)
    new = open_policy_rows(prefix, exclude=held_after, version=2)
    assert old.identity["npz_sha256"] == new.identity["npz_sha256"]
    assert (old.n, new.n) == (80, 60)
    assert old.deal_keys != new.deal_keys
    assert not new.deal_keys & held_after

    manifest, pins = manifest_of(before)
    frozen = bind_frozen_population(manifest, expected_digests=pins,
                                    base_keys=base, added_keys=extra)
    assert {k: frozen[k] for k in base} == before
    assert all(frozen[k] == "train" for k in extra)
    held_frozen = {k for k, part in frozen.items() if part != "train"}
    bound = open_policy_rows(prefix, exclude=held_frozen, version=2)
    assert bound.identity == old.identity
    assert bound.deal_keys == old.deal_keys
    assert all(np.array_equal(a, b) for a, b in
               ((bound.X, old.X), (bound.Y, old.Y), (bound.explore_flag, old.explore_flag)))


@pytest.mark.parametrize("defect", ["pin", "missing", "extra", "duplicate", "collision",
                                  "overlap", "key", "schema", "empty"])
def test_frozen_population_refuses_bad_bindings(defect):
    keys = ["deck:" + hashlib.sha256(str(i).encode()).hexdigest() for i in range(20)]
    base, extra = keys[:10], keys[10:]
    manifest, pins = manifest_of(split_deals(base, seed=1))
    if defect == "pin":
        pins["val"] = "0" * 64
    elif defect == "missing":
        base = base[:-1]
    elif defect == "extra":
        base = base + extra[:1]
    elif defect == "duplicate":
        extra = extra + extra[:1]
    elif defect == "collision":
        extra = extra + manifest["val"]
    elif defect == "overlap":
        manifest["train"] += manifest["val"]
        pins["train"] = hashlib.sha256("\n".join(sorted(manifest["train"])).encode()).hexdigest()
    elif defect == "key":
        extra = ["not-a-deal"]
    elif defect == "schema":
        manifest["schema"] = "unknown"
    elif defect == "empty":
        manifest["test"] = []
        pins["test"] = hashlib.sha256(b"").hexdigest()
    with pytest.raises(ValueError):
        bind_frozen_population(manifest, expected_digests=pins,
                               base_keys=base, added_keys=extra)


def test_trainer_consumes_frozen_base_and_fit_only_addition(store_dir, other_dir, policy_rows, tmp_path):
    from shengji.train import train_cwv as tc
    kw = dict(arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=2, hidden=16, log=None, cache_workers=1, eval_workers=1,
              cache_dir=str(tmp_path / "cache"), bench_batch=8,
              val_rank_records=50, encoder_version=2, policy_head=True,
              policy_rows=policy_rows, **THIRDS)
    base = tc.train(data=[str(store_dir)], out=tmp_path / "base", **kw)
    manifest = {"schema": SCHEMA, **{p: base["population"][p] for p in ("train", "val", "test")}}
    contract = {"schema": "shengji-frozen-training-contract-v1", "population": manifest,
                "digests": base["population"]["digest"], "added_stores": [str(other_dir)],
                "candidates": {p: base["final"][p]["search_facing"]["candidate_set"]["digest"]
                               for p in ("val", "test")},
                "policy_identity": base["policy_head"]["rows"]}
    path = tmp_path / "frozen.json"
    raw = json.dumps(contract).encode()
    path.write_bytes(raw)
    pin = hashlib.sha256(raw).hexdigest()
    result = tc.train(data=[str(store_dir), str(other_dir)], out=tmp_path / "bound",
                      frozen_population=str(path), frozen_population_sha256=pin, **kw)
    for part in ("val", "test"):
        assert result["population"][part] == base["population"][part]
        assert result["final"][part]["search_facing"]["candidate_set"]["digest"] == contract["candidates"][part]
    assert set(base["population"]["train"]) < set(result["population"]["train"])
    assert result["policy_head"]["rows"] == base["policy_head"]["rows"]
    assert result["config"]["frozen_population"]["sha256"] == pin
    assert "frozen_population" not in base["config"]
    contract["candidates"]["test"] = "0" * 64
    raw = json.dumps(contract).encode()
    path.write_bytes(raw)
    with pytest.raises(tc.TrainError, match="test: frozen candidate digest mismatch"):
        tc.train(data=[str(store_dir), str(other_dir)], out=tmp_path / "refused",
                 frozen_population=str(path), frozen_population_sha256=hashlib.sha256(raw).hexdigest(), **kw)
    assert not (tmp_path / "refused" / "checkpoints" / "epoch-01.pt").exists()


def test_frozen_cli_pair_and_early_hash_refusal(tmp_path):
    from shengji.train import train_cwv as tc
    args = tc.build_parser().parse_args(["train", "--data", "absent", "--out", str(tmp_path),
        "--frozen-population", "contract.json", "--frozen-population-sha256", "f" * 64])
    assert args.frozen_population == "contract.json"
    with pytest.raises(tc.TrainError, match="supplied together"):
        tc.train(data=["absent"], out=tmp_path, frozen_population="absent")


@pytest.mark.parametrize("payload,pin", [
    (b"{}", "0" * 64),
    (b'{"schema":1,"schema":2}', None),
    (b"[]", None),
    (b"not json", None),
])
def test_contract_rejects_unpinned_or_malformed_input(tmp_path, payload, pin):
    from shengji.train.frozen_population import load_contract
    path = tmp_path / "bad.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        load_contract(path, pin or hashlib.sha256(payload).hexdigest())


def test_policy_identity_guard_rejects_count_or_digest_drift():
    from shengji.train.frozen_population import require_policy_identity
    identity = {"rows_used": 80, "fit_deals_digest": "a" * 64}
    require_policy_identity({"policy_identity": identity}, dict(identity))
    for changed in ({**identity, "rows_used": 81},
                    {**identity, "fit_deals_digest": "b" * 64}):
        with pytest.raises(ValueError, match="effective policy rows differ"):
            require_policy_identity({"policy_identity": identity}, changed)
