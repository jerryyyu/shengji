"""Codex's three #291 findings (review 5128477578), each bound shut.

F3: the identity gate validated the version the METADATA declared while
inference encoded at the version the MODEL CONFIG carried; nothing bound
them.  F2: the complete-world points leaf loaded a v2 head and built the
v1 row, crashing at the first real prediction.  F1: train_v0's --eval-luna
and evaluate() prepared v1 caches for a v2 model.
"""

from __future__ import annotations

import os
from inspect import signature
from unittest.mock import patch

import numpy as np
import pytest

from shengji.ai import cwv_policy
from shengji.ai.cwv_policy import CWVCheckpointMismatch
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import cwv_data, train_cwv, train_v0
from shengji.train.leaf_policy import CompleteWorldPointsHead, CompleteWorldPointsLeaf
from shengji.train.model import ValuePriorNet
from tests.test_cwv_encoder_v2 import REAL_CHECKPOINT, _played_state


def _net(version: int) -> ValueNetwork:
    return ValueNetwork(ValueModelConfig(
        architecture="mlp", width=8, history_layers=1, attention_heads=1, feedforward_width=16,
        public_dim=532 if version == 1 else 561, enc_version=version))


def _save(path, model_version, metadata_version=None, *, extra=None):
    meta = {"encoder": cwv_data.cwv_encoder_identity(metadata_version or model_version)}
    if metadata_version is None:                      # archived shape: no declaration
        meta["encoder"] = {k: v for k, v in meta["encoder"].items() if k != "enc_version"}
    meta.update(extra or {})
    train_cwv.save_cwv_checkpoint(path, _net(model_version), metadata=meta)
    return path


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    cwv_policy._cached_checkpoint.cache_clear()
    yield
    cwv_policy._cached_checkpoint.cache_clear()


LOADERS = [("trainer", train_cwv.load_cwv_checkpoint, train_cwv.TrainError),
           ("policy", cwv_policy.load_cwv_checkpoint, CWVCheckpointMismatch)]


# -------------------------------------------------------------------- F3

@pytest.mark.parametrize("label,loader,error", LOADERS, ids=["trainer", "policy"])
@pytest.mark.parametrize("model_version,metadata_version", [(2, 1), (1, 2)])
def test_a_declared_version_that_is_not_the_models_is_refused(
        tmp_path, label, loader, error, model_version, metadata_version):
    path = _save(tmp_path / f"m{model_version}-i{metadata_version}.pt",
                 model_version, metadata_version)
    with pytest.raises(error, match=f"declares encoder v{metadata_version} but the model "
                                    f"config is encoder v{model_version}"):
        loader(path)


@pytest.mark.parametrize("label,loader,error", LOADERS, ids=["trainer", "policy"])
def test_a_v2_model_with_no_declared_version_is_refused_not_defaulted(
        tmp_path, label, loader, error):
    path = _save(tmp_path / "m2-undeclared.pt", 2, metadata_version=None)
    with pytest.raises(error, match="declares no encoder version but the model config is "
                                    "encoder v2"):
        loader(path)


@pytest.mark.parametrize("label,loader,error", LOADERS, ids=["trainer", "policy"])
@pytest.mark.parametrize("version", [1, 2])
def test_a_consistent_checkpoint_loads_at_its_version(tmp_path, label, loader, error, version):
    path = _save(tmp_path / f"m{version}-i{version}.pt", version, version)
    model = loader(path)[0]
    assert model.config.enc_version == version
    assert model.config.public_dim == (532 if version == 1 else 561)


@pytest.mark.parametrize("label,loader,error", LOADERS, ids=["trainer", "policy"])
def test_a_v1_model_with_no_declared_version_is_v1(tmp_path, label, loader, error):
    path = _save(tmp_path / "m1-undeclared.pt", 1, metadata_version=None)
    assert loader(path)[0].config.enc_version == 1


@pytest.mark.skipif(not os.path.exists(REAL_CHECKPOINT), reason="needs the archived CWV checkpoint")
@pytest.mark.parametrize("label,loader,error", LOADERS, ids=["trainer", "policy"])
def test_the_archived_checkpoint_still_loads_through_both_loaders(label, loader, error):
    model = loader(REAL_CHECKPOINT)[0]
    assert model.config.enc_version == 1 and model.config.public_dim == 532


