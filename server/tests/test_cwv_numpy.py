import copy
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

from shengji.ai.cwv_numpy import (CWVNumpyConfig, CWVNumpyError,
                                   CWVNumpyMLP, PACKAGE_SCHEMA,
                                   load_numpy_checkpoint)


def _weights(config):
    rng = np.random.default_rng(7)
    shape = config.public_dim + 5 * 54 + 2
    return {
        "trunk0_weight": rng.normal(size=(config.feedforward_width, shape)).astype("f4"),
        "trunk0_bias": rng.normal(size=config.feedforward_width).astype("f4"),
        "trunk1_weight": rng.normal(size=(config.width, config.feedforward_width)).astype("f4"),
        "trunk1_bias": rng.normal(size=config.width).astype("f4"),
        "head_weight": rng.normal(size=(204, config.width)).astype("f4"),
        "head_bias": rng.normal(size=204).astype("f4"),
    }


def test_runtime_matches_torch_mlp_and_deepcopy_shares_weights():
    torch = pytest.importorskip("torch")
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    cfg = CWVNumpyConfig("mlp", 8, 12, 532, 1)
    model = CWVNumpyMLP(cfg, _weights(cfg))
    tc = ValueModelConfig(architecture="mlp", width=8, feedforward_width=12,
                          public_dim=532, enc_version=1, attention_heads=1)
    tm = ValueNetwork(tc)
    with torch.no_grad():
        sd = tm.state_dict()
        for src, dst in (("trunk.0.weight", "trunk0_weight"), ("trunk.0.bias", "trunk0_bias"),
                         ("trunk.3.weight", "trunk1_weight"), ("trunk.3.bias", "trunk1_bias"),
                         ("head.weight", "head_weight"), ("head.bias", "head_bias")):
            sd[src].copy_(torch.from_numpy(model._weights[dst].copy()))
    public = np.random.default_rng(8).normal(size=(3, 532)).astype("f4")
    world = np.random.default_rng(9).normal(size=(3, 5, 54)).astype("f4")
    perspective = np.asarray([[1, 0], [0, 1], [1, 0]], dtype="f4")
    got = model.probabilities(public, world, perspective)
    with torch.no_grad():
        logits = tm(torch.from_numpy(public), torch.zeros((3, 1, 64)),
                    torch.ones((3, 1), dtype=torch.bool), torch.from_numpy(world),
                    torch.from_numpy(perspective))
        want = torch.softmax(logits, 1).numpy()
    np.testing.assert_allclose(got, want, rtol=2e-5, atol=2e-6)
    assert copy.deepcopy(model)._weights is model._weights


def test_package_roundtrip_and_fresh_process(tmp_path):
    cfg = CWVNumpyConfig("mlp", 8, 8, 561, 2)
    weights = _weights(cfg)
    payload = {"schema": PACKAGE_SCHEMA, "config": cfg.__dict__,
               "original_checkpoint_sha256": "a" * 64, "metadata": {"encoder": {"enc_version": 2}}}
    path = tmp_path / "model.npz"
    np.savez_compressed(path, metadata=np.asarray(json.dumps(payload)), **weights)
    model = load_numpy_checkpoint(path)
    assert model.enc_version == 2 and model.source_checkpoint_sha256 == "a" * 64
    code = "import sys; import shengji.ai.cwv_numpy; assert 'torch' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True, env={"PYTHONPATH": "server"})


def test_bad_batch_and_nonfinite_weights_rejected():
    cfg = CWVNumpyConfig("mlp", 8, 8, 532, 1)
    weights = _weights(cfg)
    weights["head_bias"][0] = np.nan
    with pytest.raises(CWVNumpyError):
        CWVNumpyMLP(cfg, weights)


