"""Opt-in population binding for value-only additions; no I/O or split fallback.

Callers supply authenticated base-population pins separately from the manifest
and identify base and added stores separately. This module does not authenticate
store provenance, candidate tensors, or the effective policy-row receipt.
"""
from collections.abc import Mapping, Sequence
import hashlib
import re
import json
from pathlib import Path

PARTS = ("train", "val", "test")
SCHEMA = "shengji-frozen-population-v1"


def _keys(values, label):
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(k, str) or re.fullmatch(r"deck:[0-9a-f]{64}", k) is None
        for k in values
    ):
        raise ValueError(f"{label}: full deal-key list required")
    result = set(values)
    if len(result) != len(values):
        raise ValueError(f"{label}: duplicate deal keys")
    return result


def bind_frozen_population(manifest: Mapping, *, expected_digests: Mapping,
                           base_keys: Sequence[str], added_keys: Sequence[str]):
    """Keep every base assignment; add only explicitly named, disjoint fit deals.

    Reject any missing/extra base key and any addition colliding with the base
    (including train). Never silently repartition or exclude a pinned deal.
    Caller must recheck the resulting val/test after init-exposure processing.
    """
    if not isinstance(manifest, Mapping) or set(manifest) != {"schema", *PARTS}:
        raise ValueError("invalid frozen population manifest fields")
    if manifest["schema"] != SCHEMA:
        raise ValueError("invalid frozen population schema")
    if not isinstance(expected_digests, Mapping) or set(expected_digests) != set(PARTS):
        raise ValueError("independent train/val/test digest pins required")
    assignment = {}
    for part in PARTS:
        keys = _keys(manifest[part], part)
        if not keys:
            raise ValueError(f"{part}: empty frozen partition")
        digest = hashlib.sha256("\n".join(sorted(keys)).encode()).hexdigest()
        if digest != expected_digests[part]:
            raise ValueError(f"{part}: frozen digest mismatch")
        if keys & assignment.keys():
            raise ValueError("overlapping frozen partitions")
        assignment.update(dict.fromkeys(keys, part))
    base = _keys(base_keys, "base stores")
    added = _keys(added_keys, "added stores")
    if base != assignment.keys():
        raise ValueError("base stores differ from frozen population")
    if added & base:
        raise ValueError("added stores collide with frozen base")
    assignment.update(dict.fromkeys(added, "train"))
    return assignment


def load_contract(path, sha256):
    """Read one externally pinned input; JSON duplicate keys are refused."""
    if (path is None) != (sha256 is None):
        raise ValueError("frozen population path and sha256 must be supplied together")
    if path is None:
        return None
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("frozen population contract sha256 mismatch")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate frozen contract field")
            result[key] = value
        return result
    contract = json.loads(raw, object_pairs_hook=pairs)
    required = {"schema", "population", "digests", "added_stores", "candidates", "policy_identity"}
    if not isinstance(contract, dict) or set(contract) != required:
        raise ValueError("invalid frozen contract fields")
    if contract["schema"] != "shengji-frozen-training-contract-v1":
        raise ValueError("invalid frozen training contract schema")
    roots = contract["added_stores"]
    if not isinstance(roots, list) or not roots or any(
        not isinstance(p, str) or not Path(p).is_absolute() for p in roots
    ) or len({str(Path(p).resolve()) for p in roots}) != len(roots):
        raise ValueError("distinct absolute added-store roots required")
    cands = contract["candidates"]
    if not isinstance(cands, dict) or set(cands) != {"val", "test"} or any(
        not isinstance(v, str) or re.fullmatch(r"[0-9a-f]{64}", v) is None
        for v in cands.values()
    ):
        raise ValueError("val/test candidate digest pins required")
    identity = contract["policy_identity"]
    if not isinstance(identity, dict) or not {"rows_used", "fit_deals_digest"} <= identity.keys():
        raise ValueError("effective policy identity required")
    return contract


def bind_store(contract, store):
    added_roots = {str(Path(p).resolve()) for p in contract["added_stores"]}
    base, added, seen = set(), set(), set()
    for index, (shard, _cache) in enumerate(store.entries):
        root = str(Path(shard.store).resolve())
        seen.add(root)
        (added if root in added_roots else base).update(store.keys_of(index))
    if not added_roots <= seen or not added:
        raise ValueError("added stores missing or empty")
    return bind_frozen_population(contract["population"], expected_digests=contract["digests"],
                                  base_keys=sorted(base), added_keys=sorted(added))


def require_policy_identity(contract, identity):
    if identity != contract["policy_identity"]:
        raise ValueError("effective policy rows differ from frozen base receipt")
