"""Outcome-free mechanics for a fresh Suphx O0-v2 mechanism battery.

The terminal O0 recipe used arm-separated action RNG streams and a one-sided
entropy coefficient.  This module supplies the two common pieces required by a
fresh experiment without altering or extending those frozen artifacts:

* keyed common-random-number (CRN) draws shared by oracle/public arms whenever
  they reach the same legal public decision context; and
* an optional two-sided top-two logit-margin loss that can sharpen a nearly
  tied policy or relax an over-large margin.

There is deliberately no collector, learner runner, evidence population, CLI,
gate, or launch authority here.  CRN is common infrastructure.  Margin control
is a separate factorial mechanism cell, not silently bundled into CRN.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from .exact_resume import state_digest


SCHEMA = "suphx-o0-v2-mechanics-v1"
CRN_SCHEMA = "suphx-o0-v2-keyed-crn-v1"
MARGIN_SCHEMA = "suphx-o0-v2-two-sided-logit-margin-v1"
ARMS = ("oracle", "public")
MIN_INFERENCE_SEEDS = 8
UNCHANGED_ITERATIONS_PER_ARM = 64
UNCHANGED_REWARD_TARGET = "clipped-acting-team-attacker-point-bracket-v2"


class SuphxO0V2MechanicsError(RuntimeError):
    """A CRN or margin-controller mechanics contract was violated."""


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SuphxO0V2MechanicsError(
            f"{label} must be a nonnegative integer")
    return value


def _finite(value: object, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise SuphxO0V2MechanicsError(f"{label} must be finite")
    result = float(value)
    if minimum is not None and result < minimum:
        raise SuphxO0V2MechanicsError(
            f"{label} must be at least {minimum}")
    return result


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("ascii")


def _is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def _uniform(*, root_seed: int, domain: str,
             material: Mapping[str, object]) -> float:
    _nonnegative_int(root_seed, "CRN root seed")
    if not isinstance(domain, str) or not domain:
        raise SuphxO0V2MechanicsError("CRN domain must be nonempty")
    digest = hashlib.sha256(_canonical({
        "schema": CRN_SCHEMA,
        "root_seed": root_seed,
        "domain": domain,
        "material": dict(material),
    })).digest()
    # The top 53 bits map exactly onto the mantissa grid in [0, 1).
    return (int.from_bytes(digest[:8], "big") >> 11) / float(1 << 53)


@dataclass(frozen=True)
class CrossedCRNSpec:
    """Arm-independent streams with training seed as an inference unit."""

    root_seed: int
    training_seed_indices: tuple[int, ...]
    iterations_per_arm: int = UNCHANGED_ITERATIONS_PER_ARM

    def __post_init__(self) -> None:
        _nonnegative_int(self.root_seed, "CRN root seed")
        if not isinstance(self.training_seed_indices, tuple) \
                or len(self.training_seed_indices) < MIN_INFERENCE_SEEDS \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value < 0 for value in self.training_seed_indices) \
                or len(set(self.training_seed_indices)) \
                != len(self.training_seed_indices):
            raise SuphxO0V2MechanicsError(
                "CRN design requires at least eight unique seed indices")
        if isinstance(self.iterations_per_arm, bool) \
                or self.iterations_per_arm != UNCHANGED_ITERATIONS_PER_ARM:
            raise SuphxO0V2MechanicsError(
                "CRN infrastructure cannot change the frozen O0 dose")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": CRN_SCHEMA,
            "root_seed": self.root_seed,
            "training_seed_indices": list(self.training_seed_indices),
            "training_seeds_are_inference_units": True,
            "minimum_training_seeds": MIN_INFERENCE_SEEDS,
            "arms": list(ARMS),
            "arm_identity_in_draw_key": False,
            "iterations_per_arm": self.iterations_per_arm,
            "reward_target": UNCHANGED_REWARD_TARGET,
            "same_public_context_same_draw": True,
            "diverged_public_context_independent_key": True,
        }


def public_decision_key(
        *, deal_seed: int, seat: int, role: int, surface: int,
        observation: np.ndarray, legal_private: np.ndarray,
        history: np.ndarray,
        candidate_cards: Sequence[Sequence[str]]) -> str:
    """Hash exactly the legal context allowed to couple action draws.

    Perfect/hidden features, model/checkpoint identity, privilege arm and logits
    are intentionally absent.  Thus two arms share a draw only when they reach
    the same deal, public history, acting seat, own legal information and exact
    ordered ballot.
    """
    _nonnegative_int(deal_seed, "decision deal seed")
    if seat not in range(4) or role not in (0, 1) or surface not in (0, 1):
        raise SuphxO0V2MechanicsError(
            "decision seat/role/surface is outside the ordinary-play contract")
    arrays = {
        "observation": observation,
        "legal_private": legal_private,
        "history": history,
    }
    if any(not isinstance(value, np.ndarray)
           or value.dtype != np.float32
           or not np.all(np.isfinite(value)) for value in arrays.values()) \
            or observation.ndim != 1 or legal_private.ndim != 1 \
            or history.ndim != 2:
        raise SuphxO0V2MechanicsError(
            "decision arrays must have finite float32 ordinary-play shapes")
    if not isinstance(candidate_cards, Sequence) or not candidate_cards:
        raise SuphxO0V2MechanicsError("decision ballot must be nonempty")
    ballot: list[list[str]] = []
    for action in candidate_cards:
        if not isinstance(action, Sequence) or isinstance(action, (str, bytes)) \
                or not action or any(not isinstance(card, str) or not card
                                     for card in action):
            raise SuphxO0V2MechanicsError("decision ballot action is malformed")
        ballot.append(list(action))
    return state_digest({
        "schema": "suphx-o0-v2-public-decision-key-v1",
        "deal_seed": deal_seed,
        "seat": seat,
        "role": role,
        "surface": surface,
        "observation": observation,
        "legal_private": legal_private,
        "history": history,
        "candidate_cards": ballot,
    })


@dataclass(frozen=True)
class CrossedCRNStreams:
    """Stateless, order-independent draws for one seed/iteration pair."""

    spec: CrossedCRNSpec
    training_seed_index: int
    iteration: int

    def __post_init__(self) -> None:
        if not isinstance(self.spec, CrossedCRNSpec):
            raise SuphxO0V2MechanicsError("CRN streams require an exact spec")
        if self.training_seed_index not in self.spec.training_seed_indices:
            raise SuphxO0V2MechanicsError(
                "training seed is outside the crossed CRN spec")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) \
                or not 0 <= self.iteration < self.spec.iterations_per_arm:
            raise SuphxO0V2MechanicsError(
                "CRN iteration is outside the unchanged O0 dose")

    def _base(self) -> dict[str, int]:
        return {
            "training_seed_index": self.training_seed_index,
            "iteration": self.iteration,
        }

    def deal_seed(self) -> int:
        draw = _uniform(
            root_seed=self.spec.root_seed, domain="shared-deal",
            material=self._base())
        return int(draw * (1 << 63))

    def mask_uniforms(self, public_key: str, count: int) -> tuple[float, ...]:
        if not _is_sha256(public_key):
            raise SuphxO0V2MechanicsError("mask public key must be SHA-256")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise SuphxO0V2MechanicsError("mask draw count must be positive")
        return tuple(_uniform(
            root_seed=self.spec.root_seed,
            domain="shared-privilege-mask",
            material={**self._base(), "public_key": public_key, "offset": i},
        ) for i in range(count))

    def action_uniform(self, public_key: str, occurrence: int = 0) -> float:
        if not _is_sha256(public_key):
            raise SuphxO0V2MechanicsError("action public key must be SHA-256")
        _nonnegative_int(occurrence, "decision-key occurrence")
        return _uniform(
            root_seed=self.spec.root_seed,
            domain="shared-policy-action",
            material={
                **self._base(),
                "public_key": public_key,
                "occurrence": occurrence,
            },
        )

    def receipt(self, public_keys: Sequence[str]) -> dict[str, Any]:
        if any(not _is_sha256(value) for value in public_keys):
            raise SuphxO0V2MechanicsError(
                "CRN receipt public-key population is malformed")
        return {
            "schema": "suphx-o0-v2-crn-iteration-receipt-v1",
            "spec_sha256": state_digest(self.spec.as_dict()),
            "training_seed_index": self.training_seed_index,
            "iteration": self.iteration,
            "deal_seed": self.deal_seed(),
            "public_decision_keys": list(public_keys),
            "public_decision_keys_sha256": state_digest(list(public_keys)),
            "arm_identity_in_draw_key": False,
            "outcomes": None,
        }


@dataclass(frozen=True)
class LogitMarginSpec:
    target_margin: float
    coefficient: float

    def __post_init__(self) -> None:
        target = _finite(
            self.target_margin, "target logit margin", minimum=0.0)
        coefficient = _finite(
            self.coefficient, "margin coefficient", minimum=0.0)
        if target <= 0.0 or coefficient <= 0.0:
            raise SuphxO0V2MechanicsError(
                "margin target and coefficient must be strictly positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": MARGIN_SCHEMA,
            "target_margin": float(self.target_margin),
            "coefficient": float(self.coefficient),
            "loss": "0.5 * coefficient * (top1_minus_top2-target)^2",
            "below_target": "increase_margin",
            "above_target": "decrease_margin",
            "forced_action": "zero_loss",
        }


def two_sided_margin_loss(
        logits: torch.Tensor, spec: LogitMarginSpec) \
        -> tuple[torch.Tensor, torch.Tensor]:
    """Return differentiable loss and detached top-two margin.

    The squared target is explicitly two-sided.  This primitive does not decide
    whether margin control is beneficial; that is a separate factorial arm.
    """
    if not isinstance(spec, LogitMarginSpec):
        raise SuphxO0V2MechanicsError("margin loss requires an exact spec")
    if not isinstance(logits, torch.Tensor) or logits.ndim != 1 \
            or not logits.is_floating_point() or not len(logits) \
            or not bool(torch.all(torch.isfinite(logits))):
        raise SuphxO0V2MechanicsError(
            "margin logits must be a finite nonempty vector")
    if len(logits) == 1:
        zero = logits.sum() * 0.0
        return zero, zero.detach()
    top_two = torch.topk(logits, k=2).values
    margin = top_two[0] - top_two[1]
    error = margin - float(spec.target_margin)
    loss = 0.5 * float(spec.coefficient) * error.square()
    if not bool(torch.isfinite(loss)):
        raise SuphxO0V2MechanicsError("margin loss is non-finite")
    return loss, margin.detach()


def mechanics_spec() -> dict[str, Any]:
    """Return the bounded infrastructure claim, with zero launch authority."""
    return {
        "schema": SCHEMA,
        "claim": "mechanics only; no recipe-level or strength conclusion",
        "common_infrastructure": {
            "crossed_crn": True,
            "minimum_training_seeds": MIN_INFERENCE_SEEDS,
            "iterations_per_arm": UNCHANGED_ITERATIONS_PER_ARM,
            "reward_target": UNCHANGED_REWARD_TARGET,
            "training_seed_clustered_inference_required": True,
        },
        "factorial_cells": [
            {"name": "crn_control", "crossed_crn": True,
             "margin_controller": False},
            {"name": "crn_plus_margin", "crossed_crn": True,
             "margin_controller": True},
        ],
        "forbidden_bundle": [
            "dose_change",
            "reward_target_change",
            "privilege_feature_change",
            "optimizer_change",
        ],
        "api_excludes_arm_from_draws": all(
            "arm" not in inspect.signature(method).parameters
            for method in (
                CrossedCRNStreams.deal_seed,
                CrossedCRNStreams.mask_uniforms,
                CrossedCRNStreams.action_uniform,
            )
        ),
        "experiment_launch_authorized": False,
        "o1_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }


MECHANICS_SPEC = mechanics_spec()
MECHANICS_SPEC_SHA256 = state_digest(MECHANICS_SPEC)
