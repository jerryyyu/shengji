"""Synthetic design witness, not an estimate of actual C12/SL migration."""
import hashlib
import json

import numpy as np
import pytest

from shengji.train.data import split_deals
from shengji.train.policy_rows import open_policy_rows
from shengji.train.policy_prior import input_dim
from shengji.train.frozen_population import SCHEMA, bind_frozen_population


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
