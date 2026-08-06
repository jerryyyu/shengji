"""Bounded DouZero-style structural ordinary-play microbaseline.

This is a Shengji-specific structural adaptation and code gate, not a faithful
reproduction of DouZero's three-role topology or a strength claim.  It
deliberately implements only the smallest coherent experiment:

* a from-scratch action-conditioned Q learner;
* separate attacker and defender networks (Shengji's seat-relative encoding
  makes partners within each team symmetric, while banker-team and attacking-
  team objectives are not symmetric);
* direct acting-team terminal level returns, with no oracle residual or BC
  warm start;
* an explicit chronological public-play encoder in addition to the existing
  observation planes; and
* one immutable frozen-actor round, replay insertion, and learner update per
  :class:`SynchronousSelfPlayRunner` iteration.

Declaration and burial are named fixed SmartBot controls used only to create a
complete round.  The Q actor itself refuses those unsupported surfaces, and no
ordinary-play fallback is permitted.  There is intentionally no CLI, evidence
runner, promotion rule, or production registration in this module.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from torch import nn

from ..ai.env import play_round
from ..ai.smart import SmartBot
from ..engine.cards import points
from ..engine.game import Game
from ..engine.round import Round
from .actions import enumerate_actions
from .encode import (ACT_DIM, CARD_INDEX, ENCODER_IMPLEMENTATION_SHA256,
                     ENCODER_SOURCE_SHA256S, ENC_VERSION, N_CARDS, OBS_DIM,
                     OBS_SCHEMA, encode_action, encode_obs)
from .exact_resume import (ReplayRing, ResumeRNGStreams, state_digest)
from .selfplay_contract import (CheckpointRef, load_verified,
                                save_immutable_snapshot, sha256_file,
                                signed_return)
from .synchronous_selfplay import (ActorBatchIdentity, LearnerUpdateContext,
                                   SynchronousActorBatch,
                                   SynchronousSelfPlayRunner)


EXPERIMENT = "douzero-micro-ordinary-play-v1"
SAMPLE_SCHEMA = "douzero-micro-sample-v1"
HISTORY_SCHEMA = "public-play-sequence-v1"
BALLOT_SCHEMA = "rl-actions-v1-narrow-no-extra-throws"
REWARD_SCHEMA = "direct-acting-team-level-bracket-v1"
NETWORK_SCHEMA = "separate-attacker-defender-gru-action-q-v1"
UPDATE_SCHEMA = "chosen-action-terminal-mse-one-step-v1"
EXPLORATION_SCHEMA = "epsilon-greedy-named-python-stream-v1"
OPPONENT_SCHEMA = "frozen-actor-all-ordinary-seats-smart-controls-v1"

ROLE_ATTACKER = 0
ROLE_DEFENDER = 1
ROLE_NAMES = {ROLE_ATTACKER: "attacker", ROLE_DEFENDER: "defender"}

HISTORY_MAX_EVENTS = 100
HISTORY_EVENT_DIM = N_CARDS + 4 + 4 + 2
STATE_HIDDEN = 32
HISTORY_HIDDEN = 24
ACTION_HIDDEN = 24
HEAD_HIDDEN = 48
INIT_SCALE = 0.05
EPSILON = 0.10
ROUNDS_PER_BATCH = 1
UPDATE_BATCH_SIZE = 16
LEARNING_RATE = 1e-3
REPLAY_CAPACITY = 256


_SOURCE_ROOT = Path(__file__).resolve().parents[1]
ALGORITHM_SOURCE_SHA256S = {
    "douzero_micro": sha256_file(Path(__file__).resolve()),
    "actions": sha256_file(Path(__file__).resolve().with_name("actions.py")),
    "encode": ENCODER_SOURCE_SHA256S["encode"],
    "memory": ENCODER_SOURCE_SHA256S["memory"],
    "exact_resume": sha256_file(
        Path(__file__).resolve().with_name("exact_resume.py")),
    "selfplay_contract": sha256_file(
        Path(__file__).resolve().with_name("selfplay_contract.py")),
    "synchronous_selfplay": sha256_file(
        Path(__file__).resolve().with_name("synchronous_selfplay.py")),
    "smart_controls": sha256_file(_SOURCE_ROOT / "ai" / "smart.py"),
    "heuristic": sha256_file(_SOURCE_ROOT / "ai" / "heuristic.py"),
    "mcbot": sha256_file(_SOURCE_ROOT / "ai" / "mcbot.py"),
    "round_driver": sha256_file(_SOURCE_ROOT / "ai" / "env.py"),
    "cards": sha256_file(_SOURCE_ROOT / "engine" / "cards.py"),
    "combos": sha256_file(_SOURCE_ROOT / "engine" / "combos.py"),
    "legal": sha256_file(_SOURCE_ROOT / "engine" / "legal.py"),
    "game": sha256_file(_SOURCE_ROOT / "engine" / "game.py"),
    "round": sha256_file(_SOURCE_ROOT / "engine" / "round.py"),
}


ALGORITHM_SPEC: dict[str, Any] = {
    "schema": "douzero-micro-algorithm-contract-v1",
    "claim": (
        "bounded Shengji structural adaptation/code gate; not a faithful "
        "DouZero role topology, paper reproduction, or strength result"),
    "decision_surface": "ordinary_play_only",
    "implementation_source_sha256s": ALGORITHM_SOURCE_SHA256S,
    "encoder": {
        "observation": {
            "schema": OBS_SCHEMA,
            "layout_version": ENC_VERSION,
            "dimension": OBS_DIM,
            "implementation_sha256": ENCODER_IMPLEMENTATION_SHA256,
            "source_sha256s": dict(ENCODER_SOURCE_SHA256S),
        },
        "history": HISTORY_SCHEMA,
        "history_max_events": HISTORY_MAX_EVENTS,
        "history_event_dim": HISTORY_EVENT_DIM,
        "history_semantics": (
            "chronological completed tricks then current trick; only "
            "engine-recorded public cards; 0.5 per physical copy; acting seat "
            "relative modulo four; zero-based position within trick; play "
            "size divided by 25; card points divided by 40"),
    },
    "action_ballot": {
        "schema": BALLOT_SCHEMA,
        "enumerator": "enumerate_actions",
        "exhaustive_follows": False,
        "include_throws": False,
        "target": "chosen attempted action",
    },
    "reward": {
        "schema": REWARD_SCHEMA,
        "target": "role_sign * attacker terminal bracket/possession return",
        "attacker_return_support": [-3.5, -2.5, -1.5,
                                    0.5, 1.5, 2.5, 3.5],
        "attacker_return_formula": (
            "points>=80: min(3,(points-80)//40)+0.5; points==0: -3.5; "
            "otherwise: -(1+(79-points)//40)-0.5"),
        "role_sign": {"attacker": 1, "defender": -1},
        "oracle_baseline": False,
        "warm_start": False,
    },
    "network": {
        "schema": NETWORK_SCHEMA,
        "roles": [ROLE_NAMES[ROLE_ATTACKER], ROLE_NAMES[ROLE_DEFENDER]],
        "separate_role_parameters": True,
        "role_rationale": (
            "seat-relative features make same-team partners symmetric; "
            "attacker and banker-team defender objectives remain asymmetric; "
            "this is two Shengji roles, not DouZero's three landlord roles"),
        "state_hidden": STATE_HIDDEN,
        "history_hidden": HISTORY_HIDDEN,
        "action_hidden": ACTION_HIDDEN,
        "head_hidden": HEAD_HIDDEN,
        "state_encoder": "linear-ReLU",
        "history_encoder": "one-layer unidirectional GRU final valid output",
        "action_encoder": "linear-ReLU",
        "q_head": "concat context/action then linear-ReLU-linear scalar",
        "initialization": f"named-cpu-uniform[-{INIT_SCALE},{INIT_SCALE}]",
    },
    "update": {
        "schema": UPDATE_SCHEMA,
        "optimizer": "Adam",
        "optimizer_kwargs": {
            "betas": [0.9, 0.999],
            "eps": 1e-8,
            "weight_decay": 0.0,
            "amsgrad": False,
        },
        "learning_rate": LEARNING_RATE,
        "batch_size": UPDATE_BATCH_SIZE,
        "replay_capacity": REPLAY_CAPACITY,
        "replay_sampling": (
            "uniform without replacement over logical ring; all rows in "
            "logical order when replay size <= batch size"),
        "updates_per_actor_batch": 1,
        "loss": "mean squared error on chosen action and terminal return",
        "bootstrap": False,
    },
    "exploration": {
        "schema": EXPLORATION_SCHEMA,
        "epsilon": EPSILON,
        "rng": "identity-seed domain-separated local random.Random",
        "greedy_tie_break": "first ballot index via torch.argmax",
    },
    "opponent_and_controls": {
        "schema": OPPONENT_SCHEMA,
        "ordinary_play": "same immutable actor generation at all four seats",
        "declare": "explicit SmartBot control",
        "bury": "explicit SmartBot control",
        "ordinary_fallback": False,
    },
    "batch": {
        "rounds": ROUNDS_PER_BATCH,
        "round_state": "fresh level-2 Game per round",
        "scheduling": "one frozen actor batch then one serial learner update",
        "actor_refresh": (
            "bounded runner iteration consumes caller-supplied immutable actor; "
            "published candidate is not silently promoted"),
    },
}
ALGORITHM_SHA256 = state_digest(ALGORITHM_SPEC)


class DouZeroMicroError(RuntimeError):
    """The bounded microbaseline contract was violated."""


class UnsupportedDecisionSurface(DouZeroMicroError):
    """The ordinary-play Q actor was asked to decide another phase."""


def terminal_attacker_return(attacker_points: int) -> float:
    """Terminal level-bracket utility from the attacking team's perspective.

    The half unit represents taking/retaining the deal at the 80-point boundary;
    this is the direct terminal return, not an oracle residual or bootstrapped
    target.
    """
    if isinstance(attacker_points, bool) or not isinstance(attacker_points, int):
        raise DouZeroMicroError("attacker points must be an integer")
    if attacker_points < 0:
        raise DouZeroMicroError("attacker points cannot be negative")
    if attacker_points >= 80:
        return float(min(3, (attacker_points - 80) // 40) + 0.5)
    if attacker_points == 0:
        return -3.5
    return float(-(1 + (79 - attacker_points) // 40) - 0.5)


def acting_team_return(attacker_return: float, role: int) -> float:
    if role not in ROLE_NAMES:
        raise DouZeroMicroError(f"unsupported role {role!r}")
    return float(signed_return(
        attacker_return, acting_is_attacker=role == ROLE_ATTACKER))


def encode_public_history(rnd: Round, seat: int) -> np.ndarray:
    """Chronological public engine actions before ``seat``'s decision.

    Unlike aggregate card planes, rows preserve who acted, trick position, and
    order.  Only engine-recorded plays are used, so a failed throw contributes
    the public component the engine actually accepted.
    """
    events = []
    for trick in rnd.history:
        events.extend((position, play) for position, play in enumerate(trick.plays))
    if rnd.trick is not None:
        events.extend(
            (position, play) for position, play in enumerate(rnd.trick.plays))
    if len(events) > HISTORY_MAX_EVENTS:
        raise DouZeroMicroError(
            f"public history has {len(events)} events; cap is "
            f"{HISTORY_MAX_EVENTS}")

    rows = np.zeros((len(events), HISTORY_EVENT_DIM), dtype=np.float32)
    for row_index, (position, play) in enumerate(events):
        if position not in range(4) or play.seat not in range(4):
            raise DouZeroMicroError("invalid public trick event")
        for card in play.cards:
            try:
                card_index = CARD_INDEX[card]
            except KeyError as exc:
                raise DouZeroMicroError(
                    f"unknown public card code {card!r}") from exc
            rows[row_index, card_index] += 0.5
        offset = N_CARDS
        rows[row_index, offset + (play.seat - seat) % 4] = 1.0
        offset += 4
        rows[row_index, offset + position] = 1.0
        offset += 4
        rows[row_index, offset] = len(play.cards) / 25.0
        rows[row_index, offset + 1] = sum(points(c) for c in play.cards) / 40.0
    return rows


class _RoleActionQ(nn.Module):
    def __init__(self):
        super().__init__()
        self.state_encoder = nn.Sequential(
            nn.Linear(OBS_DIM, STATE_HIDDEN), nn.ReLU())
        self.history_encoder = nn.GRU(
            HISTORY_EVENT_DIM, HISTORY_HIDDEN, batch_first=True)
        self.action_encoder = nn.Sequential(
            nn.Linear(ACT_DIM, ACTION_HIDDEN), nn.ReLU())
        self.q_head = nn.Sequential(
            nn.Linear(
                STATE_HIDDEN + HISTORY_HIDDEN + ACTION_HIDDEN, HEAD_HIDDEN),
            nn.ReLU(),
            nn.Linear(HEAD_HIDDEN, 1),
        )

    def context(self, obs: torch.Tensor, history: torch.Tensor,
                history_lengths: torch.Tensor) -> torch.Tensor:
        state_features = self.state_encoder(obs)
        if history.ndim != 3 or history.shape[0] != obs.shape[0]:
            raise DouZeroMicroError("history tensor shape does not match batch")
        if history.shape[1] == 0:
            history_features = torch.zeros(
                (obs.shape[0], HISTORY_HIDDEN), dtype=obs.dtype,
                device=obs.device)
        else:
            sequence, _ = self.history_encoder(history)
            indices = (history_lengths - 1).clamp(min=0)
            history_features = sequence[
                torch.arange(obs.shape[0], device=obs.device), indices]
            history_features = torch.where(
                (history_lengths > 0).unsqueeze(1),
                history_features,
                torch.zeros_like(history_features),
            )
        return torch.cat([state_features, history_features], dim=1)

    def score(self, context: torch.Tensor,
              actions: torch.Tensor) -> torch.Tensor:
        action_features = self.action_encoder(actions)
        return self.q_head(
            torch.cat([context, action_features], dim=1)).squeeze(1)

    def forward(self, obs: torch.Tensor, history: torch.Tensor,
                history_lengths: torch.Tensor,
                actions: torch.Tensor) -> torch.Tensor:
        return self.score(
            self.context(obs, history, history_lengths), actions)


class DouZeroRoleQ(nn.Module):
    """Two independent action-Q networks for Shengji's asymmetric team roles."""

    def __init__(self):
        super().__init__()
        self.attacker = _RoleActionQ()
        self.defender = _RoleActionQ()

    def forward(self, roles: torch.Tensor, obs: torch.Tensor,
                history: torch.Tensor, history_lengths: torch.Tensor,
                actions: torch.Tensor) -> torch.Tensor:
        if roles.ndim != 1 or roles.shape[0] != obs.shape[0]:
            raise DouZeroMicroError("role tensor shape does not match batch")
        if not bool(torch.all((roles == ROLE_ATTACKER)
                              | (roles == ROLE_DEFENDER))):
            raise DouZeroMicroError("role tensor contains unsupported value")
        attacker_q = self.attacker(obs, history, history_lengths, actions)
        defender_q = self.defender(obs, history, history_lengths, actions)
        return torch.where(roles == ROLE_ATTACKER, attacker_q, defender_q)

    def score_candidates(self, *, role: int, obs: np.ndarray,
                         history: np.ndarray,
                         actions: np.ndarray) -> torch.Tensor:
        if role not in ROLE_NAMES:
            raise DouZeroMicroError(f"unsupported role {role!r}")
        if actions.ndim != 2 or actions.shape[1] != ACT_DIM or not len(actions):
            raise DouZeroMicroError("candidate action matrix is empty or malformed")
        role_net = self.attacker if role == ROLE_ATTACKER else self.defender
        with torch.no_grad():
            obs_tensor = torch.as_tensor(
                obs, dtype=torch.float32).reshape(1, OBS_DIM)
            history_tensor = torch.as_tensor(
                history, dtype=torch.float32).reshape(
                    1, len(history), HISTORY_EVENT_DIM)
            lengths = torch.as_tensor([len(history)], dtype=torch.long)
            context = role_net.context(
                obs_tensor, history_tensor, lengths).expand(len(actions), -1)
            action_tensor = torch.as_tensor(actions, dtype=torch.float32)
            return role_net.score(context, action_tensor)


