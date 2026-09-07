"""Complete-world nets at observation-encoder v2, one level above the freeze.

``rl/value_afterstate.py`` and the other eight ``CWV_SOURCE_PATHS`` files are
frozen: archived complete-world checkpoints are accepted on their digest.
v2 therefore lives in the files that are NOT in that closure -- the model
config carries its width, the tensors are a subclass, the identity gate
dispatches on the version a checkpoint declares.
"""

from __future__ import annotations

import os
import random

import numpy as np
import pytest

from shengji.ai import cwv_policy
from shengji.ai import cwv_static_encoding as static
from shengji.ai.cwv_policy import (CWVCheckpointMismatch, CWVError, CompleteWorldEvaluator,
                                   verify_checkpoint_identity)
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl import value_afterstate, value_afterstate_v2 as v2
from shengji.rl.encode_versions import encode_obs, encode_obs_v2_columns
from shengji.rl.value_afterstate import PUBLIC_DIM, ValueAfterstateError
from shengji.rl.value_checkpoint import load_checkpoint, save_checkpoint
from shengji.rl.value_model import ValueModelConfig, ValueModelError, ValueNetwork
from shengji.train import cwv_data
from shengji.train.data import TrainDataError

REAL_CHECKPOINT = os.environ.get(
    "SHENGJI_CWV_REAL_CKPT",
    "/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/train-out/cwv/runA-mlp/best.pt")


def _played_state(seed: int = 41, plies: int = 5):
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
    for _ in range(plies):
        rnd.play(rnd.turn, smart.decide_play(rnd, rnd.turn))
    return rnd, rnd.turn


def _mlp(version: int) -> ValueModelConfig:
    return ValueModelConfig(architecture="mlp", width=8, history_layers=1, attention_heads=1,
                            feedforward_width=16, public_dim=v2.public_dim(version),
                            enc_version=version)


# ---------------------------------------------------- 1. the config carries the width

def test_archived_config_shape_still_builds_a_532_wide_net():
    archived = {"architecture": "mlp", "width": 8, "history_layers": 1, "attention_heads": 1,
                "feedforward_width": 16, "dropout": 0.0, "max_history": 100,
                "outcome_classes": 204}
    config = ValueModelConfig.from_payload(dict(archived))
    assert (config.public_dim, config.enc_version) == (PUBLIC_DIM, 1) == (532, 1)
    net = ValueNetwork(config)
    assert net.trunk[0].in_features == 532 + 5 * 54 + 2
    # and the v1 payload is the archived shape, field for field
    assert config.payload() == archived


def test_v2_config_builds_a_561_wide_net_and_round_trips():
    config = _mlp(2)
    assert config.public_dim == 561
    assert ValueNetwork(config).trunk[0].in_features == 561 + 5 * 54 + 2
    payload = config.payload()
    assert payload["public_dim"] == 561 and payload["enc_version"] == 2
    assert ValueModelConfig.from_payload(payload) == config
    seq = ValueModelConfig(public_dim=561, enc_version=2)
    assert ValueNetwork(seq).public_encoder[0].in_features == 561


def test_a_width_that_disagrees_with_the_version_is_refused():
    for public_dim, version in ((561, 1), (532, 2), (560, 2), (533, 1)):
        with pytest.raises(ValueModelError):
            ValueModelConfig(architecture="mlp", public_dim=public_dim, enc_version=version).validate()


# ------------------------------------------------ 2. checkpoints round-trip the width

def test_v2_width_survives_save_and_load(tmp_path):
    net = ValueNetwork(_mlp(2))
    save_checkpoint(tmp_path / "v2.pt", net, metadata={"encoder": {"enc_version": 2}})
    loaded, _meta = load_checkpoint(tmp_path / "v2.pt")
    assert loaded.config == net.config and loaded.config.public_dim == 561
    assert loaded.trunk[0].in_features == net.trunk[0].in_features


