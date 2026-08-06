"""Versioned transitive source identity for future RL encoder consumers.

``encode.ENCODER_SOURCE_SHA256S`` is part of the immutable corrected-V11 v2
protocol at commit cde0fec and intentionally remains its historical two-file
receipt.  New experiments must use this module instead: action vectors execute
``combos.decompose`` and card/trump helpers, so those engine sources are part of
the encoder implementation even when ``ENC_VERSION`` and ``encode.py`` do not
change.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .encode import ENC_VERSION, OBS_SCHEMA


IDENTITY_SCHEMA = "rl-encoder-transitive-source-contract-v1"
_SHENGJI = Path(__file__).resolve().parents[1]
SOURCE_PATHS = {
    "cards": _SHENGJI / "engine" / "cards.py",
    "combos": _SHENGJI / "engine" / "combos.py",
    "encode": Path(__file__).resolve().with_name("encode.py"),
    "memory": _SHENGJI / "ai" / "memory.py",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_sha256s() -> dict[str, str]:
    """Rehash the exact executable dependency closure on every call."""
    return {name: sha256_file(path) for name, path in SOURCE_PATHS.items()}


def implementation_sha256(sources: dict[str, str]) -> str:
    if set(sources) != set(SOURCE_PATHS):
        raise ValueError("encoder source identity has missing or extra files")
    payload = "|".join(
        f"{name}:{digest}" for name, digest in sorted(sources.items())
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def encoder_contract() -> dict:
    sources = source_sha256s()
    return {
        "identity_schema": IDENTITY_SCHEMA,
        "schema": OBS_SCHEMA,
        "layout_version": ENC_VERSION,
        "implementation_sha256": implementation_sha256(sources),
        "source_sha256s": sources,
    }

