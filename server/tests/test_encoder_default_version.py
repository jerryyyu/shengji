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


# ---- the version dispatch must hold through BOTH public inference entry points.
# Fixing predict_round alone left score_actions feeding 532-wide rows to a
# 561-wide net (Codex, bus 795/796), so both are witnessed here and the shared
# helper is asserted to be the single source of the rule.

import pytest


def _model(version):
    class Cfg:
        enc_version = version

    class Model:
        config = Cfg()
    return Model()


@pytest.mark.parametrize("version", [1, 2])
def test_the_shared_helper_encodes_at_the_models_own_version(version, monkeypatch):
    from shengji.rl import value_inference
    import shengji.rl.value_afterstate_v2 as v2mod

    seen = {}

    def v1(r, s):
        seen["v"] = 1
        return "v1"

    def v2(r, s, *, version):
        seen["v"] = version
        return "v2"

    monkeypatch.setattr(value_inference, "tensors_from_round", v1)
    monkeypatch.setattr(v2mod, "tensors_from_round", v2)
    got = value_inference.tensors_for_model(_model(version), object(), 0)
    assert seen["v"] == version
    assert got == ("v1" if version == 1 else "v2")


def test_a_model_with_no_declared_version_is_v1():
    from shengji.rl import value_inference

    class Bare:
        config = object()
    assert value_inference.model_enc_version(Bare()) == 1
    assert value_inference.model_enc_version(object()) == 1


@pytest.mark.parametrize("version", [1, 2])
def test_predict_round_routes_through_the_shared_helper(version, monkeypatch):
    from shengji.rl import value_inference

    calls = []
    monkeypatch.setattr(value_inference, "tensors_for_model",
                        lambda m, r, s: calls.append(value_inference.model_enc_version(m)) or "T")
    monkeypatch.setattr(value_inference, "predict_tensors",
                        lambda m, t, device="cpu": list(t))
    assert value_inference.predict_round(_model(version), object(), 0) == "T"
    assert calls == [version]


@pytest.mark.parametrize("version", [1, 2])
def test_score_actions_routes_through_the_shared_helper(version, monkeypatch):
    """The sibling API. This is the one that stayed broken after the first fix."""
    from shengji.rl import value_inference

    calls = []

    class Succ:
        phase = "play"

    monkeypatch.setattr(value_inference, "apply_action",
                        lambda rnd, seat, action: (Succ(), tuple(action)))
    monkeypatch.setattr(value_inference, "tensors_for_model",
                        lambda m, r, s: calls.append(value_inference.model_enc_version(m)) or "T")
    monkeypatch.setattr(value_inference, "predict_tensors",
                        lambda m, t, device="cpu": [object() for _ in t])
    value_inference.score_actions(_model(version), object(), 0, [["S5"]])
    assert calls == [version], "score_actions must encode at the model's version too"

