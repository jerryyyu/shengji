"""Complete-world value evaluator and the one-ply bot that uses it.

The bridge from model to policy (Jerry, 2026-09-04): a value net that sees
the SAMPLED hidden hands is the ENTIRE evaluator -- no playouts.  For every
play decision the bot enumerates production's ballot, samples W complete
worlds with production's sampler, applies every candidate in every world
(optionally letting the heuristic finish only the CURRENT trick), and scores
all W x |ballot| reached positions in one batched forward pass from the root
seat's team perspective.  ``score(a) = mean_w V`` and the bot plays argmax.

Everything a checkpoint needs is consumed through the merged #214 API only:
``value_checkpoint.load_checkpoint``, ``value_afterstate.tensors_from_round``
and ``terminal_distribution``, ``value_metrics.category_signed_level``.  This
module owns batching (stack tensors, one forward per call), the encoder
identity gate, the no-learning stratified-prior control and the registry
factories.  It never edits or bypasses ``shengji/rl/value_*.py``.

Stable consumer API (kept minimal for other arms -- e.g. a hybrid that
shortlists candidates on many cheap worlds with this evaluator and then hands
the shortlist to production's full-rollout report fold):

    evaluator = shared_evaluator(checkpoint)            # one per process
    worlds, attempts = sample_worlds(mc_bot, rnd, seat, W)
        # W canonicalised complete worlds ``(hands, buried)`` through
        # production's sampler on ANY MCBot instance (its rng, its counters)
    positions = positions_from_candidates(rnd, seat, candidates, worlds,
                                          finish_trick=True)
        # every (world, candidate) afterstate, WORLD-MAJOR: index
        # ``w * len(candidates) + k``; reshape (len(worlds), len(candidates))
    values = evaluator.score(positions, seat)            # np.ndarray float64
        # expected signed level from ``seat``'s TEAM perspective, ONE batch;
        # terminal positions are exact and never touch the model

Checkpoint metadata contract (the training build, claude/cwv-train, writes
``metadata["encoder"] = shengji.train.cwv_data.cwv_encoder_identity()``):
the checkpoint must declare the afterstate encoder it was trained against.
:func:`afterstate_encoder_identity` is that recipe -- schema
``shengji-cwv-encoder-identity-v1`` over the executable closure of
``tensors_from_round`` (nine source files) -- and imports the training
module's function once the branches are merged so there is one source of
truth.  Accepted declarations, any one of which must equal the live
``implementation_sha256`` (or, for hand-made checkpoints, the sha256 of
``value_afterstate.py`` itself):

    metadata["encoder"]            = {"implementation_sha256": <sha>, ...} | <sha>
    metadata["encoder_identity"]   = {"implementation_sha256": <sha>, ...} | <sha>
    metadata["afterstate_encoder"] = <sha>

A checkpoint without any of these is foreign and is refused; so is one whose
declared sha matches neither (the refusal names the drifted source files
when the declaration carries ``source_sha256s``).  A no-learning control
reads its stratified prior table from ``metadata["stratified_prior"]`` or
from a receipt JSON.  The training build's ``mlp`` architecture ignores the
history tensor, so the evaluator feeds it a one-row history instead of the
padded sequence; the sequence architectures receive the full history.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.combos import decompose
from ..engine.round import Round, Trick, TrickPlay
from ..rl.value_afterstate import (
    AFTERSTATE_SCHEMA,
    OUTCOME_CLASSES,
    ValueAfterstateTensors,
    category_signed_level,
    phase_for_ply,
    tensors_from_round,
    terminal_distribution,
)
from .mcbot import MCBot, _ballot_identity, _runtime_identity
from .memory import Memory


CWV_DECISION_SCHEMA = "cwv-decision-v1"
#: The training build's identity schema (``shengji.train.cwv_data``); the
#: recipe below reproduces it byte for byte until the branches merge.
AFTERSTATE_IDENTITY_SCHEMA = "shengji-cwv-encoder-identity-v1"
PRIOR_STRATA = tuple(f"{phase}|{role}" for phase in ("early", "middle", "late")
                     for role in ("attacker", "defender"))

_SHENGJI = Path(__file__).resolve().parents[1]
#: The executable closure of ``tensors_from_round`` and the training bridge
#: (the same nine files as ``cwv_data.CWV_SOURCE_PATHS``): the afterstate
#: module, the public observation encoder and its Memory, the public-history
#: encoder, the card/combo/round engine and the record rebuild/utility
#: helpers.  Editing any of these changes what a checkpoint is scored on, so
#: it changes the identity a checkpoint must carry.
AFTERSTATE_SOURCE_PATHS = {
    "value_afterstate": _SHENGJI / "rl" / "value_afterstate.py",
    "encode": _SHENGJI / "rl" / "encode.py",
    "douzero_micro": _SHENGJI / "rl" / "douzero_micro.py",
    "memory": _SHENGJI / "ai" / "memory.py",
    "cards": _SHENGJI / "engine" / "cards.py",
    "combos": _SHENGJI / "engine" / "combos.py",
    "round": _SHENGJI / "engine" / "round.py",
    "rebuild": _SHENGJI / "harvest" / "rebuild.py",
    "teacher_v1": _SHENGJI / "teacher_v1.py",
}


class CWVError(RuntimeError):
    """A checkpoint, evaluator batch, prior table or decision drifted."""


class CWVCheckpointMismatch(CWVError):
    """The checkpoint is foreign or was trained against another encoder."""


# ------------------------------------------------------------------ identity

def file_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_encoder_identity() -> dict[str, Any]:
    """This module's replica of the training build's identity recipe."""
    sources = {name: file_sha256(path)
               for name, path in AFTERSTATE_SOURCE_PATHS.items()}
    payload = "|".join(
        [AFTERSTATE_IDENTITY_SCHEMA, AFTERSTATE_SCHEMA]
        + [f"{name}:{digest}" for name, digest in sorted(sources.items())])
    return {
        "identity_schema": AFTERSTATE_IDENTITY_SCHEMA,
        "afterstate_schema": AFTERSTATE_SCHEMA,
        "implementation_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(),
        "source_sha256s": sources,
    }


def afterstate_encoder_identity() -> dict[str, Any]:
    """Rehash the afterstate encoder's executable closure on every call.

    Once the training build is merged its ``cwv_encoder_identity`` is the
    single source of truth and is used directly; until then the local
    replica (same schema, same nine files, same payload) stands in.
    """
    try:
        from ..train.cwv_data import cwv_encoder_identity
    except ImportError:
        return local_encoder_identity()
    identity = dict(cwv_encoder_identity())
    if identity.get("identity_schema") != AFTERSTATE_IDENTITY_SCHEMA \
            or not isinstance(identity.get("implementation_sha256"), str) \
            or not isinstance(identity.get("source_sha256s"), Mapping):
        raise CWVError("the training build's encoder identity schema drifted")
    return identity


_DECLARATION_KEYS = ("implementation_sha256", "afterstate_sha256",
                     "value_afterstate_sha256", "sha256", "identity")


def _sha_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [inner for key, inner in value.items()
                if key in _DECLARATION_KEYS and isinstance(inner, str)]
    return []


def _declared_sources(metadata: Mapping[str, Any]) -> Mapping[str, str]:
    for key in ("encoder", "encoder_identity", "afterstate_encoder_identity"):
        value = metadata.get(key)
        if isinstance(value, Mapping) and isinstance(value.get("source_sha256s"), Mapping):
            return value["source_sha256s"]
    return {}


def declared_encoder_shas(metadata: Mapping[str, Any]) -> list[str]:
    """Every encoder sha a checkpoint's metadata declares (possibly none)."""
    found: list[str] = []
    for key in ("encoder", "encoder_identity", "afterstate_encoder",
                "afterstate_encoder_identity", "encoder_sha256"):
        found.extend(_sha_values(metadata.get(key)))
    return [sha for sha in found if isinstance(sha, str) and sha]


