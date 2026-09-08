import copy
import hashlib

import pytest

from shengji.ai import cwv_policy
from shengji.ai.cwv_encoder_compat import history_import_move_identity


def _legacy_identity(version):
    current = cwv_policy.local_encoder_identity(version)
    # Independently reconstruct the old recipe, not the compatibility helper.
    sources = dict(current["source_sha256s"])
    sources.pop("public_history")
    source = cwv_policy.AFTERSTATE_SOURCE_PATHS["value_afterstate"].read_bytes()
    source = source.replace(b"from .public_history import HISTORY_EVENT_DIM, encode_public_history",
                            b"from .douzero_micro import HISTORY_EVENT_DIM, encode_public_history")
    sources["value_afterstate"] = hashlib.sha256(source).hexdigest()
    parts = [current["identity_schema"], current["afterstate_schema"]]
    if version != 1:
        parts.append(f"enc_version:{version}")
    digest = hashlib.sha256("|".join(parts + [f"{n}:{h}" for n, h in sorted(sources.items())]).encode()).hexdigest()
    return {**current, "source_sha256s": sources, "implementation_sha256": digest}


@pytest.mark.parametrize("version", [1, 2])
def test_source_move_accepts_old_full_identity_and_actual_legacy_export(tmp_path, version):
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
    legacy = _legacy_identity(version)
    assert legacy["implementation_sha256"] != cwv_policy.local_encoder_identity(version)["implementation_sha256"]
    assert cwv_policy.verify_checkpoint_identity({"encoder": legacy}) == legacy["implementation_sha256"]
    model = ValueNetwork(ValueModelConfig(architecture="mlp", width=32,
                         feedforward_width=64, attention_heads=1,
                         enc_version=version, public_dim={1: 532, 2: 561}[version]))
    source = tmp_path / "legacy.pt"
    package = tmp_path / "legacy.npz"
    save_checkpoint(source, model, metadata={"encoder": legacy})
    export_cwv_numpy(source, package)
    assert NumpyCompleteWorldEvaluator(package).enc_version == version


@pytest.mark.parametrize("mutation", ["computation", "constant", "unrelated_encoder"])
def test_legacy_exception_refuses_real_semantic_drift(tmp_path, monkeypatch, mutation):
    legacy = _legacy_identity(1)
    paths = dict(cwv_policy.AFTERSTATE_SOURCE_PATHS)
    key = "value_afterstate" if mutation == "unrelated_encoder" else "public_history"
    source = paths[key].read_text()
    if mutation == "computation":
        changed = source.replace("+= 0.5", "+= 0.25")
    elif mutation == "constant":
        changed = source.replace("HISTORY_MAX_EVENTS = 100", "HISTORY_MAX_EVENTS = 99")
    else:
        changed = source.replace("OUTCOME_CLASSES = 204", "OUTCOME_CLASSES = 203")
    assert changed != source
    target = tmp_path / paths[key].name
    target.write_text(changed)
    paths[key] = target
    monkeypatch.setattr(cwv_policy, "AFTERSTATE_SOURCE_PATHS", paths)
    current = cwv_policy.local_encoder_identity(1)
    with pytest.raises(cwv_policy.CWVCheckpointMismatch, match="checkpoint encoder identity"):
        cwv_policy.verify_checkpoint_identity({"encoder": legacy}, identity=current)


def test_training_and_serving_hash_actual_extracted_dependency():
    from shengji.train.cwv_data import cwv_encoder_identity
    for version in (1, 2):
        actual = cwv_policy.local_encoder_identity(version)
        assert "public_history" in actual["source_sha256s"]
        assert actual["implementation_sha256"] == cwv_encoder_identity(version)["implementation_sha256"]
