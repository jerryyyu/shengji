from __future__ import annotations

import json

import numpy as np
import pytest

from shengji.rl import stage_c_model as MODEL
from shengji.rl import stage_c_npnet as NPNET
from shengji.rl.exact_resume import state_digest


pytestmark = pytest.mark.skipif(MODEL.torch is None, reason="torch unavailable")


def _export(tmp_path, *, seed: int, epoch: int = 8):
    MODEL.torch.manual_seed(seed)
    net = MODEL.StageCRankingOutcomeNet(hidden=NPNET.HIDDEN)
    state = {name: value.detach().cpu().clone()
             for name, value in net.state_dict().items()}
    digest = state_digest(state)
    out = tmp_path / f"seed-{seed}.npz"
    artifact = NPNET.export_model(
        state, out, surface="play", seed=seed, epoch=epoch,
        model_state_sha256=digest, checkpoint_sha256=f"{seed:064x}")
    return net, artifact


def test_numpy_export_matches_torch_rank_and_outcome(tmp_path) -> None:
    net, artifact = _export(tmp_path, seed=MODEL.TRAINING_SEEDS[0])
    loaded = NPNET.StageCNpNet(
        artifact["logical_path"], expected_sha256=artifact["sha256"],
        expected_metadata=artifact["metadata"])
    rng = np.random.default_rng(17)
    obs = rng.normal(size=MODEL.OBS_DIM).astype(np.float32)
    actions = rng.normal(size=(7, MODEL.ACT_DIM)).astype(np.float32)
    torch_rank, torch_logits = net.score_candidates(obs, actions)
    torch_outcomes = MODEL.torch.nn.functional.softmax(
        torch_logits, dim=-1).detach().cpu().numpy()
    rank, outcomes = loaded.score_candidates(obs, actions)
    assert np.allclose(rank, torch_rank.detach().cpu().numpy(),
                       rtol=1e-5, atol=1e-5)
    assert np.allclose(outcomes, torch_outcomes, rtol=1e-5, atol=1e-5)
    assert all(not value.flags.writeable for value in loaded.w.values())
    with pytest.raises(ValueError, match="read-only"):
        loaded.w["rankb"][0] = 123.0


def test_ensemble_requires_all_seeds_and_matches_report_rule(tmp_path) -> None:
    members = []
    for seed in MODEL.TRAINING_SEEDS:
        _net, artifact = _export(tmp_path, seed=seed)
        members.append(NPNET.StageCNpNet(artifact["logical_path"]))
    with pytest.raises(NPNET.StageCNumpyError, match="ensemble"):
        NPNET.StageCEnsemble(
            members[:-1], surface="play", head="ranking", epoch=8)
    ensemble = NPNET.StageCEnsemble(
        members, surface="play", head="ranking", epoch=8)
    obs = np.zeros(MODEL.OBS_DIM, dtype=np.float32)
    actions = np.zeros((3, MODEL.ACT_DIM), dtype=np.float32)
    value = ensemble.select(obs, actions)
    assert value["candidate_count"] == 3
    assert value["selected_index"] == 0
    assert sum(value["ranking_probabilities"]) == pytest.approx(1.0)
    assert value["ensemble_rule"]["tie_break"] \
        == "lowest candidate index within model-score epsilon 1e-7"


def test_loader_refuses_metadata_or_archive_member_drift(tmp_path) -> None:
    _net, artifact = _export(tmp_path, seed=MODEL.TRAINING_SEEDS[0])
    with np.load(artifact["logical_path"], allow_pickle=False) as archive:
        arrays = {name: archive[name].copy() for name in archive.files}
    metadata = json.loads(arrays["metadata"].tobytes())
    metadata["surface"] = "bury"
    arrays["metadata"] = np.frombuffer(
        NPNET.canonical_json(metadata), dtype=np.uint8).copy()
    forged = tmp_path / "forged.npz"
    np.savez_compressed(forged, **arrays)
    with pytest.raises(NPNET.StageCNumpyError, match="metadata"):
        NPNET.StageCNpNet(forged)

    missing = tmp_path / "missing.npz"
    arrays.pop("rankb")
    np.savez_compressed(missing, **arrays)
    with pytest.raises(NPNET.StageCNumpyError, match="members"):
        NPNET.StageCNpNet(missing)


def test_export_refuses_overwrite_and_false_state_digest(tmp_path) -> None:
    seed = MODEL.TRAINING_SEEDS[0]
    net = MODEL.StageCRankingOutcomeNet(hidden=NPNET.HIDDEN)
    state = net.state_dict()
    out = tmp_path / "model.npz"
    with pytest.raises(NPNET.StageCNumpyError, match="digest"):
        NPNET.export_model(
            state, out, surface="play", seed=seed, epoch=8,
            model_state_sha256="0" * 64, checkpoint_sha256="1" * 64)
    digest = state_digest(state)
    NPNET.export_model(
        state, out, surface="play", seed=seed, epoch=8,
        model_state_sha256=digest, checkpoint_sha256="1" * 64)
    with pytest.raises(NPNET.StageCNumpyError, match="existing"):
        NPNET.export_model(
            state, out, surface="play", seed=seed, epoch=8,
            model_state_sha256=digest, checkpoint_sha256="1" * 64)
