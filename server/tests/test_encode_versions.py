"""The encoder is ADDITIVE: v1 keeps its bytes, v2 extends them.

PR #283 raised ENC_VERSION by REPLACING v1, which orphaned every archived
checkpoint and the registry bots built on them.  These are the contracts a
replacement cannot satisfy:

A. v1 is byte-identical to ``origin/main``'s encoder on real positions,
B. v2's first 531 columns ARE the v1 vector,
C. an archived 531-wide checkpoint still loads and still runs a forward pass,
D. a v1 cache key and a v2 cache key cannot collide.
"""

from __future__ import annotations

import gzip
import json
import random
from pathlib import Path

import numpy as np
import pytest

from shengji.ai.registry import make_bot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.harvest.rebuild import state_for_record
from shengji.rl import encoder_identity
from shengji.rl import encode as encode_v1
from shengji.rl.encode_versions import (ENC_VERSION, ENC_VERSION_MAX, OBS_DIM,
                                        OBS_DIM_BY_VERSION, OBS_SCHEMA,
                                        OBS_SCHEMA_BY_VERSION, encode_obs,
                                        encoder_version_for, obs_dim,
                                        trick_state)
from shengji.train import cwv_data, data

FIXTURE = Path(__file__).parent / "data" / "encoder_v1_positions.json.gz"


def _fixture() -> dict:
    with gzip.open(FIXTURE, "rt") as fh:
        return json.load(fh)


def _positions(payload: dict):
    """``(round, seat, reference float32 vector)`` per fixture position."""
    for record, hexed in zip(payload["records"], payload["obs"]):
        rnd = state_for_record(record)
        seat = int(record["seat"])
        assert rnd.phase == "play" and rnd.turn == seat
        yield rnd, seat, np.frombuffer(bytes.fromhex(hexed), dtype=np.float32)


# ------------------------------------------------------------- the globals

def test_v1_stays_the_default_and_v2_is_declared_beside_it():
    assert ENC_VERSION == 1, "archived checkpoints are v1; the default must stay 1"
    assert OBS_DIM == 531 == OBS_DIM_BY_VERSION[1]
    assert OBS_SCHEMA == OBS_SCHEMA_BY_VERSION[1] == \
        "rl-observation-v1-public-no-private-kitty"
    assert ENC_VERSION_MAX == 3 and OBS_DIM_BY_VERSION[2] == 560
    assert obs_dim(1) == 531 and obs_dim(2) == 560


def test_a_checkpoint_width_selects_its_encoder_version():
    assert encoder_version_for({"obs_dim": 531, "act_dim": 60}) == 1
    assert encoder_version_for({"obs_dim": 560}) == 2
    assert encoder_version_for(531) == 1 and encoder_version_for(560) == 2
    for bad in (530, 559, 0, -1, True, "531", None, {"obs_dim": "531"}):
        with pytest.raises(ValueError):
            encoder_version_for(bad)


def test_an_unknown_version_is_refused_rather_than_silently_encoded():
    rnd, seat = _self_play_state()
    for bad in (0, 4, -1, True, 1.0, "1", None):
        with pytest.raises(ValueError):
            encode_obs(rnd, seat, version=bad)


# ----------------------------------------------------- A. v1 byte identity

def test_the_golden_fixture_is_real_shard_positions_from_origin_main():
    payload = _fixture()
    assert payload["reference"] == "origin/main"
    assert payload["enc_version"] == 1 and payload["obs_dim"] == 531
    assert len(payload["records"]) == len(payload["obs"]) >= 200
    runs = {record["shard"].split("/")[0] for record in payload["records"]}
    assert len(runs) >= 3, f"positions came from one run only: {runs}"


def test_v1_is_byte_identical_to_origin_main_on_real_positions():
    """A: element for element, not a shape check."""
    payload = _fixture()
    checked = 0
    for rnd, seat, reference in _positions(payload):
        vector = encode_obs(rnd, seat, version=1)
        assert len(vector) == 531
        observed = np.asarray(vector, dtype=np.float32)
        assert observed.tobytes() == reference.tobytes(), (
            f"v1 drifted at position {checked}: first differing column "
            f"{int(np.flatnonzero(observed != reference)[0])}")
        checked += 1
    assert checked >= 200


def test_the_default_call_is_still_v1():
    payload = _fixture()
    for rnd, seat, reference in _positions(payload):
        assert np.asarray(encode_obs(rnd, seat), dtype=np.float32).tobytes() \
            == reference.tobytes()
        # v1 is not a copy of encode.py's body, it IS encode.encode_obs
        assert encode_obs(rnd, seat, version=1) == encode_v1.encode_obs(rnd, seat)
        break