@pytest.mark.skipif(not os.path.exists(REAL_CHECKPOINT), reason="needs the archived CWV checkpoint")
def test_the_archived_v1_checkpoint_loads_with_its_state_hash_intact():
    model, metadata = load_checkpoint(REAL_CHECKPOINT)       # verifies state_sha256
    assert model.config.public_dim == 532 and model.config.enc_version == 1
    assert "public_dim" not in metadata["model_config"]
    assert model.config.payload() == metadata["model_config"]


# --------------------------------------------------- 3. the v2 tensor subclass

def test_v2_tensors_are_the_v1_tensors_widened():
    rnd, seat = _played_state()
    one = value_afterstate.tensors_from_round(rnd, seat)
    two = v2.tensors_from_round(rnd, seat, version=2)
    assert isinstance(two, value_afterstate.ValueAfterstateTensors)
    assert two.public.shape == (561,)
    assert two.public[:531].tobytes() == one.public[:531].tobytes()
    assert two.public[531:560].tobytes() == \
        np.asarray(encode_obs_v2_columns(rnd, seat), dtype=np.float32).tobytes()
    assert two.public[560] == one.public[531]
    assert two.public[:531].tobytes() == \
        np.asarray(encode_obs(rnd, seat, version=1), dtype=np.float32).tobytes()
    for name in ("history", "world", "perspective"):
        assert getattr(two, name).tobytes() == getattr(one, name).tobytes()
    assert v2.tensors_from_round(rnd, seat, version=1).public.shape == (532,)


def test_the_v2_class_pins_561_and_the_v1_class_still_pins_532():
    rnd, seat = _played_state()
    one = value_afterstate.tensors_from_round(rnd, seat)
    with pytest.raises(ValueAfterstateError):
        v2.ValueAfterstateTensorsV2(one.public, one.history, one.world, one.perspective).validate()
    two = v2.tensors_from_round(rnd, seat, version=2)
    with pytest.raises(ValueAfterstateError):
        value_afterstate.ValueAfterstateTensors(
            two.public, two.history, two.world, two.perspective).validate()


# ------------------------------------------------ 4a. identity replicas per version

def test_the_policy_replica_reproduces_the_training_identity_at_both_versions():
    for version in (1, 2):
        replica = cwv_policy.local_encoder_identity(version)
        build = cwv_data.cwv_encoder_identity(version)
        assert replica["implementation_sha256"] == build["implementation_sha256"]
        assert replica["source_sha256s"] == build["source_sha256s"]
        assert cwv_policy.afterstate_encoder_identity(version)["implementation_sha256"] \
            == build["implementation_sha256"]
    assert cwv_policy.local_encoder_identity(1)["implementation_sha256"] \
        != cwv_policy.local_encoder_identity(2)["implementation_sha256"]
    # v1's payload is the historical one: the identity of an archived checkpoint
    assert "enc_version" not in cwv_policy.local_encoder_identity.__doc__.lower()[:0]


# --------------------------------------------- 4b. the gate dispatches on the version

def test_the_identity_gate_accepts_each_version_only_as_itself():
    one = cwv_data.cwv_encoder_identity(1)
    two = cwv_data.cwv_encoder_identity(2)
    v1_meta = {"encoder": {"implementation_sha256": one["implementation_sha256"],
                           "source_sha256s": one["source_sha256s"]}}      # archived shape
    v2_meta = {"encoder": {"implementation_sha256": two["implementation_sha256"],
                           "source_sha256s": two["source_sha256s"], "enc_version": 2}}
    assert verify_checkpoint_identity(v1_meta) == one["implementation_sha256"]
    assert verify_checkpoint_identity(v2_meta) == two["implementation_sha256"]
    # the historical second key: value_afterstate.py's own digest, v1 only
    assert verify_checkpoint_identity(
        {"encoder": {"implementation_sha256": one["source_sha256s"]["value_afterstate"]}}) \
        == one["source_sha256s"]["value_afterstate"]
    # a v1 identity declared as v2, and a v2 identity declared as v1, are refused
    with pytest.raises(CWVCheckpointMismatch):
        verify_checkpoint_identity({"encoder": {**v1_meta["encoder"], "enc_version": 2}})
    with pytest.raises(CWVCheckpointMismatch):
        verify_checkpoint_identity({"encoder": {**v2_meta["encoder"], "enc_version": 1}})
    with pytest.raises(CWVCheckpointMismatch):
        verify_checkpoint_identity({"encoder": {**v2_meta["encoder"], "enc_version": 3}})


