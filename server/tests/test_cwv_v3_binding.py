"""v3 feature changes bind caches/checkpoints without rewriting legacy v1/v2."""
import numpy as np
import pytest

from shengji.ai import cwv_policy as P
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train import cwv_data as D, train_cwv as T
from tests.test_cwv_encoder_v2 import _played_state
from tests.test_cwv_train import store_dir  # noqa: F401 - shared synthetic store fixture


@pytest.mark.parametrize("version", [1, 2, 3])
def test_training_and_inference_identity_agree(version):
    data = D.cwv_encoder_identity(version)
    policy = P.local_encoder_identity(version)
    assert data["implementation_sha256"] == policy["implementation_sha256"]
    assert data["source_sha256s"] == policy["source_sha256s"]
    assert ("encode_versions" in data["source_sha256s"]) == (version == 3)


def test_versioned_source_change_affects_only_v3_identity_and_cache_key(tmp_path, monkeypatch):
    previous = {v: D.cwv_encoder_identity(v) for v in (1, 2, 3)}
    before_key = D.encoder_cache_key(3)
    source = tmp_path / "cursor.py"
    source.write_text("changed feature implementation\n")
    for paths in (D.CWV_V3_SOURCE_PATHS, P.AFTERSTATE_V3_SOURCE_PATHS):
        monkeypatch.setitem(paths, "encode_versions", source)
    assert D.cwv_encoder_identity(1) == previous[1]
    assert D.cwv_encoder_identity(2) == previous[2]
    assert D.cwv_encoder_identity(3)["implementation_sha256"] != previous[3]["implementation_sha256"]
    assert D.encoder_cache_key(3) != before_key
    assert D.cwv_encoder_identity(3)["implementation_sha256"] == P.local_encoder_identity(3)["implementation_sha256"]


def test_v3_checkpoint_scores_actual_state_and_rejects_feature_drift(tmp_path, monkeypatch):
    model = ValueNetwork(ValueModelConfig(architecture="mlp", width=8,
        history_layers=1, attention_heads=1, feedforward_width=16,
        public_dim=565, enc_version=3))
    path = tmp_path / "v3.pt"
    T.save_cwv_checkpoint(path, model, metadata={"encoder": D.cwv_encoder_identity(3)})
    assert T.load_cwv_checkpoint(path)[0].config.enc_version == 3
    evaluator = P.CompleteWorldEvaluator(path, threads=1, encoding="mlp-static")
    rnd, seat = _played_state()
    assert np.isfinite(evaluator.score([rnd], seat)).all()
    source = tmp_path / "changed.py"
    source.write_text("changed v3 arithmetic\n")
    # The integrated serving path uses the training identity provider;
    # the local provider is its deployment-only fallback. Exercise both.
    for paths in (D.CWV_V3_SOURCE_PATHS, P.AFTERSTATE_V3_SOURCE_PATHS):
        monkeypatch.setitem(paths, "encode_versions", source)
    P._cached_checkpoint.cache_clear()
    with pytest.raises(P.CWVCheckpointMismatch):
        P.load_cwv_checkpoint(path)
    with pytest.raises(T.TrainError, match="encoder"):
        T.load_cwv_checkpoint(path)


def test_v3_raw_store_trains_and_scores_a_real_checkpoint(store_dir, tmp_path):
    receipt = T.train(data=[str(store_dir)], out=tmp_path / "trained-v3",
                      encoder_version=3, arch="mlp", device="cpu", epochs=1,
                      hidden=16, batch_size=64, seed=7, n_boot=2, rank_limit=2,
                      val_fraction=1/3, test_fraction=1/3, cache_workers=1,
                      eval_workers=1, bench_batch=8, log=None)
    assert receipt["config"]["encoder_version"] == 3
    assert receipt["config"]["public_dim"] == 565
    assert receipt["counts"]["records"]["reference_checked"] >= 3
    assert receipt["population"]["counts"] == {"train": 1, "val": 1, "test": 1}
    assert receipt["final"]["test"]["ranking"]["records"] > 0
    evaluator = P.CompleteWorldEvaluator(tmp_path / "trained-v3" / "best.pt",
                                        threads=1, encoding="mlp-static")
    rnd, seat = _played_state()
    assert np.isfinite(evaluator.score([rnd], seat)).all()
