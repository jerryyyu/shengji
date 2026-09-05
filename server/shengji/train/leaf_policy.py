"""Value-at-leaf screen arms (DEV): the production search with a learned LEAF.

The first real test of the value direction.  ``mc-s0-report-lcb`` scores every
(candidate, sampled world) pair with ONE deterministic heuristic continuation
to round end and uses the round's final attacker points as the rollout value.
:class:`MCValueLeafSearch` is that production class with exactly one method
overridden, ``_rollout``:

1. the determinized clone is built exactly as production builds it (same
   helpers, same order, same trusted-rollout marks);
2. the candidate is played, then the heuristic continuation runs for at most
   ``leaf_tricks`` tricks (``T``: 0 evaluates right after the candidate, 1
   completes the current trick, ...), honouring the S3b exact-endgame
   shortcut wherever production would take it;
3. a leaf that reached round end returns ``float(clone.attacker_points)``
   exactly as production does; otherwise the leaf returns a prediction of the
   round's FINAL attacker points for that clone, encoded from the clone's
   seat to act.

The prediction is in production's rollout units (final attacker points), so
``_score``, the attacker/banker sign flip, the paired report fold and the LCB
rule are untouched: only the estimator of the leaf changes.

Three leaf evaluators share the truncation:

* :class:`LearnedPointsLeaf` (``--leaf-model public``) — the search
  checkpoint's auxiliary points head (``model.py``: ``value_head`` column 1,
  trained on ``attacker_points / 100``) on the PUBLIC observation of the
  clone's seat to act, exported once per process to numpy and run single-row
  (torch per-call overhead is too high inside the rollout loop).
* :class:`CompleteWorldPointsLeaf` (``--leaf-model cwv``) — the
  complete-world value net's auxiliary points head (``train_cwv.py``:
  ``AuxPointsHead`` on the ``mlp`` trunk, trained on ``attacker_points /
  100``) on the determinized clone ITSELF: the clone is a complete world, so
  ``value_afterstate.tensors_from_round(clone, seat_to_act)`` encodes the
  sampled hands and burial into the world tensor.  Same numpy export, same
  units.  The one-ply play test of that net (#229) lost to production at
  every budget while beating a no-learning control; this leaf puts the same
  net under production's own rollouts, the cheapest depth test.
* :class:`PriorPointsLeaf` — the NO-LEARNING control: the stratified prior
  the trainer fits on the training rows (phase x role x attacker points so
  far, 18 cells; ``baselines.py``) refitted on the FINAL attacker points
  target.  Identical truncation and world dose, so a learned-minus-prior
  difference isolates "learned leaf" from "truncation + more worlds".

Two variants scope or soften the substitution (both bind into the policy
name, the calibration identity and the summary):

* ``leaf_stage="report"`` (``-report``): the leaf is consulted only inside
  the report fold (``MCBot._report_fold_gap``: the top two candidates on the
  R paired worlds, ~77% of production's rollouts); selection rollouts run
  to round end and are production's byte for byte.
* ``leaf_mode="control-variate"`` (``-cv``): the rollout runs to round end
  as production does and the net's estimate ``X`` at the horizon is
  subtracted as a per-candidate centred control variate, ``Y - beta * (X -
  mean_c X)``.  The centring sums to zero per candidate, so every mean and
  the report fold's paired gap are production's; only the fold's paired SE
  (hence the LCB statistic) changes.  ``beta=0`` is production exactly.

A checkpoint without a points head is refused; identity checks (encoder
SHA, checkpoint schema) go through ``SearchHeads.from_checkpoint`` (public)
or ``train_cwv.load_cwv_checkpoint`` (cwv).  Nothing here registers a
production default.
"""
from __future__ import annotations

import copy
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

import numpy as np

from ..ai.registry import (REGISTRY, VLEAF_BASE_POLICY, VLEAF_LEAF_MODELS, VLEAF_LEAF_MODES,
                           VLEAF_LEAF_STAGES, VLEAF_LEAF_TRICKS, vleaf_checkpoint_sha256,
                           vleaf_policy_suffix)
from ..engine.round import Round, Trick, TrickPlay
from ..rl.encode import CARD_INDEX, N_CARDS, OBS_DIM, encode_obs
from ..rl.value_afterstate import PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, tensors_from_round
from .baselines import N_STRATA, POINT_BINS, ROLES, StratifiedPrior
from .data import PLAYS_PER_ROUND, check_meta, part_keys, read_column, read_meta, split_deals

LEAF_RECORD_SCHEMA = "vleaf-leaf-v1"
POINTS_PRIOR_SCHEMA = "vleaf-points-prior-v1"
#: the aux points head is trained on ``attacker_points / POINTS_SCALE``
#: (model.py for the public head, train_cwv.AuxPointsHead for the cwv head)
POINTS_SCALE = 100.0
SUPPORTED_LEAF_TRICKS = VLEAF_LEAF_TRICKS
LEAF_MODELS = VLEAF_LEAF_MODELS
#: value_model.MLP_INPUT_DIM without importing torch into every worker (tested equal)
MLP_INPUT_DIM = PUBLIC_DIM + WORLD_RECEIVERS * N_CARDS + PERSPECTIVE_DIM


class LeafError(ValueError):
    """The leaf evaluator cannot support the stated contract (fail closed)."""


# ----------------------------------------------------------------- numpy GELU

_ERF_LIMIT = 6.0
_ERF_STEPS = 60_000
_ERF_STEP = 2.0 * _ERF_LIMIT / _ERF_STEPS
_ERF_TABLE = np.fromiter(
    map(math.erf, np.linspace(-_ERF_LIMIT, _ERF_LIMIT, _ERF_STEPS + 1)),
    dtype=np.float64, count=_ERF_STEPS + 1)


