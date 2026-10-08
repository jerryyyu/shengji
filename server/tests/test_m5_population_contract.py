"""Synthetic design witness, not an estimate of actual C12/SL migration."""
import hashlib
import json

import numpy as np

from shengji.train.data import split_deals
from shengji.train.policy_rows import open_policy_rows
from shengji.train.policy_prior import input_dim


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
