"""Dependency-light Stage-C inference and exact eight-seed ensembling.

Training and untouched REPORT evaluation use Torch snapshots.  Whole-game
screens and eventual production should not need Torch, so this module exports
the reviewed Stage-C architecture to a self-describing float32 NPZ and mirrors
the exact REPORT ensemble rule with NumPy.  It generates no candidates and
grants no policy, strength, promotion, or deployment authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .encode import ACT_DIM, OBS_DIM
from .exact_resume import state_digest
from .stage_c_model import TRAINING_SEEDS, UTILITY_BINS
from .stage_c_report import MODEL_SCORE_TIE_EPSILON


SCHEMA = "teacher-stage-c-numpy-model-v1"
HIDDEN = 256
ARRAY_NAMES = (
    "obs0w", "obs0b", "obs2w", "obs2b", "action0w", "action0b",
    "joint0w", "joint0b", "rankw", "rankb", "outcomew", "outcomeb",
)
STATE_DICT_NAMES = {
    "obs_trunk.0.weight": "obs0w",
    "obs_trunk.0.bias": "obs0b",
    "obs_trunk.2.weight": "obs2w",
    "obs_trunk.2.bias": "obs2b",
    "action_trunk.0.weight": "action0w",
    "action_trunk.0.bias": "action0b",
    "joint.0.weight": "joint0w",
    "joint.0.bias": "joint0b",
    "rank_head.weight": "rankw",
    "rank_head.bias": "rankb",
    "outcome_head.weight": "outcomew",
    "outcome_head.bias": "outcomeb",
}
EXPECTED_SHAPES = {
    "obs0w": (HIDDEN, OBS_DIM),
    "obs0b": (HIDDEN,),
    "obs2w": (128, HIDDEN),
    "obs2b": (128,),
    "action0w": (64, ACT_DIM),
    "action0b": (64,),
    "joint0w": (128, 192),
    "joint0b": (128,),
    "rankw": (1, 128),
    "rankb": (1,),
    "outcomew": (len(UTILITY_BINS), 128),
    "outcomeb": (len(UTILITY_BINS),),
}


class StageCNumpyError(RuntimeError):
    """An exported model, input tensor, or ensemble identity drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _self_hash(value: Mapping[str, object], field: str) -> str:
    return hashlib.sha256(canonical_json({
        key: item for key, item in value.items() if key != field
    })).hexdigest()


def _metadata_bytes(metadata: Mapping[str, object]) -> np.ndarray:
    return np.frombuffer(canonical_json(metadata), dtype=np.uint8).copy()


def _metadata(array: np.ndarray) -> dict:
    if array.dtype != np.uint8 or array.ndim != 1 or array.size > 1 << 20:
        raise StageCNumpyError("Stage-C NumPy metadata geometry drift")
    try:
        value = json.loads(array.tobytes())
    except (UnicodeDecodeError, ValueError) as exc:
        raise StageCNumpyError("Stage-C NumPy metadata is invalid") from exc
    if not isinstance(value, dict):
        raise StageCNumpyError("Stage-C NumPy metadata root is not an object")
    return value


