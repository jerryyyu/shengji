"""The guard behind PUBLISHED_SOURCE_SHA256 (cwv_data / cwv_policy).

memory.py, encode.py and encode_versions.py are hashed into every identity at their PRE-CHANGE
digests, because a 2026-09-19 speed change (one Memory per encode instead of two or three) was
proven byte-identical and re-hashing would have refused every archived checkpoint.  Pinning the
digest removes "any edit is caught"; THIS test replaces it with the stronger "any byte change is
caught": it rebuilds the encoder output and Memory's public surface over deterministic real
states and compares digests to a golden written by the pre-change tree.  If you change those
files and this fails, you changed the bytes -- and then the identity MUST move and this golden
MUST NOT simply be regenerated.
"""
import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).parent / "data" / "encoder_bytes_golden.json"


def _regenerate():
    import copy, hashlib, random
    import numpy as np
    from shengji.ai.memory import Memory
    from shengji.ai.smart import SmartBot
    from shengji.engine.cards import make_deck
    from shengji.engine.game import Game
    from shengji.rl.encode_versions import encode_obs
    g = json.loads(GOLDEN.read_text())
    codes = sorted(set(make_deck()))

    def surface(m):
        o = m.o; suits = sorted({o.eff_suit(c) for c in codes})
        return {"seat": m.seat, "own": m.own_kitty_known, "played": sorted(m.played.items()),
                "played_by": {s: sorted(m.played_by[s].items()) for s in range(4)},
                "voids": {s: sorted(m.voids[s]) for s in range(4)},
                "pair_cap": {s: sorted(m.pair_cap[s].items()) for s in range(4)},
                "run_cap": {s: sorted(m.run_cap[s].items()) for s in range(4)},
                "known": sorted(m.known.items()), "unseen_ordered": list(m.unseen.items()),
                "is_boss": [m.is_boss(c) for c in codes], "pair_is_boss": [m.pair_is_boss(c) for c in codes],
                "points_left": [m.points_left(None)] + [m.points_left(s) for s in suits],
                "ruff_risk": [[m.ruff_risk(su, [s]) for su in suits] for s in range(4)]}
    rows = []
    bot = SmartBot(); n = g["digest_hex_chars"]
    for sd in g["seeds"]:
        gm = Game(random.Random(sd)); rnd = gm.start_round()
        while rnd.phase == "deal": rnd.deal_next()
        for s in range(4):
            c = bot.decide_declare(rnd, s, final=True)
            if c: rnd.declare(s, c)
        rnd.finalize_declare(); rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
        plays = 0
        for d in g["depths"]:
            while plays < d and rnd.phase == "play":
                rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn)); plays += 1
            snap = copy.deepcopy(rnd); rec = {"seed": sd, "depth": d, "banker": snap.banker}
            for seat in range(4):
                for v in g["versions"]:
                    x = np.asarray(encode_obs(snap, seat, version=v), dtype=np.float32)
                    rec[f"v{v}_s{seat}"] = hashlib.sha256(x.tobytes()).hexdigest()[:n]
                for own in (0, 1):
                    j = json.dumps(surface(Memory(snap, seat, own_kitty=bool(own))), sort_keys=True, separators=(",", ":"))
                    rec[f"mem_s{seat}_own{own}"] = hashlib.sha256(j.encode()).hexdigest()[:n]
            rows.append(rec)
    return g, rows


def test_encoder_bytes_and_memory_surface_match_the_pre_change_golden():
    g, rows = _regenerate()
    assert len(rows) == len(g["rows"]) == len(g["seeds"]) * len(g["depths"])
    bad = [(a["seed"], a["depth"], k) for a, b in zip(g["rows"], rows) for k in a if a[k] != b[k]]
    assert not bad, f"{len(bad)} digest(s) differ from the pre-change golden, first: {bad[:5]}"


def test_pinned_source_digests_are_the_pre_change_ones_and_the_two_tables_agree():
    from shengji.ai import cwv_policy
    from shengji.train import cwv_data
    assert cwv_data.PUBLISHED_SOURCE_SHA256 == cwv_policy.PUBLISHED_SOURCE_SHA256
    assert set(cwv_data.PUBLISHED_SOURCE_SHA256) == {"memory", "encode", "encode_versions"}
    for digest in cwv_data.PUBLISHED_SOURCE_SHA256.values():
        assert len(digest) == 64 and int(digest, 16) >= 0


@pytest.mark.parametrize("version,expected", [(2, "a56679bbd170"), (4, "d99e7836cc4c"),
                                              (5, "1543ea186e2f"), (6, "1aad17540659")])
def test_every_published_identity_is_unchanged_by_the_speed_change(version, expected):
    """The point of the pin: the identities the caches, receipts and production's checkpoint
    carry are exactly what they were before memory.py/encode.py/encode_versions.py changed."""
    from shengji.ai.cwv_policy import afterstate_encoder_identity, local_encoder_identity
    from shengji.train.cwv_data import cwv_encoder_identity
    assert cwv_encoder_identity(version)["implementation_sha256"][:12] == expected
    assert afterstate_encoder_identity(version)["implementation_sha256"][:12] == expected
    # the loader's INDEPENDENT replica, not the cwv_data path it prefers when importable
    assert local_encoder_identity(version)["implementation_sha256"][:12] == expected
