"""Focused witnesses for the CWV training receipt cache membership index."""
from __future__ import annotations

import ast
import inspect
import json
from dataclasses import dataclass

from shengji.train import train_cwv


@dataclass(frozen=True)
class _Shard:
    sha256: object


@dataclass
class _Store:
    name: str
    shards: list[_Shard]

    def describe(self) -> dict:
        return {"name": self.name, "shards": [s.sha256 for s in self.shards]}


def test_cache_membership_matches_nested_reference_with_overlap_and_duplicates():
    shared = _Shard("shared")
    stores = [
        _Store("first", [_Shard("a"), shared, shared]),
        _Store("second", [shared, _Shard("b")]),
        _Store("empty", []),
    ]
    cache_files = [
        {"shard_sha256": "b", "ordinal": 0},
        {"shard_sha256": "shared", "ordinal": 1},
        {"shard_sha256": "a", "ordinal": 2},
        {"shard_sha256": "shared", "ordinal": 3},
        {"shard_sha256": "missing", "ordinal": 4},
        {"shard_sha256": "b", "ordinal": 5},
    ]

    expected = [
        [cache for cache in cache_files
         if any(cache["shard_sha256"] == shard.sha256 for shard in store.shards)]
        for store in stores
    ]
    actual = [train_cwv.cache_files_for_store(cache_files, store.shards)
              for store in stores]

    assert actual == expected
    assert [cache["ordinal"] for cache in actual[0]] == [1, 2, 3]
    assert [cache["ordinal"] for cache in actual[1]] == [0, 1, 3, 5]
    assert actual[2] == []
    # Repeated cache records remain repeated record objects, not deduplicated.
    assert actual[0][0] is cache_files[1] and actual[0][2] is cache_files[3]


def test_training_data_receipt_wiring_calls_index_and_preserves_serialized_shape(
        monkeypatch):
    stores = [_Store("first", [_Shard("a")]), _Store("empty", [])]
    cache_files = [{"shard_sha256": "a", "ordinal": 0}]
    prepared = type("PreparedStub", (), {"stores": stores, "cache_files": cache_files})()
    calls = []
    original = train_cwv.cache_files_for_store

    def spy(files, shards):
        calls.append((files, shards))
        return original(files, shards)

    monkeypatch.setattr(train_cwv, "cache_files_for_store", spy)
    actual = train_cwv._training_data_receipt(prepared)
    expected = [
        {**store.describe(), "cache": [cache for cache in cache_files
                                         if any(cache["shard_sha256"] == shard.sha256
                                                for shard in store.shards)]}
        for store in stores
    ]

    assert len(calls) == len(stores)
    assert [shards for _files, shards in calls] == [store.shards for store in stores]
    assert json.dumps(actual) == json.dumps(expected)

    # The production train() receipt must invoke the seam; a helper-only test
    # would not catch a disconnected optimization.
    tree = ast.parse(inspect.getsource(train_cwv.train))
    assert any(isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name)
               and node.func.id == "_training_data_receipt"
               for node in ast.walk(tree))


def test_cache_membership_hash_work_is_linear_in_inputs():
    class HashProbe:
        hashes = 0

        def __init__(self, value):
            self.value = value

        def __hash__(self):
            type(self).hashes += 1
            return hash(self.value)

        def __eq__(self, other):
            return isinstance(other, HashProbe) and self.value == other.value

    shards = [_Shard(HashProbe(f"shard-{i}")) for i in range(17)]
    cache_files = [{"shard_sha256": HashProbe(f"cache-{i}")} for i in range(23)]
    HashProbe.hashes = 0

    assert train_cwv.cache_files_for_store(cache_files, shards) == []
    assert HashProbe.hashes == len(shards) + len(cache_files)
