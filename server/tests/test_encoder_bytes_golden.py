"""The guard behind PUBLISHED_SOURCE_SHA256 (cwv_data / cwv_policy).

memory.py, encode.py and encode_versions.py are hashed into every identity at their PRE-CHANGE
digests, because a 2026-09-19 speed change (one Memory per encode instead of two or three) was
proven byte-identical and re-hashing would have refused every archived checkpoint.  Pinning the
digest removes "any edit is caught"; THIS test replaces it with "any byte change ON THESE
SAMPLED STATES is caught": it rebuilds the encoder output and Memory's public surface over
120 deterministic SmartBot states x 4 seats and compares digests to a golden written by the
pre-change tree.  That is a weaker guarantee than a source digest, not a stronger one: a
behavioural change confined to states this sample never visits would pass.  The pin is
therefore for changes ARGUED to be semantics-preserving (a refactor) and checked here; it is
NOT a licence to extend PUBLISHED_SOURCE_SHA256 over a semantic change.  If you change those
files and this fails, you changed the bytes -- then the identity MUST move and this golden
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


#: Computed from a pristine origin/main checkout (6c7380a6) by the same functions; generated,
#: not typed.  Every identity that hashes memory.py / encode.py / encode_versions.py.
PRISTINE = {
    "public": "a55cba182152fa51f2d304fb1b9adb02b6e23f4073f7bad37fe2d6ca1ab31afa",
    "transitive_v1": "56b8f92435b22a57712a4e59b1d3d9fc6639fd613ec2a54da5ec730e171d1d25",
    "transitive_v2": "56b8f92435b22a57712a4e59b1d3d9fc6639fd613ec2a54da5ec730e171d1d25",
    "transitive_v4": "3f341058054c67624eeb8c8e8ef5dc4b94edb1ebb4f9edec238d70b9a206d2d5",
    "transitive_v5": "d73b78fe1fa84d9464cff93ca6faee80e57fdc71ac06894960db8ae5d78cc743",
    "transitive_v6": "79427b8165fade30d790fa6ca8d5adc807757f233cc773377cae285d2ca7c942",
    "cwv_v1": "f0bb58e948b221a16924af512726792cdbe91d2d065b377d50b362ad91e2e523",
    "cwv_v2": "a56679bbd1709a5def52dcb7ee0a2879b760661f8d34556609849dfd09e17fa4",
    "cwv_v4": "d99e7836cc4c89be09a8b1f0c7aa05d8311cfadbe06de7bd525626296f5f1781",
    "cwv_v5": "1543ea186e2ff9183212bc3c7654c92e15d8bca025a98cc987232a3979d2601b",
    "cwv_v6": "1aad1754065924ac5ebe4d1f5616c21bb13882e8f158a599e4e8d129fadf0316",
}


@pytest.mark.parametrize("version", [1, 2, 4, 5, 6])
def test_every_identity_that_hashes_the_pinned_files_is_unchanged(version):
    """The point of the pin: every identity the caches, receipts, archived public-head and CWV
    checkpoints and production's checkpoint carry is exactly what it was before the change --
    the CWV identity (training path, serving path and the loader's INDEPENDENT replica), the
    two-file public-head identity and its cache key, and the transitive contract."""
    from shengji.ai.cwv_policy import afterstate_encoder_identity, local_encoder_identity
    from shengji.rl import encoder_identity
    from shengji.rl.encode import ENCODER_IMPLEMENTATION_SHA256
    from shengji.train import data
    from shengji.train.cwv_data import cwv_encoder_identity
    cwv = PRISTINE[f"cwv_v{version}"]
    assert cwv_encoder_identity(version)["implementation_sha256"] == cwv
    assert afterstate_encoder_identity(version)["implementation_sha256"] == cwv
    assert local_encoder_identity(version)["implementation_sha256"] == cwv
    assert encoder_identity.encoder_contract(version)["implementation_sha256"] == PRISTINE[f"transitive_v{version}"]
    assert ENCODER_IMPLEMENTATION_SHA256 == PRISTINE["public"]
    ident = data.encoder_identity(version)
    assert ident["implementation_sha256"] == PRISTINE["public"]
    assert ident["transitive"]["implementation_sha256"] == PRISTINE[f"transitive_v{version}"]
    assert data.encoder_cache_key(version) == f"v{version}-{PRISTINE['public'][:12]}"


def test_the_source_pin_is_one_table_everywhere():
    from shengji.ai import cwv_policy
    from shengji.rl import encode
    from shengji.train import cwv_data
    assert encode.PUBLISHED_SOURCE_SHA256 == cwv_data.PUBLISHED_SOURCE_SHA256 == cwv_policy.PUBLISHED_SOURCE_SHA256


def test_an_archived_public_head_checkpoint_still_passes_both_public_head_gates(tmp_path):
    """Codex, #499 review: the first pin covered the CWV identity only, and train_v0.load_checkpoint
    refused an archived public head ("checkpoint encoder a55cba182152 differs from the current
    encoder 1cbcacabb4dd").  A checkpoint carrying the PRE-CHANGE public identity must load
    through train_v0.load_checkpoint and cwv_eval.load_public_head."""
    import torch
    from shengji.train import train_v0
    from shengji.train.cwv_eval import load_public_head
    from shengji.train.train_v0 import ValuePriorNet
    cfg = train_v0.build_config(data=["never-opened"], hidden=8, encoder_version=2)
    population = train_v0.fit_population({"deal:a": "train", "deal:b": "val", "deal:c": "test"}, stores=[])
    path = tmp_path / "archived-public-v2.pt"
    train_v0.save_checkpoint(path, ValuePriorNet(cfg["arch"]), config=cfg, epoch=1, selection={},
                             baselines={}, calibration=None, split={}, population=population)
    payload = torch.load(path, map_location="cpu", weights_only=False)
    # what an archived checkpoint carries: the pre-change public identity, verbatim
    assert payload["encoder"]["implementation_sha256"] == PRISTINE["public"]
    payload["encoder"] = {**payload["encoder"], "implementation_sha256": PRISTINE["public"],
                          "enc_version": 2, "transitive": {"implementation_sha256": PRISTINE["transitive_v2"]}}
    torch.save(payload, path)
    train_v0.load_checkpoint(path, torch.device("cpu"))
    load_public_head(str(path), "cpu")