def test_encode_py_is_untouched_so_archived_checkpoint_gates_still_match():
    """The digest of ``encode.py`` is an identity, not just source.

    ``encode.ENCODER_SOURCE_SHA256S`` hashes the file; the transitive
    contract hashes it again; ``cwv_data.cwv_encoder_identity`` folds that
    into the ``implementation_sha256`` ``ai.cwv_policy`` accepts archived
    complete-world checkpoints on.  Encoder v2 therefore lives in
    ``encode_versions.py`` and must never edit ``encode.py``."""
    import subprocess
    from pathlib import Path as _Path

    repo = _Path(__file__).resolve().parents[2]
    for name in ("shengji/rl/encode.py", "shengji/rl/value_afterstate.py"):
        try:
            main_bytes = subprocess.run(
                ["git", "-C", str(repo), "show", f"origin/main:server/{name}"],
                capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            pytest.skip("origin/main is not available in this checkout")
        assert (repo / "server" / name).read_bytes() == main_bytes, (
            f"{name} must stay byte-identical to origin/main: archived "
            "checkpoints are accepted on its digest")
    assert not hasattr(encode_v1, "encode_obs_v2_columns")


# ------------------------------------------------------ B. v2 prefix rule

def test_v2_extends_the_v1_vector_without_disturbing_it():
    """B: the first 531 columns of v2 ARE v1, on the same real positions."""
    payload = _fixture()
    checked = 0
    extras = set()
    for rnd, seat, reference in _positions(payload):
        v2 = encode_obs(rnd, seat, version=2)
        assert len(v2) == 560
        assert v2[:531] == encode_obs(rnd, seat, version=1)
        assert np.asarray(v2[:531], dtype=np.float32).tobytes() \
            == reference.tobytes()
        assert all(isinstance(x, float) for x in v2[531:])
        extras.add(tuple(v2[531:]))
        checked += 1
    assert checked >= 200
    assert len(extras) > 1, "the v2 columns are constant: they carry nothing"


def test_the_v2_columns_state_the_trick_the_v1_vector_never_did():
    rnd, seat = _self_play_state()
    assert not rnd.trick.plays
    on_lead = encode_obs(rnd, seat, version=2)
    assert trick_state(rnd, seat) == (None, None, 0)
    assert on_lead[531:535] == [0.0] * 4          # nobody is winning yet
    assert on_lead[542:546] == [1.0, 0.0, 0.0, 0.0]  # first to act

    rnd.play(seat, SmartBot().decide_play(rnd, seat))
    follower = rnd.turn
    winner, lead_suit, points = trick_state(rnd, follower)
    assert winner == seat and lead_suit is not None
    after = encode_obs(rnd, follower, version=2)
    assert after[531 + (winner - follower) % 4] == 1.0
    assert after[542:546] == [0.0, 1.0, 0.0, 0.0]
    assert after[536] == min(points, 80) / 80.0
    assert after[:531] == encode_obs(rnd, follower, version=1)


# ---------------------------------------- C. an archived checkpoint still runs

def test_archived_v1_checkpoint_loads_and_runs_a_forward_pass():
    """C: the test #283 could not pass — a real 531-wide archived net."""
    bot = make_bot("rl-override-v11pair", seed=2)
    net = bot.net
    assert net.obs_dim == 531, "the archived v11pair checkpoint is 531 wide"
    assert net.enc_version == 1
    assert net.w["t0w"].shape[1] == 531

    rnd, seat = _self_play_state(seed=2)
    obs = encode_obs(rnd, seat, version=net.enc_version)
    assert len(obs) == 531
    from shengji.rl.encode import encode_action
    actions = bot._ballot._candidates(rnd, seat)
    scores = net.value_candidates(obs, [encode_action(a, rnd) for a in actions])
    assert scores.shape == (len(actions),) and np.all(np.isfinite(scores))

    played = bot.decide_play(rnd, seat)
    assert played in actions or sorted(played) in [sorted(a) for a in actions]


def test_the_torch_nets_and_arch_route_by_their_own_width():
    torch = pytest.importorskip("torch")
    from shengji.rl.model import PolicyValueNet, QNet, QNetDueling
    from shengji.train.model import DEFAULT_ARCH, ValuePriorNet

    assert DEFAULT_ARCH["obs_dim"] == 531
    assert ValuePriorNet().enc_version == 1
    assert ValuePriorNet({"obs_dim": 560, "trunk": [8, 4]}).enc_version == 2
    for factory in (QNet, QNetDueling, PolicyValueNet):
        assert factory(hidden=8).enc_version == 1
        assert factory(hidden=8, obs_dim=560).enc_version == 2
    net = QNetDueling(hidden=8, obs_dim=560)
    out = net.score_candidates([0.0] * 560, [[0.0] * 60, [0.0] * 60])
    assert out.shape == (2,) and torch.isfinite(out).all()


# ------------------------------------------------------------ D. cache keys

def test_cache_keys_differ_between_versions_and_are_stable_within_one():
    """D."""
    v1, v2 = data.encoder_cache_key(1), data.encoder_cache_key(2)
    assert v1 != v2, "a v1 cache and a v2 cache would collide"
    assert v1 == data.encoder_cache_key(1) == data.encoder_cache_key()
    assert v2 == data.encoder_cache_key(2)
    assert v1.startswith("v1-") and v2.startswith("v2-")

    a = data.cache_path("/cache", "deadbeef", version=1)
    b = data.cache_path("/cache", "deadbeef", version=2)
    assert a != b and a == data.cache_path("/cache", "deadbeef")

    c1, c2 = cwv_data.encoder_cache_key(1), cwv_data.encoder_cache_key(2)
    assert c1 != c2 and c1 == cwv_data.encoder_cache_key()
    assert cwv_data.cache_path("/cache", "deadbeef", version=1) \
        != cwv_data.cache_path("/cache", "deadbeef", version=2)
    # v1's CWV identity payload is frozen: ai/cwv_policy keeps an independent
    # replica of the recipe and archived CWV checkpoints are accepted on it.
    from shengji.ai.cwv_policy import local_encoder_identity
    assert cwv_data.cwv_encoder_identity(1)["implementation_sha256"] \
        == local_encoder_identity()["implementation_sha256"]

    for bad in (0, 4, True, "1", None):
        with pytest.raises(ValueError):
            data.encoder_cache_key(bad)


def test_the_encoder_contract_and_identity_carry_the_version():
    one = encoder_identity.encoder_contract(1)
    two = encoder_identity.encoder_contract(2)
    assert one["layout_version"] == 1 and two["layout_version"] == 2
    assert one["schema"] != two["schema"]
    assert one == encoder_identity.encoder_contract()

    assert data.encoder_identity(1)["obs_dim"] == 531
    assert data.encoder_identity(2)["obs_dim"] == 560
    assert data.encoder_identity(1) != data.encoder_identity(2)


# ------------------------------ a FRESH run can ask for v2 (no checkpoint yet)

def test_a_fresh_training_run_can_select_the_encoder_version():
    """Inference dispatch reads a checkpoint; a first v2 run has none, so the
    trainers must expose the choice or the v2 lane is unreachable."""
    pytest.importorskip("torch")
    from shengji.train import train_cwv, train_v0

    assert train_v0.DEFAULTS["encoder_version"] == 1
    # train_cwv defaults to v2 as of 2026-09-08; train_v0 is untouched and stays v1.
    assert train_cwv.DEFAULTS["encoder_version"] == 2

    v1 = train_v0.build_config(data=["d"])
    v2 = train_v0.build_config(data=["d"], encoder_version=2)
    # the width the checkpoint will DECLARE, which is what inference reads
    assert v1["arch"]["obs_dim"] == 531 and v1["encoder_version"] == 1
    assert v2["arch"]["obs_dim"] == 560 and v2["encoder_version"] == 2
    assert encoder_version_for(v2["arch"]) == 2
    assert v2["enc_version"] == 2
    for bad in (0, 4, "2", None):
        with pytest.raises(train_v0.TrainError):
            train_v0.build_config(data=["d"], encoder_version=bad)

    # Explicit v1: the point of this test is that a version can be SELECTED, and
    # since 2026-09-08 the unspecified default is v2, asserted just below.
    c1 = train_cwv.build_config(data=["d"], encoder_version=1)
    c_default = train_cwv.build_config(data=["d"])
    assert (c_default["encoder_version"], c_default["public_dim"]) == (2, 561)
    c2 = train_cwv.build_config(data=["d"], encoder_version=2)
    assert (c1["encoder_version"], c1["public_dim"]) == (1, 532)
    assert (c2["encoder_version"], c2["public_dim"]) == (2, 561)
    # the v1 model_config is field-for-field what the pre-change trainer wrote
    assert "public_dim" not in c1["model_config"] and "enc_version" not in c1["model_config"]
    assert c2["model_config"]["public_dim"] == 561 and c2["model_config"]["enc_version"] == 2
    for bad in (0, 4, "2", None):
        with pytest.raises(train_cwv.TrainError):
            train_cwv.build_config(data=["d"], encoder_version=bad)


def test_the_cli_of_both_trainers_exposes_encoder_version():
    pytest.importorskip("torch")
    from shengji.train import train_cwv, train_v0

    for module in (train_v0, train_cwv):
        parser = module.build_parser()
        default = parser.parse_args(["train", "--data", "d", "--out", "o"])
        # train_cwv defaults to v2 as of 2026-09-08; train_v0 is untouched.
        assert default.encoder_version == (2 if module is train_cwv else 1)
        chosen = parser.parse_args(
            ["train", "--data", "d", "--out", "o", "--encoder-version", "2"])
        assert chosen.encoder_version == 2
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["train", "--data", "d", "--out", "o", "--encoder-version", "4"])


