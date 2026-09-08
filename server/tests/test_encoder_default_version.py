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
