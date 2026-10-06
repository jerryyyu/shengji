import copy
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from shengji.eval import s11_manifest
from shengji.eval.s11_manifest import select_manifest_shards
from shengji.eval.s11_selection import select_deals, select_mirror
from shengji.harvest.trajectory import build_run_manifest


@pytest.fixture
def manifest(tmp_path):
    """Exercise the actual producer schema; no games, corpora or models."""
    (tmp_path / "shards").mkdir()
    sidecars = {}
    for cluster in range(80):
        # Synthetic sidecar files are needed only for the producer's digest.
        (tmp_path / "shards" / f"cluster-{cluster:06d}.json").write_text("{}")
        sidecars[cluster] = {
            "seed": 7000 + cluster, "path": f"shards/cluster-{cluster:06d}.jsonl",
            "sha256": hashlib.sha256(str(cluster).encode()).hexdigest(),
            "bytes": 1000 + cluster, "records": 100 + cluster,
            "counts": {"rounds": 2}, "work": {},
        }
    return build_run_manifest(
        {"run_id": "synthetic", "seed0": 7000, "round_mix": "first"}, {},
        rounds=160, sidecars=sidecars, merged=None, out_dir=tmp_path,
    )


def encode(manifest):
    raw = json.dumps(manifest).encode()
    return raw, hashlib.sha256(raw).hexdigest()


def test_producer_inventory_flows_into_full_frame_selector(manifest):
    raw, sha = encode(manifest)
    schedule = select_manifest_shards(raw, sha256=sha)
    assert len(schedule) == len({s.seed for s in schedule}) == 64
    assert [s.seed for s in schedule] == select_deals(sha, list(range(7000, 7080)))
    assert [s.draw_index for s in schedule] == list(range(64))
    for s in schedule:
        source = manifest["shards"][s.cluster]
        assert (s.manifest_sha256, s.run_id, s.mirror) == (
            sha, "synthetic", select_mirror(sha, s.seed))
        assert (s.path, s.sha256, s.byte_count, s.record_count) == (
            source["path"], source["sha256"], source["bytes"], source["records"])
    assert select_manifest_shards(raw, sha256=sha) == schedule
    with pytest.raises(FrozenInstanceError):
        schedule[0].seed = 999


def test_authentication_precedes_json(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("JSON parser accessed before authentication")
    monkeypatch.setattr(s11_manifest.json, "loads", forbidden)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        select_manifest_shards(b"not JSON", sha256="0" * 64)


@pytest.mark.parametrize("change", [
    lambda m: m.update(schema="unknown"),
    lambda m: m.update(record_schema="unknown"),
    lambda m: m.update(source="room"),
    lambda m: m.update(run_id="bad:run"),
    lambda m: m.update(run_id=""),
    lambda m: m.update(seed0=True),
    lambda m: m.update(seed0=-1),
    lambda m: m.update(clusters=True),
    lambda m: m.update(clusters=63),
    lambda m: m.update(rounds=159),
    lambda m: m.update(rounds=160.0),
    lambda m: m["config"].update(seed0=7001),
    lambda m: m["config"].update(run_id="other"),
    lambda m: m.update(config=[]),
    lambda m: m["shards"].pop(),
    lambda m: m["shards"].reverse(),
    lambda m: m["shards"][0].update(cluster=True),
    lambda m: m["shards"][1].update(cluster=0),
    lambda m: m["shards"][1].update(seed=7000),
    lambda m: m["shards"][1].update(seed=7001.0),
    lambda m: m["shards"][1].update(path="../cluster-000001.jsonl"),
    lambda m: m["shards"][1].update(path="/shards/cluster-000001.jsonl"),
    lambda m: m["shards"][1].update(path="shards/cluster-1.jsonl"),
    lambda m: m["shards"][1].update(sha256="A" * 64),
    lambda m: m["shards"][1].update(bytes=0),
    lambda m: m["shards"][1].update(records=True),
    lambda m: m["shards"].__setitem__(1, None),
])
def test_invalid_full_inventory_refuses_before_selection(manifest, change, monkeypatch):
    change(manifest)
    def forbidden(*args, **kwargs):
        pytest.fail("selected from an invalid inventory")
    monkeypatch.setattr(s11_manifest, "select_deals", forbidden)
    raw, sha = encode(manifest)
    with pytest.raises(ValueError):
        select_manifest_shards(raw, sha256=sha)


def test_invalid_unselected_entry_is_not_silently_skipped(manifest, monkeypatch):
    raw, sha = encode(manifest)
    selected = {s.cluster for s in select_manifest_shards(raw, sha256=sha)}
    unselected = next(i for i in range(80) if i not in selected)
    manifest["shards"][unselected]["records"] = 0
    raw, sha = encode(manifest)
    with pytest.raises(ValueError, match="records"):
        select_manifest_shards(raw, sha256=sha)


@pytest.mark.parametrize("raw", [
    b'{"schema":1,"schema":2}', b'{"nested":{"x":1,"x":2}}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'[]',
])
def test_ambiguous_or_nonfinite_json_refuses(raw):
    with pytest.raises(ValueError):
        select_manifest_shards(raw, sha256=hashlib.sha256(raw).hexdigest())


def test_outcomes_cannot_filter_schedule(manifest, monkeypatch):
    # Outcomes affect the frozen digest, but must never filter its seed list.
    manifest["counts"] = {"wins": 0, "failures": 999}
    manifest["work_realized"] = {"anything": -123}
    for shard in manifest["shards"]:
        shard["attacker_points"] = -999
    seen = []
    actual = s11_manifest.select_deals
    def select(sha, seeds):
        seen.append(copy.copy(seeds))
        return actual(sha, seeds)
    monkeypatch.setattr(s11_manifest, "select_deals", select)
    raw, sha = encode(manifest)
    assert len(select_manifest_shards(raw, sha256=sha)) == 64
    assert seen == [list(range(7000, 7080))]