def test_a_v2_run_writes_its_own_cache_and_cannot_read_a_v1_one(tmp_path):
    """A v1 cache and a v2 cache of the SAME shard never share a path, and
    the meta check refuses the other version even if a path is forced."""
    v1 = data.cache_path(tmp_path, "abc123", version=1)
    v2 = data.cache_path(tmp_path, "abc123", version=2)
    assert v1 != v2 and v1.parent == v2.parent

    meta_v1 = {"schema": data.CACHE_SCHEMA, "packing": data.packing_for(1),
               "encoder": data.encoder_identity(1)}
    meta_v2 = {"schema": data.CACHE_SCHEMA, "packing": data.packing_for(2),
               "encoder": data.encoder_identity(2)}
    assert data.check_meta(meta_v1, path=v1, version=1)["encoder"]["enc_version"] == 1
    assert data.check_meta(meta_v2, path=v2, version=2)["encoder"]["enc_version"] == 2
    with pytest.raises(data.TrainDataError):
        data.check_meta(meta_v1, path=v1, version=2)   # a v2 run reading v1
    with pytest.raises(data.TrainDataError):
        data.check_meta(meta_v2, path=v2, version=1)   # a v1 run reading v2


# ------------------------- #288's fused static fast path and encoder v2

def _played_state(plies: int = 5):
    """A play state with some history, which the CWV tensors require."""
    rnd, seat = _self_play_state()
    smart = SmartBot()
    for _ in range(plies):
        turn = rnd.turn
        rnd.play(turn, smart.decide_play(rnd, turn))
    return rnd, rnd.turn


