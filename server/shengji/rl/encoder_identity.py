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

from .encode import PUBLISHED_SOURCE_SHA256
from .encode_versions import ENC_VERSION, OBS_SCHEMA_BY_VERSION, check_version


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


#: Versions >= 4 include the DISPATCHER (``encode_versions.py``) in their source
#: closure, so publishing any later version would otherwise move an older one's
#: ``implementation_sha256`` -- orphaning its caches (176,002 v4 shard files on
#: the trainer when v5 was written) and refusing its archived checkpoints.  A
#: published version therefore pins the dispatcher digest it was published with;
#: its OWN block is still hashed live, and ``tests/data/encoder_v4_golden.json``
#: pins the bytes the dispatcher actually produces for it, so behavioural drift
#: is caught by the vector rather than by the file hash.
PUBLISHED_DISPATCHER_SHA256 = {
    4: "aa8528a636f5d59a326afbf7826043a9fcd670ddb610e36ca78f551c3c60a88b",
}


def source_paths(version: int = ENC_VERSION) -> dict[str, Path]:
    """The executable dependency closure of encoder ``version``.

    v1 and v2 keep the frozen four-file closure (their archived identities
    must keep matching).  Later versions add the files that compute their own
    columns, and ONLY those: v4's closure must not move because v5 exists, so
    each version names its block explicitly rather than accumulating."""
    version = check_version(version)
    paths = dict(SOURCE_PATHS)
    if version >= 4:
        here = Path(__file__).resolve()
        paths["encode_versions"] = here.with_name("encode_versions.py")
        if version == 4:
            paths["encode_opponent_pairs"] = here.with_name("encode_opponent_pairs.py")
        if version == 5:
            paths["encode_banker_kitty"] = here.with_name("encode_banker_kitty.py")
        if version == 6:
            # v6 EXECUTES this module, so its bytes must be in the identity or a change to
            # the correction would leave every v6 cache file and checkpoint validating
            # against a stale digest -- the hazard #476 fixed for v4.
            paths["encode_banker_kitty_corrected"] = here.with_name("encode_banker_kitty_corrected.py")
    return paths


def source_sha256s(version: int = ENC_VERSION) -> dict[str, str]:
    """The digest of every file encoder ``version`` executes.

    The dispatcher's entry is pinned for a published version (see
    ``PUBLISHED_DISPATCHER_SHA256``); every other file is hashed live."""
    version = check_version(version)
    digests = {name: sha256_file(path) for name, path in source_paths(version).items()}
    # The 2026-09-19 speed change (encode.PUBLISHED_SOURCE_SHA256): byte-identical output,
    # hashed at the pre-change digests; applied BEFORE the dispatcher pin so a published
    # version's dispatcher digest still wins.
    for name, digest in PUBLISHED_SOURCE_SHA256.items():
        if name in digests:
            digests[name] = digest
    pinned = PUBLISHED_DISPATCHER_SHA256.get(version)
    if pinned is not None and "encode_versions" in digests:
        digests["encode_versions"] = pinned
    return digests


def implementation_sha256(sources: dict[str, str], version: int = ENC_VERSION) -> str:
    if set(sources) != set(source_paths(version)):
        raise ValueError("encoder source identity has missing or extra files")
    payload = "|".join(
        f"{name}:{digest}" for name, digest in sorted(sources.items())
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def encoder_contract(version: int = ENC_VERSION) -> dict:
    """The transitive source contract for encoder ``version``.

    The version is part of the contract: two caches or checkpoints built by
    the same sources but different layouts must not compare equal.
    """
    version = check_version(version)
    sources = source_sha256s(version)
    return {
        "identity_schema": IDENTITY_SCHEMA,
        "schema": OBS_SCHEMA_BY_VERSION[version],
        "layout_version": version,
        "implementation_sha256": implementation_sha256(sources, version),
        "source_sha256s": sources,
    }

