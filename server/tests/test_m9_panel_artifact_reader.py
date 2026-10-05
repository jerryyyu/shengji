import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from shengji.eval import m9_panel_artifact_reader as reader
from shengji.eval import m9_panel_persistence as persistence
from shengji.eval import m9_panel_worker as worker
from shengji.eval.m9_panel_plan import ROOTS
from shengji.eval.m9_panel_readout import summarize_m9_panels
from test_m9_panel_completion import receipts
from test_m9_panel_readout import _records


def bundle(monkeypatch, tmp_path):
    analysis, records = _records()
    calls = []
    def collect(*args, **kwargs):
        index = len(calls)
        calls.append(index)
        return copy.deepcopy(records[index]["panel"])
    monkeypatch.setattr(worker, "collect_public_fixture_panel", collect)
    output = tmp_path / "collection"
    persistence.run_m9_panel_collection(
        analysis, [SimpleNamespace(id=root, seat=0) for root in ROOTS],
        lambda _: pytest.fail("no model permitted"), output_dir=output)
    assert calls == list(range(15))
    owner, process, _ = receipts()
    files = {}
    for name, value in (("owner", owner), ("process", process),
                        ("saved_readout", {"analysis": analysis, "provenance": {}})):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value, allow_nan=False))
        files[name] = path
    files.update(collection=output / "terminal.json", plan=output / "plan.json")
    files.update({f"validated-{i:03d}.json": output / f"validated-{i:03d}.json"
                  for i in range(15)})
    pins = {name: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, path in files.items()}
    return pins, analysis, records


def rewrite(pins, name, value):
    from pathlib import Path
    raw = json.dumps(value, allow_nan=False).encode()
    path = Path(pins[name]["path"]).with_name(f"changed-{name}.json")
    path.write_bytes(raw)
    pins[name]["path"] = str(path)
    pins[name]["sha256"] = hashlib.sha256(raw).hexdigest()


def test_real_publisher_to_authenticated_disk_reader(monkeypatch, tmp_path):
    pins, analysis, records = bundle(monkeypatch, tmp_path)
    before = copy.deepcopy(pins)
    opens = []
    stable = reader.guards._stable_read
    def track(path, limit):
        opens.append(str(path))
        return stable(path, limit)
    monkeypatch.setattr(reader.guards, "_stable_read", track)
    result = reader.read_m9_panel_files(pins, packet_sha256="a" * 64)
    assert result["analysis"] == summarize_m9_panels(analysis, records)
    assert result["input_sha256"] == {name: entry["sha256"] for name, entry in pins.items()}
    assert result["provenance_verified"] is False
    assert len(opens) == len(set(opens)) == 20
    assert pins == before


@pytest.mark.parametrize("bad", ["failed_owner", "failed_process", "bad_plan", "bad_pin"])
def test_metadata_failure_prevents_panel_open(monkeypatch, tmp_path, bad):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    if bad == "failed_owner":
        value = receipts()[0]
        value.update(process_status="failed", returncode=1)
        rewrite(pins, "owner", value)
    elif bad == "failed_process":
        value = receipts()[1]
        value.update(status="failed", returncode=1)
        rewrite(pins, "process", value)
    elif bad == "bad_plan":
        rewrite(pins, "plan", {})
    else:
        pins["owner"]["sha256"] = "0" * 64
    stable = reader.guards._stable_read
    def no_panel(path, limit):
        assert not path.name.startswith("validated-")
        return stable(path, limit)
    monkeypatch.setattr(reader.guards, "_stable_read", no_panel)
    with pytest.raises(ValueError):
        reader.read_m9_panel_files(pins, packet_sha256="a" * 64)


def test_last_panel_hash_failure_prevents_all_panel_parsing(monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    pins["validated-014.json"]["sha256"] = "0" * 64
    parse = reader.guards._parse_finite_object
    def no_panel(raw):
        assert '"panel"' not in raw
        return parse(raw)
    monkeypatch.setattr(reader.guards, "_parse_finite_object", no_panel)
    with pytest.raises(ValueError, match="validated-014"):
        reader.read_m9_panel_files(pins, packet_sha256="a" * 64)


@pytest.mark.parametrize("mutation", ["missing", "extra", "alias", "bad_sha", "relative"])
def test_pin_schema_refuses_before_file_reads(monkeypatch, tmp_path, mutation):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    if mutation == "missing":
        pins.pop("validated-014.json")
    elif mutation == "extra":
        pins["extra"] = pins["owner"]
    elif mutation == "alias":
        pins["process"] = copy.deepcopy(pins["owner"])
    elif mutation == "bad_sha":
        pins["owner"]["sha256"] = "not-a-sha"
    else:
        pins["owner"]["path"] = "relative.json"
    monkeypatch.setattr(reader.guards, "_stable_read", lambda *a: pytest.fail("unexpected read"))
    with pytest.raises(ValueError):
        reader.read_m9_panel_files(pins, packet_sha256="a" * 64)


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}',
                                 b'{"x":1e999}', '{}'.encode("utf-16")])
def test_pinned_malformed_panel_refuses(monkeypatch, tmp_path, raw):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    path = tmp_path / "bad-panel.json"
    path.write_bytes(raw)
    pins["validated-000.json"] = {
        "path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    with pytest.raises((ValueError, UnicodeError)):
        reader.read_m9_panel_files(pins, packet_sha256="a" * 64)


def test_symlink_input_refused(monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(pins["owner"]["path"])
    pins["owner"]["path"] = str(alias)
    with pytest.raises(ValueError):
        reader.read_m9_panel_files(pins, packet_sha256="a" * 64)


def test_size_cap_enforced(monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", 1)
    with pytest.raises(ValueError):
        reader.read_m9_panel_files(pins, packet_sha256="a" * 64)
