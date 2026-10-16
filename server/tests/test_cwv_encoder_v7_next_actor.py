"""Encoder v7: v2 plus a seat-relative one-hot of who acts next.

The defect it closes was measured: at a trick-boundary afterstate, flipping who leads next left
the training tensors and the serving static tensors byte-identical (300/300 states), while the
held-out residual of the production value net split by next leader (+0.010 when the root's team
leads next, -0.036 otherwise).  Every served pv-search leaf is a trick-boundary state.

What is pinned here, through the paths the work actually takes (not only the tables):

* layout: v7 is v2's 560 columns byte for byte plus 4, at a width no other version, and no
  reserved archived version, claims;
* the witness: at a boundary, flipping the next leader changes v7 in exactly the new columns
  and leaves v2 identical;
* training: ``tensors_from_round``, the bridge, the cache and its reference check at v7;
* serving: the static adapter equals the reference, a v7 joint package exports, loads, scores
  through the NumPy evaluator and constructs and plays as the served pv-search bot, while a v2
  package still loads at v2 and a mismatched version refuses;
* identity: all three closures hash the v7 module, and no published identity moves.
"""
from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl import encode_versions as ev
from shengji.rl.encode_next_actor import N_NEXT_ACTOR_COLUMNS, next_actor_columns
from shengji.rl.value_afterstate_v2 import public_dim, tensors_from_round
from tests.test_cwv_train import records, store_dir  # noqa: F401  (shared corpus fixtures)

V2 =ev.OBS_DIM_BY_VERSION[2]
BLOCK = slice(V2, V2 + N_NEXT_ACTOR_COLUMNS)


