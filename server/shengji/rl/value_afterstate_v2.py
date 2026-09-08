"""Complete-world afterstate tensors at observation-encoder v2.

``rl/value_afterstate.py`` is frozen: it belongs to the nine-file closure
whose digest archived complete-world checkpoints are accepted on
(``train.cwv_data.CWV_SOURCE_PATHS``), and its ``ValueAfterstateTensors``
pins the public tensor to ``PUBLIC_DIM`` (531 + 1).  Nothing does an
``isinstance`` or exact-type check on that class, so v2 is a SUBCLASS in
this module, one level up: the same four tensors, the public one
``PUBLIC_DIM_V2`` wide -- the v1 observation, then the 29 v2 columns, then
the trailing terminal flag v1 carries at index 531.

Everything is built by calling the frozen v1 builder and splicing, so the
v1 slice of a v2 tensor is the v1 tensor by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .public_history import HISTORY_EVENT_DIM
from .encode import N_CARDS
from .encode_versions import (ENC_VERSION, OBS_DIM_BY_VERSION, check_version,
                               cursor_columns, encode_obs_v2_columns)
from .value_afterstate import (
    PERSPECTIVE_DIM,
    PUBLIC_DIM,
    WORLD_RECEIVERS,
    ValueAfterstateError,
    ValueAfterstateTensors,
)
from .value_afterstate import tensors_from_round as _tensors_from_round_v1

PUBLIC_DIM_V2 = OBS_DIM_BY_VERSION[2] + 1          # = 561
PUBLIC_DIM_V3 = OBS_DIM_BY_VERSION[3] + 1          # = 565
PUBLIC_DIM_BY_VERSION = {version: dim + 1 for version, dim in OBS_DIM_BY_VERSION.items()}
assert PUBLIC_DIM_BY_VERSION[1] == PUBLIC_DIM


def public_dim(version: int = ENC_VERSION) -> int:
    """The complete-world public tensor width of encoder ``version``."""
    return PUBLIC_DIM_BY_VERSION[check_version(version)]


@dataclass(frozen=True)
class ValueAfterstateTensorsV2(ValueAfterstateTensors):
    """The v1 tensors with a ``PUBLIC_DIM_V2``-wide public tensor.

    ``validate`` is the parent's, with the one width changed; it is
    restated rather than delegated because the parent hard-codes
    ``PUBLIC_DIM`` and is frozen."""

    def validate(self) -> None:
        _validate_versioned(self, PUBLIC_DIM_V2)


@dataclass(frozen=True)
class ValueAfterstateTensorsV3(ValueAfterstateTensors):
    """The v1 tensors widened with v2 features and the v3 cursor."""

    def validate(self) -> None:
        _validate_versioned(self, PUBLIC_DIM_V3)


def _validate_versioned(value: ValueAfterstateTensors,
                        public_width: int) -> None:
    """Validate a versioned tensor without changing the frozen v1 class."""
    expected = (
        (value.public, (public_width,), "public"),
        (value.history, (None, HISTORY_EVENT_DIM), "history"),
        (value.world, (WORLD_RECEIVERS, N_CARDS), "world"),
        (value.perspective, (PERSPECTIVE_DIM,), "perspective"),
    )
    for tensor, shape, label in expected:
        if not isinstance(tensor, np.ndarray) or tensor.dtype != np.float32 \
                or tensor.ndim != len(shape) \
                or any(bound is not None and tensor.shape[index] != bound
                       for index, bound in enumerate(shape)) \
                or not bool(np.all(np.isfinite(tensor))):
            raise ValueAfterstateError(f"{label} tensor shape/dtype drift")
    if not 1 <= value.history.shape[0] <= 100:
        raise ValueAfterstateError("history tensor length drift")
    if not bool(np.all((value.world == 0.0) | (value.world == 0.5)
                       | (value.world == 1.0))):
        raise ValueAfterstateError("world tensor count encoding drift")
    if float(value.perspective.sum()) != 1.0 \
            or not bool(np.all((value.perspective == 0.0)
                               | (value.perspective == 1.0))):
        raise ValueAfterstateError("perspective tensor is not one-hot")


def widen(v1: ValueAfterstateTensors, rnd, root_seat: int) -> ValueAfterstateTensorsV2:
    """The v2 tensors of the state ``v1`` was built from: v1's public
    observation, the 29 v2 columns, then v1's trailing terminal flag."""
    return _widen_columns(v1, encode_obs_v2_columns(rnd, root_seat))


def widen_v3(v1: ValueAfterstateTensors, rnd,
             root_seat: int) -> ValueAfterstateTensorsV3:
    """Widen v1 tensors with v2 columns followed by the v3 cursor."""
    return _widen_columns(
        v1, encode_obs_v2_columns(rnd, root_seat)
        + cursor_columns(rnd, root_seat), version=3)


def _widen_columns(v1: ValueAfterstateTensors, columns, *, version: int = 2):
    """Common tensor assembly for reference and validated static features."""
    obs_dim = OBS_DIM_BY_VERSION[1]
    extra = np.asarray(columns, dtype=np.float32)
    public = np.concatenate((v1.public[:obs_dim], extra, v1.public[obs_dim:]))
    cls = ValueAfterstateTensorsV3 if version == 3 else ValueAfterstateTensorsV2
    out = cls(public, v1.history, v1.world, v1.perspective)
    out.validate()
    return out


def tensors_from_round(rnd, root_seat: int, *,
                       version: int = ENC_VERSION) -> ValueAfterstateTensors:
    """``value_afterstate.tensors_from_round`` at ``version``: v1 IS the
    frozen builder's call; v2 is that result widened."""
    version = check_version(version)
    v1 = _tensors_from_round_v1(rnd, root_seat)
    if version == 1:
        return v1
    if version == 2:
        return widen(v1, rnd, root_seat)
    return widen_v3(v1, rnd, root_seat)


__all__ = ["PUBLIC_DIM_V2", "PUBLIC_DIM_V3", "PUBLIC_DIM_BY_VERSION",
           "ValueAfterstateTensorsV2", "ValueAfterstateTensorsV3",
           "public_dim", "tensors_from_round", "widen", "widen_v3"]
