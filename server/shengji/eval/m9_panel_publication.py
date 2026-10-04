"""Exclusive publication adapter for an authenticated M9 panel readout.

This is a preparation layer only.  The caller still authenticates the source,
runtime and terminal seal, and supplies the exclusive canonical invocation.
The output-directory claim is per-output and is not a globally single-use
claim for an invocation.
Only a result accompanied by its matching receipt is a completed publication.
Failures keep their output directory occupied; recovery needs a separately
reviewed invocation and output path, never an automatic second read.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..luna.atomic_io import publish_exclusive_bytes
from . import m9_panel_artifact_reader as artifact_reader
from . import observation_queue as guards


_INVOCATION_KEYS = {
    "schema", "files", "packet_sha256", "output_dir",
}
_INVOCATION_SCHEMA = "m9-panel-readout-invocation-v1"
_RESULT_KEYS = {
    "analysis", "input_sha256", "packet_sha256", "provenance_verified",
}


def _json_bytes(value: Any) -> bytes:
    return guards._canonical(value)


def _validate_invocation(invocation: Any, invocation_sha256: Any) -> tuple[dict, Path]:
    if type(invocation) is not dict or set(invocation) != _INVOCATION_KEYS:
        raise ValueError("exact M9 panel readout invocation required")
    guards._strict_sha(invocation_sha256, "invocation SHA")
    guards._strict_sha(invocation["packet_sha256"], "packet SHA")
    if invocation["schema"] != _INVOCATION_SCHEMA:
        raise ValueError("unsupported M9 panel readout invocation schema")
    try:
        canonical = _json_bytes(invocation)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invocation must have canonical finite JSON") from exc
    if hashlib.sha256(canonical).hexdigest() != invocation_sha256:
        raise ValueError("invocation SHA mismatch")
    # Do not retain or pass the caller's mutable object after hashing it.
    invocation = guards._parse_finite_object(canonical)

    output = guards._canonical_absolute(invocation["output_dir"], "output_dir")
    parent = output.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError("output parent must be an existing nonsymlink directory")
    if type(invocation["files"]) is not dict:
        raise ValueError("panel files mapping required")
    return invocation, output


def _validate_result(result: Any, invocation: dict) -> dict:
    if type(result) is not dict or set(result) != _RESULT_KEYS:
        raise ValueError("artifact reader returned an invalid result")
    packet_sha256 = invocation["packet_sha256"]
    if result["packet_sha256"] != packet_sha256:
        raise ValueError("readout result belongs to another packet")
    if result["provenance_verified"] is not False:
        raise ValueError("readout result must leave provenance unverified")
    input_sha256 = result["input_sha256"]
    files = invocation["files"]
    if type(input_sha256) is not dict or set(input_sha256) != set(files):
        raise ValueError("readout input hashes do not bind invocation files")
    for name, digest in input_sha256.items():
        guards._strict_sha(digest, f"input SHA for {name}")
        entry = files[name]
        if (type(entry) is not dict or set(entry) != {"path", "sha256"}
                or digest != entry["sha256"]):
            raise ValueError("readout input hash differs from invocation pin")
    return result


def _publish_refusal(output: Path, exc: BaseException) -> None:
    """Best-effort refusal publication without score-bearing exception text."""
    refusal = {
        "schema": "m9-panel-readout-refusal-v1",
        "error_type": type(exc).__name__,
    }
    try:
        publish_exclusive_bytes(output / "refusal.json", _json_bytes(refusal),
                                mode=0o400)
    except BaseException:
        pass


def publish_m9_panel_readout_once(invocation, *, invocation_sha256):
    """Read and publish one already-authorized M9 panel bundle exactly once.

    Validation happens before claim or input access.  Once the output
    directory is exclusively created, every failure leaves the claim and any
    successfully published immutable files in place; no read or publication
    is retried and no existing output is overwritten.
    """
    invocation, output = _validate_invocation(invocation, invocation_sha256)
    packet_sha256 = invocation["packet_sha256"]

    # Directory creation is the exclusive per-output claim and deliberately
    # precedes both claim publication and the artifact reader.
    output.mkdir(mode=0o700)
    try:
        claim = {
            "schema": "m9-panel-readout-claim-v1",
            "invocation_sha256": invocation_sha256,
            "packet_sha256": packet_sha256,
            "provenance_verified": False,
        }
        publish_exclusive_bytes(output / "claim.json", _json_bytes(claim),
                                mode=0o400)

        reader_files = guards._parse_finite_object(
            _json_bytes(invocation["files"]))
        result = _validate_result(
            artifact_reader.read_m9_panel_files(
                reader_files, packet_sha256=packet_sha256),
            invocation)
        result_raw = _json_bytes(result)
        publish_exclusive_bytes(output / "result.json", result_raw, mode=0o400)
        receipt = {
            "schema": "m9-panel-readout-receipt-v1",
            "invocation_sha256": invocation_sha256,
            "packet_sha256": packet_sha256,
            "result_sha256": hashlib.sha256(result_raw).hexdigest(),
            "input_sha256": result["input_sha256"],
            "provenance_verified": False,
        }
        publish_exclusive_bytes(output / "receipt.json", _json_bytes(receipt),
                                mode=0o400)
        return receipt
    except BaseException as exc:
        _publish_refusal(output, exc)
        raise


__all__ = ["publish_m9_panel_readout_once"]