@pytest.mark.parametrize("version,public_dim", [(1, 532), (2, 561)])
def test_v1_v2_runtime_parity(version, public_dim):
    torch = pytest.importorskip("torch")
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    cfg = CWVNumpyConfig("mlp", 32, 64, public_dim, version)
    runtime = CWVNumpyMLP(cfg, _weights(cfg))
    tm = ValueNetwork(ValueModelConfig(architecture="mlp", width=32,
                          feedforward_width=64, public_dim=public_dim,
                          enc_version=version, attention_heads=1))
    with torch.no_grad():
        for src, dst in (("trunk.0.weight", "trunk0_weight"), ("trunk.0.bias", "trunk0_bias"),
                         ("trunk.3.weight", "trunk1_weight"), ("trunk.3.bias", "trunk1_bias"),
                         ("head.weight", "head_weight"), ("head.bias", "head_bias")):
            tm.state_dict()[src].copy_(torch.from_numpy(runtime._weights[dst].copy()))
    rng = np.random.default_rng(version)
    arrays = (rng.normal(size=(4, public_dim)).astype("f4"),
              rng.normal(size=(4, 5, 54)).astype("f4"),
              np.tile(np.asarray([[1, 0]], "f4"), (4, 1)))
    got = runtime.probabilities(*arrays)
    with torch.no_grad():
        logits = tm(torch.from_numpy(arrays[0]), torch.zeros((4, 1, 64)),
                    torch.ones((4, 1), dtype=torch.bool), torch.from_numpy(arrays[1]),
                    torch.from_numpy(arrays[2]))
    np.testing.assert_allclose(got, torch.softmax(logits, 1).numpy(), rtol=2e-5, atol=2e-6)
    support = np.asarray([(-101.5 + i if i < 102 else .5 + i - 102)
                          for i in range(204)])
    assert np.isfinite(got @ support).all()


def _actual_export(tmp_path, version=1):
    torch = pytest.importorskip("torch")
    from shengji.ai.cwv_policy import local_encoder_identity
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    from shengji.rl.value_checkpoint import save_checkpoint
    from scripts.export_cwv_numpy import export_cwv_numpy
    dim = {1: 532, 2: 561}[version]
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32,
                          feedforward_width=64, public_dim=dim, enc_version=version,
                          attention_heads=1))
    ckpt = tmp_path / f"source-v{version}.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(version),
                                         "sees_hidden_hands": True})
    package = tmp_path / f"export-v{version}.npz"
    export_cwv_numpy(ckpt, package)
    return package, net


@pytest.mark.parametrize("version", [1, 2])
def test_actual_export_roundtrip_and_torch_free_load_infer(tmp_path, version):
    package, _net = _actual_export(tmp_path, version)
    model = load_numpy_checkpoint(package)
    assert model.enc_version == version and model.package_sha256
    code = """
import sys
class Block:
  def find_spec(self, fullname, path=None, target=None):
    if fullname == 'torch' or fullname.startswith('torch.'):
      raise RuntimeError('torch import blocked')
    return None
sys.meta_path.insert(0, Block())
from shengji.ai.cwv_numpy import load_numpy_checkpoint
import numpy as np
m = load_numpy_checkpoint(sys.argv[1]); d=m.public_dim
r=m.probabilities(np.zeros((2,d), 'f4'), np.zeros((2,5,54), 'f4'), np.tile([[1,0]], (2,1)).astype('f4'))
assert r.shape == (2,204) and np.isfinite(r).all()
"""
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).parents[1])}
    subprocess.run([sys.executable, "-c", code, str(package)], check=True, env=env)


def test_export_is_nonoverwriting_and_cleans_failed_temp(tmp_path, monkeypatch):
    package, _net = _actual_export(tmp_path)
    sentinel = package.read_bytes()
    from scripts import export_cwv_numpy
    with pytest.raises(FileExistsError):
        export_cwv_numpy.export_cwv_numpy(tmp_path / "source-v1.pt", package)
    assert package.read_bytes() == sentinel
    target = tmp_path / "failed.npz"
    original = export_cwv_numpy.np.savez_compressed
    def fail(*args, **kwargs):
        raise OSError("injected serialization failure")
    monkeypatch.setattr(export_cwv_numpy.np, "savez_compressed", fail)
    with pytest.raises(OSError):
        export_cwv_numpy.export_cwv_numpy(tmp_path / "source-v1.pt", target)
    assert not target.exists()
    assert not list(tmp_path.glob("failed.npz.tmp-*.npz"))
    monkeypatch.setattr(export_cwv_numpy.np, "savez_compressed", original)