def verify_checkpoint_identity(metadata: Mapping[str, Any], *,
                               path: str | os.PathLike[str] | None = None,
                               identity: Mapping[str, Any] | None = None) -> str:
    """Refuse a foreign checkpoint or an encoder mismatch; return the match."""
    current = dict(identity if identity is not None
                   else afterstate_encoder_identity())
    accepted = {current["implementation_sha256"],
                current["source_sha256s"]["value_afterstate"]}
    declared = declared_encoder_shas(metadata)
    label = f"{path}: " if path is not None else ""
    if not declared:
        raise CWVCheckpointMismatch(
            f"{label}checkpoint carries no afterstate encoder identity; "
            "refusing a foreign checkpoint (expected metadata['encoder']"
            "['implementation_sha256'])")
    for sha in declared:
        if sha in accepted:
            return sha
    drifted = sorted(
        name for name, sha in _declared_sources(metadata).items()
        if name in current["source_sha256s"] and current["source_sha256s"][name] != sha)
    detail = (f"; drifted sources: {', '.join(drifted)}" if drifted else "")
    raise CWVCheckpointMismatch(
        f"{label}checkpoint encoder identity {[s[:12] for s in declared]} "
        f"matches neither the afterstate encoder "
        f"{current['implementation_sha256'][:12]} nor value_afterstate.py "
        f"{current['source_sha256s']['value_afterstate'][:12]}; a net may "
        f"only score the encoding it was trained on{detail}")


@lru_cache(maxsize=8)
def _cached_checkpoint(path: str, mtime_ns: int, size: int):
    del mtime_ns, size            # part of the key: a replaced file reloads
    from ..rl.value_checkpoint import load_checkpoint
    model, metadata = load_checkpoint(path, map_location="cpu")
    verify_checkpoint_identity(metadata, path=path)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model, metadata, file_sha256(path)


