"""Canonical score-free BELIEF-V1 B2 population and experiment constants.

This module freezes the choices that a later reviewed controller must consume:
the opened-development round population, 16 capture lanes, per-seat champion
policy RNG seeds, REF-C replicate RNG seeds, cohort seeds, resource caps, and
the primary offline retain rule.  It has no engine, model, corpus, filesystem,
subprocess, network, CLI, or execution surface.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .belief_capture import CHAMPION_POLICY
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_corpus import SPLIT_SCHEMA, split_for_round_seed
from .belief_reference import REF_C_WORLD_COUNT


B2_PROTOCOL_SCHEMA = "belief-v1-b2-open-dev-offline-protocol-v1"
B2_SEED_MATERIAL_SHA256 = (
    "d4b635bd6bc44b5e25b23881944fba68caef04c0c74b4cbae076ded191932ac6")
B2_SEED_START = 6104125432620400640
B2_ROUND_COUNT = 4096
B2_CAPTURE_LANES = 16
B2_ROUNDS_PER_LANE = 256
B2_SPLIT_COUNTS = (("train", 3279), ("calibration", 407), ("test", 410))
B2_REFERENCE_REPLICATES = (
    "calibration-replicate-0", "calibration-replicate-1", "test-primary")
MAX_SEED = 2**63 - 1

CAPTURE_CORE_HOUR_CAP = 16
CAPTURE_WALL_SECOND_CAP = 2 * 60 * 60
CAPTURE_BYTE_CAP = 4 * 1024**3
REFERENCE_CORE_HOUR_CAP = 64
REFERENCE_WALL_SECOND_CAP = 8 * 60 * 60
REFERENCE_BYTE_CAP = 4 * 1024**3
TRAIN_DEVICE_HOUR_CAP = 32
TRAIN_WALL_SECOND_CAP = 8 * 60 * 60
TRAIN_BYTE_CAP = 16 * 1024**3
TRAIN_LEARNING_RATE = "0.0003"
TRAIN_WEIGHT_DECAY = "0.01"
TRAIN_BATCH_DECISION_CAP = 256
TRAIN_GRADIENT_NORM_CAP = "1.0"
TRAIN_MAX_EPOCHS = 30
TRAIN_EARLY_STOP_PATIENCE = 3
TRAIN_MIN_IMPROVEMENT_NANONATS = 100_000
PRIMARY_RELATIVE_BRIER_FLOOR_PPB = 5_000_000  # 0.5%
PRIMARY_MEMBER_POSITIVE_MINIMUM = 6
REFERENCE_REPLICATE_DISAGREEMENT_FRACTION_PPB = 250_000_000  # 1/4
REFERENCE_RELATIVE_DISAGREEMENT_CAP_PPB = (
    PRIMARY_RELATIVE_BRIER_FLOOR_PPB
    * REFERENCE_REPLICATE_DISAGREEMENT_FRACTION_PPB // 1_000_000_000)
PRIMARY_BOOTSTRAP_REPLICATES = 20_000
REFERENCE_BRIER_CORRECTION = (
    "unbiased-multinomial-empirical-brier-v1")


class BeliefB2ProtocolError(ValueError):
    """A canonical B2 protocol input or derived field drifted."""


def _derive_seed(label: str) -> int:
    if type(label) is not str or not label:
        raise BeliefB2ProtocolError("B2 seed label is invalid")
    return int.from_bytes(hashlib.sha256(
        f"{B2_PROTOCOL_SCHEMA}|{label}".encode("ascii")).digest()[:8],
        "big") & MAX_SEED


def b2_round_seeds() -> tuple[int, ...]:
    return tuple(range(B2_SEED_START, B2_SEED_START + B2_ROUND_COUNT))


def b2_split_round_seeds(split: str) -> tuple[int, ...]:
    if split not in dict(B2_SPLIT_COUNTS):
        raise BeliefB2ProtocolError("B2 split is invalid")
    return tuple(seed for seed in b2_round_seeds()
                 if split_for_round_seed(seed) == split)


def capture_lane(round_seed: int) -> int:
    if type(round_seed) is not int \
            or not B2_SEED_START <= round_seed < B2_SEED_START + B2_ROUND_COUNT:
        raise BeliefB2ProtocolError("round seed is outside B2 population")
    return (round_seed - B2_SEED_START) % B2_CAPTURE_LANES


def champion_policy_seeds(round_seed: int) -> tuple[int, int, int, int]:
    """Return four deterministic, distinct seat-policy seeds for one round."""
    capture_lane(round_seed)
    seeds = tuple(_derive_seed(f"champion-policy|{round_seed}|seat-{seat}")
                  for seat in range(4))
    if len(set(seeds)) != 4:
        raise BeliefB2ProtocolError("champion policy seed collision")
    return seeds  # type: ignore[return-value]


def reference_sampler_seed(decision_key: str, replicate: str) -> int:
    if type(decision_key) is not str or len(decision_key) != 64 \
            or any(char not in "0123456789abcdef" for char in decision_key) \
            or replicate not in B2_REFERENCE_REPLICATES:
        raise BeliefB2ProtocolError("REF-C seed input is invalid")
    return _derive_seed(f"ref-c|{replicate}|{decision_key}")


def primary_bootstrap_seed() -> int:
    return _derive_seed("primary-paired-round-bootstrap")


def protocol_dict() -> dict[str, Any]:
    seeds = b2_round_seeds()
    split_counts = tuple((split, sum(
        split_for_round_seed(seed) == split for seed in seeds))
                         for split, _ in B2_SPLIT_COUNTS)
    lane_counts = tuple(sum(capture_lane(seed) == lane for seed in seeds)
                        for lane in range(B2_CAPTURE_LANES))
    if split_counts != B2_SPLIT_COUNTS \
            or lane_counts != (B2_ROUNDS_PER_LANE,) * B2_CAPTURE_LANES:
        raise BeliefB2ProtocolError("B2 population derivation drift")
    return {
        "schema": B2_PROTOCOL_SCHEMA,
        "seed_material_sha256": B2_SEED_MATERIAL_SHA256,
        "round_seed_start": B2_SEED_START,
        "round_seed_end": B2_SEED_START + B2_ROUND_COUNT - 1,
        "round_count": B2_ROUND_COUNT,
        "split_schema": SPLIT_SCHEMA,
        "split_counts": dict(B2_SPLIT_COUNTS),
        "capture": {
            "lane_count": B2_CAPTURE_LANES,
            "rounds_per_lane": B2_ROUNDS_PER_LANE,
            "lane_rule": "(round_seed-round_seed_start)%lane_count",
            "policy": CHAMPION_POLICY,
            "policy_seed_rule": "sha256(protocol|champion-policy|seed|seat)",
            "core_hour_cap": CAPTURE_CORE_HOUR_CAP,
            "wall_second_cap": CAPTURE_WALL_SECOND_CAP,
            "byte_cap": CAPTURE_BYTE_CAP,
            "retry_count": 0,
            "drop_count": 0,
        },
        "reference": {
            "accepted_worlds_per_decision": REF_C_WORLD_COUNT,
            "replicates": list(B2_REFERENCE_REPLICATES),
            "sampler_seed_rule": "sha256(protocol|ref-c|replicate|decision_key)",
            "calibration_replicate_disagreement_fraction_ppb": (
                REFERENCE_REPLICATE_DISAGREEMENT_FRACTION_PPB),
            "calibration_relative_disagreement_cap_ppb": (
                REFERENCE_RELATIVE_DISAGREEMENT_CAP_PPB),
            "core_hour_cap": REFERENCE_CORE_HOUR_CAP,
            "wall_second_cap": REFERENCE_WALL_SECOND_CAP,
            "byte_cap": REFERENCE_BYTE_CAP,
            "retry_count": 0,
        },
        "training": {
            "ordered_initialization_seeds": list(COHORT_SEEDS),
            "candidate_member_count": len(COHORT_SEEDS),
            "hard_geometry_permuted_label_member_count": len(COHORT_SEEDS),
            "history_chronology_ablation_is_inference_only": True,
            "history_chronology_ablation": (
                "deterministic-within-decision-event-permutation-v1"),
            "label_permutation": (
                "hard-geometry-compatible-card-label-permutation-v1"),
            "device_hour_cap": TRAIN_DEVICE_HOUR_CAP,
            "wall_second_cap": TRAIN_WALL_SECOND_CAP,
            "byte_cap": TRAIN_BYTE_CAP,
            "optimizer": "AdamW",
            "learning_rate": TRAIN_LEARNING_RATE,
            "weight_decay": TRAIN_WEIGHT_DECAY,
            "round_grouped_batch_decision_cap": TRAIN_BATCH_DECISION_CAP,
            "gradient_norm_cap": TRAIN_GRADIENT_NORM_CAP,
            "maximum_epochs": TRAIN_MAX_EPOCHS,
            "common_epoch_early_stop_patience": TRAIN_EARLY_STOP_PATIENCE,
            "cohort_mean_minimum_improvement_nanonats": (
                TRAIN_MIN_IMPROVEMENT_NANONATS),
            "epoch_round_order": "sha256(protocol|epoch|round_seed)",
            "retry_count": 0,
        },
        "primary_gate": {
            "metric": "paired-per-round-hidden-ownership-count-brier",
            "reference_finite_sample_bias_correction": (
                REFERENCE_BRIER_CORRECTION),
            "reference_world_count": REF_C_WORLD_COUNT,
            "bias_estimator": (
                "sum(p_hat*(1-p_hat))/(reference_world_count-1)"),
            "reference_minus_candidate_mean_relative_floor_ppb": (
                PRIMARY_RELATIVE_BRIER_FLOOR_PPB),
            "one_sided_95_percent_lower_bound_strictly_positive": True,
            "round_bootstrap_replicates": PRIMARY_BOOTSTRAP_REPLICATES,
            "round_bootstrap_seed": primary_bootstrap_seed(),
            "positive_member_mean_minimum": PRIMARY_MEMBER_POSITIVE_MINIMUM,
            "member_count": len(COHORT_SEEDS),
            "mean_smoothed_log_loss_improvement_nonnegative": True,
        },
        "authority": {
            "capture_execution_authorized": False,
            "reference_generation_authorized": False,
            "training_authorized": False,
            "test_split_open_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
        },
    }


def protocol_bytes() -> bytes:
    return canonical_json_bytes(protocol_dict())


def protocol_sha256() -> str:
    return hashlib.sha256(protocol_bytes()).hexdigest()