def test_the_fused_length_guard_cannot_detect_a_version_mismatch():
    """Why the fused path needs an explicit version gate.

    #288 guards its inline build with ``len(obs) != OBS_DIM``.  Under the
    additive design ``OBS_DIM`` stays 531 for every version, so at v2 that
    guard compares 531 against 531 and PASSES.  It cannot be the thing that
    keeps a v2 caller from being handed a v1-shaped tensor."""
    from shengji.ai import cwv_static_encoding as static

    assert static.OBS_DIM == 531 == OBS_DIM_BY_VERSION[1]
    assert OBS_DIM_BY_VERSION[2] == 560 != static.OBS_DIM
    # the v1 build the fused path produces would satisfy the guard at ANY
    # version, which is exactly why the guard is not a version check
    rnd, seat = _played_state()
    assert len(static.encode_obs_static(rnd, seat, version=1)) == static.OBS_DIM


def test_v1_still_takes_the_fused_fast_path():
    """#288's optimization must not be lost for the default version."""
    from shengji.ai import cwv_static_encoding as static

    rnd, seat = _played_state()
    calls = []
    real = static._fused_static_tensors

    def spy(r, s, version=ENC_VERSION):
        result = real(r, s, version)
        calls.append((version, result))
        return result

    static._fused_static_tensors = spy
    try:
        out = static.tensors_from_round_static(rnd, seat)
    finally:
        static._fused_static_tensors = real
    assert calls, "the fused path was not even consulted at v1"
    version, fused = calls[-1]
    assert version == 1
    assert fused is not None, "the fused path declined an eligible v1 state"
    assert out is fused, "v1 must be SERVED by the fused path, not the fallback"
    assert out.public.shape == (532,)