def _round(seed: int, *, rank: str | None = None, banker: int | None = None):
    from shengji.harvest.trajectory import start_round_at
    game = Game(random.Random(seed))
    rnd = game.start_round() if rank is None else start_round_at(game, rank, banker)
    while rnd.phase == "deal":
        rnd.deal_next()
    bot = SmartBot()
    for s in range(4):
        cards = bot.decide_declare(rnd, s, final=True)
        if cards:
            rnd.declare(s, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    return rnd, bot


def _states(seeds=(7, 11), ranks=(None, "J", "A"), bankers=(None, 2, 1)):
    """Every play-phase state of a few whole rounds (copies, never live references)."""
    out = []
    for seed in seeds:
        for rank, banker in zip(ranks, bankers):
            rnd, bot = _round(seed, rank=rank, banker=banker)
            while rnd.phase == "play":
                out.append(copy.deepcopy(rnd))
                rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
            out.append(copy.deepcopy(rnd))            # round_end: nobody acts
    return out


@pytest.fixture(scope="module")
def states():
    return _states()


def test_layout_is_v2_plus_four_at_a_width_nothing_else_claims():
    assert ev.ENC_VERSION_MAX == 7 and ev.OBS_SCHEMA_BY_VERSION[7] == "rl-observation-v7-next-actor"
    assert ev.OBS_DIM_BY_VERSION[7] == V2 + 4 == 564 and public_dim(7) == 565
    widths = ev.OBS_DIM_BY_VERSION
    assert len(set(widths.values())) == len(widths)
    assert ev.encoder_version_for(564) == 7 and ev.encoder_version_for(560) == 2
    # the archived v3 nets are 568 wide (public 569): never served another version's encoder
    assert ev.RESERVED_OBS_DIMS == {3: 568}
    with pytest.raises(ValueError, match="reserved"):
        ev.encoder_version_for(568)
    assert ev.APPENDS_TO[7] == 2 and 6 not in ev.APPENDS_TO
    from shengji.train import data
    layout = data.obs_layout_for(7)
    assert layout.dim == 564 and data.OBS_SEGMENTS_BY_VERSION[7][-1] == ["next_actor", 4, "bits2"]


def test_v7_is_v2_plus_the_one_hot_of_the_turn_on_every_state(states):
    boundaries = ended = 0
    for rnd in states:
        for seat in range(4):
            v2 = ev.encode_obs(rnd, seat, version=2)
            v7 = ev.encode_obs(rnd, seat, version=7)
            assert v7[:V2] == v2, "v7 must not move a v2 byte"
            block = v7[BLOCK]
            if rnd.phase == "play":
                assert block == [1.0 if rel == (rnd.turn - seat) % 4 else 0.0 for rel in range(4)]
            else:
                assert block == [0.0] * 4, "a finished round has nobody to act"
        if rnd.phase == "play" and not rnd.trick.plays:
            boundaries += 1
        ended += rnd.phase == "round_end"
    assert boundaries > 30 and ended == 6


def test_the_audit_witness_a_flipped_next_leader_is_now_visible(states):
    """The defect, reproduced on v2 and fixed on v7, on trick-boundary states."""
    from shengji.ai.cwv_static_encoding import tensors_from_round_static
    tested = 0
    for rnd in states:
        if rnd.phase != "play" or rnd.trick.plays or not rnd.history:
            continue
        flipped = copy.deepcopy(rnd)
        other = (rnd.turn + 1) % 4
        flipped.turn = other
        flipped.trick.leader = other
        root = rnd.history[-1].plays[-1].seat           # who played the trick's last card
        for build in (tensors_from_round, tensors_from_round_static):
            a2, b2 = build(rnd, root, version=2), build(flipped, root, version=2)
            assert a2.public.tobytes() == b2.public.tobytes(), "v2 cannot see the next leader"
            a7, b7 = build(rnd, root, version=7), build(flipped, root, version=7)
            changed = np.flatnonzero(a7.public != b7.public)
            assert set(changed.tolist()) <= set(range(BLOCK.start, BLOCK.stop))
            assert changed.size == 2, "exactly the old and the new next-actor column"
            assert a7.world.tobytes() == b7.world.tobytes()
        tested += 1
    assert tested > 30


def test_the_tensor_layer_builds_v7_and_its_static_adapter_agrees(states):
    from shengji.ai import cwv_static_encoding as static
    calls = []
    real = static._widen_v7_static

    def spy(*args):
        calls.append(1)
        return real(*args)

    static._widen_v7_static = spy
    try:
        compared = 0
        for rnd in states:
            if rnd.phase != "play" or not (rnd.history or rnd.trick.plays):
                continue
            for seat in range(4):
                ref = tensors_from_round(rnd, seat, version=7)
                fast = static.tensors_from_round_static(rnd, seat, version=7)
                assert ref.public.shape == (565,)
                assert ref.public.tobytes() == fast.public.tobytes()
                assert ref.world.tobytes() == fast.world.tobytes()
                assert ref.perspective.tobytes() == fast.perspective.tobytes()
                v2 = tensors_from_round(rnd, seat, version=2)
                assert ref.public[:V2].tobytes() == v2.public[:V2].tobytes()
                assert ref.public[-1] == v2.public[-1], "the terminal flag stays last"
                assert ref.public[BLOCK].tolist() == next_actor_columns(rnd, seat)
                compared += 1
    finally:
        static._widen_v7_static = real
    assert compared > 200 and len(calls) == compared, "v7 must be served by the fused path"


def test_widen_to_v7_equals_the_full_v7_encode(states):
    from shengji.rl.value_afterstate import tensors_from_round as v1_tensors
    from shengji.rl.value_afterstate_v2 import widen_to
    for rnd in states[::7]:
        if rnd.phase != "play" or not (rnd.history or rnd.trick.plays):
            continue
        seat = rnd.turn
        widened = widen_to(v1_tensors(rnd, seat), rnd, seat, 7)
        full = np.asarray([*ev.encode_obs(rnd, seat, version=7), 0.0], dtype=np.float32)
        assert widened.public.tobytes() == full.tobytes()


# ----------------------------------------------------------------- identity

def test_every_closure_hashes_the_v7_module_and_no_published_identity_moves():
    from shengji.ai import cwv_policy
    from shengji.rl.encoder_identity import encoder_contract, source_paths
    from shengji.train import cwv_data
    for paths in (source_paths(7), cwv_data.cwv_source_paths(7), cwv_policy.afterstate_source_paths(7)):
        assert "encode_next_actor" in paths
        assert not {"encode_banker_kitty", "encode_banker_kitty_corrected",
                    "encode_opponent_pairs"} & set(paths)
    for version in (1, 2, 4, 5, 6):
        assert "encode_next_actor" not in cwv_data.cwv_source_paths(version)
        assert "encode_next_actor" not in source_paths(version)
    ident = cwv_data.cwv_encoder_identity(7)
    assert ident["enc_version"] == 7 and ident["public_dim"] == 565
    assert cwv_policy.local_encoder_identity(7)["implementation_sha256"] == ident["implementation_sha256"]
    others = {cwv_data.cwv_encoder_identity(v)["implementation_sha256"] for v in (1, 2, 4, 5, 6)}
    assert ident["implementation_sha256"] not in others
    assert encoder_contract(7)["schema"] == "rl-observation-v7-next-actor"
    # the identities production and the archived caches carry
    from tests.test_encoder_bytes_golden import CURRENT_CWV
    for version, sha in CURRENT_CWV.items():
        assert cwv_data.cwv_encoder_identity(version)["implementation_sha256"] == sha


def test_a_change_to_the_v7_module_moves_only_the_v7_identity(monkeypatch):
    from shengji.train import cwv_data
    before = {v: cwv_data.cwv_encoder_identity(v)["implementation_sha256"] for v in (2, 6, 7)}
    real = cwv_data.sha256_file

    def drifted(path):
        digest = real(path)
        return "0" * 64 if str(path).endswith("encode_next_actor.py") else digest

    monkeypatch.setattr(cwv_data, "sha256_file", drifted)
    after = {v: cwv_data.cwv_encoder_identity(v)["implementation_sha256"] for v in (2, 6, 7)}
    assert after[2] == before[2] and after[6] == before[6]
    assert after[7] != before[7]


# ----------------------------------------------------------------- training

def test_the_bridge_and_the_cache_build_v7_rows(tmp_path, records, store_dir):
    from shengji.train import cwv_data
    from shengji.train.data import discover_store
    store = discover_store(str(store_dir), limit_clusters=None)
    shard = store.shards[0]
    p7, counts7 = cwv_data.build_cache(shard, tmp_path, version=7, reference_every=1)
    p2, counts2 = cwv_data.build_cache(shard, tmp_path, version=2)
    assert p7 != p2 and counts7["encoded"] == counts2["encoded"] > 0
    assert counts7["reference_checked"] == counts7["encoded"], "every v7 row re-derived"
    b7 = cwv_data.load_block(p7, shard_sha256=shard.sha256)
    b2 = cwv_data.load_block(p2, shard_sha256=shard.sha256)
    assert b7.public.shape == (b2.n, 565) and b7.meta["encoder"]["enc_version"] == 7
    assert b7.public[:, :V2].tobytes() == b2.public[:, :V2].tobytes()
    assert b7.public[:, -1].tobytes() == b2.public[:, -1].tobytes()
    live = b7.public[:, -1] == 0.0
    assert np.all(b7.public[live][:, BLOCK].sum(axis=1) == 1.0)
    for name in ("target", "world", "perspective", "deal_key", "source_ref"):
        assert np.array_equal(getattr(b7, name), getattr(b2, name)), name
    with pytest.raises(cwv_data.TrainDataError):
        cwv_data.check_public_width({"public": b2.public}, b7.meta, path=p7)


# ------------------------------------------------------------------ serving

def _joint_package(tmp_path, enc_version, *, seed=5, declare=None):
    pytest.importorskip("torch")
    import torch
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import file_sha256, local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    torch.manual_seed(seed)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                        public_dim=public_dim(enc_version), enc_version=enc_version,
                                        attention_heads=1, trunk_block="residual", trunk_layers=2,
                                        search_head=True, policy_head=True))
    net.eval()
    ckpt = tmp_path / f"joint-v{enc_version}.pt"
    encoder = local_encoder_identity(enc_version if declare is None else declare)
    save_checkpoint(ckpt, net, metadata={"encoder": encoder, "sees_hidden_hands": True})
    pkg = tmp_path / f"joint-v{enc_version}.npz"
    export_cwv_numpy(ckpt, pkg)
    return str(ckpt), str(pkg), file_sha256(pkg)