def load_cwv_checkpoint(path: str | os.PathLike[str]):
    """``(model, metadata, file_sha256)`` through #214's loader, gated."""
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise CWVError(f"checkpoint not found: {resolved}")
    stat = resolved.stat()
    return _cached_checkpoint(str(resolved), stat.st_mtime_ns, stat.st_size)


def checkpoint_id(path: str | os.PathLike[str]) -> str:
    """``<ckpt8>``: the first eight hex digits of the file's sha256."""
    return file_sha256(path)[:8]


# ----------------------------------------------------------------- evaluator

def _stack(rows: Sequence[ValueAfterstateTensors], *, history_free: bool = False):
    """Stack validated afterstate tensors into one padded torch batch.

    ``history_free`` (the ``mlp`` architecture, which never reads the
    history) sends a one-row zero history with a true mask instead of the
    padded sequence: same public/world/perspective bytes, none of the
    ``rows x 100 x 64`` allocation.
    """
    import torch

    width = rows[0].history.shape[1]
    if history_free:
        history = np.zeros((len(rows), 1, width), dtype=np.float32)
        mask = np.ones((len(rows), 1), dtype=np.bool_)
    else:
        length = max(len(row.history) for row in rows)
        history = np.zeros((len(rows), length, width), dtype=np.float32)
        mask = np.zeros((len(rows), length), dtype=np.bool_)
        for index, row in enumerate(rows):
            n = len(row.history)
            history[index, :n] = row.history
            mask[index, :n] = True
    return (torch.from_numpy(np.stack([row.public for row in rows])),
            torch.from_numpy(history), torch.from_numpy(mask),
            torch.from_numpy(np.stack([row.world for row in rows])),
            torch.from_numpy(np.stack([row.perspective for row in rows])))


def _plays_so_far(rnd: Round) -> int:
    count = sum(len(trick.plays) for trick in rnd.history)
    if rnd.trick is not None:
        count += len(rnd.trick.plays)
    return count


def position_stratum(rnd: Round, root_seat: int) -> str:
    """``phase|role`` of a reached position, as value_afterstate strata it."""
    role = "attacker" if rnd.is_attacker(root_seat) else "defender"
    return f"{phase_for_ply(max(1, _plays_so_far(rnd)))}|{role}"


class CompleteWorldEvaluator:
    """Batched expected signed level of complete rounds, one forward per call.

    ``score(positions, root_seat)`` returns a float64 array aligned with
    ``positions``; every value is the expected signed level from
    ``root_seat``'s TEAM perspective.  Terminal positions never touch the
    model: they take ``terminal_distribution`` exactly.
    """

    backend = "torch"

    def __init__(self, checkpoint: str | os.PathLike[str] | None, *,
                 device: str = "cpu", threads: int | None = 1,
                 max_batch: int = 4096, model=None,
                 metadata: Mapping[str, Any] | None = None):
        import torch

        if model is None:
            if checkpoint is None:
                raise CWVError("an evaluator needs a checkpoint or a model")
            model, metadata, sha = load_cwv_checkpoint(checkpoint)
            self.checkpoint_path = str(Path(checkpoint).resolve())
            self.checkpoint_sha256 = sha
        else:
            self.checkpoint_path = None if checkpoint is None else str(checkpoint)
            self.checkpoint_sha256 = None
        self.metadata = dict(metadata or {})
        self.model = model
        if hasattr(model, "to"):
            self.model = model.to(device)
        if hasattr(self.model, "eval"):
            self.model.eval()
        self.device = device
        if threads:
            torch.set_num_threads(int(threads))
        self.threads = threads
        if int(max_batch) < 1:
            raise CWVError("max_batch must be positive")
        self.max_batch = int(max_batch)
        self.support = np.asarray(
            [category_signed_level(index) for index in range(OUTCOME_CLASSES)],
            dtype=np.float64)
        self.positions = 0
        self.model_rows = 0
        self.terminal_rows = 0
        self.forward_calls = 0
        self.calls = 0
        self.wall_secs = 0.0
        self.cpu_secs = 0.0

    @property
    def ckpt8(self) -> str | None:
        return None if self.checkpoint_sha256 is None else self.checkpoint_sha256[:8]

    def identity(self) -> dict[str, Any]:
        return {"kind": "complete_world_value", "backend": self.backend,
                "checkpoint": self.checkpoint_path,
                "checkpoint_sha256": self.checkpoint_sha256,
                "ckpt8": self.ckpt8, "device": self.device,
                "threads": self.threads, "max_batch": self.max_batch}

    def score(self, positions: Sequence[Round], root_seat: int) -> np.ndarray:
        wall0, cpu0 = time.perf_counter(), time.process_time()
        n = len(positions)
        if n == 0:
            raise CWVError("evaluator received no positions")
        values = np.empty(n, dtype=np.float64)
        rows: list[ValueAfterstateTensors] = []
        pending: list[int] = []
        for index, rnd in enumerate(positions):
            if rnd.phase == "round_end":
                values[index] = float(
                    terminal_distribution(rnd, root_seat) @ self.support)
            else:
                rows.append(tensors_from_round(rnd, root_seat))
                pending.append(index)
        if rows:
            values[pending] = self.probabilities(rows) @ self.support
        self.calls += 1
        self.positions += n
        self.model_rows += len(rows)
        self.terminal_rows += n - len(rows)
        self.wall_secs += time.perf_counter() - wall0
        self.cpu_secs += time.process_time() - cpu0
        return values

    def probabilities(self, rows: Sequence[ValueAfterstateTensors]) -> np.ndarray:
        """``(len(rows), 204)`` float64 outcome distributions, chunked forward."""
        import torch

        out = np.empty((len(rows), OUTCOME_CLASSES), dtype=np.float64)
        history_free = getattr(getattr(self.model, "config", None),
                               "architecture", None) == "mlp"
        with torch.inference_mode():
            for start in range(0, len(rows), self.max_batch):
                chunk = rows[start:start + self.max_batch]
                public, history, mask, world, perspective = _stack(
                    chunk, history_free=history_free)
                if self.device != "cpu":
                    public, history, mask, world, perspective = (
                        public.to(self.device), history.to(self.device),
                        mask.to(self.device), world.to(self.device),
                        perspective.to(self.device))
                logits = self.model(public, history, mask, world, perspective)
                if tuple(logits.shape) != (len(chunk), OUTCOME_CLASSES) \
                        or not bool(torch.all(torch.isfinite(logits))):
                    raise CWVError("model logits drift")
                out[start:start + len(chunk)] = (
                    torch.softmax(logits, dim=1).double().cpu().numpy())
                self.forward_calls += 1
        if not bool(np.all(np.isfinite(out))) \
                or not bool(np.allclose(out.sum(axis=1), 1.0, rtol=0.0, atol=1e-5)):
            raise CWVError("model probability drift")
        return out


