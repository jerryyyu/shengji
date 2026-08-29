"""Target-free Value-Afterstate V2 inference and ensemble selection.

This boundary consumes only canonical complete-world afterstates and model
checkpoints.  It cannot accept continuation outcomes or terminal labels.  The
integer probability representation makes the sealed prediction artifact
strict JSON and gives the later evaluator one exact population to reopen.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    OUTCOME_CLASSES,
    WorldAfterstateError,
    WorldAfterstateTensorsV0,
    build_afterstate_tensors,
    category_signed_level,
    reopen_afterstate_audit,
)
from .world_afterstate_v2_model import (
    WorldAfterstateV2Batch,
    WorldAfterstateValueV2,
    collate_world_afterstate_tensors,
)
from .world_afterstate_v2_controls import CONTROL_NAMES as TRAINING_CONTROL_NAMES
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_protocol import (
    PRIOR_POINTS_BUCKETS, STATE_SOURCES, prior_points_bucket,
)
from .world_afterstate_v2_training import model_state_sha256


ROOT_SCHEMA = "world-afterstate-v2-inference-root-v1"
PREDICTION_SCHEMA = "world-afterstate-v2-candidate-prediction-v1"
POPULATION_SCHEMA = "world-afterstate-v2-prediction-population-v1"
PROBABILITY_SCALE = 1_000_000_000
MEMBERS_PER_BLOCK = 4
SEED_BLOCKS = (1, 2)
CONTROL_NAMES = ("natural", *TRAINING_CONTROL_NAMES)
AUTHORITY = {
    "audit_opening_authorized": False,
    "gameplay_authorized": False,
    "consumer_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateV2InferenceError(ValueError):
    """A target-free inference identity, tensor, or prediction drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2InferenceError(f"{label} drift")
    return value


def _strict_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2InferenceError(f"{label} drift")
    return value


def _tensor_sha256(value: WorldAfterstateTensorsV0) -> str:
    value.validate()
    return _sha({
        "public": [list(value.public.shape), _sha_bytes(value.public.tobytes())],
        "history": [list(value.history.shape), _sha_bytes(value.history.tobytes())],
        "world": [list(value.world.shape), _sha_bytes(value.world.tobytes())],
        "perspective": [
            list(value.perspective.shape),
            _sha_bytes(value.perspective.tobytes()),
        ],
    })


def _canonical_audit(raw: bytes) -> Mapping[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV2InferenceError("inference audit bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2InferenceError(
            "inference audit JSON drift") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2InferenceError(
            "inference audit canonical bytes drift")
    try:
        reopen_afterstate_audit(value)
    except WorldAfterstateError as exc:
        raise WorldAfterstateV2InferenceError(
            "inference audit reconstruction drift") from exc
    # This is a structural absence check, not a substring check over bytes.
    forbidden = {"outcome", "terminal_outcome", "signed_level_category",
                 "continuation_identity", "continuation_sha256"}
    if forbidden.intersection(value):
        raise WorldAfterstateV2InferenceError(
            "inference audit contains terminal target")
    return value


@dataclass(frozen=True)
class ValueInferenceRootV2:
    """One complete candidate set and its target-free tensor batch."""

    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    split: str
    source: str
    role: str
    phase: str
    position: str
    trump_rank: str
    trump_mode: str
    points_bucket: str
    successor_sha256s: tuple[str, ...]
    tensor_sha256s: tuple[str, ...]
    tensors: WorldAfterstateV2Batch
    schema: str = ROOT_SCHEMA

    def validate(self) -> None:
        if self.schema != ROOT_SCHEMA or self.split not in (
                "fit", "select", "audit") \
                or self.role not in ("attacker", "defender") \
                or self.phase not in ("early", "middle", "late") \
                or self.position not in ("lead", "follow") \
                or self.trump_rank not in tuple("23456789TJQKA") \
                or self.trump_mode not in ("S", "H", "D", "C", "NT") \
                or self.points_bucket not in PRIOR_POINTS_BUCKETS \
                or self.source not in STATE_SOURCES:
            raise WorldAfterstateV2InferenceError(
                "inference root identity drift")
        for label, value in (
                ("deal SHA-256", self.deal_sha256),
                ("slot SHA-256", self.slot_sha256),
                ("state SHA-256", self.state_sha256),
                ("candidate-set SHA-256", self.candidate_set_sha256)):
            _digest(value, label)
        count = len(self.successor_sha256s)
        if type(self.successor_sha256s) is not tuple or count < 2 \
                or type(self.tensor_sha256s) is not tuple \
                or len(self.tensor_sha256s) != count \
                or len(set(self.successor_sha256s)) != count \
                or type(self.tensors) is not WorldAfterstateV2Batch:
            raise WorldAfterstateV2InferenceError(
                "inference root population drift")
        self.tensors.validate()
        if self.tensors.size != count:
            raise WorldAfterstateV2InferenceError(
                "inference root tensor count drift")
        for value in (*self.successor_sha256s, *self.tensor_sha256s):
            _digest(value, "inference root digest")
        expected_set = _sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": self.state_sha256,
            "successor_sha256s": list(self.successor_sha256s),
        })
        if expected_set != self.candidate_set_sha256:
            raise WorldAfterstateV2InferenceError(
                "inference candidate-set reconstruction drift")

    @property
    def candidate_count(self) -> int:
        self.validate()
        return len(self.successor_sha256s)

    def target_free_body(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256,
            "state_sha256": self.state_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
            "split": self.split,
            "source": self.source,
            "role": self.role,
            "phase": self.phase,
            "position": self.position,
            "trump_rank": self.trump_rank,
            "trump_mode": self.trump_mode,
            "points_bucket": self.points_bucket,
            "successor_sha256s": list(self.successor_sha256s),
            "tensor_sha256s": list(self.tensor_sha256s),
        }

    @property
    def root_sha256(self) -> str:
        return _sha(self.target_free_body())


