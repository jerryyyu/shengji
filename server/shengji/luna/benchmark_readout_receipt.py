"""One-pass, exclusive publication of a synthetic readout result."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Callable


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _parent_is_safe(parent: Path) -> None:
    if not parent.is_absolute() or any(part in (".", "..") for part in parent.parts):
        raise ValueError("output parent must be absolute without traversal")
    current = Path(parent.anchor)
    for part in parent.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except OSError as exc:
            raise FileNotFoundError("output parent is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("output parent contains a symlink or non-directory")


def _exclusive_json(path: Path, value: Any) -> bytes:
    raw = _json_bytes(value)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0), 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # A failed write deliberately leaves the newly-created partial file.
        raise
    return raw


def _refuse(output: Path, identity: Any, error: BaseException) -> None:
    refusal = {
        "status": "refused",
        "identity": identity,
        "pid": os.getpid(),
        "error": {"type": type(error).__name__, "message": str(error)},
    }
    try:
        _exclusive_json(output / "refusal.json", refusal)
    except BaseException:
        # The original callback/publication exception is authoritative.
        pass


def run_once(output_dir: str | os.PathLike[str], identity: Any,
             read_callable: Callable[[], Any]) -> Any:
    """Claim ``output_dir``, invoke ``read_callable`` once, and publish it.

    The directory claim and all files are exclusive.  Failures leave the
    claim and any partial publication in place so a caller cannot silently
    retry or mistake an incomplete readout for a completed one.
    """
    if not callable(read_callable):
        raise TypeError("read_callable must be callable")
    output = Path(output_dir)
    if (not output.is_absolute()
            or any(part in (".", "..") for part in output.parts)):
        raise ValueError("output directory must be absolute without traversal")
    # Serialize the identity before claiming a directory: malformed metadata
    # cannot create an unusable claim.
    _json_bytes({"identity": identity, "pid": os.getpid()})
    parent = output.parent
    _parent_is_safe(parent)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output directory already exists: {output}")
    try:
        os.mkdir(output, 0o700)
    except FileExistsError:
        raise FileExistsError(f"output directory already exists: {output}")
    claim = {"identity": identity, "pid": os.getpid()}
    try:
        _exclusive_json(output / "claim.json", claim)
        result = read_callable()
        result_raw = _exclusive_json(output / "result.json", result)
        receipt = {
            "status": "complete",
            "identity": identity,
            "pid": os.getpid(),
            "result_sha256": hashlib.sha256(result_raw).hexdigest(),
        }
        _exclusive_json(output / "receipt.json", receipt)
        return result
    except BaseException as error:
        _refuse(output, identity, error)
        raise


__all__ = ["run_once"]