# ------------------------------------------------------ no-learning control

def _expected_level(probability: Sequence[float]) -> float:
    values = np.asarray(probability, dtype=np.float64)
    if values.shape != (OUTCOME_CLASSES,) or not np.isfinite(values).all() \
            or np.any(values < 0.0) \
            or not np.isclose(float(values.sum()), 1.0, rtol=0.0, atol=1e-6):
        raise CWVError("prior probability vector drift")
    support = np.asarray([category_signed_level(index)
                          for index in range(OUTCOME_CLASSES)], dtype=np.float64)
    return float(values @ support)


def prior_table_from(value: Mapping[str, Any]) -> tuple[dict[str, float], float]:
    """Normalise a stratified prior into ``({phase|role: level}, global)``.

    Accepted shapes: ``value_metrics.StratifiedOutcomePrior`` fields
    (``global_probability`` + ``strata_probability``); a plain map
    ``{"strata": {stratum: level | {"expected_signed_level": level}},
    "global": level}``; and #213's ``baselines.StratifiedPrior.to_dict()``
    (``cells`` of ``phase|role|points`` means, collapsed over the points bin
    by count).
    """
    if "strata_probability" in value and "global_probability" in value:
        table = {}
        for key, probability in value["strata_probability"]:
            if key not in PRIOR_STRATA:
                raise CWVError(f"prior stratum drift: {key!r}")
            table[key] = _expected_level(probability)
        return table, _expected_level(value["global_probability"])
    if "strata" in value and isinstance(value["strata"], Mapping):
        table = {}
        for key, entry in value["strata"].items():
            if key not in PRIOR_STRATA:
                raise CWVError(f"prior stratum drift: {key!r}")
            level = entry.get("expected_signed_level") \
                if isinstance(entry, Mapping) else entry
            table[key] = float(level)
        default = value.get("global", value.get("global_mean"))
        if default is None:
            if not table:
                raise CWVError("prior table is empty")
            default = float(np.mean(list(table.values())))
        return table, float(default)
    if "cells" in value:
        sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        for cell in value["cells"]:
            phase, role = str(cell["stratum"]).split("|")[:2]
            key = f"{phase}|{role}"
            if key not in PRIOR_STRATA:
                raise CWVError(f"prior stratum drift: {key!r}")
            n = int(cell.get("n", 0))
            sums[key] = sums.get(key, 0.0) + float(cell["mean"]) * n
            counts[key] = counts.get(key, 0) + n
        table = {key: sums[key] / counts[key] for key in sums if counts[key]}
        return table, float(value.get("global_mean", 0.0))
    raise CWVError("unrecognised stratified prior table")


