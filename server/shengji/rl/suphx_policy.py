"""Four-surface policy/value network for the Suphx-style microbaseline.

This is a structural model gate only.  It consumes the feature partition from
``suphx_micro`` but contains no actor, sampling, learner update, CLI, registry
entry, or run authority.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from ..engine.round import Round
from .douzero_micro import (HISTORY_EVENT_DIM, ROLE_ATTACKER, ROLE_DEFENDER,
                            ROLE_NAMES)
from .encode import ACT_DIM, OBS_DIM
from .exact_resume import state_digest
from .selfplay_contract import sha256_file
from .suphx_micro import (FEATURE_SPEC_SHA256, LEGAL_PRIVATE_DIM, PERFECT_DIM,
                          SuphxMicroError)


POLICY_SCHEMA = "suphx-micro-four-surface-policy-value-v1"
SURFACE_LEAD = 0
SURFACE_FOLLOW = 1
SURFACE_NAMES = {SURFACE_LEAD: "lead", SURFACE_FOLLOW: "follow"}

STATE_HIDDEN = 32
HISTORY_HIDDEN = 24
PERFECT_HIDDEN = 32
ACTION_HIDDEN = 24
HEAD_HIDDEN = 48
INIT_SCALE = 0.05
INITIAL_ENTROPY_ALPHA = 0.01

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
POLICY_SOURCE_SHA256S = {
    "suphx_policy": sha256_file(Path(__file__).resolve()),
    "suphx_features": sha256_file(
        Path(__file__).resolve().with_name("suphx_micro.py")),
    "douzero_history_roles": sha256_file(
        Path(__file__).resolve().with_name("douzero_micro.py")),
    "encode": sha256_file(Path(__file__).resolve().with_name("encode.py")),
    "round": sha256_file(_SOURCE_ROOT / "engine" / "round.py"),
}

POLICY_SPEC: dict[str, Any] = {
    "schema": POLICY_SCHEMA,
    "claim": "network mechanics only; no learning or strength authority",
    "feature_spec_sha256": FEATURE_SPEC_SHA256,
    "source_sha256s": POLICY_SOURCE_SHA256S,
    "surfaces": [
        "attacker_lead", "attacker_follow",
        "defender_lead", "defender_follow",
    ],
    "independent_surface_parameters": True,
    "inputs": {
        "observation_dim": OBS_DIM,
        "legal_private_dim": LEGAL_PRIVATE_DIM,
        "history_event_dim": HISTORY_EVENT_DIM,
        "masked_perfect_dim": PERFECT_DIM,
        "action_dim": ACT_DIM,
        "raw_perfect_input": False,
    },
    "hidden": {
        "state": STATE_HIDDEN,
        "history": HISTORY_HIDDEN,
        "perfect": PERFECT_HIDDEN,
        "action": ACTION_HIDDEN,
        "head": HEAD_HIDDEN,
    },
    "heads": {
        "policy": "action-conditioned scalar logit",
        "value": "state baseline only; cannot select an action or act as MC leaf",
    },
    "entropy_controller": {
        "initial_alpha": INITIAL_ENTROPY_ALPHA,
        "state": "one registered buffer per role/surface",
        "update": "not implemented in this module",
    },
    "initialization": f"named-cpu-uniform[-{INIT_SCALE},{INIT_SCALE}]",
}
POLICY_SPEC_SHA256 = state_digest(POLICY_SPEC)


class SuphxPolicyError(SuphxMicroError):
    """The four-surface model contract was violated."""


def role_for(rnd: Round, seat: int) -> int:
    if not isinstance(rnd, Round) or isinstance(seat, bool) \
            or not isinstance(seat, int) or seat not in range(4):
        raise SuphxPolicyError("role routing requires a Round and valid seat")
    return ROLE_ATTACKER if rnd.is_attacker(seat) else ROLE_DEFENDER


def surface_for(rnd: Round) -> int:
    if not isinstance(rnd, Round) or rnd.phase != "play" or rnd.trick is None:
        raise SuphxPolicyError("surface routing requires an ordinary-play state")
    return SURFACE_LEAD if not rnd.trick.plays else SURFACE_FOLLOW


def surface_key(role: int, surface: int) -> str:
    if role not in ROLE_NAMES:
        raise SuphxPolicyError(f"unsupported role {role!r}")
    if surface not in SURFACE_NAMES:
        raise SuphxPolicyError(f"unsupported surface {surface!r}")
    return f"{ROLE_NAMES[role]}_{SURFACE_NAMES[surface]}"


class _SurfacePolicyValue(nn.Module):
    def __init__(self):
        super().__init__()
        self.normal_encoder = nn.Sequential(
            nn.Linear(OBS_DIM + LEGAL_PRIVATE_DIM, STATE_HIDDEN), nn.ReLU())
        self.history_encoder = nn.GRU(
            HISTORY_EVENT_DIM, HISTORY_HIDDEN, batch_first=True)
        self.perfect_encoder = nn.Sequential(
            nn.Linear(PERFECT_DIM, PERFECT_HIDDEN), nn.ReLU())
        self.action_encoder = nn.Sequential(
            nn.Linear(ACT_DIM, ACTION_HIDDEN), nn.ReLU())
        context_dim = STATE_HIDDEN + HISTORY_HIDDEN + PERFECT_HIDDEN
        self.policy_head = nn.Sequential(
            nn.Linear(context_dim + ACTION_HIDDEN, HEAD_HIDDEN), nn.ReLU(),
            nn.Linear(HEAD_HIDDEN, 1),
        )
        self.value_head = nn.Sequential(
            nn.Linear(context_dim, HEAD_HIDDEN), nn.ReLU(),
            nn.Linear(HEAD_HIDDEN, 1),
        )
        self.register_buffer(
            "entropy_alpha",
            torch.tensor(INITIAL_ENTROPY_ALPHA, dtype=torch.float32),
        )

    def context(
            self, observation: torch.Tensor, legal_private: torch.Tensor,
            history: torch.Tensor, history_lengths: torch.Tensor,
            masked_perfect: torch.Tensor) -> torch.Tensor:
        if observation.ndim != 2 or observation.shape[1] != OBS_DIM:
            raise SuphxPolicyError("observation batch shape drift")
        batch = observation.shape[0]
        if legal_private.shape != (batch, LEGAL_PRIVATE_DIM):
            raise SuphxPolicyError("legal-private batch shape drift")
        if masked_perfect.shape != (batch, PERFECT_DIM):
            raise SuphxPolicyError("masked-perfect batch shape drift")
        if history.ndim != 3 or history.shape[0] != batch \
                or history.shape[2] != HISTORY_EVENT_DIM:
            raise SuphxPolicyError("history batch shape drift")
        if history_lengths.shape != (batch,) \
                or history_lengths.dtype != torch.long:
            raise SuphxPolicyError("history-length batch shape/dtype drift")
        if bool(torch.any(history_lengths < 0)) \
                or bool(torch.any(history_lengths > history.shape[1])):
            raise SuphxPolicyError("history length is outside padded sequence")

        normal = self.normal_encoder(torch.cat(
            [observation, legal_private], dim=1))
        if history.shape[1] == 0:
            history_features = torch.zeros(
                (batch, HISTORY_HIDDEN), dtype=observation.dtype,
                device=observation.device)
        else:
            sequence, _ = self.history_encoder(history)
            indices = (history_lengths - 1).clamp(min=0)
            history_features = sequence[
                torch.arange(batch, device=observation.device), indices]
            history_features = torch.where(
                (history_lengths > 0).unsqueeze(1),
                history_features,
                torch.zeros_like(history_features),
            )
        perfect = self.perfect_encoder(masked_perfect)
        return torch.cat([normal, history_features, perfect], dim=1)

    def score(
            self, context: torch.Tensor,
            actions: torch.Tensor) -> torch.Tensor:
        if actions.ndim != 2 or actions.shape[1] != ACT_DIM \
                or actions.shape[0] != context.shape[0]:
            raise SuphxPolicyError("action/context batch shape drift")
        action_features = self.action_encoder(actions)
        return self.policy_head(torch.cat(
            [context, action_features], dim=1)).squeeze(1)

    def value(self, context: torch.Tensor) -> torch.Tensor:
        return self.value_head(context).squeeze(1)


class SuphxPolicyValue(nn.Module):
    """Independent attacker/defender × lead/follow policy/value heads."""

    def __init__(self):
        super().__init__()
        self.surfaces = nn.ModuleDict({
            key: _SurfacePolicyValue() for key in POLICY_SPEC["surfaces"]})

    def head(self, role: int, surface: int) -> _SurfacePolicyValue:
        return self.surfaces[surface_key(role, surface)]

    def score_candidates(
            self, *, role: int, surface: int, observation: np.ndarray,
            legal_private: np.ndarray, history: np.ndarray,
            masked_perfect: np.ndarray, actions: np.ndarray,
            grad: bool = False) -> tuple[torch.Tensor, torch.Tensor]:
        """Score one ordered ballot and return logits plus state baseline."""
        if not isinstance(observation, np.ndarray) \
                or observation.dtype != np.float32 \
                or observation.shape != (OBS_DIM,):
            raise SuphxPolicyError("observation tensor shape/dtype drift")
        if not isinstance(legal_private, np.ndarray) \
                or legal_private.dtype != np.float32 \
                or legal_private.shape != (LEGAL_PRIVATE_DIM,):
            raise SuphxPolicyError("legal-private tensor shape/dtype drift")
        if not isinstance(history, np.ndarray) or history.dtype != np.float32 \
                or history.ndim != 2 \
                or history.shape[1] != HISTORY_EVENT_DIM:
            raise SuphxPolicyError("history tensor shape/dtype drift")
        if not isinstance(masked_perfect, np.ndarray) \
                or masked_perfect.dtype != np.float32 \
                or masked_perfect.shape != (PERFECT_DIM,):
            raise SuphxPolicyError("masked-perfect tensor shape/dtype drift")
        if not isinstance(actions, np.ndarray) or actions.dtype != np.float32 \
                or actions.ndim != 2 or actions.shape[1] != ACT_DIM \
                or not len(actions):
            raise SuphxPolicyError("candidate action matrix is empty or malformed")
        if any(not np.all(np.isfinite(value)) for value in (
                observation, legal_private, history, masked_perfect, actions)):
            raise SuphxPolicyError("policy input contains non-finite values")

        head = self.head(role, surface)
        context_manager = torch.enable_grad() if grad else torch.no_grad()
        with context_manager:
            observation_t = torch.from_numpy(observation).reshape(1, OBS_DIM)
            legal_t = torch.from_numpy(legal_private).reshape(
                1, LEGAL_PRIVATE_DIM)
            history_t = torch.from_numpy(history).reshape(
                1, len(history), HISTORY_EVENT_DIM)
            lengths_t = torch.tensor([len(history)], dtype=torch.long)
            perfect_t = torch.from_numpy(masked_perfect).reshape(1, PERFECT_DIM)
            context = head.context(
                observation_t, legal_t, history_t, lengths_t, perfect_t)
            value = head.value(context).squeeze(0)
            repeated = context.expand(len(actions), -1)
            logits = head.score(repeated, torch.from_numpy(actions))
        return logits, value


def new_from_scratch_model(seed: int) -> SuphxPolicyValue:
    """Create deterministic parameters without consuming global torch RNG."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise SuphxPolicyError("model seed must be an integer")
    cpu_state = torch.get_rng_state().clone()
    try:
        model = SuphxPolicyValue()
    finally:
        torch.set_rng_state(cpu_state)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    with torch.no_grad():
        for name, parameter in sorted(model.named_parameters()):
            if "entropy_alpha" in name:
                raise SuphxPolicyError("entropy controller became a parameter")
            parameter.uniform_(-INIT_SCALE, INIT_SCALE, generator=generator)
    return model