def _arrays_sha256(arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in ARRAY_NAMES:
        array = arrays[name]
        digest.update(canonical_json({
            "name": name, "shape": list(array.shape), "dtype": str(array.dtype),
        }))
        digest.update(np.ascontiguousarray(array).tobytes(order="C"))
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _state_arrays(state_dict: Mapping[str, object]) -> dict[str, np.ndarray]:
    if set(state_dict) != set(STATE_DICT_NAMES):
        raise StageCNumpyError("Stage-C state-dict architecture drift")
    result = {}
    for source, target in STATE_DICT_NAMES.items():
        value = state_dict[source]
        try:
            array = value.detach().cpu().numpy()
        except AttributeError as exc:
            raise StageCNumpyError(
                "Stage-C export requires tensor state-dict values") from exc
        array = np.asarray(array, dtype=np.float32)
        if array.shape != EXPECTED_SHAPES[target] or not np.isfinite(array).all():
            raise StageCNumpyError(f"Stage-C array geometry drift: {target}")
        result[target] = np.ascontiguousarray(array)
    return result


def export_model(
    state_dict: Mapping[str, object], out: str | os.PathLike[str], *,
    surface: str, seed: int, epoch: int, model_state_sha256: str,
    checkpoint_sha256: str,
) -> dict:
    """Publish one immutable, self-describing Stage-C NumPy artifact."""
    if (surface not in {"play", "bury"}
            or seed not in TRAINING_SEEDS
            or isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0
            or not _is_sha256(model_state_sha256)
            or not _is_sha256(checkpoint_sha256)):
        raise StageCNumpyError("Stage-C export identity drift")
    if state_digest(state_dict) != model_state_sha256:
        raise StageCNumpyError("Stage-C export model-state digest drift")
    arrays = _state_arrays(state_dict)
    metadata = {
        "schema": SCHEMA,
        "surface": surface,
        "seed": seed,
        "epoch": epoch,
        "model_state_sha256": model_state_sha256,
        "checkpoint_sha256": checkpoint_sha256,
        "architecture": f"StageCRankingOutcomeNet(hidden={HIDDEN})",
        "obs_dim": OBS_DIM,
        "act_dim": ACT_DIM,
        "utility_bins": list(UTILITY_BINS),
        "dtype": "float32",
        "array_names": list(ARRAY_NAMES),
        "arrays_sha256": _arrays_sha256(arrays),
    }
    metadata["metadata_sha256"] = _self_hash(metadata, "metadata_sha256")
    destination = Path(out)
    partial = Path(str(destination) + ".partial")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(destination) or os.path.lexists(partial):
        raise StageCNumpyError(f"refusing existing Stage-C export: {destination}")
    try:
        with partial.open("xb") as handle:
            np.savez_compressed(handle, metadata=_metadata_bytes(metadata), **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(partial, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise StageCNumpyError(
                f"refusing raced Stage-C export: {destination}") from exc
        partial.unlink()
    except BaseException:
        # Preserve a completed or partial attempt. A reviewer can inspect it,
        # and the same logical artifact cannot be silently retried.
        raise
    return {
        "logical_path": str(destination),
        "sha256": sha256_file(destination),
        "metadata": metadata,
    }


class StageCNpNet:
    """Validated NumPy mirror of one StageCRankingOutcomeNet snapshot."""

    def __init__(self, path: str | os.PathLike[str], *,
                 expected_sha256: str | None = None,
                 expected_metadata: Mapping[str, object] | None = None):
        self.path = Path(path)
        try:
            info = self.path.lstat()
        except OSError as exc:
            raise StageCNumpyError("Stage-C NumPy artifact is unavailable") from exc
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or self.path.is_symlink()):
            raise StageCNumpyError(
                "Stage-C NumPy artifact is not regular/unlinked")
        if expected_sha256 is not None and sha256_file(self.path) != expected_sha256:
            raise StageCNumpyError("Stage-C NumPy artifact SHA-256 drift")
        try:
            with np.load(self.path, allow_pickle=False) as archive:
                if (len(archive.files) != len(ARRAY_NAMES) + 1
                        or set(archive.files) != {*ARRAY_NAMES, "metadata"}):
                    raise StageCNumpyError("Stage-C NumPy archive members drift")
                self.metadata = _metadata(archive["metadata"])
                self.w = {}
                for name in ARRAY_NAMES:
                    array = archive[name]
                    if array.dtype != np.float32:
                        raise StageCNumpyError(
                            f"Stage-C NumPy array dtype drift: {name}")
                    loaded = np.asarray(array).copy()
                    loaded.setflags(write=False)
                    self.w[name] = loaded
        except (OSError, ValueError) as exc:
            raise StageCNumpyError("cannot load Stage-C NumPy artifact") from exc
        if (self.metadata.get("schema") != SCHEMA
                or self.metadata.get("metadata_sha256")
                != _self_hash(self.metadata, "metadata_sha256")
                or self.metadata.get("surface") not in {"play", "bury"}
                or self.metadata.get("seed") not in TRAINING_SEEDS
                or isinstance(self.metadata.get("epoch"), bool)
                or not isinstance(self.metadata.get("epoch"), int)
                or self.metadata.get("epoch") <= 0
                or any(not _is_sha256(self.metadata.get(field))
                       for field in ("model_state_sha256", "checkpoint_sha256"))
                or self.metadata.get("architecture")
                != f"StageCRankingOutcomeNet(hidden={HIDDEN})"
                or self.metadata.get("obs_dim") != OBS_DIM
                or self.metadata.get("act_dim") != ACT_DIM
                or self.metadata.get("utility_bins") != list(UTILITY_BINS)
                or self.metadata.get("dtype") != "float32"
                or self.metadata.get("array_names") != list(ARRAY_NAMES)
                or self.metadata.get("arrays_sha256") != _arrays_sha256(self.w)
                or (expected_metadata is not None
                    and self.metadata != dict(expected_metadata))):
            raise StageCNumpyError("Stage-C NumPy metadata identity drift")
        for name, shape in EXPECTED_SHAPES.items():
            if (self.w[name].shape != shape
                    or not np.isfinite(self.w[name]).all()):
                raise StageCNumpyError(f"Stage-C NumPy array drift: {name}")

    @staticmethod
    def _linear(value: np.ndarray, weight: np.ndarray,
                bias: np.ndarray) -> np.ndarray:
        return value @ weight.T + bias

    def score_candidates(
        self, obs: Sequence[object], actions: Sequence[Sequence[object]],
    ) -> tuple[np.ndarray, np.ndarray]:
        try:
            obs_array = np.asarray(obs, dtype=np.float32)
            action_array = np.asarray(actions, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise StageCNumpyError("Stage-C NumPy inference input drift") from exc
        if (obs_array.shape != (OBS_DIM,)
                or action_array.ndim != 2
                or action_array.shape[0] <= 0
                or action_array.shape[1] != ACT_DIM
                or not np.isfinite(obs_array).all()
                or not np.isfinite(action_array).all()):
            raise StageCNumpyError("Stage-C NumPy inference input drift")
        obs_hidden = np.maximum(self._linear(
            obs_array, self.w["obs0w"], self.w["obs0b"]), 0.0)
        obs_features = np.maximum(self._linear(
            obs_hidden, self.w["obs2w"], self.w["obs2b"]), 0.0)
        action_features = np.maximum(self._linear(
            action_array, self.w["action0w"], self.w["action0b"]), 0.0)
        repeated = np.repeat(obs_features[None, :], len(action_array), axis=0)
        joint = np.maximum(self._linear(
            np.concatenate([repeated, action_features], axis=-1),
            self.w["joint0w"], self.w["joint0b"]), 0.0)
        ranks = self._linear(joint, self.w["rankw"], self.w["rankb"]).reshape(-1)
        logits = self._linear(
            joint, self.w["outcomew"], self.w["outcomeb"])
        shifted = logits - logits.max(axis=-1, keepdims=True)
        outcomes = np.exp(shifted)
        outcomes /= outcomes.sum(axis=-1, keepdims=True)
        if (not np.isfinite(ranks).all() or not np.isfinite(outcomes).all()
                or not np.allclose(outcomes.sum(axis=-1), 1.0,
                                   rtol=1e-6, atol=1e-6)):
            raise StageCNumpyError("Stage-C NumPy inference output drift")
        return ranks, outcomes


class StageCEnsemble:
    """Exact eight-seed cohort with the untouched-REPORT averaging rule."""

    def __init__(self, members: Sequence[StageCNpNet], *,
                 surface: str, head: str, epoch: int):
        if (surface not in {"play", "bury"}
                or head not in {"ranking", "outcome"}
                or [member.metadata.get("seed") for member in members]
                != list(TRAINING_SEEDS)
                or any(member.metadata.get("surface") != surface
                       or member.metadata.get("epoch") != epoch
                       for member in members)):
            raise StageCNumpyError("Stage-C ensemble identity drift")
        self.members = list(members)
        self.surface = surface
        self.head = head
        self.epoch = epoch

    def select(
        self, obs: Sequence[object], actions: Sequence[Sequence[object]],
    ) -> dict:
        rank_votes = []
        outcomes = []
        for member in self.members:
            ranks, distributions = member.score_candidates(obs, actions)
            ranks = ranks.astype(np.float64)
            distributions = distributions.astype(np.float64)
            shifted = ranks - ranks.max()
            votes = np.exp(shifted)
            votes /= votes.sum()
            rank_votes.append(votes)
            outcomes.append(distributions)
        mean_rank = np.mean(np.stack(rank_votes), axis=0, dtype=np.float64)
        mean_outcome = np.mean(np.stack(outcomes), axis=0, dtype=np.float64)
        outcome_scores = mean_outcome @ np.asarray(UTILITY_BINS, dtype=np.float64)
        scores = mean_rank if self.head == "ranking" else outcome_scores
        if not np.isfinite(scores).all():
            raise StageCNumpyError("Stage-C ensemble score drift")
        maximum = float(scores.max())
        selected = next(
            index for index, score in enumerate(scores)
            if maximum - float(score) <= MODEL_SCORE_TIE_EPSILON)
        return {
            "surface": self.surface,
            "head": self.head,
            "epoch": self.epoch,
            "seeds": list(TRAINING_SEEDS),
            "candidate_count": len(scores),
            "selected_index": selected,
            "ranking_probabilities": mean_rank.astype(float).tolist(),
            "outcome_expected_signed_level": outcome_scores.astype(float).tolist(),
            "ensemble_rule": {
                "ranking": "mean within-ballot softmax probability across seeds",
                "outcome": "mean eight-bin probability across seeds",
                "tie_break": (
                    "lowest candidate index within model-score epsilon 1e-7"),
            },
        }