def build_inference_root_v2(material: PopulationMaterialV2) \
        -> ValueInferenceRootV2:
    """Build target-free candidate tensors from a sealed population row."""
    if type(material) is not PopulationMaterialV2:
        raise WorldAfterstateV2InferenceError(
            "inference material type drift")
    try:
        material.validate()
    except Exception as exc:
        raise WorldAfterstateV2InferenceError(
            "inference material validation drift") from exc
    values: list[WorldAfterstateTensorsV0] = []
    for index, candidate in enumerate(material.candidates):
        audit = _canonical_audit(material.private_audit_raws[index])
        if _sha_bytes(material.private_audit_raws[index]) \
                != candidate.audit_sha256 \
                or audit.get("successor_sha256") != candidate.successor_sha256:
            raise WorldAfterstateV2InferenceError(
                "inference candidate audit binding drift")
        try:
            values.append(build_afterstate_tensors(audit))
        except WorldAfterstateError as exc:
            raise WorldAfterstateV2InferenceError(
                "inference tensor construction drift") from exc
    result = ValueInferenceRootV2(
        deal_sha256=material.state.deal_sha256,
        slot_sha256=material.state.slot_sha256,
        state_sha256=material.state.state_sha256,
        candidate_set_sha256=material.candidate_set_sha256,
        split=material.state.split,
        source=material.state.source,
        role=material.state.role,
        phase=material.state.phase,
        position=material.state.position,
        trump_rank=material.state.trump_rank,
        trump_mode=material.state.trump_mode,
        points_bucket=prior_points_bucket(
            material.prestate.get("public", {}).get("attacker_points")),
        successor_sha256s=tuple(
            candidate.successor_sha256 for candidate in material.candidates),
        tensor_sha256s=tuple(_tensor_sha256(value) for value in values),
        tensors=collate_world_afterstate_tensors(values),
    )
    result.validate()
    return result


def _quantize_probability_row(row: torch.Tensor) -> tuple[int, ...]:
    if row.shape != (OUTCOME_CLASSES,) or row.dtype not in (
            torch.float32, torch.float64) \
            or not bool(torch.all(torch.isfinite(row))) \
            or bool(torch.any(row < 0)):
        raise WorldAfterstateV2InferenceError(
            "inference probability row drift")
    values = row.detach().cpu().to(torch.float64).numpy()
    total = float(values.sum())
    if not math.isfinite(total) or total <= 0:
        raise WorldAfterstateV2InferenceError(
            "inference probability total drift")
    values = values / total
    scaled = values * PROBABILITY_SCALE
    floors = np.floor(scaled).astype(np.int64)
    residual = PROBABILITY_SCALE - int(floors.sum())
    if residual < 0 or residual > OUTCOME_CLASSES:
        raise WorldAfterstateV2InferenceError(
            "inference probability residual drift")
    # Largest remainder; category index is the deterministic tie breaker.
    order = sorted(range(OUTCOME_CLASSES),
                   key=lambda index: (-(scaled[index] - floors[index]), index))
    for index in order[:residual]:
        floors[index] += 1
    result = tuple(int(value) for value in floors)
    if sum(result) != PROBABILITY_SCALE or any(value < 0 for value in result):
        raise WorldAfterstateV2InferenceError(
            "inference probability quantization drift")
    return result


