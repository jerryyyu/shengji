"""Encoder v4 (issue #341): opponent pair caps, pairs played per suit and trump,
unseen per suit.  Public information only; v1/v2 bytes untouched; 3 reserved."""
import copy
import random
from collections import Counter

import pytest

from shengji.ai.memory import Memory
from shengji.engine.cards import SUITS, TRUMP
from shengji.rl import encode_versions as ev
from shengji.rl.encode_opponent_pairs import (N_OPPONENT_PAIR_COLUMNS, OPPONENT_PAIR_COLUMNS,
                                              opponent_pair_columns)
from shengji.rl.encoder_identity import encoder_contract
from tests.test_world_shortlist import play_state
# the trainer fixture family is module-local to test_cwv_train; importing registers it
from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401

SUITS_EFF = tuple(SUITS) + (TRUMP,)


def test_layout_widths_and_reserved_three():
    assert N_OPPONENT_PAIR_COLUMNS == 75 and len(OPPONENT_PAIR_COLUMNS) == 75
    assert ev.OBS_DIM_BY_VERSION[4] == ev.OBS_DIM_BY_VERSION[2] + 75 == 635
    assert ev.ENC_VERSION_MAX == 4
    with pytest.raises(ValueError):
        ev.check_version(3)          # Codex's own-hand block; not defined on this branch


def test_v4_extends_v2_without_disturbing_its_bytes():
    rnd = play_state(); seat = rnd.turn
    v2 = ev.encode_obs(rnd, seat, version=2)
    v4 = ev.encode_obs(rnd, seat, version=4)
    assert len(v4) == 635 and v4[:560] == v2
    assert ev.encode_obs(rnd, seat, version=1) == v2[:531]


def test_columns_are_computed_from_public_state_only():
    """Swapping a hidden card between the two OPPONENTS changes no public fact,
    so the v4 block must be byte-identical; the world planes are not consulted."""
    rnd = play_state(); seat = rnd.turn
    before = ev.encode_obs(rnd, seat, version=4)[560:]
    other = copy.deepcopy(rnd)
    a, b = (seat + 1) % 4, (seat + 3) % 4
    ca, cb = other.hands[a][0], other.hands[b][0]
    if ca == cb:
        pytest.skip("first cards equal; no swap possible")
    other.hands[a][0], other.hands[b][0] = cb, ca
    assert ev.encode_obs(other, seat, version=4)[560:] == before


def test_unseen_and_pairs_possible_match_the_memory():
    rnd = play_state(); seat = rnd.turn
    mem = Memory(rnd, seat, own_kitty=False)
    cols = dict(zip(OPPONENT_PAIR_COLUMNS, opponent_pair_columns(rnd, seat, mem)))
    o = rnd.ordering
    for s in SUITS_EFF:
        unseen = sum(n for c, n in mem.unseen.items() if o.eff_suit(c) == s)
        possible = sum(1 for c, n in mem.unseen.items() if n >= 2 and o.eff_suit(c) == s)
        assert cols[f"unseen_frac:{s}"] == pytest.approx(unseen / 27.0)
        assert cols[f"pairs_possible_frac:{s}"] == pytest.approx(possible / 13.0)


def test_pair_cap_flags_are_one_hot_and_agree_with_the_memory():
    rnd = play_state(); seat = rnd.turn
    mem = Memory(rnd, seat, own_kitty=False)
    cols = dict(zip(OPPONENT_PAIR_COLUMNS, opponent_pair_columns(rnd, seat, mem)))
    for rel in (1, 2, 3):
        other = (seat + rel) % 4
        for s in SUITS_EFF:
            flags = [cols[f"pair_cap:{rel}:{s}:{st}"] for st in ("zero", "at_most_one", "unknown")]
            assert sum(flags) == 1.0
            cap = mem.max_pairs(other, s)
            assert flags == [float(cap == 0), float(cap == 1), float(cap is None)]


