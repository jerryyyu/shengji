"""The training default is v2; loading an existing v1 checkpoint is unaffected.

The second half is the one that matters. Changing a training default must not
change how an ALREADY TRAINED checkpoint is scored: the evaluator dispatches on
each checkpoint's own declared ``enc_version``, and an archived checkpoint that
predates the field is v1 forever.
"""
from shengji.rl.encode_versions import OBS_DIM_BY_VERSION
from shengji.train.train_cwv import DEFAULTS


def test_new_trainings_default_to_encoder_v2():
    assert DEFAULTS["encoder_version"] == 2


def test_the_default_carries_the_matching_width():
    assert OBS_DIM_BY_VERSION[DEFAULTS["encoder_version"]] == 560


def test_a_v1_checkpoint_is_still_scored_as_v1_under_the_new_default():
    """Dispatch is per-checkpoint, so the default cannot retro-fit old nets."""
    class V1Config:
        enc_version = 1

    class Model:
        config = V1Config()

    from shengji.ai.cwv_policy import CompleteWorldEvaluator
    ev = CompleteWorldEvaluator.__new__(CompleteWorldEvaluator)
    ev.model = Model()
    assert ev.enc_version == 1, "a v1 checkpoint must not become v2 by default"
    from shengji.rl.value_afterstate_v2 import public_dim
    assert public_dim(ev.enc_version) == 532


def test_a_checkpoint_with_no_declared_version_is_v1():
    """Archived checkpoints predate the field; they are v1, not the default."""
    class Model:
        config = object()

    from shengji.ai.cwv_policy import CompleteWorldEvaluator
    ev = CompleteWorldEvaluator.__new__(CompleteWorldEvaluator)
    ev.model = Model()
    assert ev.enc_version == 1


def test_predict_round_encodes_at_the_models_own_version():
    """The legacy single-round API must follow the checkpoint, not the frozen v1.

    ``predict_round`` called the frozen v1 builder unconditionally, so once v2
    checkpoints existed it fed 532-wide rows to a 561-wide net. Codex found this
    while reviewing the default flip (bus 792).
    """
    import numpy as np
    from shengji.rl import value_inference

    seen = {}

    class Cfg:
        enc_version = 2

    class Model:
        config = Cfg()

    def fake_v1(rnd, seat):
        seen["called"] = 1
        return "v1-tensors"

    def fake_v2(rnd, seat, *, version):
        seen["called"] = version
        return "v2-tensors"

    import shengji.rl.value_afterstate_v2 as v2mod
    orig_v1 = value_inference.tensors_from_round
    orig_v2 = v2mod.tensors_from_round
    orig_pt = value_inference.predict_tensors
    value_inference.tensors_from_round = fake_v1
    v2mod.tensors_from_round = fake_v2
    value_inference.predict_tensors = lambda m, t, device="cpu": [t[0]]
    try:
        got = value_inference.predict_round(Model(), object(), 0)
    finally:
        value_inference.tensors_from_round = orig_v1
        v2mod.tensors_from_round = orig_v2
        value_inference.predict_tensors = orig_pt
    assert seen["called"] == 2, "a v2 model must not be encoded by the v1 builder"
    assert got == "v2-tensors"


def test_predict_round_still_uses_v1_for_a_v1_model():
    from shengji.rl import value_inference

    seen = {}

    class Model:
        config = type("C", (), {"enc_version": 1})()

    def fake_v1(rnd, seat):
        seen["called"] = 1
        return "v1-tensors"

    orig_v1 = value_inference.tensors_from_round
    orig_pt = value_inference.predict_tensors
    value_inference.tensors_from_round = fake_v1
    value_inference.predict_tensors = lambda m, t, device="cpu": [t[0]]
    try:
        assert value_inference.predict_round(Model(), object(), 0) == "v1-tensors"
    finally:
        value_inference.tensors_from_round = orig_v1
        value_inference.predict_tensors = orig_pt
    assert seen["called"] == 1
