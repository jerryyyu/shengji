import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading

import pytest

from shengji.eval import m9_panel_publication as publication
from test_m9_panel_artifact_reader import bundle


def invocation_for(pins, output):
    return {
        "schema": "m9-panel-readout-invocation-v1",
        "files": copy.deepcopy(pins),
        "packet_sha256": "a" * 64,
        "output_dir": str(output),
    }


def invocation_sha(invocation):
    return hashlib.sha256(publication.guards._canonical(invocation)).hexdigest()


def test_real_reader_is_published_once_with_bound_receipt(monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")

    receipt = publication.publish_m9_panel_readout_once(
        invocation, invocation_sha256=invocation_sha(invocation))
    output = Path(invocation["output_dir"])
    result_raw = (output / "result.json").read_bytes()
    result = json.loads(result_raw)

    assert receipt == json.loads((output / "receipt.json").read_text())
    assert receipt["result_sha256"] == hashlib.sha256(result_raw).hexdigest()
    assert receipt["input_sha256"] == result["input_sha256"]
    assert receipt["packet_sha256"] == "a" * 64
    assert receipt["provenance_verified"] is False
    assert json.loads((output / "claim.json").read_text())["invocation_sha256"] == invocation_sha(invocation)
    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        lambda *args, **kwargs: pytest.fail("reader retried"))
    with pytest.raises(FileExistsError):
        publication.publish_m9_panel_readout_once(
            invocation, invocation_sha256=invocation_sha(invocation))


def test_invocation_sha_and_output_paths_refuse_before_claim_or_reader(
        monkeypatch, tmp_path):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    output = tmp_path / "readout"
    invocation = invocation_for(pins, output)
    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        lambda *args, **kwargs: pytest.fail("reader called"))

    with pytest.raises(ValueError, match="invocation SHA"):
        publication.publish_m9_panel_readout_once(
            invocation, invocation_sha256="0" * 64)
    assert not output.exists()

    invocation["output_dir"] = str(tmp_path / "link" / "readout")
    (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical absolute path"):
        publication.publish_m9_panel_readout_once(
            invocation, invocation_sha256=invocation_sha(invocation))

    invocation["output_dir"] = str(tmp_path / "existing")
    Path(invocation["output_dir"]).mkdir()
    with pytest.raises(FileExistsError):
        publication.publish_m9_panel_readout_once(
            invocation, invocation_sha256=invocation_sha(invocation))


@pytest.mark.parametrize("error_class", [RuntimeError, KeyboardInterrupt])
def test_refusal_preserves_claim_and_hides_exception_text(monkeypatch, tmp_path, error_class):
    pins, _, _ = bundle(monkeypatch, tmp_path)
    invocation = invocation_for(pins, tmp_path / "readout")

    def refuse(*args, **kwargs):
        raise error_class("score-bearing details must not be retained")

    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files", refuse)
    with pytest.raises(error_class, match="score-bearing"):
        publication.publish_m9_panel_readout_once(
            invocation, invocation_sha256=invocation_sha(invocation))

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
    receipt = publication.publish_m9_panel_readout_once(
        invocation, invocation_sha256=invocation_sha(invocation))
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
        futures = [pool.submit(publication.publish_m9_panel_readout_once,
                               invocation,
                               invocation_sha256=invocation_sha(invocation))
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
        publication.publish_m9_panel_readout_once(
            invocation, invocation_sha256=invocation_sha(invocation))

    output = Path(invocation["output_dir"])
    assert receipt_calls == 1
    assert (output / "claim.json").exists()
    assert (output / "result.json").exists()
    assert not (output / "receipt.json").exists()
    assert json.loads((output / "refusal.json").read_text())["error_type"] == "OSError"
    monkeypatch.setattr(publication.artifact_reader, "read_m9_panel_files",
                        lambda *args, **kwargs: pytest.fail("reader retried"))
    with pytest.raises(FileExistsError):
        publication.publish_m9_panel_readout_once(
            invocation, invocation_sha256=invocation_sha(invocation))
