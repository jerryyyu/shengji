"""Outcome-blind S11 frame selection; no IO or provenance certification.

The caller must authenticate a frozen inventory before selecting deals, and
verify a complete chosen mirror before supplying its play count. Missing or
invalid selected inputs are failures, never reasons to draw replacements.
"""
from __future__ import annotations

import hashlib
import json


DOMAIN = "s11a-pvc-frame-v1"
DEAL_COUNT = 64


def _seed(value):
    if type(value) is not int or value < 0:
        raise ValueError("deal seed must be a nonnegative integer")
    return value


def _key(manifest_sha, stage, *coordinates):
    if (type(manifest_sha) is not str or len(manifest_sha) != 64
            or any(c not in "0123456789abcdef" for c in manifest_sha)):
        raise ValueError("lowercase manifest SHA256 required")
    raw = json.dumps([DOMAIN, manifest_sha, stage, *coordinates],
                     separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(raw).digest()


def select_deals(manifest_sha, deal_seeds):
    """Return exactly 64 hash-ordered distinct seeds from the full inventory."""
    if type(deal_seeds) not in (list, tuple):
        raise ValueError("complete seed inventory list required")
    seeds = [_seed(seed) for seed in deal_seeds]
    if len(seeds) != len(set(seeds)) or len(seeds) < DEAL_COUNT:
        raise ValueError("inventory must contain at least 64 distinct seeds")
    return sorted(seeds, key=lambda seed: (_key(manifest_sha, "deal", seed), seed))[:DEAL_COUNT]


def select_mirror(manifest_sha, deal_seed):
    """Pick mirror 0 or 1, independent of availability; no fallback mirror."""
    return _key(manifest_sha, "mirror", _seed(deal_seed))[-1] & 1


def select_ply(manifest_sha, deal_seed, mirror, play_count):
    """Pick from every play in a complete mirror, excluding only bury records.

    A standard round has 100 playable cards, hence at most 100 play decisions.
    The caller authenticates contiguous plies 0..play_count-1; this function
    cannot detect an inventory fabricated by dropping inconvenient positions.
    """
    _seed(deal_seed)
    if type(mirror) is not int or mirror != select_mirror(manifest_sha, deal_seed):
        raise ValueError("mirror differs from frozen selection")
    if type(play_count) is not int or not 1 <= play_count <= 100:
        raise ValueError("complete mirror play count must be 1..100")
    return min(range(play_count), key=lambda ply: (
        _key(manifest_sha, "ply", deal_seed, mirror, ply), ply))
