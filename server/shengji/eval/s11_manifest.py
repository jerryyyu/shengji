"""Bind the S11 deal draw to a complete, authenticated trajectory inventory.

This is a bytes-to-schedule adapter, not an exposure/seal certification or a
file reader. The expected manifest digest comes from the reviewed frame, not
from the supplied bytes. No outcomes, sidecars or shard contents are consulted.
Selected shards still require byte authentication, normalization and terminal
reconstruction before the position draw can be used. Never replace a refusal.
"""
from dataclasses import dataclass
import hashlib
import json
import math

from .s11_selection import DEAL_COUNT, select_deals, select_mirror


@dataclass(frozen=True)
class SelectedShard:
    manifest_sha256: str
    draw_index: int
    run_id: str
    cluster: int
    seed: int
    mirror: int
    path: str
    sha256: str
    byte_count: int
    record_count: int


def _sha(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("lowercase SHA256 required")
    return value


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {name}")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"nonfinite JSON: {value}")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        _constant(value)
    return result


def select_manifest_shards(raw: bytes, *, sha256: str) -> tuple[SelectedShard, ...]:
    """Authenticate all inventory entries, then return exactly 64 in draw order.

    ``rounds`` counts both mirrors, whereas ``clusters`` counts distinct deals.
    The native producer requires contiguous clusters, seeds ``seed0+cluster``,
    and canonical shard paths. Check the entire inventory, including unselected
    entries: accepting a shortened or malformed frame would change the draw.
    The digest also binds ignored fields, so this does not promise invariance
    when a manifest is rewritten (even if only its outcome counters changed).
    """
    if type(raw) is not bytes:
        raise ValueError("raw manifest bytes required")
    _sha(sha256)
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("manifest SHA256 mismatch before JSON access")
    manifest = json.loads(raw, object_pairs_hook=_object,
                          parse_constant=_constant, parse_float=_float)
    if type(manifest) is not dict:
        raise ValueError("manifest must be an object")
    if (manifest.get("schema") != "shengji-trajectory-manifest-v1"
            or manifest.get("record_schema") != "shengji-decision-record-v1"
            or manifest.get("source") != "trajectory"):
        raise ValueError("unsupported trajectory manifest schema/source")
    run_id = manifest.get("run_id")
    if type(run_id) is not str or not run_id or ":" in run_id:
        raise ValueError("invalid run_id")
    seed0 = _integer(manifest.get("seed0"), "seed0")
    clusters = _integer(manifest.get("clusters"), "clusters", DEAL_COUNT)
    rounds = _integer(manifest.get("rounds"), "rounds", 2 * DEAL_COUNT)
    if rounds != 2 * clusters:
        raise ValueError("rounds must equal twice the complete cluster count")
    config = manifest.get("config")
    if (type(config) is not dict or config.get("run_id") != run_id
            or type(config.get("seed0")) is not int or config["seed0"] != seed0):
        raise ValueError("manifest/config identity mismatch")
    shards = manifest.get("shards")
    if type(shards) is not list or len(shards) != clusters:
        raise ValueError("complete shard inventory required")
    by_seed = {}
    for cluster, shard in enumerate(shards):
        if type(shard) is not dict:
            raise ValueError("shard inventory entry must be an object")
        if _integer(shard.get("cluster"), "cluster") != cluster:
            raise ValueError("clusters must be contiguous and ordered from zero")
        seed = _integer(shard.get("seed"), "seed")
        if seed != seed0 + cluster:
            raise ValueError("shard seed must equal seed0 + cluster")
        if shard.get("path") != f"shards/cluster-{cluster:06d}.jsonl":
            raise ValueError("noncanonical shard path")
        _sha(shard.get("sha256"))
        _integer(shard.get("bytes"), "shard bytes", 1)
        _integer(shard.get("records"), "shard records", 1)
        by_seed[seed] = shard
    selected = select_deals(sha256, list(by_seed))
    return tuple(SelectedShard(
        manifest_sha256=sha256, draw_index=index, run_id=run_id,
        cluster=by_seed[seed]["cluster"], seed=seed,
        mirror=select_mirror(sha256, seed), path=by_seed[seed]["path"],
        sha256=by_seed[seed]["sha256"], byte_count=by_seed[seed]["bytes"],
        record_count=by_seed[seed]["records"],
    ) for index, seed in enumerate(selected))