class StratifiedPriorEvaluator:
    """The no-learning control: the stratum's prior expected level as value.

    Identical sampling and positions, no learned information: every
    non-terminal position of one decision shares its stratum, so the control
    can only separate candidates through exact terminal values.
    """

    backend = "prior"

    def __init__(self, table: Mapping[str, float], global_value: float, *,
                 source: str, checkpoint_sha256: str | None = None):
        self.table = {key: float(value) for key, value in table.items()}
        self.global_value = float(global_value)
        self.source = source
        self.checkpoint_sha256 = checkpoint_sha256
        self.support = np.asarray(
            [category_signed_level(index) for index in range(OUTCOME_CLASSES)],
            dtype=np.float64)
        self.positions = 0
        self.terminal_rows = 0
        self.calls = 0
        self.wall_secs = 0.0
        self.cpu_secs = 0.0

    @property
    def ckpt8(self) -> str | None:
        return None if self.checkpoint_sha256 is None else self.checkpoint_sha256[:8]

    def identity(self) -> dict[str, Any]:
        return {"kind": "stratified_prior", "backend": self.backend,
                "source": self.source, "checkpoint_sha256": self.checkpoint_sha256,
                "table": dict(sorted(self.table.items())),
                "global": self.global_value}

    def score(self, positions: Sequence[Round], root_seat: int) -> np.ndarray:
        wall0, cpu0 = time.perf_counter(), time.process_time()
        if not positions:
            raise CWVError("evaluator received no positions")
        values = np.empty(len(positions), dtype=np.float64)
        for index, rnd in enumerate(positions):
            if rnd.phase == "round_end":
                values[index] = float(
                    terminal_distribution(rnd, root_seat) @ self.support)
                self.terminal_rows += 1
            else:
                values[index] = self.table.get(
                    position_stratum(rnd, root_seat), self.global_value)
        self.calls += 1
        self.positions += len(positions)
        self.wall_secs += time.perf_counter() - wall0
        self.cpu_secs += time.process_time() - cpu0
        return values


def prior_table_from_metadata(metadata: Mapping[str, Any], *,
                              label: str = "checkpoint") -> tuple[dict[str, float], float]:
    """The stratified prior a checkpoint carries: ``metadata["stratified_prior"]``
    (this module's dev checkpoints) or the training build's
    ``metadata["baselines"]["stratified_prior"]`` (#213 ``cells`` form)."""
    prior = metadata.get("stratified_prior")
    if not isinstance(prior, Mapping):
        baselines = metadata.get("baselines")
        if isinstance(baselines, Mapping):
            prior = baselines.get("stratified_prior")
    if not isinstance(prior, Mapping):
        raise CWVError(
            f"{label}: metadata carries no stratified_prior; pass the "
            "training receipt (SHENGJI_CWV_RECEIPT / --receipt)")
    return prior_table_from(prior)


def prior_evaluator_for(checkpoint: str | os.PathLike[str] | None, *,
                        receipt: str | os.PathLike[str] | None = None
                        ) -> StratifiedPriorEvaluator:
    """Prior table from a receipt JSON, else from the checkpoint metadata."""
    sha = None if checkpoint is None else file_sha256(checkpoint)
    if receipt is not None:
        with Path(receipt).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for key in ("stratified_prior", "prior", "baselines"):
            if isinstance(payload.get(key), Mapping):
                inner = payload[key]
                if key == "baselines" and isinstance(
                        inner.get("stratified_prior"), Mapping):
                    inner = inner["stratified_prior"]
                payload = inner
                break
        table, default = prior_table_from(payload)
        return StratifiedPriorEvaluator(
            table, default, source=str(Path(receipt).resolve()),
            checkpoint_sha256=sha)
    if checkpoint is None:
        raise CWVError("a prior control needs a receipt or a checkpoint")
    _model, metadata, sha = load_cwv_checkpoint(checkpoint)
    table, default = prior_table_from_metadata(metadata, label=str(checkpoint))
    return StratifiedPriorEvaluator(
        table, default, source=f"checkpoint:{Path(checkpoint).resolve()}",
        checkpoint_sha256=sha)


# ------------------------------------------------- worlds and afterstates

def sample_worlds(bot: MCBot, rnd: Round, seat: int, n: int, *, mem=None
                  ) -> tuple[list[tuple[list[list[str]], list[str]]], int]:
    """``n`` canonicalised complete worlds through production's sampler.

    Uses ``bot``'s own ``_sample_hands`` (its rng and sampler counters) and
    ``_complete_determinized_hands`` (the validation + canonicalisation that
    ``MCBot._rollout`` applies), so every world is exactly what a production
    rollout would have received.  Returns ``(worlds, attempts)``; each world
    is ``(hands, buried)``.  A failed draw is skipped, never fabricated, and
    the attempt cap is production's ``SAMPLE_ATTEMPT_FACTOR``.
    """
    if mem is None:
        mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    worlds: list[tuple[list[list[str]], list[str]]] = []
    attempts = 0
    cap = n * bot.SAMPLE_ATTEMPT_FACTOR
    while len(worlds) < n and attempts < cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is None:
            continue
        hands, buried = sampled
        worlds.append((
            bot._complete_determinized_hands(rnd, seat, hands, buried=buried),
            sorted(buried)))
    return worlds, attempts


_DEFAULT_FINISHER: Any = None


