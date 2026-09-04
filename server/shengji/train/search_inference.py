"""Small, fail-closed inference adapter for learned search.

The adapter deliberately keeps action enumeration outside the model.  Callers
provide the complete legal population and receive one distribution over that
population; no hidden state is read beyond :mod:`shengji.rl.encode`.
"""

from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

import torch

from ..rl.encode import ACT_DIM, OBS_DIM, encode_action, encode_obs
from .data import encoder_identity
from .model import MODEL_SCHEMA, ValuePriorNet


CHECKPOINT_SCHEMA = "shengji-train-v0-checkpoint-v3"
LEGACY_CHECKPOINT_SCHEMA = "shengji-train-v0-checkpoint-v2"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _as_state(state: Any) -> tuple[Any, int]:
    """Accept either a public ``(Round, seat)`` pair or a Round leaf.

    LearnedSearchBot passes continuation rounds directly; their ``turn`` is
    the acting seat.  The pair form remains useful for callers evaluating a
    state whose acting seat is kept separately.
    """
    if isinstance(state, (tuple, list)):
        if len(state) != 2:
            raise ValueError("state must be a (Round, seat) pair")
        rnd, seat = state
    else:
        rnd = state
        seat = getattr(rnd, "turn", None)
    if not isinstance(seat, int) or isinstance(seat, bool) or not 0 <= seat < 4:
        raise ValueError("state must carry an acting seat in [0, 4)")
    return rnd, seat