def test_a_v7_package_exports_loads_and_scores_like_its_checkpoint(tmp_path, states):
    from shengji.ai.cwv_numpy import load_cwv_numpy
    from shengji.ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
    from shengji.ai.cwv_policy import CompleteWorldEvaluator
    ckpt, pkg, _sha = _joint_package(tmp_path, 7)
    model = load_cwv_numpy(pkg)
    assert (model.enc_version, model.public_dim) == (7, 565)
    numpy_eval = NumpyCompleteWorldEvaluator(pkg, encoding="mlp-static")
    torch_eval = CompleteWorldEvaluator(ckpt, encoding="reference")
    assert numpy_eval.enc_version == torch_eval.enc_version == 7
    positions = [s for s in states if s.phase == "play" and s.history][:40]
    seats = [s.turn for s in positions]
    a = numpy_eval.score_many(positions, seats)
    b = torch_eval.score_many(positions, seats)
    np.testing.assert_allclose(a, b, rtol=0, atol=1e-5)
    # the next actor reaches the net: the same boundary state with another leader scores differently
    boundary = next(s for s in positions if not s.trick.plays)
    flipped = copy.deepcopy(boundary)
    flipped.turn = flipped.trick.leader = (boundary.turn + 1) % 4
    root = boundary.history[-1].plays[-1].seat
    x, y = numpy_eval.score_many([boundary, flipped], [root, root])
    assert x != y