def test_v2_fuses_only_its_v1_base_then_keeps_all_canonical_v2_columns():
    """#294 permits v1 fusion plus widening, never a bare v1 result."""
    from shengji.ai import cwv_static_encoding as static
    from shengji.rl.value_afterstate_v2 import tensors_from_round

    rnd, seat = _played_state()
    calls = []
    real = static._fused_static_tensors

    def spy(r, s, version=ENC_VERSION):
        calls.append(version)
        return real(r, s, version)

    static._fused_static_tensors = spy
    try:
        out = static.tensors_from_round_static(rnd, seat, version=2)
    finally:
        static._fused_static_tensors = real
    assert calls == [1], "fusion must build only the v1 base, never pretend to encode v2"
    reference = tensors_from_round(rnd, seat, version=2)
    assert out.public.shape == (561,)
    np.testing.assert_array_equal(out.public, reference.public)
    np.testing.assert_array_equal(out.world, reference.world)
    np.testing.assert_array_equal(out.perspective, reference.perspective)


def test_the_fused_builder_itself_refuses_to_serve_a_v2_request():
    """A direct call cannot produce a tensor a v2 consumer would accept."""
    from shengji.ai import cwv_static_encoding as static

    rnd, seat = _played_state()
    assert static._fused_static_tensors(rnd, seat, 1) is not None
    assert static._fused_static_tensors(rnd, seat, 2) is None, \
        "the fused builder writes the v1 layout; it must decline v2"


def test_the_v2_observation_is_560_wide_through_the_reference_encoder():
    from shengji.ai import cwv_static_encoding as static

    rnd, seat = _played_state()
    fast_v1 = static.encode_obs_static(rnd, seat)
    assert len(fast_v1) == 531 and fast_v1 == encode_obs(rnd, seat, version=1)

    wide = static.encode_obs_static(rnd, seat, version=2)
    assert len(wide) == 560, "a v2 request must not be served a v1-width vector"
    assert wide == encode_obs(rnd, seat, version=2)
    assert wide[:531] == fast_v1


def test_complete_world_static_tensors_at_v2_are_561_wide_never_narrowed():
    """``rl/value_afterstate.py`` is frozen, so v2 tensors come from the
    subclass in ``value_afterstate_v2`` one level up; a v2 caller gets 561
    columns whose v1 slice is the v1 tensor, never a 532-wide answer."""
    from shengji.ai import cwv_static_encoding as static

    rnd, seat = _played_state()
    v1 = static.tensors_from_round_static(rnd, seat)
    v2 = static.tensors_from_round_static(rnd, seat, version=2)
    assert v1.public.shape == (532,) and v2.public.shape == (561,)
    assert v2.public[:531].tobytes() == v1.public[:531].tobytes()
    assert v2.public[560] == v1.public[531]


# ------------------------------------- the packing table covers BOTH widths

def test_the_feature_layout_covers_and_refuses_at_both_widths():
    for version, width in OBS_DIM_BY_VERSION.items():
        layout = data.obs_layout_for(version)
        assert layout.dim == width
        assert sum(w for _n, w, _k in data.OBS_SEGMENTS_BY_VERSION[version]) == width
        # the refusal #283 failed: a table that does not cover the vector
        with pytest.raises(Exception):
            data.FeatureLayout("obs", data.OBS_SEGMENTS_BY_VERSION[version][:-1], width)
        with pytest.raises(Exception):
            data.FeatureLayout("obs", data.OBS_SEGMENTS_BY_VERSION[version], width + 1)
    assert data.OBS_LAYOUT is data.obs_layout_for(1)
    assert data.PACKING == data.packing_for(1) != data.packing_for(2)


def test_both_widths_pack_and_unpack_real_observations_byte_exactly():
    payload = _fixture()
    rows = {1: [], 2: []}
    for rnd, seat, _reference in _positions(payload):
        for version in (1, 2):
            rows[version].append(encode_obs(rnd, seat, version=version))
        if len(rows[1]) == 64:
            break
    for version, vectors in rows.items():
        obs = np.asarray(vectors, dtype=np.float32)
        packed = data.pack_features(obs, np.zeros((0, 60), np.float32))
        back = data.obs_layout_for(version).unpack(
            packed["obs_bits"], None, packed["obs_f32"])
        assert back.shape == obs.shape
        assert back.tobytes() == obs.tobytes()


# --------------------------------------------------------------- helpers

def _self_play_state(seed: int = 41):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    smart = SmartBot()
    for seat in range(4):
        cards = smart.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, smart.decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play" and rnd.turn is not None
    return rnd, rnd.turn
