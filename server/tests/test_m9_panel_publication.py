import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from shengji.eval import m9_panel_publication as publication
from test_m9_panel_artifact_reader import bundle
from test_observation_runtime import _fake_capture_context


def invocation_for(pins, output):
    return {
        "schema": "m9-panel-readout-invocation-v1",
        "files": copy.deepcopy(pins),
        "controls": {},  # authenticated by bootstrap, not this adapter
        "packet_sha256": "a" * 64,
        "collection_packet": {"path": str(output.parent / "collection-packet.json"),
                              "sha256": "a" * 64},
        "output_dir": str(output),
        "runtime": {"path": str(output.parent / "runtime.json"), "sha256": "c" * 64},
    }


def invocation_sha(invocation):
    return hashlib.sha256(publication.guards._canonical(invocation)).hexdigest()


def collection_packet_for(invocation):
    files = invocation["files"]
    process = Path(files.get("process", {}).get(
        "path", str(Path(invocation["output_dir"]).parent / "process.json")))
    owner = files.get("owner", {}).get(
        "path", str(Path(invocation["output_dir"]).parent / "owner.json"))
    saved = files.get("saved_readout", {}).get(
        "path", str(Path(invocation["output_dir"]).parent / "saved.json"))
    saved_sha = files.get("saved_readout", {}).get("sha256", "0" * 64)
    return {
        "schema": "m9-panel-admission-v1",
        "status": owner,
        "recipe": {
            "output_dir": str(Path(files.get("collection", {}).get(
                "path", str(Path(invocation["output_dir"]).parent / "collection"))).parent),
            "evidence": str(process.parent),
            "saved_readout": saved,
            "saved_readout_sha256": saved_sha,
        },
    }


def publish(invocation, **kwargs):
    return publication.publish_m9_panel_readout_once(
        invocation, collection_packet=collection_packet_for(invocation), **kwargs)


def publish_packet(invocation, packet, **kwargs):
    return publication.publish_m9_panel_readout_once(
        invocation, collection_packet=packet, **kwargs)


@pytest.mark.parametrize("drift_phase", [None, "before", "after"])
def test_real_runtime_source_stamp_fences_actual_publication(monkeypatch, tmp_path, drift_phase):
    from shengji.eval import observation_runtime as runtime

    pins, _, _ = bundle(monkeypatch, tmp_path)
    source, _, _, _, _ = _fake_capture_context(tmp_path / "runtime", monkeypatch)
    # Only host/native process plumbing is synthetic. Capture/admission source
    # hashes and the subsequent source-stat checks are the real implementation.
    monkeypatch.setattr(runtime.runtime_fence, "capture", lambda path, imports: {
        "source_root": str(path), "imports": imports})
    monkeypatch.setattr(runtime.runtime_fence, "RuntimeFence",
                        lambda *args: SimpleNamespace(check=lambda: True))
    monkeypatch.setattr(runtime, "_routes", lambda path: None)
    manifest = runtime.capture(source, profile="panel-readout")
    admitted = runtime.ObservationRuntime(manifest, profile="panel-readout")
    monkeypatch.setattr(runtime, "_sha", lambda *args: pytest.fail("runtime check rehashed"))
    changed_source = source / "shengji" / "engine" / "round.py"
    output = tmp_path / "readout"
    invocation = invocation_for(pins, output)
    manifest_path = tmp_path / "runtime.json"
    manifest_raw = publication.guards._canonical(manifest)
    manifest_path.write_bytes(manifest_raw)
    invocation["runtime"] = {"path": str(manifest_path),
                             "sha256": hashlib.sha256(manifest_raw).hexdigest()}
    real_reader = publication.artifact_reader.read_m9_panel_files
    calls = []

    def read(*args, **kwargs):
        calls.append("read")
        result = real_reader(*args, **kwargs)
        if drift_phase == "after":
            changed_source.write_text("# source changed after runtime admission\n")
        return result

    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files", read)
    if drift_phase == "before":
        changed_source.write_text("# source changed before publication claim\n")
    kwargs = dict(invocation_sha256=invocation_sha(invocation), runtime_check=admitted.check)
    if drift_phase is None:
        publish(invocation, **kwargs)
        assert (output / "receipt.json").is_file()
    else:
        with pytest.raises(ValueError, match="runtime check failed"):
            publish(invocation, **kwargs)
        assert not (output / "result.json").exists()
        assert not (output / "receipt.json").exists()
        assert output.exists() is (drift_phase == "after")
        if drift_phase == "after":
            assert (output / "claim.json").is_file()
            assert (output / "refusal.json").is_file()
    assert calls == ([] if drift_phase == "before" else ["read"])