def test_pairs_played_counts_pairs_played_together_not_copies_over_time():
    rnd = play_state(); seat = rnd.turn
    mem = Memory(rnd, seat, own_kitty=False)
    cols = dict(zip(OPPONENT_PAIR_COLUMNS, opponent_pair_columns(rnd, seat, mem)))
    o = rnd.ordering
    expect_all, expect_by = Counter(), {s: Counter() for s in range(4)}
    tricks = list(rnd.history) + ([rnd.trick] if rnd.trick and rnd.trick.plays else [])
    for t in tricks:
        for tp in t.plays:
            for card, n in Counter(tp.cards).items():
                if n >= 2:
                    expect_all[o.eff_suit(card)] += n // 2
                    expect_by[tp.seat][o.eff_suit(card)] += n // 2
    for s in SUITS_EFF:
        assert cols[f"pairs_played_frac:{s}"] == pytest.approx(expect_all[s] / 13.0)
        for rel in (1, 2, 3):
            assert cols[f"pairs_played_by_frac:{rel}:{s}"] == pytest.approx(
                expect_by[(seat + rel) % 4][s] / 13.0)
    # a hand-built history witness: one pair played together counts once, two
    # copies on different tricks count zero
    from types import SimpleNamespace
    two_copies_apart = SimpleNamespace(plays=[SimpleNamespace(seat=0, cards=["S5"]),
                                              SimpleNamespace(seat=1, cards=["S5"])])
    together = SimpleNamespace(plays=[SimpleNamespace(seat=0, cards=["S5", "S5"])])
    from shengji.rl.encode_opponent_pairs import _pairs_in_play
    assert sum(_pairs_in_play(p.cards, o)[o.eff_suit("S5")] for p in two_copies_apart.plays) == 0
    assert _pairs_in_play(together.plays[0].cards, o)[o.eff_suit("S5")] == 1


def test_a_proven_pair_cap_reaches_the_net_on_some_real_round():
    """Play random legal rounds with the heuristic until a follower proves a
    pair cap, then check the flag is set for the actor who can see it."""
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.round import Round
    bot = HeuristicBot()
    for attempt in range(60):
        rnd = play_state(seed=attempt) if "seed" in play_state.__code__.co_varnames else play_state()
        rng = random.Random(attempt)
        steps = 0
        while rnd.phase == "play" and steps < 40:
            s = rnd.turn
            rnd.play(s, bot.decide_play(rnd, s))
            steps += 1
            for seat in range(4):
                mem = Memory(rnd, seat, own_kitty=False)
                for other in range(4):
                    if other == seat:
                        continue
                    for suit, cap in mem.pair_cap[other].items():
                        if cap == 0:
                            cols = dict(zip(OPPONENT_PAIR_COLUMNS,
                                            opponent_pair_columns(rnd, seat, mem)))
                            rel = (other - seat) % 4
                            assert cols[f"pair_cap:{rel}:{suit}:zero"] == 1.0
                            return
    pytest.skip("no pair cap proven in 60 random rounds")


def test_identity_for_v4_binds_its_own_files_and_leaves_v2_alone():
    c2, c4 = encoder_contract(2), encoder_contract(4)
    assert set(c2["source_sha256s"]) == {"cards", "combos", "encode", "memory"}
    assert set(c4["source_sha256s"]) == set(c2["source_sha256s"]) | {"encode_versions", "encode_opponent_pairs"}
    assert c4["layout_version"] == 4 and c4["schema"] == "rl-observation-v4-opponent-pairs"
    assert c4["implementation_sha256"] != c2["implementation_sha256"]


