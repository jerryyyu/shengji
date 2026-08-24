"""Filesystem-boundary tests for the natural PT0 runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
from shengji.rl.privileged_teacher_pt0_natural import NaturalPT0Design, NATURAL_PT0_SCHEMA


_SCRIPT = Path(__file__).parents[1] / "scripts" / "run_privileged_teacher_pt0_natural.py"
_FROZEN_DESIGN = (Path(__file__).parents[1] / "scripts"
                  / "privileged_teacher_pt0_natural_design.v1.json")
_SPEC = importlib.util.spec_from_file_location("natural_runner", _SCRIPT)
runner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(runner)


SOURCE = "a" * 40
CAPTURE_SECRET = bytes(range(32))
CAPTURE_SECRET_SHA256 = hashlib.sha256(CAPTURE_SECRET).hexdigest()


def _design_bytes() -> bytes:
    design = NaturalPT0Design(
        capture_secret_sha256=CAPTURE_SECRET_SHA256,
        trump_ranks=("2",), banker_seats=(0,),
        production_policy="heuristic", unique_worlds_per_state=2,
        max_sampler_attempts=100, max_exact_nodes=50_000)
    return canonical_json_bytes(design.payload())


def _design() -> NaturalPT0Design:
    return runner._design_from_bytes(_design_bytes())


def _fake_core(monkeypatch, *, status="COMPLETE", crash=False):
    def fake(design, *, record_sink=None, **kwargs):
        records = []
        count = (len(design.bucket_keys) if status == "COMPLETE"
                 else kwargs.get("deadline_exempt_prefix", 0))
        for index in range(count):
            record = {"schema": "safe-record-v1", "index": index}
            records.append(record)
            if record_sink is not None:
                record_sink(index, canonical_json_bytes(record))
                if crash and index == 0:
                    raise RuntimeError("synthetic crash")
        packet = {
            "schema": NATURAL_PT0_SCHEMA,
            "design_sha256": hashlib.sha256(
                canonical_json_bytes(design.payload())).hexdigest(),
            "records": records,
            "record_count": count,
            "total_record_count": len(design.bucket_keys),
            "status": status,
            "truncated_by_deadline": status != "COMPLETE",
            "progress": {"completed_units": count,
                         "total_units": len(design.bucket_keys),
                         "percent_basis_points": (count * 10_000) // len(design.bucket_keys)},
            "summary": {},
            "authority": design.authority(),
        }
        packet["packet_sha256"] = hashlib.sha256(
            canonical_json_bytes(packet)).hexdigest()
        return packet

    monkeypatch.setattr(runner.core, "run_natural_packet", fake)
    monkeypatch.setattr(
        runner.core, "summarize_natural_records",
        lambda design, records, *, complete: {})
    monkeypatch.setattr(
        runner, "_validate_packet_records",
        lambda design, records: None)


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(runner, "_git_identity", lambda _: SOURCE)


def _run(tmp_path, source, **kwargs):
    design = tmp_path / "design.json"
    design.write_bytes(_design_bytes())
    secret = tmp_path / "capture-secret.bin"
    if not secret.exists():
        secret.write_bytes(CAPTURE_SECRET)
        secret.chmod(0o600)
    return runner.run_bundle(
        design, secret, tmp_path / "bundle", SOURCE, **kwargs)


def test_noncanonical_design_refused(tmp_path, source):
    design = tmp_path / "design.json"
    design.write_bytes(json.dumps(json.loads(_design_bytes()), indent=2).encode())
    with pytest.raises(runner.RunnerRefused, match="canonical"):
        runner.run_bundle(
            design, tmp_path / "capture-secret.bin",
            tmp_path / "bundle", SOURCE)


def test_frozen_design_is_canonical_and_pins_the_104_state_grid():
    raw = _FROZEN_DESIGN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == \
        "450a1b0faf66ffe6f2a2bab061ce3a2feaad0ceaebe4cc84bc9e5182633b8b5a"
    design = runner._design_from_bytes(raw)
    assert len(design.bucket_keys) == 104
    assert design.proposal_worlds_per_state == 16
    assert design.evaluation_worlds_per_state == 16
    assert design.baseline_seeds_per_state == 4
    assert design.bootstrap_replicates == 5_000
    assert b"round_seeds" not in raw
    assert design.capture_secret_sha256 == \
        "11b870146f739e08d56f2161f97f69053c0d9f969623a91b9acc0ed85e8ca573"


def test_capture_secret_commitment_and_private_mode_are_load_bearing(
        tmp_path, source):
    design_path = tmp_path / "design.json"
    design_path.write_bytes(_design_bytes())
    secret = tmp_path / "capture-secret.bin"
    secret.write_bytes(b"x" * 32)
    secret.chmod(0o600)
    with pytest.raises(runner.RunnerRefused, match="commitment"):
        runner.run_bundle(
            design_path, secret, tmp_path / "wrong-secret", SOURCE)
    secret.write_bytes(CAPTURE_SECRET)
    secret.chmod(0o644)
    with pytest.raises(runner.RunnerRefused, match="mode/link"):
        runner.run_bundle(
            design_path, secret, tmp_path / "public-secret", SOURCE)


def test_first_run_and_byte_identical_reopen(monkeypatch, tmp_path, source):
    _fake_core(monkeypatch)
    first = _run(tmp_path, source)
    packet = (tmp_path / "bundle" / "packet.json").read_bytes()
    manifest = (tmp_path / "bundle" / "manifest.json").read_bytes()
    second = runner.run_bundle(
        tmp_path / "design.json", tmp_path / "capture-secret.bin",
        tmp_path / "bundle", SOURCE)
    assert first == second
    assert packet == (tmp_path / "bundle" / "packet.json").read_bytes()
    assert manifest == (tmp_path / "bundle" / "manifest.json").read_bytes()


def test_mismatched_existing_record_refused_on_resume(monkeypatch, tmp_path, source):
    _fake_core(monkeypatch, crash=True)
    with pytest.raises(RuntimeError):
        _run(tmp_path, source)
    record = tmp_path / "bundle.partial" / "records" / "record-000000.json"
    record.write_bytes(b"{\"mutant\":true}\n")
    _fake_core(monkeypatch)
    with pytest.raises(runner.RunnerRefused, match="bytes mismatch"):
        runner.run_bundle(
            tmp_path / "design.json", tmp_path / "capture-secret.bin",
            tmp_path / "bundle", SOURCE)


def test_expired_resume_cannot_return_less_than_durable_prefix(
        monkeypatch, tmp_path, source):
    _fake_core(monkeypatch, crash=True)
    with pytest.raises(RuntimeError):
        _run(tmp_path, source)
    _fake_core(monkeypatch, status="TRUNCATED")
    result = runner.run_bundle(
        tmp_path / "design.json", tmp_path / "capture-secret.bin",
        tmp_path / "bundle", SOURCE, deadline_seconds=0)
    assert result["status"] == "TRUNCATED"
    assert result["record_count"] == 1
    assert not (tmp_path / "bundle.partial").exists()


def test_source_refusal_happens_before_project_import(
        monkeypatch, tmp_path):
    monkeypatch.setattr(
        runner, "_check_expected_source",
        lambda *_: (_ for _ in ()).throw(
            runner.RunnerRefused("synthetic source refusal")))
    monkeypatch.setattr(
        runner, "_load_core",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("project import happened before source refusal")))
    with pytest.raises(runner.RunnerRefused, match="synthetic source refusal"):
        runner.run_bundle(
            tmp_path / "missing-design.json",
            tmp_path / "missing-secret.bin", tmp_path / "bundle", SOURCE)


def test_extra_file_and_symlink_refused(monkeypatch, tmp_path, source):
    _fake_core(monkeypatch, crash=True)
    with pytest.raises(RuntimeError):
        _run(tmp_path, source)
    (tmp_path / "bundle.partial" / "extra").write_bytes(b"x")
    _fake_core(monkeypatch)
    with pytest.raises(runner.RunnerRefused, match="extra"):
        runner.run_bundle(
            tmp_path / "design.json", tmp_path / "capture-secret.bin",
            tmp_path / "bundle", SOURCE)

    # A completed bundle with a symlink replacing a record must not reopen.
    root = tmp_path / "final"
    design = tmp_path / "design-final.json"
    design.write_bytes(_design_bytes())
    secret = tmp_path / "capture-secret.bin"
    secret.write_bytes(CAPTURE_SECRET)
    secret.chmod(0o600)
    runner.run_bundle(design, secret, root, SOURCE)
    target = root / "records" / "record-000000.json"
    data = target.read_bytes()
    os.chmod(root / "records", 0o755)
    target.unlink()
    target.symlink_to(root / "packet.json")
    with pytest.raises(runner.RunnerRefused, match="symlink"):
        runner.verify_bundle(root, design=_design())
    target.unlink()
    target.write_bytes(data)


def test_truncated_bundle_is_valid_and_immutable(monkeypatch, tmp_path, source):
    _fake_core(monkeypatch, status="TRUNCATED")
    result = _run(tmp_path, source)
    assert result["status"] == "TRUNCATED"
    assert runner.verify_bundle(
        tmp_path / "bundle", design=_design())["status"] == "TRUNCATED"
    assert not (tmp_path / "bundle.partial").exists()


def test_manifest_coordination_mutation_refused_by_independent_verify(
        monkeypatch, tmp_path, source):
    _fake_core(monkeypatch)
    _run(tmp_path, source)
    manifest = tmp_path / "bundle" / "manifest.json"
    data = json.loads(manifest.read_text())
    data["packet_sha256"] = "b" * 64
    os.chmod(manifest, 0o644)
    manifest.write_bytes(canonical_json_bytes(data))
    with pytest.raises(runner.RunnerRefused, match="manifest hash"):
        runner.verify_bundle(tmp_path / "bundle", design=_design())


def test_coordinated_packet_manifest_rehash_cannot_forge_summary(
        monkeypatch, tmp_path, source):
    _fake_core(monkeypatch)
    _run(tmp_path, source)
    root = tmp_path / "bundle"
    packet_path = root / "packet.json"
    manifest_path = root / "manifest.json"
    os.chmod(root, 0o755)
    os.chmod(packet_path, 0o644)
    os.chmod(manifest_path, 0o644)
    packet = json.loads(packet_path.read_text())
    packet["summary"] = {"forged": True}
    packet_without_hash = dict(packet)
    packet_without_hash.pop("packet_sha256")
    packet["packet_sha256"] = hashlib.sha256(
        canonical_json_bytes(packet_without_hash)).hexdigest()
    packet_bytes = canonical_json_bytes(packet)
    packet_path.write_bytes(packet_bytes)
    manifest = json.loads(manifest_path.read_text())
    manifest["packet_sha256"] = packet["packet_sha256"]
    manifest["packet_bytes_sha256"] = hashlib.sha256(packet_bytes).hexdigest()
    manifest_without_hash = dict(manifest)
    manifest_without_hash.pop("manifest_sha256")
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(manifest_without_hash)).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(runner.RunnerRefused, match="summary reconstruction"):
        runner.verify_bundle(root, design=_design())


def test_fully_staged_bundle_finalizes_atomically_on_resume(
        monkeypatch, tmp_path, source):
    _fake_core(monkeypatch)
    expected = _run(tmp_path, source)
    final = tmp_path / "bundle"
    staged = tmp_path / "bundle.partial"
    os.chmod(final, 0o755)
    final.rename(staged)
    resumed = runner.run_bundle(
        tmp_path / "design.json", tmp_path / "capture-secret.bin",
        final, SOURCE)
    assert resumed == expected
    assert final.is_dir() and not staged.exists()


def test_final_bundle_is_bound_to_the_supplied_design(
        monkeypatch, tmp_path, source):
    _fake_core(monkeypatch)
    _run(tmp_path, source)
    changed = NaturalPT0Design(
        capture_secret_sha256=hashlib.sha256(b"x" * 32).hexdigest(),
        trump_ranks=("2",), banker_seats=(0,),
        production_policy="heuristic", unique_worlds_per_state=2,
        max_sampler_attempts=100, max_exact_nodes=50_000)
    changed_path = tmp_path / "changed-design.json"
    changed_path.write_bytes(canonical_json_bytes(changed.payload()))
    with pytest.raises(runner.RunnerRefused, match="coordination|metadata"):
        runner.run_bundle(
            changed_path, tmp_path / "capture-secret.bin",
            tmp_path / "bundle", SOURCE)


def test_capture_seed_index_is_refused_as_hidden_provenance():
    with pytest.raises(runner.RunnerRefused, match="unsafe hidden field"):
        runner._safe_record(
            b'{"capture_seed_index":0,"schema":"x"}\n', "record")


def test_authority_is_false(monkeypatch, tmp_path, source):
    _fake_core(monkeypatch)
    result = _run(tmp_path, source)
    assert result["authority"] == runner.AUTHORITY
    manifest = json.loads((tmp_path / "bundle" / "manifest.json").read_text())
    assert manifest["authority"] == runner.AUTHORITY


def test_real_core_bundle_reopens_exact_state_population(
        monkeypatch, tmp_path, source):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    result = _run(tmp_path, source)
    assert result["status"] == "COMPLETE"
    assert result["record_count"] == 4
    assert runner.verify_bundle(
        tmp_path / "bundle", design=_design(),
        expected_source_git=SOURCE) == result
    packet = json.loads((tmp_path / "bundle" / "packet.json").read_text())
    packet["records"][0]["role"] = "attacker-team" \
        if packet["records"][0]["role"] == "banker-team" else "banker-team"
    with pytest.raises(runner.RunnerRefused, match="state population"):
        runner._validate_packet_records(_design(), packet["records"])
