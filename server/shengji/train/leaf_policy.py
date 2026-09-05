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

Two leaf evaluators share the truncation:

* :class:`LearnedPointsLeaf` — the checkpoint's auxiliary points head
  (``model.py``: ``value_head`` column 1, trained on ``attacker_points / 100``),
  exported once per process to numpy and run single-row (torch per-call
  overhead is too high inside the rollout loop).
* :class:`PriorPointsLeaf` — the NO-LEARNING control: the stratified prior
  the trainer fits on the training rows (phase x role x attacker points so
  far, 18 cells; ``baselines.py``) refitted on the FINAL attacker points
  target.  Identical truncation and world dose, so a learned-minus-prior
  difference isolates "learned leaf" from "truncation + more worlds".

A checkpoint without a points head is refused; identity checks (encoder
SHA, checkpoint schema) go through ``SearchHeads.from_checkpoint``.  Nothing
here registers a production default.
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

from ..ai.registry import (REGISTRY, VLEAF_BASE_POLICY, VLEAF_LEAF_TRICKS,
                           vleaf_checkpoint_sha256)
from ..engine.round import Round, Trick, TrickPlay
from ..rl.encode import encode_obs
from .baselines import N_STRATA, POINT_BINS, ROLES, StratifiedPrior
from .data import PLAYS_PER_ROUND, check_meta, part_keys, read_column, read_meta, split_deals

LEAF_RECORD_SCHEMA = "vleaf-leaf-v1"
POINTS_PRIOR_SCHEMA = "vleaf-points-prior-v1"
#: the aux points head is trained on ``attacker_points / POINTS_SCALE`` (model.py)
POINTS_SCALE = 100.0
SUPPORTED_LEAF_TRICKS = VLEAF_LEAF_TRICKS


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

class MCValueLeafSearch(REGISTRY[VLEAF_BASE_POLICY]):
    """Production search; ONLY ``_rollout`` is overridden (module docstring)."""

    LEAF_TRICKS = 1

    def __init__(self, leaf, *, seed: int | None = None, leaf_tricks: int = 1):
        super().__init__(seed)
        # The registry names cover SUPPORTED_LEAF_TRICKS; the class accepts any
        # horizon so a horizon beyond the round is the identity witness.
        if type(leaf_tricks) is not int or leaf_tricks < 0:
            raise LeafError("leaf_tricks must be a non-negative integer")
        if not callable(getattr(leaf, "final_attacker_points", None)):
            raise LeafError("leaf must provide final_attacker_points(clone, seat)")
        self.LEAF_TRICKS = leaf_tricks
        self.leaf = leaf
        self.policy_name = f"{VLEAF_BASE_POLICY}+vleaf-{leaf.kind}-t{leaf_tricks}"
        # Cumulative, like MCBot's own counters: leaf_calls == rollouts scored,
        # and terminal + exact + predicted == leaf_calls.
        self.leaf_counts = {"leaf_calls": 0, "terminal_leaves": 0, "exact_leaves": 0,
                            "predicted_leaves": 0, "leaf_plies": 0}
        self.leaf_secs = 0.0

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
        horizon = self._leaf_horizon(rnd)
        counts = self.leaf_counts
        counts["leaf_calls"] += 1
        while clone.phase == "play":
            exact = (self._exact_endgame_value(clone, exact_session)
                     if _exact_on else None)
            if exact is not None:
                counts["exact_leaves"] += 1
                return exact
            if len(clone.history) >= horizon:
                counts["predicted_leaves"] += 1
                return self._leaf_value(clone)
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
            counts["leaf_plies"] += 1
        counts["terminal_leaves"] += 1
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
def load_points_prior(path: str) -> StratifiedPointsPrior:
    return StratifiedPointsPrior.from_json(path)


def make_vleaf_bot(*, checkpoint: str | os.PathLike, leaf_tricks: int = 1,
                   seed: int | None = None, allow_legacy: bool = False,
                   expected_sha256: str | None = None) -> MCValueLeafSearch:
    head = load_points_head(str(Path(checkpoint).resolve()), bool(allow_legacy))
    actual = head.metadata.get("checkpoint_sha256")
    if expected_sha256 is not None and actual != expected_sha256:
        raise RuntimeError(f"checkpoint {checkpoint} changed since registration: "
                           f"{actual} != {expected_sha256}")
    return MCValueLeafSearch(LearnedPointsLeaf(head), seed=seed, leaf_tricks=leaf_tricks)


def make_vleaf_prior_bot(*, prior: str | os.PathLike, leaf_tricks: int = 1,
                         seed: int | None = None,
                         expected_sha256: str | None = None) -> MCValueLeafSearch:
    table = load_points_prior(str(Path(prior).resolve()))
    actual = table.provenance.get("file_sha256")
    if expected_sha256 is not None and actual != expected_sha256:
        raise RuntimeError(f"points prior {prior} changed since registration: "
                           f"{actual} != {expected_sha256}")
    return MCValueLeafSearch(PriorPointsLeaf(table), seed=seed, leaf_tricks=leaf_tricks)


def leaf_record(bot) -> dict:
    """Cumulative leaf telemetry of one bot (zeros for a production bot)."""
    counts = dict(getattr(bot, "leaf_counts", None) or {})
    leaf = getattr(bot, "leaf", None)
    return {
        "schema": LEAF_RECORD_SCHEMA,
        "leaf": leaf.describe() if leaf is not None else None,
        "leaf_tricks": getattr(bot, "LEAF_TRICKS", None) if leaf is not None else None,
        "counts": counts,
        "leaf_secs": float(getattr(bot, "leaf_secs", 0.0)),
    }
