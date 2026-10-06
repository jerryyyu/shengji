"""Authenticate and normalize one PVC shard, without selecting on its labels.

Caller supplies pins from the independently authenticated frozen manifest.
This helper does not establish corpus eligibility, read files, choose mirrors,
or prove legal/terminal replay. Send its ordered rows to reconstruction before
using their count for the frozen position draw. Never substitute another shard
or mirror after refusal.
"""
import hashlib
import json


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {label}")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError(f"nonfinite JSON: {value}")


def mirror_play_rows(raw, *, sha256, record_count, run_id, cluster, seed, mirror):
    """Return all play rows for the requested mirror, in contiguous ply order.

    Native shard order is mirror/seat/ply, not chronological. Both mirrors'
    coordinates are checked; labels are parsed but never used for filtering.
    Bury rows alone are excluded by an explicit, validated decision-kind rule.
    """
    if type(raw) is not bytes:
        raise ValueError("raw shard bytes required")
    if (type(sha256) is not str or len(sha256) != 64
            or any(c not in "0123456789abcdef" for c in sha256)):
        raise ValueError("lowercase shard SHA256 required")
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("shard SHA256 mismatch before JSON access")
    _integer(record_count, "record count", 1)
    _integer(cluster, "cluster")
    _integer(seed, "seed")
    if type(mirror) is not int or mirror not in (0, 1):
        raise ValueError("mirror must be 0 or 1")
    if type(run_id) is not str or not run_id or ":" in run_id:
        raise ValueError("invalid run_id")
    lines = raw.decode("utf-8").splitlines()
    if len(lines) != record_count or any(not line.strip() for line in lines):
        raise ValueError("shard record count or blank record mismatch")
    plays = {0: {}, 1: {}}
    buries = set()
    for line in lines:
        row = json.loads(line, object_pairs_hook=_object, parse_constant=_nonfinite)
        if type(row) is not dict:
            raise ValueError("record must be an object")
        ref = row.get("source_ref")
        parts = ref.split(":") if type(ref) is str else []
        if len(parts) != 5 or parts[:2] != [run_id, str(cluster)]:
            raise ValueError("record run/cluster mismatch")
        if parts[2] not in ("0", "1") or parts[3] not in ("0", "1", "2", "3"):
            raise ValueError("invalid mirror/seat coordinate")
        m, seat = int(parts[2]), int(parts[3])
        if type(row.get("seat")) is not int or row["seat"] != seat:
            raise ValueError("record seat mismatch")
        if type(row.get("round_seed")) is not int or row["round_seed"] != seed:
            raise ValueError("record seed mismatch")
        kind = row.get("decision_kind")
        if kind == "bury":
            if (parts[4] != "bury" or row.get("ply") is not None
                    or row.get("plays_prefix") != [] or m in buries):
                raise ValueError("invalid or duplicate bury record")
            buries.add(m)
        elif kind == "play":
            ply = row.get("ply")
            _integer(ply, "ply")
            if parts[4] != str(ply) or ply in plays[m]:
                raise ValueError("invalid or duplicate play coordinate")
            plays[m][ply] = row
        else:
            raise ValueError("unknown decision kind")
    for values in plays.values():
        if not 1 <= len(values) <= 100 or sorted(values) != list(range(len(values))):
            raise ValueError("both mirrors need contiguous complete play indices")
    return [plays[mirror][ply] for ply in range(len(plays[mirror]))]