@pytest.mark.parametrize("response", [False, None, 1])
def test_runtime_refusal_before_claim_prevents_reader(monkeypatch, tmp_path, response):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    output = tmp_path / "readout"
    invocation = invocation_for(pins, output)
    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        lambda *a, **kw: pytest.fail("reader before valid runtime"))
    with pytest.raises(ValueError, match="runtime check failed before claim"):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation),
            runtime_check=lambda: response)
    assert not output.exists()


@pytest.mark.parametrize("runtime", [{}, {"path": "relative", "sha256": "c" * 64},
                                    {"path": "/not-read.json", "sha256": "bad"}])
def test_runtime_pin_shape_refuses_before_claim(monkeypatch, tmp_path, runtime):
    output = tmp_path / "readout"
    invocation = invocation_for({}, output)
    invocation["runtime"] = runtime
    with pytest.raises(ValueError):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation),
            runtime_check=lambda: pytest.fail("checked invalid invocation"))
    assert not output.exists()


@pytest.mark.parametrize("drift", [False, True])
def test_runtime_checked_around_real_reader_before_publication(monkeypatch, tmp_path, drift):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    output = tmp_path / "readout"
    invocation = invocation_for(pins, output)
    events = []
    real_reader = publication.artifact_reader.read_m9_panel_files

    def check():
        events.append("check")
        assert not (output / "result.json").exists()
        assert not (output / "receipt.json").exists()
        return not (drift and len(events) == 3)

    def read(*args, **kwargs):
        assert events == ["check"]
        assert (output / "claim.json").exists()
        events.append("read")
        return real_reader(*args, **kwargs)

    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files", read)
    kwargs = dict(invocation_sha256=invocation_sha(invocation), runtime_check=check)
    if drift:
        with pytest.raises(ValueError, match="runtime check failed after analysis"):
            publish(invocation, **kwargs)
        assert (output / "claim.json").exists()
        assert (output / "refusal.json").exists()
        assert not (output / "result.json").exists()
        assert not (output / "receipt.json").exists()
    else:
        publish(invocation, **kwargs)
        assert (output / "receipt.json").exists()
    assert events == ["check", "read", "check"]


def test_real_reader_is_published_once_with_bound_receipt(monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")

    receipt = publish(
        invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)
    output = Path(invocation["output_dir"])
    result_raw = (output / "result.json").read_bytes()
    result = json.loads(result_raw)

    assert receipt == json.loads((output / "receipt.json").read_text())
    assert receipt["result_sha256"] == hashlib.sha256(result_raw).hexdigest()
    assert receipt["input_sha256"] == result["input_sha256"]
    assert receipt["packet_sha256"] == "a" * 64
    assert receipt["provenance_verified"] is False
    assert receipt["runtime"] == invocation["runtime"]
    assert json.loads((output / "claim.json").read_text())["invocation_sha256"] == invocation_sha(invocation)
    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        lambda *args, **kwargs: pytest.fail("reader retried"))
    with pytest.raises(FileExistsError):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)


def test_invocation_sha_and_output_paths_refuse_before_claim_or_reader(
        monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    output = tmp_path / "readout"
    invocation = invocation_for(pins, output)
    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        lambda *args, **kwargs: pytest.fail("reader called"))

    with pytest.raises(ValueError, match="invocation SHA"):
        publish(
            invocation, invocation_sha256="0" * 64, runtime_check=lambda: True)
    assert not output.exists()

    invocation["output_dir"] = str(tmp_path / "link" / "readout")
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical absolute path"):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)

    invocation["output_dir"] = str(tmp_path / "existing")
    Path(invocation["output_dir"]).mkdir()
    with pytest.raises(FileExistsError):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)


@pytest.mark.parametrize("mutation", ["schema", "process", "record", "saved_digest"])
def test_collection_packet_binding_refuses_wrong_run_before_publication(
        monkeypatch, tmp_path, mutation):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    output = tmp_path / "readout"
    invocation = invocation_for(pins, output)
    packet = collection_packet_for(invocation)
    if mutation == "schema":
        packet["schema"] = "m9-admission-v1"
    elif mutation == "process":
        invocation["files"]["process"]["path"] = str(tmp_path / "other-process.json")
        invocation["files"]["process"]["sha256"] = "b" * 64
    elif mutation == "record":
        invocation["files"]["validated-000.json"]["path"] = str(
            tmp_path / "other-record.json")
        invocation["files"]["validated-000.json"]["sha256"] = "b" * 64
    else:
        packet["recipe"]["saved_readout_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        publish_packet(invocation, packet,
                       invocation_sha256=invocation_sha(invocation),
                       runtime_check=lambda: pytest.fail("runtime checked too early"))
    assert not output.exists()