def default_finisher():
    """The heuristic that finishes a trick when no policy is supplied."""
    global _DEFAULT_FINISHER
    if _DEFAULT_FINISHER is None:
        from .heuristic import HeuristicBot
        _DEFAULT_FINISHER = HeuristicBot()
    return _DEFAULT_FINISHER


def finish_current_trick(clone: Round, policy=None) -> None:
    """Let ``policy`` play until the CURRENT trick resolves, never further."""
    policy = default_finisher() if policy is None else policy
    while clone.phase == "play" and clone.trick is not None and clone.trick.plays:
        s = clone.turn
        assert s is not None
        clone.play(s, policy.decide_play(clone, s))


def afterstate(rnd: Round, seat: int, hands: Sequence[Sequence[str]],
               buried: Sequence[str], candidate: Sequence[str], *,
               finish_trick: bool = False, policy=None) -> Round:
    """Clone exactly as ``MCBot._rollout`` does, play ``candidate``, stop."""
    clone: Round = copy.copy(rnd)
    clone.hands = [list(hand) for hand in hands]
    clone.buried = list(buried)
    assert rnd.trick is not None
    clone.trick = Trick(
        leader=rnd.trick.leader,
        plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
    clone.history = list(rnd.history)
    clone.last_trick = rnd.last_trick
    clone.message = None
    clone._trusted_rollout = True
    clone._determinized_world = True
    clone.play(seat, list(candidate))
    if finish_trick:
        finish_current_trick(clone, policy)
    return clone


def positions_from_candidates(rnd: Round, seat: int,
                              candidates: Sequence[Sequence[str]],
                              worlds: Sequence[tuple[Sequence[Sequence[str]], Sequence[str]]],
                              finish_trick: bool = True, *, policy=None) -> list[Round]:
    """Every (world, candidate) afterstate for one batched ``score`` call.

    WORLD-MAJOR: position ``w * len(candidates) + k`` is candidate ``k``
    played in world ``w``, so ``values.reshape(len(worlds), len(candidates))``
    recovers the matrix.  ``worlds`` are ``(hands, buried)`` pairs as
    returned by :func:`sample_worlds`.  With ``finish_trick`` the heuristic
    (or ``policy``) completes only the current trick, so the net is not asked
    to model who wins it.
    """
    if not candidates or not worlds:
        raise CWVError("positions need at least one candidate and one world")
    return [afterstate(rnd, seat, hands, buried, candidate,
                       finish_trick=finish_trick, policy=policy)
            for hands, buried in worlds for candidate in candidates]


# ----------------------------------------------------------------------- bot

class CWVOnePlyBot(MCBot):
    """One-ply search whose only evaluator is the complete-world value net.

    Subclasses the production class for its ballot (``_candidates``), world
    sampler (``_sample_hands`` + ``_complete_determinized_hands``), declare
    and bury; only ``decide_play`` is replaced.  Production's tractor lock and
    single-candidate early returns are kept as the same decision boundary, so
    the evaluator is the one thing that differs from the production bot.
    """

    CWV_WORLDS = 100          # W complete worlds per decision
    CWV_FINISH_TRICK = True   # heuristic finishes the CURRENT trick only
    CWV_LCB_K = 0.0           # score = mean - k * se (0 = plain mean)

    def __init__(self, seed: int | None = None, *, evaluator=None):
        super().__init__(seed)
        if evaluator is None or not hasattr(evaluator, "score"):
            raise CWVError("CWVOnePlyBot needs an evaluator with score()")
        self.evaluator = evaluator
        self.positions_evaluated = 0
        self.cwv_decisions = 0
        self.batch_wall_secs = 0.0
        self.batch_cpu_secs = 0.0
        self.build_wall_secs = 0.0

    # ----------------------------------------------------------- sampling
    def sample_worlds(self, rnd: Round, seat: int, n: int, *, mem=None
                      ) -> tuple[list[tuple[list[list[str]], list[str]]], int]:
        """``n`` canonicalised complete worlds (module :func:`sample_worlds`)."""
        return sample_worlds(self, rnd, seat, n, mem=mem)

    # ---------------------------------------------------------- positions
    def _afterstate(self, rnd: Round, seat: int, hands: list[list[str]],
                    buried: list[str], candidate: list[str]) -> Round:
        """Module :func:`afterstate`, then this bot's own trick finisher."""
        clone = afterstate(rnd, seat, hands, buried, candidate, finish_trick=False)
        if self.CWV_FINISH_TRICK:
            self._finish_trick(clone)
        return clone

    def _finish_trick(self, clone: Round) -> None:
        """Let the heuristic play until the CURRENT trick resolves, no more."""
        finish_current_trick(clone, self.rollout_policy)

    @staticmethod
    def reduce_scores(matrix: np.ndarray, lcb_k: float) -> tuple[np.ndarray, np.ndarray]:
        """``(score, se)`` per candidate from a ``(worlds, candidates)`` matrix."""
        matrix = np.asarray(matrix, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[0] < 1:
            raise CWVError("score matrix must be (worlds, candidates)")
        means = matrix.mean(axis=0)
        if matrix.shape[0] >= 2:
            se = matrix.std(axis=0, ddof=1) / math.sqrt(matrix.shape[0])
        else:
            se = np.full(matrix.shape[1], math.inf if lcb_k else 0.0)
        return (means - lcb_k * se if lcb_k else means), se

    # ------------------------------------------------------------ decision
    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        assert rnd.trick is not None and rnd.ordering is not None
        self.last_eval = None
        self.last_n_worlds = 0
        self.last_decision_record = None
        self.last_override_stats = None
        self.last_alloc = None
        sampler_before = self._sampler_snapshot()
        if self.TRACTOR_LOCK and not rnd.trick.plays:
            pick = self.canonical_lead(rnd, seat)
            dec = decompose(pick, rnd.ordering)
            if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
                return pick
        candidates = self._candidates(rnd, seat)
        if len(candidates) <= 1:
            return candidates[0]
        self.search_calls += 1
        self.cwv_decisions += 1
        started = time.perf_counter()
        pre_rng_state = self.rng.getstate()
        n_worlds = int(self.CWV_WORLDS)
        if n_worlds < 1:
            raise CWVError("CWV_WORLDS must be positive")
        mem = Memory(rnd, seat, own_kitty=getattr(self, "BANKER_KITTY", True))
        worlds, attempts = self.sample_worlds(rnd, seat, n_worlds, mem=mem)
        used = len(worlds)
        self.last_n_worlds = used
        K = len(candidates)
        short = used < n_worlds
        self.last_alloc = {
            "mode": "cwv_one_ply", "attempts": attempts,
            "attempt_cap": n_worlds * self.SAMPLE_ATTEMPT_FACTOR,
            "attempt_cap_hit": short, "worlds": used,
            "rollouts": used * K, "decision_rollouts": used * K,
            "dummy_rollouts": 0, "budget": n_worlds * K, "short": short,
            "survivors": K, "survivor_indices": list(range(K)),
            "n_by_candidate": [used] * K,
        }
        means = [float("-inf")] * K
        ses = [float("inf")] * K
        scores = [float("-inf")] * K
        best = 0
        batch_wall = batch_cpu = build_wall = 0.0
        if used:
            build0 = time.perf_counter()
            positions = [self._afterstate(rnd, seat, hands, buried, cand)
                         for hands, buried in worlds for cand in candidates]
            build_wall = time.perf_counter() - build0
            wall0, cpu0 = time.perf_counter(), time.process_time()
            values = np.asarray(self.evaluator.score(positions, seat), dtype=np.float64)
            batch_wall = time.perf_counter() - wall0
            batch_cpu = time.process_time() - cpu0
            if values.shape != (used * K,):
                raise CWVError("evaluator returned a misaligned value vector")
            matrix = values.reshape(used, K)   # world-major, candidate-minor
            score, se = self.reduce_scores(matrix, self.CWV_LCB_K)
            means = matrix.mean(axis=0).tolist()
            ses = se.tolist()
            scores = score.tolist()
            best = int(np.argmax(score))
            self.positions_evaluated += used * K
            self.rollouts += used * K
            self.batch_wall_secs += batch_wall
            self.batch_cpu_secs += batch_cpu
            self.build_wall_secs += build_wall
        self.last_eval = (candidates, means)
        self.last_decision_record = {
            "schema": CWV_DECISION_SCHEMA,
            "policy": getattr(self, "policy_name", type(self).__name__),
            "policy_class": type(self).__name__,
            "code": _runtime_identity(),
            "ballot": _ballot_identity(self),
            "evaluator": self.evaluator.identity()
            if hasattr(self.evaluator, "identity") else repr(self.evaluator),
            "n_determinizations": n_worlds,
            "finish_trick": bool(self.CWV_FINISH_TRICK),
            "lcb_k": float(self.CWV_LCB_K),
            "margin": 0.0,
            "seed": self.seed,
            "rng_state": pre_rng_state,
            "candidates": [list(c) for c in candidates],
            "means": means,
            "paired_se": ses,
            "scores": scores,
            "n_by_candidate": [used] * K,
            "eligible_indices": list(range(K)),
            "raw_winner_index": best,
            "worlds": used,
            "alloc": self.last_alloc,
            "work": {
                "positions": used * K,
                "selection_budget": n_worlds * K,
                "selection_rollouts": used * K,
                "total_budget": n_worlds * K,
                "total_rollouts": used * K,
                "batch_wall_secs": batch_wall,
                "batch_cpu_secs": batch_cpu,
                "build_wall_secs": build_wall,
            },
        }
        if short:
            if used == 0:
                self.zero_world_decisions += 1
            self.short_search_decisions += 1
            return self._finish_decision(
                candidates, 0, "selection_underfilled", started, sampler_before)
        return self._finish_decision(
            candidates, best, "cwv_argmax" if best != 0 else "candidate0_best",
            started, sampler_before)


# ------------------------------------------------------------- registry glue

def policy_name(ckpt8: str, worlds: int, *, lcb: float = 0.0) -> str:
    suffix = f"-lcb{lcb:g}" if lcb else ""
    return f"mc-cwv-{ckpt8}-w{int(worlds)}{suffix}"


def control_name(worlds: int, *, lcb: float = 0.0) -> str:
    suffix = f"-lcb{lcb:g}" if lcb else ""
    return f"mc-cwv-prior-w{int(worlds)}{suffix}"


@lru_cache(maxsize=None)
def _bot_class(worlds: int, finish_trick: bool, lcb: float) -> type:
    name = f"CWVOnePly_w{worlds}" + ("" if finish_trick else "_nofinish") \
        + (f"_lcb{lcb:g}" if lcb else "")
    return type(name, (CWVOnePlyBot,), {
        "CWV_WORLDS": int(worlds), "CWV_FINISH_TRICK": bool(finish_trick),
        "CWV_LCB_K": float(lcb)})


@lru_cache(maxsize=8)
def _shared_evaluator(path: str, mtime_ns: int, size: int, threads: int | None,
                      max_batch: int) -> CompleteWorldEvaluator:
    del mtime_ns, size
    return CompleteWorldEvaluator(path, threads=threads, max_batch=max_batch)


def shared_evaluator(checkpoint: str | os.PathLike[str], *, threads: int | None = 1,
                     max_batch: int = 4096) -> CompleteWorldEvaluator:
    """One evaluator per (checkpoint file, threads) per process."""
    resolved = Path(checkpoint).resolve()
    if not resolved.is_file():
        raise CWVError(f"checkpoint not found: {resolved}")
    stat = resolved.stat()
    return _shared_evaluator(str(resolved), stat.st_mtime_ns, stat.st_size,
                             threads, int(max_batch))


def make_cwv_bot(checkpoint: str | os.PathLike[str], *, worlds: int,
                 seed: int | None = None, finish_trick: bool = True,
                 lcb: float = 0.0, prior: bool = False,
                 receipt: str | os.PathLike[str] | None = None,
                 threads: int | None = 1) -> CWVOnePlyBot:
    if prior:
        evaluator = prior_evaluator_for(checkpoint, receipt=receipt)
    else:
        evaluator = shared_evaluator(checkpoint, threads=threads)
    bot = _bot_class(int(worlds), bool(finish_trick), float(lcb))(
        seed, evaluator=evaluator)
    bot.cwv_checkpoint_sha256 = evaluator.checkpoint_sha256
    bot.cwv_ckpt8 = evaluator.ckpt8
    return bot


def cwv_registry_entries(checkpoint: str | os.PathLike[str],
                         worlds: Sequence[int], *, finish_trick: bool = True,
                         lcb: float = 0.0,
                         receipt: str | os.PathLike[str] | None = None
                         ) -> dict[str, Any]:
    """``{name: factory}`` for every W: the arm and its no-learning control.

    Names embed the checkpoint id, in the style of ``_make_vleaf``: the
    checkpoint IS the policy's identity, so a bare ``mc-cwv`` never exists.
    """
    ckpt8 = checkpoint_id(checkpoint)
    entries: dict[str, Any] = {}

    def factory(w: int, prior: bool):
        def make(**kw):
            return make_cwv_bot(
                checkpoint, worlds=w, seed=kw.get("seed"),
                finish_trick=finish_trick, lcb=lcb, prior=prior, receipt=receipt)
        return make

    for w in sorted({int(w) for w in worlds}):
        if w < 1:
            raise CWVError("worlds must be positive")
        entries[policy_name(ckpt8, w, lcb=lcb)] = factory(w, False)
        entries[control_name(w, lcb=lcb)] = factory(w, True)
    return entries


def env_registry_entries(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Registry entries described by ``SHENGJI_CWV_*`` (empty without a ckpt).

    SHENGJI_CWV_CKPT          checkpoint path (required for any entry)
    SHENGJI_CWV_WORLDS        comma list of W (default 30,100,300,1000)
    SHENGJI_CWV_FINISH_TRICK  1/0 (default 1)
    SHENGJI_CWV_LCB           k for mean - k*se (default 0 = plain mean)
    SHENGJI_CWV_RECEIPT       training receipt JSON for the prior control
    """
    env = os.environ if environ is None else environ
    checkpoint = env.get("SHENGJI_CWV_CKPT")
    if not checkpoint:
        return {}
    worlds = [int(part) for part in
              env.get("SHENGJI_CWV_WORLDS", "30,100,300,1000").split(",") if part]
    finish = env.get("SHENGJI_CWV_FINISH_TRICK", "1") not in ("0", "false", "no", "")
    lcb = float(env.get("SHENGJI_CWV_LCB", "0") or 0.0)
    receipt = env.get("SHENGJI_CWV_RECEIPT") or None
    return cwv_registry_entries(checkpoint, worlds, finish_trick=finish,
                                lcb=lcb, receipt=receipt)
