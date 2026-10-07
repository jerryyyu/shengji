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


W32_IDENTITY = "c4c6b7c30203ccf33ddbf549fa500d94659149d69bd368533e67db620b4a78dc"


def _combined_identity(version):
    # Independently rebuild the pre-extraction identity, with the actual archived
    # round source (not the compatibility helper's mapping).
    from pathlib import Path
    legacy = _legacy_identity(version)
    sources = dict(legacy['source_sha256s'])
    sources['round'] = hashlib.sha256(
        (Path(__file__).parent / 'data/round_release30.py.txt').read_bytes()).hexdigest()
    parts = [legacy['identity_schema'], legacy['afterstate_schema']]
    if version != 1:
        parts.append(f'enc_version:{version}')
    digest = hashlib.sha256('|'.join(parts + [f'{n}:{h}' for n,h in sorted(sources.items())]).encode()).hexdigest()
    return dict(legacy, source_sha256s=sources, implementation_sha256=digest)


@pytest.mark.parametrize('version', [1, 2, 4, 5])
def test_composed_migrations_match_independent_legacy_identity(version):
    from shengji.ai.cwv_encoder_compat import round_notice_history_import_identity
    current = cwv_policy.local_encoder_identity(version)
    before = copy.deepcopy(current)
    legacy = _combined_identity(version)
    assert round_notice_history_import_identity(current, cwv_policy.AFTERSTATE_SOURCE_PATHS) == legacy['implementation_sha256']
    assert current == before
    assert cwv_policy.verify_checkpoint_identity({'encoder':legacy}) == legacy['implementation_sha256']
    if version == 2:
        assert legacy['implementation_sha256'] == W32_IDENTITY


@pytest.mark.parametrize('mutation', ['version', 'round', 'memory', 'history'])
def test_composed_migrations_still_refuse_unproven_changes(tmp_path, monkeypatch, mutation):
    from shengji.ai.cwv_encoder_compat import round_notice_history_import_identity
    current = copy.deepcopy(cwv_policy.local_encoder_identity(2))
    paths = dict(cwv_policy.AFTERSTATE_SOURCE_PATHS)
    if mutation == 'version':
        current['enc_version'] = 6
    elif mutation == 'history':
        path = tmp_path / 'public_history.py'
        text = paths['public_history'].read_text()
        changed = text.replace('+= 0.5', '+= 0.25')
        assert changed != text
        path.write_text(changed)
        paths['public_history'] = path
    else:
        current['source_sha256s'][mutation] = 'f' * 64
    assert round_notice_history_import_identity(current, paths) != W32_IDENTITY
    monkeypatch.setattr(cwv_policy, 'AFTERSTATE_SOURCE_PATHS', paths)
    with pytest.raises(cwv_policy.CWVCheckpointMismatch):
        cwv_policy.verify_checkpoint_identity({'encoder': _combined_identity(2)}, identity=current)


def test_combined_legacy_checkpoint_loads_through_trainer_export_and_evaluator(tmp_path):
    from test_encoder_round_compat import _trainer_checkpoint
    from shengji.train.train_cwv import load_cwv_checkpoint
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
    checkpoint = _trainer_checkpoint(tmp_path, W32_IDENTITY)
    model, metadata, _ = load_cwv_checkpoint(checkpoint)
    assert model.config.enc_version == 2
    assert metadata['encoder']['implementation_sha256'] == W32_IDENTITY
    package = tmp_path / 'combined.npz'
    export_cwv_numpy(checkpoint, package)
    assert NumpyCompleteWorldEvaluator(package).enc_version == 2


@pytest.mark.parametrize('seed', [98260924, 98260925])
def test_both_migrations_together_preserve_replayed_tensors(monkeypatch, seed):
    from test_encoder_round_compat import _trace, PROVEN_VERSIONS
    from shengji.rl import value_afterstate, douzero_micro
    current, script = _trace(seed, PROVEN_VERSIONS)
    monkeypatch.setattr(value_afterstate, 'encode_public_history', douzero_micro.encode_public_history)
    legacy, replayed = _trace(seed, PROVEN_VERSIONS, legacy=True, script=script)
    assert len(current) == len(legacy) >= 20
    assert replayed == script
    for (seat_a, tensors_a), (seat_b, tensors_b) in zip(current, legacy):
        assert seat_a == seat_b
        for version in PROVEN_VERSIONS:
            assert tensors_a[version].tobytes() == tensors_b[version].tobytes()