def expected_signed_microlevels(probability_ppb: Sequence[int]) -> int:
    if type(probability_ppb) not in (list, tuple) \
            or len(probability_ppb) != OUTCOME_CLASSES \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in probability_ppb) \
            or sum(probability_ppb) != PROBABILITY_SCALE:
        raise WorldAfterstateV2InferenceError(
            "prediction probability simplex drift")
    # Signed levels are half-integral.  Accumulate integer half-level PPB so
    # the sealed expectation is independent of large-float rounding.
    numerator = sum(
        value * int(round(category_signed_level(index) * 2))
        for index, value in enumerate(probability_ppb))
    # half-level PPB * 500,000 microlevels / 1,000,000,000 PPB.
    denominator = 2_000
    return ((numerator + denominator // 2) // denominator
            if numerator >= 0 else
            -((-numerator + denominator // 2) // denominator))


@dataclass(frozen=True)
class CandidatePredictionV2:
    root_sha256: str
    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    candidate_index: int
    successor_sha256: str
    tensor_sha256: str
    seed_block: int
    member_index: int
    control_name: str
    model_state_sha256: str
    probability_ppb: tuple[int, ...]
    expected_signed_microlevels: int
    consumer_eligible: bool
    schema: str = PREDICTION_SCHEMA

    def validate(self) -> None:
        for value in (self.root_sha256, self.deal_sha256, self.slot_sha256,
                      self.state_sha256, self.candidate_set_sha256,
                      self.successor_sha256, self.tensor_sha256,
                      self.model_state_sha256):
            _digest(value, "prediction digest")
        _strict_int(self.candidate_index, "prediction candidate index")
        _strict_int(self.member_index, "prediction member index")
        if self.schema != PREDICTION_SCHEMA \
                or self.seed_block not in SEED_BLOCKS \
                or self.member_index >= MEMBERS_PER_BLOCK \
                or self.control_name not in CONTROL_NAMES \
                or type(self.probability_ppb) is not tuple \
                or self.expected_signed_microlevels != \
                expected_signed_microlevels(self.probability_ppb) \
                or type(self.consumer_eligible) is not bool \
                or self.consumer_eligible != (
                    self.seed_block == 1 and self.control_name == "natural"):
            raise WorldAfterstateV2InferenceError(
                "candidate prediction identity/value drift")

    @property
    def key(self) -> tuple[str, int, str, int, int]:
        self.validate()
        return (self.root_sha256, self.candidate_index, self.control_name,
                self.seed_block, self.member_index)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "root_sha256": self.root_sha256,
            "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256,
            "state_sha256": self.state_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
            "candidate_index": self.candidate_index,
            "successor_sha256": self.successor_sha256,
            "tensor_sha256": self.tensor_sha256,
            "seed_block": self.seed_block,
            "member_index": self.member_index,
            "control_name": self.control_name,
            "model_state_sha256": self.model_state_sha256,
            "probability_ppb": list(self.probability_ppb),
            "expected_signed_microlevels": self.expected_signed_microlevels,
            "consumer_eligible": self.consumer_eligible,
        }


def predict_root_v2(model: WorldAfterstateValueV2,
                    root: ValueInferenceRootV2, *, seed_block: int,
                    member_index: int,
                    control_name: str = "natural") \
        -> tuple[CandidatePredictionV2, ...]:
    if type(model) is not WorldAfterstateValueV2 \
            or type(root) is not ValueInferenceRootV2:
        raise WorldAfterstateV2InferenceError(
            "prediction request type drift")
    root.validate()
    _strict_int(member_index, "prediction member index")
    if seed_block not in SEED_BLOCKS or member_index >= MEMBERS_PER_BLOCK \
            or control_name not in CONTROL_NAMES:
        raise WorldAfterstateV2InferenceError(
            "prediction cohort identity drift")
    before = model_state_sha256(model)
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            logits = model(root.tensors)
            probabilities = torch.softmax(logits, dim=1)
    finally:
        model.train(was_training)
    if probabilities.shape != (root.candidate_count, OUTCOME_CLASSES) \
            or model_state_sha256(model) != before:
        raise WorldAfterstateV2InferenceError(
            "prediction execution drift")
    built = []
    for index in range(root.candidate_count):
        probability_ppb = _quantize_probability_row(probabilities[index])
        built.append(CandidatePredictionV2(
            root_sha256=root.root_sha256,
            deal_sha256=root.deal_sha256,
            slot_sha256=root.slot_sha256,
            state_sha256=root.state_sha256,
            candidate_set_sha256=root.candidate_set_sha256,
            candidate_index=index,
            successor_sha256=root.successor_sha256s[index],
            tensor_sha256=root.tensor_sha256s[index],
            seed_block=seed_block,
            member_index=member_index,
            control_name=control_name,
            model_state_sha256=before,
            probability_ppb=probability_ppb,
            expected_signed_microlevels=expected_signed_microlevels(
                probability_ppb),
            consumer_eligible=(seed_block == 1
                               and control_name == "natural"),
        ))
    rows = tuple(built)
    for row in rows:
        row.validate()
    return rows


def prediction_population_manifest_v2(
        roots: Sequence[ValueInferenceRootV2],
        predictions: Sequence[CandidatePredictionV2], *, split: str,
        control_name: str, seed_block: int) -> dict[str, Any]:
    if type(roots) not in (list, tuple) or not roots \
            or type(predictions) not in (list, tuple) or not predictions \
            or split not in ("fit", "select", "audit") \
            or control_name not in CONTROL_NAMES or seed_block not in SEED_BLOCKS:
        raise WorldAfterstateV2InferenceError(
            "prediction population request drift")
    root_map: dict[str, ValueInferenceRootV2] = {}
    for root in roots:
        if type(root) is not ValueInferenceRootV2:
            raise WorldAfterstateV2InferenceError(
                "prediction root type drift")
        root.validate()
        if root.split != split or root.root_sha256 in root_map:
            raise WorldAfterstateV2InferenceError(
                "prediction root split/duplicate drift")
        root_map[root.root_sha256] = root
    rows: dict[tuple[str, int, int], CandidatePredictionV2] = {}
    for prediction in predictions:
        if type(prediction) is not CandidatePredictionV2:
            raise WorldAfterstateV2InferenceError(
                "prediction row type drift")
        prediction.validate()
        if prediction.control_name != control_name \
                or prediction.seed_block != seed_block:
            raise WorldAfterstateV2InferenceError(
                "prediction cohort mixing drift")
        key = (prediction.root_sha256, prediction.candidate_index,
               prediction.member_index)
        if key in rows:
            raise WorldAfterstateV2InferenceError(
                "duplicate prediction row")
        rows[key] = prediction
    expected = {
        (root.root_sha256, candidate, member)
        for root in roots
        for candidate in range(root.candidate_count)
        for member in range(MEMBERS_PER_BLOCK)
    }
    if set(rows) != expected:
        raise WorldAfterstateV2InferenceError(
            "prediction population drop/member drift")
    model_states: dict[int, set[str]] = {member: set()
                                         for member in range(MEMBERS_PER_BLOCK)}
    for (root_sha, candidate, member), prediction in rows.items():
        root = root_map[root_sha]
        if (prediction.deal_sha256, prediction.slot_sha256,
                prediction.state_sha256, prediction.candidate_set_sha256,
                prediction.successor_sha256, prediction.tensor_sha256) != (
                    root.deal_sha256, root.slot_sha256, root.state_sha256,
                    root.candidate_set_sha256,
                    root.successor_sha256s[candidate],
                    root.tensor_sha256s[candidate]):
            raise WorldAfterstateV2InferenceError(
                "prediction/root binding drift")
        model_states[member].add(prediction.model_state_sha256)
    if any(len(values) != 1 for values in model_states.values()) \
            or len({next(iter(values)) for values in model_states.values()}) \
            != MEMBERS_PER_BLOCK:
        raise WorldAfterstateV2InferenceError(
            "prediction model population drift")
    ordered_roots = sorted(roots, key=lambda item: item.root_sha256)
    root_bindings = [
        {**root.target_free_body(), "root_sha256": root.root_sha256}
        for root in ordered_roots]
    body = {
        "schema": POPULATION_SCHEMA,
        "split": split,
        "control_name": control_name,
        "seed_block": seed_block,
        "root_count": len(root_map),
        "candidate_count": sum(root.candidate_count for root in roots),
        "member_count": MEMBERS_PER_BLOCK,
        "root_bindings": root_bindings,
        "root_population_sha256": _sha([
            {key: item for key, item in binding.items()
             if key != "root_sha256"}
            for binding in root_bindings]),
        "predictions": [rows[key].payload() for key in sorted(rows)],
        "authority": dict(AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def validate_prediction_population_manifest_v2(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or set(value) != {
            "schema", "split", "control_name", "seed_block", "root_count",
            "candidate_count", "member_count", "root_population_sha256",
            "root_bindings", "predictions", "authority", "manifest_sha256"} \
            or value.get("schema") != POPULATION_SCHEMA \
            or value.get("split") not in ("fit", "select", "audit") \
            or value.get("control_name") not in CONTROL_NAMES \
            or value.get("seed_block") not in SEED_BLOCKS \
            or value.get("member_count") != MEMBERS_PER_BLOCK \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV2InferenceError(
            "prediction manifest schema drift")
    _digest(value.get("root_population_sha256"),
            "prediction root population digest")
    _digest(value.get("manifest_sha256"), "prediction manifest digest")
    for name in ("root_count", "candidate_count"):
        _strict_int(value.get(name), f"prediction {name}", minimum=1)
    bindings = value.get("root_bindings")
    if type(bindings) is not list or len(bindings) != value["root_count"]:
        raise WorldAfterstateV2InferenceError(
            "prediction root binding population drift")
    roots: dict[str, dict[str, Any]] = {}
    root_bodies = []
    expected_candidates = 0
    previous_root: str | None = None
    root_keys = {
        "schema", "deal_sha256", "slot_sha256", "state_sha256",
        "candidate_set_sha256", "split", "source", "role", "phase",
        "position", "trump_rank", "trump_mode", "points_bucket",
        "successor_sha256s",
        "tensor_sha256s", "root_sha256",
    }
    for binding in bindings:
        if type(binding) is not dict or set(binding) != root_keys \
                or binding.get("schema") != ROOT_SCHEMA \
                or binding.get("split") != value["split"] \
                or binding.get("role") not in ("attacker", "defender") \
                or binding.get("phase") not in ("early", "middle", "late") \
                or binding.get("position") not in ("lead", "follow") \
                or binding.get("trump_rank") not in tuple("23456789TJQKA") \
                or binding.get("trump_mode") not in ("S", "H", "D", "C", "NT") \
                or binding.get("points_bucket") not in PRIOR_POINTS_BUCKETS:
            raise WorldAfterstateV2InferenceError(
                "prediction root binding drift")
        for name in ("deal_sha256", "slot_sha256", "state_sha256",
                     "candidate_set_sha256", "root_sha256"):
            _digest(binding[name], "prediction root binding digest")
        successors = binding.get("successor_sha256s")
        tensors = binding.get("tensor_sha256s")
        if type(successors) is not list or len(successors) < 2 \
                or type(tensors) is not list or len(tensors) != len(successors) \
                or len(set(successors)) != len(successors):
            raise WorldAfterstateV2InferenceError(
                "prediction root binding candidate drift")
        for digest in (*successors, *tensors):
            _digest(digest, "prediction root candidate digest")
        expected_set = _sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": binding["state_sha256"],
            "successor_sha256s": successors,
        })
        body = {key: item for key, item in binding.items()
                if key != "root_sha256"}
        if binding["candidate_set_sha256"] != expected_set \
                or binding["root_sha256"] != _sha(body) \
                or binding["root_sha256"] in roots \
                or (previous_root is not None
                    and binding["root_sha256"] <= previous_root):
            raise WorldAfterstateV2InferenceError(
                "prediction root binding reconstruction drift")
        roots[binding["root_sha256"]] = binding
        previous_root = binding["root_sha256"]
        root_bodies.append(body)
        expected_candidates += len(successors)
    if expected_candidates != value["candidate_count"] \
            or value["root_population_sha256"] != _sha(root_bodies):
        raise WorldAfterstateV2InferenceError(
            "prediction root population reconstruction drift")
    rows = value.get("predictions")
    if type(rows) is not list or len(rows) != (
            value["candidate_count"] * MEMBERS_PER_BLOCK):
        raise WorldAfterstateV2InferenceError(
            "prediction manifest population drift")
    seen = set()
    previous_prediction: tuple[str, int, str, int, int] | None = None
    models: dict[int, set[str]] = {
        member: set() for member in range(MEMBERS_PER_BLOCK)}
    for payload in rows:
        if type(payload) is not dict:
            raise WorldAfterstateV2InferenceError(
                "prediction manifest row drift")
        try:
            row = CandidatePredictionV2(
                **{key: tuple(item) if key == "probability_ppb" else item
                   for key, item in payload.items()})
            row.validate()
        except (TypeError, ValueError) as exc:
            raise WorldAfterstateV2InferenceError(
                "prediction manifest row drift") from exc
        if row.control_name != value["control_name"] \
                or row.seed_block != value["seed_block"] \
                or row.key in seen \
                or (previous_prediction is not None
                    and row.key <= previous_prediction):
            raise WorldAfterstateV2InferenceError(
                "prediction manifest cohort/duplicate drift")
        seen.add(row.key)
        previous_prediction = row.key
        binding = roots.get(row.root_sha256)
        if binding is None or row.candidate_index >= len(
                binding["successor_sha256s"]) \
                or (row.deal_sha256, row.slot_sha256, row.state_sha256,
                    row.candidate_set_sha256, row.successor_sha256,
                    row.tensor_sha256) != (
                        binding["deal_sha256"], binding["slot_sha256"],
                        binding["state_sha256"],
                        binding["candidate_set_sha256"],
                        binding["successor_sha256s"][row.candidate_index],
                        binding["tensor_sha256s"][row.candidate_index]):
            raise WorldAfterstateV2InferenceError(
                "prediction manifest root binding drift")
        models[row.member_index].add(row.model_state_sha256)
    expected = {
        (root_sha, candidate, value["control_name"], value["seed_block"], member)
        for root_sha, binding in roots.items()
        for candidate in range(len(binding["successor_sha256s"]))
        for member in range(MEMBERS_PER_BLOCK)
    }
    if seen != expected or any(len(items) != 1 for items in models.values()) \
            or len({next(iter(items)) for items in models.values()}) \
            != MEMBERS_PER_BLOCK:
        raise WorldAfterstateV2InferenceError(
            "prediction manifest complete model population drift")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV2InferenceError(
            "prediction manifest reconstruction drift")


def reopen_prediction_population_manifest_v2(
        value: Mapping[str, Any]) -> tuple[CandidatePredictionV2, ...]:
    """Reopen the exact prediction rows after full manifest validation."""
    validate_prediction_population_manifest_v2(value)
    result = tuple(CandidatePredictionV2(
        **{key: tuple(item) if key == "probability_ppb" else item
           for key, item in payload.items()})
        for payload in value["predictions"])
    for row in result:
        row.validate()
    return result


def select_primary_actions_v2(
        predictions: Sequence[CandidatePredictionV2]) -> dict[str, int]:
    """Select from block-1 natural ensemble, breaking every tie to incumbent."""
    if type(predictions) not in (list, tuple) or not predictions:
        raise WorldAfterstateV2InferenceError(
            "primary selection population drift")
    roots: dict[str, dict[int, dict[int, int]]] = {}
    for row in predictions:
        if type(row) is not CandidatePredictionV2:
            raise WorldAfterstateV2InferenceError(
                "primary selection row type drift")
        row.validate()
        if not row.consumer_eligible:
            raise WorldAfterstateV2InferenceError(
                "non-primary prediction cannot select actions")
        member = roots.setdefault(row.root_sha256, {}).setdefault(
            row.candidate_index, {})
        if row.member_index in member:
            raise WorldAfterstateV2InferenceError(
                "primary selection duplicate member")
        member[row.member_index] = row.expected_signed_microlevels
    selected: dict[str, int] = {}
    for root, candidates in roots.items():
        indexes = sorted(candidates)
        if indexes != list(range(len(indexes))) or len(indexes) < 2 \
                or any(set(members) != set(range(MEMBERS_PER_BLOCK))
                       for members in candidates.values()):
            raise WorldAfterstateV2InferenceError(
                "primary selection incomplete root")
        sums = {candidate: sum(candidates[candidate].values())
                for candidate in indexes}
        best = max(sums.values())
        winners = [candidate for candidate in indexes
                   if sums[candidate] == best]
        selected[root] = 0 if 0 in winners else min(winners)
    return selected


__all__ = [
    "AUTHORITY", "CONTROL_NAMES", "MEMBERS_PER_BLOCK", "PROBABILITY_SCALE",
    "CandidatePredictionV2", "ValueInferenceRootV2",
    "WorldAfterstateV2InferenceError", "build_inference_root_v2",
    "expected_signed_microlevels", "predict_root_v2",
    "prediction_population_manifest_v2",
    "reopen_prediction_population_manifest_v2",
    "select_primary_actions_v2", "validate_prediction_population_manifest_v2",
]