def test_export_keeps_population_provenance_without_room_copy_bloat(tmp_path):
    from shengji.ai.cwv_policy import local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint, load_checkpoint
    from scripts.export_cwv_numpy import export_cwv_numpy
    _package, model = _actual_export(tmp_path)
    population = {"shards": [{"path": f"source-{i}", "sha": "a" * 64} for i in range(500)]}
    source = tmp_path / "population.pt"
    save_checkpoint(source, model, metadata={"encoder": local_encoder_identity(),
                                            "population": population})
    target = tmp_path / "population.npz"
    original_sha = export_cwv_numpy(source, target)
    exported = load_numpy_checkpoint(target)
    assert "population" not in exported.metadata
    reference = exported.metadata["training_population_reference"]
    assert reference["checkpoint_sha256"] == original_sha
    assert reference["metadata_key"] == "population"
    assert len(reference["canonical_json_sha256"]) == 64
    assert reference["canonical_json_bytes"] > 10000
    assert load_checkpoint(source)[1]["population"] == population


def test_immutability_metadata_and_empty_batch(tmp_path):
    cfg = CWVNumpyConfig("mlp", 8, 8, 532, 1)
    metadata = {"nested": {"x": 1}}
    model = CWVNumpyMLP(cfg, _weights(cfg), metadata=metadata,
                        original_checkpoint_sha256="a" * 64)
    with pytest.raises(TypeError):
        model._weights["head_bias"] = model._weights["head_bias"]
    with pytest.raises(ValueError):
        model._weights["head_bias"].setflags(write=True)
    clone = copy.deepcopy(model)
    clone.metadata["nested"]["x"] = 2
    assert model.metadata["nested"]["x"] == 1
    assert model.probabilities(np.empty((0,532), "f4"), np.empty((0,5,54), "f4"),
                               np.empty((0,2), "f4")).shape == (0,204)


def test_reject_hostile_packages(tmp_path):
    cfg = CWVNumpyConfig("mlp", 8, 8, 532, 1)
    weights = _weights(cfg)
    good = {"schema": PACKAGE_SCHEMA, "config": cfg.__dict__,
            "original_checkpoint_sha256": "a" * 64, "metadata": {}}
    def write(name, payload=good, arrays=weights):
        path = tmp_path / name
        np.savez_compressed(path, metadata=np.asarray(json.dumps(payload)), **arrays)
        return path
    badsha = dict(good, original_checkpoint_sha256="z" * 64)
    with pytest.raises(CWVNumpyError): load_numpy_checkpoint(write("badsha", badsha))
    missing = dict(good); del missing["metadata"]
    with pytest.raises(CWVNumpyError): load_numpy_checkpoint(write("missing", missing))
    malformed = dict(weights); malformed["head_bias"] = np.zeros(3, "f4")
    with pytest.raises(CWVNumpyError): load_numpy_checkpoint(write("shape", arrays=malformed))
    extra = dict(good, extra=1)
    with pytest.raises(CWVNumpyError): load_numpy_checkpoint(write("extra", extra))
    oversized = tmp_path / "oversized.npz"
    with oversized.open("wb") as f: f.truncate(128 * 1024 * 1024 + 1)
    with pytest.raises(CWVNumpyError): load_numpy_checkpoint(oversized)
    duplicate = tmp_path / "duplicate.npz"
    with zipfile.ZipFile(duplicate, "w") as z:
        z.writestr("metadata.npy", b"x")
        z.writestr("metadata.npy", b"y")
    with pytest.raises(CWVNumpyError): load_numpy_checkpoint(duplicate)
