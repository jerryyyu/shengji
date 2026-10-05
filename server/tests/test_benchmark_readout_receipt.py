from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest

from shengji.luna.benchmark_readout_receipt import run_once


def test_complete_run_publishes_claim_result_and_receipt(tmp_path):
    output = tmp_path / "out"
    identity = {"plan_sha256": "a" * 64, "row": "synthetic"}
    result = {"status": "complete", "values": [1, 2, 3]}
    assert run_once(output, identity, lambda: result) == result
    claim = json.loads((output / "claim.json").read_text())
    assert claim["identity"] == identity and claim["pid"] > 0
    raw = (output / "result.json").read_bytes()
    assert json.loads(raw) == result
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["status"] == "complete"
    assert receipt["identity"] == identity
    assert receipt["result_sha256"] == hashlib.sha256(raw).hexdigest()


def test_existing_output_refuses_before_callback(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    called = []
    with pytest.raises(FileExistsError):
        run_once(output, {"row": "existing"}, lambda: called.append(True))
    assert called == []
    assert list(output.iterdir()) == []


def test_callback_error_preserves_claim_and_writes_exclusive_refusal(tmp_path):
    output = tmp_path / "out"

    def fail():
        raise RuntimeError("synthetic callback failure")

    with pytest.raises(RuntimeError, match="synthetic callback"):
        run_once(output, {"row": "failed"}, fail)
    assert (output / "claim.json").is_file()
    refusal = json.loads((output / "refusal.json").read_text())
    assert refusal["status"] == "refused"
    assert refusal["identity"] == {"row": "failed"}
    assert not (output / "result.json").exists()
    assert not (output / "receipt.json").exists()


def test_nonfinite_result_refuses_without_json_nan(tmp_path):
    output = tmp_path / "out"
    with pytest.raises(ValueError):
        run_once(output, {"row": "nan"}, lambda: {"value": float("nan")})
    assert (output / "claim.json").is_file()
    assert (output / "refusal.json").is_file()
    assert not (output / "result.json").exists()
    assert b"NaN" not in (output / "refusal.json").read_bytes()


def test_symlink_parent_is_refused_before_claim(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    called = []
    with pytest.raises(ValueError, match="symlink"):
        run_once(link / "out", {"row": "symlink"}, lambda: called.append(True))
    assert called == []
    assert not (real / "out").exists()


def test_concurrent_calls_have_one_directory_claim_and_one_callback(tmp_path):
    output = tmp_path / "out"
    lock = threading.Lock()
    callbacks = []

    def callback():
        with lock:
            callbacks.append(True)
        time.sleep(0.03)
        return {"winner": True}

    def invoke():
        try:
            return ("ok", run_once(output, {"row": "race"}, callback))
        except FileExistsError:
            return ("refused", None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: invoke(), range(8)))
    assert sum(kind == "ok" for kind, _ in outcomes) == 1
    assert sum(kind == "refused" for kind, _ in outcomes) == 7
    assert len(callbacks) == 1
    assert (output / "receipt.json").is_file()
