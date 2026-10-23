import json
from pathlib import Path

import pytest

from shard_store import ShardStore


def test_roundtrip_is_reusable_and_ordered(tmp_path):
    outputs = ("candidate-a", "comparator-a")
    with ShardStore(outputs, tmp_path) as store:
        assert tuple(store) == outputs and len(store) == 2
        store.add(outputs[0], 2, json.dumps({"cluster": 2}).encode())
        store.add(outputs[0], 0, json.dumps({"cluster": 0}).encode())
        store.add(outputs[1], 1, json.dumps({"cluster": 1}).encode())
        assert list(store[outputs[0]]) == [{"cluster": 0}, {"cluster": 2}]
        assert list(store[outputs[0]]) == [{"cluster": 0}, {"cluster": 2}]
        assert list(store[outputs[1]]) == [{"cluster": 1}]
        directory = store.directory
        assert directory.is_dir()
    assert not directory.exists()


@pytest.mark.parametrize("output, cluster, data, match", [
    ("unknown", 0, b"{}", "unknown"),
    ("candidate", -1, b"{}", "0..519"),
    ("candidate", 520, b"{}", "0..519"),
    ("candidate", True, b"{}", "0..519"),
    ("candidate", 0, "{}", "bytes"),
])
def test_rejects_invalid_inserts(tmp_path, output, cluster, data, match):
    with ShardStore(("candidate",), tmp_path) as store:
        with pytest.raises((KeyError, ValueError, TypeError), match=match):
            store.add(output, cluster, data)


def test_duplicate_is_rejected_and_store_survives(tmp_path):
    with ShardStore(("candidate",), tmp_path) as store:
        store.add("candidate", 0, b'{"ok": true}')
        with pytest.raises(ValueError, match="duplicate"):
            store.add("candidate", 0, b'{"ok": false}')
        assert list(store["candidate"]) == [{"ok": True}]


def test_unknown_keys_and_close_are_safe(tmp_path):
    store = ShardStore(("candidate",), tmp_path)
    directory = store.directory
    with pytest.raises(KeyError):
        store["other"]
    store.close()
    assert not directory.exists()
    with pytest.raises(ValueError, match="closed"):
        store.add("candidate", 0, b"{}")


def test_exception_context_cleans_private_directory(tmp_path):
    directory = None
    with pytest.raises(RuntimeError):
        with ShardStore(("candidate",), tmp_path) as store:
            directory = store.directory
            raise RuntimeError("abort")
    assert directory is not None and not directory.exists()