class SearchHeads:
    """Batched ValuePriorNet heads for exhaustive-search consumers.

    ``model_calls`` counts each actual trunk or head invocation.  A prior call
    therefore costs one trunk invocation plus one prior-head invocation per
    action chunk; a value call costs one trunk plus one value-head invocation.
    """

    def __init__(self, model: ValuePriorNet, *, batch_size: int = 256,
                 device: str | torch.device = "cpu",
                 metadata: Mapping[str, Any] | None = None):
        if not isinstance(model, ValuePriorNet):
            raise TypeError("model must be a ValuePriorNet")
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        self.model = model
        self.batch_size = batch_size
        self.device = torch.device(device)
        self.model.to(self.device)
        self.model.eval()
        self.metadata = copy.deepcopy(dict(metadata or {}))
        self.counters = {
            "model_calls": 0,
            "value_rows": 0,
            "prior_action_rows": 0,
            "inference_secs": 0.0,
        }

    @classmethod
    def from_checkpoint(cls, path: str | Path, *, batch_size: int = 256,
                        device: str | torch.device = "cpu",
                        allow_legacy: bool = False) -> "SearchHeads":
        checkpoint_path = Path(path)
        try:
            digest = _file_sha256(checkpoint_path)
        except OSError as exc:
            raise ValueError(f"{checkpoint_path}: cannot read checkpoint") from exc
        try:
            payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        except Exception as exc:
            raise ValueError(f"{checkpoint_path}: unreadable checkpoint") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("checkpoint payload must be a mapping")
        schema = payload.get("schema")
        legacy = schema == LEGACY_CHECKPOINT_SCHEMA
        if schema != CHECKPOINT_SCHEMA and not (legacy and allow_legacy):
            wanted = f"{CHECKPOINT_SCHEMA} (legacy requires allow_legacy=True)"
            raise ValueError(f"checkpoint schema {schema!r} != {wanted}")
        if payload.get("model_schema") != MODEL_SCHEMA:
            raise ValueError("checkpoint model schema differs from this build")
        enc = payload.get("encoder")
        current = encoder_identity()
        transitive = enc.get("transitive") if isinstance(enc, Mapping) else None
        if not isinstance(enc, Mapping) or enc.get("implementation_sha256") != current["implementation_sha256"]:
            raise ValueError("checkpoint encoder differs from the current encoder")
        if (not isinstance(transitive, Mapping)
                or transitive.get("implementation_sha256")
                != current["transitive"]["implementation_sha256"]):
            raise ValueError("checkpoint transitive encoder differs from the current encoder")
        arch = payload.get("arch")
        if not isinstance(arch, Mapping):
            raise ValueError("checkpoint arch is missing or malformed")
        if type(arch.get("obs_dim")) is not int or type(arch.get("act_dim")) is not int:
            raise ValueError("checkpoint arch dimensions are malformed")
        obs_dim = arch["obs_dim"]
        act_dim = arch["act_dim"]
        if obs_dim != OBS_DIM or act_dim != ACT_DIM:
            raise ValueError("checkpoint arch dimensions differ from the current encoder")
        state = payload.get("model_state")
        if not isinstance(state, Mapping):
            raise ValueError("checkpoint model_state is missing or malformed")
        try:
            model = ValuePriorNet(dict(arch))
            model.load_state_dict(state, strict=True)
        except Exception as exc:
            raise ValueError("checkpoint model architecture or state differs") from exc
        population = payload.get("population")
        if not legacy and not isinstance(population, Mapping):
            raise ValueError("v3 checkpoint has no persisted population")
        metadata = {
            "checkpoint_sha256": digest,
            "schema": schema,
            "model_schema": payload["model_schema"],
            "epoch": payload.get("epoch"),
            "encoder": copy.deepcopy(dict(enc)),
            "population": copy.deepcopy(dict(population)) if isinstance(population, Mapping) else None,
            "population_available": isinstance(population, Mapping) and not legacy,
            "legacy": legacy,
            # A population binding is provenance, not evidence that a caller
            # supplied an actually disjoint evaluation set.
            "held_out_claim": False,
        }
        return cls(model, batch_size=batch_size, device=device, metadata=metadata)

    def _check_actions(self, rnd: Any, actions: Sequence[Any]) -> None:
        if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)) or len(actions) == 0:
            raise ValueError("actions must be a non-empty sequence")
        if getattr(rnd, "ordering", None) is None:
            raise ValueError("round must have finalized ordering")

    def priors(self, rnd: Any, seat: int, actions: Sequence[Any]) -> list[float]:
        """Return a single softmax distribution over every supplied action."""
        if not isinstance(seat, int) or isinstance(seat, bool) or not 0 <= seat < 4:
            raise ValueError("seat must be an integer in [0, 4)")
        self._check_actions(rnd, actions)
        started = perf_counter()
        try:
            obs = torch.tensor([encode_obs(rnd, seat)], dtype=torch.float32, device=self.device)
            with torch.inference_mode():
                emb = self.model.trunk(obs)
                self.counters["model_calls"] += 1
                if emb.shape != (1, self.model.embed_dim):
                    raise ValueError("trunk returned the wrong shape")
                logits_parts: list[torch.Tensor] = []
                for start in range(0, len(actions), self.batch_size):
                    action_rows = [encode_action(list(action), rnd)
                                   for action in actions[start:start + self.batch_size]]
                    if any(len(row) != ACT_DIM for row in action_rows):
                        raise ValueError("action encoder returned the wrong shape")
                    cand = torch.tensor(action_rows,
                                        dtype=torch.float32, device=self.device).unsqueeze(0)
                    chunk = cand.shape[1]
                    joined = torch.cat([emb.unsqueeze(1).expand(-1, chunk, -1), cand], dim=2)
                    logits = self.model.prior_head(joined).squeeze(2)
                    self.counters["model_calls"] += 1
                    if logits.shape != (1, chunk):
                        raise ValueError("prior head returned the wrong shape")
                    logits_parts.append(logits.squeeze(0))
                logits_all = torch.cat(logits_parts, dim=0)
                if logits_all.shape != (len(actions),) or not torch.isfinite(logits_all).all():
                    raise ValueError("prior head returned non-finite values")
                probs = torch.softmax(logits_all, dim=0)
                if not torch.isfinite(probs).all():
                    raise ValueError("prior softmax returned non-finite values")
                result = probs.detach().cpu().tolist()
            if not all(math.isfinite(float(v)) for v in result):
                raise ValueError("prior output is non-finite")
            self.counters["prior_action_rows"] += len(actions)
            return [float(v) for v in result]
        finally:
            self.counters["inference_secs"] += perf_counter() - started

    def values(self, states: Sequence[Any]) -> list[float]:
        """Return signed-level utility predictions for each acting team."""
        if not isinstance(states, Sequence) or isinstance(states, (str, bytes)) or len(states) == 0:
            raise ValueError("states must be a non-empty sequence")
        started = perf_counter()
        try:
            rows = []
            for state in states:
                rnd, seat = _as_state(state)
                if getattr(rnd, "ordering", None) is None:
                    raise ValueError("round must have finalized ordering")
                rows.append(encode_obs(rnd, seat))
            with torch.inference_mode():
                outputs: list[torch.Tensor] = []
                for start in range(0, len(rows), self.batch_size):
                    obs = torch.tensor(rows[start:start + self.batch_size], dtype=torch.float32,
                                       device=self.device)
                    emb = self.model.trunk(obs)
                    self.counters["model_calls"] += 1
                    if emb.shape != (obs.shape[0], self.model.embed_dim):
                        raise ValueError("trunk returned the wrong shape")
                    value = self.model.value_head(emb)
                    self.counters["model_calls"] += 1
                    if value.ndim != 2 or value.shape[0] != obs.shape[0] or value.shape[1] < 1:
                        raise ValueError("value head returned the wrong shape")
                    outputs.append(value[:, 0])
                result_tensor = torch.cat(outputs, dim=0)
                if result_tensor.shape != (len(rows),) or not torch.isfinite(result_tensor).all():
                    raise ValueError("value head returned non-finite values")
                result = result_tensor.detach().cpu().tolist()
            self.counters["value_rows"] += len(rows)
            return [float(v) for v in result]
        finally:
            self.counters["inference_secs"] += perf_counter() - started
