#!/usr/bin/env python3
"""One-shot host reader for the sealed S61 DEV screen output.

The dispatch paths, lane identity, and launcher pin are literal host pins.
This wrapper performs one input binding, imports only the hash-verified reader,
and publishes a small claim exclusively; it does not retry or rediscover inputs.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys


LANE = "s61dev"
LAUNCHER_SHA256 = "fd6f3005a932dfe76bc82ad57781c6beaf3cf5c4e2ed58f394d917768981aa19"
TRUSTED = {
    "lane": LANE,
    "launcher_sha256": LAUNCHER_SHA256,
    "host": "shengji-cloud",
    "root": "/root/vol-dev-claude-s61dev-r46-20261022",
    "status": "/root/claude_s61dev_screen.status",
    "reservation": "/root/claude_reservations/s61dev.json",
}
READER_PATH = Path(__file__).with_name("s61dev_read.py").resolve()
READER_SHA256 = "476ea123db53d42fd2e1df37e79fde89b18e2e2a45c290e15be4ca9db8c00d67"
READER_LIB_PATH = Path(__file__).with_name("reader_lib.py").resolve()
READER_LIB_SHA256 = "9c7ea58bddf5d7fe5515a50a3239e0ea7d0b0defe4dcb315ebb50b719dea24ee"
RESULT_SCHEMA = "s61dev-sealed-claim-v1"
RESULT_PATH = "/root/codex-s61dev-readout/result.json"
CLAIM_SUFFIX = ".claim"

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def need(ok, message):
    if not ok:
        raise ValueError(message)


def _canonical_output(path):
    path = Path(path)
    need(path.is_absolute() and path == path.resolve(), "result path must be an absolute canonical path")
    need(not path.exists() or not path.is_symlink(), "result path must not be a symlink")
    need(path.parent.is_dir() and path.parent == path.parent.resolve(), "result parent must be an existing canonical directory")
    need(not any(parent.is_symlink() for parent in path.parents), "result path has a symlink parent")
    need(not path.exists(), "result already exists; one-shot read refuses a rerun")
    claim = Path(str(path) + CLAIM_SUFFIX)
    need(not claim.exists(), "result claim already exists; one-shot read refuses a rerun")
    root = Path(TRUSTED["root"])
    need(path != root and root not in path.parents, "result must be outside the sealed output root")
    need(claim != root and root not in claim.parents, "result claim must be outside the sealed output root")
    return path, claim


def _regular(path, label):
    path = Path(path)
    need(path.is_absolute() and path == path.resolve(), f"{label} path is not canonical")
    need(stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink(), f"{label} is not a regular file")
    return path


def _load_verified_module(path, digest, name):
    path = _regular(path, name)
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == digest, f"{name} source SHA256 mismatch")
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


reader_lib = _load_verified_module(READER_LIB_PATH, READER_LIB_SHA256, "s61dev_sealed_reader_lib")


def _load_verified_reader():
    return _load_verified_module(READER_PATH, READER_SHA256, "s61dev_sealed_reader")


def _claim(result, binding):
    validity = result.get("validity") or {}
    bar = result.get("bar") or {}
    levels = result.get("levels")
    points = result.get("points")
    return {
        "schema": RESULT_SCHEMA,
        "lane": LANE,
        "host": TRUSTED["host"],
        "reader_sha256": READER_SHA256,
        "launcher_sha256": TRUSTED["launcher_sha256"],
        "binding": {
            "root": binding["root"],
            "status": binding["status"],
            "reservation": binding["reservation"],
            "status_sha256": binding["status_sha256"],
            "reservation_sha256": binding["reservation_sha256"],
            "files": binding["files"],
        },
        "deals": result.get("deals"),
        "validity": validity.get("verdict"),
        "verdict": bar.get("verdict"),
        "attribution_status": bar.get("attribution_status"),
        "levels": levels,
        "points": points,
        "readout": result,
    }


def _publish(path, claim):
    raw = (json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fd = None
            fh.write(raw)
    finally:
        if fd is not None:
            os.close(fd)


def _claim_record():
    return {
        "schema": RESULT_SCHEMA,
        "status": "claimed",
        "lane": LANE,
        "host": TRUSTED["host"],
        "reader_sha256": READER_SHA256,
        "launcher_sha256": TRUSTED["launcher_sha256"],
        "result": RESULT_PATH,
    }


def read_once():
    destination, claim_path = _canonical_output(RESULT_PATH)
    _publish(claim_path, _claim_record())
    # Binding is intentionally before the reader source is opened or imported.
    binding = reader_lib.bind_inputs(
        TRUSTED["root"], TRUSTED["status"], TRUSTED["reservation"], trusted=TRUSTED)
    root = Path(binding["root"])
    data = _regular(root / "duel.jsonl", "duel input")
    sums = _regular(root / "SHA256SUMS", "checksum manifest")
    reader = _load_verified_reader()
    result = reader.analyze(str(data), status=binding["status"], sums=str(sums))
    _publish(destination, _claim(result, binding))
    return destination


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv:
            raise ValueError("host reader takes no input paths")
        path = read_once()
    except Exception as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "complete", "result": str(path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
