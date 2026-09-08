"""Opt-in NumPy backend for the existing complete-world/W32 consumer.

Only weights are shared. Each bot owns its evaluator counters, and each room
snapshot copies those counters alongside its RNG. Package identity differs
from the originating Torch checkpoint; never reuse the Torch policy name.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import numpy as np

from .cwv_policy import (
    CWVError, CompleteWorldEvaluator, bind_encoder_version,
    local_encoder_identity, verify_checkpoint_identity,
)
from .cwv_numpy import load_numpy_checkpoint
from ..rl.value_afterstate import OUTCOME_CLASSES, category_signed_level


@lru_cache(maxsize=8)
def _weights(path: str, mtime_ns: int, size: int):
    del mtime_ns, size
    model = load_numpy_checkpoint(path)
    version = bind_encoder_version(model.metadata, model, path=path)
    # The existing local identity recipe is the Torch-free equivalent of the
    # training identity. Tests compare both; do not import the training stack
    # just to hash encoder source in a serving process.
    verify_checkpoint_identity(model.metadata, path=path,
                               identity=local_encoder_identity(version))
    return model


class NumpyCompleteWorldEvaluator(CompleteWorldEvaluator):
    backend = "numpy"

    def __init__(self, checkpoint, *, max_batch=4096, encoding="reference",
                 threads=1):
        if encoding not in ("reference", "mlp-static"):
            raise CWVError("encoding must be 'reference' or 'mlp-static'")
        if type(max_batch) is not int or max_batch < 1:
            raise CWVError("max_batch must be positive")
        if threads not in (None, 1):
            raise CWVError("NumPy serving requires launch-time BLAS thread configuration")
        resolved = Path(checkpoint).resolve()
        stat = resolved.stat()
        self.model = _weights(str(resolved), stat.st_mtime_ns, stat.st_size)
        self.metadata = copy.deepcopy(dict(self.model.metadata))
        self.checkpoint_path = str(resolved)
        self.checkpoint_sha256 = self.model.package_sha256
        self.encoding, self.device = encoding, "cpu"
        # NumPy cannot promise a BLAS thread count through this API. Configure
        # it before process startup and measure it in the deployment receipt.
        self.threads = None
        self.max_batch = max_batch
        self.support = np.asarray([category_signed_level(i)
                                   for i in range(OUTCOME_CLASSES)], dtype=np.float64)
        self.positions = self.model_rows = self.terminal_rows = 0
        self.forward_calls = self.calls = 0
        self.wall_secs = self.cpu_secs = 0.0

    def identity(self):
        return {**super().identity(),
                "source_checkpoint_sha256": self.model.source_checkpoint_sha256}

    def probabilities(self, rows):
        out = np.empty((len(rows), OUTCOME_CLASSES), dtype=np.float64)
        for start in range(0, len(rows), self.max_batch):
            chunk = rows[start:start + self.max_batch]
            values = self.model.probabilities(
                np.stack([r.public for r in chunk]),
                np.stack([r.world for r in chunk]),
                np.stack([r.perspective for r in chunk]))
            if (values.shape != (len(chunk), OUTCOME_CLASSES)
                    or not np.isfinite(values).all() or np.any(values < 0)
                    or not np.allclose(values.sum(axis=1), 1.0, rtol=0, atol=1e-5)):
                raise CWVError("model probability drift")
            out[start:start + len(chunk)] = values
            self.forward_calls += 1
        return out