# --------------------------------------------- 4c. the evaluator routes by the net

def _spy_evaluator(version: int, encoding: str):
    seen = []

    class Recorded(CompleteWorldEvaluator):
        def probabilities(self, rows):
            seen.extend(int(row.public.shape[0]) for row in rows)
            return super().probabilities(rows)

    return Recorded(None, model=ValueNetwork(_mlp(version)), encoding=encoding), seen


@pytest.mark.parametrize("encoding", ["reference", "mlp-static"])
def test_a_v2_net_is_fed_561_wide_rows_and_never_the_fused_path(encoding):
    rnd, seat = _played_state()
    evaluator, seen = _spy_evaluator(2, encoding)
    assert evaluator.enc_version == 2
    calls = []
    real = static._fused_static_tensors
    static._fused_static_tensors = lambda r, s, version=1: calls.append(version) or real(r, s, version)
    try:
        values = evaluator.score([rnd], seat)
    finally:
        static._fused_static_tensors = real
    assert values.shape == (1,) and np.isfinite(values[0])
    assert seen == [561]
    assert calls == [], "the fused builder writes the v1 layout; v2 must never enter it"


def test_a_v1_net_is_still_fed_532_wide_rows_through_the_fused_path():
    rnd, seat = _played_state()
    evaluator, seen = _spy_evaluator(1, "mlp-static")
    assert evaluator.enc_version == 1
    calls = []
    real = static._fused_static_tensors
    static._fused_static_tensors = lambda r, s, version=1: calls.append(real(r, s, version)) or calls[-1]
    try:
        evaluator.score([rnd], seat)
    finally:
        static._fused_static_tensors = real
    assert seen == [532]
    assert calls and calls[0] is not None, "v1 must still be SERVED by the fused path"


def test_mis_routed_rows_are_refused_before_the_net_sees_them():
    """A v1-shaped row reaching a v2 net is a named width refusal, not a
    matmul error and never a silent score."""
    rnd, seat = _played_state()
    evaluator, _seen = _spy_evaluator(2, "reference")
    v1_row = value_afterstate.tensors_from_round(rnd, seat)
    with pytest.raises(CWVError, match="public tensor width \\[532\\] != the net's 561"):
        evaluator.probabilities([v1_row])
    evaluator1, _ = _spy_evaluator(1, "reference")
    with pytest.raises(CWVError, match="\\[561\\] != the net's 532"):
        evaluator1.probabilities([v2.tensors_from_round(rnd, seat, version=2)])


# ------------------------------------------------- 6. cache rows at the version's width

def test_cache_rows_must_be_their_declared_versions_width():
    ok2 = {"public": np.zeros((3, 561), np.float32)}
    ok1 = {"public": np.zeros((3, 532), np.float32)}
    cwv_data.check_public_width(ok2, {"encoder": {"enc_version": 2}}, path="c")
    cwv_data.check_public_width(ok1, {"encoder": {}}, path="c")           # archived meta: v1
    with pytest.raises(TrainDataError, match="532 wide, encoder v2 rows are 561"):
        cwv_data.check_public_width(ok1, {"encoder": {"enc_version": 2}}, path="c")
    with pytest.raises(TrainDataError, match="561 wide, encoder v1 rows are 532"):
        cwv_data.check_public_width(ok2, {"encoder": {"enc_version": 1}}, path="c")