def test_collection_packet_pin_is_retained_in_claim_and_receipt(monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")
    packet = collection_packet_for(invocation)
    receipt = publish_packet(invocation, packet,
                             invocation_sha256=invocation_sha(invocation),
                             runtime_check=lambda: True)
    assert receipt["collection_packet"] == invocation["collection_packet"]
    claim = json.loads((Path(invocation["output_dir"]) / "claim.json").read_text())
    assert claim["collection_packet"] == invocation["collection_packet"]


@pytest.mark.parametrize("error_class", [RuntimeError, KeyboardInterrupt])
def test_refusal_preserves_claim_and_hides_exception_text(monkeypatch, tmp_path, error_class):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")

    def refuse(*args, **kwargs):
        raise error_class("score-bearing details must not be retained")

    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files", refuse)
    with pytest.raises(error_class, match="score-bearing"):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)

    output = Path(invocation["output_dir"])
    refusal = json.loads((output / "refusal.json").read_text())
    assert refusal == {
        "schema": "m9-panel-readout-refusal-v1",
        "error_type": error_class.__name__,
    }
    assert "score-bearing" not in (output / "refusal.json").read_text()
    assert (output / "claim.json").exists()
    assert not (output / "result.json").exists()
    assert not (output / "receipt.json").exists()


@pytest.mark.parametrize("mutate_caller", [False, True])
def test_reader_mutation_cannot_change_hashed_invocation_bindings(
        monkeypatch, tmp_path, mutate_caller):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")
    original_files = copy.deepcopy(invocation["files"])
    real_reader = publication.artifact_reader.read_m9_panel_files

    def mutate_reader(files, *, packet_sha256):
        expected = real_reader(copy.deepcopy(files), packet_sha256=packet_sha256)
        if mutate_caller:
            invocation["files"].clear()
            invocation["packet_sha256"] = "b" * 64
        else:
            files.clear()
        return expected

    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        mutate_reader)
    receipt = publish(
        invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)
    if not mutate_caller:
        assert invocation["files"] == original_files
    assert receipt["packet_sha256"] == "a" * 64
    assert receipt["input_sha256"] == {
        name: entry["sha256"] for name, entry in original_files.items()}


def test_concurrent_calls_allow_only_one_reader(monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")
    real_reader = publication.artifact_reader.read_m9_panel_files
    started = threading.Event()
    release = threading.Event()
    calls = 0
    lock = threading.Lock()

    def one_reader(*args, **kwargs):
        nonlocal calls
        with lock:
            calls += 1
        started.set()
        assert release.wait(5)
        return real_reader(*args, **kwargs)

    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        one_reader)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish,
                               invocation,
                               invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)
                   for _ in range(2)]
        assert started.wait(5)
        release.set()
        results = []
        errors = []
        for future in futures:
            try:
                results.append(future.result())
            except FileExistsError as exc:
                errors.append(exc)

    assert calls == 1
    assert len(results) == len(errors) == 1


def test_receipt_failure_preserves_result_and_refuses_without_retry(
        monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")
    real_publish = publication.publish_exclusive_bytes
    receipt_calls = 0

    def fail_receipt(path, raw, **kwargs):
        nonlocal receipt_calls
        if Path(path).name == "receipt.json":
            receipt_calls += 1
            raise OSError("receipt publication failed")
        return real_publish(path, raw, **kwargs)

    monkeypatch.setattr(publication, "publish_exclusive_bytes", fail_receipt)
    with pytest.raises(OSError, match="receipt publication failed"):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)

    output = Path(invocation["output_dir"])
    assert receipt_calls == 1
    assert (output / "claim.json").exists()
    assert (output / "result.json").exists()
    assert not (output / "receipt.json").exists()
    assert json.loads((output / "refusal.json").read_text())["error_type"] == "OSError"
    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        lambda *args, **kwargs: pytest.fail("reader retried"))
    with pytest.raises(FileExistsError):
        publish(
            invocation, invocation_sha256=invocation_sha(invocation), runtime_check=lambda: True)