# -------------------------------------------------------------------- F2

def test_a_v2_points_head_predicts_a_real_leaf_at_its_own_width(tmp_path):
    aux = train_cwv.AuxPointsHead(8)
    path = _save(tmp_path / "v2-aux.pt", 2, 2, extra={"aux_points_head": aux.payload()})
    head = CompleteWorldPointsHead.from_checkpoint(path)
    assert head.input_dim == 833 and head.enc_version == 2
    rnd, seat = _played_state()
    value, raw, banked = CompleteWorldPointsLeaf(head).predict(rnd, seat)   # never raised
    assert np.isfinite(value) and np.isfinite(raw)


def test_a_v1_points_head_still_predicts_the_historical_804_row(tmp_path):
    from shengji.train.leaf_policy import cwv_leaf_inputs, cwv_reference_inputs

    aux = train_cwv.AuxPointsHead(8)
    path = _save(tmp_path / "v1-aux.pt", 1, 1, extra={"aux_points_head": aux.payload()})
    head = CompleteWorldPointsHead.from_checkpoint(path)
    assert head.input_dim == 804 and head.enc_version == 1
    rnd, seat = _played_state()
    assert cwv_leaf_inputs(rnd, seat).tobytes() == cwv_reference_inputs(rnd, seat).tobytes()
    assert cwv_leaf_inputs(rnd, seat, version=1).tobytes() == cwv_leaf_inputs(rnd, seat).tobytes()
    wide = cwv_leaf_inputs(rnd, seat, version=2)
    assert wide.shape == (833,) and wide[:531].tobytes() == cwv_leaf_inputs(rnd, seat)[:531].tobytes()
    CompleteWorldPointsLeaf(head).predict(rnd, seat)


# -------------------------------------------------------------------- F1

def _v2_public_checkpoint(tmp_path):
    cfg = train_v0.build_config(data=["never-opened"], hidden=8, encoder_version=2)
    population = train_v0.fit_population(
        {"deal:a": "train", "deal:b": "val", "deal:c": "test"}, stores=[])
    path = tmp_path / "public-v2.pt"
    train_v0.save_checkpoint(path, ValuePriorNet(cfg["arch"]), config=cfg, epoch=1, selection={},
                             baselines={}, calibration=None, split={}, population=population)
    return path


@pytest.mark.parametrize("options", [{"data": ["never-opened"]},
                                     {"eval_luna": "never-opened-luna"}],
                         ids=["data", "eval-luna"])
def test_evaluate_prepares_every_path_at_the_loaded_checkpoints_version(tmp_path, options):
    path = _v2_public_checkpoint(tmp_path)
    real = signature(train_v0.prepare_stores)
    seen = []

    class Reached(Exception):
        pass

    def observe(*args, **kwargs):
        bound = real.bind(*args, **kwargs)
        bound.apply_defaults()
        seen.append(bound.arguments["version"])
        raise Reached

    with patch.object(train_v0, "prepare_stores", observe):
        with pytest.raises(Reached):
            train_v0.evaluate(checkpoint=str(path), out=tmp_path / "eval", device="cpu",
                              cache_workers=1, log=None, **options)
    assert seen == [2], f"evaluation prepared at version {seen}, the checkpoint is v2"


def test_training_prepares_the_luna_holdout_at_the_configured_version():
    """The --eval-luna preparation inside ``train()`` must carry the run's
    version like the main preparation does.  ``train()`` cannot be driven to
    that call without a real store, so this pins the call site itself: the
    luna ``prepare_stores([eval_luna], ...)`` call passes ``version=``."""
    import inspect
    import re

    source = inspect.getsource(train_v0.train)
    calls = re.findall(r"prepare_stores\(\[eval_luna\],.*?\)\n", source, re.S)
    assert len(calls) == 1, "expected exactly one luna preparation call in train()"
    assert "version=enc_version" in calls[0], calls[0]