def test_encoder_v4_net_trains_loads_verifies_and_scores_a_real_shortlist_decision(
        store_dir, tmp_path):
    """The actual consumers: trainer, cache flavour, checkpoint identity gate, and a
    real W32 shortlist decision under both encodings, at width 636."""
    import numpy as np
    from shengji.ai.cwv_policy import load_cwv_checkpoint, verify_checkpoint_identity
    from shengji.train import cwv_data, train_cwv
    from tests.test_cwv_train import THIRDS, _shortlist_decision

    kw = dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=1, seed=7, batch_size=64,
              n_boot=10, hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32,
              val_rank_records=50, **THIRDS)
    receipt = train_cwv.train(out=tmp_path / "v4", encoder_version=4, **kw)
    assert receipt["config"]["encoder_version"] == 4
    assert receipt["config"]["model_config"]["public_dim"] == 636
    assert receipt["encoder"]["enc_version"] == 4
    assert receipt["encoder"]["implementation_sha256"] == \
        cwv_data.cwv_encoder_identity(4)["implementation_sha256"]
    assert receipt["encoder"]["implementation_sha256"] != \
        cwv_data.cwv_encoder_identity(2)["implementation_sha256"]
    cache = next((tmp_path / "v4" / "cache").glob("*.cwv-v4-*.npz"))
    assert np.load(cache)["public"].shape[1] == 636

    checkpoint = tmp_path / "v4" / "best.pt"
    model, metadata, _sha = load_cwv_checkpoint(checkpoint)
    assert model.config.public_dim == 636 and model.config.enc_version == 4
    assert verify_checkpoint_identity(metadata) == \
        cwv_data.cwv_encoder_identity(4)["implementation_sha256"]
    for encoding in ("reference", "mlp-static"):
        evaluator, widths, fused = _shortlist_decision(checkpoint, encoding=encoding)
        assert evaluator.enc_version == 4
        assert widths and set(widths) == {636}, (encoding, widths)
        # v4 has no fused static base yet: both encodings take the reference route
        assert fused == [], (encoding, fused)


def test_cwv_identity_cache_key_and_checkpoint_check_bind_the_v4_files(monkeypatch):
    """A changed v4 feature-source hash must change the v4 CWV identity, the
    cache key and the serving replica, and refuse a checkpoint stamped before
    the change, while leaving the v2 identity and its cache key untouched."""
    from shengji.ai import cwv_policy
    from shengji.train import cwv_data

    v2_before, v4_before = cwv_data.cwv_encoder_identity(2), cwv_data.cwv_encoder_identity(4)
    assert set(v2_before["source_sha256s"]) == set(cwv_data.CWV_SOURCE_PATHS)
    assert set(v4_before["source_sha256s"]) == set(cwv_data.CWV_SOURCE_PATHS) | {"encode_versions", "encode_opponent_pairs"}
    assert v4_before["public_head_encoder_contract_sha256"] == encoder_contract(4)["implementation_sha256"]
    assert v2_before["public_head_encoder_contract_sha256"] == encoder_contract(2)["implementation_sha256"]
    assert cwv_policy.local_encoder_identity(4)["implementation_sha256"] == v4_before["implementation_sha256"]
    assert cwv_policy.local_encoder_identity(2)["implementation_sha256"] == v2_before["implementation_sha256"]
    key2_before, key4_before = cwv_data.encoder_cache_key(2), cwv_data.encoder_cache_key(4)
    # A checkpoint stamped at today's v4 identity verifies today.
    cwv_policy.verify_checkpoint_identity({"encoder": v4_before})

    real = cwv_data.sha256_file

    def edited(path):
        digest = real(path)
        return "0" * 64 if str(path).endswith("encode_opponent_pairs.py") else digest
    monkeypatch.setattr(cwv_data, "sha256_file", edited)
    monkeypatch.setattr(cwv_policy, "file_sha256", edited)

    v2_after, v4_after = cwv_data.cwv_encoder_identity(2), cwv_data.cwv_encoder_identity(4)
    assert v2_after["implementation_sha256"] == v2_before["implementation_sha256"]
    assert cwv_data.encoder_cache_key(2) == key2_before
    assert v4_after["implementation_sha256"] != v4_before["implementation_sha256"]
    assert cwv_data.encoder_cache_key(4) != key4_before
    assert cwv_policy.local_encoder_identity(4)["implementation_sha256"] == v4_after["implementation_sha256"]
    with pytest.raises(cwv_policy.CWVCheckpointMismatch):
        cwv_policy.verify_checkpoint_identity({"encoder": v4_before})
    cwv_policy.verify_checkpoint_identity({"encoder": v4_after})
    cwv_policy.verify_checkpoint_identity({"encoder": v2_before})
