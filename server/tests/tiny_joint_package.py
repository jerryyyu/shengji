"""A tiny synthetic joint ``.npz`` package for tests that need real NumPy model
loading without a trained checkpoint."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from shengji.ai.cwv_numpy import PACKAGE_SCHEMA_V2, CWVNumpyConfig, expected_arrays
from shengji.ai.cwv_policy import file_sha256


def _write_joint_package(path: Path, seed: int) -> str:
    """A tiny plain-trunk joint package (value + 54-card policy head) with
    random weights; returns its sha256."""
    from shengji.ai.cwv_policy import local_encoder_identity
    cfg = CWVNumpyConfig(architecture="mlp", width=8, feedforward_width=16, public_dim=561,
                         enc_version=2, trunk_block="plain", trunk_layers=2, policy_head=True)
    rng = np.random.default_rng(seed)
    weights = {k: (rng.standard_normal(shape) * 0.2).astype(np.float32)
               for k, shape in expected_arrays(cfg).items()}
    payload = {"schema": PACKAGE_SCHEMA_V2,
               "config": {"architecture": "mlp", "width": 8, "feedforward_width": 16,
                          "public_dim": 561, "enc_version": 2, "trunk_block": "plain",
                          "trunk_layers": 2, "policy_head": True},
               "original_checkpoint_sha256": "0" * 64,
               "metadata": {"exported_value_head": "outcome",
                            "encoder": local_encoder_identity(2), "sees_hidden_hands": True}}
    np.savez_compressed(path, metadata=np.asarray(json.dumps(payload, sort_keys=True)), **weights)
    return file_sha256(path)