def erf(x: np.ndarray) -> np.ndarray:
    """``math.erf`` over an array: linear interpolation of a 2e-4 grid on
    [-6, 6] (|error| < 1e-8, tested), saturating to ``erf(+-6)`` beyond.
    numpy has no erf and a per-element ``math.erf`` loop costs more than the
    rest of the forward pass."""
    x = np.asarray(x, dtype=np.float64)
    pos = (np.clip(x, -_ERF_LIMIT, _ERF_LIMIT) + _ERF_LIMIT) / _ERF_STEP
    idx = np.minimum(pos.astype(np.int64), _ERF_STEPS - 1)
    lo = _ERF_TABLE[idx]
    return lo + (_ERF_TABLE[idx + 1] - lo) * (pos - idx)


def gelu(x: np.ndarray) -> np.ndarray:
    """torch.nn.GELU(approximate='none'): 0.5 x (1 + erf(x / sqrt 2))."""
    x = np.asarray(x, dtype=np.float64)
    return 0.5 * x * (1.0 + erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------- points head

def require_points_head(*, arch: Mapping[str, Any] | None = None,
                        output_width: int | None = None) -> None:
    """Refuse a checkpoint without the auxiliary points head (``model.py``:
    ``arch['aux_points']`` widens the value head to two outputs)."""
    if arch is not None and not arch.get("aux_points"):
        raise LeafError("checkpoint has no points head: arch.aux_points is false "
                        "(train with --aux-points)")
    if output_width is not None and output_width != 2:
        raise LeafError("checkpoint has no points head: the value head emits "
                        f"{output_width} column(s), the points head is column 1")


class PointsHead:
    """The checkpoint's attacker-points head as a numpy MLP.

    ``layers`` are ``(weight, bias)`` pairs: every hidden layer (trunk layers
    and the value head's hidden layer) is followed by an exact GELU; the last
    layer is linear with two outputs, ``[signed-level value, attacker points
    / POINTS_SCALE]``.  Dropout is identity at inference.
    """

    def __init__(self, hidden: Sequence[tuple[np.ndarray, np.ndarray]],
                 output: tuple[np.ndarray, np.ndarray], *,
                 metadata: Mapping[str, Any] | None = None):
        if not hidden:
            raise LeafError("points head needs at least one hidden layer")
        self.hidden = [(np.ascontiguousarray(w.T, dtype=np.float64),
                        np.ascontiguousarray(b, dtype=np.float64)) for w, b in hidden]
        w, b = output
        self.output = (np.ascontiguousarray(w.T, dtype=np.float64),
                       np.ascontiguousarray(b, dtype=np.float64))
        require_points_head(output_width=int(self.output[0].shape[1]))
        if self.output[1].shape != (self.output[0].shape[1],):
            raise LeafError("points head output bias does not match its weight")
        self.obs_dim = int(self.hidden[0][0].shape[0])
        width = self.obs_dim
        for wt, bias in self.hidden:
            if wt.shape[0] != width or bias.shape != (wt.shape[1],):
                raise LeafError("points head layers do not chain")
            width = wt.shape[1]
        if self.output[0].shape[0] != width:
            raise LeafError("points head output layer does not chain")
        self.metadata = copy.deepcopy(dict(metadata or {}))
        self.calls = 0

    @classmethod
    def from_model(cls, model, *, metadata: Mapping[str, Any] | None = None) -> "PointsHead":
        """Export a ``ValuePriorNet`` with ``arch['aux_points']``; refuses one
        without the head or with a non-exact GELU."""
        import torch
        from torch import nn

        arch = getattr(model, "arch", None)
        if not isinstance(arch, Mapping):
            raise LeafError("model carries no arch")
        require_points_head(arch=arch)

        def linear(module) -> tuple[np.ndarray, np.ndarray]:
            if not isinstance(module, nn.Linear) or module.bias is None:
                raise LeafError(f"expected a biased nn.Linear, found {type(module).__name__}")
            with torch.no_grad():
                return (module.weight.detach().cpu().double().numpy().copy(),
                        module.bias.detach().cpu().double().numpy().copy())

        def exact_gelu(module) -> None:
            if not isinstance(module, nn.GELU) or getattr(module, "approximate", "none") != "none":
                raise LeafError(f"expected an exact nn.GELU, found {type(module).__name__}")

        hidden = []
        trunk = list(model.trunk)
        i = 0
        while i < len(trunk):
            weight = linear(trunk[i])
            exact_gelu(trunk[i + 1])
            hidden.append(weight)
            i += 2
            if i < len(trunk) and isinstance(trunk[i], nn.Dropout):
                i += 1
        head = list(model.value_head)
        if len(head) != 3:
            raise LeafError("value head is not Linear -> GELU -> Linear")
        hidden.append(linear(head[0]))
        exact_gelu(head[1])
        output = linear(head[2])
        require_points_head(output_width=int(output[0].shape[0]))
        meta = dict(metadata or {})
        meta["points_head"] = {"column": 1, "target": "final attacker points / 100",
                               "scale": POINTS_SCALE, "arch": dict(arch)}
        return cls(hidden, output, metadata=meta)

    @classmethod
    def from_checkpoint(cls, path: str | os.PathLike, *, allow_legacy: bool = False) -> "PointsHead":
        """Load through ``SearchHeads.from_checkpoint`` (schema and encoder
        identity checks), then export the points head."""
        from .search_inference import SearchHeads

        heads = SearchHeads.from_checkpoint(path, allow_legacy=allow_legacy, device="cpu")
        return cls.from_model(heads.model, metadata=heads.metadata)

    def forward(self, obs) -> np.ndarray:
        """Raw head outputs for one row (``[2]``) or a batch (``[B, 2]``)."""
        x = np.asarray(obs, dtype=np.float64)
        if x.shape[-1] != self.obs_dim:
            raise LeafError(f"observation width {x.shape[-1]} != {self.obs_dim}")
        for wt, bias in self.hidden:
            x = gelu(x @ wt + bias)
        wt, bias = self.output
        return x @ wt + bias

    def final_attacker_points(self, obs) -> float:
        self.calls += 1
        value = float(self.forward(obs)[1]) * POINTS_SCALE
        if not math.isfinite(value):
            raise LeafError("points head returned a non-finite leaf value")
        return value


# --------------------------------------------- complete-world points head

def require_cwv_points_head(metadata: Mapping[str, Any], *, arch: str | None = None) -> None:
    """Refuse a complete-world checkpoint without the auxiliary points head
    (``train_cwv.py``: ``--aux-points`` stores ``metadata['aux_points_head']``)
    or with an architecture whose trunk it cannot read."""
    if arch is not None and arch != "mlp":
        raise LeafError(f"complete-world leaf needs the mlp architecture, checkpoint is {arch!r}")
    head = metadata.get("aux_points_head")
    if not isinstance(head, Mapping) or not head:
        raise LeafError("checkpoint has no points head: metadata.aux_points_head is null "
                        "(train with --aux-points)")


class CompleteWorldPointsHead:
    """The complete-world net's ``mlp`` trunk plus its auxiliary points head
    as a numpy MLP: ``[public | world.ravel | perspective]`` (804) ->
    GELU(W1) -> GELU(W2) -> aux linear (one output, attacker points / 100).
    Dropout is identity at inference.  Single-row float64, like
    :class:`PointsHead`; torch's own single-row forward is not faster and
    the export is witnessed equal within 1e-5.
    """

    leaf_model = "cwv"

    def __init__(self, hidden: Sequence[tuple[np.ndarray, np.ndarray]],
                 output: tuple[np.ndarray, np.ndarray], *,
                 metadata: Mapping[str, Any] | None = None):
        if not hidden:
            raise LeafError("complete-world points head needs at least one hidden layer")
        self.hidden = [(np.ascontiguousarray(w.T, dtype=np.float64),
                        np.ascontiguousarray(b, dtype=np.float64)) for w, b in hidden]
        w, b = output
        self.output = (np.ascontiguousarray(w.T, dtype=np.float64),
                       np.ascontiguousarray(b, dtype=np.float64))
        if self.output[0].shape[1] != 1 or self.output[1].shape != (1,):
            raise LeafError("complete-world points head must emit exactly one output")
        self.input_dim = int(self.hidden[0][0].shape[0])
        width = self.input_dim
        for wt, bias in self.hidden:
            if wt.shape[0] != width or bias.shape != (wt.shape[1],):
                raise LeafError("complete-world points head layers do not chain")
            width = wt.shape[1]
        if self.output[0].shape[0] != width:
            raise LeafError("complete-world points head output layer does not chain")
        self.metadata = copy.deepcopy(dict(metadata or {}))
        self.calls = 0

    @classmethod
    def from_model(cls, model, aux_head, *, metadata: Mapping[str, Any] | None = None
                   ) -> "CompleteWorldPointsHead":
        """Export a ``ValueNetwork(architecture='mlp')`` trunk and its
        ``AuxPointsHead``; refuses another architecture, a missing head or a
        non-exact GELU."""
        import torch
        from torch import nn

        config = getattr(model, "config", None)
        if getattr(config, "architecture", None) != "mlp":
            raise LeafError("complete-world leaf needs the mlp architecture "
                            f"(checkpoint is {getattr(config, 'architecture', None)!r})")
        if aux_head is None:
            raise LeafError("checkpoint has no points head: metadata.aux_points_head is null "
                            "(train with --aux-points)")

        def linear(module) -> tuple[np.ndarray, np.ndarray]:
            if not isinstance(module, nn.Linear) or module.bias is None:
                raise LeafError(f"expected a biased nn.Linear, found {type(module).__name__}")
            with torch.no_grad():
                return (module.weight.detach().cpu().double().numpy().copy(),
                        module.bias.detach().cpu().double().numpy().copy())

        hidden = []
        trunk = list(model.trunk)
        i = 0
        while i < len(trunk):
            hidden.append(linear(trunk[i]))
            act = trunk[i + 1]
            if not isinstance(act, nn.GELU) or getattr(act, "approximate", "none") != "none":
                raise LeafError(f"expected an exact nn.GELU, found {type(act).__name__}")
            i += 2
            if i < len(trunk) and isinstance(trunk[i], nn.Dropout):
                i += 1
        output = linear(aux_head.linear)
        meta = dict(metadata or {})
        meta["points_head"] = {"source": "metadata.aux_points_head on the mlp trunk",
                               "target": "final attacker points / 100", "scale": POINTS_SCALE,
                               "model_config": dict(config.payload())}
        return cls(hidden, output, metadata=meta)

    @classmethod
    def from_checkpoint(cls, path: str | os.PathLike) -> "CompleteWorldPointsHead":
        """Load through ``train_cwv.load_cwv_checkpoint`` (schema, arch and
        afterstate-encoder identity checks), then export the points head."""
        from .train_cwv import TrainError, load_cwv_checkpoint

        path = str(Path(path).resolve())
        try:
            model, metadata, aux = load_cwv_checkpoint(path, "cpu")
        except TrainError as exc:
            raise LeafError(f"complete-world checkpoint refused: {exc}") from exc
        require_cwv_points_head(metadata, arch=metadata.get("arch"))
        meta = {k: metadata.get(k) for k in ("schema", "arch", "epoch", "encoder", "git",
                                             "selection", "headline", "model_config")}
        meta["checkpoint_sha256"] = vleaf_checkpoint_sha256(path)
        meta["checkpoint"] = path
        meta["sees_hidden_hands"] = metadata.get("sees_hidden_hands")
        return cls.from_model(model, aux, metadata=meta)

    def forward(self, inputs) -> np.ndarray:
        """Aux head output (points / 100) for one row (``[1]``) or a batch (``[B, 1]``)."""
        x = np.asarray(inputs, dtype=np.float64)
        if x.shape[-1] != self.input_dim:
            raise LeafError(f"input width {x.shape[-1]} != {self.input_dim}")
        for wt, bias in self.hidden:
            x = gelu(x @ wt + bias)
        wt, bias = self.output
        return x @ wt + bias

    def final_attacker_points(self, inputs) -> float:
        self.calls += 1
        value = float(self.forward(inputs)[0]) * POINTS_SCALE
        if not math.isfinite(value):
            raise LeafError("complete-world points head returned a non-finite leaf value")
        return value


def cwv_reference_inputs(clone: Round, seat: int) -> np.ndarray:
    """The mlp's input row through ``value_afterstate.tensors_from_round``
    (the encoding the net was trained on), laid out as the trunk reads it
    (``value_model.ValueNetwork.features``: public | world.ravel | perspective)."""
    t = tensors_from_round(clone, seat)
    return np.concatenate((t.public, t.world.reshape(-1), t.perspective))


def cwv_leaf_inputs(clone: Round, seat: int) -> np.ndarray:
    """:func:`cwv_reference_inputs`, byte for byte (tested on real states),
    without the two costs the leaf never uses: the public-history tensor (the
    ``mlp`` trunk reads none) and the deck-conservation check (the
    determinizer already validated the clone's world).  ~50 us instead of
    ~120 us per leaf, next to a ~30 us forward."""
    x = np.zeros(MLP_INPUT_DIM, dtype=np.float32)
    x[:OBS_DIM] = encode_obs(clone, seat)
    x[OBS_DIM] = float(clone.phase == "round_end")
    world = x[PUBLIC_DIM:PUBLIC_DIM + WORLD_RECEIVERS * N_CARDS].reshape(WORLD_RECEIVERS, N_CARDS)
    hands = clone.hands
    for relative in range(4):
        row = world[relative]
        for card in hands[(seat + relative) % 4]:
            row[CARD_INDEX[card]] += 0.5
    row = world[4]
    for card in clone.buried:
        row[CARD_INDEX[card]] += 0.5
    attacker = clone.is_attacker(seat)
    x[PUBLIC_DIM + WORLD_RECEIVERS * N_CARDS] = float(attacker)
    x[PUBLIC_DIM + WORLD_RECEIVERS * N_CARDS + 1] = float(not attacker)
    return x


# --------------------------------------------------------- stratified prior

def leaf_ply(clone: Round) -> int:
    """Plays made so far in the round, the training rows' ``ply``."""
    assert clone.trick is not None
    return 4 * len(clone.history) + len(clone.trick.plays)


def leaf_stratum(ply: int, role_attacker: bool, points: float) -> int:
    """``baselines.stratum_index`` for one row (phase thirds x role x points bin)."""
    phase = min(2, max(0, int(ply) * 3 // PLAYS_PER_ROUND))
    point_bin = 0 if points < 40 else (1 if points < 80 else 2)
    return (phase * len(ROLES) + int(bool(role_attacker))) * len(POINT_BINS) + point_bin


class StratifiedPointsPrior:
    """Mean FINAL attacker points per stratum (global-mean fallback), the
    no-learning leaf.  Same strata and fitting rule as the trainer's
    ``StratifiedPrior``; the target is the round's final attacker points
    instead of signed-level utility."""

    def __init__(self, sums, counts, *, provenance: Mapping[str, Any] | None = None):
        self.prior = StratifiedPrior(np.asarray(sums, np.float64), np.asarray(counts, np.int64))
        if self.prior.sums.shape != (N_STRATA,) or self.prior.counts.shape != (N_STRATA,):
            raise LeafError(f"points prior needs {N_STRATA} cells")
        self.means = self.prior.means()
        self.provenance = copy.deepcopy(dict(provenance or {}))

    @property
    def n(self) -> int:
        return int(self.prior.counts.sum())

    def predict(self, ply: int, role_attacker: bool, points: float) -> float:
        return float(self.means[leaf_stratum(ply, role_attacker, points)])

    def to_dict(self) -> dict:
        base = self.prior.to_dict()
        return {
            "schema": POINTS_PRIOR_SCHEMA,
            "target": "round's final attacker points (outcome.attacker_points)",
            "units": "attacker points, production's rollout units",
            **base,
            "provenance": copy.deepcopy(self.provenance),
            "held_out_claim": False,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StratifiedPointsPrior":
        if d.get("schema") != POINTS_PRIOR_SCHEMA:
            raise LeafError(f"points prior schema {d.get('schema')!r} != {POINTS_PRIOR_SCHEMA!r}")
        return cls(d["sums"], d["counts"], provenance=d.get("provenance"))

    @classmethod
    def from_json(cls, path: str | os.PathLike) -> "StratifiedPointsPrior":
        with open(path, "r", encoding="utf-8") as fh:
            table = cls.from_dict(json.load(fh))
        table.provenance["file_sha256"] = vleaf_checkpoint_sha256(path)
        return table


def fit_points_prior(cache_files: Sequence[str | os.PathLike], *, split_seed: int,
                     val_fraction: float, test_fraction: float, part: str = "train",
                     expected_shards: Mapping[str, str] | None = None) -> StratifiedPointsPrior:
    """Refit the trainer's strata on the FINAL attacker points of the
    ``part`` rows of the given cache files, reproducing the trainer's split
    (``split_deals`` over the same deal keys, same seed and fractions).

    ``expected_shards`` (``{cache path: shard sha256}``) binds each cache
    file to the receipt's shard; every file must carry the current encoder.
    """
    columns = ("deal_key", "ply", "role_attacker", "points_so_far", "attacker_points")
    parts: dict[str, list[np.ndarray]] = {name: [] for name in columns}
    encoders = set()
    for path in cache_files:
        meta = check_meta(read_meta(path), path=path,
                          shard_sha256=(expected_shards or {}).get(str(path)))
        encoders.add(meta["encoder"]["implementation_sha256"])
        for name in columns:
            parts[name].append(np.asarray(read_column(path, name)))
    if not parts["deal_key"]:
        raise LeafError("no cache files to fit the points prior on")
    arrays = {name: np.concatenate(chunks) for name, chunks in parts.items()}
    keys = np.unique(arrays["deal_key"].astype(str))
    assignment = split_deals(keys.tolist(), seed=int(split_seed), val_fraction=val_fraction,
                             test_fraction=test_fraction)
    mask = np.isin(arrays["deal_key"].astype(str), part_keys(assignment, part))
    if not mask.any():
        raise LeafError(f"no {part} rows in the cache files")
    prior = StratifiedPrior()
    prior.add(arrays["ply"][mask], arrays["role_attacker"][mask],
              arrays["points_so_far"][mask], arrays["attacker_points"][mask])
    counts = {p: int(sum(1 for v in assignment.values() if v == p)) for p in ("train", "val", "test")}
    return StratifiedPointsPrior(prior.sums, prior.counts, provenance={
        "fitted_on": part,
        "split": {"seed": int(split_seed), "val_fraction": float(val_fraction),
                  "test_fraction": float(test_fraction),
                  "method": "split_deals: rank of sha256(seed|deal_key)"},
        "deals": counts,
        "rows": {"total": int(mask.size), part: int(mask.sum())},
        "cache_files": len(list(cache_files)),
        "encoder_implementation_sha256": sorted(encoders),
    })


# ------------------------------------------------------------------- leaves

class LearnedPointsLeaf:
    """The points head, encoded from the clone's seat to act."""

    kind = "learned"

    def __init__(self, head: PointsHead):
        self.head = head

    def final_attacker_points(self, clone: Round, seat: int) -> float:
        return self.head.final_attacker_points(encode_obs(clone, seat))

    def describe(self) -> dict:
        meta = self.head.metadata
        sha = meta.get("checkpoint_sha256")
        return {"kind": self.kind, "checkpoint_sha256": sha,
                "checkpoint_id": sha[:8] if isinstance(sha, str) else None,
                "epoch": meta.get("epoch"), "schema": meta.get("schema"),
                "legacy": meta.get("legacy"), "held_out_claim": False,
                "target": "final attacker points (points head, column 1 x 100)"}


class CompleteWorldPointsLeaf:
    """The complete-world points head on the determinized clone, from the
    clone's seat to act.  ``encode_secs`` / ``forward_secs`` split the
    per-leaf cost (tensors vs numpy MLP) for the profile."""

    kind = "cwv"

    def __init__(self, head: CompleteWorldPointsHead):
        self.head = head
        self.encode_secs = 0.0
        self.forward_secs = 0.0

    def final_attacker_points(self, clone: Round, seat: int) -> float:
        t0 = perf_counter()
        inputs = cwv_leaf_inputs(clone, seat)
        t1 = perf_counter()
        value = self.head.final_attacker_points(inputs)
        self.forward_secs += perf_counter() - t1
        self.encode_secs += t1 - t0
        return value

    def describe(self) -> dict:
        meta = self.head.metadata
        sha = meta.get("checkpoint_sha256")
        enc = meta.get("encoder") or {}
        return {"kind": self.kind, "leaf_model": "cwv", "checkpoint_sha256": sha,
                "checkpoint_id": sha[:8] if isinstance(sha, str) else None,
                "epoch": meta.get("epoch"), "schema": meta.get("schema"),
                "arch": meta.get("arch"), "sees_hidden_hands": meta.get("sees_hidden_hands"),
                "encoder_implementation_sha256": enc.get("implementation_sha256"),
                "held_out_claim": False,
                "target": ("final attacker points (complete-world aux points head x 100 on "
                           "the determinized clone)")}


class PriorPointsLeaf:
    """The stratified points prior at the clone's seat to act."""

    kind = "prior"

    def __init__(self, table: StratifiedPointsPrior):
        self.table = table

    def final_attacker_points(self, clone: Round, seat: int) -> float:
        return self.table.predict(leaf_ply(clone), clone.is_attacker(seat),
                                  clone.attacker_points)

    def describe(self) -> dict:
        p = self.table.provenance
        return {"kind": self.kind, "file_sha256": p.get("file_sha256"),
                "fitted_on": p.get("fitted_on"), "rows": p.get("rows"),
                "n": self.table.n, "global_mean": self.table.prior.global_mean,
                "held_out_claim": False,
                "target": "final attacker points (stratified prior, 18 cells)"}


# ---------------------------------------------------------------------- bot

#: where the leaf is consulted: ``all`` = every rollout (selection and
#: report fold); ``report`` = only inside ``_report_fold_gap`` (the top two
#: candidates on the R paired worlds), selection rollouts run to round end
#: exactly as production's.
LEAF_STAGES = VLEAF_LEAF_STAGES
#: how the leaf's estimate enters the value: ``replace`` = the rollout stops
#: at the horizon and returns the estimate; ``control-variate`` = the rollout
#: runs to round end and the estimate is a centred control variate (below).
LEAF_MODES = VLEAF_LEAF_MODES
DEFAULT_CV_BETA = 1.0


def policy_suffix(*, leaf_stage: str = "all", leaf_mode: str = "replace",
                  beta: float = DEFAULT_CV_BETA) -> str:
    """``-report`` / ``-cv`` (``-cv-b<beta>`` off the default) after ``-t<T>``."""
    return vleaf_policy_suffix(leaf_stage=leaf_stage, leaf_mode=leaf_mode, beta=beta)


class MCValueLeafSearch(REGISTRY[VLEAF_BASE_POLICY]):
    """Production search; ``_rollout`` is overridden (module docstring), and
    ``_report_fold_gap`` / ``decide_play`` only to scope the leaf to a stage
    and to apply the control variate:

    * ``leaf_stage="report"``: ``_rollout`` consults ``_leaf_on()``; the flag
      is raised for the duration of ``_report_fold_gap`` (delegating to
      production's) and is down during selection, whose rollouts therefore
      run to round end untouched (values byte-identical to production's).
    * ``leaf_mode="control-variate"``: the rollout runs to round end as
      production does and buffers the net's estimate ``X`` of that world at
      the horizon; when a candidate's batch of worlds completes the value is
      ``Y - beta * (X - mean_c X)`` with the mean over that candidate's worlds
      of the batch.  The centring sums to zero, so per-candidate means and
      the paired gap are production's exactly; only the paired SE changes
      (``_cv_report_fold``), hence the LCB rule's statistic.
    """

    LEAF_TRICKS = 1

    def __init__(self, leaf, *, seed: int | None = None, leaf_tricks: int = 1,
                 leaf_stage: str = "all", leaf_mode: str = "replace",
                 beta: float = DEFAULT_CV_BETA):
        super().__init__(seed)
        # The registry names cover SUPPORTED_LEAF_TRICKS; the class accepts any
        # horizon so a horizon beyond the round is the identity witness.
        if type(leaf_tricks) is not int or leaf_tricks < 0:
            raise LeafError("leaf_tricks must be a non-negative integer")
        if not callable(getattr(leaf, "final_attacker_points", None)):
            raise LeafError("leaf must provide final_attacker_points(clone, seat)")
        if leaf_stage not in LEAF_STAGES:
            raise LeafError(f"leaf_stage must be one of {LEAF_STAGES}, got {leaf_stage!r}")
        if leaf_mode not in LEAF_MODES:
            raise LeafError(f"leaf_mode must be one of {LEAF_MODES}, got {leaf_mode!r}")
        if isinstance(beta, bool) or not isinstance(beta, (int, float)) or not math.isfinite(beta):
            raise LeafError("beta must be a finite number")
        self.LEAF_TRICKS = leaf_tricks
        self.leaf = leaf
        self.leaf_stage = leaf_stage
        self.leaf_mode = leaf_mode
        self.beta = float(beta)
        self.policy_name = (f"{VLEAF_BASE_POLICY}+vleaf-{leaf.kind}-t{leaf_tricks}"
                            + policy_suffix(leaf_stage=leaf_stage, leaf_mode=leaf_mode,
                                            beta=self.beta))
        # Cumulative, like MCBot's own counters: leaf_calls == rollouts scored,
        # and terminal + exact + predicted == leaf_calls.
        self.leaf_counts = {"leaf_calls": 0, "terminal_leaves": 0, "exact_leaves": 0,
                            "predicted_leaves": 0, "leaf_plies": 0}
        # Net calls by stage (a control-variate call is a net call that did
        # not replace the leaf: it is counted here, never in predicted_leaves).
        self.stage_counts = {"selection_net_calls": 0, "report_net_calls": 0,
                             "control_variate_calls": 0}
        self.leaf_secs = 0.0
        self._leaf_active = leaf_stage == "all"
        self._in_report_fold = False
        # control variate: (candidate key -> [X or None per rollout, in order]);
        # the offsets say where the report fold's entries start
        self._cv_buffer: dict[tuple[str, ...], list[float | None]] = {}
        self._cv_report_offsets: dict[tuple[str, ...], int] = {}
        self.last_control_variate = None

    # ------------------------------------------------------------- stages

    def _leaf_on(self) -> bool:
        """Whether this rollout may consult the leaf (the stage flag)."""
        return self._leaf_active

    def _report_fold_gap(self, rnd, seat, mem, i_attack, cand_a, cand_b, n,
                         *, seed: int, keep_deltas: bool = False):
        """Production's report fold with the leaf flag raised for its duration."""
        was_active, was_report = self._leaf_active, self._in_report_fold
        self._leaf_active = True
        self._in_report_fold = True
        try:
            if self.leaf_mode == "control-variate":
                return self._cv_report_fold(rnd, seat, mem, i_attack, cand_a, cand_b, n,
                                            seed=seed, keep_deltas=keep_deltas)
            return super()._report_fold_gap(rnd, seat, mem, i_attack, cand_a, cand_b, n,
                                            seed=seed, keep_deltas=keep_deltas)
        finally:
            self._leaf_active, self._in_report_fold = was_active, was_report

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        if self.leaf_mode != "control-variate":
            return super().decide_play(rnd, seat)
        self._cv_buffer = {}
        self._cv_report_offsets = {}
        self.last_control_variate = None
        try:
            return super().decide_play(rnd, seat)
        finally:
            record = self.last_decision_record
            if record is not None:
                record["control_variate"] = self._cv_decision_summary(record)
            self._cv_buffer = {}

    # ---------------------------------------------------------- control variate

    @staticmethod
    def _cv_centred(values: Sequence[float | None]) -> tuple[list[float], float | None]:
        """``X - mean(X)`` over one candidate's batch (0.0 where the rollout
        never reached the horizon: no estimate, no correction); the sum of the
        corrections is zero by construction."""
        known = [x for x in values if x is not None]
        if not known:
            return [0.0] * len(values), None
        mean = math.fsum(known) / len(known)
        return [0.0 if x is None else x - mean for x in values], mean

    def _cv_report_fold(self, rnd, seat, mem, i_attack, cand_a, cand_b, n, *, seed, keep_deltas):
        """The control variate applied where the report fold forms its paired
        gap: production's fold runs unchanged (same draws, same rollouts, the
        buffered X per rollout), then each candidate's centred correction is
        subtracted from its per-world value and the paired SE is recomputed
        from the corrected deltas.  The gap is production's: the corrections
        sum to zero per candidate."""
        key_a, key_b = tuple(cand_a), tuple(cand_b)
        before = {k: len(self._cv_buffer.get(k, ())) for k in (key_a, key_b)}
        out = super()._report_fold_gap(rnd, seat, mem, i_attack, cand_a, cand_b, n,
                                       seed=seed, keep_deltas=True)
        deltas = out["deltas"]
        used = out["worlds"]
        xa = self._cv_buffer.get(key_a, [])[before[key_a]:]
        xb = self._cv_buffer.get(key_b, [])[before[key_b]:]
        if len(xa) != used or len(xb) != used or len(deltas) != used:
            raise LeafError("control variate: buffered estimates do not match the report worlds")
        self._cv_report_offsets = dict(before)
        ca, mean_a = self._cv_centred(xa)
        cb, mean_b = self._cv_centred(xb)
        sign = 1.0 if i_attack else -1.0
        beta = self.beta
        # values were sign-flipped to the acting team before pairing; so is X
        corrected = [d - beta * sign * (a - b) for d, a, b in zip(deltas, ca, cb)]
        d_sum = math.fsum(corrected)
        d_sq = math.fsum(c * c for c in corrected)
        raw_se = out["se"]
        se = self._paired_se(d_sum, d_sq, used)
        # The gap stays production's: each candidate's corrections sum to
        # zero (correction_sum witnesses it), so the corrected paired mean is
        # the raw paired mean up to float residue.
        out["se"] = se
        out["control_variate"] = {
            "beta": beta, "worlds": used,
            "net_calls": {"a": sum(x is not None for x in xa), "b": sum(x is not None for x in xb)},
            "mean_estimate": {"a": mean_a, "b": mean_b},
            "correction_sum": {"a": math.fsum(beta * c for c in ca),
                               "b": math.fsum(beta * c for c in cb)},
            "max_abs_correction": max((abs(beta * c) for c in (*ca, *cb)), default=0.0),
            "gap_from_corrected": d_sum / used if used else 0.0,
            "raw_se": raw_se, "se": se,
            "variance_ratio": ((se / raw_se) ** 2 if raw_se and math.isfinite(raw_se)
                               and math.isfinite(se) else None),
        }
        if keep_deltas:
            out["raw_deltas"] = deltas
            out["deltas"] = corrected
        else:
            del out["deltas"]
        return out

    def _cv_decision_summary(self, record: dict) -> dict:
        """Per-candidate centring facts of the selection stage (its means are
        invariant under the centred correction, so nothing is rewritten) plus
        the report fold's correction."""
        selection = {}
        for cand in record.get("candidates", []):
            key = tuple(cand)
            xs = self._cv_buffer.get(key, [])[:self._cv_report_offsets.get(key, None)]
            _, mean = self._cv_centred(xs)
            selection[" ".join(cand)] = {"rollouts": len(xs),
                                         "net_calls": sum(x is not None for x in xs),
                                         "mean_estimate": mean}
        report = (record.get("report_fold") or {}).get("control_variate")
        return {"beta": self.beta, "leaf_stage": self.leaf_stage,
                "selection_means_unchanged": True, "selection": selection, "report": report}

    # ------------------------------------------------------------- rollout

    def _rollout(self, rnd: Round, seat: int, sampled: dict[int, list[str]],
                 buried: list[str], candidate: list[str], *,
                 exact_session=None) -> float:
        # Clone construction: MCBot._rollout, byte for byte.
        clone: Round = copy.copy(rnd)
        clone.hands = self._complete_determinized_hands(
            rnd, seat, sampled, buried=buried)
        clone.buried = sorted(buried)
        assert rnd.trick is not None
        clone.trick = Trick(
            leader=rnd.trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
        clone.history = list(rnd.history)
        clone.last_trick = rnd.last_trick
        clone.message = None
        clone._trusted_rollout = True  # skip follow re-validation (audit)
        clone._determinized_world = True
        clone.play(seat, list(candidate))
        policy = self.rollout_policy
        _exact_on = self.EXACT_ENDGAME
        counts = self.leaf_counts
        counts["leaf_calls"] += 1
        leaf_on = self._leaf_on()
        # A stage whose leaf is off runs to round end: production's loop.
        horizon = self._leaf_horizon(rnd) if leaf_on else None
        control_variate = leaf_on and self.leaf_mode == "control-variate"
        buffer = self._cv_buffer.setdefault(tuple(candidate), []) if control_variate else None
        estimate = None
        stage = "report_net_calls" if self._in_report_fold else "selection_net_calls"
        while clone.phase == "play":
            exact = (self._exact_endgame_value(clone, exact_session)
                     if _exact_on else None)
            if exact is not None:
                counts["exact_leaves"] += 1
                if buffer is not None:
                    buffer.append(estimate)
                return exact
            if horizon is not None and len(clone.history) >= horizon:
                if buffer is None:
                    counts["predicted_leaves"] += 1
                    self.stage_counts[stage] += 1
                    return self._leaf_value(clone)
                # control variate: the estimate, in the units the caller
                # scores the playout in, is buffered and the playout goes on
                estimate = self._score(self._leaf_value(clone))
                self.stage_counts[stage] += 1
                self.stage_counts["control_variate_calls"] += 1
                horizon = None
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
            counts["leaf_plies"] += 1
        counts["terminal_leaves"] += 1
        if buffer is not None:
            buffer.append(estimate)
        return self._terminal_value(clone)

    @staticmethod
    def _terminal_value(clone: Round) -> float:
        """A leaf that reached round end: production's value, never the head."""
        return float(clone.attacker_points)

    def _leaf_horizon(self, rnd: Round) -> int:
        """Resolved tricks at which the continuation stops: T beyond the root."""
        return len(rnd.history) + self.LEAF_TRICKS

    def _leaf_value(self, clone: Round) -> float:
        """The leaf's final-attacker-points prediction from the clone's seat
        to act (production's rollout units)."""
        seat = clone.turn
        assert seat is not None
        started = perf_counter()
        try:
            return self.leaf.final_attacker_points(clone, seat)
        finally:
            self.leaf_secs += perf_counter() - started


# ------------------------------------------------------------- construction

@lru_cache(maxsize=4)
def load_points_head(path: str, allow_legacy: bool = False) -> PointsHead:
    """Once per process: the checkpoint's points head as numpy weights."""
    return PointsHead.from_checkpoint(path, allow_legacy=allow_legacy)


@lru_cache(maxsize=4)
def load_cwv_points_head(path: str) -> CompleteWorldPointsHead:
    """Once per process: the complete-world checkpoint's trunk + aux head as numpy."""
    return CompleteWorldPointsHead.from_checkpoint(path)


@lru_cache(maxsize=4)
def load_points_prior(path: str) -> StratifiedPointsPrior:
    return StratifiedPointsPrior.from_json(path)


def load_leaf_head(checkpoint: str | os.PathLike, *, leaf_model: str = "public",
                   allow_legacy: bool = False):
    """The points head named by ``leaf_model``; refuses an unknown model."""
    if leaf_model not in LEAF_MODELS:
        raise LeafError(f"leaf_model must be one of {LEAF_MODELS}, got {leaf_model!r}")
    path = str(Path(checkpoint).resolve())
    if leaf_model == "cwv":
        return load_cwv_points_head(path)
    try:
        return load_points_head(path, bool(allow_legacy))
    except LeafError:
        raise
    except ValueError as exc:       # SearchHeads' schema / encoder refusals
        raise LeafError(f"public checkpoint refused: {exc}") from exc


def make_learned_leaf(head):
    if isinstance(head, CompleteWorldPointsHead):
        return CompleteWorldPointsLeaf(head)
    return LearnedPointsLeaf(head)


def make_vleaf_bot(*, checkpoint: str | os.PathLike, leaf_tricks: int = 1,
                   seed: int | None = None, allow_legacy: bool = False,
                   expected_sha256: str | None = None,
                   leaf_model: str = "public", leaf_stage: str = "all",
                   leaf_mode: str = "replace", beta: float = DEFAULT_CV_BETA) -> MCValueLeafSearch:
    head = load_leaf_head(checkpoint, leaf_model=leaf_model, allow_legacy=allow_legacy)
    actual = head.metadata.get("checkpoint_sha256")
    if expected_sha256 is not None and actual != expected_sha256:
        raise RuntimeError(f"checkpoint {checkpoint} changed since registration: "
                           f"{actual} != {expected_sha256}")
    return MCValueLeafSearch(make_learned_leaf(head), seed=seed, leaf_tricks=leaf_tricks,
                             leaf_stage=leaf_stage, leaf_mode=leaf_mode, beta=beta)


def make_vleaf_prior_bot(*, prior: str | os.PathLike, leaf_tricks: int = 1,
                         seed: int | None = None,
                         expected_sha256: str | None = None, leaf_stage: str = "all",
                         leaf_mode: str = "replace", beta: float = DEFAULT_CV_BETA) -> MCValueLeafSearch:
    table = load_points_prior(str(Path(prior).resolve()))
    actual = table.provenance.get("file_sha256")
    if expected_sha256 is not None and actual != expected_sha256:
        raise RuntimeError(f"points prior {prior} changed since registration: "
                           f"{actual} != {expected_sha256}")
    return MCValueLeafSearch(PriorPointsLeaf(table), seed=seed, leaf_tricks=leaf_tricks,
                             leaf_stage=leaf_stage, leaf_mode=leaf_mode, beta=beta)


def leaf_record(bot) -> dict:
    """Cumulative leaf telemetry of one bot (zeros for a production bot)."""
    counts = dict(getattr(bot, "leaf_counts", None) or {})
    leaf = getattr(bot, "leaf", None)
    return {
        "schema": LEAF_RECORD_SCHEMA,
        "leaf": leaf.describe() if leaf is not None else None,
        "leaf_tricks": getattr(bot, "LEAF_TRICKS", None) if leaf is not None else None,
        "leaf_stage": getattr(bot, "leaf_stage", None) if leaf is not None else None,
        "leaf_mode": getattr(bot, "leaf_mode", None) if leaf is not None else None,
        "beta": getattr(bot, "beta", None) if leaf is not None else None,
        "counts": counts,
        "stage_counts": dict(getattr(bot, "stage_counts", None) or {}),
        "leaf_secs": float(getattr(bot, "leaf_secs", 0.0)),
        "leaf_encode_secs": float(getattr(leaf, "encode_secs", 0.0)),
        "leaf_forward_secs": float(getattr(leaf, "forward_secs", 0.0)),
    }
