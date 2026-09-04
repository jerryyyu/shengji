"""Feature boundary for a Suphx-style Shengji microbaseline.

This module implements only the first code gate in
``docs_archive/SUPHX_MICRO_SPEC.md``:
the exact split between information a player may legally observe and
simulator-only card ownership used during privileged training.  It contains no
policy, learner, CLI, registry entry, experiment runner, or promotion rule.

Suphx oracle guiding trains one policy on ``[x_normal, delta * x_oracle]`` and
gradually decays the elementwise Bernoulli keep probability to zero.  In
Shengji, the banker's buried cards are *normal private information* because the
banker chose them.  Treating all burial as oracle-only would create a knowingly
incorrect public endpoint, so burial is partitioned by acting seat here.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import numpy as np

from ..engine.round import Round
from .douzero_micro import HISTORY_SCHEMA, encode_public_history
from .encode import (CARD_INDEX, ENCODER_IMPLEMENTATION_SHA256,
                     ENCODER_SOURCE_SHA256S, N_CARDS, OBS_DIM, OBS_SCHEMA,
                     encode_obs)
from .exact_resume import state_digest
from .selfplay_contract import sha256_file


EXPERIMENT = "suphx-micro-ordinary-play-v1"
FEATURE_PARTITION_SCHEMA = "suphx-micro-feature-partition-v1"
LEGAL_PRIVATE_SCHEMA = "banker-known-burial-counts-v1"
PERFECT_FEATURE_SCHEMA = "relative-hidden-hands-and-hidden-burial-v1"
MASK_SCHEMA = "elementwise-bernoulli-named-python-stream-v1"

LEGAL_PRIVATE_DIM = N_CARDS
PERFECT_HAND_BLOCKS = 3
PERFECT_BURIAL_BLOCK = 1
PERFECT_DIM = (PERFECT_HAND_BLOCKS + PERFECT_BURIAL_BLOCK) * N_CARDS

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
FEATURE_SOURCE_SHA256S = {
    "suphx_micro": sha256_file(Path(__file__).resolve()),
    "encode": ENCODER_SOURCE_SHA256S["encode"],
    "memory": ENCODER_SOURCE_SHA256S["memory"],
    "public_history": sha256_file(
        Path(__file__).resolve().with_name("douzero_micro.py")),
    "cards": sha256_file(_SOURCE_ROOT / "engine" / "cards.py"),
    "round": sha256_file(_SOURCE_ROOT / "engine" / "round.py"),
}

FEATURE_SPEC: dict[str, Any] = {
    "schema": FEATURE_PARTITION_SCHEMA,
    "claim": "feature mechanics only; no learning or strength authority",
    "experiment": EXPERIMENT,
    "source_sha256s": FEATURE_SOURCE_SHA256S,
    "normal": {
        "observation_schema": OBS_SCHEMA,
        "observation_dim": OBS_DIM,
        "observation_implementation_sha256": ENCODER_IMPLEMENTATION_SHA256,
        "public_history_schema": HISTORY_SCHEMA,
        "legal_private_schema": LEGAL_PRIVATE_SCHEMA,
        "legal_private_dim": LEGAL_PRIVATE_DIM,
        "legal_private_semantics": (
            "buried-card multiplicities scaled by 0.5 for banker; exact zeros "
            "for every nonbanker"),
    },
    "perfect": {
        "schema": PERFECT_FEATURE_SCHEMA,
        "dimension": PERFECT_DIM,
        "hand_blocks": ["relative_seat_1", "relative_seat_2",
                        "relative_seat_3"],
        "burial_block": (
            "buried-card multiplicities for nonbanker; exact zeros for banker"),
        "card_multiplicity_scale": 0.5,
    },
    "mask": {
        "schema": MASK_SCHEMA,
        "shape": [PERFECT_DIM],
        "draws_per_decision": PERFECT_DIM,
        "endpoint_draws_are_consumed": True,
        "action_rng_is_separate": True,
    },
}
FEATURE_SPEC_SHA256 = state_digest(FEATURE_SPEC)


class SuphxMicroError(RuntimeError):
    """The privileged-information feature contract was violated."""


def _require_play_state(rnd: Round, seat: int) -> None:
    if not isinstance(rnd, Round):
        raise SuphxMicroError("feature encoder requires a Round")
    if isinstance(seat, bool) or not isinstance(seat, int) or seat not in range(4):
        raise SuphxMicroError("acting seat must be an integer in range(4)")
    if rnd.phase != "play" or rnd.ordering is None or rnd.trick is None:
        raise SuphxMicroError("privileged features require an ordinary-play state")
    if rnd.banker not in range(4):
        raise SuphxMicroError("round banker is invalid")
    if not isinstance(rnd.buried, list) or len(rnd.buried) != 8:
        raise SuphxMicroError("ordinary-play state must retain the exact burial")
    if not isinstance(rnd.hands, list) or len(rnd.hands) != 4:
        raise SuphxMicroError("round hand population is malformed")


def _card_counts(cards: list[str], *, label: str) -> np.ndarray:
    counts = np.zeros(N_CARDS, dtype=np.float32)
    physical: dict[str, int] = {}
    for card in cards:
        try:
            index = CARD_INDEX[card]
        except (KeyError, TypeError) as exc:
            raise SuphxMicroError(f"{label} contains unknown card {card!r}") \
                from exc
        physical[card] = physical.get(card, 0) + 1
        if physical[card] > 2:
            raise SuphxMicroError(
                f"{label} contains more than two physical copies of {card}")
        counts[index] += np.float32(0.5)
    return counts


def encode_legal_private(rnd: Round, seat: int) -> np.ndarray:
    """Encode information legal to the actor but absent from encoder v1.

    Encoder v1 intentionally excludes private kitty/burial for historical
    provenance.  A new policy must not perpetuate that omission: the banker
    selected and therefore knows the eight buried cards.
    """
    _require_play_state(rnd, seat)
    if seat != rnd.banker:
        return np.zeros(LEGAL_PRIVATE_DIM, dtype=np.float32)
    return _card_counts(rnd.buried, label="banker-known burial")


def encode_perfect_features(rnd: Round, seat: int) -> np.ndarray:
    """Encode only simulator information unavailable to ``seat``.

    The first three blocks are remaining hands in relative seat order.  The
    last block contains burial only for a nonbanker; for the banker those cards
    belong to :func:`encode_legal_private` and must not disappear at gamma zero.
    """
    _require_play_state(rnd, seat)
    blocks = [
        _card_counts(rnd.hands[(seat + relative) % 4],
                     label=f"relative hidden hand {relative}")
        for relative in range(1, 4)
    ]
    blocks.append(
        _card_counts(rnd.buried, label="hidden burial")
        if seat != rnd.banker
        else np.zeros(N_CARDS, dtype=np.float32)
    )
    result = np.concatenate(blocks).astype(np.float32, copy=False)
    if result.shape != (PERFECT_DIM,):
        raise SuphxMicroError("perfect feature dimension drift")
    return result


def encode_feature_partition(rnd: Round, seat: int) -> dict[str, np.ndarray]:
    """Return the exact normal/perfect tensors before curriculum masking."""
    _require_play_state(rnd, seat)
    obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32)
    history = encode_public_history(rnd, seat)
    legal_private = encode_legal_private(rnd, seat)
    perfect = encode_perfect_features(rnd, seat)
    if obs.shape != (OBS_DIM,) or history.dtype != np.float32:
        raise SuphxMicroError("normal encoder shape or dtype drift")
    return {
        "observation": obs,
        "public_history": history,
        "legal_private": legal_private,
        "perfect": perfect,
    }


def draw_privilege_mask(
        keep_probability: float, rng: random.Random) -> np.ndarray:
    """Draw exactly ``PERFECT_DIM`` Bernoulli values, including endpoints."""
    if isinstance(keep_probability, bool) or not isinstance(
            keep_probability, (int, float)):
        raise SuphxMicroError("keep probability must be a finite number")
    probability = float(keep_probability)
    if not np.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise SuphxMicroError("keep probability must be within [0, 1]")
    if not isinstance(rng, random.Random):
        raise SuphxMicroError("privilege mask requires a local random.Random")
    # Do not special-case 0 or 1.  Equal endpoint work prevents a curriculum
    # arm from shifting subsequent named mask-stream decisions.
    return np.fromiter(
        (1.0 if rng.random() < probability else 0.0
         for _ in range(PERFECT_DIM)),
        dtype=np.float32,
        count=PERFECT_DIM,
    )


def apply_privilege_mask(
        perfect: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if not isinstance(perfect, np.ndarray) or perfect.dtype != np.float32 \
            or perfect.shape != (PERFECT_DIM,):
        raise SuphxMicroError("perfect tensor shape or dtype drift")
    if not isinstance(mask, np.ndarray) or mask.dtype != np.float32 \
            or mask.shape != (PERFECT_DIM,):
        raise SuphxMicroError("privilege mask shape or dtype drift")
    if not np.all((mask == 0.0) | (mask == 1.0)):
        raise SuphxMicroError("privilege mask must be binary")
    if not np.all(np.isfinite(perfect)):
        raise SuphxMicroError("perfect tensor contains non-finite values")
    return np.multiply(perfect, mask, dtype=np.float32)