def test_a_v7_joint_package_is_the_served_bot_and_plays(tmp_path):
    from shengji.train import pv_search_policy as pv
    from shengji.train.cwv_prior_admission import load_prior_checked, prior_encoder_version
    _ckpt, pkg, sha = _joint_package(tmp_path, 7)
    kind, net, payload = load_prior_checked(pkg, sha)
    assert kind == "joint-numpy" and prior_encoder_version(kind, net, payload) == 7
    bot = pv.make_pv_search_bot(pkg, sha256=sha, seed=3, worlds=3, candidates=4, cap=400,
                                batch_size=16)
    rnd, _ = _round(625091990)
    seat = rnd.turn
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    assert played and bot.last_decision_record["encoder_version"] == 7
    rnd.play(seat, played)


def test_the_v2_runtime_contract_is_unchanged_and_mismatches_refuse(tmp_path):
    from shengji.ai.cwv_numpy import CWVNumpyConfig, CWVNumpyError
    from shengji.ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
    from shengji.ai.cwv_policy import (CWVCheckpointMismatch, CWVError, CompleteWorldEvaluator,
                                       load_cwv_checkpoint)
    # release 45's configuration still validates, at its own width only
    CWVNumpyConfig("mlp", 165, 330, 561, 2, trunk_block="residual", trunk_layers=4,
                   policy_head=True).validate()
    for public, version in ((565, 2), (561, 7), (569, 3), (562, 6)):
        with pytest.raises(CWVNumpyError):
            CWVNumpyConfig("mlp", 32, 64, public, version, trunk_block="residual",
                           trunk_layers=2).validate()
    # a v7 net whose metadata declares v2 is refused at admission, so it is never exported
    bad = tmp_path / "declares-v2"
    bad.mkdir()
    with pytest.raises(CWVCheckpointMismatch):
        _joint_package(bad, 7, declare=2)
    ckpt, pkg, _sha = _joint_package(tmp_path, 7, seed=9)
    model, _meta, _ = load_cwv_checkpoint(ckpt)
    assert model.config.enc_version == 7
    # v2 rows offered to a v7 net: a named refusal on both backends, never a silent matmul
    rnd, bot = _round(31)
    rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
    v2_rows = [tensors_from_round(rnd, 0, version=2)]
    with pytest.raises(CWVNumpyError, match="shape drift"):
        NumpyCompleteWorldEvaluator(pkg, encoding="reference").probabilities(v2_rows)
    with pytest.raises(CWVError, match="width"):
        CompleteWorldEvaluator(ckpt).probabilities(v2_rows)