def new_from_scratch_model(seed: int) -> DouZeroRoleQ:
    """Create deterministic weights without advancing process-global RNGs."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise DouZeroMicroError("model seed must be an integer")
    cpu_rng_state = torch.get_rng_state().clone()
    try:
        model = DouZeroRoleQ()
    finally:
        torch.set_rng_state(cpu_rng_state)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    with torch.no_grad():
        for _, parameter in sorted(model.named_parameters()):
            parameter.uniform_(
                -INIT_SCALE, INIT_SCALE, generator=generator)
    return model


def load_actor(path: str) -> DouZeroRoleQ:
    """Loader passed only through :func:`load_verified`."""
    model = new_from_scratch_model(0)
    state = torch.load(path, map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def publish_initial_actor(model: DouZeroRoleQ,
                          directory: str | Path) -> CheckpointRef:
    if not isinstance(model, DouZeroRoleQ):
        raise DouZeroMicroError("initial actor must be DouZeroRoleQ")
    return save_immutable_snapshot(
        model, directory, label="douzero_actor", sequence=0)


@dataclass
class _DecisionRecord:
    role: int
    obs: np.ndarray
    history: np.ndarray
    action: np.ndarray
    action_cards: tuple[str, ...]
    seat: int


class OrdinaryPlayActor:
    """Frozen epsilon-greedy actor for the sole supported decision surface."""

    def __init__(self, model: DouZeroRoleQ, rng: random.Random):
        self.model = model
        self.rng = rng
        self.records: list[_DecisionRecord] = []

    def decide_declare(self, *_args, **_kwargs):
        raise UnsupportedDecisionSurface(
            "DouZero micro actor does not implement declaration")

    def decide_bury(self, *_args, **_kwargs):
        raise UnsupportedDecisionSurface(
            "DouZero micro actor does not implement burial")

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        if rnd.phase != "play" or rnd.turn != seat or rnd.trick is None \
                or rnd.ordering is None:
            raise UnsupportedDecisionSurface(
                "DouZero micro actor supports only a legal ordinary-play turn")
        actions = enumerate_actions(
            rnd, seat, exhaustive_follows=False, include_throws=False)
        if not actions:
            raise DouZeroMicroError("ordinary-play ballot is empty")
        obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32)
        history = encode_public_history(rnd, seat)
        encoded_actions = np.asarray(
            [encode_action(action, rnd) for action in actions],
            dtype=np.float32).reshape(-1, ACT_DIM)
        role = ROLE_ATTACKER if rnd.is_attacker(seat) else ROLE_DEFENDER
        if len(actions) > 1 and self.rng.random() < EPSILON:
            chosen = self.rng.randrange(len(actions))
        elif len(actions) > 1:
            scores = self.model.score_candidates(
                role=role, obs=obs, history=history, actions=encoded_actions)
            chosen = int(torch.argmax(scores).item())
        else:
            chosen = 0
        self.records.append(_DecisionRecord(
            role=role,
            obs=obs,
            history=history,
            action=encoded_actions[chosen].copy(),
            action_cards=tuple(actions[chosen]),
            seat=seat,
        ))
        return list(actions[chosen])


class _ExplicitSurfaceComposite:
    """Named routing: SmartBot controls setup; Q actor controls every play."""

    def __init__(self, actor: OrdinaryPlayActor):
        self.actor = actor
        self.control = SmartBot()

    def decide_declare(self, rnd: Round, seat: int,
                       final: bool = False):
        return self.control.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd: Round, seat: int):
        return self.control.decide_bury(rnd, seat)

    def decide_play(self, rnd: Round, seat: int):
        return self.actor.decide_play(rnd, seat)


def _child_seed(parent: int, domain: str, sequence: int) -> int:
    payload = f"{int(parent)}|{domain}|{int(sequence)}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _sample_from_record(
        record: _DecisionRecord, *, identity: ActorBatchIdentity,
        round_index: int, decision_index: int, game_seed: int,
        attacker_return: float) -> dict[str, Any]:
    history_length = len(record.history)
    history = np.zeros(
        (HISTORY_MAX_EVENTS, HISTORY_EVENT_DIM), dtype=np.float32)
    history[:history_length] = record.history
    return {
        "schema": SAMPLE_SCHEMA,
        "surface": "ordinary_play",
        "history_schema": HISTORY_SCHEMA,
        "ballot_schema": BALLOT_SCHEMA,
        "reward_schema": REWARD_SCHEMA,
        "role": record.role,
        "obs": record.obs.copy(),
        # Fixed-shape storage avoids serialization-dependent strides for the
        # valid empty history at the first decision.  ``history_length`` keeps
        # padding outside the semantic sequence.
        "history": history,
        "history_length": history_length,
        "action": record.action.copy(),
        "action_cards": record.action_cards,
        "attacker_return": float(attacker_return),
        "target": acting_team_return(attacker_return, record.role),
        "seat": record.seat,
        "round_index": round_index,
        "decision_index": decision_index,
        "game_seed": game_seed,
        "actor_sha256": identity.actor_ref.sha256,
        "batch_sequence": identity.sequence,
        "runner_contract_sha256": identity.contract_sha256,
    }


@dataclass(frozen=True)
class DouZeroMicroCollector:
    expected_runner_contract_sha256: str
    rounds_per_batch: int = ROUNDS_PER_BATCH

    def __post_init__(self) -> None:
        if self.rounds_per_batch != ROUNDS_PER_BATCH:
            raise DouZeroMicroError(
                "round count is fixed by the algorithm contract")
        if not isinstance(self.expected_runner_contract_sha256, str) \
                or len(self.expected_runner_contract_sha256) != 64:
            raise DouZeroMicroError("expected runner contract must be SHA-256")

    def __call__(self, identity: ActorBatchIdentity) -> SynchronousActorBatch:
        if identity.experiment != EXPERIMENT or identity.purpose != "actor":
            raise DouZeroMicroError("unexpected actor batch identity")
        if identity.contract_sha256 != self.expected_runner_contract_sha256:
            raise DouZeroMicroError("actor batch runner contract mismatch")
        model = load_verified(identity.actor_ref, load_actor)
        actor = OrdinaryPlayActor(
            model,
            random.Random(_child_seed(identity.seed, "exploration", 0)),
        )
        policies = [_ExplicitSurfaceComposite(actor) for _ in range(4)]
        samples: list[dict[str, Any]] = []
        for round_index in range(self.rounds_per_batch):
            game_seed = _child_seed(identity.seed, "game", round_index)
            actor.records = []
            game = Game(random.Random(game_seed))
            play_round(game, policies)
            if game.round is None or game.result is None:
                raise DouZeroMicroError("round collection ended without result")
            attacker_return = terminal_attacker_return(
                game.result.attacker_points)
            for decision_index, record in enumerate(actor.records):
                samples.append(_sample_from_record(
                    record,
                    identity=identity,
                    round_index=round_index,
                    decision_index=decision_index,
                    game_seed=game_seed,
                    attacker_return=attacker_return,
                ))
        if not samples:
            raise DouZeroMicroError("actor batch contains no ordinary-play samples")
        return SynchronousActorBatch(identity=identity, samples=tuple(samples))


_SAMPLE_FIELDS = {
    "schema", "surface", "history_schema", "ballot_schema", "reward_schema",
    "role", "obs", "history", "history_length", "action", "action_cards",
    "attacker_return", "target", "seat", "round_index", "decision_index",
    "game_seed", "actor_sha256", "batch_sequence",
    "runner_contract_sha256",
}


def validate_sample(
        sample: object, *, identity: ActorBatchIdentity | None = None,
        contract_sha256: str | None = None) -> None:
    """Validate one sample, optionally against its producing batch.

    Replay legitimately contains samples from older immutable actors and batch
    sequences.  Collection validates all three provenance fields against the
    producing identity; replay updates bind only the runner contract while
    retaining and structurally validating the original actor/batch stamps.
    """
    if (identity is None) == (contract_sha256 is None):
        raise DouZeroMicroError(
            "validate_sample requires exactly one provenance boundary")
    if not isinstance(sample, Mapping) or set(sample) != _SAMPLE_FIELDS:
        raise DouZeroMicroError("micro sample fields mismatch")
    if sample["schema"] != SAMPLE_SCHEMA \
            or sample["surface"] != "ordinary_play":
        raise UnsupportedDecisionSurface("sample is not ordinary play")
    if sample["history_schema"] != HISTORY_SCHEMA \
            or sample["ballot_schema"] != BALLOT_SCHEMA \
            or sample["reward_schema"] != REWARD_SCHEMA:
        raise DouZeroMicroError("sample encoder/ballot/reward contract mismatch")
    role = sample["role"]
    if isinstance(role, bool) or not isinstance(role, int) \
            or role not in ROLE_NAMES:
        raise DouZeroMicroError("sample role is unsupported")
    obs = sample["obs"]
    history = sample["history"]
    action = sample["action"]
    if not isinstance(obs, np.ndarray) or obs.dtype != np.float32 \
            or obs.shape != (OBS_DIM,):
        raise DouZeroMicroError("sample observation shape/dtype mismatch")
    if not isinstance(history, np.ndarray) or history.dtype != np.float32 \
            or history.shape != (HISTORY_MAX_EVENTS, HISTORY_EVENT_DIM):
        raise DouZeroMicroError("sample history shape/dtype mismatch")
    if not isinstance(action, np.ndarray) or action.dtype != np.float32 \
            or action.shape != (ACT_DIM,):
        raise DouZeroMicroError("sample action shape/dtype mismatch")
    if not np.all(np.isfinite(obs)) or not np.all(np.isfinite(history)) \
            or not np.all(np.isfinite(action)):
        raise DouZeroMicroError("sample tensors contain non-finite values")
    if not isinstance(sample["action_cards"], tuple) \
            or not sample["action_cards"] \
            or not all(isinstance(card, str) and card in CARD_INDEX
                       for card in sample["action_cards"]):
        raise DouZeroMicroError("sample action cards are malformed")
    if isinstance(sample["seat"], bool) or not isinstance(sample["seat"], int) \
            or sample["seat"] not in range(4):
        raise DouZeroMicroError("sample seat is invalid")
    for label in ("history_length", "round_index", "decision_index",
                  "game_seed", "batch_sequence"):
        value = sample[label]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DouZeroMicroError(f"sample {label} is invalid")
    if sample["history_length"] > HISTORY_MAX_EVENTS:
        raise DouZeroMicroError("sample history length exceeds its fixed cap")
    if np.any(history[sample["history_length"]:] != 0):
        raise DouZeroMicroError("sample history padding is nonzero")
    attacker_return = sample["attacker_return"]
    target = sample["target"]
    if not isinstance(attacker_return, float) or not math.isfinite(attacker_return) \
            or not isinstance(target, float) or not math.isfinite(target):
        raise DouZeroMicroError("sample target is non-finite or non-float")
    if attacker_return not in {-3.5, -2.5, -1.5, 0.5, 1.5, 2.5, 3.5}:
        raise DouZeroMicroError("sample terminal return is outside reward support")
    if target != acting_team_return(attacker_return, role):
        raise DouZeroMicroError("sample target is not the direct signed return")
    actor_sha256 = sample["actor_sha256"]
    if not isinstance(actor_sha256, str) or len(actor_sha256) != 64 \
            or any(char not in "0123456789abcdef" for char in actor_sha256):
        raise DouZeroMicroError("sample actor digest is malformed")
    expected_contract = (identity.contract_sha256 if identity is not None
                         else contract_sha256)
    if sample["runner_contract_sha256"] != expected_contract:
        raise DouZeroMicroError("sample runner contract provenance mismatch")
    if identity is not None and (
            actor_sha256 != identity.actor_ref.sha256
            or sample["batch_sequence"] != identity.sequence):
        raise DouZeroMicroError("sample actor/batch provenance mismatch")


def _collate(samples: list[Mapping[str, Any]]) -> tuple[torch.Tensor, ...]:
    lengths = np.asarray(
        [sample["history_length"] for sample in samples], dtype=np.int64)
    max_history = int(lengths.max(initial=0))
    histories = np.stack(
        [sample["history"] for sample in samples])[:, :max_history].copy()
    return (
        torch.as_tensor([sample["role"] for sample in samples],
                        dtype=torch.long),
        torch.from_numpy(np.stack([sample["obs"] for sample in samples])),
        torch.from_numpy(histories),
        torch.from_numpy(lengths),
        torch.from_numpy(np.stack([sample["action"] for sample in samples])),
        torch.as_tensor([sample["target"] for sample in samples],
                        dtype=torch.float32),
    )


@dataclass(frozen=True)
class DouZeroMicroUpdate:
    batch_size: int = UPDATE_BATCH_SIZE

    def __post_init__(self) -> None:
        if self.batch_size != UPDATE_BATCH_SIZE:
            raise DouZeroMicroError("update batch size is fixed by contract")

    def __call__(self, context: LearnerUpdateContext) -> None:
        if not isinstance(context.learner, DouZeroRoleQ):
            raise DouZeroMicroError("learner has wrong network type")
        logical = context.replay.logical_items()
        if not logical:
            raise DouZeroMicroError("cannot update from empty replay")
        take = min(self.batch_size, len(logical))
        if take == len(logical):
            indices = list(range(len(logical)))
        else:
            indices = [int(value) for value in context.rng.numpy.choice(
                len(logical), size=take, replace=False)]
        samples = [logical[index] for index in indices]
        for sample in samples:
            validate_sample(
                sample,
                contract_sha256=context.batch.identity.contract_sha256)
        roles, obs, history, lengths, actions, targets = _collate(samples)
        predictions = context.learner(
            roles, obs, history, lengths, actions)
        loss = torch.mean((predictions - targets).square())
        context.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        context.optimizer.step()
        context.optimizer.zero_grad(set_to_none=True)


@dataclass
class DouZeroMicroBundle:
    learner: DouZeroRoleQ
    optimizer: torch.optim.Optimizer
    replay: ReplayRing
    rng: ResumeRNGStreams


def new_bundle(*, model_seed: int, learner_rng_seed: int,
               replay_capacity: int = REPLAY_CAPACITY) -> DouZeroMicroBundle:
    if replay_capacity != REPLAY_CAPACITY:
        raise DouZeroMicroError("replay capacity is fixed by contract")
    learner = new_from_scratch_model(model_seed)
    return DouZeroMicroBundle(
        learner=learner,
        optimizer=torch.optim.Adam(learner.parameters(), lr=LEARNING_RATE),
        replay=ReplayRing(replay_capacity),
        rng=ResumeRNGStreams.seeded(learner_rng_seed),
    )


def new_runner(*, bundle: DouZeroMicroBundle, actor_ref: CheckpointRef,
               snapshot_dir: str | Path, root_seed: int) \
        -> SynchronousSelfPlayRunner:
    return SynchronousSelfPlayRunner(
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=ALGORITHM_SHA256,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        snapshot_dir=snapshot_dir,
    )


def resume_runner(
        resume_ref: CheckpointRef, *, bundle: DouZeroMicroBundle,
        actor_ref: CheckpointRef, candidate_ref: CheckpointRef,
        snapshot_dir: str | Path, root_seed: int) -> SynchronousSelfPlayRunner:
    return SynchronousSelfPlayRunner.resume(
        resume_ref,
        experiment=EXPERIMENT,
        root_seed=root_seed,
        algorithm_sha256=ALGORITHM_SHA256,
        learner=bundle.learner,
        optimizer=bundle.optimizer,
        replay=bundle.replay,
        rng=bundle.rng,
        actor_ref=actor_ref,
        candidate_ref=candidate_ref,
        snapshot_dir=snapshot_dir,
    )


def _wire_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        return {
            "__ndarray__": True,
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "data": base64.b64encode(array.tobytes()).decode("ascii"),
        }
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise DouZeroMicroError("wire mappings require string keys")
        return {key: _wire_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_wire_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise DouZeroMicroError(
        f"unsupported actor-batch wire value {type(value).__name__}")


def actor_batch_bytes(batch: SynchronousActorBatch) -> bytes:
    """Canonical bytes used by interrupted/resumed collector equivalence."""
    if not isinstance(batch, SynchronousActorBatch):
        raise DouZeroMicroError("expected SynchronousActorBatch")
    payload = {
        "schema": "douzero-micro-actor-batch-wire-v1",
        "identity": batch.identity.as_dict(),
        "samples": batch.samples,
    }
    return json.dumps(
        _wire_value(payload), sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")


def bundle_digest(bundle: DouZeroMicroBundle) -> str:
    return state_digest({
        "learner": bundle.learner.state_dict(),
        "optimizer": bundle.optimizer.state_dict(),
        "replay": bundle.replay.state_dict(),
        "rng": bundle.rng.state_dict(),
    })


def contract_digest(spec: Mapping[str, Any]) -> str:
    """Test seam proving every declared algorithm choice affects identity."""
    return state_digest(copy.deepcopy(spec))
